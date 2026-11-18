import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from google import genai
from google.genai import types

CHANNEL_ID = os.environ["YOUTUBE_CHANNEL_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

STATE_FILE = "seen_videos.json"
RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"


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


def fetch_rss_entries() -> list[dict[str, str]]:
    """Fetch and parse YouTube channel RSS feed entries, oldest first."""
    req = urllib.request.Request(RSS_URL, headers={"User-Agent": "Mozilla/5.0"})
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


def summarize_video(video_url: str) -> str:
    """Generate a condensed video summary using Gemini."""
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = (
        "Provide a condensed summary of this video under 3,500 characters. Include:\n"
        "1. **Core Thesis** (1-2 sentences)\n"
        "2. **Key Takeaways** (bullet points with timestamps)\n"
        "3. **Actionable Advice or Conclusions**"
    )

    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=[
            types.Part.from_uri(file_uri=video_url, mime_type="video/mp4"),
            prompt,
        ],
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty summary.")
    return response.text


def send_discord_message(title: str, url: str, summary: str) -> None:
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
        DISCORD_WEBHOOK_URL,
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


def main() -> None:
    """Check for new videos, summarize them, notify Discord, and update state."""
    seen = load_seen_videos()
    entries = fetch_rss_entries()

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
            summary = summarize_video(video["url"])
            send_discord_message(video["title"], video["url"], summary)
            seen.append(video["id"])
            save_seen_videos(seen)
        except Exception as e:
            print(f"Failed to process {video['id']}: {e}")


if __name__ == "__main__":
    main()
