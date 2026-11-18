"""Prefix moderation commands grouped under ``?w``."""

from datetime import timedelta
import logging
import re
from typing import Optional

import discord
from discord.ext import commands

logger = logging.getLogger("WeVibe.Moderation")


def parse_duration(value: str) -> Optional[timedelta]:
    """Parse a timeout duration such as 10m, 2h, or 1d."""
    match = re.fullmatch(r"(\d+)\s*([smhd])", value.lower())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    if seconds < 1 or seconds > 28 * 86400:
        return None
    return timedelta(seconds=seconds)


class ModerationCog(commands.Cog, name="Moderation"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.group(name="w", invoke_without_command=True)
    @commands.guild_only()
    async def moderation_group(self, ctx: commands.Context):
        """Moderation commands: ?w kick, ?w ban, and ?w mute."""
        await ctx.send(
            "Usage: `?w kick @member [reason]`, `?w ban @member [reason]`, "
            "or `?w mute @member [duration] [reason]`.",
            delete_after=10,
        )

    @moderation_group.command(name="kick")
    @commands.has_guild_permissions(kick_members=True)
    @commands.bot_has_guild_permissions(kick_members=True)
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason given"):
        """Kick a member, including bot members, when Discord hierarchy allows it."""
        if not await self._can_act_on(ctx, member):
            return
        try:
            await member.kick(reason=f"{ctx.author}: {reason[:400]}")
            await ctx.send(f"✅ Kicked **{member}**. Reason: {reason[:400]}", delete_after=10)
        except discord.Forbidden:
            await ctx.send("❌ I cannot kick that member because of role hierarchy or permissions.", delete_after=10)
        except discord.HTTPException:
            logger.exception("Kick request failed for %s", member.id)
            await ctx.send("❌ Discord rejected the kick request.", delete_after=10)

    @moderation_group.command(name="ban")
    @commands.has_guild_permissions(ban_members=True)
    @commands.bot_has_guild_permissions(ban_members=True)
    async def ban(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason given"):
        """Ban a member, including bot members, when Discord hierarchy allows it."""
        if not await self._can_act_on(ctx, member):
            return
        try:
            await member.ban(reason=f"{ctx.author}: {reason[:400]}", delete_message_seconds=0)
            await ctx.send(f"✅ Banned **{member}**. Reason: {reason[:400]}", delete_after=10)
        except discord.Forbidden:
            await ctx.send("❌ I cannot ban that member because of role hierarchy or permissions.", delete_after=10)
        except discord.HTTPException:
            logger.exception("Ban request failed for %s", member.id)
            await ctx.send("❌ Discord rejected the ban request.", delete_after=10)

    @moderation_group.command(name="mute", aliases=("timeout",))
    @commands.has_guild_permissions(moderate_members=True)
    @commands.bot_has_guild_permissions(moderate_members=True)
    async def mute(
        self,
        ctx: commands.Context,
        member: discord.Member,
        duration: str = "10m",
        *,
        reason: str = "No reason given",
    ):
        """Timeout a member for up to 28 days; bots may be targeted too."""
        timeout = parse_duration(duration)
        if timeout is None:
            await ctx.send("❌ Duration must be between 1 second and 28 days, e.g. `10m`, `2h`, or `1d`.", delete_after=10)
            return
        if not await self._can_act_on(ctx, member):
            return
        try:
            await member.timeout(timeout, reason=f"{ctx.author}: {reason[:400]}")
            await ctx.send(f"✅ Timed out **{member}** for `{duration}`. Reason: {reason[:400]}", delete_after=10)
        except discord.Forbidden:
            await ctx.send("❌ I cannot mute that member because of role hierarchy or permissions.", delete_after=10)
        except discord.HTTPException:
            logger.exception("Timeout request failed for %s", member.id)
            await ctx.send("❌ Discord rejected the mute request.", delete_after=10)

    async def _can_act_on(self, ctx: commands.Context, member: discord.Member) -> bool:
        actor = ctx.author
        me = ctx.guild.me if ctx.guild else None
        if member == actor:
            await ctx.send("❌ You cannot moderate yourself.", delete_after=10)
            return False
        if member == me:
            await ctx.send("❌ You cannot moderate me.", delete_after=10)
            return False
        bot_member = ctx.guild.me if ctx.guild else None
        if bot_member is None:
            await ctx.send("❌ I cannot resolve my server member permissions.", delete_after=10)
            return False
        if member.top_role >= bot_member.top_role:
            await ctx.send("❌ That member's role is higher than or equal to mine.", delete_after=10)
            return False
        if isinstance(actor, discord.Member) and member.top_role >= actor.top_role and not actor.guild_permissions.administrator:
            await ctx.send("❌ You cannot moderate a member with an equal or higher role.", delete_after=10)
            return False
        return True

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if ctx.command is None or not ctx.command.qualified_name.startswith("w"):
            return
        if isinstance(error, commands.MissingPermissions):
            message = "❌ You need the required Discord moderation permission for that command."
        elif isinstance(error, commands.BotMissingPermissions):
            message = "❌ I am missing the Discord permission required for that command."
        elif isinstance(error, commands.MemberNotFound):
            message = "❌ I could not find that server member. Mention them or provide their user ID."
        elif isinstance(error, commands.MissingRequiredArgument):
            message = "❌ Please provide a member. Example: `?w kick @member reason`."
        elif isinstance(error, commands.CommandNotFound):
            return
        else:
            logger.exception("Moderation command failed", exc_info=error)
            message = "❌ That moderation command failed."
        try:
            await ctx.send(message, delete_after=10)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationCog(bot))
