"""Уведомления операторов: формирование, маршрутизация, ретраи."""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from app import keyboards, texts
from app.config import Settings
from app.db.models import Application, Consultation, Direction
from app.logging_setup import get_logger

log = get_logger("notifier")
MSK = ZoneInfo("Europe/Moscow")


def resolve_target(settings: Settings, obj: Application | Consultation) -> int | None:
    """Определяет chat_id оператора по типу заявки и направлению."""
    if isinstance(obj, Application):
        return settings.admin_chat_for("join")
    return settings.admin_chat_for("consult", obj.direction.value)


def build_notification(obj: Application | Consultation) -> str:
    """Собирает текст уведомления по спецификации."""
    verified = texts.NOTIFY_VERIFIED if obj.phone_verified else ""
    sent = obj.created_at.astimezone(MSK).strftime("%d.%m.%Y %H:%M")

    if isinstance(obj, Application):
        kind = "Вступление"
        extra = (
            f"Населённый пункт: {obj.city or '—'}\n"
            f"Участник СВО: {texts.yes_no(obj.is_svo_participant)}\n"
        )
    else:
        kind = f"Консультация: {texts.DIRECTION_TITLES[obj.direction.value]}"
        extra = ""

    return texts.NOTIFY.format(
        ticket=obj.ticket,
        kind=kind,
        fio=obj.fio,
        phone=obj.phone,
        verified=verified,
        extra=extra,
        sent=sent,
    )


class Notifier:
    """Отправка уведомлений операторам с ретраями и очередью повтора."""

    def __init__(self, bot, settings: Settings, limiter=None) -> None:
        self.bot = bot
        self.settings = settings
        self.limiter = limiter
        self._queue: asyncio.Queue[tuple[int, str, str, int]] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

    def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._retry_worker())

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None

    async def _send(self, chat_id: int, text: str, ticket: str) -> None:
        kb = keyboards.operator_actions(ticket)

        async def _do():
            return await self.bot.send_message(
                chat_id=chat_id, text=text, attachments=kb
            )

        if self.limiter is not None:
            await self.limiter.run(_do)
        else:
            await _do()

    async def notify(self, obj: Application | Consultation) -> bool:
        """Отправляет уведомление с 3 попытками (экспоненциальная задержка).

        Возвращает True при успехе. При неудаче ставит в очередь повтора и
        возвращает False — сохранение заявки этим не откатывается.
        """
        chat_id = resolve_target(self.settings, obj)
        if chat_id is None:
            log.warning("notify_no_chat", ticket=obj.ticket)
            return False

        text = build_notification(obj)
        ok = await self._attempt(chat_id, text, obj.ticket, attempts=3)
        if not ok:
            await self._queue.put((chat_id, text, obj.ticket, 0))
            log.error("notify_queued_for_retry", ticket=obj.ticket)
        return ok

    async def _attempt(self, chat_id: int, text: str, ticket: str, attempts: int) -> bool:
        delay = 1.0
        for i in range(1, attempts + 1):
            try:
                await self._send(chat_id, text, ticket)
                log.info("notify_sent", ticket=ticket, chat_id=chat_id, attempt=i)
                return True
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "notify_attempt_failed",
                    ticket=ticket,
                    attempt=i,
                    error=str(exc),
                )
                if i < attempts:
                    await asyncio.sleep(delay)
                    delay *= 2
        return False

    async def _retry_worker(self) -> None:
        """Фоновая переотправка не доставленных уведомлений."""
        while True:
            chat_id, text, ticket, tries = await self._queue.get()
            await asyncio.sleep(min(60.0, 5.0 * (2**tries)))
            ok = await self._attempt(chat_id, text, ticket, attempts=1)
            if not ok:
                if tries < 8:
                    await self._queue.put((chat_id, text, ticket, tries + 1))
                else:
                    log.error("notify_giving_up", ticket=ticket)
            self._queue.task_done()
