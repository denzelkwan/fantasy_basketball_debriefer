# Fantasy Basketball Debriefer

Zero-cost automated pipeline that monitors a YouTube channel via its native RSS feed, summarizes new uploads with Gemini (`gemini-3.8-flash`, with automatic fallback), and posts the summary to a private Discord channel via webhook.

## Setup

1. Add the following **Repository Secrets** under **Settings → Secrets and variables → Actions**:
   - `YOUTUBE_CHANNEL_ID`
   - `GEMINI_API_KEY`
   - `DISCORD_WEBHOOK_URL`
2. Trigger **Actions → YouTube Summary Pipeline → Run workflow** once to seed `seen_videos.json` without spamming Discord.
3. Schedule runs externally via **cron-job.org** (`POST` to `https://api.github.com/repos/denzelkwan/fantasy_basketball_debriefer/actions/workflows/summarize.yml/dispatches` with `{"ref":"main"}` and a repo-scoped Fine-grained PAT with `Actions: Read and write`). GitHub's built-in `schedule` cron is disabled to avoid dropped runs.

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
