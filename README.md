# Fantasy Basketball Debriefer

Zero-cost automated pipeline that monitors a YouTube channel via its native RSS feed, summarizes new uploads with Gemini (`gemini-3.8-flash`, with automatic fallback), and posts the summary to a private Discord channel via webhook.

## Setup

1. Add the following **Repository Secrets** under **Settings → Secrets and variables → Actions**:
   - `YOUTUBE_CHANNEL_ID`
   - `GEMINI_API_KEY`
   - `DISCORD_WEBHOOK_URL`
2. Run **Actions → YouTube Summary Pipeline → Run workflow** once to seed `seen_videos.json` with existing videos without spamming Discord.
3. Subsequent runs execute automatically every 15 minutes (`7,22,37,52 * * * *`).

## Local Testing

One-time setup (avoids `ModuleNotFoundError: No module named 'google'`):

```bash
python3 -m venv .venv
.venv/bin/pip install google-genai
cp .env.example .env
# Fill in GEMINI_API_KEY, YOUTUBE_CHANNEL_ID, and DISCORD_WEBHOOK_URL in .env
```

Run tests directly with `.venv/bin/python3` (no `activate` needed; does not modify `seen_videos.json`):

```bash
# Newest video from YOUTUBE_CHANNEL_ID (terminal only)
.venv/bin/python3 summarize.py --latest

# Specific video URL (terminal only)
.venv/bin/python3 summarize.py --test-url "https://www.youtube.com/watch?v=YOUR_VIDEO_ID"

# Preview Discord embed
.venv/bin/python3 summarize.py --latest --send-discord
```
