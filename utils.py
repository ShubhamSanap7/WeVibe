"""
WeVibe Discord Bot - Utilities & Helper Functions
Handles standard embed formatting, progress bar generation, text sanitization, and access checks.
"""

import re
from datetime import datetime, timezone
from typing import Optional, List
import discord
from bs4 import BeautifulSoup

from config import COLOR_BRAND, FOOTER_TEXT, FOOTER_ICON_URL


def create_embed(
    title: str,
    description: Optional[str] = None,
    color: int = COLOR_BRAND,
    url: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    image_url: Optional[str] = None,
    footer_text: Optional[str] = None,
    timestamp: Optional[datetime] = None
) -> discord.Embed:
    """Creates a consistent WeVibe-branded Discord Embed."""
    embed = discord.Embed(
        title=title[:256] if title else None,
        description=description[:4096] if description else None,
        color=color,
        url=url
    )

    if thumbnail_url and (thumbnail_url.startswith("http://") or thumbnail_url.startswith("https://")):
        embed.set_thumbnail(url=thumbnail_url)

    if image_url and (image_url.startswith("http://") or image_url.startswith("https://")):
        embed.set_image(url=image_url)

    embed.set_footer(
        text=footer_text or FOOTER_TEXT,
        icon_url=FOOTER_ICON_URL
    )

    embed.timestamp = timestamp or datetime.now(timezone.utc)
    return embed


def make_progress_bar(ratio: float, length: int = 10, filled_char: str = "▰", empty_char: str = "▱") -> str:
    """Generates a visual progress bar (e.g. ▰▰▰▰▱▱▱▱▱▱)."""
    clamped_ratio = max(0.0, min(1.0, ratio))
    filled_count = round(clamped_ratio * length)
    empty_count = length - filled_count
    return (filled_char * filled_count) + (empty_char * empty_count)


def clean_html_summary(html_text: str, max_chars: int = 250) -> str:
    """Strips HTML tags, cleans extra whitespaces, and trims text to max_chars."""
    if not html_text:
        return ""
    try:
        soup = BeautifulSoup(html_text, "html.parser")
        # Remove script and style tags
        for element in soup(["script", "style"]):
            element.decompose()
        clean = soup.get_text(separator=" ")
    except Exception:
        # Fallback to simple regex if BeautifulSoup fails
        clean = re.sub(r"<[^>]+>", " ", html_text)

    # Normalize whitespaces
    clean = re.sub(r"\s+", " ", clean).strip()

    if len(clean) <= max_chars:
        return clean

    # Trim to last word before max_chars
    trimmed = clean[:max_chars]
    last_space = trimmed.rfind(" ")
    if last_space > 0:
        trimmed = trimmed[:last_space]
    return trimmed + "..."


def get_rank_badge(position: int) -> str:
    """Returns a medal emoji for top 3 or a formatted number for others."""
    badges = {
        1: "🥇",
        2: "🥈",
        3: "🥉"
    }
    return badges.get(position, f"`{position}.`")


def format_story_text(words: List[str]) -> str:
    """
    Intelligently formats a sequence of story words into readable prose,
    attaching punctuation without awkward leading spaces.
    """
    if not words:
        return ""

    text = ""
    # Punctuation that shouldn't have a space before it
    no_pre_space = {".", ",", "!", "?", ";", ":", "…", "'", "’", ")", "]", "}"}
    # Punctuation that shouldn't have a space after it
    no_post_space = {"(", "[", "{", "“", '"'}

    prev_no_post = False
    for i, word in enumerate(words):
        word = word.strip()
        if not word:
            continue

        if i == 0 or prev_no_post or (word in no_pre_space):
            text += word
        else:
            text += " " + word

        prev_no_post = word in no_post_space

    return text
