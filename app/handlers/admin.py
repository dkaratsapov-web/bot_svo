"""Админ- и оператор-функции: /stats, /export, кнопки «Взять/Обработано»."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from maxapi import Router
from maxapi.context import BaseContext
from maxapi.enums.upload_type import UploadType
from maxapi.filters.command import Command
from maxapi.types.input_media import InputMediaBuffer

from app import keyboards, texts
from app.config import get_settings
from app.db import repo
from app.db.models import ApplicationStatus
from app.db.session import session_scope
from app.handlers import helpers
from app.handlers.helpers import send
from app.logging_setup import get_logger
from app.services import export
from app.utils.filters import Payload

router = Router()
log = get_logger("admin")


def _is_admin(event) -> bool:
    return get_settings().is_admin(helpers.user_meta(event)[0])


def _parse_date(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%d.%m.%Y").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# /stats
# --------------------------------------------------------------------------- #
@router.message_created(Command("stats"))
async def cmd_stats(event, context: BaseContext) -> None:
    if not _is_admin(event):
        await send(event, texts.ADMIN_ONLY)
        return
    async with session_scope() as session:
        data = await repo.stats(session)
    await send(event, texts.STATS.format(**data))


# --------------------------------------------------------------------------- #
# /export [dd.mm.yyyy dd.mm.yyyy]
# --------------------------------------------------------------------------- #
@router.message_created(Command("export"))
async def cmd_export(event, context: BaseContext, args: list[str] | None = None) -> None:
    if not _is_admin(event):
        await send(event, texts.ADMIN_ONLY)
        return

    args = args or []
    date_from = date_to = None
    if len(args) >= 2:
        date_from = _parse_date(args[0])
        date_to = _parse_date(args[1])
        if date_from is None or date_to is None:
            await send(event, texts.EXPORT_BAD_DATES)
            return
        # Верхняя граница включительно: сравнение < (date_to + 1 день)
        date_to = date_to + timedelta(days=1)

    async with session_scope() as session:
        apps = await repo.list_applications(session, date_from, date_to)
        cons = await repo.list_consultations(session, date_from, date_to)

    if not apps and not cons:
        await send(event, texts.EXPORT_EMPTY)
        return

    content = export.build_workbook(apps, cons)
    filename = export.export_filename(
        date_from, (date_to - timedelta(days=1)) if date_to else None
    )
    media = InputMediaBuffer(buffer=content, filename=filename, type=UploadType.FILE)
    chat_id, user_id = event.get_ids()
    await event.bot.send_message(chat_id=chat_id, user_id=user_id, attachments=[media])
    log.info("export_sent", filename=filename, apps=len(apps), cons=len(cons))


# --------------------------------------------------------------------------- #
# Кнопки операторов под уведомлением
# --------------------------------------------------------------------------- #
@router.message_callback(Payload(keyboards.P_ADMIN_TAKE, prefix=True))
async def take(event, context: BaseContext, suffix: str) -> None:
    await _set_status(event, suffix, ApplicationStatus.in_progress, "take")


@router.message_callback(Payload(keyboards.P_ADMIN_DONE, prefix=True))
async def mark_done(event, context: BaseContext, suffix: str) -> None:
    await _set_status(event, suffix, ApplicationStatus.done, "done")


async def _set_status(event, ticket: str, status: ApplicationStatus, action: str) -> None:
    max_user_id, _, username, display = helpers.user_meta(event)
    who = display or (f"@{username}" if username else str(max_user_id))

    async with session_scope() as session:
        obj = await repo.set_status_by_ticket(session, ticket, status)
        if obj is not None:
            await repo.add_event(
                session,
                type=f"operator_{action}",
                payload={"ticket": ticket, "by": max_user_id, "who": who},
            )

    if obj is None:
        await helpers.ack(event, f"Заявка {ticket} не найдена")
        return

    note = (
        texts.NOTIFY_TAKEN if status == ApplicationStatus.in_progress else texts.NOTIFY_MARKED_DONE
    ).format(ticket=ticket, who=who)
    await helpers.ack(event, texts.ACK_SAVED)
    # Дублируем статус реплаем в чат операторов
    if event.message is not None:
        try:
            await event.message.answer(note)
        except Exception:  # noqa: BLE001
            pass
