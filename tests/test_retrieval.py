"""Phase 2 — deterministic retrieval engine tests."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.data.loader import RestaurantStore
from app.data.models import DayHours, HardConstraints, QueryIntent, Restaurant
from app.retrieval.filters import (
    apply_hard_constraints,
    filter_by_city,
    filter_by_cuisines,
    filter_by_delivery,
    filter_by_locality,
    filter_by_max_cost,
    filter_by_min_rating,
    filter_by_open_now,
    filter_by_price_range,
    filter_by_table_booking,
    filter_by_veg,
)
from app.retrieval.relaxation import RelaxationPolicy
from app.retrieval.retriever import Retriever, pre_rank
from app.utils.hours import is_open_at, is_open_now

TZ = ZoneInfo("Asia/Kolkata")


def _hours(
    open_time: str = "11:00", close_time: str = "23:00"
) -> dict[str, DayHours]:
    day = DayHours(open=open_time, close=close_time)
    return {d: day for d in (
        "monday", "tuesday", "wednesday", "thursday",
        "friday", "saturday", "sunday",
    )}


def _overnight_friday() -> dict[str, DayHours]:
    return {
        "friday": DayHours(open="18:00", close="02:00"),
    }


@pytest.fixture
def catalog() -> list[Restaurant]:
    return [
        Restaurant(
            restaurant_id="R001",
            name="Green Garden Cafe",
            city="bengaluru",
            locality="indiranagar",
            cuisines=["North Indian", "Continental"],
            average_cost_for_two=1200,
            price_range=2,
            rating=4.5,
            votes=842,
            is_veg="Veg",
            has_table_booking=True,
            has_online_delivery=True,
            opening_hours=_hours(),
        ),
        Restaurant(
            restaurant_id="R002",
            name="Spice Route",
            city="bengaluru",
            locality="koramangala",
            cuisines=["Chinese", "Thai"],
            average_cost_for_two=800,
            price_range=2,
            rating=4.2,
            votes=512,
            is_veg="Both",
            has_table_booking=False,
            has_online_delivery=True,
            opening_hours=_hours("12:00", "22:30"),
        ),
        Restaurant(
            restaurant_id="R003",
            name="The Grill House",
            city="bengaluru",
            locality="mg road",
            cuisines=["BBQ", "Steak"],
            average_cost_for_two=2500,
            price_range=4,
            rating=4.7,
            votes=1203,
            is_veg="Non-Veg",
            has_table_booking=True,
            has_online_delivery=False,
            opening_hours=_hours("19:00", "23:30"),
        ),
        Restaurant(
            restaurant_id="R004",
            name="Budget Bites",
            city="bengaluru",
            locality="indiranagar",
            cuisines=["Street Food"],
            average_cost_for_two=300,
            price_range=1,
            rating=3.8,
            votes=200,
            is_veg="Veg",
            has_table_booking=False,
            has_online_delivery=True,
            opening_hours=_hours(),
        ),
        Restaurant(
            restaurant_id="R005",
            name="Night Owl Diner",
            city="bengaluru",
            locality="koramangala",
            cuisines=["American"],
            average_cost_for_two=600,
            price_range=2,
            rating=4.0,
            votes=350,
            is_veg="Both",
            has_table_booking=True,
            has_online_delivery=False,
            opening_hours=_overnight_friday(),
        ),
        Restaurant(
            restaurant_id="R006",
            name="Mumbai Spice",
            city="mumbai",
            locality="bandra",
            cuisines=["Maharashtrian"],
            average_cost_for_two=900,
            price_range=2,
            rating=4.1,
            votes=400,
            is_veg="Both",
            opening_hours=_hours(),
        ),
    ]


@pytest.fixture
def store(catalog: list[Restaurant]) -> RestaurantStore:
    return RestaurantStore(catalog)


@pytest.fixture
def retriever(store: RestaurantStore) -> Retriever:
    return Retriever(store, timezone="Asia/Kolkata")


def test_filter_by_city_case_insensitive(catalog: list[Restaurant]) -> None:
    result = filter_by_city(catalog, "Bengaluru")
    assert len(result) == 5
    assert all(r.city == "bengaluru" for r in result)


def test_filter_by_locality_exact_and_fuzzy(catalog: list[Restaurant]) -> None:
    exact = filter_by_locality(catalog, "indiranagar")
    assert {r.restaurant_id for r in exact} == {"R001", "R004"}

    fuzzy = filter_by_locality(catalog, "mg road")
    assert any(r.restaurant_id == "R003" for r in fuzzy)


def test_filter_by_cuisines_overlap(catalog: list[Restaurant]) -> None:
    result = filter_by_cuisines(catalog, ["Chinese"])
    assert {r.restaurant_id for r in result} == {"R002"}


def test_filter_by_veg_logic(catalog: list[Restaurant]) -> None:
    veg = filter_by_veg(catalog, True)
    assert all(r.is_veg in ("Veg", "Both") for r in veg)
    assert "R003" not in {r.restaurant_id for r in veg}

    nonveg = filter_by_veg(catalog, False)
    assert "R001" not in {r.restaurant_id for r in nonveg}
    assert "R003" in {r.restaurant_id for r in nonveg}


def test_filter_by_max_cost(catalog: list[Restaurant]) -> None:
    result = filter_by_max_cost(catalog, 500)
    assert {r.restaurant_id for r in result} == {"R004"}


def test_filter_by_min_rating(catalog: list[Restaurant]) -> None:
    result = filter_by_min_rating(catalog, 4.5)
    assert {r.restaurant_id for r in result} == {"R001", "R003"}


def test_filter_by_table_booking(catalog: list[Restaurant]) -> None:
    result = filter_by_table_booking(catalog, True)
    assert all(r.has_table_booking for r in result)


def test_filter_by_delivery(catalog: list[Restaurant]) -> None:
    result = filter_by_delivery(catalog, True)
    assert all(r.has_online_delivery for r in result)


def test_filter_by_price_range(catalog: list[Restaurant]) -> None:
    result = filter_by_price_range(catalog, 1)
    assert {r.restaurant_id for r in result} == {"R004"}


def test_is_open_at_same_day_hours() -> None:
    assert is_open_at("11:00", "23:00", 12 * 60)
    assert not is_open_at("11:00", "23:00", 10 * 60)
    assert not is_open_at("11:00", "23:00", 23 * 60)


def test_is_open_at_overnight_hours() -> None:
    assert is_open_at("18:00", "02:00", 20 * 60)
    assert is_open_at("18:00", "02:00", 1 * 60)
    assert not is_open_at("18:00", "02:00", 3 * 60)


def test_is_open_now_overnight_spill_from_previous_day() -> None:
    saturday_1am = datetime(2026, 6, 20, 1, 0, tzinfo=TZ)
    assert is_open_now(_overnight_friday(), now=saturday_1am, timezone="Asia/Kolkata")

    saturday_3am = datetime(2026, 6, 20, 3, 0, tzinfo=TZ)
    assert not is_open_now(_overnight_friday(), now=saturday_3am, timezone="Asia/Kolkata")


def test_is_open_now_closed_day_missing_hours() -> None:
    monday_noon = datetime(2026, 6, 15, 12, 0, tzinfo=TZ)
    assert not is_open_now(_overnight_friday(), now=monday_noon, timezone="Asia/Kolkata")


def test_filter_by_open_now_at_3am(catalog: list[Restaurant]) -> None:
    saturday_3am = datetime(2026, 6, 20, 3, 0, tzinfo=TZ)
    result = filter_by_open_now(
        catalog, open_now=True, now=saturday_3am, timezone="Asia/Kolkata"
    )
    assert result == []

    saturday_1am = datetime(2026, 6, 20, 1, 0, tzinfo=TZ)
    result = filter_by_open_now(
        catalog, open_now=True, now=saturday_1am, timezone="Asia/Kolkata"
    )
    assert {r.restaurant_id for r in result} == {"R005"}


def test_combined_constraints_indiranagar_veg(catalog: list[Restaurant]) -> None:
    result = apply_hard_constraints(
        catalog,
        city="bengaluru",
        locality="indiranagar",
        is_veg=True,
    )
    assert {r.restaurant_id for r in result} == {"R001", "R004"}


def test_pre_rank_order_is_deterministic(catalog: list[Restaurant]) -> None:
    ranked = pre_rank(catalog)
    ids = [r.restaurant_id for r in ranked]
    assert ids[0] == "R003"
    assert pre_rank(catalog) == ranked


def test_retriever_caps_at_max_candidates(store: RestaurantStore) -> None:
    retriever = Retriever(store)
    intent = QueryIntent(hard_constraints=HardConstraints(city="bengaluru"))
    result = retriever.retrieve_candidates(intent, max_candidates=2)
    assert len(result.candidates) <= 2
    assert result.total_before_limit >= len(result.candidates)


def test_relaxation_order_keeps_locality_last() -> None:
    policy = RelaxationPolicy()

    c1, n1 = policy.relax_once(
        HardConstraints(
            open_now=True,
            locality="indiranagar",
            max_cost_for_two=500,
            min_rating=4.5,
            cuisines=["Chinese", "Thai"],
            city="bengaluru",
        )
    )
    assert c1.open_now is None
    assert "open_now" in n1.lower()
    # Locality must survive while weaker constraints still exist.
    assert c1.locality == "indiranagar"

    c2, n2 = policy.relax_once(c1)
    assert c2.max_cost_for_two == 600
    assert "600" in n2
    assert c2.locality == "indiranagar"

    # Keep relaxing rating and cuisines; locality must remain set the whole time.
    constraints = c2
    last_note: str | None = "seed"
    while last_note is not None:
        assert constraints.locality == "indiranagar"
        next_constraints, last_note = policy.relax_once(constraints)
        if last_note is None:
            break
        if "locality" in last_note.lower():
            # Locality is only relaxed once every other lever is exhausted.
            assert next_constraints.min_rating in (None, 0.0) or next_constraints.min_rating == 0
            assert not next_constraints.cuisines
            assert next_constraints.locality is None
            constraints = next_constraints
            break
        constraints = next_constraints

    assert constraints.locality is None


def test_retriever_prefers_relaxing_rating_over_locality(catalog: list[Restaurant]) -> None:
    """An over-constrained query in a real area should stay in that area."""
    store = RestaurantStore(catalog)
    retriever = Retriever(store)
    # Indiranagar has R001 (4.5) and R004 (3.8); min_rating 5.0 matches none,
    # so the policy must lower the rating rather than abandon the locality.
    intent = QueryIntent(
        hard_constraints=HardConstraints(
            city="bengaluru",
            locality="indiranagar",
            min_rating=5.0,
        )
    )
    result = retriever.retrieve_candidates(intent)
    assert len(result.candidates) > 0
    assert all(r.locality == "indiranagar" for r in result.candidates)
    assert any("min_rating" in note for note in result.relaxed_constraints)
    assert not any("locality" in note.lower() for note in result.relaxed_constraints)


def test_retriever_relaxes_budget_when_no_matches(retriever: Retriever) -> None:
    intent = QueryIntent(
        hard_constraints=HardConstraints(
            city="bengaluru",
            max_cost_for_two=250,
        )
    )
    result = retriever.retrieve_candidates(intent)
    assert len(result.candidates) > 0
    assert any("max_cost_for_two" in note for note in result.relaxed_constraints)
    assert all(r.average_cost_for_two <= 300 for r in result.candidates)


def test_retriever_zero_result_after_all_relaxations(retriever: Retriever) -> None:
    intent = QueryIntent(
        hard_constraints=HardConstraints(
            city="bengaluru",
            locality="indiranagar",
            is_veg=True,
            max_cost_for_two=50,
            min_rating=5.0,
            cuisines=["Martian"],
        )
    )
    result = retriever.retrieve_candidates(intent)
    assert result.candidates == []
    assert len(result.relaxed_constraints) > 0


def test_retriever_indiranagar_veg_query(retriever: Retriever) -> None:
    intent = QueryIntent(
        hard_constraints=HardConstraints(
            city="bengaluru",
            locality="indiranagar",
            is_veg=True,
        )
    )
    result = retriever.retrieve_candidates(intent)
    assert len(result.candidates) == 2
    assert all(r.locality == "indiranagar" for r in result.candidates)
    assert all(r.is_veg in ("Veg", "Both") for r in result.candidates)
    assert result.relaxed_constraints == []


def test_retriever_open_now_relaxation(retriever: Retriever) -> None:
    saturday_3am = datetime(2026, 6, 20, 3, 0, tzinfo=TZ)
    intent = QueryIntent(
        hard_constraints=HardConstraints(
            city="bengaluru",
            locality="indiranagar",
            open_now=True,
        )
    )
    result = retriever.retrieve_candidates(intent, now=saturday_3am)
    assert len(result.candidates) > 0
    assert any("open_now" in n.lower() for n in result.relaxed_constraints)


def test_production_dataset_retrieval() -> None:
    from app.config import settings

    if not settings.data_file.exists():
        pytest.skip("Production dataset not available")

    store = RestaurantStore.from_file(settings.data_file)
    retriever = Retriever(store, timezone=settings.timezone)

    intent = QueryIntent(
        hard_constraints=HardConstraints(
            city="bengaluru",
            locality="indiranagar",
            is_veg=True,
        )
    )
    result = retriever.retrieve_candidates(intent, max_candidates=50)
    assert len(result.candidates) <= 50
    assert all(r.is_veg in ("Veg", "Both") for r in result.candidates)
