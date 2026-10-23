"""
WeVibe Discord Bot - Random Daily Polls Cog
Manages the 100+ question poll bank, daily scheduled posting, persistent button voting,
live visual progress bars, 24-hour auto-close, and admin management commands.
"""

import json
import logging
import os
import random
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import Database
from utils import create_embed, make_progress_bar
from config import (
    CHANNEL_POLLS_ID,
    COLOR_POLL,
    COLOR_SUCCESS,
    COLOR_ERROR,
    POLL_POST_HOUR_UTC
)
from cogs.access import verify_user_certified

logger = logging.getLogger("WeVibe.Polls")

POLLS_JSON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "polls.json")


def load_poll_bank() -> List[Dict[str, Any]]:
    """Loads poll bank from data/polls.json."""
    if not os.path.exists(POLLS_JSON_PATH):
        logger.error("Polls JSON file not found at %s", POLLS_JSON_PATH)
        return []
    try:
        with open(POLLS_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Error reading polls.json: %s", e)
        return []


def save_poll_bank(data: List[Dict[str, Any]]) -> bool:
    """Saves updated poll bank to data/polls.json."""
    try:
        with open(POLLS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error("Error saving polls.json: %s", e)
        return False


def build_poll_embed(
    poll_id: int,
    question: str,
    options: List[str],
    votes: Dict[int, int],
    total_voters: int,
    expires_at_iso: str,
    is_closed: bool = False
) -> discord.Embed:
    """Constructs the poll embed with live result bars."""
    title = f"📊 Daily Poll: {question}" if not is_closed else f"📊 [CLOSED] Daily Poll: {question}"

    # Calculate percentages
    lines = []
    max_votes = -1
    winning_indices = []

    if is_closed and total_voters > 0:
        for idx in range(len(options)):
            count = votes.get(idx, 0)
            if count > max_votes:
                max_votes = count
                winning_indices = [idx]
            elif count == max_votes:
                winning_indices.append(idx)

    for idx, opt in enumerate(options):
        count = votes.get(idx, 0)
        ratio = (count / total_voters) if total_voters > 0 else 0.0
        pct = round(ratio * 100)
        bar = make_progress_bar(ratio, length=12)

        winner_prefix = "🏆 **WINNER: " if (is_closed and idx in winning_indices and max_votes > 0) else "**"
        winner_suffix = "**" if (is_closed and idx in winning_indices and max_votes > 0) else "**"

        lines.append(f"{winner_prefix}{opt}{winner_suffix}\n`{bar}` **{pct}%** ({count} vote{'s' if count != 1 else ''})\n")

    desc = "\n".join(lines)

    try:
        exp_dt = datetime.fromisoformat(expires_at_iso)
        timestamp_code = f"<t:{int(exp_dt.timestamp())}:R>"
    except Exception:
        timestamp_code = "24 hours"

    if is_closed:
        footer_sub = "This poll has ended • Thank you for voting!"
    else:
        footer_sub = f"Total Voters: {total_voters} • Closes {timestamp_code}"

    embed = create_embed(
        title=title,
        description=desc,
        color=COLOR_POLL if not is_closed else 0x95A5A6,
        footer_text=f"WeVibe Polls • {footer_sub}"
    )

    if not is_closed:
        embed.set_author(name="WeVibe Daily Community Poll", icon_url="https://cdn.discordapp.com/emojis/1041071239564861440.webp")
    return embed


class PollButton(discord.ui.Button):
    def __init__(self, poll_id: int, option_index: int, option_text: str):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=option_text[:80],
            custom_id=f"wevibe_poll:{poll_id}:{option_index}"
        )
        self.poll_id = poll_id
        self.option_index = option_index
        self.option_text = option_text

    async def callback(self, interaction: discord.Interaction):
        # 1. Access Check (Certified users only)
        db: Database = interaction.client.db
        if not await verify_user_certified(db, interaction):
            return

        # 2. Check if poll is closed
        poll = await db.get_poll(self.poll_id)
        if not poll or poll["is_closed"]:
            await interaction.response.send_message("This poll has already ended.", ephemeral=True)
            return

        # 3. Record or update vote
        await db.record_poll_vote(self.poll_id, interaction.user.id, self.option_index)

        # 4. Fetch updated stats
        votes = await db.get_poll_votes(self.poll_id)
        total_voters = await db.get_poll_total_voters(self.poll_id)

        # 5. Re-render embed
        new_embed = build_poll_embed(
            poll_id=self.poll_id,
            question=poll["question"],
            options=poll["options"],
            votes=votes,
            total_voters=total_voters,
            expires_at_iso=poll["expires_at"],
            is_closed=False
        )

        try:
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=new_embed)
            else:
                await interaction.message.edit(embed=new_embed)
        except Exception as e:
            logger.error("Failed to update poll message: %s", e)

        try:
            await interaction.followup.send(
                f"✅ You voted for: **{self.option_text}** (You can change your vote anytime before the poll closes).",
                ephemeral=True
            )
        except Exception:
            pass


class PollView(discord.ui.View):
    def __init__(self, poll_id: int, options: List[str], disabled: bool = False):
        super().__init__(timeout=None)
        self.poll_id = poll_id
        for idx, opt in enumerate(options):
            btn = PollButton(poll_id=poll_id, option_index=idx, option_text=opt)
            btn.disabled = disabled
            self.add_item(btn)


class PollsCog(commands.Cog, name="Polls"):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self.daily_poll_task.start()
        self.check_expired_polls.start()

    async def cog_load(self):
        # Re-register all active polls to ensure buttons persist after bot restarts
        active_polls = await self.db.get_active_polls()
        for p in active_polls:
            self.bot.add_view(PollView(poll_id=p["id"], options=p["options"], disabled=False))
        logger.info("Registered %s persistent poll views.", len(active_polls))

    async def cog_unload(self):
        self.daily_poll_task.cancel()
        self.check_expired_polls.cancel()

    # =========================================================================
    # CORE DISPATCHER
    # =========================================================================
    async def post_poll(self, question: str, options: List[str], channel_id: Optional[int] = None) -> Optional[int]:
        """Creates a poll in DB, sends the message, attaches persistent view, and returns poll_id."""
        target_channel_id = channel_id or CHANNEL_POLLS_ID
        if not target_channel_id:
            logger.warning("No CHANNEL_POLLS configured.")
            return None

        channel = self.bot.get_channel(target_channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(target_channel_id)
            except Exception as e:
                logger.error("Could not fetch poll channel %s: %s", target_channel_id, e)
                return None

        # Expiration in 24 hours
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=24)

        # Insert into DB
        poll_id = await self.db.create_poll(
            channel_id=target_channel_id,
            question=question,
            options=options,
            expires_at=expires_at
        )

        view = PollView(poll_id=poll_id, options=options)
        embed = build_poll_embed(
            poll_id=poll_id,
            question=question,
            options=options,
            votes={},
            total_voters=0,
            expires_at_iso=expires_at.isoformat(),
            is_closed=False
        )

        msg = await channel.send(embed=embed, view=view)
        await self.db.set_poll_message_id(poll_id, msg.id)
        self.bot.add_view(view)
        logger.info("Posted new poll #%s: '%s' in #%s", poll_id, question, channel.name)
        return poll_id

    # =========================================================================
    # SCHEDULED TASKS
    # =========================================================================
    @tasks.loop(minutes=30)
    async def daily_poll_task(self):
        """Checks if it is time to post the daily poll (POLL_POST_HOUR_UTC)."""
        now = datetime.now(timezone.utc)
        # Check if current hour matches configured hour
        if now.hour != POLL_POST_HOUR_UTC:
            return

        # Check if we already posted a poll today
        today_str = now.strftime("%Y-%m-%d")
        metadata_key = f"daily_poll_posted_{today_str}"
        # We can check if metadata exists in bot_metadata
        async with self.bot.db_pool_lock if hasattr(self.bot, 'db_pool_lock') else asyncio.Lock():
            pass

        # Check bank
        bank = load_poll_bank()
        if not bank:
            return

        used_ids = await self.db.get_all_used_poll_ids()
        available = [p for p in bank if p["id"] not in used_ids]

        # Reset if bank used up
        if not available:
            logger.info("All polls in bank have been used! Resetting used polls pool.")
            await self.db.clear_used_polls()
            available = bank

        chosen = random.choice(available)
        poll_id = await self.post_poll(chosen["question"], chosen["options"])
        if poll_id:
            await self.db.mark_poll_used(chosen["id"])

    @tasks.loop(minutes=2)
    async def check_expired_polls(self):
        """Finds expired open polls, closes them, and updates message to show final results."""
        expired = await self.db.get_expired_open_polls()
        for p in expired:
            try:
                channel = self.bot.get_channel(p["channel_id"])
                if not channel:
                    channel = await self.bot.fetch_channel(p["channel_id"])

                msg = await channel.fetch_message(p["message_id"])

                votes = await self.db.get_poll_votes(p["id"])
                total_voters = await self.db.get_poll_total_voters(p["id"])

                closed_embed = build_poll_embed(
                    poll_id=p["id"],
                    question=p["question"],
                    options=p["options"],
                    votes=votes,
                    total_voters=total_voters,
                    expires_at_iso=p["expires_at"],
                    is_closed=True
                )

                disabled_view = PollView(poll_id=p["id"], options=p["options"], disabled=True)
                await msg.edit(embed=closed_embed, view=disabled_view)
                await self.db.close_poll(p["id"])
                logger.info("Closed expired poll #%s ('%s')", p["id"], p["question"])
            except Exception as e:
                logger.error("Failed to close expired poll #%s: %s", p["id"], e)
                # Ensure it doesn't get stuck in open state if message was deleted
                await self.db.close_poll(p["id"])

    @daily_poll_task.before_loop
    @check_expired_polls.before_loop
    async def before_poll_tasks(self):
        await self.bot.wait_until_ready()

    # =========================================================================
    # SLASH COMMANDS: /poll add, /poll post-now, /poll list
    # =========================================================================
    poll_group = app_commands.Group(
        name="poll",
        description="Daily community poll management commands.",
        default_permissions=discord.Permissions(administrator=True)
    )

    @poll_group.command(name="post-now", description="Immediately post a poll from the bank or by ID.")
    @app_commands.describe(poll_id="Optional specific poll ID from the bank to post")
    @app_commands.default_permissions(administrator=True)
    async def poll_post_now(self, interaction: discord.Interaction, poll_id: Optional[int] = None):
        """Admin command to post a poll immediately."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need Administrator permissions to use this command.", ephemeral=True)
            return

        bank = load_poll_bank()
        if not bank:
            await interaction.response.send_message("Poll bank is empty.", ephemeral=True)
            return

        target_poll = None
        if poll_id is not None:
            for p in bank:
                if p["id"] == poll_id:
                    target_poll = p
                    break
            if not target_poll:
                await interaction.response.send_message(f"Poll with ID `{poll_id}` not found in bank.", ephemeral=True)
                return
        else:
            used_ids = await self.db.get_all_used_poll_ids()
            available = [p for p in bank if p["id"] not in used_ids]
            if not available:
                await self.db.clear_used_polls()
                available = bank
            target_poll = random.choice(available)

        await interaction.response.defer(ephemeral=True)
        created_id = await self.post_poll(target_poll["question"], target_poll["options"])
        if created_id:
            await self.db.mark_poll_used(target_poll["id"])
            await interaction.followup.send(
                f"✅ Poll posted successfully in <#{CHANNEL_POLLS_ID}>!\n**Question:** {target_poll['question']}",
                ephemeral=True
            )
        else:
            await interaction.followup.send("❌ Failed to post poll. Check channel permissions and configuration.", ephemeral=True)

    @poll_group.command(name="add", description="Add a new poll question to the poll bank.")
    @app_commands.describe(
        question="The question for the poll",
        option1="First option",
        option2="Second option",
        option3="Third option (optional)",
        option4="Fourth option (optional)",
        topic="Topic tag (e.g. AI, Dev, Career)"
    )
    @app_commands.default_permissions(administrator=True)
    async def poll_add(
        self,
        interaction: discord.Interaction,
        question: str,
        option1: str,
        option2: str,
        option3: Optional[str] = None,
        option4: Optional[str] = None,
        topic: Optional[str] = "Community"
    ):
        """Admin command to add a custom poll to the bank."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need Administrator permissions to use this command.", ephemeral=True)
            return

        options = [option1.strip(), option2.strip()]
        if option3 and option3.strip():
            options.append(option3.strip())
        if option4 and option4.strip():
            options.append(option4.strip())

        bank = load_poll_bank()
        new_id = (max([p["id"] for p in bank]) + 1) if bank else 1

        new_entry = {
            "id": new_id,
            "topic": topic or "Community",
            "question": question.strip(),
            "options": options
        }
        bank.append(new_entry)

        if save_poll_bank(bank):
            embed = create_embed(
                title="✅ Poll Added to Bank",
                description=f"**ID:** `#{new_id}`\n**Topic:** `{new_entry['topic']}`\n**Question:** {new_entry['question']}\n**Options:**\n" + "\n".join([f"• {o}" for o in options]),
                color=COLOR_SUCCESS
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("❌ Failed to save poll to bank.", ephemeral=True)

    @poll_group.command(name="list", description="List active polls and poll bank statistics.")
    @app_commands.default_permissions(administrator=True)
    async def poll_list(self, interaction: discord.Interaction):
        """Admin command to list poll statuses."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need Administrator permissions to use this command.", ephemeral=True)
            return

        bank = load_poll_bank()
        used_ids = await self.db.get_all_used_poll_ids()
        active = await self.db.get_active_polls()

        desc = [
            f"**Total Questions in Bank:** `{len(bank)}`",
            f"**Used Bank Polls:** `{len(used_ids)}`",
            f"**Remaining Unused:** `{len(bank) - len(used_ids)}`",
            f"**Currently Active Polls:** `{len(active)}`\n"
        ]

        if active:
            desc.append("**Active Polls:**")
            for p in active:
                desc.append(f"• ID `#{p['id']}`: {p['question']} (Ends: `{p['expires_at'][:19]}` UTC)")

        embed = create_embed(
            title="📊 WeVibe Poll Status",
            description="\n".join(desc),
            color=COLOR_POLL
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    db: Database = bot.db
    await bot.add_cog(PollsCog(bot, db))
