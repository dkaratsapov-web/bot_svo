"""Тесты маршрутизации уведомлений операторов и формата текста."""

from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.db.models import Application, Consultation, Direction
from app.services import notifier


def _settings(**kw):
    base = dict(
        _env_file=None,
        ADMIN_CHAT_DEFAULT_ID="999",
        ADMIN_CHAT_JOIN_ID="100",
        ADMIN_CHAT_JOB_ID="200",
        ADMIN_CHAT_PSY_ID="300",
        ADMIN_CHAT_LAW_ID="400",
        ADMIN_CHAT_OTHER_ID="500",
    )
    base.update(kw)
    return Settings(**base)


def _app():
    return Application(
        ticket="ASV-2026-000001", fio="Иванов Иван", phone="+79001112233",
        phone_verified=True, city="Тверь", is_svo_participant=True,
        created_at=datetime(2026, 7, 1, 9, 30, tzinfo=timezone.utc),
    )


def _con(direction):
    return Consultation(
        ticket="CON-2026-000001", direction=direction, fio="Пётр Петров",
        phone="+79005556677", phone_verified=False,
        created_at=datetime(2026, 7, 1, 9, 30, tzinfo=timezone.utc),
    )


def test_route_join_to_join_chat():
    assert notifier.resolve_target(_settings(), _app()) == 100


@pytest.mark.parametrize(
    "direction,expected",
    [
        (Direction.job, 200),
        (Direction.psy, 300),
        (Direction.law, 400),
        (Direction.other, 500),
    ],
)
def test_route_consult_by_direction(direction, expected):
    assert notifier.resolve_target(_settings(), _con(direction)) == expected


def test_route_fallback_to_default():
    s = _settings(ADMIN_CHAT_JOB_ID="")
    assert notifier.resolve_target(s, _con(Direction.job)) == 999


def test_route_none_when_no_chats():
    s = Settings(_env_file=None)
    assert notifier.resolve_target(s, _app()) is None


def test_notification_text_join_contains_fields():
    text = notifier.build_notification(_app())
    assert "ASV-2026-000001" in text
    assert "Вступление" in text
    assert "Иванов Иван" in text
    assert "подтверждён MAX" in text
    assert "Населённый пункт: Тверь" in text
    assert "Участник СВО: да" in text


def test_notification_text_consult_has_direction_and_no_city():
    text = notifier.build_notification(_con(Direction.psy))
    assert "Психологическая помощь" in text
    assert "Населённый пункт" not in text
    assert "подтверждён MAX" not in text  # phone_verified=False


class _FakeBot:
    def __init__(self, fail_times=0):
        self.fail_times = fail_times
        self.calls = []

    async def send_message(self, chat_id=None, user_id=None, text=None, attachments=None):
        self.calls.append((chat_id, text))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("network")
        return {"ok": True}


@pytest.mark.asyncio
async def test_notify_sends_to_resolved_chat():
    bot = _FakeBot()
    n = notifier.Notifier(bot, _settings())
    ok = await n.notify(_app())
    assert ok is True
    assert bot.calls[0][0] == 100  # чат «Вступление»
    assert "ASV-2026-000001" in bot.calls[0][1]


@pytest.mark.asyncio
async def test_notify_returns_false_without_chat_and_does_not_send():
    bot = _FakeBot()
    n = notifier.Notifier(bot, Settings(_env_file=None))
    ok = await n.notify(_app())
    assert ok is False
    assert bot.calls == []


@pytest.mark.asyncio
async def test_notify_retries_then_queues_on_persistent_failure(monkeypatch):
    async def _no_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(notifier.asyncio, "sleep", _no_sleep)
    bot = _FakeBot(fail_times=99)
    n = notifier.Notifier(bot, _settings())
    ok = await n.notify(_con(Direction.job))
    assert ok is False           # 3 попытки исчерпаны
    assert len(bot.calls) == 3   # ретраи выполнены
    assert n._queue.qsize() == 1  # заявка поставлена в очередь повтора


@pytest.mark.asyncio
async def test_notify_retry_succeeds_on_second_attempt(monkeypatch):
    async def _no_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(notifier.asyncio, "sleep", _no_sleep)
    bot = _FakeBot(fail_times=1)
    n = notifier.Notifier(bot, _settings())
    ok = await n.notify(_app())
    assert ok is True
    assert len(bot.calls) == 2


@pytest.mark.asyncio
async def test_notify_uses_rate_limiter():
    from app.utils.rate_limit import RateLimiter

    bot = _FakeBot()
    n = notifier.Notifier(bot, _settings(), limiter=RateLimiter(rate=1000))
    ok = await n.notify(_app())
    assert ok is True
    assert bot.calls[0][0] == 100


@pytest.mark.asyncio
async def test_retry_worker_delivers_queued_message(monkeypatch):
    import asyncio

    async def _no_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(notifier.asyncio, "sleep", _no_sleep)
    bot = _FakeBot()  # воркер должен доставить с первой попытки
    n = notifier.Notifier(bot, _settings())
    await n._queue.put((100, "текст", "ASV-2026-000001", 0))
    n.start()
    await asyncio.wait_for(n._queue.join(), timeout=2.0)
    await n.stop()
    assert bot.calls and bot.calls[0][0] == 100
