import csv
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSV_PATH = os.path.join(BASE_DIR, "data", "flights_2026.csv")

def search_flights(_state, origin, destination, date, return_date=None, **kwargs):
    print(f"[DEBUG] Local Search: {origin} -> {destination} on {date}")
    
    if not os.path.exists(CSV_PATH):
        print(f"[ERROR] CSV missing: {CSV_PATH}")
        return []

    results = []
    req_org = origin.lower()
    req_dst = destination.lower()
    
    target_dest = "London"
    if "paris" in req_dst: target_dest = "Paris"
    elif "new york" in req_dst: target_dest = "New York"
    
    org_candidates = {req_org}
    if "tel aviv" in req_org or "tlv" in req_org:
        org_candidates.update(["tel aviv", "tlv", "ben gurion"])

    try:
        with open(CSV_PATH, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['date'] != date: continue
                if row['dst'] != target_dest: continue
                
                row_org = row['org'].lower()
                if not any(c in row_org for c in org_candidates): continue

                results.append({
                    "airline": row['airline'],
                    "price": float(row['price']),
                    "departure": row['dep'],
                    "duration": int(row['dur']),
                    "outbound": {
                        "airline": row['airline'],
                        "flight_number": row['num'],
                        "origin": row['org'],
                        "destination": row['dst'],
                        "departure": row['dep'],
                        "arrival": row['arr'],
                    }
                })
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return []

    sorted_results = sorted(results, key=lambda x: x['price'])
    
    # === התיקון: כתיבה למשתנה הנכון (flight_options) ===
    try:
        # דריסה מלאה של הרשימה הקיימת כדי להבטיח עדכון
        _state.flight_options = sorted_results
        print(f"[DEBUG] SUCCESS! Updated state.flight_options with {len(sorted_results)} flights.")
    except Exception as e:
        print(f"[ERROR] Failed to update state: {e}")
    
    return sorted_results