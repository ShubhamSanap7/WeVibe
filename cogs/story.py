"""
WeVibe Discord Bot - One-Word Story (#one-word-story) Cog (Manual Admin Control)
Stories only run after an admin executes /story start.
When no story is active, the bot completely ignores all messages in #one-word-story.
When a story is active:
- Certified users only (unauthorized gets ephemeral-style auto-deleting notice: "You don't have access to this bot.")
- Exactly one word per message (attached punctuation allowed)
- No user can send two messages in a row
- Automatic completion between 40 and 80 words with a rich compilation embed
- Bot does NOT start a new story automatically when a story ends
- Admin commands: /story start, /story skip, /story stop
"""

import logging
import random
from typing import Optional, List, Dict, Any
import discord
from discord import app_commands
from discord.ext import commands

from database import Database
from utils import create_embed, format_story_text
from config import (
    CHANNEL_STORY_ID,
    COLOR_STORY,
    COLOR_SUCCESS,
    COLOR_ERROR,
    STORY_MIN_WORDS,
    STORY_MAX_WORDS,
    STORY_STARTERS,
    FOOTER_TEXT
)

logger = logging.getLogger("WeVibe.Story")


class StoryCog(commands.Cog, name="Story"):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db

    async def finish_story(self, story: Dict[str, Any], channel: discord.TextChannel, status: str = "completed"):
        """Finishes the story, posts the complete narrative embed, and marks it ended. Does NOT start a new one."""
        story_id = story["id"]
        await self.db.complete_story(story_id, status=status)

        # Retrieve all words
        words_data = await self.db.get_story_words(story_id)
        words_list = [w["word"] for w in words_data]
        compiled_text = format_story_text(words_list)

        # Retrieve contributors
        bot_id = self.bot.user.id if self.bot.user else 0
        contributors = await self.db.get_story_contributors(story_id, bot_id)

        contrib_lines = []
        for user_id, count in contributors[:10]:
            contrib_lines.append(f"• <@{user_id}> — **{count}** word{'s' if count != 1 else ''}")

        embed = create_embed(
            title=f"📖 Story #{story_id} — The Completed Tale",
            description=f"> *\"{compiled_text}\"*\n\n✨ *Use `/story start` to begin a new story.*",
            color=COLOR_STORY,
            footer_text=f"{FOOTER_TEXT} • Use /story start to begin a new story."
        )
        embed.add_field(name="Total Words", value=str(len(words_list)), inline=True)
        embed.add_field(name="Unique Authors", value=str(len(contributors)), inline=True)
        if contrib_lines:
            embed.add_field(name="Top Contributors", value="\n".join(contrib_lines), inline=False)

        await channel.send(embed=embed)
        logger.info("Finished Story #%s (%s words). Awaiting manual /story start.", story_id, len(words_list))

    # =========================================================================
    # MESSAGE LISTENER
    # =========================================================================
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bots and DMs
        if message.author.bot or not message.guild:
            return

        # Check if message is in the designated story channel
        if not CHANNEL_STORY_ID or message.channel.id != CHANNEL_STORY_ID:
            return

        # When NO story is active, ignore all messages: no deleting, no rules, nothing.
        story = await self.db.get_active_story(CHANNEL_STORY_ID)
        if not story:
            return

        # Helper to safely delete message and notify
        async def reject_message(reason: str):
            try:
                await message.delete()
            except discord.Forbidden:
                logger.warning("Bot lacks Manage Messages permission in #one-word-story!")
            except Exception:
                pass

            try:
                # Ephemeral-style short auto-deleting reply (5 seconds)
                await message.channel.send(
                    f"{message.author.mention} {reason}",
                    delete_after=5
                )
            except Exception:
                # DM Fallback if channel sending fails
                try:
                    await message.author.send(f"Your message in #one-word-story was removed: {reason}")
                except Exception:
                    pass

        # 1. Access Check (Certified users only)
        is_cert = await self.db.is_certified(message.author.id)
        if not is_cert:
            await reject_message("You don't have access to this bot.")
            return

        raw_content = message.content.strip()

        # 2. Check for attachments or embeds only
        if not raw_content and (message.attachments or message.embeds):
            await reject_message("Rule violation: Attachments/embeds are not allowed. Send only **one word**!")
            return

        # 3. Exactly one word check (no spaces, newlines, tabs)
        tokens = raw_content.split()
        if len(tokens) != 1 or any(c.isspace() for c in raw_content):
            await reject_message("Rule violation: You can only send **one word** at a time!")
            return

        word = tokens[0]

        # Ensure word is not too excessively long (e.g. spam)
        if len(word) > 35:
            await reject_message("Rule violation: That word is unreasonably long!")
            return

        # 4. Turn check: A user cannot send two messages in a row
        if story["last_user_id"] == message.author.id:
            await reject_message("Rule violation: You cannot send two words in a row! Wait for someone else.")
            return

        # Word is valid! Record it
        new_count = await self.db.add_story_word(story["id"], message.author.id, word)
        logger.debug("Story #%s received word #%s: '%s' from %s", story["id"], new_count, word, message.author)

        # Check if story has reached target length
        if new_count >= story["target_length"]:
            await self.finish_story(story, message.channel, status="completed")

    # =========================================================================
    # SLASH COMMANDS: /story start, /story skip, /story stop
    # =========================================================================
    story_group = app_commands.Group(
        name="story",
        description="One-word story management commands (Administrator only).",
        default_permissions=discord.Permissions(administrator=True)
    )

    @story_group.command(name="start", description="Start a new one-word story session.")
    @app_commands.default_permissions(administrator=True)
    async def story_start(self, interaction: discord.Interaction):
        """Admin command to start a new story."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need Administrator permissions to use this command.", ephemeral=True)
            return

        target_channel_id = CHANNEL_STORY_ID or interaction.channel_id
        active_story = await self.db.get_active_story(target_channel_id)
        if active_story:
            await interaction.response.send_message("A story is already running.", ephemeral=True)
            return

        channel = self.bot.get_channel(target_channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(target_channel_id)
            except Exception as e:
                await interaction.response.send_message(f"❌ Could not access channel <#{target_channel_id}>: {e}", ephemeral=True)
                return

        await interaction.response.defer(ephemeral=True)

        target_length = random.randint(STORY_MIN_WORDS, STORY_MAX_WORDS)
        starter_word = random.choice(STORY_STARTERS)
        bot_user_id = self.bot.user.id if self.bot.user else 0

        story_id = await self.db.create_story(
            channel_id=target_channel_id,
            target_length=target_length,
            starter_word=starter_word,
            bot_user_id=bot_user_id
        )

        embed = create_embed(
            title="📖 A new story has begun!",
            description=(
                f"The first word is:\n\n"
                f"# **{starter_word}**\n\n"
                f"**Rules:**\n"
                f"• Certified users only\n"
                f"• Send exactly **one word** per message (punctuation attached is allowed)\n"
                f"• You cannot post two words in a row!\n"
                f"• Story ends automatically when it reaches its mystery length."
            ),
            color=COLOR_STORY
        )

        await channel.send(embed=embed)
        await interaction.followup.send(
            f"✅ Story `#{story_id}` started in <#{target_channel_id}> with starter word **{starter_word}**.",
            ephemeral=True
        )
        logger.info("Admin %s started Story #%s (starter: '%s', target: %d words)", interaction.user, story_id, starter_word, target_length)

    @story_group.command(name="skip", description="End the active story early and post its compiled text.")
    @app_commands.default_permissions(administrator=True)
    async def story_skip(self, interaction: discord.Interaction):
        """Admin command to skip and finalize active story."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need Administrator permissions to use this command.", ephemeral=True)
            return

        target_channel_id = CHANNEL_STORY_ID or interaction.channel_id
        story = await self.db.get_active_story(target_channel_id)
        if not story:
            await interaction.response.send_message("No story is running.", ephemeral=True)
            return

        channel = self.bot.get_channel(story["channel_id"])
        if not channel:
            channel = await self.bot.fetch_channel(story["channel_id"])

        await interaction.response.defer(ephemeral=True)
        await self.finish_story(story, channel, status="skipped")
        await interaction.followup.send(f"✅ Story `#{story['id']}` was ended and summarized.", ephemeral=True)

    @story_group.command(name="stop", description="Cancel the active story without posting it.")
    @app_commands.default_permissions(administrator=True)
    async def story_stop(self, interaction: discord.Interaction):
        """Admin command to cancel active story cleanly."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need Administrator permissions to use this command.", ephemeral=True)
            return

        target_channel_id = CHANNEL_STORY_ID or interaction.channel_id
        story = await self.db.get_active_story(target_channel_id)
        if not story:
            await interaction.response.send_message("No story is running.", ephemeral=True)
            return

        await self.db.complete_story(story["id"], status="cancelled")

        channel = self.bot.get_channel(story["channel_id"])
        if not channel:
            try:
                channel = await self.bot.fetch_channel(story["channel_id"])
            except Exception:
                pass

        if channel:
            embed = create_embed(
                title="🛑 Story Stopped",
                description="The active story has been cancelled by an administrator.\n\n*Use `/story start` to begin a new story.*",
                color=COLOR_ERROR
            )
            await channel.send(embed=embed)

        await interaction.response.send_message(f"✅ Story `#{story['id']}` has been stopped.", ephemeral=True)
        logger.info("Admin %s stopped Story #%s", interaction.user, story["id"])


async def setup(bot: commands.Bot):
    db: Database = bot.db
    await bot.add_cog(StoryCog(bot, db))
