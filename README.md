# AI-Powered Restaurant Recommendation System

A **hybrid** restaurant recommendation API that combines deterministic retrieval
with LLM-powered ranking and natural-language explanations. Users ask in plain
English (e.g. *"Cheap vegetarian street food near MG Road, open right now"*) and
get back a short list of **grounded, ranked, explainable** recommendations drawn
from a real Zomato (Bengaluru) dataset.

> **Hybrid design, in one sentence:** hard constraints are enforced by
> *deterministic code* (never the LLM), and only the already-valid candidates are
> handed to the LLM for *soft-preference ranking and reasoning* — so the model can
> never invent a restaurant or violate a constraint.

---

## Architecture at a glance

```
                ┌─────────────┐   free text + optional structured filters
   user query ─▶│  Intent     │  (Groq llama-3.1-8b, rule-based fallback)
                │  Parser     │
                └──────┬──────┘
                       │ QueryIntent (hard_constraints + soft_preferences)
                       ▼
                ┌─────────────┐   exact filtering + ordered relaxation
                │ Retrieval   │  (pure Python over the in-memory catalog)
                │ Engine      │
                └──────┬──────┘
                       │ bounded, pre-ranked candidate shortlist
                       ▼
                ┌─────────────┐   rank by soft prefs + write reasons
                │  Ranker     │  (Groq llama-3.3-70b, deterministic fallback)
                └──────┬──────┘  + no-hallucination ID validation & backfill
                       │
                       ▼
              grounded JSON recommendations
```

Detailed design lives in [`docs/architecture.md`](docs/architecture.md);
the phase-by-phase build log is in
[`docs/implementation-plan.md`](docs/implementation-plan.md); corner cases and
decisions are catalogued in [`docs/edge-case.md`](docs/edge-case.md).

---

## Prerequisites

- **Python 3.11+**
- A **Groq API key** — free at <https://console.groq.com>
  (the system still runs without one, falling back to deterministic ranking)

---

## Setup (under 15 minutes)

```bash
# 1. Clone and enter the project
cd "AI-Powered Restaurant Recommendation System"

# 2. Create and activate a virtual environment
python -m venv .venv
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env          # Windows: copy .env.example .env
# then edit .env and set GROQ_API_KEY=...
```

### Data

A preprocessed dataset ships at `data/restaurants.json` (~12,000 Bengaluru
restaurants). To regenerate it from the source Hugging Face Zomato dataset:

```bash
cd src
python -m app.data.ingest
```

---

## Run the API

```bash
uvicorn app.main:app --reload --app-dir src
```

The server starts on <http://127.0.0.1:8000>. Open that URL to use the **web UI**
(a search-driven frontend served from `frontend/`); it redirects to `/ui/`.
Interactive API docs (Swagger UI) are at <http://127.0.0.1:8000/docs>.

### Web UI (Phase 8)

The frontend is a static HTML + vanilla JS app (Tailwind via CDN) implementing the
"Culinary Intelligence" design. It offers a natural-language search box, dropdown
filters (city, locality, cuisines), live AI-ranked result cards with match scores
and explanations, and a restaurant detail modal. It calls the backend over the
same origin, so no extra setup is needed.

Quick health check:

```bash
curl http://127.0.0.1:8000/health
```

---

## Endpoints

| Method | Path                      | Description                                            |
| ------ | ------------------------- | ----------------------------------------------------- |
| `POST` | `/recommend`              | Natural-language + structured recommendation request. |
| `POST` | `/recommend/chat`         | Conversational refinement turn (carries `session_id`).|
| `GET`  | `/meta`                   | Filter options (cities, localities, cuisines).        |
| `GET`  | `/health`                 | Liveness/readiness, dataset & Groq config status.     |
| `GET`  | `/restaurants/{id}`       | Fetch a single restaurant by ID.                      |

### `POST /recommend` request body

```json
{
  "query": "cozy vegetarian place for a date in Indiranagar",
  "filters": {
    "min_rating": 4.0,
    "max_cost_for_two": 1500
  },
  "top_n": 3
}
```

- `query` *(string, optional)* — free-text request (max 2000 chars).
- `filters` *(object, optional)* — explicit structured constraints that
  **override** anything parsed from the query.
- `top_n` *(int, 1–20, default 5)* — number of recommendations to return.

At least one of `query` or `filters` is required.

---

## Example requests & responses

A live-generated set of 6 request/response pairs (including all five golden
queries) is saved in [`examples/sample_responses.json`](examples/sample_responses.json)
with a walkthrough in [`examples/README.md`](examples/README.md).

### Example: cheap veg street food, open now

```bash
curl -X POST http://127.0.0.1:8000/recommend \
  -H "Content-Type: application/json" \
  -d '{"query": "Cheap vegetarian street food near MG Road, open right now.", "top_n": 5}'
```

Response (abridged):

```json
{
  "query_understood": {
    "hard_constraints": {
      "city": "bengaluru",
      "locality": "mg road",
      "is_veg": true,
      "open_now": true,
      "max_price_range": 1
    },
    "soft_preferences": []
  },
  "recommendations": [
    {
      "restaurant_id": "R2958",
      "name": "KC Das",
      "locality": "mg road",
      "cuisines": ["Mithai", "Street Food"],
      "rating": 3.9,
      "average_cost_for_two": 200,
      "is_veg": "Both",
      "match_score": 0.9,
      "rank": 1,
      "reason": "KC Das serves Street Food with a high rating and price range of 1, a good fit for cheap vegetarian street food near MG Road."
    }
  ],
  "meta": {
    "candidate_count": 17,
    "latency_ms": 2031,
    "ranker": "groq",
    "groq_model": "llama-3.3-70b-versatile"
  }
}
```

### Other golden queries

```bash
# Romantic rooftop, budget no concern
curl -X POST http://127.0.0.1:8000/recommend -H "Content-Type: application/json" \
  -d '{"query": "Romantic rooftop restaurant for an anniversary dinner, budget no concern."}'

# Family-friendly North Indian with table booking for large groups
curl -X POST http://127.0.0.1:8000/recommend -H "Content-Type: application/json" \
  -d '{"query": "Family-friendly North Indian place that takes table bookings and seats large groups."}'

# Best-rated Chinese delivery under Rs.800 for two
curl -X POST http://127.0.0.1:8000/recommend -H "Content-Type: application/json" \
  -d '{"query": "Best-rated Chinese delivery under Rs.800 for two."}'

# Quiet cafe good for laptop work
curl -X POST http://127.0.0.1:8000/recommend -H "Content-Type: application/json" \
  -d '{"query": "A quiet cafe good for working with a laptop and good coffee."}'
```

---

## Advanced features (Phase 9)

These are layered on additively and configurable via `.env`:

- **Conversational refinement** — `POST /recommend/chat` returns a `session_id`;
  send it back on later turns to carry context and avoid repeating restaurants.
  Understands refinements like *"show cheaper options"* and *"outdoor seating"*.
- **Semantic pre-rank** — a dependency-free TF-IDF + cosine index reorders the
  candidate shortlist by similarity to your query before the LLM ranks it
  (`SEMANTIC_WEIGHT`). No embedding API or model download required.
- **Response caching** — repeated identical requests are served from an in-memory
  TTL + LRU cache (`meta.cached: true`).
- **Distance-aware** — pass `user_lat`/`user_lng` (+ optional `max_distance_km`)
  to get `distance_km` per result (inert until the dataset includes coordinates).
- **Personalization** — pass a `user_id` to let the service learn cuisine/ambiance
  affinity across requests and blend it into ranking (`meta.personalized: true`).

```bash
# Conversational example
curl -X POST http://127.0.0.1:8000/recommend/chat -H "Content-Type: application/json" \
  -d '{"query":"rooftop dinner in indiranagar","top_n":3}'
# → returns "session_id": "abc123…"; reuse it:
curl -X POST http://127.0.0.1:8000/recommend/chat -H "Content-Type: application/json" \
  -d '{"session_id":"abc123…","query":"show cheaper options","top_n":3}'
```

## Configuration

All settings load from `.env` (see [`.env.example`](.env.example)). Key options:

| Variable               | Default                     | Purpose                                             |
| ---------------------- | --------------------------- | --------------------------------------------------- |
| `GROQ_API_KEY`         | *(empty)*                   | Groq key; empty ⇒ deterministic fallback ranking.   |
| `GROQ_MODEL_INTENT`    | `llama-3.1-8b-instant`      | Model used for intent parsing.                      |
| `GROQ_MODEL_RANK`      | `llama-3.3-70b-versatile`   | Model used for ranking/reasoning.                   |
| `GROQ_TIMEOUT_SECONDS` | `30`                        | Per-request LLM timeout.                            |
| `DATA_PATH`            | `data/restaurants.json`     | Path to the preprocessed dataset.                  |
| `DEFAULT_CITY`         | `Bengaluru`                 | City used when the query omits a location.          |
| `MAX_CANDIDATES`       | `50`                        | Cap after deterministic retrieval.                 |
| `LLM_RANK_CANDIDATES`  | `20`                        | Shortlist size sent to the LLM (stays under TPM).   |
| `DEFAULT_TOP_N`        | `5`                         | Default number of recommendations.                 |
| `TIMEZONE`             | `Asia/Kolkata`              | Timezone for `open_now` logic.                      |
| `CACHE_ENABLED`        | `true`                      | Enable the TTL + LRU response cache.               |
| `CACHE_TTL_SECONDS`    | `300`                       | Cache entry lifetime.                              |
| `SEMANTIC_ENABLED`     | `true`                      | Enable the TF-IDF semantic pre-rank.              |
| `SEMANTIC_WEIGHT`      | `0.35`                      | Semantic vs rating blend (0–1) for reordering.    |
| `SESSION_TTL_SECONDS`  | `1800`                      | Conversation session lifetime.                    |
| `PERSONALIZATION_ENABLED` | `true`                   | Enable per-`user_id` preference learning.         |

---

## Running tests

```bash
pytest                      # all unit + API tests (LLM calls are mocked)
pytest -v                   # verbose
```

To additionally exercise the **live Groq** pipeline:

```bash
# Windows PowerShell
$env:RUN_LIVE_LLM_TESTS="1"; pytest tests/test_golden_queries.py
# macOS / Linux
RUN_LIVE_LLM_TESTS=1 pytest tests/test_golden_queries.py
```

Regenerate the live example responses:

```bash
python scripts/generate_examples.py
```

---

## Project structure

```
.
├── data/restaurants.json        # preprocessed Zomato catalog
├── docs/                        # architecture, plan, edge cases
├── examples/                    # sample requests/responses
├── scripts/                     # predict.py, smoke_api.py, generate_examples.py
├── src/app/
│   ├── api/                     # FastAPI routes, schemas, error types
│   ├── data/                    # models, loader, ingest pipeline
│   ├── intent/                  # LLM intent parser + rule-based fallback
│   ├── retrieval/               # filters, relaxation, retriever
│   ├── ranking/                 # LLM ranker + deterministic fallback
│   ├── llm/                     # Groq client + LLM protocol
│   ├── pipeline/                # orchestrator + response builder
│   ├── utils/                   # hours, validation helpers
│   ├── config.py                # settings
│   └── main.py                  # app entrypoint
└── tests/                       # unit, API, hardening, golden-query tests
```

---

## How the hybrid guarantees correctness

- **Hard constraints are code, not prompts.** Location, price, cuisine, veg,
  delivery/booking and *open now* are filtered deterministically before the LLM
  ever runs.
- **No hallucination.** The ranker may only return IDs from the candidate set;
  invalid IDs are dropped and the list is backfilled from the deterministic
  pre-ranking.
- **Always answers.** If Groq is unavailable, rate-limited, or times out, the
  system falls back to rule-based intent parsing and deterministic ranking, and
  the response `meta.ranker` reports which path was used.
- **Graceful relaxation.** When strict filters yield nothing, constraints are
  relaxed in a defined order and the loosened filters are reported in `notes`.

---

## Optional: Docker

```bash
docker build -t restaurant-recommender .
docker run --rm -p 8000:8000 --env-file .env restaurant-recommender
```
