#!/usr/bin/env python3
"""
achiyayeda_rss.py — בונה ומעדכן פיד RSS מכל קבצי השמע בתגית "סיפור
לשמיעה" (material_tags) באתר achiyayeda.org.

מבנה שאומת מול תעבורת אמיתית מהאתר:
  1. דף הרשימה (https://achiyayeda.org/material_tags/<tag-slug>/) מכיל
     קישורים לעמודי פריט בודדים (https://achiyayeda.org/material/<slug>/)
  2. עימוד וורדפרס סטנדרטי: .../page/2/, .../page/3/ וכו'
  3. כל עמוד פריט מכיל ישירות קישור לקובץ mp3 סטטי, גלוי בלי הגנה
     (wp-content/uploads/.../file.mp3) - זה אומת ידנית מול הדפדפן
     ואינו דורש הרשמה/התחברות לצפייה/האזנה עצמה (רק לכפתור "הורדה
     מהירה" בעמוד הרשימה יש דרישת הרשמה, לא לתוכן בעמוד הפריט עצמו).

הרצה:
    pip install requests
    python3 achiyayeda_rss.py
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

BASE_URL = "https://achiyayeda.org"
TAG_SLUG = "%D7%A1%D7%99%D7%A4%D7%95%D7%A8-%D7%9C%D7%A9%D7%9E%D7%99%D7%A2%D7%94"  # סיפור-לשמיעה
TAG_URL = f"{BASE_URL}/material_tags/{TAG_SLUG}/"

MAX_PAGES = 50
OUTPUT_XML = "feed_achiyayeda.xml"
STATE_FILE = "state_achiyayeda.json"
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


def fetch(url):
    try:
        resp = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return None
        return resp.text
    except requests.RequestException as e:
        print(f"  [!] שגיאת רשת ב-{url}: {e}")
        return None


def extract_material_links(page_html):
    """
    מחלץ קישורים לעמודי פריט בודדים. חשוב: מסננים החוצה קישורי ניווט
    "מזוהמים" שמופיעים באתר עם סיומת מספרית נוספת (כמו .../material/<slug>/202) -
    אלה לא פריטים אמיתיים, רק קישורי תפריט צדדיים. פריט אמיתי מסתיים
    ב-"/" ממש לפני המרכאות הסוגרות.
    """
    links = re.findall(r'href="(https://achiyayeda\.org/material/[^"/]+/)"', page_html)
    return sorted(set(links))


def fetch_all_material_links():
    all_links = set()
    for page in range(1, MAX_PAGES + 1):
        url = TAG_URL if page == 1 else f"{TAG_URL}page/{page}/"
        page_html = fetch(url)
        if not page_html:
            print(f"  [.] עמוד {page} לא נטען - מסיים")
            break
        links = extract_material_links(page_html)
        new_links = [l for l in links if l not in all_links]
        if not links:
            print(f"  [.] עמוד {page} לא הכיל פריטים - מסיים")
            break
        all_links.update(links)
        print(f"  [.] עמוד {page}: {len(links)} קישורים ({len(new_links)} חדשים), סה\"כ עד כה: {len(all_links)}")
        if not new_links and page > 1:
            print("      אין קישורים חדשים - כנראה הגענו לסוף (חוזר על עצמו) - מסיים")
            break
    return sorted(all_links)


def parse_material_page(material_html, material_url):
    """מחלץ כותרת, מחבר, קטגוריה, וכתובת mp3 מתוך עמוד פריט בודד."""
    mp3_match = re.search(
        r'(https://achiyayeda\.org/wp-content/uploads/[^"\'\s)\]<>(]+\.mp3)', material_html
    )
    if not mp3_match:
        return None
    audio_url = html.unescape(mp3_match.group(1))

    title = ""
    h1_match = re.search(r'<h1[^>]*>([^<]+)</h1>', material_html)
    if h1_match:
        title = clean_text(h1_match.group(1))
    if not title:
        title_tag_match = re.search(r'<title>([^<]+)</title>', material_html)
        if title_tag_match:
            title = clean_text(title_tag_match.group(1)).split(" – ")[0].split(" - ")[0]

    author = ""
    author_match = re.search(r'מחבר:\s*</[^>]+>\s*([^<]+)<', material_html)
    if not author_match:
        author_match = re.search(r'מחבר[:\s]+([^\n<]{2,60})', material_html)
    if author_match:
        author = clean_text(author_match.group(1))

    category = ""
    category_match = re.search(r'קטגוריה:\s*</[^>]+>\s*([^<]+)<', material_html)
    if not category_match:
        category_match = re.search(r'קטגוריה[:\s]+([^\n<]{2,60})', material_html)
    if category_match:
        category = clean_text(category_match.group(1))

    # מזהה ייחודי מתוך ה-slug של הכתובת (חלק אחרי /material/ ולפני ה-/ הסופי)
    slug_match = re.search(r'/material/([^/]+)/$', material_url)
    guid = slug_match.group(1) if slug_match else material_url

    return {
        "title": title or "(ללא כותרת)",
        "author": author,
        "category": category,
        "link": material_url,
        "audio_url": audio_url,
        "guid": guid,
    }


def fetch_filesize(audio_url):
    """שולף גודל קובץ אמיתי - חשוב לנגינה תקינה בחלק מהנגנים."""
    try:
        resp = SESSION.head(audio_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        size = resp.headers.get("Content-Length")
        return int(size) if size else 0
    except (requests.RequestException, ValueError, TypeError):
        return 0


def normalize_episode(item):
    title = item["title"]
    if item["author"]:
        title = f"{title} - {item['author']}"
    description = title
    if item["category"]:
        description = f"{title} ({item['category']})"

    return {
        "title": title,
        "description": description,
        "link": quote(item["link"], safe=":/?=&%"),
        "guid": item["guid"],
        "audio_url": quote(item["audio_url"], safe=":/?=&%"),
        "filesize": item.get("filesize", 0),
    }


def build_episode_xml(ep, pub_date):
    return f"""    <item>
      <title>{escape(ep['title'])}</title>
      <description>{escape(ep['description'])}</description>
      <link>{escape(ep['link'])}</link>
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
    <title>אחיה ידע - סיפור לשמיעה</title>
    <description>כל קבצי השמע בתגית "סיפור לשמיעה" - achiyayeda.org</description>
    <link>{escape(TAG_URL)}</link>
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
    print(f"[1/4] אוסף קישורים לכל הפריטים מתוך: {TAG_URL}")
    material_links = fetch_all_material_links()
    print(f"      נמצאו {len(material_links)} פריטים בסה\"כ")

    print("[2/4] נכנס לכל עמוד פריט ומחלץ כתובת mp3...")
    items = []
    for i, url in enumerate(material_links, 1):
        material_html = fetch(url)
        if not material_html:
            continue
        item = parse_material_page(material_html, url)
        if item:
            items.append(item)
        if i % 20 == 0:
            print(f"      עובד {i}/{len(material_links)}...")
    print(f"      חולצו {len(items)} פריטים עם קובץ שמע תקין")

    print("[3/4] שולף גדלי קבצים...")
    size_cache = {}
    for i, item in enumerate(items, 1):
        url = item["audio_url"]
        if url not in size_cache:
            size_cache[url] = fetch_filesize(url)
        item["filesize"] = size_cache[url]
        if i % 20 == 0:
            print(f"      נבדקו {i}/{len(items)}...")

    episodes = [normalize_episode(item) for item in items]

    state = load_state()
    known = set(state.get("known_guids", []))
    new_guids = [ep["guid"] for ep in episodes if ep["guid"] not in known]
    print(f"      {len(new_guids)} פריטים חדשים מאז הריצה האחרונה")

    print("[4/4] בונה ושומר את קובץ ה-RSS...")
    feed_xml = build_feed(episodes)
    with open(OUTPUT_XML, "w", encoding="utf-8") as f:
        f.write(feed_xml)

    state["known_guids"] = [ep["guid"] for ep in episodes]
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    print(f"\nהושלם: {OUTPUT_XML} מכיל {len(episodes)} פריטים.")


if __name__ == "__main__":
    main()
