"""Domain data models used inside Shared State and by the Trip Synthesizer."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FlightOption:
    origin: str = ""
    destination: str = ""
    departure_date: str = ""
    return_date: str = ""
    price: float = 0.0
    currency: str = "USD"
    airline: str = ""
    duration: str = ""
    stops: int = 0
    raw_data: dict = field(default_factory=dict)


@dataclass
class HotelOption:
    name: str = ""
    destination: str = ""
    check_in: str = ""
    check_out: str = ""
    price_per_night: float = 0.0
    total_price: float = 0.0
    currency: str = "USD"
    rating: float = 0.0
    raw_data: dict = field(default_factory=dict)


@dataclass
class WeatherInfo:
    destination: str = ""
    date_range: str = ""
    avg_temp_c: float = 0.0
    conditions: str = ""
    is_forecast: bool = True
    raw_data: dict = field(default_factory=dict)


@dataclass
class POI:
    name: str = ""
    category: str = ""
    lat: float = 0.0
    lon: float = 0.0
    description: str = ""
    raw_data: dict = field(default_factory=dict)


@dataclass
class ItineraryDay:
    day_number: int = 0
    date: str = ""
    activities: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class TripPlan:
    destination: str = ""
    date_window: str = ""
    flights: list[FlightOption] = field(default_factory=list)
    hotels: list[HotelOption] = field(default_factory=list)
    weather: list[WeatherInfo] = field(default_factory=list)
    itinerary: list[ItineraryDay] = field(default_factory=list)
    total_cost: float = 0.0
    cost_breakdown: dict = field(default_factory=dict)
    rationale: str = ""
    assumptions: list[str] = field(default_factory=list)
    label: str = ""  # e.g. "cheapest", "balanced", "premium"
