"""Outer-middleware: идемпотентность и анти-флуд."""

from __future__ import annotations

from typing import Any

from maxapi.filters.middleware import BaseMiddleware
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated

from app import texts
from app.logging_setup import get_logger
from app.runtime import runtime
from app.services.idempotency import update_key

log = get_logger("middleware")


class IdempotencyMiddleware(BaseMiddleware):
    """Отсекает повторную доставку одного и того же апдейта."""

    async def __call__(self, handler, event, data: dict[str, Any]) -> Any:
        key = update_key(event)
        if key is not None and await runtime.idempotency.seen(key):
            log.info("duplicate_update_skipped", key=key)
            # Для callback всё равно подтверждаем, чтобы у оператора/пользователя
            # не «завис» индикатор загрузки.
            if isinstance(event, MessageCallback):
                try:
                    await event.ack()
                except Exception:  # noqa: BLE001
                    pass
            return None
        return await handler(event, data)


class AntiFloodMiddleware(BaseMiddleware):
    """Ограничивает частоту сообщений от пользователя (мягкий тротлинг)."""

    async def __call__(self, handler, event, data: dict[str, Any]) -> Any:
        user_id: int | None = None
        if isinstance(event, MessageCreated):
            user_id = event.get_ids()[1]
        elif isinstance(event, MessageCallback):
            user_id = event.callback.user.user_id

        if user_id is not None and runtime.antiflood.hit(user_id):
            log.warning("throttled", user_id=user_id)
            try:
                if isinstance(event, MessageCallback):
                    await event.ack(texts.THROTTLED)
                elif isinstance(event, MessageCreated):
                    await event.message.answer(texts.THROTTLED)
            except Exception:  # noqa: BLE001
                pass
            return None
        return await handler(event, data)
