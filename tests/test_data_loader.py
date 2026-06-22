"""Phase 1 — data loader and model tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings
from app.data.loader import RestaurantStore
from app.data.models import HardConstraints, QueryIntent, Restaurant

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE_JSON = FIXTURES / "sample_restaurants.json"


@pytest.fixture
def sample_store() -> RestaurantStore:
    return RestaurantStore.from_file(SAMPLE_JSON)


def test_restaurant_model_validates_sample_record() -> None:
    raw = json.loads(SAMPLE_JSON.read_text(encoding="utf-8"))[0]
    restaurant = Restaurant(**raw)
    assert restaurant.restaurant_id == "R001"
    assert restaurant.name == "Green Garden Cafe"
    assert restaurant.is_veg == "Veg"


def test_query_intent_schemas_exist() -> None:
    intent = QueryIntent(
        original_query="cozy veg place in Indiranagar",
        hard_constraints=HardConstraints(city="bengaluru", is_veg=True),
        soft_preferences=["cozy", "romantic"],
    )
    assert intent.hard_constraints.city == "bengaluru"
    assert intent.soft_preferences == ["cozy", "romantic"]


def test_store_loads_json_and_normalises_location(sample_store: RestaurantStore) -> None:
    assert sample_store.count() == 3
    restaurant = sample_store.get_by_id("R001")
    assert restaurant is not None
    assert restaurant.city == "bengaluru"
    assert restaurant.locality == "indiranagar"


def test_get_by_id_returns_none_for_invalid_id(sample_store: RestaurantStore) -> None:
    assert sample_store.get_by_id("INVALID") is None
    assert sample_store.get_by_id("") is None


def test_get_all_returns_copy_of_catalog(sample_store: RestaurantStore) -> None:
    all_restaurants = sample_store.get_all()
    assert len(all_restaurants) == 3
    ids = {r.restaurant_id for r in all_restaurants}
    assert ids == {"R001", "R002", "R003"}


def test_store_loads_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "restaurants.csv"
    csv_path.write_text(
        "restaurant_id,name,city,locality,cuisines,average_cost_for_two,"
        "price_range,rating,votes,is_veg,has_table_booking,has_online_delivery,"
        "ambiance_tags,popular_dishes,description\n"
        'R010,Test Cafe,Bengaluru,Indiranagar,"[""Cafe""]",400,1,4.0,10,'
        'Veg,true,true,"[""cozy""]","[""Coffee""]",A test cafe.\n',
        encoding="utf-8",
    )
    store = RestaurantStore.from_file(csv_path)
    assert store.count() == 1
    restaurant = store.get_by_id("R010")
    assert restaurant is not None
    assert restaurant.city == "bengaluru"
    assert restaurant.cuisines == ["Cafe"]


def test_production_dataset_loads_and_validates() -> None:
    if not settings.data_file.exists():
        pytest.skip("Production dataset not generated yet")
    store = RestaurantStore.from_file(settings.data_file)
    assert store.count() > 0
    assert store.get_by_id("R0001") is not None
    localities = store.get_localities()
    cuisines = store.get_cuisines()
    assert len(localities) > 1
    assert len(cuisines) > 1
