# Project Context — AI-Powered Restaurant Recommendation System (Zomato-Inspired)

> **Document Type:** Development Specification / Problem Statement
> **Intended Use:** Persistent context file for building the application in Cursor
> **Source:** [`PROBLEM STATEMENT.docx`](./PROBLEM%20STATEMENT.docx)
> **Version:** 1.1

This file captures the **entire context** of the project. Treat it as the source
of truth when scaffolding, generating, and refactoring code. Every architectural
and behavioral decision below is intentional — follow it unless explicitly told
otherwise.

---

## 1. Background & Context

Food discovery platforms like Zomato host thousands of restaurants, each with
attributes such as cuisine, location, price range, ratings, dietary options,
ambiance, and operating hours. Users often struggle to find a restaurant that
fits their exact intent because traditional filter-based search is rigid and
cannot understand natural-language requests like:

> "Find me a cozy, budget-friendly vegetarian place for a date night near
> Indiranagar that's open late and good for groups."

This request mixes **structured constraints** (location, price, veg/non-veg,
open hours) with **subjective, fuzzy preferences** (cozy, romantic, good for
groups). Pure keyword search or fixed dropdown filters cannot reliably handle
this.

The goal of this project is to build an AI-powered recommendation service that
combines **STRUCTURED restaurant data** with a **LARGE LANGUAGE MODEL (LLM)** to
interpret natural-language preferences, reason over the data, and return ranked,
explainable restaurant recommendations.

---

## 2. Objective

Build a backend-driven recommendation system (with an optional simple frontend)
that:

- **(a)** Accepts a user's preferences as natural language and/or structured filters.
- **(b)** Retrieves candidate restaurants from a structured dataset/database.
- **(c)** Uses an LLM to interpret intent, rank candidates, and generate human-readable explanations for **WHY** each restaurant was recommended.
- **(d)** Returns a ranked list of recommendations with reasoning.

The key differentiator from a normal search system is the **HYBRID approach**:
deterministic structured filtering for hard constraints **+** LLM reasoning for
soft/subjective preferences and explanation.

---

## 3. Core Problem to Solve

**Given:**

- A dataset of restaurants with structured attributes.
- A user query that may contain **hard constraints** (must-have) and **soft preferences** (nice-to-have, subjective).

**Produce:**

- A ranked list of restaurants that best match the user's intent.
- A natural-language explanation per recommendation.
- Graceful handling when no perfect match exists (suggest closest matches and explain the trade-offs).

> ⚠️ **Critical rule:** The system must **NOT hallucinate restaurants**. All
> recommendations MUST come from the actual dataset. The LLM is used for
> understanding, ranking, and explaining — **NOT** for inventing restaurant data.

---

## 4. Functional Requirements

### 4.1 Input Handling
- Accept a free-text natural-language query.
- Optionally accept structured filters (cuisine, city/locality, max price, veg/non-veg, minimum rating, etc.).
- Parse the natural-language query into structured constraints + soft preferences (intent extraction).

### 4.2 Structured Data Retrieval
- **Load and preprocess** the Zomato dataset from Hugging Face:
  [ManikaSaini/zomato-restaurant-recommendation](https://huggingface.co/datasets/ManikaSaini/zomato-restaurant-recommendation)
  — transform raw rows into the canonical restaurant schema (JSON/CSV) used by the service.
- Filter the restaurant dataset on **HARD constraints** (e.g., location, cuisine, veg-only, price ceiling, open now) using **deterministic logic — NOT the LLM**.
- Return a candidate shortlist (e.g., top 20–50 restaurants) for the LLM to reason over. This keeps cost and latency low and prevents hallucination.

### 4.3 LLM-Based Ranking & Reasoning
- Pass the candidate shortlist + the user's soft preferences to the LLM.
- The LLM ranks candidates against subjective criteria (ambiance, occasion suitability, "cozy", "good for groups", etc.).
- The LLM must justify rankings using **ONLY** the attributes provided in the candidate data.

### 4.4 Output / Recommendations
- Return the top **N** recommendations (configurable, default **N = 5**).
- For each recommendation include:
  - Restaurant name and key attributes
  - A match score or rank
  - A 1–2 sentence explanation of why it fits the user's request
- If no candidate satisfies all hard constraints, relax the least-critical constraint, return closest matches, and clearly state what was relaxed.

### 4.5 Conversational Follow-Up *(Optional / Stretch Goal)*
- Allow the user to refine results conversationally (e.g., "show cheaper options", "something with outdoor seating").
- Maintain conversation context across turns.

---

## 5. Data Model (Structured Restaurant Data)

Use a CSV / JSON dataset or a database table, populated from the **Hugging Face
Zomato dataset** above (preprocessed at build/setup time). Each restaurant record
should include (at minimum) the following fields. A small synthetic fixture set
may be used for unit tests only.

| Field | Type / Notes |
|-------|--------------|
| `restaurant_id` | unique identifier (string/int) |
| `name` | restaurant name (string) |
| `city` | city (string) |
| `locality` | area / neighborhood (string) |
| `cuisines` | list of cuisines (e.g., `["North Indian","Chinese"]`) |
| `average_cost_for_two` | numeric (currency) |
| `price_range` | 1–4 (1 = cheap, 4 = expensive) |
| `rating` | aggregate rating, e.g., 0.0 – 5.0 |
| `votes` | number of ratings/reviews (int) |
| `is_veg` | boolean / `"Veg"` \| `"Non-Veg"` \| `"Both"` |
| `has_table_booking` | boolean |
| `has_online_delivery` | boolean |
| `ambiance_tags` | list (e.g., `["cozy","romantic","family-friendly","rooftop","outdoor seating","good for groups"]`) |
| `opening_hours` | structured hours per day (or open/close time) |
| `latitude`, `longitude` | optional, for distance-based ranking |
| `popular_dishes` | list of strings (optional) |
| `description` | short text blurb (optional, helps LLM reasoning) |

**Extended fields from Zomato preprocessing** (optional but recommended for UI / LLM):

| Field | Type / Notes |
|-------|--------------|
| `address` | full street address (string) |
| `phone` | contact number (string) |
| `url` | Zomato listing URL (string) |
| `rest_type` | list (e.g., `["Casual Dining","Cafe"]`) — feeds `ambiance_tags` |
| `listed_in_type` | listing category from Zomato (string) |
| `listed_in_city` | listing city label from Zomato (string) |

> **NOTE:** The raw Hugging Face dataset does not include `opening_hours` or
> explicit `is_veg`; these are **derived at ingestion** (default hours, heuristic
> veg classification from cuisines/dishes). Richer text fields (`ambiance_tags`,
> `description`, `popular_dishes`) directly improve LLM reasoning quality for
> subjective queries.

---

## 6. System Architecture (Recommended)

A clean layered architecture:

```
  [ Client / UI ]
        |
        v
  [ API Layer ]            <-- REST endpoint(s), request validation
        |
        v
  [ Intent Parser ]        <-- LLM (or rules) extracts hard vs soft constraints
        |
        v
  [ Retrieval Layer ]      <-- Deterministic filtering over structured data
        |                       (DB query / pandas filter) -> candidate shortlist
        v
  [ Ranking & Reasoning ]  <-- LLM ranks shortlist + generates explanations
        |
        v
  [ Response Builder ]     <-- Formats ranked results + explanations as JSON
        |
        v
  [ Client / UI ]
```

**Two LLM touch-points:**

1. **Intent extraction** (natural language → structured intent).
2. **Ranking + explanation** over the retrieved candidate set.

These can be merged into a single LLM call for a simpler MVP, but separating them
gives better control, lower cost, and fewer hallucinations.

---

## 7. Suggested API Contract

**Endpoint:** `POST /recommend`

**Request Body (JSON):**

```json
{
  "query": "cozy budget-friendly vegetarian place for a date in Indiranagar",
  "filters": {
    "city": "Bengaluru",
    "max_cost_for_two": 1500,
    "is_veg": true,
    "min_rating": 4.0
  },
  "top_n": 5
}
```

**Response Body (JSON):**

```json
{
  "query_understood": {
    "hard_constraints": {
      "city": "Bengaluru",
      "locality": "Indiranagar",
      "is_veg": true,
      "max_cost_for_two": 1500
    },
    "soft_preferences": ["cozy", "romantic", "date-night"]
  },
  "recommendations": [
    {
      "restaurant_id": "R123",
      "name": "...",
      "rating": 4.5,
      "average_cost_for_two": 1200,
      "match_score": 0.92,
      "reason": "Cozy, dimly-lit ambiance ideal for a date, fully vegetarian, and within your budget in Indiranagar."
    }
  ],
  "notes": "No restaurant matched all constraints under Rs.1000, so the budget was relaxed to Rs.1500 to surface these matches."
}
```

---

## 8. Technical Requirements / Suggested Stack

*(These are suggestions; choose what fits the developer's comfort.)*

| Concern | Recommendation |
|---------|----------------|
| Language | Python (recommended) or Node.js |
| Backend | FastAPI / Flask (Python) or Express (Node) |
| Data source | Hugging Face Zomato dataset → preprocessed JSON via `app.data.ingest` |
| Data store | CSV/JSON + pandas for MVP; PostgreSQL/SQLite for scale |
| LLM provider | Any LLM API (configurable via environment variable) |
| Vector search | **OPTIONAL** — embeddings + similarity search over descriptions/ambiance for better soft-matching |
| Frontend | **OPTIONAL** — simple React or HTML page with a search box and result cards |
| Config | API keys via `.env` (never hard-coded) |

**LLM Usage Principles:**

- Always ground the LLM with the retrieved candidate data in the prompt.
- Instruct the LLM to recommend **ONLY** from the provided candidates.
- Request structured (JSON) output from the LLM for reliable parsing.
- Handle LLM errors / malformed output gracefully (retry or fallback to rating-based ranking).

---

## 9. Non-Functional Requirements

| Attribute | Requirement |
|-----------|-------------|
| Accuracy | Recommendations must respect all hard constraints. |
| No Hallucination | Never return restaurants not present in the dataset. |
| Explainability | Every recommendation includes a clear reason. |
| Latency | Target < 3–5 seconds per request for the MVP. |
| Cost Efficiency | Limit LLM input by pre-filtering to a small candidate set. |
| Robustness | Handle empty results, vague queries, and typos gracefully. |
| Security | Secrets in environment variables; validate all input. |
| Maintainability | Modular code (parser, retriever, ranker, API separated). |

---

## 10. Edge Cases to Handle

- Query with no location → ask for it or default to a configured city.
- No restaurant satisfies all hard constraints → relax + explain.
- Vague query ("somewhere nice to eat") → use defaults / popular + rating.
- Conflicting constraints (e.g., "cheapest fine-dining") → surface trade-off.
- Empty dataset / filtered to zero candidates → clear "no results" message.
- LLM returns invalid JSON → retry once, then fall back to deterministic ranking by rating and votes.

---

## 11. Evaluation Criteria (How Success Is Measured)

- **Correctness** — Hard constraints always honored.
- **Relevance** — Soft preferences meaningfully influence ranking.
- **Explainability** — Reasons are accurate and grounded in real attributes.
- **Hybrid Design** — Clear separation between deterministic filtering and LLM reasoning (not "everything dumped into the LLM").
- **Code Quality** — Modular, readable, documented, configurable.
- **UX** — Output is clean, ranked, and easy to consume (JSON/UI).

---

## 12. Deliverables

1. A working backend service exposing the `/recommend` endpoint.
2. A preprocessed restaurant dataset (JSON/CSV) sourced from the Hugging Face Zomato dataset.
3. Hybrid pipeline: structured retrieval + LLM ranking/explanation.
4. A README with setup, environment variables, and run instructions.
5. Example requests and responses (sample queries demonstrating behavior).
6. *(Optional)* A minimal frontend search interface.
7. *(Optional)* Conversational refinement and/or embedding-based soft matching.

---

## 13. Stretch Goals (Bonus)

- Multi-turn conversational refinement with memory.
- Embedding-based semantic search over descriptions and reviews.
- Personalization using a user's past preferences / history.
- "Open now" logic using real-time clock vs `opening_hours`.
- Distance-based ranking using `latitude`/`longitude` + user location.
- Caching of LLM responses for repeated/similar queries.

---

## 14. Example User Queries (For Testing)

- "Cheap vegetarian street food near MG Road, open right now."
- "Romantic rooftop restaurant for an anniversary dinner, budget no concern."
- "Family-friendly North Indian place that takes table bookings and seats large groups."
- "Best-rated Chinese delivery under Rs.800 for two."
- "A quiet cafe good for working with a laptop and good coffee."

---

*End of context.*
