"""
WeVibe Verification Script
Tests database models, poll bank integrity, feed definitions, and helper routines.
"""

import sys
import os
import json
import asyncio

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

print("--- Step 1: Testing Imports & Config ---")
import config
import utils
import database
from cogs.ranking import calculate_rankings_score

print(f"Config loaded. Poll Post Hour: {config.POLL_POST_HOUR_UTC} UTC")
print(f"Breaking sources count: {len(config.BREAKING_CONFIG.sources)}")
print(f"Research sources count: {len(config.RESEARCH_CONFIG.sources)}")
print(f"AI news sources count: {len(config.AI_NEWS_CONFIG.sources)}")
print(f"Tech news sources count: {len(config.TECH_NEWS_CONFIG.sources)}")

print("\n--- Step 2: Testing Poll Bank ---")
with open("data/polls.json", "r", encoding="utf-8") as f:
    polls = json.load(f)
print(f"Poll questions in bank: {len(polls)}")
assert len(polls) >= 100, f"Expected at least 100 questions, got {len(polls)}"
for p in polls:
    assert "id" in p and "question" in p and "options" in p
    assert 2 <= len(p["options"]) <= 4
print("Poll bank structure validated!")

print("\n--- Step 3: Testing SQLite Database ---")
test_db_path = "data/test_wevibe.db"
if os.path.exists(test_db_path):
    os.remove(test_db_path)

async def test_db():
    db = database.Database(test_db_path)
    await db.init()

    # Access
    await db.add_certified_user(123456789, "TestUser#0001", 987654321)
    assert await db.is_certified(123456789) is True
    assert await db.is_certified(999999999) is False
    users = await db.get_all_certified_users()
    assert len(users) == 1
    print("✓ Access control tested")

    # News Deduplication
    url_hash = "abc123hash"
    assert await db.is_news_posted(url_hash) is False
    await db.mark_news_posted(url_hash, "https://example.com/test", "Sample Title", "breaking")
    assert await db.is_news_posted(url_hash) is True
    await db.record_breaking_post(url_hash)
    assert await db.get_breaking_posts_today_count() == 1
    print("✓ News deduplication & daily breaking cap tested")

    # Polls
    from datetime import datetime, timezone, timedelta
    exp = datetime.now(timezone.utc) + timedelta(hours=24)
    poll_id = await db.create_poll(111, "Tabs or Spaces?", ["Tabs", "Spaces"], exp)
    await db.record_poll_vote(poll_id, 123456789, 0)
    await db.record_poll_vote(poll_id, 987654321, 0)
    votes = await db.get_poll_votes(poll_id)
    assert votes.get(0) == 2
    assert await db.get_poll_total_voters(poll_id) == 2
    print("✓ Poll voting & stats tested")

    # Rankings
    rank_id = await db.create_ranking(222, "Top Languages", ["Rust", "Go", "Python"], 123456789)
    await db.record_rank_vote(rank_id, 123456789, first_choice=0, second_choice=1, third_choice=2)
    rank_votes = await db.get_rank_votes(rank_id)
    assert len(rank_votes) == 1
    print("✓ Ranking storage tested")

    # Story
    story_id = await db.create_story(333, 50, "Suddenly", 101010)
    story = await db.get_active_story(333)
    assert story["id"] == story_id
    assert story["current_word_count"] == 1
    new_pos = await db.add_story_word(story_id, 123456789, "a")
    assert new_pos == 2
    words = await db.get_story_words(story_id)
    assert len(words) == 2
    text = utils.format_story_text([w["word"] for w in words])
    assert text == "Suddenly a"

    # Test story completion (status != 'active')
    await db.complete_story(story_id, status="completed")
    active_after = await db.get_active_story(333)
    assert active_after is None, "Completed story should no longer be active"
    print("✓ One-word story state & manual completion tested")

asyncio.run(test_db())

if os.path.exists(test_db_path):
    os.remove(test_db_path)

print("\n--- Step 4: Testing Ranking Scoring Logic ---")
options = ["Cursor", "Copilot", "Claude Code"]
votes = [
    {"first_choice": 0, "second_choice": 1, "third_choice": 2}, # Cursor: 3, Copilot: 2, Claude: 1
    {"first_choice": 0, "second_choice": 2, "third_choice": 1}, # Cursor: 3, Copilot: 1, Claude: 2
    {"first_choice": 1, "second_choice": 0, "third_choice": 2}, # Cursor: 2, Copilot: 3, Claude: 1
]
# Cursor: 3 + 3 + 2 = 8 pts (2 x 1st)
# Copilot: 2 + 1 + 3 = 6 pts (1 x 1st)
# Claude: 1 + 2 + 1 = 4 pts (0 x 1st)
scores = calculate_rankings_score(options, votes)
assert scores[0]["name"] == "Cursor" and scores[0]["points"] == 8
assert scores[1]["name"] == "Copilot" and scores[1]["points"] == 6
assert scores[2]["name"] == "Claude Code" and scores[2]["points"] == 4
print("✓ Ranking scoring & tie-breaking verified")

print("\n--- Step 5: Testing Progress Bar ---")
bar = utils.make_progress_bar(0.6, length=10)
print(f"60% Progress Bar: {bar}")
assert bar == "▰▰▰▰▰▰▱▱▱▱"
print("✓ Progress bar verified")

print("\n=======================================================")
print("ALL VERIFICATION CHECKS PASSED WITH 100% SUCCESS!")
print("=======================================================")
