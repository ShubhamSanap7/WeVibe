"""
WeVibe Discord Bot - Asynchronous SQLite Database Layer
Handles persistent storage for news deduplication, polls, rankings, and story states.
"""

import json
import os
import aiosqlite
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

from config import DATABASE_PATH


class Database:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        # Ensure parent directory exists
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)

    async def init(self) -> None:
        """Initializes tables and indices."""
        async with aiosqlite.connect(self.db_path) as db:
            # Enable foreign keys and WAL mode for better concurrency
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA foreign_keys=ON;")

            # Remove the legacy database-backed certification system from older installs.
            await db.execute("DROP TABLE IF EXISTS certified_users")

            # 1. News Deduplication
            await db.execute("""
                CREATE TABLE IF NOT EXISTS posted_news (
                    url_hash TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT,
                    channel_key TEXT NOT NULL,
                    posted_at TEXT NOT NULL
                )
            """)

            # 3. Breaking News Daily Tracker
            await db.execute("""
                CREATE TABLE IF NOT EXISTS breaking_daily_tracker (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    posted_date TEXT NOT NULL,
                    item_hash TEXT NOT NULL
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_breaking_date ON breaking_daily_tracker (posted_date);")

            # 4. Polls
            await db.execute("""
                CREATE TABLE IF NOT EXISTS polls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER,
                    channel_id INTEGER NOT NULL,
                    question TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    is_closed INTEGER DEFAULT 0
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS poll_votes (
                    poll_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    option_index INTEGER NOT NULL,
                    voted_at TEXT NOT NULL,
                    PRIMARY KEY (poll_id, user_id),
                    FOREIGN KEY (poll_id) REFERENCES polls (id) ON DELETE CASCADE
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS used_polls (
                    bank_id INTEGER PRIMARY KEY,
                    used_at TEXT NOT NULL
                )
            """)

            # 5. Rankings
            await db.execute("""
                CREATE TABLE IF NOT EXISTS rankings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER,
                    channel_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_closed INTEGER DEFAULT 0,
                    created_by INTEGER NOT NULL
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS rank_votes (
                    rank_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    first_choice INTEGER NOT NULL,
                    second_choice INTEGER NOT NULL,
                    third_choice INTEGER NOT NULL,
                    voted_at TEXT NOT NULL,
                    PRIMARY KEY (rank_id, user_id),
                    FOREIGN KEY (rank_id) REFERENCES rankings (id) ON DELETE CASCADE
                )
            """)

            # 6. One-Word Story
            await db.execute("""
                CREATE TABLE IF NOT EXISTS stories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    target_length INTEGER NOT NULL,
                    current_word_count INTEGER DEFAULT 0,
                    last_user_id INTEGER,
                    status TEXT DEFAULT 'active',
                    started_at TEXT NOT NULL,
                    ended_at TEXT
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS story_words (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    story_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    word TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (story_id) REFERENCES stories (id) ON DELETE CASCADE
                )
            """)

            # 7. Key-Value Metadata
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bot_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            await db.commit()

    # =========================================================================
    # SYSTEM STATS HELPERS
    # =========================================================================
    async def get_total_rankings_count(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM rankings") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_completed_stories_count(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM stories WHERE status = 'completed'") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    # =========================================================================
    # NEWS DEDUPLICATION & LIMITS
    # =========================================================================
    async def is_news_posted(self, url_hash: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT 1 FROM posted_news WHERE url_hash = ?", (url_hash,)
            ) as cursor:
                return (await cursor.fetchone()) is not None

    async def mark_news_posted(self, url_hash: str, url: str, title: str, channel_key: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO posted_news (url_hash, url, title, channel_key, posted_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (url_hash, url, title, channel_key, now)
            )
            await db.commit()

    async def get_breaking_posts_today_count(self) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM breaking_daily_tracker WHERE posted_date = ?", (today,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def record_breaking_post(self, item_hash: str) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO breaking_daily_tracker (posted_date, item_hash) VALUES (?, ?)",
                (today, item_hash)
            )
            await db.commit()

    async def get_posted_news_count(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM posted_news") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    # =========================================================================
    # POLLS
    # =========================================================================
    async def create_poll(
        self,
        channel_id: int,
        question: str,
        options: List[str],
        expires_at: datetime
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        exp_str = expires_at.isoformat()
        options_json = json.dumps(options)
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO polls (channel_id, question, options_json, created_at, expires_at, is_closed)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (channel_id, question, options_json, now, exp_str)
            )
            await db.commit()
            return cursor.lastrowid

    async def set_poll_message_id(self, poll_id: int, message_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE polls SET message_id = ? WHERE id = ?",
                (message_id, poll_id)
            )
            await db.commit()

    async def get_poll(self, poll_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM polls WHERE id = ?", (poll_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                data = dict(row)
                data["options"] = json.loads(data["options_json"])
                return data

    async def record_poll_vote(self, poll_id: int, user_id: int, option_index: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO poll_votes (poll_id, user_id, option_index, voted_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(poll_id, user_id) DO UPDATE SET
                    option_index = excluded.option_index,
                    voted_at = excluded.voted_at
                """,
                (poll_id, user_id, option_index, now)
            )
            await db.commit()

    async def get_poll_votes(self, poll_id: int) -> Dict[int, int]:
        """Returns a dict mapping option_index -> vote_count."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT option_index, COUNT(*) as cnt
                FROM poll_votes
                WHERE poll_id = ?
                GROUP BY option_index
                """,
                (poll_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return {row[0]: row[1] for row in rows}

    async def get_user_poll_vote(self, poll_id: int, user_id: int) -> Optional[int]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT option_index FROM poll_votes WHERE poll_id = ? AND user_id = ?",
                (poll_id, user_id)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def get_poll_total_voters(self, poll_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(DISTINCT user_id) FROM poll_votes WHERE poll_id = ?", (poll_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def close_poll(self, poll_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE polls SET is_closed = 1 WHERE id = ?", (poll_id,))
            await db.commit()

    async def get_active_polls(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM polls WHERE is_closed = 0") as cursor:
                rows = await cursor.fetchall()
                result = []
                for r in rows:
                    item = dict(r)
                    item["options"] = json.loads(item["options_json"])
                    result.append(item)
                return result

    async def get_expired_open_polls(self) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM polls WHERE is_closed = 0 AND expires_at <= ?", (now,)
            ) as cursor:
                rows = await cursor.fetchall()
                result = []
                for r in rows:
                    item = dict(r)
                    item["options"] = json.loads(item["options_json"])
                    result.append(item)
                return result

    async def is_poll_used(self, bank_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT 1 FROM used_polls WHERE bank_id = ?", (bank_id,)) as cursor:
                return (await cursor.fetchone()) is not None

    async def mark_poll_used(self, bank_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO used_polls (bank_id, used_at) VALUES (?, ?)",
                (bank_id, now)
            )
            await db.commit()

    async def get_all_used_poll_ids(self) -> List[int]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT bank_id FROM used_polls") as cursor:
                rows = await cursor.fetchall()
                return [r[0] for r in rows]

    async def clear_used_polls(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM used_polls")
            await db.commit()

    # =========================================================================
    # RANKINGS
    # =========================================================================
    async def create_ranking(
        self,
        channel_id: int,
        title: str,
        options: List[str],
        created_by: int
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        options_json = json.dumps(options)
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO rankings (channel_id, title, options_json, created_at, is_closed, created_by)
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (channel_id, title, options_json, now, created_by)
            )
            await db.commit()
            return cursor.lastrowid

    async def set_ranking_message_id(self, rank_id: int, message_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE rankings SET message_id = ? WHERE id = ?",
                (message_id, rank_id)
            )
            await db.commit()

    async def get_ranking(self, rank_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM rankings WHERE id = ?", (rank_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                data = dict(row)
                data["options"] = json.loads(data["options_json"])
                return data

    async def record_rank_vote(
        self,
        rank_id: int,
        user_id: int,
        first_choice: int,
        second_choice: int,
        third_choice: int
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO rank_votes (rank_id, user_id, first_choice, second_choice, third_choice, voted_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(rank_id, user_id) DO UPDATE SET
                    first_choice = excluded.first_choice,
                    second_choice = excluded.second_choice,
                    third_choice = excluded.third_choice,
                    voted_at = excluded.voted_at
                """,
                (rank_id, user_id, first_choice, second_choice, third_choice, now)
            )
            await db.commit()

    async def get_rank_votes(self, rank_id: int) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM rank_votes WHERE rank_id = ?", (rank_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def close_ranking(self, rank_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE rankings SET is_closed = 1 WHERE id = ?", (rank_id,))
            await db.commit()

    async def get_active_rankings(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM rankings WHERE is_closed = 0") as cursor:
                rows = await cursor.fetchall()
                result = []
                for r in rows:
                    item = dict(r)
                    item["options"] = json.loads(item["options_json"])
                    result.append(item)
                return result

    async def get_all_rankings(self, limit: int = 15) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM rankings ORDER BY id DESC LIMIT ?", (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
                result = []
                for r in rows:
                    item = dict(r)
                    item["options"] = json.loads(item["options_json"])
                    result.append(item)
                return result

    # =========================================================================
    # ONE-WORD STORY
    # =========================================================================
    async def get_active_story(self, channel_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM stories
                WHERE channel_id = ? AND status = 'active'
                ORDER BY id DESC LIMIT 1
                """,
                (channel_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def create_story(
        self,
        channel_id: int,
        target_length: int,
        starter_word: str,
        bot_user_id: int
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO stories (channel_id, target_length, current_word_count, last_user_id, status, started_at)
                VALUES (?, ?, 1, ?, 'active', ?)
                """,
                (channel_id, target_length, bot_user_id, now)
            )
            story_id = cursor.lastrowid

            # Add starter word at position 1
            await db.execute(
                """
                INSERT INTO story_words (story_id, user_id, word, position, created_at)
                VALUES (?, ?, ?, 1, ?)
                """,
                (story_id, bot_user_id, starter_word, now)
            )
            await db.commit()
            return story_id

    async def add_story_word(self, story_id: int, user_id: int, word: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            # Increment current_word_count and update last_user_id
            await db.execute(
                """
                UPDATE stories
                SET current_word_count = current_word_count + 1,
                    last_user_id = ?
                WHERE id = ?
                """,
                (user_id, story_id)
            )

            # Get new position
            async with db.execute("SELECT current_word_count FROM stories WHERE id = ?", (story_id,)) as cur:
                row = await cur.fetchone()
                new_pos = row[0] if row else 1

            await db.execute(
                """
                INSERT INTO story_words (story_id, user_id, word, position, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (story_id, user_id, word, new_pos, now)
            )
            await db.commit()
            return new_pos

    async def get_story_words(self, story_id: int) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM story_words WHERE story_id = ? ORDER BY position ASC",
                (story_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def get_story_contributors(self, story_id: int, bot_user_id: int) -> List[Tuple[int, int]]:
        """Returns list of (user_id, word_count) sorted by highest contributions, excluding the bot."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT user_id, COUNT(*) as cnt
                FROM story_words
                WHERE story_id = ? AND user_id != ?
                GROUP BY user_id
                ORDER BY cnt DESC
                """,
                (story_id, bot_user_id)
            ) as cursor:
                rows = await cursor.fetchall()
                return [(r[0], r[1]) for r in rows]

    async def complete_story(self, story_id: int, status: str = "completed") -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE stories SET status = ?, ended_at = ? WHERE id = ?",
                (status, now, story_id)
            )
            await db.commit()
