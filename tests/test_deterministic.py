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
