#!/usr/bin/env python3
"""
kolhalashon_rss_4859.py — בונה ומעדכן פיד RSS לשיעורים של רב/עמוד מסוים
באתר kolhalashon.com (מזהה GeneralID/RavID: 4859), ישירות מתוך ה-API
הפנימי שלו.

מבנה שאומת מול תעבורת רשת אמיתית מהאתר:

  1. שליפת רשימת השיעורים:
     POST https://www.kolhalashon.com/api/Search/WebSite_GetRavShiurim/
     Content-Type: application/json
     Body: {
       "QueryType": -1, "LangID": -1, "MasechetID": -1, "DafNo": -1,
       "MasechetIDY": -1, "DafNoY": -1, "MoedID": -1, "CustomBool": false,
       "DafNoYOz": -1, "EnglishDisplay": false,
       "FilterSwitch": "111...1" (99 פעמים "1"),
       "FiltersArray": [], "FromRow": <עימוד, מתחיל מ-0>,
       "GeneralID": 4859, "NumOfRows": 24, "ParashaID": -1,
       "PrefferedLanguage": -1, "SearchOrder": 7, "activefilterType": "all"
     }
     מחזיר: רשימת שיעורים, כל אחד עם FileId, TitleHebrew, ShiurDuration,
     RecordDate וכו'. ממשיכים לבקש FromRow הבא (מתווסף NumOfRows בכל פעם)
     עד שמתקבלת רשימה ריקה.

  2. כתובת קובץ ה-mp3 של כל שיעור (אומתה ישירות מול השרת):
     https://www.kolhalashon.com/api/files/GetMp3FileToPlay/<FileId>

הרצה:
    pip install requests
    python3 kolhalashon_rss_4859.py
"""

import json
import os
import re
import html
from datetime import datetime, timezone, timedelta
from xml.sax.saxutils import escape

import requests

# ============================== הגדרות ==============================

BASE_URL = "https://www.kolhalashon.com"
SEARCH_URL = f"{BASE_URL}/api/Search/WebSite_GetRavShiurim/"
AUDIO_URL_TEMPLATE = f"{BASE_URL}/api/files/GetMp3FileToPlay/{{file_id}}"

GENERAL_ID = 4859                 # מזהה הרב/העמוד
NUM_OF_ROWS = 24                  # כמות שיעורים לעמוד (כמו שהאתר עצמו משתמש)
MAX_PAGES = 100                   # תקרת בטיחות

OUTPUT_XML = "feed_kolhalashon_4859.xml"
STATE_FILE = "state_kolhalashon_4859.json"
REQUEST_TIMEOUT = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": f"{BASE_URL}/he/regularSite/ravs/{GENERAL_ID}/1/1",
}

FILTER_SWITCH = "1" * 99  # כפי שנצפה בבקשה האמיתית מהדפדפן

# ======================================================================


def clean_text(raw):
    if not raw:
        return ""
    text = html.unescape(str(raw))
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def israel_utc_offset(dt):
    return timedelta(hours=3) if 3 <= dt.month <= 10 else timedelta(hours=2)


def local_to_rfc822(date_str):
    """ממיר תאריך ("YYYY-MM-DDTHH:MM:SS...", זמן מקומי ישראל) ל-RFC 822."""
    try:
        dt = datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    offset = israel_utc_offset(dt)
    dt = dt.replace(tzinfo=timezone(offset))
    return dt.strftime("%a, %d %b %Y %H:%M:%S %z")


def duration_to_hhmmss(duration_str):
    """ShiurDuration כבר מגיע בפורמט HH:MM:SS - מוודאים שזה תקין ומחזירים כמות שהוא."""
    if re.match(r"^\d{2}:\d{2}:\d{2}$", str(duration_str or "")):
        return duration_str
    return "00:00:00"


def build_request_body(from_row):
    return {
        "QueryType": -1,
        "LangID": -1,
        "MasechetID": -1,
        "DafNo": -1,
        "MasechetIDY": -1,
        "DafNoY": -1,
        "MoedID": -1,
        "CustomBool": False,
        "DafNoYOz": -1,
        "EnglishDisplay": False,
        "FilterSwitch": FILTER_SWITCH,
        "FiltersArray": [],
        "FromRow": from_row,
        "GeneralID": GENERAL_ID,
        "NumOfRows": NUM_OF_ROWS,
        "ParashaID": -1,
        "PrefferedLanguage": -1,
        "SearchOrder": 7,
        "activefilterType": "all",
    }


def fetch_all_shiurim():
    all_items = []
    from_row = 0
    for page in range(1, MAX_PAGES + 1):
        try:
            resp = requests.post(
                SEARCH_URL,
                json=build_request_body(from_row),
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                print(f"  [!] עמוד {page} (FromRow={from_row}) -> HTTP {resp.status_code}")
                break
            items = resp.json()
        except (requests.RequestException, ValueError) as e:
            print(f"  [!] שגיאה בעמוד {page}: {e}")
            break

        if not items:
            print(f"  [.] עמוד {page} ריק - מסיים")
            break

        all_items.extend(items)
        print(f"  [.] עמוד {page} - {len(items)} שיעורים (FromRow={from_row})")

        if len(items) < NUM_OF_ROWS:
            break  # זה היה העמוד האחרון (חלקי)

        from_row += NUM_OF_ROWS

    return all_items


def normalize_shiur(item):
    file_id = item.get("FileId")
    title = clean_text(item.get("TitleHebrew", ""))
    topic = clean_text(item.get("MainTopicHebrew", ""))
    description = topic or title
    pub_date = local_to_rfc822(item.get("RecordDate", ""))
    duration = duration_to_hhmmss(item.get("ShiurDuration", ""))
    audio_url = AUDIO_URL_TEMPLATE.format(file_id=file_id)

    return {
        "title": title or "(ללא כותרת)",
        "description": description,
        "link": f"{BASE_URL}/he/regularSite/ravs/{GENERAL_ID}/1/1",
        "guid": str(file_id),
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


def build_feed(channel_title, episodes):
    items_xml = "\n".join(build_episode_xml(ep) for ep in episodes if ep["audio_url"])
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    link = f"{BASE_URL}/he/regularSite/ravs/{GENERAL_ID}/1/1"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{escape(channel_title)}</title>
    <description>{escape(channel_title)} - קול הלשון</description>
    <link>{escape(link)}</link>
    <language>he-il</language>
    <lastBuildDate>{now}</lastBuildDate>
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
    print(f"[1/3] שולף את כל השיעורים של GeneralID={GENERAL_ID}...")
    raw_items = fetch_all_shiurim()
    print(f"      נמצאו {len(raw_items)} שיעורים בסה\"כ")

    if not raw_items:
        print("      לא נמצאו שיעורים - עוצר")
        return

    channel_title = clean_text(raw_items[0].get("UserNameHebrew", "")) or f"קול הלשון - {GENERAL_ID}"

    print("[2/3] מנרמל שיעורים...")
    episodes = [normalize_shiur(item) for item in raw_items]
    episodes = [ep for ep in episodes if ep["audio_url"]]
    episodes.sort(key=lambda e: e["pub_date"], reverse=True)

    state = load_state()
    known = set(state.get("known_guids", []))
    new_guids = [ep["guid"] for ep in episodes if ep["guid"] not in known]
    print(f"      {len(new_guids)} שיעורים חדשים מאז הריצה האחרונה")

    print("[3/3] בונה ושומר את קובץ ה-RSS...")
    feed_xml = build_feed(channel_title, episodes)
    with open(OUTPUT_XML, "w", encoding="utf-8") as f:
        f.write(feed_xml)

    state["known_guids"] = [ep["guid"] for ep in episodes]
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    print(f"\nהושלם: {OUTPUT_XML} מכיל {len(episodes)} שיעורים.")


if __name__ == "__main__":
    main()
