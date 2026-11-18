# Fantasy Basketball Debriefer

Zero-cost automated pipeline that monitors a YouTube channel via its native RSS feed, summarizes new uploads with Gemini (`gemini-3.5-flash`), and posts the summary to a private Discord channel via webhook.

## Setup

1. Add the following **Repository Secrets** under **Settings → Secrets and variables → Actions**:
   - `YOUTUBE_CHANNEL_ID`
   - `GEMINI_API_KEY`
   - `DISCORD_WEBHOOK_URL`
2. Run **Actions → YouTube Summary Pipeline → Run workflow** once to seed `seen_videos.json` with existing videos without spamming Discord.
3. Subsequent runs execute automatically every 4 hours (`15 */4 * * *`).
