#!/usr/bin/env python3
"""
doscast_rss_430.py — בונה ומעדכן פיד RSS לפודקאסט "המזרחן" (podcast_id 430)
מאתר doscast.co.il, ישירות מתוך ה-API הפנימי שלו.

מבנה שאומת מול תעבורת רשת אמיתית מהאתר:
    POST https://api.doscast.co.il/api/podcasts/get
    Content-Type: application/json
    Body: {"id": "430"}

    מחזיר JSON: {"data": {..., "episodes": [...]}}

כל פרק כולל audio_parse (קובץ מתארח בשרתי doscast עצמם - עדיף) או
audio_link (מקור חיצוני, למשל listenbox/podbean) כגיבוי.

הרצה:
    pip install requests
    python3 doscast_rss_430.py
"""

import json
import os
import re
import html
from datetime import datetime, timezone, timedelta
from xml.sax.saxutils import escape

import requests

# ============================== הגדרות ==============================

API_URL = "https://api.doscast.co.il/api/podcasts/get"
PODCAST_ID = "430"                # מזהה הפודקאסט - "המזרחן"

OUTPUT_XML = "feed_doscast_430.xml"
STATE_FILE = "state_doscast_430.json"
REQUEST_TIMEOUT = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": "https://www.doscast.co.il/",
}

# ======================================================================


def clean_text(raw):
    """מנקה HTML entities ותגי HTML מטקסט."""
    if not raw:
        return ""
    text = html.unescape(str(raw))
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def israel_utc_offset(dt):
    """הערכה גסה של offset ישראל: קיץ (IDT, UTC+3) בערך אפריל-אוקטובר."""
    return timedelta(hours=3) if 3 <= dt.month <= 10 else timedelta(hours=2)


def local_to_rfc822(date_str):
    """ממיר תאריך ("YYYY-MM-DD HH:MM:SS", זמן מקומי ישראל) ל-RFC 822."""
    try:
        dt = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    offset = israel_utc_offset(dt)
    dt = dt.replace(tzinfo=timezone(offset))
    return dt.strftime("%a, %d %b %Y %H:%M:%S %z")


def seconds_to_hhmmss(duration):
    try:
        total = int(duration)
    except (ValueError, TypeError):
        return "00:00:00"
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fetch_podcast_data():
    try:
        resp = requests.post(
            API_URL,
            json={"id": PODCAST_ID},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            print(f"  [!] {API_URL} -> HTTP {resp.status_code}")
            return None
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  [!] שגיאה: {e}")
        return None


def normalize_episode(ep):
    title = clean_text(ep.get("title", ""))
    description = clean_text(ep.get("description", "")) or title
    # מעדיפים audio_parse (קובץ שמתארח אצל doscast עצמם) על פני audio_link
    # (מקור חיצוני, שעלול להיעלם או להשתנות)
    audio_url = ep.get("audio_parse") or ep.get("audio_link", "")
    guid = str(ep.get("rss_guid") or ep.get("id", ""))
    link = ep.get("share_url", "")
    pub_date = local_to_rfc822(ep.get("date", ""))
    duration = seconds_to_hhmmss(ep.get("duration", 0))

    return {
        "title": title or "(ללא כותרת)",
        "description": description,
        "link": link,
        "guid": guid,
        "pub_date": pub_date,
        "audio_url": audio_url,
        "duration": duration,
    }


def build_episode_xml(ep):
    return f"""    <item>
      <title>{escape(ep['title'])}</title>
      <description>{escape(ep['description'])}</description>
      <link>{escape(ep['link'])}</link>
      <guid isPermaLink="false">{escape(ep['guid'])}</guid>
      <pubDate>{ep['pub_date']}</pubDate>
      <enclosure url="{escape(ep['audio_url'])}" length="0" type="audio/mpeg"/>
      <itunes:duration>{ep['duration']}</itunes:duration>
    </item>"""


def build_feed(podcast_info, episodes):
    items_xml = "\n".join(build_episode_xml(ep) for ep in episodes if ep["audio_url"])
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    title = clean_text(podcast_info.get("title", ""))
    description = clean_text(podcast_info.get("description", "")) or title
    image = podcast_info.get("pic_big", "")
    link = podcast_info.get("share_url", "")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{escape(title)}</title>
    <description>{escape(description)}</description>
    <link>{escape(link)}</link>
    <language>he-il</language>
    <lastBuildDate>{now}</lastBuildDate>
    <itunes:image href="{escape(image)}"/>
{items_xml}
  </channel>
</rss>
"""


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"known_guids": []}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def main():
    print(f"[1/3] שולף נתוני פודקאסט {PODCAST_ID} מ-{API_URL}...")
    raw = fetch_podcast_data()
    if not raw or "data" not in raw:
        print("      נכשל - לא התקבלו נתונים תקינים")
        return

    podcast_info = raw["data"]
    print(f"      פודקאסט: {clean_text(podcast_info.get('title', ''))}")

    print("[2/3] מנרמל פרקים...")
    raw_episodes = podcast_info.get("episodes", [])
    episodes = [normalize_episode(ep) for ep in raw_episodes]
    episodes = [ep for ep in episodes if ep["audio_url"]]
    episodes.sort(key=lambda e: e["pub_date"], reverse=True)
    print(f"      נמצאו {len(episodes)} פרקים עם קובץ שמע תקין")

    state = load_state()
    known = set(state.get("known_guids", []))
    new_guids = [ep["guid"] for ep in episodes if ep["guid"] not in known]
    print(f"      {len(new_guids)} פרקים חדשים מאז הריצה האחרונה")

    print("[3/3] בונה ושומר את קובץ ה-RSS...")
    feed_xml = build_feed(podcast_info, episodes)
    with open(OUTPUT_XML, "w", encoding="utf-8") as f:
        f.write(feed_xml)

    state["known_guids"] = [ep["guid"] for ep in episodes]
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    print(f"\nהושלם: {OUTPUT_XML} מכיל {len(episodes)} פרקים.")


if __name__ == "__main__":
    main()
