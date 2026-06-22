"""Ad-hoc prediction runner: intent → retrieval → LLM ranking.

Usage (from project root, venv active):
    python -m scripts.predict --locality bellandur --min-rating 4.2 --max-cost 1500 --top-n 5

Requires GROQ_API_KEY in .env (or environment) for LLM ranking; otherwise the
deterministic fallback ranker is used.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Windows consoles often default to cp1252, which cannot encode ₹/unicode.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from app.config import settings  # noqa: E402
from app.data.loader import RestaurantStore  # noqa: E402
from app.data.models import HardConstraints, QueryIntent  # noqa: E402
from app.intent.parser import IntentParser  # noqa: E402
from app.ranking.ranker import Ranker  # noqa: E402
from app.retrieval.retriever import Retriever  # noqa: E402


async def run(args: argparse.Namespace) -> None:
    store = RestaurantStore.from_file(settings.data_file)
    print(f"Loaded {store.count():,} restaurants from {settings.data_file.name}")
    print(f"Groq configured: {settings.groq_configured}")

    # Build intent. When a free-text query is given, parse it; otherwise use filters.
    if args.query:
        parser = IntentParser()
        intent = await parser.parse(
            args.query,
            filters={
                "city": args.city,
                "locality": args.locality,
                "min_rating": args.min_rating,
                "max_cost_for_two": args.max_cost,
            },
        )
    else:
        intent = QueryIntent(
            original_query=(
                f"Top restaurants in {args.locality} with rating at least "
                f"{args.min_rating} and budget under Rs.{args.max_cost} for two."
            ),
            hard_constraints=HardConstraints(
                city=args.city.lower() if args.city else None,
                locality=args.locality.lower() if args.locality else None,
                min_rating=args.min_rating,
                max_cost_for_two=args.max_cost,
            ),
            soft_preferences=[],
        )

    retriever = Retriever(store, timezone=settings.timezone)
    retrieval = retriever.retrieve_candidates(intent, max_candidates=settings.max_candidates)

    print("\n--- Retrieval ---")
    print(f"Candidates: {len(retrieval.candidates)} (from {retrieval.total_before_limit} matches)")
    if retrieval.relaxed_constraints:
        print("Relaxations applied:")
        for note in retrieval.relaxed_constraints:
            print(f"  - {note}")

    if not retrieval.candidates:
        print("\nNo restaurants matched even after relaxation.")
        return

    ranker = Ranker()
    result = await ranker.rank(retrieval.candidates, intent, top_n=args.top_n)

    print(f"\n--- Top {args.top_n} Recommendations (ranker: {result.ranker}) ---")
    for rec in result.recommendations:
        score = f"{rec.match_score:.2f}" if rec.match_score is not None else "n/a"
        print(f"\n#{rec.rank}  {rec.name}  [{rec.restaurant_id}]")
        print(f"    Locality : {rec.locality.title()}")
        print(f"    Cuisines : {', '.join(rec.cuisines)}")
        print(f"    Rating   : {rec.rating}/5 ({rec.votes} votes)")
        print(f"    Cost(2)  : Rs.{rec.average_cost_for_two}   Veg: {rec.is_veg}")
        print(f"    Score    : {score}")
        print(f"    Why      : {rec.reason}")


def main() -> None:
    p = argparse.ArgumentParser(description="Predict top restaurants")
    p.add_argument("--query", default="", help="Optional free-text query")
    p.add_argument("--city", default="bengaluru")
    p.add_argument("--locality", default=None)
    p.add_argument("--min-rating", type=float, default=None, dest="min_rating")
    p.add_argument("--max-cost", type=int, default=None, dest="max_cost")
    p.add_argument("--top-n", type=int, default=5, dest="top_n")
    args = p.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
