import json
import re
import time
import os
from pathlib import Path
from curl_cffi import requests
from google import genai
from google.genai import types
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- הגדרת נתיבים מוחלטים קבועים (כדי למנוע בעיות של תיקיית עבודה) ---
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
CARS_DATA_FILE = BASE_DIR / "scraped_cars.json"
PROCESSED_TOKENS_FILE = BASE_DIR / "processed_tokens.json"
RESULTS_FILE = BASE_DIR / "gemini_results_history.json"

# טעינת המפתח
load_dotenv(dotenv_path=ENV_PATH)
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError(f"GEMINI_API_KEY לא נמצא! ודא שקובץ ה-.env קיים בנתיב: {ENV_PATH}")

client = genai.Client(api_key=api_key)

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9,he;q=0.8",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "cookie": (
        "__uzma=324fb6c9-fc40-4452-ab55-d0727596ef26; __uzmb=1791232313; __uzme=7261; __ssds=0; "
        "__uzmaj0=324fb6c9-fc40-4452-ab55-d0727596ef26; __uzmbj0=1791232314; __uzmlj0=7kBBn58xgEM/ETMdcfD2VeNeh1YfqMH9J9OOSyfyoEQ=; "
        "y2018-2-cohort=63; guest_token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJwYXlsb2FkIjp7InV1aWQiOiIyYzA0YjE4Yi1hY2RiLTRlYzQtYTNlYy0yMDRmMDIwMmJkMjUifSwiaWF0IjoxNzkxMjMyMzE1LCJleHAiOjE4MjI3ODk5MTV9.KS5RH7fTN6HEhWK6fGD5nvi7SFuR8m2XLE6bB87Dxyg; "
        "_hjSessionUser_266550=eyJpZCI6ImZhNjYwMzk1LTY4NDEtNTNhZS04YjhiLWIwNjg0Y2E4ZTNiOCIsImNyZWF0ZWQiOjE3OTEyMzIzMTUzOTMsImV4aXN0aW5nIjp0cnVlfQ==; "
        "feed_mix_session=8b4457ff-0612-46e9-b808-936dbd0cc686; "
        "__uzmfj0=7f9000324fb6c9-fc40-4452-ab55-d0727596ef262-179123231464873951894-0051539e61c255451c673; "
        "uzmxj=7fc0009709049e-fb27-439d-a9e2-6ad9c79c62ed2-179123231464873951894-00883985e683eda470573; "
        "__uzmc=4733223518275; __uzmd=1791306746; "
        "__uzmf=7f9000324fb6c9-fc40-4452-ab55-d0727596ef262-179123231365274432685-0055a29485a818d1156235; "
        "uzmx=7fc0009709049e-fb27-439d-a9e2-6ad9c79c62ed2-179123231365274434477-008191cfd1212b8d9d9658"
    )
}

def fetch_initial_cars(page=1):
    url = "https://gw.yad2.co.il/feed-search-vehicles/cars/transform"
    params = {
        "year": "2010-2018",
        "manufacturer": "21,36,27,30",
        "model": "10273,10331,10497,10385",
        "price": "-1-30000",
        "page": page,
    }
    
    try:
        res = requests.get(url, params=params, headers=HEADERS, impersonate="chrome120")
        if res.status_code != 200:
            print(f"שגיאה בגישה לפיד (סטטוס: {res.status_code})")
            return []
            
        data = res.json().get("data", {})
        categories = ["private", "commercial", "solo", "platinum"]
        
        tokens = []
        for cat in categories:
            for ad in data.get(cat, []):
                token = ad.get("token")
                price = ad.get("price")
                if token and price and isinstance(price, (int, float)) and price > 0:
                    tokens.append(str(token).strip())
                    
        return tokens
    except Exception as e:
        print(f"שגיאה ב-fetch_initial_cars: {e}")
        return []

def fetch_car_full_details(token):
    url = f"https://www.yad2.co.il/vehicles/item/{token}"
    html_headers = HEADERS.copy()
    html_headers["accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    
    try:
        res = requests.get(url, headers=html_headers, impersonate="chrome120")
        
        if res.status_code != 200:
            print(f"\n[🚨 שגיאת חסימה / רשת] נכשל בשליפת מודעה {token}. סטטוס: {res.status_code}")
            return None

        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', res.text)
        if not match:
            print(f"\n[🚨 שינוי מבנה HTML] לא נמצא בלוק הנתונים __NEXT_DATA__ בדף המודעה {token}.")
            return None

        raw_json = json.loads(match.group(1))
        queries = raw_json.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
        
        data = {}
        for query in queries:
            state_data = query.get("state", {}).get("data", {})
            if isinstance(state_data, dict) and "vehicleDates" in state_data:
                data = state_data
                break
                
        if not data:
            print(f"\n[🚨 שינוי נתיב JSON] הנתונים לא נמצאו בנתיב המוכר עבור {token}.")
            return None

        month_data = data.get("vehicleDates", {}).get("monthOfProduction")
        month_val = month_data.get("id") if isinstance(month_data, dict) else month_data

        item = {
            "token": token,
            "manufacturer": data.get("manufacturer", {}).get("text"),
            "model": data.get("model", {}).get("text"),
            "subModel": data.get("subModel", {}).get("text"),
            "year": data.get("vehicleDates", {}).get("yearOfProduction"),
            "month": month_val,
            "hand": data.get("hand", {}).get("id"),
            "km": data.get("kilometers") or data.get("km"),
            "previousOwnership": data.get("previousOwnership", {}).get("text"),
            "currentPrice": data.get("price"),
            "originalPrice": data.get("metaData", {}).get("priceBeforeTag") or data.get("price"),
            "sellerType": data.get("adType"),
            "agencyName": data.get("customer", {}).get("agencyName"),
            "testUntil": data.get("vehicleDates", {}).get("testDate"),
            "description": data.get("info") or data.get("description", {}).get("text"),
            "link": url
        }
        return item
        
    except Exception as e:
        print(f"\n[🚨 שגיאה קריטית בחילוץ] קרס בזמן עיבוד הנתונים של {token}. פרטי: {e}")
        return None

def analyze_cars_with_gemini(cars_list, max_retries=3):
    """שולח רשימת רכבים לניתוח ודירוג אינדיבידואלי ללא השוואה הדדית"""
    prompt = f"""
אתה מומחה לבדיקת כדאיות ואמינות רכבי יד שנייה בישראל.
תפקידך להעריך כל רכב ברשימה **באופן עצמאי ומבודד לחלוטין (Individual Assessment)**, כאילו הוא הרכב היחיד שקיים.

### הנחיות קריטיות:
1. **הערכה מבודדת:** אין להשוות בין הרכבים ברשימה, אין לבצע דירוג תחרותי, ואין לבחור 'הכי טוב מבין הקיימים'. כל רכב נמדד אך ורק מול הסטנדרטים המקצועיים שלו.
2. **פרופיל היעד לרכישה:**
- רכב ראשון: עדיפות לאמינות גבוהה, עלויות טיפולים זולות וחלפים זמינים, וצריכת דלק חסכונית/סבירה.
- העדפה מובהקת למכלולים פשוטים: מנועים אטמוספריים וגירים פלנטריים או רציפים אמינים.
3. **דגלים אדומים לפסילה או הורדת ציון חדה:**
- גירים רובוטיים כפולי-מצמדים בעייתיים (DSG ישן, Powershift וכו') ללא תיעוד החלפה.
- ממוצע נסועה חריג מעל 20,000–25,000 ק"מ בשנה.
- מחיר בלתי סביר או חשד למודעת מימון/תרמית.
- טסט העומד לפוג בקרוב מאוד.
4. **סינון לפי ציון (רף 7.0):**
- דרג כל רכב בציון שנע בין 1.0 ל-10.0.
- **החזר אך ורק רכבים שקיבלו ציון 7.0 ומעלה.**
- רכב עם ציון 6.9 ומטה ייפסל ולא ייכלל בפלט.
5. **ללא מכסת תוצאות:** 
- אל תנסה להגיע למספר מסוים של רכבים.
- אם מתוך הרשימה 5 רכבים ראויים – החזר את כל ה-5.
- אם אף רכב אינו מגיע לציון 7.0 ומעלה – החזר רשימה ריקה (`[]`).

### נתוני הקלט:
{json.dumps(cars_list, ensure_ascii=False, indent=2)}

החזר אך ורק אובייקט JSON תקין במבנה הבא (ללא Markdown וללא טקסט מקדים):
{{
  "top_recommendations": [
    {{
      "link": "הקישור הישיר של הרכב",
      "car_name": "שנתון + יצרן + דגם + תת-דגם",
      "price": 10000,
      "km": 50000,
      "score_out_of_10": 8.5,
      "pros": [
        "יתרון מובהק של הרכב המסוים הזה"
      ],
      "cons_and_warnings": [
        "נקודות תורפה לבדיקה פיזית במוסך / מגרעות"
      ],
      "verdict_reason": "נימוק תמציתי מדוע הרכב עבר את רף ה-7.0 וראוי לרכישה"
    }}
  ]
}}
"""

    for attempt in range(max_retries):
        try:
            res = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            text_content = "".join(part.text for part in res.candidates[0].content.parts if getattr(part, "text", None))
            return json.loads(text_content)
        except Exception as e:
            error_msg = str(e)
            if "503" in error_msg or "UNAVAILABLE" in error_msg:
                if attempt < max_retries - 1:
                    wait_time = 1800  # 30 דקות = 1800 שניות
                    print(f"השרת של Gemini עמוס כרגע. ממתין 30 דקות ומנסה שוב (ניסיון {attempt + 2}/{max_retries})...")
                    time.sleep(wait_time)
                else:
                    print("השרת עדיין עמוס לאחר מספר ניסיונות.")
                    raise e
            else:
                raise e

def send_top_cars_email(cars):
    """מסנן רכבים מעל ציון 8.5 ושולח אימייל מעוצב במידה ונמצאו כאלו"""
    sender_email = os.getenv("EMAIL_SENDER")
    sender_password = os.getenv("EMAIL_PASSWORD")
    receiver_email = os.getenv("EMAIL_RECEIVER")
    
    if not sender_email or not sender_password or not receiver_email:
        print("[מערכת]: חסרים פרטי אימייל בקובץ ה-.env. מדלג על שליחת המייל.")
        return

    # סינון הרכבים עם ציון מעל 8.5
    top_tier_cars = [car for car in cars if car.get("score_out_of_10", 0) >= 8]
    
    if not top_tier_cars:
        print("[מערכת]: לא נמצאו רכבים עם ציון מעל 8.5 בהרצה זו, לא נשלח מייל.")
        return
        
    print(f"[מערכת]: מכין מייל עבור {len(top_tier_cars)} רכבים מצטיינים...")
    
    # בניית תבנית ה-HTML המעוצבת
    html_content = f"""
    <html dir="rtl" lang="he">
    <head>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; margin: 0; padding: 20px; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; padding: 20px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
            h2 {{ color: #2c3e50; text-align: center; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
            .car-card {{ border: 1px solid #e1e8ed; border-radius: 6px; margin-bottom: 20px; padding: 15px; background-color: #fdfdfd; transition: 0.3s; }}
            .car-card:hover {{ box-shadow: 0 2px 12px rgba(0,0,0,0.1); }}
            .car-title {{ font-size: 20px; font-weight: bold; color: #2980b9; margin-bottom: 12px; }}
            .car-detail {{ margin: 6px 0; font-size: 15px; line-height: 1.4; }}
            .score {{ font-size: 18px; font-weight: bold; color: #27ae60; background: #e8f8f5; display: inline-block; padding: 4px 8px; border-radius: 4px; margin-top: 5px; }}
            .pros {{ color: #27ae60; }}
            .cons {{ color: #e74c3c; }}
            .btn {{ display: block; width: fit-content; padding: 10px 20px; margin: 15px auto 5px; background-color: #3498db; color: white; text-decoration: none; border-radius: 4px; text-align: center; font-weight: bold; }}
            .btn:hover {{ background-color: #2980b9; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>🚗 רכבים מומלצים מעל ציון 8.5 🚗</h2>
            <p>היי ניב,</p>
            <p>הסקריפט שלך מצא עסקאות מעולות שעברו את רף ה-8.5:</p>
    """
    
    for car in top_tier_cars:
        pros_li = "".join([f"<li>{p}</li>" for p in car.get("pros", [])])
        cons_li = "".join([f"<li>{c}</li>" for c in car.get("cons_and_warnings", [])])
        
        html_content += f"""
            <div class="car-card">
                <div class="car-title">{car.get('car_name', 'רכב ללא שם')}</div>
                <div class="car-detail"><strong>מחיר:</strong> ₪{car.get('price', 'לא צוין'):,}</div>
                <div class="car-detail"><strong>קילומטראז':</strong> {car.get('km', 'לא צוין'):,} ק"מ</div>
                <div class="car-detail score">ציון מ-Gemini: {car.get('score_out_of_10', 'N/A')}/10</div>
                
                <div class="car-detail">
                    <strong>יתרונות:</strong>
                    <ul class="pros">{pros_li}</ul>
                </div>
                <div class="car-detail">
                    <strong>לתשומת לב:</strong>
                    <ul class="cons">{cons_li}</ul>
                </div>
                <div class="car-detail"><strong>סיכום:</strong> {car.get('verdict_reason', '')}</div>
                
                <a href="{car.get('link', '#')}" class="btn" target="_blank" style="color: white;">למעבר למודעה</a>
            </div>
        """
        
    html_content += """
        </div>
    </body>
    </html>
    """
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🔥 נמצאו {len(top_tier_cars)} רכבים מעולים (ציון מעל 8.5) ביד 2!"
    msg["From"] = sender_email
    msg["To"] = receiver_email
    
    # חיבור תוכן ה-HTML למייל
    msg.attach(MIMEText(html_content, "html"))
    
    try:
        # התחברות לשרת גוגל ושליחה
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        print("[מערכת]: מייל ההתראות נשלח בהצלחה!")
    except Exception as e:
        print(f"[מערכת]: שגיאה בשליחת המייל - {e}")

if __name__ == "__main__":
    enriched_cars = []
    loaded_from_file = False
    processed_tokens = set()

    # 1. טעינת הזיכרון
    if PROCESSED_TOKENS_FILE.exists() and PROCESSED_TOKENS_FILE.stat().st_size > 0:
        try:
            with open(PROCESSED_TOKENS_FILE, "r", encoding="utf-8") as f:
                loaded_data = json.load(f)
                if isinstance(loaded_data, list):
                    processed_tokens = set(str(t).strip() for t in loaded_data)
                    print(f"[מערכת] נטענו {len(processed_tokens)} מזהי רכבים מהיסטוריית הזיכרון.")
        except json.JSONDecodeError:
            print("[מערכת] קובץ הזיכרון פגום. מתחיל זיכרון חדש.")

    # 2. בדיקת נתוני גיבוי מקומיים
    if CARS_DATA_FILE.exists() and CARS_DATA_FILE.stat().st_size > 0:
        try:
            with open(CARS_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data: 
                    enriched_cars = data
                    loaded_from_file = True
                    print(f"[מערכת] טוען נתונים שנשמרו מקומית מהרצה קודמת...")
        except json.JSONDecodeError:
            pass

    # 3. סריקת רכבים חדשים
    if not loaded_from_file:
        MAX_CARS_TO_PROCESS = 10
        MAX_PAGES_TO_CHECK = 10
        tokens_to_process = []
        current_page = 1

        print("\nמחפש רכבים חדשים שלא נשלחו בעבר ל-Gemini...")
        
        while len(tokens_to_process) < MAX_CARS_TO_PROCESS and current_page <= MAX_PAGES_TO_CHECK:
            print(f"סורק את עמוד {current_page}...")
            page_tokens = fetch_initial_cars(page=current_page)
            
            if not page_tokens:
                print("לא נמצאו רכבים בעמוד זה. עוצר סריקה.")
                break
                
            skipped_this_page = 0
            for token in page_tokens:
                clean_token = str(token).strip()
                # בודק אם הטוקן כבר בהיסטוריה שלנו או שכבר הוספנו אותו לעיבוד
                if clean_token in processed_tokens or clean_token in tokens_to_process:
                    skipped_this_page += 1
                    continue
                tokens_to_process.append(clean_token)
                if len(tokens_to_process) == MAX_CARS_TO_PROCESS:
                    break
            
            if skipped_this_page > 0:
                print(f"   (סוננו {skipped_this_page} מודעות מעמוד זה שכבר קיימות בזיכרון)")
                
            if len(tokens_to_process) < MAX_CARS_TO_PROCESS:
                current_page += 1
                time.sleep(2)
                
        print(f"\nסה\"כ נאספו {len(tokens_to_process)} רכבים חדשים לחלוטין לעיבוד.")
        
        if tokens_to_process:
            print("מתחיל לחלץ נתונים מלאים עבור הרכבים...")
            for i, token in enumerate(tokens_to_process, 1):
                print(f"   [{i}/{len(tokens_to_process)}] מעבד רכב: {token}")
                car_data = fetch_car_full_details(token)
                if car_data:
                    enriched_cars.append(car_data)
                time.sleep(1)
                
            if enriched_cars:
                with open(CARS_DATA_FILE, "w", encoding="utf-8") as f:
                    json.dump(enriched_cars, f, ensure_ascii=False, indent=2)

    # 4. שלב הניתוח
    if enriched_cars:
        print("\n3. מעביר לניתוח ב-Gemini API...")
        try:
            analysis = analyze_cars_with_gemini(enriched_cars)
            
            if "top_recommendations" in analysis:
                for rec in analysis["top_recommendations"]:
                    original_data = next((car for car in enriched_cars if car.get("link") == rec.get("link")), None)
                    if original_data:
                        rec["additional_info"] = {
                            "hand": original_data.get("hand"),
                            "testUntil": original_data.get("testUntil"),
                            "previousOwnership": original_data.get("previousOwnership"),
                            "sellerType": original_data.get("sellerType"),
                            "agencyName": original_data.get("agencyName"),
                            "month": original_data.get("month"),
                            "description": original_data.get("description"),
                            "originalPrice": original_data.get("originalPrice"),
                            "token": original_data.get("token")
                        }

            print("\n=== תוצאות הניתוח הסופיות ===")
            print(json.dumps(analysis, ensure_ascii=False, indent=2))
            
            # שמירת הזיכרון המעודכן
            for car in enriched_cars:
                processed_tokens.add(str(car["token"]).strip())
            
            with open(PROCESSED_TOKENS_FILE, "w", encoding="utf-8") as f:
                json.dump(list(processed_tokens), f, ensure_ascii=False, indent=2)
            print(f"[מערכת]: קובץ הזיכרון עודכן בהצלחה (מכיל כעת {len(processed_tokens)} רכבים).")
            
            # הוספה לקובץ התוצאות
            existing_results = []
            if RESULTS_FILE.exists() and RESULTS_FILE.stat().st_size > 0:
                try:
                    with open(RESULTS_FILE, "r", encoding="utf-8") as rf:
                        existing_results = json.load(rf)
                except json.JSONDecodeError:
                    pass
            
            analysis["run_timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
            existing_results.append(analysis)
            
            with open(RESULTS_FILE, "w", encoding="utf-8") as wf:
                json.dump(existing_results, wf, ensure_ascii=False, indent=2)

            # --- הוספה של שליחת המייל ---
            if "top_recommendations" in analysis:
                send_top_cars_email(analysis["top_recommendations"])
            
            # --- השינוי כאן: מחיקת קובץ הגיבוי תמיד בעת הצלחה ---
            if CARS_DATA_FILE.exists():
                os.remove(CARS_DATA_FILE)
                print(f"[מערכת]: קובץ הגיבוי '{CARS_DATA_FILE.name}' נמחק בהצלחה לאחר שהנתונים עברו בהצלחה ל-Gemini.")
                
        except Exception as e:
            print(f"שגיאה בתקשורת מול Gemini API: {e}")
            print(f"[מערכת]: הנתונים נשמרו מקומית לגיבוי בקובץ '{CARS_DATA_FILE.name}'. הרץ שוב.")
    else:
        print("לא נמצאו נתונים חדשים לניתוח.")