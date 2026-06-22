"""Domain exceptions mapped to the documented HTTP error contract (§9.1)."""

from __future__ import annotations


class AmbiguousQueryError(Exception):
    """Raised when a query cannot be processed (e.g., no location and no default city).

    Mapped to HTTP 422 ``ambiguous_query``.
    """

    def __init__(self, message: str = "Please specify a city or locality.") -> None:
        self.message = message
        super().__init__(message)


class ServiceUnavailableError(Exception):
    """Raised when the service cannot serve requests (e.g., dataset not loaded).

    Mapped to HTTP 503 ``service_unavailable``.
    """

    def __init__(self, message: str = "Service temporarily unavailable.") -> None:
        self.message = message
        super().__init__(message)
