"""Per-key in-memory sliding-window rate limiting."""

from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    """Allow a fixed number of requests per key in a rolling time window."""

    def __init__(self, limit: int = 30, window_seconds: float = 60.0) -> None:
        if limit < 1:
            raise ValueError("limit must be at least one request")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key_id: str, now: float | None = None) -> bool:
        """Record a request and return whether it is within the limit."""
        current_time = time.monotonic() if now is None else now
        window_start = current_time - self.window_seconds
        with self._lock:
            requests = self._requests.setdefault(key_id, deque())
            while requests and requests[0] <= window_start:
                requests.popleft()
            if len(requests) >= self.limit:
                return False
            requests.append(current_time)
            return True
