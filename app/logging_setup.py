"""Настройка structlog: JSON в stdout, без PII в открытом виде."""

from __future__ import annotations

import logging
import re
import sys

import structlog

_PHONE_RE = re.compile(r"(\+?7|8)\D?\(?\d{3}\)?\D?\d{3}\D?\d{2}\D?\d{2}")


def mask_phone(phone: str | None) -> str:
    """+79001230011 -> +7900***0011."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 7:
        return "***"
    prefix = "+7" if len(digits) == 11 else ""
    core = digits[-10:] if len(digits) >= 10 else digits
    return f"{prefix}{core[:3]}***{core[-4:]}"


def mask_fio(fio: str | None) -> str:
    """Иванов Иван Иванович -> Иванов И. И."""
    if not fio:
        return ""
    parts = fio.split()
    if len(parts) == 1:
        return parts[0]
    initials = " ".join(f"{p[0]}." for p in parts[1:] if p)
    return f"{parts[0]} {initials}".strip()


def _mask_phones_in_text(_logger, _method, event_dict):
    """Процессор structlog: маскирует похожие на телефон подстроки в тексте."""

    def repl(match: re.Match[str]) -> str:
        return mask_phone(match.group(0))

    for key, value in list(event_dict.items()):
        if isinstance(value, str):
            event_dict[key] = _PHONE_RE.sub(repl, value)
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _mask_phones_in_text,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
