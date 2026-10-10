import json
import re
import time
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from curl_cffi import requests
from google import genai
from google.genai import types
from dotenv import load_dotenv

# הגדרת נתיבים מוחלטים
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
RESULTS_FILE = BASE_DIR / "gemini_results_history.json"
PROCESSED_TOKENS_FILE = BASE_DIR / "processed_tokens.json"

# טעינת משתני סביבה
load_dotenv(dotenv_path=ENV_PATH)
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY לא נמצא! ודא שמשתנה הסביבה מוגדר היטב.")

client = genai.Client(api_key=api_key)

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9,he;q=0.8",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "cookie": "guest_token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9;" 
}

def fetch_current_price(token):
    """
    שולף את המחיר העדכני.
    מחזיר: 
    - מספר (המחיר) אם הצליח.
    - "REMOVED" אם המודעה הוסרה בוודאות.
    - None אם יש שגיאת רשת/חסימה.
    """
    url = f"https://www.yad2.co.il/vehicles/item/{token}"
    try:
        res = requests.get(url, headers=HEADERS, impersonate="chrome120", allow_redirects=False)
        
        if res.status_code in (404, 410, 301, 302):
            return "REMOVED"
            
        if res.status_code != 200:
            return None 
            
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', res.text)
        if not match:
            if "לא נמצא" in res.text or "לא קיימת" in res.text:
                return "REMOVED"
            return None

        raw_json = json.loads(match.group(1))
        queries = raw_json.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
        
        if not queries:
            return "REMOVED" 

        for query in queries:
            state_data = query.get("state", {}).get("data", {})
            if isinstance(state_data, dict) and "price" in state_data:
                return state_data.get("price")
                
        return "REMOVED"
    except Exception:
        return None

def analyze_price_drop_with_gemini(car_data, old_price, new_price, old_score, max_retries=3):
    """שולח את נתוני ירידת המחיר להערכה מחדש ב-Gemini"""
    prompt = f"""
אתה מומחה לבדיקת כדאיות ואמינות רכבי יד שנייה בישראל.
הרכב הבא נבדק בעבר על ידך וקיבל ציון {old_score} מתוך 10, כשהמחיר שלו היה {old_price} ש"ח.
כעת, המוכר הוריד את המחיר ל-{new_price} ש"ח! (חיסכון של {old_price - new_price} ש"ח).

פרטי הרכב המקוריים:
{json.dumps(car_data, ensure_ascii=False, indent=2)}

תפקידך:
1. להעריך עד כמה ירידת המחיר הופכת את הרכב למשתלם יותר.
2. לתת ציון מעודכן מ-1.0 עד 10.0 בהתחשב במחיר החדש.

החזר אך ורק אובייקט JSON תקין במבנה הבא:
{{
  "new_score_out_of_10": 9.2,
  "verdict_reason": "הסבר קצר ותמציתי על כדאיות העסקה עכשיו."
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
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                if attempt < max_retries - 1:
                    time.sleep(20 * (attempt + 1))
                else:
                    return None
            else:
                return None

def send_price_drop_email(cars):
    """שולח אימייל על רכבים שחוו ירידת מחיר"""
    sender_email = os.getenv("EMAIL_SENDER")
    sender_password = os.getenv("EMAIL_PASSWORD")
    receiver_email = os.getenv("EMAIL_RECEIVER")
    
    if not sender_email or not sender_password or not receiver_email:
        print("[מערכת]: חסרים פרטי אימייל בקובץ ה-.env. מדלג על שליחת המייל.")
        return

    print(f"[מערכת]: מכין מייל התראות עבור {len(cars)} רכבים שהוזלו...")
    
    html_content = """
    <html dir="rtl" lang="he">
    <head>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; margin: 0; padding: 20px; color: #333; }
            .container { max-width: 600px; margin: 0 auto; background: #ffffff; padding: 20px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
            h2 { color: #2c3e50; text-align: center; border-bottom: 2px solid #e74c3c; padding-bottom: 10px; }
            .car-card { border: 1px solid #e1e8ed; border-radius: 6px; margin-bottom: 20px; padding: 15px; background-color: #fdfdfd; }
            .car-title { font-size: 20px; font-weight: bold; color: #c0392b; margin-bottom: 12px; }
            .detail { margin: 8px 0; font-size: 15px; line-height: 1.4; }
            .strike { text-decoration: line-through; color: #95a5a6; margin-left: 5px; }
            .new-val { font-weight: bold; color: #27ae60; font-size: 16px; }
            .btn { display: block; width: fit-content; padding: 10px 20px; margin: 15px auto 5px; background-color: #3498db; color: white; text-decoration: none; border-radius: 4px; text-align: center; font-weight: bold; }
            .btn:hover { background-color: #2980b9; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>📉 המוכרים נלחצים! ירידות מחיר חדשות 📉</h2>
            <p>היי ניב,</p>
            <p>הסקריפט זיהה שהמוכרים הבאים חתכו את המחיר של הרכבים שכבר שמרנו במאגר:</p>
    """
    
    for car in cars:
        alert = car.get("price_drop_alert", {})
        old_price = alert.get("old_price", 0)
        new_price = alert.get("new_price", 0)
        old_score = alert.get("old_score", 0)
        new_score = car.get("score_out_of_10", 0)
        savings = old_price - new_price
        
        html_content += f"""
            <div class="car-card">
                <div class="car-title">{car.get('car_name', 'רכב ללא שם')}</div>
                <div class="detail">💰 <strong>מחיר:</strong> <span class="strike">₪{old_price:,}</span> <span class="new-val">₪{new_price:,}</span> (חיסכון של ₪{savings:,})</div>
                <div class="detail">⭐ <strong>ציון Gemini:</strong> <span class="strike">{old_score}</span> <span class="new-val">{new_score}</span> / 10</div>
                <div class="detail">📝 <strong>ניתוח מעודכן:</strong> {alert.get('analysis', '')}</div>
                <a href="{car.get('link', '#')}" class="btn" target="_blank">למעבר למודעה</a>
            </div>
        """
        
    html_content += """
        </div>
    </body>
    </html>
    """
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📉 {len(cars)} מוכרים הורידו מחיר ביד 2!"
    msg["From"] = sender_email
    msg["To"] = receiver_email
    
    msg.attach(MIMEText(html_content, "html"))
    
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        print("[מערכת]: מייל התראות ירידת מחיר נשלח בהצלחה!")
    except Exception as e:
        print(f"[מערכת]: שגיאה בשליחת המייל - {e}")

if __name__ == "__main__":
    if not RESULTS_FILE.exists() or RESULTS_FILE.stat().st_size == 0:
        print("[מערכת]: לא נמצא קובץ היסטוריה לסריקה. מסיים ריצה.")
        exit()

    try:
        with open(RESULTS_FILE, "r", encoding="utf-8") as f:
            history_data = json.load(f)
    except json.JSONDecodeError:
        print("[מערכת]: קובץ ההיסטוריה פגום.")
        exit()

    print("[מערכת]: מתחיל סריקת מעקב מחירים על רכבים שנשמרו בעבר...")
    cars_updated_count = 0
    total_cars_checked = 0
    tokens_to_remove = []
    cars_with_price_drops = [] # רשימה לאיסוף הרכבים שהוזלו לטובת המייל

    for run in history_data:
        if "top_recommendations" in run:
            cars_to_keep = [] 
            
            for car in run["top_recommendations"]:
                if "price_drop_alert" in car:
                    car["price_drop_alert"]["is_new"] = False

                token = car.get("additional_info", {}).get("token")
                old_price = car.get("price")
                old_score = car.get("score_out_of_10")
                
                if not token or not old_price:
                    cars_to_keep.append(car)
                    continue

                total_cars_checked += 1
                time.sleep(1) 
                
                current_price = fetch_current_price(token)
                
                if current_price == "REMOVED":
                    print(f"[{token}] 🗑️ המודעה הוסרה מיד 2! מוחק מהמאגר...")
                    tokens_to_remove.append(token)
                    cars_updated_count += 1
                    continue 

                if current_price and isinstance(current_price, (int, float)):
                    if current_price < old_price:
                        print(f"[{token}] 🚨 ירידת מחיר! {old_price} ₪ ---> {current_price} ₪. פונה ל-Gemini...")
                        
                        gemini_analysis = analyze_price_drop_with_gemini(car, old_price, current_price, old_score)
                        
                        if gemini_analysis:
                            car["price"] = current_price
                            car["score_out_of_10"] = gemini_analysis.get("new_score_out_of_10", old_score)
                            
                            car["price_drop_alert"] = {
                                "is_new": True,
                                "old_price": old_price,
                                "new_price": current_price,
                                "old_score": old_score,         
                                "analysis": gemini_analysis.get("verdict_reason", ""),
                                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                            }
                            
                            cars_updated_count += 1
                            cars_with_price_drops.append(car) # הוספת הרכב לרשימת המייל
                            print(f"   [V] הרכב עודכן בהצלחה. ציון חדש: {car['score_out_of_10']}")
                
                cars_to_keep.append(car)
            
            run["top_recommendations"] = cars_to_keep

    if cars_updated_count > 0:
        with open(RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(history_data, f, ensure_ascii=False, indent=2)
        print(f"\n[מערכת]: סריקה הסתיימה. הקובץ עודכן (נמחקו/עודכנו סה\"כ {cars_updated_count} רכבים).")
    else:
        with open(RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(history_data, f, ensure_ascii=False, indent=2)
        print(f"\n[מערכת]: סריקה הסתיימה. נבדקו {total_cars_checked} רכבים, לא נמצאו שינויים.")

    # שליחת המייל אם נמצאו ירידות מחיר
    if cars_with_price_drops:
        send_price_drop_email(cars_with_price_drops)

    if tokens_to_remove and PROCESSED_TOKENS_FILE.exists():
        try:
            with open(PROCESSED_TOKENS_FILE, "r", encoding="utf-8") as f:
                pt_data = json.load(f)
                
            if isinstance(pt_data, list):
                pt_data_cleaned = [t for t in pt_data if t not in tokens_to_remove]
                with open(PROCESSED_TOKENS_FILE, "w", encoding="utf-8") as f:
                    json.dump(pt_data_cleaned, f, ensure_ascii=False, indent=2)
                print(f"[מערכת]: {len(tokens_to_remove)} טוקנים הוסרו בהצלחה מקובץ הזיכרון.")
        except Exception as e:
            print(f"[שגיאה]: תקלה בעדכון קובץ הזיכרון: {e}")