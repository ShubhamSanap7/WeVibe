"""
WeVibe Discord Bot - Main Entry Point
Handles bot initialization, asynchronous SQLite setup, cog loading,
guild slash command synchronization, and global error handling.
"""

import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from logging.handlers import RotatingFileHandler
import discord
from discord import app_commands
from discord.ext import commands

from config import (
    DISCORD_TOKEN, GUILD_ID, DATABASE_PATH, FOOTER_TEXT,
    BREAKING_CONFIG, RESEARCH_CONFIG, AI_NEWS_CONFIG, TECH_NEWS_CONFIG,
)
from database import Database
from utils import create_embed, NotCertifiedError

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            str(LOG_DIR / "wevibe.log"),
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        ),
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
        self.started_at = datetime.now(timezone.utc)

    async def setup_hook(self):
        """Asynchronous initialization executed before login."""
        logger.info("Initializing SQLite database at %s...", DATABASE_PATH)
        await self.db.init()

        # Load all feature cogs
        cogs = [
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
            name="over the WeVibe community | /help"
        )
        await self.change_presence(status=discord.Status.online, activity=activity)

    async def on_connect(self):
        logger.info("Connected to Discord gateway.")

    async def on_disconnect(self):
        logger.warning("Disconnected from Discord gateway; discord.py will reconnect automatically.")

    async def on_resumed(self):
        logger.info("Discord gateway session resumed.")

    async def on_error(self, event_method: str, *args, **kwargs):
        logger.exception("Unhandled exception in Discord event '%s'.", event_method)


bot = WeVibeBot()


@bot.tree.command(name="help", description="Show WeVibe commands and how its features work.")
async def help_command(interaction: discord.Interaction):
    embed = create_embed(
        title="📚 WeVibe Help",
        description=(
            "News is posted automatically to the configured news channels. Polls let everyone vote once "
            "and change their vote; rankings collect a Top 3 from everyone; the story accepts one word at a "
            "time while active, with no back-to-back messages."
        )
    )
    embed.add_field(
        name="Everyone's commands",
        value=(
            "`/help` — Show this guide\n"
            "`/info` — Show bot status and statistics\n"
            "Poll and ranking buttons — Vote or update your vote\n"
            "Story channel — Add one word while a story is active"
        ),
        inline=False,
    )
    embed.add_field(
        name="Certified-only commands",
        value=(
            "`/news force-post` — Run a news feed check\n"
            "`/poll post-now`, `/poll add`, `/poll list` — Manage polls\n"
            "`/rank create`, `/rank close`, `/rank list` — Manage rankings\n"
            "`/story start`, `/story skip`, `/story stop` — Manage the one-word story"
        ),
        inline=False,
    )
    embed.add_field(name="Channels", value="News channels receive feeds; the polls channel receives polls; the story channel hosts the active one-word story.", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="info", description="Show WeVibe bot information and live statistics.")
async def info_command(interaction: discord.Interaction):
    configs = [BREAKING_CONFIG, RESEARCH_CONFIG, AI_NEWS_CONFIG, TECH_NEWS_CONFIG]
    news_sources = sum(len(c.sources) for c in configs)
    news_channels = sum(c.channel_id is not None for c in configs)
    poll_bank_path = Path(__file__).parent / "data" / "polls.json"
    try:
        import json
        with poll_bank_path.open(encoding="utf-8") as poll_file:
            poll_count = len(json.load(poll_file))
    except (OSError, ValueError):
        poll_count = 0
    rankings = await bot.db.get_total_rankings_count()
    stories = await bot.db.get_completed_stories_count()
    uptime = datetime.now(timezone.utc) - bot.started_at
    uptime_text = str(uptime).split(".")[0]
    intervals = "\n".join(f"#{c.channel_key}: every {c.interval_minutes} minutes" for c in configs)
    embed = create_embed(title="ℹ️ WeVibe Info", description="A community bot for tech news, polls, rankings, and collaborative one-word stories.")
    embed.add_field(name="News", value=f"{news_sources} sources across {news_channels} configured channels\n{intervals}", inline=False)
    embed.add_field(name="Content", value=f"Polls in bank: **{poll_count}**\nRankings created: **{rankings}**\nStories completed: **{stories}**", inline=False)
    embed.add_field(name="Runtime", value=f"Uptime: **{uptime_text}**\nPython: **{sys.version.split()[0]}**\ndiscord.py: **{discord.__version__}**\nLatency: **{round(bot.latency * 1000)} ms**", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ==============================================================================
# GLOBAL SLASH COMMAND ERROR HANDLER
# ==============================================================================
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Handles unhandled slash command errors gracefully."""
    if isinstance(error, NotCertifiedError):
        msg = "You don't have permission to use this command."
    elif isinstance(error, app_commands.errors.MissingPermissions):
        msg = "You don't have permission to use this command."
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
        bot.run(DISCORD_TOKEN, reconnect=True)
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
