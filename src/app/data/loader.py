"""Data loader — loads preprocessed restaurant JSON into memory at startup.

Provides a simple in-memory store with ``get_all()``, ``get_by_id()``,
and ``count()`` accessors.  The store validates each record against the
``Restaurant`` schema during load and normalises city/locality to
lowercase for matching.

Usage (inside FastAPI lifespan or tests):
    from app.data.loader import RestaurantStore

    store = RestaurantStore.from_file(settings.data_file)
    store.get_all()       # → list[Restaurant]
    store.get_by_id("R0001")  # → Restaurant | None
    store.count()         # → int
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from app.data.models import Restaurant

logger = logging.getLogger(__name__)


class RestaurantStore:
    """In-memory restaurant catalogue loaded from a JSON file."""

    def __init__(self, restaurants: list[Restaurant]) -> None:
        self._restaurants = restaurants
        self._by_id: dict[str, Restaurant] = {
            r.restaurant_id: r for r in restaurants
        }

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, path: Path | str) -> "RestaurantStore":
        """Load restaurants from a JSON or CSV file and validate each record.

        Parameters
        ----------
        path:
            Path to ``restaurants.json`` or ``restaurants.csv``.

        Returns
        -------
        A populated ``RestaurantStore`` instance.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        ValueError
            If the file extension is not supported.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Restaurant data file not found: {path}")

        logger.info("Loading restaurant data from %s", path)
        suffix = path.suffix.lower()
        if suffix == ".json":
            raw_records = cls._load_json(path)
        elif suffix == ".csv":
            raw_records = cls._load_csv(path)
        else:
            raise ValueError(
                f"Unsupported data file format '{suffix}'. Use .json or .csv."
            )

        restaurants, errors = cls._parse_records(raw_records)
        logger.info(
            "Loaded %d restaurants (%d skipped due to validation errors)",
            len(restaurants),
            errors,
        )
        return cls(restaurants)

    @staticmethod
    def _load_json(path: Path) -> list[dict[str, Any]]:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"Expected a JSON array in {path}")
        return data

    @staticmethod
    def _load_csv(path: Path) -> list[dict[str, Any]]:
        df = pd.read_csv(path)
        records: list[dict[str, Any]] = df.where(pd.notna(df), None).to_dict(
            orient="records"
        )
        for record in records:
            for key, value in list(record.items()):
                if value is None:
                    record.pop(key)
                    continue
                if isinstance(value, str) and value.startswith(("[", "{")):
                    try:
                        record[key] = json.loads(value)
                    except json.JSONDecodeError:
                        pass
        return records

    @classmethod
    def _parse_records(
        cls, raw_records: list[dict[str, Any]]
    ) -> tuple[list[Restaurant], int]:
        restaurants: list[Restaurant] = []
        errors = 0
        for idx, record in enumerate(raw_records):
            try:
                normalised = cls._normalise_record(record)
                restaurants.append(Restaurant(**normalised))
            except Exception as exc:
                errors += 1
                if errors <= 5:
                    logger.warning("Skipping record %d: %s", idx, exc)
        return restaurants, errors

    @staticmethod
    def _normalise_record(record: dict[str, Any]) -> dict[str, Any]:
        """Normalise city/locality and coerce list-like fields for validation."""
        data = dict(record)
        if "city" in data and isinstance(data["city"], str):
            data["city"] = data["city"].strip().lower()
        if "locality" in data and isinstance(data["locality"], str):
            data["locality"] = data["locality"].strip().lower()
        return data

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_all(self) -> list[Restaurant]:
        """Return all loaded restaurants."""
        return list(self._restaurants)

    def get_by_id(self, restaurant_id: str) -> Restaurant | None:
        """Return a restaurant by its ID, or None if not found."""
        return self._by_id.get(restaurant_id)

    def count(self) -> int:
        """Return the total number of loaded restaurants."""
        return len(self._restaurants)

    def get_cities(self) -> list[str]:
        """Return sorted list of unique cities."""
        return sorted({r.city for r in self._restaurants if r.city})

    def get_localities(self) -> list[str]:
        """Return sorted list of unique localities."""
        return sorted({r.locality for r in self._restaurants if r.locality})

    def get_cuisines(self) -> list[str]:
        """Return sorted list of unique cuisines across all restaurants."""
        cuisines: set[str] = set()
        for r in self._restaurants:
            cuisines.update(r.cuisines)
        return sorted(cuisines)
