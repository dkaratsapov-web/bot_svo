"""Идемпотентность доставки апдейтов: dedupe по ключу с TTL 24 ч.

Redis в проде, in-memory-фолбэк в dev. Гарантирует, что повторная доставка
одного и того же webhook-апдейта не запустит обработку дважды.
"""

from __future__ import annotations

import time

DEFAULT_TTL = 24 * 3600


class IdempotencyStore:
    def __init__(self, redis_client=None, ttl: int = DEFAULT_TTL, prefix: str = "idem") -> None:
        self.redis = redis_client
        self.ttl = ttl
        self.prefix = prefix
        self._mem: dict[str, float] = {}

    async def seen(self, key: str) -> bool:
        """Атомарно помечает ключ обработанным.

        Возвращает True, если ключ уже был обработан ранее (дубликат).
        """
        full = f"{self.prefix}:{key}"
        if self.redis is not None:
            # SET NX: True если установлено впервые -> не дубликат
            was_set = await self.redis.set(full, "1", nx=True, ex=self.ttl)
            return not bool(was_set)

        now = time.monotonic()
        self._gc(now)
        if full in self._mem:
            return True
        self._mem[full] = now + self.ttl
        return False

    def _gc(self, now: float) -> None:
        if len(self._mem) < 10000:
            return
        expired = [k for k, exp in self._mem.items() if exp < now]
        for k in expired:
            self._mem.pop(k, None)


def update_key(event) -> str | None:
    """Строит стабильный ключ для апдейта (для dedupe)."""
    from maxapi.types.updates.message_callback import MessageCallback
    from maxapi.types.updates.message_created import MessageCreated

    if isinstance(event, MessageCallback):
        return f"cb:{event.callback.callback_id}"
    if isinstance(event, MessageCreated):
        body = event.message.body
        mid = getattr(body, "mid", None) if body else None
        if mid:
            return f"msg:{mid}"
        return f"msg:{event.message.timestamp}:{event.get_ids()[1]}"
    return None
