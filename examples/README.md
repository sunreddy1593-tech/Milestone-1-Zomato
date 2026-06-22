# Example requests & responses

[`sample_responses.json`](sample_responses.json) contains **live** request/response
pairs captured from the running pipeline (Groq ranking enabled). It includes all
five golden queries from the problem statement plus one structured-filter example.

Regenerate it any time with:

```bash
python scripts/generate_examples.py
```

Each entry has the shape:

```json
{
  "request":  { "query": "...", "filters": { ... }, "top_n": 5 },
  "response": { "query_understood": { ... }, "recommendations": [ ... ], "notes": null, "meta": { ... } }
}
```

## The six examples

| # | Request                                                                                  | Demonstrates                                                  |
| - | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| 1 | Cheap vegetarian street food near MG Road, open right now.                                | Hard constraints: veg + locality + price + `open_now`.       |
| 2 | Romantic rooftop restaurant for an anniversary dinner, budget no concern.                | Pure soft preferences ranked by the LLM.                     |
| 3 | Family-friendly North Indian place that takes table bookings and seats large groups.     | Cuisine + `has_table_booking` + group/ambiance prefs.        |
| 4 | Best-rated Chinese delivery under Rs.800 for two.                                         | Cuisine + `has_online_delivery` + cost + min-rating.         |
| 5 | A quiet cafe good for working with a laptop and good coffee.                              | Ambiance soft preferences over a broad candidate set.        |
| 6 | cozy vegetarian place for a date in Indiranagar (+ filters `min_rating`, `max_cost`)     | Structured filters overriding/augmenting parsed intent.      |

## Trying them against a running server

Start the API (`uvicorn app.main:app --reload --app-dir src`), then:

```bash
curl -X POST http://127.0.0.1:8000/recommend \
  -H "Content-Type: application/json" \
  -d '{"query": "Best-rated Chinese delivery under Rs.800 for two."}'
```

## Verifying correctness (manual eval checklist)

For any response, confirm:

- **Grounded:** every `restaurant_id` exists (try `GET /restaurants/{id}`).
- **Constraints respected:** veg/delivery/booking/price match the request.
- **Explainable:** each `reason` cites attributes the restaurant actually has.
- **Hybrid:** `meta.ranker` is `groq` (LLM ranked) or `fallback` (deterministic),
  and `meta.candidate_count` reflects deterministic retrieval, not the LLM.
