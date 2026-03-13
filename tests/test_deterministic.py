"""Unit tests for deterministic (zero-LLM) components.

These test pure Python logic that runs without any API or LLM calls:
- Feasibility check (Gate B)
- Rejection classification
- Destination grouping & splitting
- Cache key generation
- Budget tightness detection
- Response builders

Run with: python -m pytest tests/ -v
"""

import json
import pytest

from app.models.shared_state import SharedState
from app.agents.planner import get_destination_groups, split_tasks_by_destination
from app.utils.cache import make_cache_key


# ═══════════════════════════════════════════════════════════════════════════
#  Planner: destination grouping
# ═══════════════════════════════════════════════════════════════════════════

class TestDestinationGrouping:
    """Tests for get_destination_groups and split_tasks_by_destination."""

    def test_groups_ordered_by_first_appearance(self):
        tasks = [
            {"task": "search_flights", "destination_group": "Miami"},
            {"task": "search_hotels", "destination_group": "Miami"},
            {"task": "search_flights", "destination_group": "Paris"},
            {"task": "search_flights", "destination_group": "Tokyo"},
        ]
        groups = get_destination_groups(tasks)
        assert groups == ["Miami", "Paris", "Tokyo"]

    def test_groups_deduplicated(self):
        tasks = [
            {"task": "search_flights", "destination_group": "Miami"},
            {"task": "search_hotels", "destination_group": "Miami"},
            {"task": "get_weather", "destination_group": "Miami"},
        ]
        groups = get_destination_groups(tasks)
        assert groups == ["Miami"]

    def test_empty_task_list(self):
        assert get_destination_groups([]) == []

    def test_tasks_without_destination_group(self):
        tasks = [{"task": "rag_search", "params": {}}]
        groups = get_destination_groups(tasks)
        assert groups == []

    def test_split_by_destination(self):
        tasks = [
            {"task": "search_flights", "destination_group": "Miami"},
            {"task": "search_hotels", "destination_group": "Miami"},
            {"task": "search_flights", "destination_group": "Paris"},
            {"task": "rag_search", "params": {}},
        ]
        split = split_tasks_by_destination(tasks)
        assert len(split["Miami"]) == 2
        assert len(split["Paris"]) == 1
        assert len(split["_general"]) == 1

    def test_split_empty_list(self):
        assert split_tasks_by_destination([]) == {}


# ═══════════════════════════════════════════════════════════════════════════
#  Cache: key generation
# ═══════════════════════════════════════════════════════════════════════════

class TestCacheKeys:
    """Tests for make_cache_key determinism and uniqueness."""

    def test_same_params_same_key(self):
        p = {"destination": "Miami", "check_in": "2026-06-10"}
        k1 = make_cache_key("hotels", p)
        k2 = make_cache_key("hotels", p)
        assert k1 == k2

    def test_different_params_different_key(self):
        k1 = make_cache_key("hotels", {"destination": "Miami"})
        k2 = make_cache_key("hotels", {"destination": "Paris"})
        assert k1 != k2

    def test_different_prefix_different_key(self):
        p = {"destination": "Miami"}
        k1 = make_cache_key("hotels", p)
        k2 = make_cache_key("flights", p)
        assert k1 != k2

    def test_key_format(self):
        k = make_cache_key("weather", {"lat": 25.7})
        assert k.startswith("weather:")
        assert len(k) == len("weather:") + 16  # prefix + 16-char hex digest

    def test_param_order_irrelevant(self):
        k1 = make_cache_key("x", {"a": 1, "b": 2})
        k2 = make_cache_key("x", {"b": 2, "a": 1})
        assert k1 == k2


# ═══════════════════════════════════════════════════════════════════════════
#  Main: feasibility check (Gate B)
# ═══════════════════════════════════════════════════════════════════════════

class TestFeasibilityCheck:
    """Tests for _feasibility_check — deterministic budget guard."""

    def _make_state(self, budget, flight_price, hotel_total, duration=7):
        state = SharedState()
        state.constraints = {
            "budget_total": budget,
            "duration_days": duration,
        }
        if flight_price is not None:
            state.flight_options = [{"price": flight_price}]
        if hotel_total is not None:
            state.hotel_options = [{"total_price": hotel_total}]
        return state

    def test_feasible_within_budget(self):
        from app.main import _feasibility_check
        state = self._make_state(budget=2000, flight_price=300, hotel_total=500, duration=7)
        result = _feasibility_check(state)
        assert result is None  # feasible

    def test_infeasible_over_budget(self):
        from app.main import _feasibility_check
        state = self._make_state(budget=500, flight_price=400, hotel_total=500, duration=7)
        result = _feasibility_check(state)
        assert result is not None
        assert result["lower_bound"] > 500

    def test_no_budget_constraint(self):
        from app.main import _feasibility_check
        state = SharedState()
        state.constraints = {}
        state.flight_options = [{"price": 9999}]
        result = _feasibility_check(state)
        assert result is None  # no budget = always feasible

    def test_no_pricing_data(self):
        from app.main import _feasibility_check
        state = SharedState()
        state.constraints = {"budget_total": 1000}
        result = _feasibility_check(state)
        assert result is None  # no data = can't check

    def test_flight_price_not_doubled(self):
        """Flights are roundtrip totals — Gate B should NOT multiply by 2."""
        from app.main import _feasibility_check
        state = self._make_state(budget=1000, flight_price=300, hotel_total=400, duration=4)
        result = _feasibility_check(state)
        if result:
            assert result["cheapest_roundtrip_flight"] == 300  # not 600


# ═══════════════════════════════════════════════════════════════════════════
#  Main: rejection classification
# ═══════════════════════════════════════════════════════════════════════════

class TestRejectionClassification:
    """Tests for _classify_rejection — maps issues to repair categories."""

    def test_budget_issues(self):
        from app.main import _classify_rejection
        verdict = {"issues": ["Package total exceeds budget by 30%"]}
        assert _classify_rejection(verdict) == "BUDGET"

    def test_alignment_issues(self):
        from app.main import _classify_rejection
        verdict = {"issues": ["Check-in date doesn't match arrival"]}
        assert _classify_rejection(verdict) == "ALIGNMENT"

    def test_grounding_issues(self):
        from app.main import _classify_rejection
        verdict = {"issues": ["Fabricated hotel name not in data"]}
        assert _classify_rejection(verdict) == "GROUNDING"

    def test_missing_info(self):
        from app.main import _classify_rejection
        verdict = {"issues": ["Missing weather data"]}
        assert _classify_rejection(verdict) == "MISSING_INFO"

    def test_empty_issues_defaults_grounding(self):
        from app.main import _classify_rejection
        verdict = {"issues": []}
        assert _classify_rejection(verdict) == "GROUNDING"

    def test_multiple_issues_picks_dominant(self):
        from app.main import _classify_rejection
        verdict = {"issues": [
            "Price exceeds budget",
            "Cost too expensive",
            "Check-in date mismatch",
        ]}
        assert _classify_rejection(verdict) == "BUDGET"


# ═══════════════════════════════════════════════════════════════════════════
#  SharedState
# ═══════════════════════════════════════════════════════════════════════════

class TestSharedState:
    """Tests for SharedState LLM budget management."""

    def test_can_call_llm_initially(self):
        state = SharedState()
        assert state.can_call_llm() is True

    def test_cannot_call_after_cap(self):
        state = SharedState()
        state.llm_call_count = 8
        assert state.can_call_llm() is False

    def test_remaining_calls(self):
        state = SharedState()
        state.llm_call_count = 5
        assert state.remaining_llm_calls() == 3

    def test_cap_is_eight(self):
        state = SharedState()
        assert state.llm_call_cap == 8

    def test_default_state_empty(self):
        state = SharedState()
        assert state.flight_options == []
        assert state.hotel_options == []
        assert state.constraints == {}
        assert state.task_list == []
        assert state.draft_plans == []


# ═══════════════════════════════════════════════════════════════════════════
#  Verifier: price cross-check
# ═══════════════════════════════════════════════════════════════════════════

class TestPriceCrossCheck:
    """Tests for _cross_check_prices — catches fabricated prices."""

    def test_valid_prices_no_issues(self):
        from app.agents.verifier import _cross_check_prices
        state = SharedState()
        state.flight_options = [{"price": 300}, {"price": 450}]
        state.hotel_options = [{"total_price": 500}, {"total_price": 700}]
        plan = {
            "flights": {"total_flight_cost": 300},
            "hotel": {"total_cost": 500},
        }
        issues: list[str] = []
        _cross_check_prices(plan, state, "Pkg 1", issues)
        assert issues == []

    def test_fabricated_flight_price_detected(self):
        from app.agents.verifier import _cross_check_prices
        state = SharedState()
        state.flight_options = [{"price": 300}, {"price": 450}]
        state.hotel_options = [{"total_price": 500}]
        plan = {
            "flights": {"total_flight_cost": 150},
            "hotel": {"total_cost": 500},
        }
        issues: list[str] = []
        _cross_check_prices(plan, state, "Pkg 1", issues)
        assert len(issues) == 1
        assert "flight cost" in issues[0].lower()

    def test_fabricated_hotel_price_detected(self):
        from app.agents.verifier import _cross_check_prices
        state = SharedState()
        state.flight_options = [{"price": 300}]
        state.hotel_options = [{"total_price": 500}, {"total_price": 700}]
        plan = {
            "flights": {"total_flight_cost": 300},
            "hotel": {"total_cost": 99},
        }
        issues: list[str] = []
        _cross_check_prices(plan, state, "Pkg 1", issues)
        assert len(issues) == 1
        assert "hotel cost" in issues[0].lower()

    def test_close_price_within_tolerance(self):
        from app.agents.verifier import _cross_check_prices
        state = SharedState()
        state.flight_options = [{"price": 300}]
        state.hotel_options = [{"total_price": 500}]
        plan = {
            "flights": {"total_flight_cost": 303},
            "hotel": {"total_cost": 505},
        }
        issues: list[str] = []
        _cross_check_prices(plan, state, "Pkg 1", issues)
        assert issues == []


class TestGroupDataByDestination:
    """Tests for _group_data_by_destination — ensures flightless destinations are excluded."""

    def test_excludes_destinations_without_flights(self):
        from app.agents.synthesizer import _group_data_by_destination
        state = SharedState()
        state.flight_options = [
            {"destination_city": "Miami", "price": 300},
            {"destination_city": "Miami", "price": 350},
        ]
        state.hotel_options = [
            {"destination_city": "Miami", "total_price": 500},
            {"destination_city": "Montauk", "total_price": 200},
            {"destination_city": "Nags Head", "total_price": 150},
        ]
        state.weather_context = []
        state.poi_list = []
        result = _group_data_by_destination(state)
        assert "Montauk" not in result
        assert "Nags Head" not in result

    def test_includes_destinations_with_flights(self):
        from app.agents.synthesizer import _group_data_by_destination
        state = SharedState()
        state.flight_options = [
            {"destination_city": "Miami", "price": 300},
            {"destination_city": "Cancun", "price": 400},
        ]
        state.hotel_options = [
            {"destination_city": "Miami", "total_price": 500},
            {"destination_city": "Cancun", "total_price": 600},
        ]
        state.weather_context = []
        state.poi_list = []
        result = _group_data_by_destination(state)
        assert "Miami" in result
        assert "Cancun" in result
        assert len(result["Miami"]["flights"]) == 1
        assert len(result["Cancun"]["flights"]) == 1

    def test_single_destination_with_flights_returns_grouped(self):
        from app.agents.synthesizer import _group_data_by_destination
        state = SharedState()
        state.flight_options = [{"destination_city": "Miami", "price": 300}]
        state.hotel_options = [
            {"destination_city": "Miami", "total_price": 500},
            {"destination_city": "Montauk", "total_price": 200},
        ]
        state.weather_context = []
        state.poi_list = []
        result = _group_data_by_destination(state)
        assert "Miami" in result
        assert "Montauk" not in result

    def test_empty_flights_returns_empty(self):
        from app.agents.synthesizer import _group_data_by_destination
        state = SharedState()
        state.flight_options = []
        state.hotel_options = [{"destination_city": "Montauk", "total_price": 200}]
        state.weather_context = []
        state.poi_list = []
        result = _group_data_by_destination(state)
        assert result == {}


class TestWantsDifferentDestinations:
    """Tests for _wants_different_destinations — detects alternative requests."""

    def test_detects_different(self):
        from app.main import _wants_different_destinations
        assert _wants_different_destinations("give me different locations") is True
        assert _wants_different_destinations("show me other options") is True
        assert _wants_different_destinations("alternative destinations") is True
        assert _wants_different_destinations("new places please") is True

    def test_ignores_unrelated(self):
        from app.main import _wants_different_destinations
        assert _wants_different_destinations("from tlv") is False
        assert _wants_different_destinations("cheaper hotel") is False
        assert _wants_different_destinations("budget 2000") is False


class TestFabricatedTransportDetection:
    """Verifier should catch fabricated drive/bus/train transport."""

    def test_drive_detected(self):
        state = SharedState()
        state.flight_options = []
        state.hotel_options = []
        issues: list[str] = []
        plan = {
            "destination": "Montauk",
            "flights": {
                "outbound": {"airline": "Drive (self-drive)", "origin": "NYC", "destination": "Montauk"},
                "total_flight_cost": 0,
            },
            "hotel": {},
            "weather_summary": "warm",
            "itinerary": [{"day": 1}],
            "cost_breakdown": {"total": 1000},
            "rationale": "test",
        }
        from app.agents.verifier import _REQUIRED_KEYS
        missing = _REQUIRED_KEYS - set(plan.keys())
        assert not missing

        flights = plan.get("flights", {})
        if isinstance(flights, dict):
            outbound = flights.get("outbound", {})
            if isinstance(outbound, dict):
                airline = outbound.get("airline", "").lower()
                if any(fake in airline for fake in ("drive", "self-drive", "bus", "train", "ferry", "car")):
                    issues.append("fabricated transport detected")

        assert len(issues) == 1


# ═══════════════════════════════════════════════════════════════════════════
#  Verification tests for recent changes (contracts A-F)
# ═══════════════════════════════════════════════════════════════════════════

class TestFlightPricingSemantics:
    """Contract A: Flight prices are per-person; totals account for travelers."""

    def test_feasibility_multiplies_by_travelers(self):
        """2 travelers -> flight cost doubled in feasibility check."""
        from app.main import _feasibility_check
        state = SharedState()
        state.constraints = {
            "budget_total": 1000,
            "duration_days": 3,
            "travelers": 2,
        }
        state.flight_options = [{"price": 300}]
        state.hotel_options = [{"total_price": 200}]
        result = _feasibility_check(state)
        # Lower bound: 300*2 + 200 + 50*3*2 = 600+200+300 = 1100 > 1000*1.05
        assert result is not None
        assert result["cheapest_roundtrip_flight"] == 600  # 300 * 2 travelers
        assert result["cheapest_flight_per_person"] == 300
        assert result["travelers"] == 2

    def test_feasibility_single_traveler_no_multiply(self):
        """1 traveler -> flight cost used as-is."""
        from app.main import _feasibility_check
        state = SharedState()
        state.constraints = {
            "budget_total": 2000,
            "duration_days": 3,
            "travelers": 1,
        }
        state.flight_options = [{"price": 300}]
        state.hotel_options = [{"total_price": 200}]
        result = _feasibility_check(state)
        assert result is None

    def test_feasibility_no_travelers_defaults_to_one(self):
        """No travelers field -> defaults to 1, not doubled."""
        from app.main import _feasibility_check
        state = SharedState()
        state.constraints = {
            "budget_total": 2000,
            "duration_days": 3,
        }
        state.flight_options = [{"price": 300}]
        state.hotel_options = [{"total_price": 200}]
        result = _feasibility_check(state)
        assert result is None

    def test_budget_tight_respects_travelers(self):
        from app.main import _is_budget_tight
        state = SharedState()
        state.constraints = {
            "budget_total": 1000,
            "duration_days": 4,
            "travelers": 2,
        }
        state.flight_options = [{"price": 200}]
        state.hotel_options = [{"total_price": 300}]
        # Lower bound: 200*2 + 300 + 50*4*2 = 400+300+400 = 1100 > 850
        assert _is_budget_tight(state) is True

    def test_price_cross_check_allows_traveler_multiples(self):
        """Price grounding should allow 2x of per-person price."""
        from app.agents.verifier import _cross_check_prices
        state = SharedState()
        state.flight_options = [{"price": 300}]
        state.hotel_options = [{"total_price": 500}]
        plan = {
            "flights": {"total_flight_cost": 600},  # 300 * 2 travelers
            "hotel": {"total_cost": 500},
        }
        issues: list[str] = []
        _cross_check_prices(plan, state, "Pkg 1", issues)
        assert issues == []


class TestFlightDateSanity:
    """Contract B: Flight datetime sanity checks."""

    def test_valid_flight_dates_no_issues(self):
        from app.agents.verifier import _check_flight_dates
        state = SharedState()
        plan = {
            "flights": {
                "outbound": {
                    "departure": "2026-06-10T08:00:00",
                    "arrival": "2026-06-10T14:00:00",
                },
                "return": {
                    "departure": "2026-06-17T10:00:00",
                    "arrival": "2026-06-17T16:00:00",
                },
            },
            "date_window": "2026-06-10 to 2026-06-17",
        }
        issues: list[str] = []
        _check_flight_dates(plan, state, "Pkg 1", issues)
        assert issues == []

    def test_arrival_before_departure_flagged(self):
        from app.agents.verifier import _check_flight_dates
        state = SharedState()
        plan = {
            "flights": {
                "outbound": {
                    "departure": "2026-06-10T14:00:00",
                    "arrival": "2026-06-10T08:00:00",
                },
            },
        }
        issues: list[str] = []
        _check_flight_dates(plan, state, "Pkg 1", issues)
        assert any("before departure" in i for i in issues)

    def test_next_day_arrival_is_valid(self):
        """Long-haul flight arriving next day should NOT be flagged."""
        from app.agents.verifier import _check_flight_dates
        state = SharedState()
        plan = {
            "flights": {
                "outbound": {
                    "departure": "2026-06-10T22:00:00",
                    "arrival": "2026-06-11T06:00:00",
                },
            },
            "date_window": "2026-06-10 to 2026-06-17",
        }
        issues: list[str] = []
        _check_flight_dates(plan, state, "Pkg 1", issues)
        assert issues == []

    def test_return_before_outbound_flagged(self):
        from app.agents.verifier import _check_flight_dates
        state = SharedState()
        plan = {
            "flights": {
                "outbound": {
                    "departure": "2026-06-10T08:00:00",
                    "arrival": "2026-06-10T14:00:00",
                },
                "return": {
                    "departure": "2026-06-09T10:00:00",
                    "arrival": "2026-06-09T16:00:00",
                },
            },
        }
        issues: list[str] = []
        _check_flight_dates(plan, state, "Pkg 1", issues)
        assert any("before outbound arrival" in i for i in issues)

    def test_flight_outside_date_window_flagged(self):
        from app.agents.verifier import _check_flight_dates
        state = SharedState()
        plan = {
            "flights": {
                "outbound": {
                    "departure": "2026-07-15T08:00:00",
                    "arrival": "2026-07-15T14:00:00",
                },
            },
            "date_window": "2026-06-10 to 2026-06-17",
        }
        issues: list[str] = []
        _check_flight_dates(plan, state, "Pkg 1", issues)
        assert any("outside date_window" in i for i in issues)

    def test_excessive_duration_flagged(self):
        from app.agents.verifier import _check_flight_dates
        state = SharedState()
        plan = {
            "flights": {
                "outbound": {
                    "departure": "2026-06-10T08:00:00",
                    "arrival": "2026-06-12T16:00:00",
                },
            },
        }
        issues: list[str] = []
        _check_flight_dates(plan, state, "Pkg 1", issues)
        assert any("exceeds 30h" in i for i in issues)


class TestHotelDataIntegrity:
    """Contract C: Hotel data quality checks."""

    def test_zero_price_hotel_filtered(self):
        from app.tools.hotels_tool import _parse_hotel_results
        raw = {
            "data": {
                "hotels": [
                    {"property": {"name": "Good Hotel", "priceBreakdown": {"grossPrice": {"value": 500}}, "reviewScore": 8}},
                    {"property": {"name": "Zero Hotel", "priceBreakdown": {"grossPrice": {"value": 0}}, "reviewScore": 7}},
                ]
            }
        }
        options = _parse_hotel_results(raw, "2026-06-10", "2026-06-14", "Paris", adults=2)
        assert len(options) == 1
        assert options[0]["name"] == "Good Hotel"

    def test_booking_url_has_correct_adults(self):
        from app.tools.hotels_tool import _build_hotel_url
        url = _build_hotel_url("Test Hotel", "2026-06-10", "2026-06-14", adults=2)
        assert "group_adults=2" in url

    def test_booking_url_defaults_to_one(self):
        from app.tools.hotels_tool import _build_hotel_url
        url = _build_hotel_url("Test Hotel", "2026-06-10", "2026-06-14")
        assert "group_adults=1" in url

    def test_verifier_flags_zero_hotel_cost(self):
        from app.agents.verifier import _check_hotel_data
        plan = {
            "hotel": {"name": "Bad Hotel", "total_cost": 0, "per_night": 0},
            "cost_breakdown": {"hotel": 0},
        }
        issues: list[str] = []
        _check_hotel_data(plan, "Pkg 1", issues)
        assert any("zero or missing" in i for i in issues)

    def test_verifier_passes_valid_hotel(self):
        from app.agents.verifier import _check_hotel_data
        plan = {
            "hotel": {"name": "Good Hotel", "total_cost": 500, "per_night": 100},
            "cost_breakdown": {"hotel": 500},
        }
        issues: list[str] = []
        _check_hotel_data(plan, "Pkg 1", issues)
        assert issues == []

    def test_verifier_flags_hotel_not_in_cost_breakdown(self):
        from app.agents.verifier import _check_hotel_data
        plan = {
            "hotel": {"name": "Nice Hotel", "total_cost": 500, "per_night": 100},
            "cost_breakdown": {"hotel": 0},
        }
        issues: list[str] = []
        _check_hotel_data(plan, "Pkg 1", issues)
        assert any("not reflected in cost_breakdown" in i for i in issues)


class TestItineraryDateAlignment:
    """Contract B (cont.): Itinerary days match date_window."""

    def test_matching_days_no_issues(self):
        from app.agents.verifier import _check_itinerary_date_alignment
        plan = {
            "itinerary": [{"day": 1}, {"day": 2}, {"day": 3}, {"day": 4}],
            "date_window": "2026-06-10 to 2026-06-13",
        }
        issues: list[str] = []
        _check_itinerary_date_alignment(plan, "Pkg 1", issues)
        assert issues == []

    def test_missing_days_flagged(self):
        from app.agents.verifier import _check_itinerary_date_alignment
        plan = {
            "itinerary": [{"day": 1}, {"day": 2}],
            "date_window": "2026-06-10 to 2026-06-16",
        }
        issues: list[str] = []
        _check_itinerary_date_alignment(plan, "Pkg 1", issues)
        assert any("missing" in i for i in issues)

    def test_off_by_one_tolerated(self):
        from app.agents.verifier import _check_itinerary_date_alignment
        plan = {
            "itinerary": [{"day": 1}, {"day": 2}, {"day": 3}],
            "date_window": "2026-06-10 to 2026-06-13",
        }
        issues: list[str] = []
        _check_itinerary_date_alignment(plan, "Pkg 1", issues)
        assert issues == []


class TestSessionContinuity:
    """Contract D: session_id preserved across all response paths."""

    def test_with_metadata_always_sets_session_id(self):
        import time
        from app.main import _with_metadata
        from app.models.schemas import ExecuteResponse
        state = SharedState()
        state.session_id = "test-session-123"
        state.llm_call_count = 3
        resp = ExecuteResponse(status="ok", error=None, response="test", steps=[])
        result = _with_metadata(resp, state, time.time())
        assert result.session_id == "test-session-123"
        assert result.llm_calls_used == 3

    def test_no_data_response_preserves_session(self):
        from app.main import _build_no_data_response, _session_memory
        state = SharedState()
        state.session_id = "no-data-session"
        state.constraints = {"origin": "NYC"}
        _build_no_data_response(state)
        assert "no-data-session" in _session_memory
        del _session_memory["no-data-session"]

    def test_gate_b_response_preserves_session(self):
        from app.main import _build_gate_b_response, _session_memory
        state = SharedState()
        state.session_id = "gate-b-session"
        state.constraints = {"origin": "NYC", "destinations": ["Paris"]}
        feasibility = {
            "lower_bound": 2000, "cheapest_roundtrip_flight": 800,
            "cheapest_flight_per_person": 400, "travelers": 2,
            "hotel_total": 600, "daily_expenses": 600,
            "duration": 7, "budget": 1000, "gap_pct": 100,
            "dominant_cost": "flights",
        }
        _build_gate_b_response(state, feasibility)
        assert "gate-b-session" in _session_memory
        del _session_memory["gate-b-session"]
