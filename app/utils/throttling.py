"""Анти-флуд: ограничение частоты сообщений от пользователя.

Скользящее окно в памяти процесса. Для одиночного инстанса этого достаточно;
при горизонтальном масштабировании счётчики следует вынести в Redis.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class AntiFlood:
    def __init__(self, limit: int = 20, window_sec: float = 60.0) -> None:
        self.limit = limit
        self.window = window_sec
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def hit(self, user_id: int, now: float | None = None) -> bool:
        """Регистрирует событие. Возвращает True, если лимит превышен (тротлинг)."""
        ts = now if now is not None else time.monotonic()
        dq = self._hits[user_id]
        boundary = ts - self.window
        while dq and dq[0] < boundary:
            dq.popleft()
        dq.append(ts)
        return len(dq) > self.limit

    def reset(self, user_id: int) -> None:
        self._hits.pop(user_id, None)
