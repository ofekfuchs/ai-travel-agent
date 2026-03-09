import requests
import json
import sys
import os
import time

# הגדרות
API_URL = "http://127.0.0.1:8000/api/execute"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILENAME = os.path.join(BASE_DIR, "stress_test_formatted.txt")

def clean_print(text):
    """מדפיס גם למסך וגם לקובץ בצורה נקייה"""
    print(text)
    try:
        with open(OUTPUT_FILENAME, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except: pass

def parse_supervisor_decision(steps):
    """מחלץ את ההחלטה והסיבה מתוך הלוגים הפנימיים"""
    if not steps:
        return "N/A", "No steps recorded", None

    last_step = steps[-1]
    response_block = last_step.get("response", {})
    content = response_block.get("content", {})

    # טיפול במקרה שהתוכן הוא string (json stringified)
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except:
            pass # משאיר כמו שהוא אם זה לא ג'ייסון

    if isinstance(content, dict):
        action = content.get("next_action", "UNKNOWN").upper()
        reason = content.get("reason", "No reason provided")
        question = content.get("clarification_question")
        return action, reason, question
    
    return "ERROR", str(content), None

def run_test(prompt, index, total):
    header = f"\n🔹 TEST {index}/{total}: \"{prompt}\""
    clean_print(header)
    clean_print("-" * 60)

    try:
        response = requests.post(API_URL, json={"prompt": prompt})
        
        if response.status_code != 200:
            clean_print(f"❌ SERVER ERROR: {response.status_code}")
            return

        data = response.json()
        
        # 1. ניתוח המוח של הסופרוויזור
        action, reason, question = parse_supervisor_decision(data.get("steps", []))
        
        # הדפסה יפה של ההחלטה
        if action == "PLAN":
            clean_print(f"🧠 DECISION:  ✅ PLAN")
        elif action == "ASK_CLARIFICATION":
            clean_print(f"🧠 DECISION:  ✋ ASK CLARIFICATION")
        else:
            clean_print(f"🧠 DECISION:  ⚠️ {action}")

        clean_print(f"💡 REASON:    {reason}")
        
        if question:
            clean_print(f"❓ QUESTION:  {question}")

        # 2. ניתוח התשובה הסופית למשתמש
        final_res = data.get("response")
        clean_print("-" * 60)
        if final_res:
            # מנקה רווחים מיותרים
            clean_print(f"📝 FINAL OUTPUT:\n{str(final_res).strip()}")
        else:
            clean_print("❌ NO FINAL OUTPUT (Did you restart the server?)")
            
        clean_print("=" * 60)

    except Exception as e:
        clean_print(f"❌ CRITICAL ERROR: {e}")

if __name__ == "__main__":
    # מנקה קובץ לוג ישן
    if os.path.exists(OUTPUT_FILENAME):
        try: os.remove(OUTPUT_FILENAME)
        except: pass

    TEST_CASES = [
            # 1. Happy Path
            "Plan a 3-day trip from Tel Aviv to Paris in May 2026. Budget $1500.",

            # 2. Anchor Rule (הוספתי "from Tel Aviv" כדי שלא ייפול על חוסר במוצא)
            "I want a surfing trip to Europe from Tel Aviv in September 2026. Keep it cheap.",

            # 3. Broad Guard (אמור להיחסם)
            "Show me all available flights to Europe for the entire month of September 2026.",

            # 4. Capability Guard (אמור להיחסם)
            "Please book the flight to Paris for me using my credit card.",
            
            # 5. Missing Info (אמור להיחסם)
            "I want to fly from Tel Aviv to London."
        ]

    print(f"🚀 Starting nice formatting test...\n")
    
    for i, prompt in enumerate(TEST_CASES, 1):
        run_test(prompt, i, len(TEST_CASES))
        time.sleep(0.5)

    print(f"\n📄 Full results saved to: {OUTPUT_FILENAME}")