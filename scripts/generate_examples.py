"""Run the golden queries through the live pipeline and save example responses.

Writes examples/sample_responses.json. Requires GROQ_API_KEY in .env.

Usage (from project root):
    python scripts/generate_examples.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.api.schemas import RecommendRequest  # noqa: E402
from app.config import settings  # noqa: E402
from app.data.loader import RestaurantStore  # noqa: E402
from app.pipeline.orchestrator import Orchestrator  # noqa: E402

QUERIES = [
    {"query": "Cheap vegetarian street food near MG Road, open right now.", "top_n": 5},
    {"query": "Romantic rooftop restaurant for an anniversary dinner, budget no concern.", "top_n": 5},
    {"query": "Family-friendly North Indian place that takes table bookings and seats large groups.", "top_n": 5},
    {"query": "Best-rated Chinese delivery under Rs.800 for two.", "top_n": 5},
    {"query": "A quiet cafe good for working with a laptop and good coffee.", "top_n": 5},
    {
        "query": "cozy vegetarian place for a date in Indiranagar",
        "filters": {"min_rating": 4.0, "max_cost_for_two": 1500},
        "top_n": 3,
    },
]

OUTPUT = Path(__file__).resolve().parent.parent / "examples" / "sample_responses.json"


async def main() -> None:
    store = RestaurantStore.from_file(settings.data_file)
    orchestrator = Orchestrator(store)
    print(f"Loaded {store.count():,} restaurants; groq_configured={settings.groq_configured}")

    examples = []
    for payload in QUERIES:
        print(f"\n> {payload['query']}")
        response = await orchestrator.recommend(RecommendRequest(**payload))
        body = response.model_dump()
        examples.append({"request": payload, "response": body})
        print(f"  ranker={body['meta']['ranker']} "
              f"candidates={body['meta']['candidate_count']} "
              f"latency_ms={body['meta']['latency_ms']} "
              f"results={len(body['recommendations'])}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(examples, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(examples)} examples to {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
