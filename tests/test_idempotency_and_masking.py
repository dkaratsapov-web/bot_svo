"""Тесты идемпотентности доставки и маскирования PII в логах."""

import pytest

from app.logging_setup import mask_fio, mask_phone
from app.services.idempotency import IdempotencyStore


@pytest.mark.asyncio
async def test_idempotency_memory_dedup():
    store = IdempotencyStore(redis_client=None)
    assert await store.seen("upd:1") is False  # первый раз — не дубликат
    assert await store.seen("upd:1") is True   # повтор — дубликат
    assert await store.seen("upd:2") is False


def test_mask_phone():
    assert mask_phone("+79001230011") == "+7900***0011"
    assert mask_phone("89001230011") == "+7900***0011"
    assert mask_phone("") == ""


def test_mask_fio():
    assert mask_fio("Иванов Иван Иванович") == "Иванов И. И."
    assert mask_fio("Петров Пётр") == "Петров П."
    assert mask_fio("") == ""
