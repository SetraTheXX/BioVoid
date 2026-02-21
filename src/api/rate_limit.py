"""Simple in-memory fixed-window rate limiter."""

from __future__ import annotations

import threading
import time
from collections import deque


class InMemoryRateLimiter:
    """Thread-safe fixed-window in-memory rate limiter."""

    def __init__(self, max_requests: int = 120, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = {}

    def allow(self, client_id: str) -> tuple[bool, int]:
        """
        Return (allowed, retry_after_seconds).

        retry_after_seconds is 0 when allowed.
        """
        now = time.monotonic()
        window_start = now - self.window_seconds

        with self._lock:
            queue = self._events.setdefault(client_id, deque())
            while queue and queue[0] < window_start:
                queue.popleft()

            if len(queue) >= self.max_requests:
                retry_after = int(max(1, self.window_seconds - (now - queue[0])))
                return False, retry_after

            queue.append(now)
            return True, 0
