"""Constraint relaxation policy when zero candidates match."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from app.data.models import HardConstraints


@dataclass
class RelaxationPolicy:
    """Ordered relaxation steps applied when retrieval returns zero matches.

    Each constraint category is relaxed at most once per retrieval, except
    ``min_rating`` (step down repeatedly) and ``cuisines`` (drop one at a time).

    ``locality`` is intentionally relaxed *last*: when a user picks a specific
    area we keep them inside it as long as possible, loosening the weaker
    preferences (open-now, cost, rating, cuisine) first and only broadening to
    the whole city as a final fallback.
    """

    cost_increase_pct: float = 0.20
    rating_decrease_step: float = 0.5
    _open_now_relaxed: bool = field(default=False, init=False, repr=False)
    _locality_relaxed: bool = field(default=False, init=False, repr=False)
    _max_cost_relaxed: bool = field(default=False, init=False, repr=False)

    def reset(self) -> None:
        """Clear relaxation state for a new retrieval request."""
        self._open_now_relaxed = False
        self._locality_relaxed = False
        self._max_cost_relaxed = False

    def relax_once(
        self, constraints: HardConstraints
    ) -> tuple[HardConstraints, str | None]:
        """Return a relaxed copy of ``constraints`` and a human-readable note.

        Returns ``(constraints, None)`` when no further relaxation is possible.
        """
        relaxed = deepcopy(constraints)

        if not self._open_now_relaxed and relaxed.open_now is True:
            self._open_now_relaxed = True
            relaxed.open_now = None
            return (
                relaxed,
                "Relaxed open_now requirement (showing restaurants regardless of current hours).",
            )

        if not self._max_cost_relaxed and relaxed.max_cost_for_two is not None:
            self._max_cost_relaxed = True
            original = relaxed.max_cost_for_two
            increased = int(original * (1 + self.cost_increase_pct))
            if increased <= original:
                increased = original + 1
            relaxed.max_cost_for_two = increased
            return (
                relaxed,
                f"Raised max_cost_for_two from Rs.{original} to Rs.{increased}.",
            )

        if relaxed.min_rating is not None and relaxed.min_rating > 0:
            original = relaxed.min_rating
            decreased = max(0.0, original - self.rating_decrease_step)
            if decreased < original:
                relaxed.min_rating = decreased if decreased > 0 else None
                target = relaxed.min_rating if relaxed.min_rating is not None else "none"
                return (
                    relaxed,
                    f"Lowered min_rating from {original} to {target}.",
                )

        if relaxed.cuisines:
            dropped = relaxed.cuisines.pop()
            remaining = ", ".join(relaxed.cuisines) if relaxed.cuisines else "any cuisine"
            return (
                relaxed,
                f"Dropped cuisine requirement '{dropped}' (remaining: {remaining}).",
            )

        # Locality is relaxed last so an explicitly chosen area is preserved
        # until every other constraint has already been loosened.
        if not self._locality_relaxed and relaxed.locality:
            self._locality_relaxed = True
            locality = relaxed.locality
            relaxed.locality = None
            return (
                relaxed,
                f"Broadened search from locality '{locality}' to entire city.",
            )

        return constraints, None
