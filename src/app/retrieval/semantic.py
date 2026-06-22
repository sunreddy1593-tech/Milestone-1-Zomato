"""Dependency-free semantic search index (Phase 9.4).

A lightweight TF-IDF + cosine-similarity index over each restaurant's textual
signals (cuisines, ambiance tags, description, dishes, locality). This is a
self-contained stand-in for an embedding model + FAISS: it needs no external
API key, no model download, and no extra dependencies, while still giving the
pipeline a "soft" semantic pre-rank over the deterministic candidate set.

Used as a *pre-rank boost*: it reorders the already hard-filtered candidate
shortlist by similarity to the user's free-text query before the LLM ranker
sees it. It never changes which hard constraints are enforced.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from app.data.models import Restaurant

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    """
    a an and the for with to of in on at is are be good great place places
    near me my we us you your restaurant restaurants food eat eating want
    looking like nice some something really very just that this these those
    open now today tonight please find show get
    """.split()
)


def _tokenize(text: str) -> list[str]:
    return [
        t
        for t in _TOKEN_RE.findall((text or "").lower())
        if len(t) > 2 and t not in _STOPWORDS
    ]


def _restaurant_text(r: Restaurant) -> str:
    parts = [
        r.name,
        " ".join(r.cuisines),
        " ".join(r.ambiance_tags),
        " ".join(r.rest_type),
        r.locality,
        " ".join(r.popular_dishes[:10]),
        r.description,
    ]
    return " ".join(p for p in parts if p)


class SemanticIndex:
    """TF-IDF vectors with cosine similarity scoring."""

    def __init__(self, restaurants: list[Restaurant]) -> None:
        self._idf: dict[str, float] = {}
        self._vectors: dict[str, dict[str, float]] = {}
        self._build(restaurants)

    def _build(self, restaurants: list[Restaurant]) -> None:
        doc_tokens: dict[str, list[str]] = {}
        df: Counter[str] = Counter()
        for r in restaurants:
            tokens = _tokenize(_restaurant_text(r))
            doc_tokens[r.restaurant_id] = tokens
            df.update(set(tokens))

        n_docs = max(1, len(restaurants))
        self._idf = {
            term: math.log((n_docs + 1) / (count + 1)) + 1.0
            for term, count in df.items()
        }

        for rid, tokens in doc_tokens.items():
            self._vectors[rid] = self._vectorize(tokens)

    def _vectorize(self, tokens: list[str]) -> dict[str, float]:
        if not tokens:
            return {}
        tf = Counter(tokens)
        total = len(tokens)
        vec = {
            term: (count / total) * self._idf.get(term, 0.0)
            for term, count in tf.items()
            if self._idf.get(term, 0.0) > 0.0
        }
        norm = math.sqrt(sum(w * w for w in vec.values()))
        if norm == 0:
            return {}
        return {term: w / norm for term, w in vec.items()}

    def _query_vector(self, query: str) -> dict[str, float]:
        return self._vectorize(_tokenize(query))

    def score(self, query: str, restaurant_ids: list[str]) -> dict[str, float]:
        """Cosine similarity (0..1) of ``query`` to each given restaurant.

        Missing restaurants or an empty query yield 0.0 for all.
        """
        qvec = self._query_vector(query)
        if not qvec:
            return {rid: 0.0 for rid in restaurant_ids}
        scores: dict[str, float] = {}
        for rid in restaurant_ids:
            dvec = self._vectors.get(rid)
            if not dvec:
                scores[rid] = 0.0
                continue
            # Both vectors are L2-normalised → dot product is cosine similarity.
            small, large = (qvec, dvec) if len(qvec) <= len(dvec) else (dvec, qvec)
            scores[rid] = sum(w * large.get(term, 0.0) for term, w in small.items())
        return scores

    def __len__(self) -> int:
        return len(self._vectors)
