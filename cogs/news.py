"""
WeVibe Discord Bot - News Aggregation & Auto-Posting System
Monitors RSS feeds across 4 channels (#breaking-updates, #research-and-papers, #ai-news, #news)
with cross-channel deduplication, first-run rate limiting, robust error handling, and rich embeds.
"""

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
import feedparser

from database import Database
from utils import create_embed, clean_html_summary, is_certified
from config import (
    BREAKING_CONFIG,
    RESEARCH_CONFIG,
    AI_NEWS_CONFIG,
    TECH_NEWS_CONFIG,
    BREAKING_KEYWORDS,
    AI_KEYWORDS,
    CATEGORY_COLORS,
    FIRST_RUN_MAX_PER_FEED,
    ChannelNewsConfig,
    FeedSource,
    FOOTER_TEXT
)

logger = logging.getLogger("WeVibe.News")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WeVibeNewsBot/1.0 (+https://discord.gg/wevibe)"
}


def hash_url(url: str) -> str:
    """Generates a stable SHA-256 hash of a URL."""
    # Strip tracking parameters
    clean_url = re.sub(r"[\?&]utm_[^&]+", "", url.strip().lower())
    return hashlib.sha256(clean_url.encode("utf-8")).hexdigest()


class NewsCog(commands.Cog, name="News"):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self.session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Lock()

        # Start scheduled loops
        self.breaking_task.start()
        self.ai_news_task.start()
        self.tech_news_task.start()
        self.research_task.start()

    async def cog_load(self):
        timeout = aiohttp.ClientTimeout(total=20)
        self.session = aiohttp.ClientSession(headers=HEADERS, timeout=timeout)

    async def cog_unload(self):
        self.breaking_task.cancel()
        self.ai_news_task.cancel()
        self.tech_news_task.cancel()
        self.research_task.cancel()
        if self.session and not self.session.closed:
            await self.session.close()

    # =========================================================================
    # FEED FETCHING & PARSING
    # =========================================================================
    async def fetch_feed_entries(self, source: FeedSource) -> List[Dict[str, Any]]:
        """Safely fetches and parses an RSS feed without crashing on failure."""
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=20)
            self.session = aiohttp.ClientSession(headers=HEADERS, timeout=timeout)

        try:
            async with self.session.get(source.url) as response:
                if response.status != 200:
                    logger.warning("Feed %s returned HTTP %s", source.name, response.status)
                    return []
                text = await response.text()
                parsed = feedparser.parse(text)
                if parsed.bozo and not parsed.entries:
                    logger.warning("Feed %s encountered parsing issue: %s", source.name, parsed.bozo_exception)
                return parsed.entries
        except asyncio.TimeoutError:
            logger.warning("Timeout fetching feed %s (%s)", source.name, source.url)
            return []
        except Exception as e:
            logger.error("Error fetching feed %s: %s", source.name, e)
            return []

    def extract_thumbnail(self, entry: Any) -> Optional[str]:
        """Attempts to extract a high-quality thumbnail image URL from an entry."""
        # 1. Check media_content
        media = entry.get("media_content", [])
        if media and isinstance(media, list):
            for m in media:
                url = m.get("url")
                if url and (url.endswith(".jpg") or url.endswith(".png") or url.endswith(".webp")):
                    return url

        # 2. Check media_thumbnail
        thumbs = entry.get("media_thumbnail", [])
        if thumbs and isinstance(thumbs, list):
            for t in thumbs:
                url = t.get("url")
                if url:
                    return url

        # 3. Check enclosures
        enclosures = entry.get("enclosures", [])
        if enclosures and isinstance(enclosures, list):
            for enc in enclosures:
                url = enc.get("href")
                enc_type = enc.get("type", "")
                if url and "image" in enc_type:
                    return url

        # 4. Check embedded image tag in summary or content
        html_block = entry.get("summary", "")
        if not html_block and entry.get("content"):
            html_block = entry["content"][0].get("value", "")

        if html_block:
            img_match = re.search(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', html_block)
            if img_match:
                img_url = img_match.group(1)
                # Filter out tracking pixels
                if not any(px in img_url for px in ["tracking", "feedburner", "1x1", "pixel"]):
                    return img_url

        return None

    def determine_tech_category(self, title: str, summary: str, default: str) -> str:
        """Determines category for general tech channel based on keywords."""
        content = (title + " " + summary).lower()
        if any(w in content for w in ["breach", "cve", "ransomware", "malware", "vulnerability", "zero-day", "hacker"]):
            return "Cybersecurity"
        if any(w in content for w in ["ai", "llm", "gpt", "model", "neural", "deep learning", "claude", "gemini"]):
            return "AI"
        if any(w in content for w in ["github", "git", "release", "rust", "python", "javascript", "typescript", "compiler", "linux", "kernel", "docker"]):
            return "Dev / Coding"
        if any(w in content for w in ["launches", "unveils", "announces", "introduces", "debuts", "reveals"]):
            return "Launch"
        if any(w in content for w in ["gpu", "geforce", "radeon", "steam", "rtx", "playstation", "xbox", "nintendo"]):
            return "Gaming Tech"
        return default

    # =========================================================================
    # CORE POSTING LOGIC
    # =========================================================================
    async def process_channel_feed(self, config: ChannelNewsConfig) -> int:
        """Processes and posts news items for a specific channel configuration."""
        if not config.channel_id:
            logger.debug("Channel ID for %s not configured. Skipping.", config.channel_key)
            return 0

        channel = self.bot.get_channel(config.channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(config.channel_id)
            except Exception as e:
                logger.warning("Could not resolve channel ID %s for %s: %s", config.channel_id, config.channel_key, e)
                return 0

        # Check total news posted count to detect first run
        total_posted = await self.db.get_posted_news_count()
        is_first_run = total_posted == 0

        posted_in_this_cycle = 0

        # Check daily cap for breaking news
        if config.channel_key == "breaking" and config.daily_post_cap:
            today_breaking_count = await self.db.get_breaking_posts_today_count()
            if today_breaking_count >= config.daily_post_cap:
                logger.info("Daily breaking news cap reached (%s/%s). Skipping.", today_breaking_count, config.daily_post_cap)
                return 0

        # Collect candidate items across sources
        candidates: List[Dict[str, Any]] = []

        for source in config.sources:
            try:
                entries = await self.fetch_feed_entries(source)
                if not entries:
                    continue

                # On first run, limit entries per feed
                if is_first_run:
                    entries = entries[:FIRST_RUN_MAX_PER_FEED]

                for entry in entries:
                    link = entry.get("link", "").strip()
                    title = entry.get("title", "").strip()
                    if not link or not title:
                        continue

                    url_h = hash_url(link)
                    if await self.db.is_news_posted(url_h):
                        continue

                    # Filter: Breaking News
                    if config.channel_key == "breaking":
                        is_top_hn = False
                        if source.is_hn:
                            # Feed URL already includes points=300
                            is_top_hn = True

                        title_lower = title.lower()
                        matches_keywords = any(kw.lower() in title_lower for kw in BREAKING_KEYWORDS)

                        if not (is_top_hn or matches_keywords):
                            continue

                    # Filter: AI News (Must be strictly AI)
                    elif config.channel_key == "ai-news":
                        text_to_check = (title + " " + entry.get("summary", "")).lower()
                        # If feed is already dedicated AI (OpenAI, Anthropic), pass through; otherwise check keywords
                        if source.default_category == "AI":
                            matches_ai = True
                        else:
                            matches_ai = any(kw.lower() in text_to_check for kw in AI_KEYWORDS)

                        if not matches_ai:
                            continue

                    candidates.append({
                        "entry": entry,
                        "source": source,
                        "url_hash": url_h,
                        "link": link,
                        "title": title
                    })
            except Exception as e:
                logger.error("Unexpected error in feed loop for source %s: %s", source.name, e)
                continue

        # Sort candidates or limit to max_posts_per_cycle
        limit = config.max_posts_per_cycle
        if config.channel_key == "breaking" and config.daily_post_cap:
            remaining_today = config.daily_post_cap - (await self.db.get_breaking_posts_today_count())
            limit = min(limit, remaining_today)

        for item in candidates[:limit]:
            entry = item["entry"]
            source = item["source"]
            link = item["link"]
            title = item["title"]
            url_h = item["url_hash"]

            # Double check deduplication before posting
            if await self.db.is_news_posted(url_h):
                continue

            summary = clean_html_summary(entry.get("summary", "") or entry.get("description", ""), max_chars=250)
            thumbnail = self.extract_thumbnail(entry)

            # Category & Color
            category = source.default_category
            color = config.color
            if config.channel_key == "news":
                category = self.determine_tech_category(title, summary, source.default_category)
                color = CATEGORY_COLORS.get(category, config.color)
            elif config.channel_key == "research":
                category = "Paper"

            embed = create_embed(
                title=title,
                description=summary,
                color=color,
                url=link,
                thumbnail_url=thumbnail,
                footer_text=f"WeVibe • {source.name} | [{category}]"
            )

            # Add source and link button / fields
            embed.add_field(name="Category", value=f"`{category}`", inline=True)
            embed.add_field(name="Source", value=source.name, inline=True)
            embed.add_field(name="Link", value=f"[Read Full Article]({link})", inline=True)

            try:
                await channel.send(embed=embed)
                await self.db.mark_news_posted(url_h, link, title, config.channel_key)
                if config.channel_key == "breaking":
                    await self.db.record_breaking_post(url_h)
                posted_in_this_cycle += 1
                logger.info("Posted news item [%s]: %s -> #%s", category, title, channel.name)
                # Small pause between messages to be polite to Discord rate limits
                await asyncio.sleep(1.5)
            except discord.Forbidden:
                logger.error("Missing permissions to send message in channel #%s (%s)", channel.name, channel.id)
                break
            except Exception as e:
                logger.error("Failed to post news item: %s", e)

        return posted_in_this_cycle

    # =========================================================================
    # SCHEDULED TASKS
    # =========================================================================
    @tasks.loop(minutes=20)
    async def breaking_task(self):
        """Monitors breaking news feeds every 20 minutes."""
        async with self._lock:
            try:
                await self.process_channel_feed(BREAKING_CONFIG)
            except Exception as e:
                logger.error("Error in breaking_task: %s", e)

    @tasks.loop(hours=1)
    async def ai_news_task(self):
        """Monitors AI news feeds every hour."""
        async with self._lock:
            try:
                await self.process_channel_feed(AI_NEWS_CONFIG)
            except Exception as e:
                logger.error("Error in ai_news_task: %s", e)

    @tasks.loop(hours=2)
    async def tech_news_task(self):
        """Monitors general tech feeds every 2 hours."""
        async with self._lock:
            try:
                await self.process_channel_feed(TECH_NEWS_CONFIG)
            except Exception as e:
                logger.error("Error in tech_news_task: %s", e)

    @tasks.loop(hours=6)
    async def research_task(self):
        """Monitors research papers and blogs every 6 hours."""
        async with self._lock:
            try:
                await self.process_channel_feed(RESEARCH_CONFIG)
            except Exception as e:
                logger.error("Error in research_task: %s", e)

    async def _restart_loop(self, loop: tasks.Loop, name: str):
        if loop.is_being_cancelled() or self.bot.is_closed():
            return
        logger.warning("Scheduled loop %s stopped; restarting it in 5 seconds.", name)
        await asyncio.sleep(5)
        if not loop.is_being_cancelled() and not loop.is_running() and not self.bot.is_closed():
            try:
                loop.start()
                logger.info("Restarted scheduled loop %s.", name)
            except Exception:
                logger.exception("Failed to restart scheduled loop %s.", name)

    @breaking_task.error
    async def breaking_task_error(self, error: Exception):
        logger.exception("Unhandled error in breaking_task: %s", error)

    @ai_news_task.error
    async def ai_news_task_error(self, error: Exception):
        logger.exception("Unhandled error in ai_news_task: %s", error)

    @tech_news_task.error
    async def tech_news_task_error(self, error: Exception):
        logger.exception("Unhandled error in tech_news_task: %s", error)

    @research_task.error
    async def research_task_error(self, error: Exception):
        logger.exception("Unhandled error in research_task: %s", error)

    @breaking_task.after_loop
    async def breaking_task_after_loop(self):
        asyncio.create_task(self._restart_loop(self.breaking_task, "breaking_task"))

    @ai_news_task.after_loop
    async def ai_news_task_after_loop(self):
        asyncio.create_task(self._restart_loop(self.ai_news_task, "ai_news_task"))

    @tech_news_task.after_loop
    async def tech_news_task_after_loop(self):
        asyncio.create_task(self._restart_loop(self.tech_news_task, "tech_news_task"))

    @research_task.after_loop
    async def research_task_after_loop(self):
        asyncio.create_task(self._restart_loop(self.research_task, "research_task"))

    @breaking_task.before_loop
    @ai_news_task.before_loop
    @tech_news_task.before_loop
    @research_task.before_loop
    async def before_tasks(self):
        await self.bot.wait_until_ready()

    # =========================================================================
    # ADMIN SLASH COMMAND: /news force-post
    # =========================================================================
    news_group = app_commands.Group(
        name="news",
        description="News aggregation management commands."
    )

    @news_group.command(name="force-post", description="Manually trigger a news check and post cycle.")
    @app_commands.describe(channel_type="The specific news channel to check, or all channels if omitted")
    @app_commands.choices(channel_type=[
        app_commands.Choice(name="All News Channels", value="all"),
        app_commands.Choice(name="#breaking-updates", value="breaking"),
        app_commands.Choice(name="#research-and-papers", value="research"),
        app_commands.Choice(name="#ai-news", value="ai-news"),
        app_commands.Choice(name="#news (Tech)", value="news"),
    ])
    @is_certified()
    async def news_force_post(self, interaction: discord.Interaction, channel_type: Optional[app_commands.Choice[str]] = None):
        """Command to force a manual feed cycle (Certified users only)."""
        target = channel_type.value if channel_type else "all"
        await interaction.response.defer(ephemeral=True)

        posted_summary: Dict[str, int] = {}
        configs_to_run = []

        if target in ("all", "breaking"):
            configs_to_run.append(BREAKING_CONFIG)
        if target in ("all", "ai-news"):
            configs_to_run.append(AI_NEWS_CONFIG)
        if target in ("all", "news"):
            configs_to_run.append(TECH_NEWS_CONFIG)
        if target in ("all", "research"):
            configs_to_run.append(RESEARCH_CONFIG)

        async with self._lock:
            for cfg in configs_to_run:
                try:
                    count = await self.process_channel_feed(cfg)
                    posted_summary[cfg.channel_key] = count
                except Exception as e:
                    logger.error("Error force-posting for %s: %s", cfg.channel_key, e)
                    posted_summary[cfg.channel_key] = 0

        lines = [f"• `#{k}`: **{v}** new post(s)" for k, v in posted_summary.items()]
        embed = create_embed(
            title="📰 Manual News Check Completed",
            description="\n".join(lines) if lines else "No channels were processed.",
            color=CATEGORY_COLORS.get("Tech", 0x1ABC9C)
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    db: Database = bot.db
    await bot.add_cog(NewsCog(bot, db))
