"""Кастомные фильтры для callback-кнопок."""

from __future__ import annotations

from typing import Any

from maxapi.filters import BaseFilter
from maxapi.types.updates.message_callback import MessageCallback


class Payload(BaseFilter):
    """Совпадение payload callback-кнопки по точному значению или префиксу.

    Пример:
        @router.message_callback(Payload("menu:join"))
        @router.message_callback(Payload("admin:take:", prefix=True))

    При prefix=True в handler передаётся kwarg ``suffix`` — часть payload
    после префикса (например, тикет).
    """

    def __init__(self, value: str, *, prefix: bool = False) -> None:
        self.value = value
        self.prefix = prefix

    async def __call__(self, event: Any) -> bool | dict[str, Any]:
        if not isinstance(event, MessageCallback):
            return False
        payload = event.callback.payload
        if not payload:
            return False
        if self.prefix:
            if payload.startswith(self.value):
                return {"suffix": payload[len(self.value):]}
            return False
        return payload == self.value


class PayloadIn(BaseFilter):
    """Совпадение payload с одним из значений набора."""

    def __init__(self, values: set[str]) -> None:
        self.values = set(values)

    async def __call__(self, event: Any) -> bool | dict[str, Any]:
        if not isinstance(event, MessageCallback):
            return False
        payload = event.callback.payload
        if payload in self.values:
            return {"payload_value": payload}
        return False
