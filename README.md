# 🎵 WeVibe Discord Bot

A Discord community bot built with **Python 3.11+**, **discord.py 2.x**, **aiohttp**, **feedparser**, and **aiosqlite**.

WeVibe powers the **WeVibe** server with automated tech and AI news feeds, daily community polls, interactive Top 3 ranking leaderboards, and an automated one-word collaborative storytelling game.

---

## 🚀 Key Features

### 🛡️ Access Control
- Put comma-separated Discord user IDs in `CERTIFIED_USER_IDS` in `.env` for certified-only management commands.
- Everyone can vote in polls and rankings and participate in an active one-word story.
- Certified-only commands reply ephemerally with `You don't have permission to use this command.` when used by another user.

---

### 📰 Automated News System (4 Channels, Cross-Channel Deduplication)
Feeds are monitored continuously and posted with rich branding embeds, category tags, source attribution, and timestamps.
- **Cross-Channel Deduplication**: Every posted link is hashed into SQLite (`posted_news`). Once posted anywhere, it is **never** posted again across any channel.
- **First-Run Rate Limiting**: On first boot, limits to at most 3 items per feed to prevent channel flooding.
- **Priority Pipeline**: `Breaking News` > `AI News` > `General Tech News`.
- **Fault-Tolerant**: If a feed returns an HTTP error or times out, the bot logs a warning and proceeds without interruption.

| Channel | Interval | Post Cap | Criteria & Top Sources |
| :--- | :--- | :--- | :--- |
| **`#breaking-updates`** | 20 mins | Max 6/day | High-impact tech news, HN 300+ points, model releases, vulnerabilities, zero-days, breaches. |
| **`#research-and-papers`** | 6 hours | Max 5/cycle | arXiv (cs.AI, cs.LG, cs.CL, cs.CR), Hugging Face Daily Papers, Google Research, DeepMind. Tagged `[Paper]`. |
| **`#ai-news`** | 1 hour | Max 3/cycle | Dedicated AI news (OpenAI, Anthropic, Google AI, Meta AI, Verge AI, TechCrunch AI) with strict keyword filtering. |
| **`#news`** | 2 hours | Max 4/cycle | Dev, Cybersecurity, Hardware, Launches, Gaming Tech (HN, TechCrunch, Verge, Ars Technica, BleepingComputer, GitHub Blog, Dev.to). |

- **Certified-only command**:
  - `/news force-post [channel_type]`: Trigger a manual check and post cycle immediately.

---

### 📊 Daily Community Polls (`#random-daily-polls`)
- **Poll Bank**: Includes **105+ curated questions** in `data/polls.json` covering AI, Dev, Frameworks, Cloud, Career, and tech debates.
- **Daily Automated Schedule**: Posts a new random poll daily at a configurable UTC hour (`POLL_POST_HOUR_UTC`).
- **No Repeats**: Tracks used polls in SQLite and only resets once the entire bank has been cycled.
- **Live Progress Bars**: Real-time visual bars (e.g. `▰▰▰▰▰▱▱▱▱▱ 50%`) updating automatically whenever someone clicks a button.
- **Changeable Votes**: Everyone can change their vote anytime before the 24-hour mark.
- **24-Hour Auto-Close**: Closes after 24 hours, marks the winner with 🏆, and disables buttons.
- **Persistent Across Restarts**: Dynamic Discord UI views resume immediately after bot restarts.
- **Certified-only management commands**:
  - `/poll post-now [poll_id]`: Post a poll immediately.
  - `/poll add question:"..." option1:"..." option2:"..." [option3] [option4]`: Add a custom question to the bank.
  - `/poll list`: View bank statistics and active polls.

---

### 🏆 Interactive Top 3 Ranking (`#rankings`)
- Certified users create live ranking leaderboards with 2 to 10 options.
- **Ephemeral Selection UI**: Anyone can click `🗳️ Cast / Change Your Top 3 Vote` to get an ephemeral view containing **three dropdown menus** and a **Submit** button.
- **Scoring**:
  - 🥇 1st Place = **3 points**
  - 🥈 2nd Place = **2 points**
  - 🥉 3rd Place = **1 point**
- **Tie-Breaker**: Ties are broken by the highest number of 1st-place votes (`(X × 1st)`).
- **Validation**: Strict validation prevents selecting the same option multiple times.
- **Live Leaderboard**: Embed updates live with rank badges (`🥇`, `🥈`, `🥉`, `4.`, `5.`), points, progress bars, and total voters.
- **Certified-only management commands**:
  - `/rank create title:"..." options:"A, B, C, D, E"`: Create a new ranking leaderboard.
  - `/rank close rank_id:N`: Freeze leaderboard, announce winner, and disable votes.
  - `/rank list`: View active and past rankings.

---

### 📖 One-Word Story (`#one-word-story`)
Collaborative storytelling engine running directly in Discord with manual administrative control:
- **Manual Start**: The bot does **not** start stories on its own (neither on bot startup nor after a story concludes). A story only runs when an admin uses `/story start`.
- **Idle State**: When no story is running, the bot completely ignores all messages in `#one-word-story` (no deletions, no rule enforcement).
- **Active Story Rules**:
  1. Everyone may participate.
  2. Exactly **one word** per message (attached punctuation like `hello!`, `"wait,` is allowed).
  3. No back-to-back words (a user cannot post twice in a row).
  4. Invalid messages are deleted immediately with a 5-second auto-deleting explanation notice (or DM fallback).
- **Mystery Length**: Stories automatically conclude between **40 and 80 words** (random target hidden from users).
- **Story Completion**: At the target length, compiles the tale into a formatted book embed with top contributors and word counts, then marks the story as ended and stays idle until the next `/story start`.
- **Certified-only commands**:
  - `/story start`: Start a new story session with a random starter word and hidden target length.
  - `/story skip`: End the active story early and post its compiled text.
  - `/story stop`: Cancel the active story without posting the narrative.

---

## 📁 Project Architecture

```
WeVibe/
├── .env.example            # Environment variables template
├── requirements.txt        # Python dependency list
├── README.md               # Documentation and setup guide
├── config.py               # Feed sources, intervals, caps, colors & constants
├── database.py             # Asynchronous SQLite layer (aiosqlite)
├── utils.py                # Embed builder, progress bars, HTML cleaner, text formatter
├── main.py                 # Bot entrypoint, gateway setup, slash command syncing
├── cogs/
│   ├── __init__.py
│   ├── news.py             # RSS scraper, deduplication, 4-channel tasks, /news force-post
│   ├── polls.py            # Daily polls, 24h timer, live result bars, button views
│   ├── ranking.py          # Top 3 ranking, ephemeral 3-dropdowns UI, live leaderboard
│   └── story.py            # One-word story listener, moderation, compilation embed
├── data/
│   └── polls.json          # Curated bank of 105+ tech/dev/AI poll questions
└── tests/
    └── test_wevibe.py      # Automated test suite for DB, scoring & integrity
```

---

## 🛠️ Setup Instructions

### 1. Prerequisites
- **Python 3.11** or newer (`python --version`)
- A Discord account and administrative access to your server.

### 2. Configure Discord Developer Portal
1. Navigate to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application** and name it **WeVibe**.
3. Under the **Bot** tab:
   - Click **Reset Token** and copy your **Bot Token**.
   - Under **Privileged Gateway Intents**, enable:
     - ✅ **Message Content Intent** *(Critical for `#one-word-story`)*
     - ✅ **Server Members Intent**
     - ✅ **Presence Intent**
4. Under **OAuth2 -> URL Generator**:
   - Select scopes: `bot`, `applications.commands`
   - Select bot permissions:
     - `Administrator` (or explicitly: `Manage Messages`, `Send Messages`, `Embed Links`, `Read Message History`, `View Channels`)
   - Copy the generated URL and invite the bot to your server.

### 3. Installation
Open your terminal in `D:/Projects/WeVibe`:

```bash
# Optional: create a virtual environment
python -m venv venv
venv\Scripts\activate   # On Windows

# Install dependencies
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env`:

```bash
copy .env.example .env
```

Open `.env` and fill in your Discord IDs:
*(Tip: In Discord, go to User Settings -> Advanced -> enable **Developer Mode**, then right-click your server and channels to copy their IDs)*

```ini
DISCORD_TOKEN=your_actual_bot_token_here
GUILD_ID=your_server_id_here
CERTIFIED_USER_IDS=123456789012345678,987654321098765432

# Channel IDs
CHANNEL_BREAKING=123456789012345678
CHANNEL_RESEARCH=123456789012345678
CHANNEL_AI_NEWS=123456789012345678
CHANNEL_NEWS=123456789012345678
CHANNEL_POLLS=123456789012345678
CHANNEL_STORY=123456789012345678

# Optional: Daily poll hour (UTC 0-23, default 14)
POLL_POST_HOUR_UTC=14
```

### 5. Run the Verification Tests
To verify database schemas, poll questions bank, and ranking calculations:

```bash
python tests/test_wevibe.py
```

### 6. Start the Bot
```bash
python main.py
```

On launch:
- The bot initializes the SQLite database (`data/wevibe.db`).
- Loads all cogs (`news`, `polls`, `ranking`, `story`).
- Synchronizes slash commands directly to your `GUILD_ID` for instant availability.
- Begins scheduled background tasks for news feeds and daily polls.

---

## 📋 Slash Commands Cheat Sheet

| Command | Permission | Description |
| :--- | :--- | :--- |
| `/help` | Everyone | Show commands and feature guidance |
| `/info` | Everyone | Show bot statistics and runtime information |
| `/news force-post [channel]` | Certified users | Manually trigger a news check and post cycle |
| `/poll post-now [poll_id]` | Certified users | Immediately post a poll from the bank |
| `/poll add ...` | Certified users | Add a custom poll question to the bank |
| `/poll list` | Certified users | View bank statistics and active polls |
| `/rank create title:... options:...` | Certified users | Create a new Top 3 ranking leaderboard |
| `/rank close rank_id:N` | Certified users | Close ranking and announce winner |
| `/rank list` | Certified users | List active and past rankings |
| `/story start` | Certified users | Start a new one-word story session |
| `/story skip` | Certified users | End active story early and post completed tale |
| `/story stop` | Certified users | Cancel the active story without posting |

---

## 🎨 Customizing Feeds & Settings
All news sources, intervals, daily limits, and colors can be adjusted directly in [`config.py`](file:///D:/Projects/WeVibe/config.py):
- Add or remove RSS feeds by editing `BREAKING_CONFIG.sources`, `RESEARCH_CONFIG.sources`, `AI_NEWS_CONFIG.sources`, or `TECH_NEWS_CONFIG.sources`.
- Adjust intervals (e.g. `interval_minutes=20`).
- Update branding colors in the `COLOR_*` palette.
