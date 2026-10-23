"""Staff-only prefix AFK commands and AFK mention handling."""

import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple

import discord
from discord.ext import commands

from config import CHANNEL_STORY_ID, COLOR_BRAND, COMMAND_PREFIX, STAFF_ROLE_ID
from database import Database
from utils import create_embed

logger = logging.getLogger("WeVibe.AFK")


def format_duration(seconds: float) -> str:
    """Format an elapsed duration for a compact Discord embed."""
    total = max(0, int(seconds))
    days, total = divmod(total, 86400)
    hours, total = divmod(total, 3600)
    minutes, secs = divmod(total, 60)
    parts = []
    for value, label in ((days, "day"), (hours, "hour"), (minutes, "minute"), (secs, "second")):
        if value:
            parts.append(f"{value} {label}{'' if value == 1 else 's'}")
    return ", ".join(parts[:2]) if parts else "less than a minute"


class AFKCog(commands.Cog, name="AFK"):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self._notice_times: Dict[Tuple[int, int], float] = {}

    def _is_staff(self, member: discord.Member) -> bool:
        return STAFF_ROLE_ID is not None and any(role.id == STAFF_ROLE_ID for role in getattr(member, "roles", []))

    @staticmethod
    def _safe_reason(reason: str) -> str:
        return discord.utils.escape_mentions(reason.strip())[:100] or "No reason given"

    async def _delete_command(self, message: discord.Message) -> None:
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass
        except Exception:
            logger.debug("Could not delete AFK command message.", exc_info=True)

    async def _short_reply(self, message: discord.Message, content: str) -> None:
        try:
            await message.channel.send(content, delete_after=5, allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            logger.debug("Could not send AFK command response.", exc_info=True)

    @commands.command(name="afk")
    async def afk_command(self, ctx: commands.Context, *, reason: str = "No reason given"):
        if not isinstance(ctx.author, discord.Member) or not self._is_staff(ctx.author):
            await self._short_reply(ctx.message, "Only staff can use this command.")
            await self._delete_command(ctx.message)
            return

        safe_reason = self._safe_reason(reason)
        await self.db.set_afk(ctx.author.id, safe_reason)
        embed = create_embed(
            title="💤 You're now AFK",
            description=f"**Reason:** {safe_reason}\n\nAnyone who mentions you will be told you're away.",
            color=COLOR_BRAND,
        )
        try:
            await ctx.send(embed=embed, delete_after=10, allowed_mentions=discord.AllowedMentions.none())
        finally:
            await self._delete_command(ctx.message)

    @commands.command(name="back")
    async def back_command(self, ctx: commands.Context):
        if not isinstance(ctx.author, discord.Member) or not self._is_staff(ctx.author):
            await self._short_reply(ctx.message, "Only staff can use this command.")
            await self._delete_command(ctx.message)
            return

        afk = await self.db.remove_afk(ctx.author.id)
        if afk:
            await self._send_welcome_back(ctx.channel, ctx.author, afk)
        await self._delete_command(ctx.message)

    async def _send_welcome_back(self, channel: discord.abc.Messageable, member: discord.Member, afk: dict) -> None:
        started = datetime.fromisoformat(afk["started_at"])
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        embed = create_embed(
            title=f"👋 Welcome back, {member.display_name}!",
            description=f"You were AFK for {format_duration((datetime.now(timezone.utc) - started).total_seconds())}.",
            color=COLOR_BRAND,
        )
        embed.add_field(name="Mentions while away", value=str(afk["mention_count"]), inline=False)
        await channel.send(embed=embed, delete_after=10, allowed_mentions=discord.AllowedMentions.none())

    async def _reply_target_author(self, message: discord.Message) -> Optional[discord.User]:
        reference = message.reference
        if not reference or not reference.message_id:
            return None
        resolved = reference.resolved
        if isinstance(resolved, discord.Message):
            return resolved.author
        try:
            replied = await message.channel.fetch_message(reference.message_id)
            return replied.author
        except Exception:
            return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        content = message.content.lstrip()
        is_afk_command = (
            content == f"{COMMAND_PREFIX}afk"
            or content.startswith(f"{COMMAND_PREFIX}afk ")
            or content == f"{COMMAND_PREFIX}back"
        )
        if isinstance(message.author, discord.Member) and not is_afk_command:
            current_afk = await self.db.get_afk(message.author.id)
            if current_afk:
                removed = await self.db.remove_afk(message.author.id)
                if removed and message.channel.id != CHANNEL_STORY_ID:
                    try:
                        await self._send_welcome_back(message.channel, message.author, removed)
                    except Exception:
                        logger.exception("Failed to send AFK welcome-back message.")

        mentioned_ids = {member.id for member in message.mentions}
        reply_author = await self._reply_target_author(message)
        if reply_author:
            mentioned_ids.add(reply_author.id)
        suppress_notice = message.channel.id == CHANNEL_STORY_ID
        now = time.monotonic()
        for user_id in mentioned_ids:
            afk = await self.db.get_afk(user_id)
            if not afk:
                continue
            await self.db.increment_afk_mentions(user_id)
            if suppress_notice:
                continue
            key = (message.channel.id, user_id)
            if now - self._notice_times.get(key, 0) < 30:
                continue
            self._notice_times[key] = now
            member = message.guild.get_member(user_id)
            display_name = member.display_name if member else f"User {user_id}"
            try:
                started = datetime.fromisoformat(afk["started_at"])
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                embed = create_embed(
                    title=f"💤 {display_name} is AFK",
                    description=f"**Reason:** {afk['reason']}",
                    color=COLOR_BRAND,
                )
                embed.add_field(name="Away since", value=f"<t:{int(started.timestamp())}:R>", inline=False)
                await message.channel.send(embed=embed, delete_after=15, allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                logger.exception("Failed to send AFK notice for user %s.", user_id)


async def setup(bot: commands.Bot):
    await bot.add_cog(AFKCog(bot, bot.db))
