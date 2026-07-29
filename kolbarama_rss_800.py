#!/usr/bin/env python3
"""
kolbarama_rss.py — בונה ומעדכן פיד RSS לתוכנית "שמונה: אפס אפס" באתר
kol-barama.co.il, כולל שליפת הארכיון המלא (לא רק העמוד הראשון).

בשונה מ-emess.co.il, לאתר הזה אין REST API פתוח לפרקים - לכן הסקריפט
פשוט "קורא" (מוריד) את דף התוכנית עצמו, מחלץ ממנו את הפרקים מתוך
מבנה ה-HTML האמיתי, ואז ממשיך לבקש עוד עמודים באמצעות בקשת ה-AJAX
שהאתר עצמו משתמש בה עבור כפתור "טען עוד" (אומת מול תעבורת רשת אמיתית):

    POST https://kol-barama.co.il/wp-admin/admin-ajax.php
    action=load_more_past_shows
    paged=<מספר עמוד, מתחיל מ-2>
    data_show_id=<מזהה פנימי של התוכנית - למשל 38199 עבור "שמונה: אפס אפס">

    מחזיר JSON: {"html": "<עוד בלוקי past-show...>", "hide_button": bool}
    ממשיכים לבקש עמודים נוספים עד ש-hide_button הופך ל-true (או שאין html).

מבנה כל בלוק פרק ("past-show"):
    <div class="past-show post-<ID>" >
        <div class="right-side">
            <a href="<קישור לעמוד הפרק>">
                <span><תאריך עברי></span>
                <span><תאריך לועזי D.M.YYYY></span>
            </a>
        </div>
        ...
        <source src="<קישור ה-mp3>" type="audio/mpeg">

הרצה:
    pip install requests
    python3 kolbarama_rss.py
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

BASE_URL = "https://kol-barama.co.il"
SHOW_SLUG = "%d7%a9%d7%9e%d7%95%d7%a0%d7%94-%d7%90%d7%a4%d7%a1-%d7%90%d7%a4%d7%a1"  # שמונה-אפס-אפס
SHOW_NAME = "שמונה: אפס אפס"
SHOW_PAGE_URL = f"{BASE_URL}/show/{SHOW_SLUG}/"
DATA_SHOW_ID = 38199              # מזהה פנימי של התוכנית, לשימוש ב-AJAX

AJAX_URL = f"{BASE_URL}/wp-admin/admin-ajax.php"
MAX_PAGES = 100                   # תקרת בטיחות - כמות עמודי AJAX מקסימלית

OUTPUT_XML = "feed_kolbarama_800.xml"
STATE_FILE = "state_kolbarama_800.json"
REQUEST_TIMEOUT = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": BASE_URL + "/",
    "Connection": "keep-alive",
}

# ======================================================================


def fetch_more_pages():
    """
    שולף את כל עמודי הארכיון הנוספים (מעבר לעמוד הראשון) דרך בקשת ה-AJAX
    שהאתר משתמש בה עבור כפתור "טען עוד". ממשיך עד hide_button=True או
    שאין יותר HTML בתגובה.
    """
    all_extra_html = []
    page = 2
    while page <= MAX_PAGES:
        try:
            resp = SESSION.post(
                AJAX_URL,
                data={
                    "action": "load_more_past_shows",
                    "paged": page,
                    "data_show_id": DATA_SHOW_ID,
                },
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                print(f"  [!] עמוד {page} -> HTTP {resp.status_code}")
                break
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            print(f"  [!] שגיאה בעמוד {page}: {e}")
            break

        page_html = data.get("html", "")
        if not page_html.strip():
            print(f"  [.] עמוד {page} ריק - מסיים")
            break

        all_extra_html.append(page_html)
        print(f"  [.] עמוד {page} נטען בהצלחה")

        if data.get("hide_button"):
            print("      hide_button=True - זה היה העמוד האחרון")
            break

        page += 1

    return "\n".join(all_extra_html)


try:
    import cloudscraper
    SESSION = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )
except ImportError:
    # אם cloudscraper לא מותקן, נופלים בחזרה ל-requests רגיל (פחות סיכוי לעבור חסימות)
    SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def warm_up_session():
    """מבצע בקשה ראשונית לדף הבית כדי לקבל עוגיות (cookies) אם יש הגנת בוטים."""
    try:
        SESSION.get(BASE_URL + "/", timeout=REQUEST_TIMEOUT)
    except requests.RequestException:
        pass  # לא קריטי אם זה נכשל - ננסה להמשיך בכל מקרה


def fetch_show_page():
    try:
        resp = SESSION.get(SHOW_PAGE_URL, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            print(f"  [!] {SHOW_PAGE_URL} -> HTTP {resp.status_code}")
            return None
        return resp.text
    except requests.RequestException as e:
        print(f"  [!] שגיאת רשת: {e}")
        return None


def gregorian_to_rfc822(date_str):
    """ממיר תאריך בפורמט D.M.YYYY (או DD.MM.YYYY) ל-RFC 822, עם שעה קבועה 00:00 (ישראל)."""
    try:
        dt = datetime.strptime(date_str.strip(), "%d.%m.%Y")
    except ValueError:
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    offset = timedelta(hours=3) if 3 <= dt.month <= 10 else timedelta(hours=2)
    dt = dt.replace(tzinfo=timezone(offset))
    return dt.strftime("%a, %d %b %Y %H:%M:%S %z")


def parse_episodes(page_html):
    """
    מפצל את ה-HTML לפי כל בלוק "past-show" ומחלץ מכל אחד:
    id, קישור לעמוד הפרק, תאריך עברי, תאריך לועזי, קישור mp3.
    """
    episodes = []
    # מפצלים לפי תחילת כל בלוק
    blocks = re.split(r'<div class="past-show post-', page_html)
    for block in blocks[1:]:  # הפריט הראשון הוא הכל לפני הבלוק הראשון - מדלגים
        id_match = re.match(r'(\d+)', block)
        if not id_match:
            continue
        post_id = id_match.group(1)

        link_match = re.search(
            r'<a href="([^"]+)">\s*<span>([^<]*)</span>\s*<span>([^<]*)</span>',
            block
        )
        if not link_match:
            continue
        episode_link = link_match.group(1)
        hebrew_date = html.unescape(link_match.group(2)).strip()
        gregorian_date = html.unescape(link_match.group(3)).strip()

        mp3_match = re.search(r'<source src="([^"]+\.mp3)"', block)
        if not mp3_match:
            continue
        mp3_url = html.unescape(mp3_match.group(1))

        episodes.append({
            "id": post_id,
            "link": episode_link,
            "hebrew_date": hebrew_date,
            "gregorian_date": gregorian_date,
            "mp3_url": mp3_url,
        })
    return episodes


def normalize_episode(ep):
    title = f"{SHOW_NAME} - {ep['gregorian_date']} ({ep['hebrew_date']})"
    pub_date = gregorian_to_rfc822(ep["gregorian_date"])
    # כתובת ה-mp3 באתר מכילה רווחים ותווי עברית לא מקודדים - מקודדים
    # אותה כראוי כדי שתהיה כתובת URL תקינה (safe=':/' שומר על מבנה הכתובת).
    safe_audio_url = quote(ep["mp3_url"], safe=":/")
    return {
        "title": title,
        "description": title,
        "link": ep["link"],
        "guid": ep["id"],
        "pub_date": pub_date,
        "audio_url": safe_audio_url,
    }


def build_episode_xml(ep):
    return f"""    <item>
      <title>{escape(ep['title'])}</title>
      <description>{escape(ep['description'])}</description>
      <link>{escape(ep['link'])}</link>
      <guid isPermaLink="false">{escape(ep['guid'])}</guid>
      <pubDate>{ep['pub_date']}</pubDate>
      <enclosure url="{escape(ep['audio_url'])}" length="0" type="audio/mpeg"/>
    </item>"""


def build_feed(episodes):
    items_xml = "\n".join(build_episode_xml(ep) for ep in episodes)
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{escape(SHOW_NAME)}</title>
    <description>{escape(SHOW_NAME)} - רדיו קול ברמה</description>
    <link>{escape(SHOW_PAGE_URL)}</link>
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
    print("[0/4] מבצע ביקור חימום בדף הבית (לקבלת עוגיות אם צריך)...")
    warm_up_session()

    print(f"[1/4] מוריד את דף התוכנית: {SHOW_PAGE_URL}")
    page_html = fetch_show_page()
    if not page_html:
        print("      נכשל - לא ניתן היה להוריד את הדף")
        return

    print("[2/4] מוריד עמודי ארכיון נוספים (AJAX 'טען עוד')...")
    extra_html = fetch_more_pages()

    print("[3/4] מחלץ פרקים מכל ה-HTML שנאסף...")
    combined_html = page_html + "\n" + extra_html
    raw_episodes = parse_episodes(combined_html)

    # הסרת כפילויות לפי guid (id), למקרה שאותו פרק הופיע פעמיים
    seen_ids = set()
    unique_raw = []
    for ep in raw_episodes:
        if ep["id"] in seen_ids:
            continue
        seen_ids.add(ep["id"])
        unique_raw.append(ep)

    episodes = [normalize_episode(ep) for ep in unique_raw]
    print(f"      נמצאו {len(episodes)} פרקים ייחודיים בסה\"כ")

    state = load_state()
    known = set(state.get("known_guids", []))
    new_guids = [ep["guid"] for ep in episodes if ep["guid"] not in known]
    print(f"      {len(new_guids)} פרקים חדשים מאז הריצה האחרונה")

    print("[4/4] בונה ושומר את קובץ ה-RSS...")
    feed_xml = build_feed(episodes)
    with open(OUTPUT_XML, "w", encoding="utf-8") as f:
        f.write(feed_xml)

    state["known_guids"] = [ep["guid"] for ep in episodes]
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    print(f"\nהושלם: {OUTPUT_XML} מכיל {len(episodes)} פרקים.")


if __name__ == "__main__":
    main()
