#!/usr/bin/env python3
"""
halomot_rss_67.py — בונה ומעדכן פיד RSS מקטגוריית "תוכן חופשי" (category
ID 67) באתר halomothasidiim.co.il.

מבנה שאומת מול תעבורת רשת אמיתית מהאתר:

  1. דף הקטגוריה מכיל את הפרקים הראשונים ישירות ב-HTML, וגם מגדיר:
         LOAD_MORE_AJAX = {"url": "https://halomothasidiim.co.il/wp-admin/admin-ajax.php",
                            "nonce": "<טוקן שמשתנה בכל טעינת דף>"}

  2. עמודים נוספים נשלפים דרך:
     POST https://halomothasidiim.co.il/wp-admin/admin-ajax.php
     action=load_more_posts
     paged=<מספר עמוד, מתחיל מ-2>
     nonce=<הטוקן שחולץ מהדף>
     item_type=audio
     category=67

  3. כל פרק הוא בלוק <article id="audio-<ID>" class="grid-item audio-item">
     עם: קישור לעמוד הפרק, כותרת, ותכונת data-audio עם כתובת ה"נגן"
     (page שמפנה בסופו של דבר לקובץ mp3 האמיתי - podcast apps עוקבים
     אחרי הפניות HTTP אוטומטית).

  4. חשוב לבטיחות: כל פריט נבדק אם הוא "נעול" (lock-cover /
     password-access-cover עם style שאינו "display: none") - פריטים
     נעולים מדולגים ולא נכללים בפיד, כדי לא לפרסם תוכן מוגן בטעות.

הרצה:
    pip install requests
    python3 halomot_rss_67.py
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

BASE_URL = "https://halomothasidiim.co.il"
CATEGORY_SLUG = "%d7%aa%d7%95%d7%9b%d7%9f-%d7%97%d7%95%d7%a4%d7%a9%d7%99"  # תוכן-חופשי
CATEGORY_ID = 67
ITEM_TYPE = "audio"

CATEGORY_PAGE_URL = f"{BASE_URL}/category/{CATEGORY_SLUG}/"
AJAX_URL = f"{BASE_URL}/wp-admin/admin-ajax.php"
MAX_PAGES = 100

OUTPUT_XML = "feed_halomot_67.xml"
STATE_FILE = "state_halomot_67.json"
REQUEST_TIMEOUT = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": CATEGORY_PAGE_URL,
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


def fetch_category_page():
    try:
        resp = SESSION.get(CATEGORY_PAGE_URL, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            print(f"  [!] {CATEGORY_PAGE_URL} -> HTTP {resp.status_code}")
            return None
        return resp.text
    except requests.RequestException as e:
        print(f"  [!] שגיאת רשת: {e}")
        return None


def extract_nonce(page_html):
    """מחלץ את ה-nonce מתוך LOAD_MORE_AJAX = {"url": "...", "nonce": "..."} בדף."""
    match = re.search(r'LOAD_MORE_AJAX\s*=\s*\{[^}]*"nonce"\s*:\s*"([^"]+)"', page_html)
    if match:
        return match.group(1)
    return None


def fetch_more_pages(nonce):
    """שולף את כל עמודי הארכיון הנוספים דרך AJAX 'הצג עוד'."""
    all_extra_html = []
    page = 2
    while page <= MAX_PAGES:
        try:
            resp = SESSION.post(
                AJAX_URL,
                data={
                    "action": "load_more_posts",
                    "paged": page,
                    "nonce": nonce,
                    "item_type": ITEM_TYPE,
                    "category": CATEGORY_ID,
                },
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                print(f"  [!] עמוד {page} -> HTTP {resp.status_code}")
                break
            page_html = resp.text
        except requests.RequestException as e:
            print(f"  [!] שגיאה בעמוד {page}: {e}")
            break

        if not page_html or not page_html.strip():
            print(f"  [.] עמוד {page} ריק - מסיים")
            break

        # אם התגובה JSON עטוף (במקום HTML ישיר), ננסה לחלץ ממנה
        stripped = page_html.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                data = json.loads(stripped)
                if isinstance(data, dict):
                    page_html = data.get("html") or data.get("data") or ""
                elif isinstance(data, list):
                    page_html = ""
            except ValueError:
                pass

        if not page_html or "audio-item" not in page_html:
            print(f"  [.] עמוד {page} לא הכיל פריטים נוספים - מסיים")
            break

        all_extra_html.append(page_html)
        print(f"  [.] עמוד {page} נטען בהצלחה")
        page += 1

    return "\n".join(all_extra_html)


def resolve_audio_url(episode_id):
    """
    התגלית המרכזית: מזהה הפרק (מתוך id="audio-<ID>") הוא בעצם ה-ID
    של קובץ המדיה (attachment) בוורדפרס. אפשר לשלוף את כתובת ה-mp3
    הנקייה, ואת גודל הקובץ (חשוב! אפליקציות פודקאסטים רבות דוחות
    enclosure עם length="0"), ישירות דרך ה-REST API הרגיל של וורדפרס:

        GET https://halomothasidiim.co.il/wp-json/wp/v2/media/<ID>

    מחזיר: (source_url, filesize) או (None, None) בכשל.
    """
    api_url = f"{BASE_URL}/wp-json/wp/v2/media/{episode_id}"
    try:
        resp = SESSION.get(api_url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            print(f"    [!] {api_url} -> HTTP {resp.status_code}")
            return None, None
        data = resp.json()
        source_url = data.get("source_url")
        filesize = data.get("filesize") or data.get("media_details", {}).get("filesize") or 0
        return source_url, filesize
    except (requests.RequestException, ValueError) as e:
        print(f"    [!] נכשל לפתור מדיה עבור ID {episode_id}: {e}")
        return None, None


def parse_episodes(page_html):
    """מפצל את ה-HTML לפי כל בלוק article.audio-item ומחלץ את הפרטים."""
    episodes = []
    blocks = re.split(r'<article id="audio-', page_html)
    for block in blocks[1:]:
        id_match = re.match(r'(\d+)"', block)
        if not id_match:
            continue
        episode_id = id_match.group(1)

        # בדיקת נעילה - מדלגים על כל פריט שלא מסומן בפירוש כ"display: none"
        lock_match = re.search(r'class="lock-cover"\s+style="display:\s*([a-zA-Z]+)"', block)
        password_match = re.search(r'class="password-access-cover"\s+style="display:\s*([a-zA-Z]+)"', block)
        if lock_match and lock_match.group(1).lower() != "none":
            continue
        if password_match and password_match.group(1).lower() != "none":
            continue

        link_match = re.search(r'<a class="series-post-link" href="([^"]+)"', block)
        title_match = re.search(
            r'<div class="series-post-title audio-post-title">([^<]*)</div>', block
        )
        audio_match = re.search(r'data-audio="([^"]+)"', block)
        image_match = re.search(r'background-image:\s*url\(([^)]+)\)', block)

        if not (link_match and title_match and audio_match):
            continue

        episodes.append({
            "id": episode_id,
            "link": html.unescape(link_match.group(1)),
            "title": clean_text(title_match.group(1)),
            "audio_url": html.unescape(audio_match.group(1)),
            "image": html.unescape(image_match.group(1)) if image_match else "",
        })
    return episodes


def normalize_episode(ep):
    return {
        "title": ep["title"] or "(ללא כותרת)",
        "description": ep["title"],
        "link": quote(ep["link"], safe=":/?=&%"),
        "guid": ep["id"],
        "pub_date": None,  # אין תאריך פרסום מפורש בכרטיס - נמלא סדר יורד לפי סדר הופעה
        "audio_url": quote(ep["audio_url"], safe=":/?=&%"),
        "image": quote(ep["image"], safe=":/%") if ep["image"] else "",
        "filesize": ep.get("filesize", 0),
    }


def build_episode_xml(ep, pub_date):
    img_tag = f'<itunes:image href="{escape(ep["image"])}"/>\n      ' if ep["image"] else ""
    return f"""    <item>
      <title>{escape(ep['title'])}</title>
      <description>{escape(ep['description'])}</description>
      <link>{escape(ep['link'])}</link>
      <guid isPermaLink="false">{escape(ep['guid'])}</guid>
      <pubDate>{pub_date}</pubDate>
      <enclosure url="{escape(ep['audio_url'])}" length="{ep['filesize']}" type="audio/mpeg"/>
      {img_tag}</item>"""


def build_feed(episodes):
    # אין תאריכים אמיתיים לפרקים בכרטיסים - משתמשים בסדר ההופעה (מהחדש
    # לישן, כפי שהאתר עצמו מציג) ומייצרים תאריכים יורדים מלאכותיים כדי
    # ששמירת הסדר בפיד תישמר נכון באפליקציות פודקאסטים.
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
    <title>חלומות של צדיקים - תוכן חופשי</title>
    <description>תוכן חופשי - חלומות של צדיקים</description>
    <link>{escape(CATEGORY_PAGE_URL)}</link>
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
    print(f"[1/5] מוריד את דף הקטגוריה: {CATEGORY_PAGE_URL}")
    page_html = fetch_category_page()
    if not page_html:
        print("      נכשל - לא ניתן היה להוריד את הדף")
        return

    print("[2/5] מחלץ nonce לצורך בקשות 'הצג עוד'...")
    nonce = extract_nonce(page_html)
    if not nonce:
        print("      [!] לא נמצא nonce - ימשיך רק עם העמוד הראשון (בלי עימוד)")
        extra_html = ""
    else:
        print(f"      נמצא nonce: {nonce}")
        print("[3/5] מוריד עמודי ארכיון נוספים...")
        extra_html = fetch_more_pages(nonce)

    combined_html = page_html + "\n" + extra_html
    raw_episodes = parse_episodes(combined_html)

    seen_ids = set()
    unique_raw = []
    for ep in raw_episodes:
        if ep["id"] in seen_ids:
            continue
        seen_ids.add(ep["id"])
        unique_raw.append(ep)

    print(f"[4/5] נמצאו {len(unique_raw)} פרקים פתוחים (לא נעולים) - פותר כתובות mp3 דרך WP media API...")
    resolved = []
    for i, ep in enumerate(unique_raw, 1):
        real_url, filesize = resolve_audio_url(ep["id"])
        if real_url:
            ep["audio_url"] = real_url
            ep["filesize"] = filesize or 0
            resolved.append(ep)
        if i % 20 == 0:
            print(f"      נפתרו {i}/{len(unique_raw)} כתובות...")
    print(f"      {len(resolved)}/{len(unique_raw)} פרקים נפתרו בהצלחה")

    episodes = [normalize_episode(ep) for ep in resolved]

    state = load_state()
    known = set(state.get("known_guids", []))
    new_guids = [ep["guid"] for ep in episodes if ep["guid"] not in known]
    print(f"      {len(new_guids)} פרקים חדשים מאז הריצה האחרונה")

    print("[5/5] בונה ושומר את קובץ ה-RSS...")
    feed_xml = build_feed(episodes)
    with open(OUTPUT_XML, "w", encoding="utf-8") as f:
        f.write(feed_xml)

    state["known_guids"] = [ep["guid"] for ep in episodes]
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    print(f"\nהושלם: {OUTPUT_XML} מכיל {len(episodes)} פרקים.")


if __name__ == "__main__":
    main()
