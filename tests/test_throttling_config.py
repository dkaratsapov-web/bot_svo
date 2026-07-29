"""Тесты анти-флуда и разбора конфигурации доступа."""

from app.config import Settings
from app.utils.throttling import AntiFlood


def test_antiflood_triggers_after_limit():
    af = AntiFlood(limit=3, window_sec=60.0)
    t = 0.0
    results = [af.hit(42, now=t + i * 0.1) for i in range(5)]
    # Первые 3 — в пределах лимита, далее тротлинг
    assert results[:3] == [False, False, False]
    assert results[3] is True


def test_antiflood_window_slides():
    af = AntiFlood(limit=2, window_sec=10.0)
    assert af.hit(1, now=0.0) is False
    assert af.hit(1, now=1.0) is False
    assert af.hit(1, now=2.0) is True
    # Спустя окно счётчик очищается
    assert af.hit(1, now=100.0) is False


def test_admin_ids_parsing_and_check():
    s = Settings(_env_file=None, ADMIN_USER_IDS="123, 456 ,789")
    assert s.admin_user_ids == [123, 456, 789]
    assert s.is_admin(456) is True
    assert s.is_admin(999) is False
    assert s.is_admin(None) is False


def test_admin_chat_routing_helpers():
    s = Settings(
        _env_file=None,
        ADMIN_CHAT_DEFAULT_ID="9",
        ADMIN_CHAT_JOIN_ID="1",
        ADMIN_CHAT_LAW_ID="4",
    )
    assert s.admin_chat_for("join") == 1
    assert s.admin_chat_for("consult", "law") == 4
    assert s.admin_chat_for("consult", "psy") == 9  # фолбэк на default
    assert s.use_webhook is False
