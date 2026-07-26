#!/usr/bin/env python3
"""
emess_rss_453.py — בונה ומעדכן פיד RSS לתוכנית 453 באתר emess.co.il,
ישירות מתוך ה-REST API הפתוח של וורדפרס.

מבנה שאומת מול נתונים אמיתיים מהאתר:
  - כל הפרקים של כל התוכניות הם מאותו post type: aryo_programs
  - כל פרק מתויג ב-taxonomy בשם tax_broadcasters עם ID של התוכנית שלו
  - ניתן לסנן ישירות: /wp-json/wp/v2/aryo_programs?tax_broadcasters=453
  - קובץ השמע של כל פרק נמצא בשדה audio_in_content[0].audio_file

הרצה:
    pip install requests
    python3 emess_rss_453.py
"""

import json
import os
import re
import sys
import html
from datetime import datetime, timezone, timedelta
from xml.sax.saxutils import escape

import requests

# ============================== הגדרות ==============================

BASE_URL = "https://www.emess.co.il"
POST_TYPE = "aryo_programs"
TAXONOMY = "tax_broadcasters"
TERM_ID = 453                     # מזהה התוכנית
OUTPUT_XML = "feed_453.xml"
STATE_FILE = "state_453.json"

PER_PAGE = 100
REQUEST_TIMEOUT = 20
MAX_PAGES = 50                    # תקרת בטיחות - כמות עמודים מקסימלית לסריקה

# ישראל: IDT (קיץ, UTC+3) בערך אפריל-אוקטובר, IST (חורף, UTC+2) שאר השנה.
# הערכה גסה - אם צריך דיוק מוחלט אפשר להתקין tzdata ולהשתמש ב-zoneinfo.
def israel_utc_offset(dt):
    return timedelta(hours=3) if 3 <= dt.month <= 10 else timedelta(hours=2)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PodcastFeedBuilder/1.0)"
}

# ======================================================================


def clean_text(raw):
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def local_to_rfc822(local_date_str):
    """
    ממיר "date" (זמן מקומי בישראל, כפי שוורדפרס מחזיר) ל-RFC 822 עם offset נכון.
    """
    try:
        dt = datetime.strptime(local_date_str[:19], "%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    offset = israel_utc_offset(dt)
    dt = dt.replace(tzinfo=timezone(offset))
    return dt.strftime("%a, %d %b %Y %H:%M:%S %z")


def get_json(path, params=None):
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            print(f"  [!] {url} -> HTTP {resp.status_code}")
            return None, None
        total_pages = int(resp.headers.get("X-WP-TotalPages", "1"))
        return resp.json(), total_pages
    except requests.RequestException as e:
        print(f"  [!] שגיאת רשת ב-{url}: {e}")
        return None, None
    except ValueError:
        # תגובה לא-JSON תקינה
        return None, None


def fetch_program_name(term_id):
    """שולף את שם התוכנית מתוך ה-taxonomy term עצמו."""
    data, _ = get_json(f"/wp-json/wp/v2/{TAXONOMY}/{term_id}")
    if data and isinstance(data, dict):
        name = clean_text(data.get("name", ""))
        description = clean_text(data.get("description", ""))
        if name:
            return name, description
    return f"תוכנית {term_id}", ""


def fetch_all_episodes(term_id):
    """שולף את כל הפרקים המתויגים בתוכנית הנתונה, עם pagination מלא."""
    all_items = []
    for page in range(1, MAX_PAGES + 1):
        params = {
            TAXONOMY: term_id,
            "per_page": PER_PAGE,
            "page": page,
            "orderby": "date",
            "order": "desc",
        }
        data, total_pages = get_json(f"/wp-json/wp/v2/{POST_TYPE}", params=params)
        if not data:
            break
        if isinstance(data, dict) and data.get("code"):
            print(f"  [!] שגיאת API: {data.get('message')}")
            break
        if not isinstance(data, list) or len(data) == 0:
            break
        all_items.extend(data)
        print(f"  [.] עמוד {page}/{total_pages or '?'} - {len(data)} פריטים")
        if total_pages and page >= total_pages:
            break
    return all_items


def normalize_episode(raw):
    ep_id = raw.get("id")
    title = clean_text(raw.get("title", {}).get("rendered", ""))
    link = raw.get("link", "")
    date_str = raw.get("date", "")
    pub_date = local_to_rfc822(date_str)

    # קובץ השמע - מנסה כמה מקומות אפשריים במבנה.
    # לפעמים כל פריט ברשימה הוא dict ({"audio_file": "..."}), ולפעמים
    # (במבנה נתונים ישן/שונה) הפריט הוא string ישירות - מטפלים בשני המקרים.
    audio_url = ""
    audio_list = raw.get("audio_in_content") or raw.get("extra_data", {}).get("audios_in_content")
    if audio_list and isinstance(audio_list, list) and len(audio_list) > 0:
        first = audio_list[0]
        if isinstance(first, dict):
            audio_url = first.get("audio_file", "")
        elif isinstance(first, str):
            audio_url = first

    # תמונה - featured media forced, אם קיים
    image = ""
    extra = raw.get("extra_data", {})
    if isinstance(extra.get("featured_media_forced"), dict):
        image = extra["featured_media_forced"].get("url", "")

    description = title  # אין content/excerpt בפועל אצל aryo_programs

    return {
        "id": ep_id,
        "title": title or "(ללא כותרת)",
        "description": description,
        "link": link,
        "guid": str(ep_id),
        "pub_date": pub_date,
        "audio_url": audio_url,
        "image": image,
    }


def build_episode_xml(ep):
    img_tag = f'<itunes:image href="{escape(ep["image"])}"/>\n      ' if ep["image"] else ""
    return f"""    <item>
      <title>{escape(ep['title'])}</title>
      <description>{escape(ep['description'])}</description>
      <link>{escape(ep['link'])}</link>
      <guid isPermaLink="false">{escape(ep['guid'])}</guid>
      <pubDate>{ep['pub_date']}</pubDate>
      <enclosure url="{escape(ep['audio_url'])}" length="0" type="audio/mpeg"/>
      {img_tag}</item>"""


def build_feed(program_name, program_description, episodes):
    items_xml = "\n".join(build_episode_xml(ep) for ep in episodes if ep["audio_url"])
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    program_link = f"{BASE_URL}/audio/program/{TERM_ID}"
    # תמונת תוכנית - לוקח מהפרק הראשון שיש לו תמונה
    program_image = next((ep["image"] for ep in episodes if ep["image"]), "")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{escape(program_name)}</title>
    <description>{escape(program_description or program_name)}</description>
    <link>{escape(program_link)}</link>
    <language>he-il</language>
    <lastBuildDate>{now}</lastBuildDate>
    <itunes:image href="{escape(program_image)}"/>
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
    print(f"[1/4] שולף את שם התוכנית (taxonomy term {TERM_ID})...")
    program_name, program_description = fetch_program_name(TERM_ID)
    print(f"      תוכנית: {program_name}")

    print(f"[2/4] שולף את כל הפרקים המתויגים ב-{TAXONOMY}={TERM_ID}...")
    raw_episodes = fetch_all_episodes(TERM_ID)
    episodes = []
    skipped = 0
    for ep in raw_episodes:
        try:
            episodes.append(normalize_episode(ep))
        except Exception as e:
            skipped += 1
            print(f"  [!] דילוג על פרק פגום (id={ep.get('id', '?')}): {e}")
    if skipped:
        print(f"      דולגו {skipped} פרקים עם מבנה נתונים לא תקין")
    episodes = [ep for ep in episodes if ep["audio_url"]]
    episodes.sort(key=lambda e: e["pub_date"], reverse=True)
    print(f"      נמצאו {len(episodes)} פרקים עם קובץ שמע תקין")

    print("[3/4] משווה מול הריצה הקודמת...")
    state = load_state()
    known = set(state.get("known_guids", []))
    new_guids = [ep["guid"] for ep in episodes if ep["guid"] not in known]
    print(f"      {len(new_guids)} פרקים חדשים מאז הריצה האחרונה")

    print("[4/4] בונה ושומר את קובץ ה-RSS...")
    feed_xml = build_feed(program_name, program_description, episodes)
    with open(OUTPUT_XML, "w", encoding="utf-8") as f:
        f.write(feed_xml)

    state["known_guids"] = [ep["guid"] for ep in episodes]
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    print(f"\nהושלם: {OUTPUT_XML} מכיל {len(episodes)} פרקים.")
    if new_guids:
        print("פרקים חדשים שנוספו:")
        for ep in episodes:
            if ep["guid"] in new_guids:
                print(f"  - {ep['title']}")


if __name__ == "__main__":
    main()

# ==========================================================================
# הרצה אוטומטית (cron):
#
#   crontab -e
#   0 * * * * cd /path/to/podcast_feed && python3 emess_rss.py >> log.txt 2>&1
#
#   חשוף את feed.xml דרך שרת ה-web שלך בכתובת קבועה, זו כתובת ה-RSS הסופית.
# ==========================================================================
