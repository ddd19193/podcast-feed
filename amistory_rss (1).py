#!/usr/bin/env python3
"""
amistory_rss.py — משקף (מראה, mirror) את ה-RSS המקורי של פודקאסט
"סיפורי אמיתי המספר" (amistory.co.il).

הרעיון: לפודקאסט הזה כבר יש RSS אמיתי ומלא שהיוצר שולח ל-Apple Podcasts
ו-Spotify (זו הדרך היחידה שבה תוכן מגיע לפלטפורמות האלה). ה-RSS הזה
"מוסתר" מהמשתמש הרגיל באפליקציות, אבל ה-API הפומבי של Apple (iTunes
Lookup API) חושף אותו לכל אחד תחת השדה "feedUrl".

לכן, במקום לבנות scraper מורכב לאתר amistory.co.il עצמו (שיש בו מאות
סיפורים מפוזרים בעשרות קטגוריות בלי API ברור) - הסקריפט הזה:
  1. שולף את כתובת ה-RSS האמיתית דרך Apple: https://itunes.apple.com/lookup?id=<APPLE_PODCAST_ID>
  2. מוריד את ה-RSS המקורי מהכתובת הזו
  3. שומר אותו כמו שהוא בקובץ הפלט שלנו (זהו "mirror" - שיקוף מלא)

זה גם מבטיח שנקבל את **כל** הפרקים (לא רק את אלה שמוצגים בעמוד my-stories),
כי ה-RSS המקורי הוא המקור האמיתי שממנו מוזן כל תוכן הפודקאסט.

הרצה:
    pip install requests
    python3 amistory_rss.py
"""

import requests

# ============================== הגדרות ==============================

APPLE_PODCAST_ID = "1329424446"   # מזהה הפודקאסט באפל פודקאסטס
LOOKUP_URL = f"https://itunes.apple.com/lookup?id={APPLE_PODCAST_ID}"

OUTPUT_XML = "feed_amistory.xml"
REQUEST_TIMEOUT = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

# ======================================================================


def get_feed_url():
    """שולף את כתובת ה-RSS האמיתית דרך iTunes Lookup API."""
    try:
        resp = requests.get(LOOKUP_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            print(f"  [!] {LOOKUP_URL} -> HTTP {resp.status_code}")
            return None
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  [!] שגיאה: {e}")
        return None

    results = data.get("results", [])
    if not results:
        print("  [!] לא נמצאו תוצאות עבור המזהה הזה ב-Apple Podcasts")
        return None

    feed_url = results[0].get("feedUrl")
    if not feed_url:
        print("  [!] לא נמצא feedUrl בתוצאה")
        return None

    print(f"      נמצא RSS מקורי: {feed_url}")
    return feed_url


def mirror_feed(feed_url):
    """מוריד את ה-RSS המקורי ושומר אותו כפי שהוא."""
    try:
        resp = requests.get(feed_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            print(f"  [!] {feed_url} -> HTTP {resp.status_code}")
            return False
    except requests.RequestException as e:
        print(f"  [!] שגיאה בהורדת ה-RSS: {e}")
        return False

    with open(OUTPUT_XML, "wb") as f:
        f.write(resp.content)

    num_items = resp.text.count("<item>") or resp.text.count("<item ")
    print(f"      נשמר {OUTPUT_XML} ({num_items} פרקים בערך)")
    return True


def main():
    print("[1/2] שולף את כתובת ה-RSS האמיתית מ-Apple...")
    feed_url = get_feed_url()
    if not feed_url:
        print("      נכשל - לא ניתן היה למצוא את כתובת ה-RSS")
        return

    print("[2/2] מוריד ושומר את ה-RSS...")
    success = mirror_feed(feed_url)
    if success:
        print(f"\nהושלם: {OUTPUT_XML} עודכן בהצלחה.")
    else:
        print("\nנכשל בשלב האחרון.")


if __name__ == "__main__":
    main()
