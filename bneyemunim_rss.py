#!/usr/bin/env python3
"""
bneyemunim_rss.py — בונה ומעדכן פיד RSS מדף "סיפורי ר' שרגי על תפילה"
באתר bneyemunim.co.il.

מבנה שאומת מול קוד המקור האמיתי של הדף: כל פרק מופיע כ-
    <h2 class="elementor-heading-title elementor-size-default">כותרת</h2>
    ... (בהמשך אותו בלוק)
    <audio class="jet-audio-player" ... src="<כתובת mp3 נקייה>" ...>

הכל בעמוד אחד סטטי, בלי עימוד או AJAX - קל יחסית לשאר האתרים.

הרצה:
    pip install requests
    python3 bneyemunim_rss.py
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

PAGE_URL = "https://www.bneyemunim.co.il/%d7%a1%d7%99%d7%a4%d7%95%d7%a8%d7%99-%d7%a8-%d7%a9%d7%a8%d7%92%d7%99-%d7%a2%d7%9c-%d7%aa%d7%a4%d7%99%d7%9c%d7%94/"

OUTPUT_XML = "feed_bneyemunim.xml"
STATE_FILE = "state_bneyemunim.json"
REQUEST_TIMEOUT = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# ======================================================================


def clean_text(raw):
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


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


def parse_episodes(page_html):
    """
    מפצל את הדף לפי כל כותרת <h2 class="elementor-heading-title...">
    ומחלץ מהבלוק שאחריה את תג ה-audio עם ה-src הנקי.
    """
    episodes = []
    blocks = re.split(r'<h2 class="elementor-heading-title[^"]*">', page_html)
    for block in blocks[1:]:
        title_match = re.match(r'([^<]+)</h2>', block)
        if not title_match:
            continue
        title = clean_text(title_match.group(1))

        audio_match = re.search(r'<audio[^>]+src="([^"]+)"', block)
        if not audio_match:
            continue
        audio_url = html.unescape(audio_match.group(1))

        episodes.append({
            "title": title,
            "audio_url": audio_url,
        })
    return episodes


def fetch_filesize(audio_url):
    try:
        resp = SESSION.head(audio_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        size = resp.headers.get("Content-Length")
        return int(size) if size else 0
    except (requests.RequestException, ValueError, TypeError):
        return 0


def normalize_episode(ep, index):
    return {
        "title": ep["title"] or "(ללא כותרת)",
        "description": ep["title"],
        "guid": f"bneyemunim-{index}-{ep['title']}",
        "audio_url": quote(ep["audio_url"], safe=":/?=&%"),
        "filesize": ep.get("filesize", 0),
    }


def build_episode_xml(ep, pub_date):
    return f"""    <item>
      <title>{escape(ep['title'])}</title>
      <description>{escape(ep['description'])}</description>
      <guid isPermaLink="false">{escape(ep['guid'])}</guid>
      <pubDate>{pub_date}</pubDate>
      <enclosure url="{escape(ep['audio_url'])}" length="{ep['filesize']}" type="audio/mpeg"/>
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
    <title>בני אמונים - סיפורי ר' שרגי על תפילה</title>
    <description>סיפורי ר' שרגי על מעלת התפילה - bneyemunim.co.il</description>
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

    print("[2/3] מחלץ פרקים...")
    raw_episodes = parse_episodes(page_html)
    print(f"      נמצאו {len(raw_episodes)} פרקים")

    print("      שולף גדלי קבצים...")
    for ep in raw_episodes:
        ep["filesize"] = fetch_filesize(ep["audio_url"])

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
