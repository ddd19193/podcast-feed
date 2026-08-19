#!/usr/bin/env python3
"""
pneimelech_rss.py — בונה ומעדכן פיד RSS מכל קבצי השמע בעמוד "ספורים"
באתר pneimelech.com.

מבנה שאומת מול קוד המקור האמיתי של הדף: מערך JSON טעון סטטית (לא AJAX)
בתוך תג <script>, בפורמט:

    [
      {"listName": "<שם קטגוריה>", "list": [
        {"url": "<כתובת mp3/ogg>", "name": "<שם פרק>", "playtime": "MM:SS",
         "fid": <מספר>, "saf": "publish"},
        ...
      ]},
      ...
    ]

הערה: אותה כתובת URL חוזרת לפעמים על כמה "פרקים" בעלי שמות שונים (fid
זהה) - זה נראה כמו מבנה נתונים לא לגמרי נקי באתר המקור עצמו, לא שגיאה
בסקריפט. הסקריפט כולל את כולם כפי שהם, עם guid ייחודי מלאכותי (fid +
אינדקס) כדי להימנע מהתנגשויות.

הרצה:
    pip install requests
    python3 pneimelech_rss.py
"""

import json
import os
import re
import html
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from xml.sax.saxutils import escape

import requests

# ============================== הגדרות ==============================

PAGE_URL = "https://pneimelech.com/%d7%a1%d7%99%d7%a4%d7%95%d7%a8%d7%99%d7%9d/"

OUTPUT_XML = "feed_pneimelech.xml"
STATE_FILE = "state_pneimelech.json"
REQUEST_TIMEOUT = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# ======================================================================


def decode_js_string(raw):
    """מפענח מחרוזת עם unicode escapes בסגנון JS (\\u05d0...) לעברית תקינה."""
    if not raw:
        return ""
    try:
        return json.loads('"' + raw.replace('"', '\\"') + '"')
    except (ValueError, json.JSONDecodeError):
        return html.unescape(raw)


def fetch_page():
    try:
        resp = SESSION.get(PAGE_URL, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            print(f"  [!] {PAGE_URL} -> HTTP {resp.status_code}")
            return None
        return resp.text
    except requests.RequestException as e:
        print(f"  [!] שגיאת רשת: {e}")
        return None


def playtime_to_hhmmss(playtime):
    """ממיר משך מפורמט 'MM:SS' או 'H:MM:SS' ל-HH:MM:SS אחיד."""
    parts = (playtime or "").split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return "00:00:00"
    if len(parts) == 2:
        h, m, s = 0, parts[0], parts[1]
    elif len(parts) == 3:
        h, m, s = parts
    else:
        return "00:00:00"
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_categories(page_html):
    """
    מפצל את הדף לפי כל בלוק {"listName":"...", ומחלץ ממנו את שם
    הקטגוריה ואת כל הפרקים בתוך ה-list שלה.
    """
    episodes = []
    blocks = re.split(r'\{"listName":"', page_html)
    for block in blocks[1:]:
        name_match = re.match(r'([^"]*)"', block)
        if not name_match:
            continue
        category_name = decode_js_string(name_match.group(1))

        # חותכים את הבלוק בגבול ה-list הזה בלבד (עד ]} שסוגר את ה-list)
        list_match = re.search(r'"list":\[(.*?)\]\s*\}', block, re.DOTALL)
        if not list_match:
            continue
        list_content = list_match.group(1)

        item_pattern = re.compile(
            r'\{"url":"([^"]*)","name":"([^"]*)","playtime":"([^"]*)",'
            r'"fid":(\d+),"saf":"([^"]*)"\}'
        )
        for item_match in item_pattern.finditer(list_content):
            url, name, playtime, fid, status = item_match.groups()
            if status != "publish":
                continue
            episodes.append({
                "category": category_name,
                "url": decode_js_string(url),
                "name": decode_js_string(name),
                "playtime": playtime,
                "fid": fid,
            })
    return episodes


def fetch_filesize(audio_url):
    """שולף את גודל הקובץ האמיתי (בייטים) דרך בקשת HEAD - חשוב! חלק
    מהנגנים לא מנגנים enclosure עם length="0"."""
    try:
        resp = SESSION.head(audio_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        size = resp.headers.get("Content-Length")
        return int(size) if size else 0
    except (requests.RequestException, ValueError, TypeError):
        return 0


def normalize_episode(ep, index):
    title = ep["name"] or "(ללא כותרת)"
    category = ep["category"]
    full_title = f"{category} - {title}" if category else title
    audio_url = quote(ep["url"], safe=":/?=&%")
    # guid ייחודי מלאכותי - fid לבדו לא מספיק כי הוא חוזר על כמה פרקים
    guid = f"{ep['fid']}-{index}"

    return {
        "title": full_title,
        "description": full_title,
        "guid": guid,
        "audio_url": audio_url,
        "duration": playtime_to_hhmmss(ep["playtime"]),
        "filesize": ep.get("filesize", 0),
    }


def build_episode_xml(ep, pub_date):
    return f"""    <item>
      <title>{escape(ep['title'])}</title>
      <description>{escape(ep['description'])}</description>
      <guid isPermaLink="false">{escape(ep['guid'])}</guid>
      <pubDate>{pub_date}</pubDate>
      <enclosure url="{escape(ep['audio_url'])}" length="{ep['filesize']}" type="audio/mpeg"/>
      <itunes:duration>{ep['duration']}</itunes:duration>
    </item>"""


def build_feed(episodes):
    now = datetime.now(timezone.utc)
    items_xml_parts = []
    for i, ep in enumerate(episodes):
        fake_date = now - timedelta(minutes=i)
        pub_date = fake_date.strftime("%a, %d %b %Y %H:%M:%S %z")
        items_xml_parts.append(build_episode_xml(ep, pub_date))
    items_xml = "\n".join(items_xml_parts)

    now_str = now.strftime("%a, %d %b %Y %H:%M:%S %z")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>פני מלך - ספורים</title>
    <description>כל קבצי השמע - עמוד ספורים, pneimelech.com</description>
    <link>{escape(PAGE_URL)}</link>
    <language>he-il</language>
    <lastBuildDate>{now_str}</lastBuildDate>
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
    print(f"[1/3] מוריד את הדף: {PAGE_URL}")
    page_html = fetch_page()
    if not page_html:
        print("      נכשל - לא ניתן היה להוריד את הדף")
        return

    print("[2/3] מחלץ קטגוריות ופרקים...")
    raw_episodes = parse_categories(page_html)
    print(f"      נמצאו {len(raw_episodes)} פרקים בסה\"כ (בכל הקטגוריות)")

    # שולפים גודל קובץ פעם אחת לכל URL ייחודי (יש כתובות שחוזרות על כמה פרקים)
    print("      שולף גדלי קבצים (HEAD requests, עם caching לכתובות חוזרות)...")
    size_cache = {}
    for i, ep in enumerate(raw_episodes, 1):
        url = ep["url"]
        if url not in size_cache:
            size_cache[url] = fetch_filesize(url)
        ep["filesize"] = size_cache[url]
        if i % 20 == 0:
            print(f"      נבדקו {i}/{len(raw_episodes)} פרקים...")

    episodes = [normalize_episode(ep, i) for i, ep in enumerate(raw_episodes)]

    state = load_state()
    known = set(state.get("known_guids", []))
    new_guids = [ep["guid"] for ep in episodes if ep["guid"] not in known]
    print(f"      {len(new_guids)} פרקים חדשים מאז הריצה האחרונה")

    print("[3/3] בונה ושומר את קובץ ה-RSS...")
    feed_xml = build_feed(episodes)
    with open(OUTPUT_XML, "w", encoding="utf-8") as f:
        f.write(feed_xml)

    state["known_guids"] = [ep["guid"] for ep in episodes]
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    print(f"\nהושלם: {OUTPUT_XML} מכיל {len(episodes)} פרקים.")


if __name__ == "__main__":
    main()
