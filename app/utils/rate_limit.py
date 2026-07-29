"""Глобальный ограничитель исходящих запросов к API MAX (лимит 30 rps).

Реализован как асинхронный token-bucket: вызовы, превышающие темп,
асинхронно ожидают освобождения токена (очередь через asyncio.Lock).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class RateLimiter:
    def __init__(self, rate: float = 30.0, capacity: float | None = None) -> None:
        self.rate = rate
        self.capacity = capacity if capacity is not None else rate
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._updated
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                wait = (1 - self._tokens) / self.rate
                await asyncio.sleep(wait)

    async def run(self, factory: Callable[[], Awaitable[T]]) -> T:
        await self.acquire()
        return await factory()


# Единый глобальный экземпляр (≤30 rps к platform-api2.max.ru).
limiter = RateLimiter(rate=30.0)
