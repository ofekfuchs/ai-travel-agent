import csv
import os
import random
from datetime import datetime, timedelta

# יצירת תיקיית דאטה
if not os.path.exists("data"):
    os.makedirs("data")

# --- תבניות בסיס (עם Tel Aviv) ---
FLIGHT_TEMPLATES = [
    # לונדון
    {"airline": "El Al", "num": "LY315", "org": "Tel Aviv", "dst": "London", "dep": "10:00", "dur": 330, "base": 600},
    {"airline": "British Airways", "num": "BA164", "org": "Tel Aviv", "dst": "London", "dep": "16:35", "dur": 335, "base": 650},
    {"airline": "Wizz Air", "num": "W9445", "org": "Tel Aviv", "dst": "London", "dep": "21:55", "dur": 325, "base": 250},
    {"airline": "EasyJet", "num": "U2208", "org": "Tel Aviv", "dst": "London", "dep": "06:15", "dur": 330, "base": 290},
    # פריז
    {"airline": "El Al", "num": "LY323", "org": "Tel Aviv", "dst": "Paris", "dep": "09:00", "dur": 295, "base": 550},
    {"airline": "Air France", "num": "AF963", "org": "Tel Aviv", "dst": "Paris", "dep": "16:50", "dur": 305, "base": 600},
    # ניו יורק
    {"airline": "El Al", "num": "LY001", "org": "Tel Aviv", "dst": "New York", "dep": "00:45", "dur": 720, "base": 1100},
    {"airline": "United", "num": "UA085", "org": "Tel Aviv", "dst": "New York", "dep": "11:00", "dur": 740, "base": 950},
]

HOTELS_TEMPLATES = [
    {"name": "The Ritz London", "city": "London", "rating": 5.0, "base": 950, "amenities": "Luxury|Spa"},
    {"name": "Strand Palace", "city": "London", "rating": 4.0, "base": 230, "amenities": "Central|Gym"},
    {"name": "Generator London", "city": "London", "rating": 3.0, "base": 50, "amenities": "Hostel|Bar"},
    {"name": "Ritz Paris", "city": "Paris", "rating": 5.0, "base": 1400, "amenities": "Luxury|History"},
    {"name": "Ibis Bastille", "city": "Paris", "rating": 3.0, "base": 100, "amenities": "Basic|WiFi"},
    {"name": "The Plaza", "city": "New York", "rating": 5.0, "base": 1300, "amenities": "Iconic|Luxury"},
    {"name": "Pod 51", "city": "New York", "rating": 3.0, "base": 120, "amenities": "Budget|Rooftop"},
]

def generate():
    print("🎲 Generating 2026 data (Seasonality + Christmas + Weekends)...")

    f_flights = open("data/flights_2026.csv", "w", newline="", encoding="utf-8")
    f_hotels = open("data/hotels_2026.csv", "w", newline="", encoding="utf-8")
    
    wf = csv.DictWriter(f_flights, fieldnames=["date", "airline", "num", "org", "dst", "dep", "arr", "dur", "price"])
    wh = csv.DictWriter(f_hotels, fieldnames=["date", "name", "city", "rating", "price", "amenities"])
    
    wf.writeheader()
    wh.writeheader()

    curr = datetime(2026, 1, 1)
    end = datetime(2026, 12, 31)

    while curr <= end:
        date_str = curr.strftime("%Y-%m-%d")
        month = curr.month
        
        # זיהוי סופ"ש: 4=שישי, 5=שבת, 6=ראשון
        is_weekend = curr.weekday() in [4, 5, 6] 

        # --- שכבה 1: עונתיות בסיסית ---
        if month == 12 and curr.day >= 15: # כריסמס
            season_mult = 1.8
            availability = 0.4 
        elif month in [7, 8]: # קיץ
            season_mult = 1.4
            availability = 0.6
        elif month in [1, 2]: # חורף
            season_mult = 0.8
            availability = 0.95
        else: # רגיל
            season_mult = 1.0
            availability = 0.9

        # --- שכבה 2: תוספת סופ"ש ---
        if is_weekend:
            season_mult += 0.25 # מייקרים בעוד 25%
            availability -= 0.1 # קצת פחות זמינות בסופ"ש

        # 1. ג'ינרוט טיסות
        for flt in FLIGHT_TEMPLATES:
            if random.random() > availability: continue 

            dep_dt = datetime.strptime(f"{date_str} {flt['dep']}", "%Y-%m-%d %H:%M")
            arr_dt = dep_dt + timedelta(minutes=flt['dur'])
            
            # מחיר סופי (בסיס * מכפיל עונה + רעש רנדומלי)
            price = int(flt['base'] * season_mult) + random.randint(-20, 20)

            wf.writerow({
                "date": date_str, "airline": flt['airline'], "num": flt['num'],
                "org": flt['org'], "dst": flt['dst'],
                "dep": dep_dt.strftime("%Y-%m-%dT%H:%M:00"),
                "arr": arr_dt.strftime("%Y-%m-%dT%H:%M:00"),
                "dur": flt['dur'], "price": price
            })

        # 2. ג'ינרוט מלונות
        for h in HOTELS_TEMPLATES:
            if random.random() > (availability + 0.1): continue

            price = int(h['base'] * season_mult) + random.randint(-10, 50)
            wh.writerow({
                "date": date_str, "name": h['name'], "city": h['city'],
                "rating": h['rating'], "price": price, "amenities": h['amenities']
            })

        curr += timedelta(days=1)

    f_flights.close()
    f_hotels.close()
    print("✅ Files created! (Check weekends & holidays)")

if __name__ == "__main__":
    generate()