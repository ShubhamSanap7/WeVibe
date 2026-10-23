"""
WeVibe Discord Bot - Central Configuration File
All feed URLs, intervals, posting limits, colors, and environment settings are defined here.
"""

import os
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from dotenv import load_dotenv

# Load .env file
load_dotenv()

logger = logging.getLogger("WeVibe.Config")

# ==============================================================================
# DISCORD & GUILD SETTINGS
# ==============================================================================
DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID: Optional[int] = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID", "").strip().isdigit() else None

# Parse CERTIFIED_USER_IDS from comma-separated string in .env
CERTIFIED_USER_IDS: Set[int] = set()
_raw_certified = os.getenv("CERTIFIED_USER_IDS", "")
for _part in _raw_certified.split(","):
    _clean = _part.strip()
    if not _clean:
        continue
    if _clean.isdigit():
        CERTIFIED_USER_IDS.add(int(_clean))
    else:
        logger.warning("Invalid user ID in CERTIFIED_USER_IDS: '%s'", _clean)

# ==============================================================================
# CHANNEL IDS
# ==============================================================================
CHANNEL_BREAKING_ID: Optional[int] = int(os.getenv("CHANNEL_BREAKING")) if os.getenv("CHANNEL_BREAKING", "").strip().isdigit() else None
CHANNEL_RESEARCH_ID: Optional[int] = int(os.getenv("CHANNEL_RESEARCH")) if os.getenv("CHANNEL_RESEARCH", "").strip().isdigit() else None
CHANNEL_AI_NEWS_ID: Optional[int] = int(os.getenv("CHANNEL_AI_NEWS")) if os.getenv("CHANNEL_AI_NEWS", "").strip().isdigit() else None
CHANNEL_NEWS_ID: Optional[int] = int(os.getenv("CHANNEL_NEWS")) if os.getenv("CHANNEL_NEWS", "").strip().isdigit() else None
CHANNEL_POLLS_ID: Optional[int] = int(os.getenv("CHANNEL_POLLS")) if os.getenv("CHANNEL_POLLS", "").strip().isdigit() else None
CHANNEL_STORY_ID: Optional[int] = int(os.getenv("CHANNEL_STORY")) if os.getenv("CHANNEL_STORY", "").strip().isdigit() else None

# Optional role to ping when a poll is posted
_raw_poll_ping_role_id = os.getenv("POLL_PING_ROLE_ID", "").strip()
POLL_PING_ROLE_ID: Optional[int] = None
if not _raw_poll_ping_role_id:
    logger.warning("POLL_PING_ROLE_ID is empty; poll role pings are disabled.")
elif _raw_poll_ping_role_id.isdigit():
    POLL_PING_ROLE_ID = int(_raw_poll_ping_role_id)
else:
    logger.warning("Invalid POLL_PING_ROLE_ID: '%s'; poll role pings are disabled.", _raw_poll_ping_role_id)

# Optional role to ping when a story starts or ends
_raw_story_ping_role_id = os.getenv("STORY_PING_ROLE_ID", "").strip()
STORY_PING_ROLE_ID: Optional[int] = None
if not _raw_story_ping_role_id:
    logger.warning("STORY_PING_ROLE_ID is empty; story role pings are disabled.")
elif _raw_story_ping_role_id.isdigit():
    STORY_PING_ROLE_ID = int(_raw_story_ping_role_id)
else:
    logger.warning("Invalid STORY_PING_ROLE_ID: '%s'; story role pings are disabled.", _raw_story_ping_role_id)

# Database path
DATABASE_PATH: str = os.getenv("DATABASE_PATH", "data/wevibe.db").strip()

# Daily poll schedule
POLL_POST_HOUR_UTC: int = int(os.getenv("POLL_POST_HOUR_UTC", "14"))

# WeVibe Footer & Branding
FOOTER_TEXT: str = "WeVibe • Stay Connected & Informed"
FOOTER_ICON_URL: Optional[str] = None  # Optional custom icon URL

# ==============================================================================
# COLOR PALETTE (Purple / Blue / Brand aesthetics)
# ==============================================================================
COLOR_BRAND: int = 0x5865F2         # Blurple / WeVibe Brand
COLOR_BREAKING: int = 0xED4245      # Vibrant Red for High-Impact Breaking News
COLOR_RESEARCH: int = 0x3498DB      # Deep Scholar Blue for Research & Papers
COLOR_AI_NEWS: int = 0x9B59B6       # Amethyst Purple for AI News
COLOR_NEWS: int = 0x1ABC9C          # Teal / Turquoise for General Tech & Dev News
COLOR_POLL: int = 0xF1C40F          # Amber / Gold for Polls
COLOR_RANK: int = 0xE67E22          # Orange for Rankings
COLOR_STORY: int = 0x6C5CE7         # Royal Indigo for One-Word Story
COLOR_SUCCESS: int = 0x2ECC71       # Green
COLOR_ERROR: int = 0xE74C3C         # Red

# Category specific colors for general #news channel
CATEGORY_COLORS: Dict[str, int] = {
    "AI": 0x9B59B6,
    "Cybersecurity": 0xE74C3C,
    "Dev / Coding": 0x3498DB,
    "Launch": 0xE67E22,
    "Gaming Tech": 0x2ECC71,
    "Tech": 0x1ABC9C,
}

# ==============================================================================
# NEWS FEEDS & SOURCES CONFIGURATION
# ==============================================================================
@dataclass
class FeedSource:
    name: str
    url: str
    default_category: str = "Tech"
    is_hn: bool = False  # Special Hacker News score filter


@dataclass
class ChannelNewsConfig:
    channel_key: str
    channel_id: Optional[int]
    interval_minutes: int
    max_posts_per_cycle: int
    daily_post_cap: Optional[int] = None
    color: int = COLOR_BRAND
    sources: List[FeedSource] = field(default_factory=list)


# 1) #breaking-updates
BREAKING_KEYWORDS: List[str] = [
    "released", "launches", "launch", "breach", "vulnerability",
    "zero-day", "0-day", "gpt", "claude", "gemini", "llama",
    "deepseek", "open source", "critical flaw", "ransomware",
    "unveils", "major update", "outage", "data leak"
]

BREAKING_CONFIG = ChannelNewsConfig(
    channel_key="breaking",
    channel_id=CHANNEL_BREAKING_ID,
    interval_minutes=20,  # Checked every 20 minutes
    max_posts_per_cycle=2,
    daily_post_cap=6,     # Max 6 posts per day
    color=COLOR_BREAKING,
    sources=[
        FeedSource(name="Hacker News (Top)", url="https://hnrss.org/frontpage?points=300", default_category="Breaking", is_hn=True),
        FeedSource(name="BleepingComputer", url="https://www.bleepingcomputer.com/feed/", default_category="Cybersecurity"),
        FeedSource(name="Techmeme", url="https://www.techmeme.com/feed.xml", default_category="Breaking"),
        FeedSource(name="OpenAI News", url="https://openai.com/news/rss.xml", default_category="AI"),
        FeedSource(name="Anthropic News", url="https://www.anthropic.com/news/feed", default_category="AI"),
        FeedSource(name="GitHub Blog", url="https://github.blog/feed/", default_category="Dev / Coding"),
    ]
)

# 2) #research-and-papers
RESEARCH_CONFIG = ChannelNewsConfig(
    channel_key="research",
    channel_id=CHANNEL_RESEARCH_ID,
    interval_minutes=360,  # Checked every 6 hours
    max_posts_per_cycle=5, # Post max 5 per cycle
    color=COLOR_RESEARCH,
    sources=[
        FeedSource(name="arXiv cs.AI", url="https://rss.arxiv.org/rss/cs.AI", default_category="Paper"),
        FeedSource(name="arXiv cs.LG", url="https://rss.arxiv.org/rss/cs.LG", default_category="Paper"),
        FeedSource(name="arXiv cs.CL", url="https://rss.arxiv.org/rss/cs.CL", default_category="Paper"),
        FeedSource(name="arXiv cs.CR", url="https://rss.arxiv.org/rss/cs.CR", default_category="Paper"),
        FeedSource(name="Hugging Face Daily Papers", url="https://huggingface.co/blog/feed.xml", default_category="Paper"),
        FeedSource(name="Google Research", url="https://research.google/blog/rss/", default_category="Paper"),
        FeedSource(name="DeepMind", url="https://deepmind.google/blog/rss.xml", default_category="Paper"),
    ]
)

# 3) #ai-news (ONLY AI news)
AI_KEYWORDS: List[str] = [
    "ai", "artificial intelligence", "llm", "gpt", "claude", "gemini",
    "llama", "deepseek", "machine learning", "neural network", "transformer",
    "diffusion", "agent", "mistral", "copilot", "hugging face", "openai",
    "anthropic", "deepmind", "generative ai"
]

AI_NEWS_CONFIG = ChannelNewsConfig(
    channel_key="ai-news",
    channel_id=CHANNEL_AI_NEWS_ID,
    interval_minutes=60,  # Checked every hour
    max_posts_per_cycle=3, # Max 3 posts per cycle
    color=COLOR_AI_NEWS,
    sources=[
        FeedSource(name="OpenAI", url="https://openai.com/news/rss.xml", default_category="AI"),
        FeedSource(name="Anthropic", url="https://www.anthropic.com/news/feed", default_category="AI"),
        FeedSource(name="Google AI", url="https://blog.google/technology/ai/rss/", default_category="AI"),
        FeedSource(name="Hugging Face Blog", url="https://huggingface.co/blog/feed.xml", default_category="AI"),
        FeedSource(name="The Verge AI", url="https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", default_category="AI"),
        FeedSource(name="TechCrunch AI", url="https://techcrunch.com/category/artificial-intelligence/feed/", default_category="AI"),
        FeedSource(name="VentureBeat AI", url="https://venturebeat.com/category/ai/feed/", default_category="AI"),
    ]
)

# 4) #news (All types of tech news)
TECH_NEWS_CONFIG = ChannelNewsConfig(
    channel_key="news",
    channel_id=CHANNEL_NEWS_ID,
    interval_minutes=120, # Checked every 2 hours
    max_posts_per_cycle=4, # Max 4 posts per cycle
    color=COLOR_NEWS,
    sources=[
        FeedSource(name="Hacker News", url="https://hnrss.org/frontpage?points=100", default_category="Tech", is_hn=True),
        FeedSource(name="TechCrunch", url="https://techcrunch.com/feed/", default_category="Launch"),
        FeedSource(name="The Verge", url="https://www.theverge.com/rss/index.xml", default_category="Tech"),
        FeedSource(name="Ars Technica", url="https://feeds.arstechnica.com/arstechnica/index", default_category="Tech"),
        FeedSource(name="BleepingComputer", url="https://www.bleepingcomputer.com/feed/", default_category="Cybersecurity"),
        FeedSource(name="GitHub Blog", url="https://github.blog/feed/", default_category="Dev / Coding"),
        FeedSource(name="Dev.to", url="https://dev.to/feed", default_category="Dev / Coding"),
        FeedSource(name="Phoronix", url="https://www.phoronix.com/phoronix-rss.php", default_category="Dev / Coding"),
        FeedSource(name="PC Gamer Tech", url="https://www.pcgamer.com/rss/", default_category="Gaming Tech"),
    ]
)

# Maximum items to post per feed on the very first execution to avoid spamming
FIRST_RUN_MAX_PER_FEED: int = 3

# Priority order for deduplication across channels
NEWS_CHANNEL_PRIORITY = ["breaking", "ai-news", "news", "research"]

# ==============================================================================
# ONE-WORD STORY CONFIGURATION
# ==============================================================================
STORY_MIN_WORDS: int = 40
STORY_MAX_WORDS: int = 80

STORY_STARTERS: List[str] = [
    "Once", "Suddenly", "Nobody", "Yesterday", "Deep", "Legends",
    "Somewhere", "In", "Beyond", "Far", "Long", "Silently",
    "Unexpectedly", "Beneath", "Tonight", "Long ago", "Before",
    "Darkness", "Whispers", "Echoes", "Somewhere", "Deeply"
]
