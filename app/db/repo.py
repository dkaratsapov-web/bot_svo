"""Репозиторий: доступ к данным (пользователи, заявки, события)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Application,
    ApplicationStatus,
    Consultation,
    Direction,
    Event,
    User,
    utcnow,
)

JOIN_TICKET_PREFIX = "ASV"
CONSULT_TICKET_PREFIX = "CON"


# --------------------------------------------------------------------------- #
# Пользователи
# --------------------------------------------------------------------------- #
async def get_user_by_max_id(session: AsyncSession, max_user_id: int) -> User | None:
    res = await session.execute(select(User).where(User.max_user_id == max_user_id))
    return res.scalar_one_or_none()


async def get_or_create_user(
    session: AsyncSession,
    max_user_id: int,
    chat_id: int | None = None,
    username: str | None = None,
    display_name: str | None = None,
) -> User:
    user = await get_user_by_max_id(session, max_user_id)
    if user is None:
        user = User(
            max_user_id=max_user_id,
            chat_id=chat_id,
            username=username,
            display_name=display_name,
        )
        session.add(user)
        await session.flush()
        return user

    # Мягко обновляем изменяемые поля
    if chat_id is not None:
        user.chat_id = chat_id
    if username is not None:
        user.username = username
    if display_name is not None:
        user.display_name = display_name
    return user


async def set_consent(session: AsyncSession, user: User, version: str) -> None:
    user.consent_given_at = utcnow()
    user.consent_version = version
    await session.flush()


# --------------------------------------------------------------------------- #
# Тикеты
# --------------------------------------------------------------------------- #
async def _next_ticket(session: AsyncSession, prefix: str, year: int) -> str:
    """Генерирует следующий тикет вида PREFIX-YYYY-000001.

    Порядковый номер — max существующего для (prefix, year) + 1. Нулевое
    дополнение до 6 цифр обеспечивает корректную лексикографическую сортировку.
    """
    like = f"{prefix}-{year}-%"
    model = Application if prefix == JOIN_TICKET_PREFIX else Consultation
    res = await session.execute(
        select(func.max(model.ticket)).where(model.ticket.like(like))
    )
    last: str | None = res.scalar_one_or_none()
    seq = 1
    if last:
        try:
            seq = int(last.rsplit("-", 1)[1]) + 1
        except (ValueError, IndexError):
            seq = 1
    return f"{prefix}-{year}-{seq:06d}"


# --------------------------------------------------------------------------- #
# Антидубль
# --------------------------------------------------------------------------- #
async def find_recent_application(
    session: AsyncSession, user_id: int, window_hours: int
) -> Application | None:
    since = utcnow() - timedelta(hours=window_hours)
    res = await session.execute(
        select(Application)
        .where(
            Application.user_id == user_id,
            Application.status != ApplicationStatus.draft,
            Application.status != ApplicationStatus.rejected,
            Application.created_at >= since,
        )
        .order_by(Application.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def find_recent_consultation(
    session: AsyncSession, user_id: int, direction: Direction, window_hours: int
) -> Consultation | None:
    since = utcnow() - timedelta(hours=window_hours)
    res = await session.execute(
        select(Consultation)
        .where(
            Consultation.user_id == user_id,
            Consultation.direction == direction,
            Consultation.status != ApplicationStatus.draft,
            Consultation.status != ApplicationStatus.rejected,
            Consultation.created_at >= since,
        )
        .order_by(Consultation.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Создание заявок
# --------------------------------------------------------------------------- #
async def create_application(
    session: AsyncSession,
    user: User,
    fio: str,
    phone: str,
    phone_verified: bool,
    city: str | None,
    is_svo_participant: bool | None,
    status: ApplicationStatus = ApplicationStatus.new,
    is_repeat: bool = False,
) -> Application:
    year = utcnow().astimezone(timezone.utc).year
    ticket = await _next_ticket(session, JOIN_TICKET_PREFIX, year)
    app = Application(
        ticket=ticket,
        user_id=user.id,
        fio=fio,
        phone=phone,
        phone_verified=phone_verified,
        city=city,
        is_svo_participant=is_svo_participant,
        status=status,
        is_repeat=is_repeat,
    )
    session.add(app)
    await session.flush()
    return app


async def create_consultation(
    session: AsyncSession,
    user: User,
    direction: Direction,
    fio: str,
    phone: str,
    phone_verified: bool,
    free_text: str | None = None,
    status: ApplicationStatus = ApplicationStatus.new,
    is_repeat: bool = False,
) -> Consultation:
    year = utcnow().astimezone(timezone.utc).year
    ticket = await _next_ticket(session, CONSULT_TICKET_PREFIX, year)
    con = Consultation(
        ticket=ticket,
        user_id=user.id,
        direction=direction,
        fio=fio,
        phone=phone,
        phone_verified=phone_verified,
        free_text=free_text,
        status=status,
        is_repeat=is_repeat,
    )
    session.add(con)
    await session.flush()
    return con


# --------------------------------------------------------------------------- #
# Смена статуса (кнопки операторов)
# --------------------------------------------------------------------------- #
async def get_application_by_ticket(session: AsyncSession, ticket: str) -> Application | None:
    res = await session.execute(select(Application).where(Application.ticket == ticket))
    return res.scalar_one_or_none()


async def get_consultation_by_ticket(session: AsyncSession, ticket: str) -> Consultation | None:
    res = await session.execute(select(Consultation).where(Consultation.ticket == ticket))
    return res.scalar_one_or_none()


async def set_status_by_ticket(
    session: AsyncSession, ticket: str, status: ApplicationStatus
) -> Application | Consultation | None:
    obj: Application | Consultation | None
    if ticket.startswith(JOIN_TICKET_PREFIX):
        obj = await get_application_by_ticket(session, ticket)
    else:
        obj = await get_consultation_by_ticket(session, ticket)
    if obj is not None:
        obj.status = status
        obj.updated_at = utcnow()
        await session.flush()
    return obj


# --------------------------------------------------------------------------- #
# События / аудит
# --------------------------------------------------------------------------- #
async def add_event(
    session: AsyncSession,
    type: str,
    user_id: int | None = None,
    payload: dict | None = None,
) -> Event:
    ev = Event(
        type=type,
        user_id=user_id,
        payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
    )
    session.add(ev)
    await session.flush()
    return ev


# --------------------------------------------------------------------------- #
# Статистика и выгрузка
# --------------------------------------------------------------------------- #
async def _count(session: AsyncSession, model, *conditions) -> int:
    res = await session.execute(select(func.count()).select_from(model).where(*conditions))
    return int(res.scalar_one())


async def stats(session: AsyncSession) -> dict:
    now = utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    data = {
        "j_today": await _count(session, Application, Application.created_at >= today_start),
        "j_week": await _count(session, Application, Application.created_at >= week_start),
        "j_total": await _count(session, Application),
        "c_today": await _count(session, Consultation, Consultation.created_at >= today_start),
        "c_week": await _count(session, Consultation, Consultation.created_at >= week_start),
        "c_total": await _count(session, Consultation),
    }
    for d in Direction:
        data[f"d_{d.value}"] = await _count(
            session, Consultation, Consultation.direction == d
        )
    return data


async def list_applications(
    session: AsyncSession, date_from: datetime | None = None, date_to: datetime | None = None
) -> list[Application]:
    stmt = select(Application).options(selectinload(Application.user))
    if date_from is not None:
        stmt = stmt.where(Application.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Application.created_at < date_to)
    stmt = stmt.order_by(Application.created_at)
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def list_consultations(
    session: AsyncSession, date_from: datetime | None = None, date_to: datetime | None = None
) -> list[Consultation]:
    stmt = select(Consultation).options(selectinload(Consultation.user))
    if date_from is not None:
        stmt = stmt.where(Consultation.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Consultation.created_at < date_to)
    stmt = stmt.order_by(Consultation.created_at)
    res = await session.execute(stmt)
    return list(res.scalars().all())
