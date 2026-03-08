"""POI tool -- MOCK VERSION with Random Generation.
Generates random points of interest without calling external APIs.
"""

from __future__ import annotations

import random
from typing import Any

from app.models.shared_state import SharedState
from app.utils.step_logger import log_tool_call
from app.tools.geocode import geocode

_POI_TYPES = ["Museum", "Park", "Square", "Tower", "Market", "Bridge"]

def search_pois(
    state: SharedState,
    latitude: float = 0.0,
    longitude: float = 0.0,
    radius_m: int = 5000,
    kinds: str = "interesting_places",
    limit: int = 15,
    destination_name: str = "",
) -> list[dict[str, Any]]:
    """Generate 3 random POIs near the destination."""
    
    print(f"   [MOCK POI] Generating random POIs for {destination_name}")

    # נסיון להשיג קואורדינטות אמיתיות אם חסר (בעזרת הכלי החינמי)
    # אם זה נכשל, נשתמש ב-0,0 וזה בסדר למוק
    if (not latitude or not longitude) and destination_name:
        coords = geocode(destination_name)
        if coords:
            latitude, longitude = coords

    options = []
    for i in range(3):
        category = random.choice(_POI_TYPES)
        name = f"The {destination_name} {category}"
        
        # יצירת "רעש" בקואורדינטות כדי שלא כולם יהיו באותה נקודה
        # שינוי של 0.01 מעלה זה בערך קילומטר
        lat_offset = random.uniform(-0.02, 0.02)
        lon_offset = random.uniform(-0.02, 0.02)

        poi = {
            "name": name,
            "kinds": "interesting_places,tourist_object",
            "lat": latitude + lat_offset,
            "lon": longitude + lon_offset,
            "xid": f"mock_xid_{random.randint(10000,99999)}"
        }
        options.append(poi)

    state.poi_list.extend(options)
    log_tool_call(state, "Executor", "poi_search", 
                 {"dest": destination_name}, 
                 {"count": len(options), "source": "RANDOM_MOCK"})
    
    return options