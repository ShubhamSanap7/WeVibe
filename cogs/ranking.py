"""
WeVibe Discord Bot - Interactive Top 3 Ranking Cog
Allows admins to create ranked leaderboards (2 to 10 options).
Everyone can rank their Top 3 via an ephemeral UI (3 dropdowns + submit button).
Points: 1st = 3 pts, 2nd = 2 pts, 3rd = 1 pt.
Updates live after every vote with progress bars and tie-breaking by 1st-place count.
Persistent across bot restarts.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
import discord
from discord import app_commands
from discord.ext import commands

from database import Database
from utils import create_embed, make_progress_bar, get_rank_badge, is_certified
from config import COLOR_RANK, COLOR_SUCCESS, COLOR_ERROR

logger = logging.getLogger("WeVibe.Ranking")


def calculate_rankings_score(options: List[str], votes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Calculates scores for all options:
    1st choice = 3 points, 2nd choice = 2 points, 3rd choice = 1 point.
    Ties broken by number of 1st-place votes.
    """
    stats = {}
    for idx, opt in enumerate(options):
        stats[idx] = {
            "index": idx,
            "name": opt,
            "points": 0,
            "first_place_votes": 0,
            "second_place_votes": 0,
            "third_place_votes": 0
        }

    for v in votes:
        c1 = v["first_choice"]
        c2 = v["second_choice"]
        c3 = v["third_choice"]

        if c1 in stats:
            stats[c1]["points"] += 3
            stats[c1]["first_place_votes"] += 1
        if c2 in stats:
            stats[c2]["points"] += 2
            stats[c2]["second_place_votes"] += 1
        if c3 in stats and c3 != -1:
            stats[c3]["points"] += 1
            stats[c3]["third_place_votes"] += 1

    # Sort key: points DESC, first_place_votes DESC, then alphabetically by name
    sorted_items = sorted(
        stats.values(),
        key=lambda x: (x["points"], x["first_place_votes"], -x["index"]),
        reverse=True
    )
    return sorted_items


def build_ranking_embed(
    rank_id: int,
    title: str,
    options: List[str],
    votes: List[Dict[str, Any]],
    is_closed: bool = False
) -> discord.Embed:
    """Builds the live leaderboard embed with rank badges, points, 1st-place votes, and bars."""
    sorted_stats = calculate_rankings_score(options, votes)
    total_voters = len(votes)
    max_possible_points = max([s["points"] for s in sorted_stats]) if sorted_stats and sorted_stats[0]["points"] > 0 else 1

    lines = []
    status_header = f"📊 **Leaderboard** • Total Voters: **{total_voters}**"
    if is_closed:
        winner = sorted_stats[0] if sorted_stats and sorted_stats[0]["points"] > 0 else None
        if winner:
            status_header += f"\n🏆 **WINNER: {winner['name']}** ({winner['points']} pts)"
        else:
            status_header += "\n🔒 **Ranking is closed.**"

    lines.append(status_header)
    lines.append("")

    for rank_pos, item in enumerate(sorted_stats, start=1):
        badge = get_rank_badge(rank_pos)
        points = item["points"]
        first_count = item["first_place_votes"]
        name = item["name"]

        # Bar relative to highest scoring item
        ratio = (points / max_possible_points) if max_possible_points > 0 else 0.0
        bar = make_progress_bar(ratio, length=10)

        lines.append(
            f"{badge} **{name}** — **{points}** pts `({first_count} × 1st)`\n"
            f"`{bar}`\n"
        )

    embed_title = f"🏆 Ranking: {title}" if not is_closed else f"🔒 [CLOSED] Ranking: {title}"
    embed = create_embed(
        title=embed_title,
        description="\n".join(lines),
        color=COLOR_RANK if not is_closed else 0x7F8C8D,
        footer_text=f"WeVibe Rankings • Rank #{rank_id} • 1st: 3pts | 2nd: 2pts | 3rd: 1pt"
    )
    return embed


# =============================================================================
# EPHEMERAL TOP 3 SELECTION MODAL / VIEW
# =============================================================================
class RankSubmissionView(discord.ui.View):
    def __init__(self, rank_id: int, options: List[str], leaderboard_message: discord.Message, db: Database):
        super().__init__(timeout=180)  # Ephemeral view active for 3 minutes
        self.rank_id = rank_id
        self.options = options
        self.leaderboard_message = leaderboard_message
        self.db = db

        self.first_choice: Optional[int] = None
        self.second_choice: Optional[int] = None
        self.third_choice: Optional[int] = None

        has_three_choices = len(options) >= 3

        # Dropdown 1: 1st Choice
        d1_options = [discord.SelectOption(label=f"🥇 {opt[:90]}", value=str(i)) for i, opt in enumerate(options)]
        self.select_first = discord.ui.Select(
            placeholder="🥇 Select 1st Choice (3 Points)",
            options=d1_options,
            row=0
        )
        self.select_first.callback = self.on_first_selected
        self.add_item(self.select_first)

        # Dropdown 2: 2nd Choice
        d2_options = [discord.SelectOption(label=f"🥈 {opt[:90]}", value=str(i)) for i, opt in enumerate(options)]
        self.select_second = discord.ui.Select(
            placeholder="🥈 Select 2nd Choice (2 Points)",
            options=d2_options,
            row=1
        )
        self.select_second.callback = self.on_second_selected
        self.add_item(self.select_second)

        # Dropdown 3: 3rd Choice (if at least 3 options exist)
        if has_three_choices:
            d3_options = [discord.SelectOption(label=f"🥉 {opt[:90]}", value=str(i)) for i, opt in enumerate(options)]
            self.select_third = discord.ui.Select(
                placeholder="🥉 Select 3rd Choice (1 Point)",
                options=d3_options,
                row=2
            )
            self.select_third.callback = self.on_third_selected
            self.add_item(self.select_third)

        # Submit Button
        self.submit_button = discord.ui.Button(
            label="Submit Top 3 Ranking",
            style=discord.ButtonStyle.success,
            emoji="✅",
            row=3
        )
        self.submit_button.callback = self.on_submit_clicked
        self.add_item(self.submit_button)

    async def on_first_selected(self, interaction: discord.Interaction):
        self.first_choice = int(self.select_first.values[0])
        await interaction.response.defer()

    async def on_second_selected(self, interaction: discord.Interaction):
        self.second_choice = int(self.select_second.values[0])
        await interaction.response.defer()

    async def on_third_selected(self, interaction: discord.Interaction):
        self.third_choice = int(self.select_third.values[0])
        await interaction.response.defer()

    async def on_submit_clicked(self, interaction: discord.Interaction):
        # Validation
        if self.first_choice is None:
            await interaction.response.send_message("⚠️ Please select your **1st choice**.", ephemeral=True)
            return

        if self.second_choice is None:
            await interaction.response.send_message("⚠️ Please select your **2nd choice**.", ephemeral=True)
            return

        has_three_choices = len(self.options) >= 3
        if has_three_choices and self.third_choice is None:
            await interaction.response.send_message("⚠️ Please select your **3rd choice**.", ephemeral=True)
            return

        # Check for duplicates: picking the same option twice is strictly blocked
        c3 = self.third_choice if has_three_choices else -1
        if self.first_choice == self.second_choice or (has_three_choices and (self.first_choice == c3 or self.second_choice == c3)):
            await interaction.response.send_message(
                "❌ **Duplicate Selection!** You cannot pick the same option for multiple ranks. Please select distinct choices.",
                ephemeral=True
            )
            return

        # Check if ranking is still open
        rank = await self.db.get_ranking(self.rank_id)
        if not rank or rank["is_closed"]:
            await interaction.response.send_message("This ranking has already been closed.", ephemeral=True)
            return

        # Save or update vote
        await self.db.record_rank_vote(
            rank_id=self.rank_id,
            user_id=interaction.user.id,
            first_choice=self.first_choice,
            second_choice=self.second_choice,
            third_choice=c3
        )

        # Fetch updated votes and live-update the leaderboard message
        all_votes = await self.db.get_rank_votes(self.rank_id)
        new_embed = build_ranking_embed(
            rank_id=self.rank_id,
            title=rank["title"],
            options=rank["options"],
            votes=all_votes,
            is_closed=False
        )

        try:
            await self.leaderboard_message.edit(embed=new_embed)
        except Exception:
            try:
                ch = interaction.client.get_channel(rank["channel_id"]) or await interaction.client.fetch_channel(rank["channel_id"])
                msg_obj = await ch.fetch_message(rank["message_id"])
                await msg_obj.edit(embed=new_embed)
            except Exception as e2:
                logger.error("Failed to update ranking leaderboard message: %s", e2)

        # Confirmation summary
        opt1_name = self.options[self.first_choice]
        opt2_name = self.options[self.second_choice]
        opt3_name = self.options[c3] if c3 != -1 else "N/A"

        msg = (
            f"🎉 **Your ranking has been recorded!**\n"
            f"🥇 1st (3 pts): **{opt1_name}**\n"
            f"🥈 2nd (2 pts): **{opt2_name}**\n"
        )
        if has_three_choices:
            msg += f"🥉 3rd (1 pt): **{opt3_name}**\n"
        msg += "\n*(You can submit again anytime to update your vote)*"

        # Disable submission view after submit
        for item in self.children:
            item.disabled = True
        try:
            await interaction.response.edit_message(content=msg, view=None)
        except Exception:
            await interaction.followup.send(msg, ephemeral=True)


# =============================================================================
# PERSISTENT LEADERBOARD BUTTON VIEW
# =============================================================================
class RankLeaderboardButton(discord.ui.Button):
    def __init__(self, rank_id: int):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label="🗳️ Cast / Change Your Top 3 Vote",
            custom_id=f"wevibe_rank:{rank_id}",
            emoji="⭐"
        )
        self.rank_id = rank_id

    async def callback(self, interaction: discord.Interaction):
        db: Database = interaction.client.db

        # 1. Check if ranking is closed
        rank = await db.get_ranking(self.rank_id)
        if not rank or rank["is_closed"]:
            await interaction.response.send_message("This ranking is closed.", ephemeral=True)
            return

        # 3. Present ephemeral Top 3 selection view
        submission_view = RankSubmissionView(
            rank_id=self.rank_id,
            options=rank["options"],
            leaderboard_message=interaction.message,
            db=db
        )

        await interaction.response.send_message(
            f"Select your choices for **{rank['title']}** below, then click **Submit**:",
            view=submission_view,
            ephemeral=True
        )


class RankLeaderboardView(discord.ui.View):
    def __init__(self, rank_id: int, disabled: bool = False):
        super().__init__(timeout=None)
        self.rank_id = rank_id
        btn = RankLeaderboardButton(rank_id)
        btn.disabled = disabled
        self.add_item(btn)


# =============================================================================
# RANKING COG
# =============================================================================
class RankingCog(commands.Cog, name="Ranking"):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db

    async def cog_load(self):
        # Register persistent views for active rankings on startup
        active_rankings = await self.db.get_active_rankings()
        for r in active_rankings:
            try:
                self.bot.add_view(RankLeaderboardView(rank_id=r["id"], disabled=False))
            except Exception:
                logger.exception("Failed to restore ranking view #%s", r["id"])
        logger.info("Registered %s persistent ranking views.", len(active_rankings))

    rank_group = app_commands.Group(
        name="rank",
        description="Community Top 3 ranking and leaderboard commands."
    )

    @rank_group.command(name="create", description="Create a new Top 3 ranking leaderboard.")
    @app_commands.describe(
        title="Title of the ranking (e.g. Best AI Code Editors 2026)",
        options="Comma-separated list of 2 to 10 options (e.g. Cursor, Copilot, Windsurf, Claude Code)"
    )
    @is_certified()
    async def rank_create(self, interaction: discord.Interaction, title: str, options: str):
        """Create a new ranking (certified users only)."""

        parsed_options = [opt.strip() for opt in options.split(",") if opt.strip()]

        if len(parsed_options) < 2:
            await interaction.response.send_message("❌ A ranking must have at least **2 options**.", ephemeral=True)
            return

        if len(parsed_options) > 10:
            await interaction.response.send_message("❌ A ranking can have at most **10 options**.", ephemeral=True)
            return

        # Check for duplicate options in input
        if len(parsed_options) != len(set(parsed_options)):
            await interaction.response.send_message("❌ All options must be unique.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        rank_id = await self.db.create_ranking(
            channel_id=interaction.channel_id,
            title=title.strip(),
            options=parsed_options,
            created_by=interaction.user.id
        )

        embed = build_ranking_embed(
            rank_id=rank_id,
            title=title.strip(),
            options=parsed_options,
            votes=[],
            is_closed=False
        )

        view = RankLeaderboardView(rank_id=rank_id, disabled=False)
        msg = await interaction.channel.send(embed=embed, view=view)

        await self.db.set_ranking_message_id(rank_id, msg.id)
        self.bot.add_view(view)

        await interaction.followup.send(
            f"✅ Ranking **#{rank_id}** created successfully with {len(parsed_options)} options!",
            ephemeral=True
        )
        logger.info("Created ranking #%s '%s' with options: %s", rank_id, title, parsed_options)

    @rank_group.command(name="close", description="Close an active ranking, freeze the leaderboard, and announce the winner.")
    @app_commands.describe(rank_id="ID of the ranking to close")
    @is_certified()
    async def rank_close(self, interaction: discord.Interaction, rank_id: int):
        """Close a ranking (certified users only)."""

        rank = await self.db.get_ranking(rank_id)
        if not rank:
            await interaction.response.send_message(f"❌ Ranking with ID `#{rank_id}` not found.", ephemeral=True)
            return

        if rank["is_closed"]:
            await interaction.response.send_message(f"Ranking `#{rank_id}` is already closed.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Mark closed in DB
        await self.db.close_ranking(rank_id)

        # Update message
        try:
            channel = self.bot.get_channel(rank["channel_id"])
            if not channel:
                channel = await self.bot.fetch_channel(rank["channel_id"])

            msg = await channel.fetch_message(rank["message_id"])
            votes = await self.db.get_rank_votes(rank_id)

            closed_embed = build_ranking_embed(
                rank_id=rank_id,
                title=rank["title"],
                options=rank["options"],
                votes=votes,
                is_closed=True
            )

            disabled_view = RankLeaderboardView(rank_id=rank_id, disabled=True)
            await msg.edit(embed=closed_embed, view=disabled_view)

            sorted_stats = calculate_rankings_score(rank["options"], votes)
            winner_text = sorted_stats[0]["name"] if sorted_stats and sorted_stats[0]["points"] > 0 else "No votes"

            await interaction.followup.send(
                f"✅ Ranking `#{rank_id}` is now closed! 🏆 Winner: **{winner_text}**.",
                ephemeral=True
            )
        except Exception as e:
            logger.error("Error closing ranking #%s: %s", rank_id, e)
            await interaction.followup.send(f"Ranking `#{rank_id}` closed in database, but failed to edit message: {e}", ephemeral=True)

    @rank_group.command(name="list", description="List active and recent rankings.")
    @is_certified()
    async def rank_list(self, interaction: discord.Interaction):
        """List rankings (certified users only)."""

        rankings = await self.db.get_all_rankings(limit=15)
        if not rankings:
            await interaction.response.send_message("No rankings found.", ephemeral=True)
            return

        lines = []
        for r in rankings:
            status = "🔒 Closed" if r["is_closed"] else "🟢 Active"
            lines.append(f"• ID `#{r['id']}`: **{r['title']}** [{status}] — {len(r['options'])} options")

        embed = create_embed(
            title="🏆 WeVibe Rankings List",
            description="\n".join(lines),
            color=COLOR_RANK
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    db: Database = bot.db
    await bot.add_cog(RankingCog(bot, db))
