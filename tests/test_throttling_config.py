"""Тесты анти-флуда и разбора конфигурации доступа."""

import pytest

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


# Настройки читаются из окружения, а не из init-аргументов: pydantic-settings
# обрабатывает эти пути по-разному (для сложных типов env-значение сперва
# разбирается как JSON). Тесты ниже идут именно через окружение.
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", []),                       # пустое значение роняло старт бота
        ("123, 456 ,789", [123, 456, 789]),
        ("111,abc,,222", [111, 222]),   # опечатка не должна ломать запуск
        ("[1,2]", [1, 2]),              # JSON-подобная запись
        ('["7","8"]', [7, 8]),
        ("42", [42]),
    ],
)
def test_admin_ids_from_env(monkeypatch, raw, expected):
    monkeypatch.setenv("ADMIN_USER_IDS", raw)
    assert Settings(_env_file=None).admin_user_ids == expected


def test_admin_ids_absent_from_env(monkeypatch):
    monkeypatch.delenv("ADMIN_USER_IDS", raising=False)
    assert Settings(_env_file=None).admin_user_ids == []


@pytest.mark.parametrize(
    "var",
    [
        "ADMIN_CHAT_DEFAULT_ID",
        "ADMIN_CHAT_JOIN_ID",
        "ADMIN_CHAT_JOB_ID",
        "ADMIN_CHAT_PSY_ID",
        "ADMIN_CHAT_LAW_ID",
        "ADMIN_CHAT_OTHER_ID",
    ],
)
def test_empty_chat_ids_from_env_become_none(monkeypatch, var):
    """Пустые значения чатов допустимы — бот стартует и падает на фолбэк."""
    monkeypatch.setenv(var, "")
    settings = Settings(_env_file=None)
    assert getattr(settings, var.lower()) is None


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
