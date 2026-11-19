import argparse
import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from google import genai
from google.genai import errors, types

STATE_FILE = "seen_videos.json"
DEFAULT_MODELS = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]


def load_dotenv(path: str = ".env") -> None:
    """Load key=value pairs from a local .env file without overriding existing env vars."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require_env(name: str) -> str:
    """Return a required environment variable or raise a clear error."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_seen_videos() -> list[str]:
    """Load previously processed video IDs from disk."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_seen_videos(video_ids: list[str]) -> None:
    """Persist the most recent 100 processed video IDs to disk."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(video_ids[-100:], f, indent=2)


def fetch_rss_entries(channel_id: str) -> list[dict[str, str]]:
    """Fetch and parse YouTube channel RSS feed entries, oldest first."""
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as response:
        xml_data = response.read()

    root = ET.fromstring(xml_data)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
    }

    entries = []
    for entry in root.findall("atom:entry", ns):
        video_id_el = entry.find("yt:videoId", ns)
        title_el = entry.find("atom:title", ns)
        if video_id_el is None or not video_id_el.text or title_el is None:
            continue
        video_id = video_id_el.text
        title = title_el.text or "Untitled Video"
        link = f"https://www.youtube.com/watch?v={video_id}"
        entries.append({"id": video_id, "title": title, "url": link})

    # Process oldest unseen videos first
    return list(reversed(entries))


def summarize_video(
    video_url: str, api_key: str, model: str | None = None
) -> str:
    """Generate a condensed video summary using Gemini, with fallback on 503/server errors."""
    client = genai.Client(api_key=api_key)
    prompt = (
        "You are an NBA fantasy basketball assistant summarizing this video for a 9-cat, 12-team "
        "league manager making add, drop, hold, and streaming decisions.\n\n"
        "Rules:\n"
        "- Report ONLY players, injuries, trades, schedule notes, and recommendations mentioned in the video.\n"
        "- Prioritize 9-cat value (categories, efficiency, minutes/usage) and 12-team relevance, "
        "but note if the creator specifies 10-team or 14-team thresholds.\n"
        "- Ignore intros, sponsor reads, and non-fantasy banter.\n"
        "- Keep the entire response under 3,500 characters.\n"
        "- Use Discord-friendly markdown (bold text and bullet points only; NO markdown tables).\n"
        "- Be ultra-concise—use short fragments, not full paragraphs.\n\n"
        "Format your response as:\n\n"
        "**Big Picture / Schedule Notes** (1-2 bullets max, omit if none)\n"
        "- Key team schedules (e.g., high-volume game weeks), major injury/trade news affecting multiple players.\n\n"
        "**Player Takeaways**\n"
        "For each player discussed, use one bullet in this exact format:\n"
        "- **[VERDICT] Player Name (League size if specified, e.g. 10T/12T/14T)** — "
        "*Reason in <=15 words* (e.g., minutes/usage trend, 9-cat impact, injury/trade beneficiary, "
        "fluke warning, or schedule boost).\n\n"
        "Use only these verdicts: ADD, STREAM, BUY LOW / HOLD, SELL HIGH, DROP, IGNORE (Fluke)."
    )

    models_to_try = [model] if model else DEFAULT_MODELS
    last_error: Exception | None = None

    for candidate in models_to_try:
        attempt_start = time.perf_counter()
        try:
            response = client.models.generate_content(
                model=candidate,
                contents=[
                    types.Part.from_uri(file_uri=video_url, mime_type="video/mp4"),
                    prompt,
                ],
                config=types.GenerateContentConfig(
                    media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
                    thinking_config=types.ThinkingConfig(
                        thinking_level=types.ThinkingLevel.LOW,
                    ),
                ),
            )
            if not response.text:
                raise RuntimeError("Gemini returned an empty summary.")
            attempt_elapsed = time.perf_counter() - attempt_start
            print(f"[Model] Succeeded with {candidate} in {attempt_elapsed:.2f}s")
            return response.text
        except errors.APIError as exc:
            attempt_elapsed = time.perf_counter() - attempt_start
            if exc.code not in (404, 429, 500, 502, 503, 504):
                raise
            last_error = exc
            print(
                f"[Model] {candidate} failed ({exc.code}) after {attempt_elapsed:.2f}s; "
                "trying fallback..."
            )

    raise last_error or RuntimeError("All Gemini models failed.")


def send_discord_message(title: str, url: str, summary: str, webhook_url: str) -> None:
    """Post the video summary to Discord as an embed."""
    # Discord embeds allow up to 4,096 characters in the description
    truncated_summary = summary[:4000] + ("..." if len(summary) > 4000 else "")

    payload = {
        "username": "YouTube Summarizer",
        "embeds": [
            {
                "title": title[:256],
                "url": url,
                "description": truncated_summary,
                "color": 16711680,  # YouTube red
            }
        ],
    }

    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        if response.status not in (200, 204):
            raise RuntimeError(f"Discord returned status {response.status}")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for local testing vs. normal pipeline execution."""
    parser = argparse.ArgumentParser(description="Automated YouTube Summary Pipeline")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--test-url",
        help="Summarize a single YouTube URL without modifying seen_videos.json.",
    )
    mode.add_argument(
        "--latest",
        action="store_true",
        help="Summarize the newest video from YOUTUBE_CHANNEL_ID without modifying seen_videos.json.",
    )
    parser.add_argument(
        "--send-discord",
        action="store_true",
        help="Also post the test summary to DISCORD_WEBHOOK_URL (only with --test-url or --latest).",
    )
    parser.add_argument(
        "--model",
        help="Override the Gemini model (e.g. gemini-3.6-flash).",
    )
    args = parser.parse_args()
    if args.send_discord and not (args.test_url or args.latest):
        parser.error("--send-discord requires --test-url or --latest")
    return args


def fetch_video_title(video_url: str) -> str:
    """Fetch a YouTube video's title via oEmbed, falling back to a generic label."""
    oembed_url = (
        "https://www.youtube.com/oembed?"
        + urllib.parse.urlencode({"url": video_url, "format": "json"})
    )
    req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("title") or "Test Video Summary"
    except Exception:
        return "Test Video Summary"


def run_test_mode(args: argparse.Namespace) -> None:
    """Run a single-video dry run without updating seen_videos.json."""
    api_key = require_env("GEMINI_API_KEY")

    if args.test_url:
        url = args.test_url
        title = fetch_video_title(url)
    else:
        channel_id = require_env("YOUTUBE_CHANNEL_ID")
        entries = fetch_rss_entries(channel_id)
        if not entries:
            print("No videos found in RSS feed.")
            return
        latest = entries[-1]
        title = latest["title"]
        url = latest["url"]

    print(f"Summarizing (dry run): {title} ({url})\n")
    start = time.perf_counter()
    summary = summarize_video(url, api_key, model=args.model)
    elapsed = time.perf_counter() - start
    print(f"=== {title} ===\n{url}\n\n{summary}\n\n[Summary generated in {elapsed:.2f}s]")

    if args.send_discord:
        webhook_url = require_env("DISCORD_WEBHOOK_URL")
        send_discord_message(title, url, summary, webhook_url)
        print("\nPosted test summary to Discord.")


def main() -> None:
    """Check for new videos, summarize them, notify Discord, and update state."""
    load_dotenv()
    args = parse_args()

    if args.test_url or args.latest:
        run_test_mode(args)
        return

    channel_id = require_env("YOUTUBE_CHANNEL_ID")
    api_key = require_env("GEMINI_API_KEY")
    webhook_url = require_env("DISCORD_WEBHOOK_URL")

    seen = load_seen_videos()
    entries = fetch_rss_entries(channel_id)

    # Seed existing videos on first run without triggering summaries
    if not seen and entries:
        print("First run detected. Seeding existing videos without summarizing.")
        save_seen_videos([e["id"] for e in entries])
        return

    new_entries = [e for e in entries if e["id"] not in seen]
    if not new_entries:
        print("No new videos found.")
        return

    for video in new_entries:
        print(f"Summarizing: {video['title']} ({video['url']})")
        try:
            summary = summarize_video(video["url"], api_key, model=args.model)
            send_discord_message(video["title"], video["url"], summary, webhook_url)
            seen.append(video["id"])
            save_seen_videos(seen)
        except Exception as e:
            print(f"Failed to process {video['id']}: {e}")


if __name__ == "__main__":
    main()
