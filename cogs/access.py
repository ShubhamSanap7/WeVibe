"""
WeVibe Discord Bot - Access & Certification Cog
Manages certified users who are allowed to participate in interactive features (polls, rankings, stories).
"""

import logging
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

from database import Database
from utils import create_embed
from config import COLOR_BRAND, COLOR_SUCCESS, COLOR_ERROR

logger = logging.getLogger("WeVibe.Access")

UNAUTHORIZED_MESSAGE = "You don't have access to this bot."


async def verify_user_certified(db: Database, interaction: discord.Interaction) -> bool:
    """
    Checks if an interaction's user is certified.
    If not, responds with an ephemeral message and returns False.
    """
    is_cert = await db.is_certified(interaction.user.id)
    if not is_cert:
        if not interaction.response.is_done():
            await interaction.response.send_message(UNAUTHORIZED_MESSAGE, ephemeral=True)
        else:
            await interaction.followup.send(UNAUTHORIZED_MESSAGE, ephemeral=True)
        return False
    return True


class AccessCog(commands.Cog, name="Access"):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db

    # Slash command group: /certify
    certify_group = app_commands.Group(
        name="certify",
        description="Manage certified users who can interact with polls, ranking, and stories.",
        default_permissions=discord.Permissions(administrator=True)
    )

    @certify_group.command(name="add", description="Grant certified user access to interactive features.")
    @app_commands.describe(user="The user to certify")
    @app_commands.default_permissions(administrator=True)
    async def certify_add(self, interaction: discord.Interaction, user: discord.Member):
        """Admin command to certify a user."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need Administrator permissions to use this command.", ephemeral=True)
            return

        success = await self.db.add_certified_user(
            user_id=user.id,
            username=str(user),
            added_by=interaction.user.id
        )

        if success:
            embed = create_embed(
                title="✅ User Certified",
                description=f"{user.mention} (`{user.id}`) is now certified to participate in polls, rankings, and the story channel.",
                color=COLOR_SUCCESS
            )
            embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info("User %s (%s) certified by %s", user, user.id, interaction.user)
        else:
            embed = create_embed(
                title="❌ Error",
                description=f"Failed to certify {user.mention}. Please try again.",
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @certify_group.command(name="remove", description="Revoke certified user access.")
    @app_commands.describe(user="The user to uncertify")
    @app_commands.default_permissions(administrator=True)
    async def certify_remove(self, interaction: discord.Interaction, user: discord.Member):
        """Admin command to remove certification from a user."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need Administrator permissions to use this command.", ephemeral=True)
            return

        removed = await self.db.remove_certified_user(user.id)
        if removed:
            embed = create_embed(
                title="🗑️ Certification Removed",
                description=f"Revoked certification for {user.mention} (`{user.id}`).",
                color=COLOR_SUCCESS
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info("User %s (%s) uncertified by %s", user, user.id, interaction.user)
        else:
            embed = create_embed(
                title="⚠️ User Not Certified",
                description=f"{user.mention} is not in the certified users list.",
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @certify_group.command(name="list", description="List all certified users.")
    @app_commands.default_permissions(administrator=True)
    async def certify_list(self, interaction: discord.Interaction):
        """Admin command to list all certified users."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need Administrator permissions to use this command.", ephemeral=True)
            return

        users = await self.db.get_all_certified_users()
        if not users:
            embed = create_embed(
                title="📋 Certified Users",
                description="No users are currently certified. Use `/certify add @user` to certify members.",
                color=COLOR_BRAND
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        lines = []
        for u in users:
            added_at = u['added_at'][:10]
            lines.append(f"• <@{u['user_id']}> (`{u['username']}`) — Added: {added_at}")

        # Discord embeds allow up to 4096 chars in description
        chunk = "\n".join(lines[:40])
        total_count = len(users)
        embed = create_embed(
            title=f"📋 Certified Users ({total_count})",
            description=chunk,
            color=COLOR_BRAND
        )
        if total_count > 40:
            embed.set_footer(text=f"Showing 40 of {total_count} certified users.")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    db: Database = bot.db
    await bot.add_cog(AccessCog(bot, db))
