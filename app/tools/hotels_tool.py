import csv
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSV_PATH = os.path.join(BASE_DIR, "data", "hotels_2026.csv")

def search_hotels(_state, destination, check_in, check_out, adults=1, **kwargs):
    print(f"[DEBUG] Local Hotel Search: {destination}")
    
    if not os.path.exists(CSV_PATH): return []

    req_dst = destination.lower()
    target_city = "London"
    if "paris" in req_dst: target_city = "Paris"
    elif "new york" in req_dst: target_city = "New York"

    try:
        d1 = datetime.strptime(check_in, "%Y-%m-%d")
        d2 = datetime.strptime(check_out, "%Y-%m-%d")
        nights = (d2 - d1).days
        if nights < 1: nights = 1
    except: nights = 1

    results = []
    try:
        with open(CSV_PATH, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['date'] == check_in and row['city'] == target_city:
                    price = float(row['price'])
                    results.append({
                        "name": row['name'],
                        "rating": float(row['rating']),
                        "city": row['city'],
                        "total_price": price * nights,
                        "currency": "USD",
                        "amenities": row['amenities'].split("|")
                    })
    except: return []

    sorted_results = sorted(results, key=lambda x: x['total_price'])
    
    # === התיקון: כתיבה למשתנה הנכון (hotel_options) ===
    try:
        _state.hotel_options = sorted_results
        print(f"[DEBUG] SUCCESS! Updated state.hotel_options with {len(sorted_results)} hotels.")
    except Exception as e:
        print(f"[ERROR] Failed to update state: {e}")

    return sorted_results