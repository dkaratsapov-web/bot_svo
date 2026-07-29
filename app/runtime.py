"""Разделяемые между handler'ами зависимости.

Инициализируются один раз при старте (main.py) и доступны handler'ам без
явной передачи через data — так handler-функции остаются простыми.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.idempotency import IdempotencyStore
    from app.services.notifier import Notifier
    from app.utils.throttling import AntiFlood


class Runtime:
    settings: "Settings"
    notifier: "Notifier"
    antiflood: "AntiFlood"
    idempotency: "IdempotencyStore"

    def operator_url(self) -> str | None:
        """Ссылка «связаться с оператором»: сайт → tel: → mailto:."""
        s = self.settings
        if s.org_site_url:
            return s.org_site_url
        if s.org_phone:
            digits = "".join(ch for ch in s.org_phone if ch.isdigit() or ch == "+")
            return f"tel:{digits}" if digits else None
        if s.org_email:
            return f"mailto:{s.org_email}"
        return None


runtime = Runtime()
