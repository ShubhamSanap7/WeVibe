"""
WeVibe Discord Bot - Main Entry Point
Handles bot initialization, asynchronous SQLite setup, cog loading,
guild slash command synchronization, and global error handling.
"""

import asyncio
import logging
import sys
import discord
from discord import app_commands
from discord.ext import commands

from config import DISCORD_TOKEN, GUILD_ID, DATABASE_PATH, FOOTER_TEXT
from database import Database

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("WeVibe.Main")


class WeVibeBot(commands.Bot):
    def __init__(self):
        # Configure required Gateway Intents
        intents = discord.Intents.default()
        intents.message_content = True  # Required for #one-word-story
        intents.members = True          # Helpful for user resolution
        intents.guilds = True

        super().__init__(
            command_prefix="!",  # Slash commands are primary; prefix kept for compatibility
            intents=intents,
            help_command=None
        )

        self.db = Database(DATABASE_PATH)

    async def setup_hook(self):
        """Asynchronous initialization executed before login."""
        logger.info("Initializing SQLite database at %s...", DATABASE_PATH)
        await self.db.init()

        # Load all feature cogs
        cogs = [
            "cogs.access",
            "cogs.news",
            "cogs.polls",
            "cogs.ranking",
            "cogs.story"
        ]

        for cog in cogs:
            try:
                await self.load_extension(cog)
                logger.info("Loaded cog: %s", cog)
            except Exception as e:
                logger.critical("Failed to load cog %s: %s", cog, e, exc_info=True)

        # Synchronize slash commands (instant sync to GUILD_ID if configured)
        try:
            if GUILD_ID:
                guild_obj = discord.Object(id=GUILD_ID)
                self.tree.copy_global_to(guild=guild_obj)
                synced = await self.tree.sync(guild=guild_obj)
                logger.info("⚡ Synced %d slash commands directly to Guild ID: %d", len(synced), GUILD_ID)
            else:
                synced = await self.tree.sync()
                logger.info("⚡ Synced %d global slash commands (may take up to an hour to propagate globally).", len(synced))
        except Exception as e:
            logger.error("Failed to sync application slash commands: %s", e)

    async def on_ready(self):
        """Triggered once the bot is connected and ready."""
        logger.info("=" * 60)
        logger.info("WeVibe Bot is LIVE!")
        logger.info("Logged in as: %s (ID: %s)", self.user, self.user.id)
        logger.info("Connected to %d guild(s)", len(self.guilds))
        logger.info("=" * 60)

        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="over WeVibe community | /certify, /news, /poll, /rank, /story"
        )
        await self.change_presence(status=discord.Status.online, activity=activity)


bot = WeVibeBot()


# ==============================================================================
# GLOBAL SLASH COMMAND ERROR HANDLER
# ==============================================================================
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Handles unhandled slash command errors gracefully."""
    if isinstance(error, app_commands.errors.MissingPermissions):
        msg = "❌ You don't have permission to use this command."
    elif isinstance(error, app_commands.errors.BotMissingPermissions):
        msg = f"❌ The bot is missing required permissions: {', '.join(error.missing_permissions)}"
    elif isinstance(error, app_commands.errors.CommandOnCooldown):
        msg = f"⏳ Command on cooldown. Try again in {error.retry_after:.1f}s."
    else:
        logger.error("Unhandled slash command error in %s: %s", interaction.command.name if interaction.command else "Unknown", error, exc_info=error)
        msg = "⚠️ An unexpected error occurred while processing this command."

    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)
    except Exception:
        pass


def main():
    if not DISCORD_TOKEN or DISCORD_TOKEN == "your_bot_token_here":
        print("\n" + "!" * 70)
        print("ERROR: DISCORD_TOKEN is missing or not set!")
        print("Please copy .env.example to .env and configure your bot token:")
        print("  cp .env.example .env")
        print("  (Then edit .env and insert your actual DISCORD_TOKEN)")
        print("!" * 70 + "\n")
        sys.exit(1)

    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        print("\n" + "!" * 70)
        print("ERROR: Invalid Discord Bot Token!")
        print("Please verify the DISCORD_TOKEN in your .env file.")
        print("!" * 70 + "\n")
        sys.exit(1)
    except Exception as e:
        logger.critical("Fatal error starting WeVibe Bot: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
