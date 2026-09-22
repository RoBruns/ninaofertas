"""Rate limiter em memoria com interface substituivel por Redis."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from threading import Lock
from time import monotonic
from typing import Protocol

from fastapi import Request

from api.errors import APIError


class RateLimiter(Protocol):
    def hit(self, bucket: str, key: str, limit: int, window_seconds: int) -> bool: ...

    def clear(self) -> None: ...


class InMemoryRateLimiter:
    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._entries: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, bucket: str, key: str, limit: int, window_seconds: int) -> bool:
        now = self._clock()
        cutoff = now - window_seconds
        with self._lock:
            entries = self._entries[(bucket, key)]
            while entries and entries[0] <= cutoff:
                entries.popleft()
            if len(entries) >= limit:
                return False
            entries.append(now)
            return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


limiter: RateLimiter = InMemoryRateLimiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def limit_login(request: Request) -> None:
    if not limiter.hit("login", client_ip(request), 5, 60):
        raise APIError(429, "RATE_LIMITED", "Limite de tentativas excedido")
