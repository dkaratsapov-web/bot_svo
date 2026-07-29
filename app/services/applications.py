"""Бизнес-логика заявок: создание, тикеты, антидубль."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repo
from app.db.models import (
    Application,
    ApplicationStatus,
    Consultation,
    Direction,
    User,
)


@dataclass(slots=True)
class SubmitResult:
    """Итог попытки создания заявки."""

    created: bool
    duplicate: bool
    application: Application | None = None
    consultation: Consultation | None = None

    @property
    def obj(self) -> Application | Consultation | None:
        return self.application or self.consultation


async def submit_join(
    session: AsyncSession,
    user: User,
    *,
    fio: str,
    phone: str,
    phone_verified: bool,
    city: str | None,
    is_svo_participant: bool | None,
    window_hours: int,
    force: bool = False,
) -> SubmitResult:
    """Создаёт заявку на вступление с учётом антидубля."""
    if not force:
        dup = await repo.find_recent_application(session, user.id, window_hours)
        if dup is not None:
            return SubmitResult(created=False, duplicate=True, application=dup)

    app = await repo.create_application(
        session,
        user,
        fio=fio,
        phone=phone,
        phone_verified=phone_verified,
        city=city,
        is_svo_participant=is_svo_participant,
        status=ApplicationStatus.new,
        is_repeat=force,
    )
    await repo.add_event(
        session,
        type="join_submitted",
        user_id=user.id,
        payload={"ticket": app.ticket, "is_repeat": force},
    )
    return SubmitResult(created=True, duplicate=False, application=app)


async def submit_consult(
    session: AsyncSession,
    user: User,
    *,
    direction: Direction,
    fio: str,
    phone: str,
    phone_verified: bool,
    free_text: str | None,
    window_hours: int,
    force: bool = False,
) -> SubmitResult:
    """Создаёт заявку на консультацию с учётом антидубля (по направлению)."""
    if not force:
        dup = await repo.find_recent_consultation(
            session, user.id, direction, window_hours
        )
        if dup is not None:
            return SubmitResult(created=False, duplicate=True, consultation=dup)

    con = await repo.create_consultation(
        session,
        user,
        direction=direction,
        fio=fio,
        phone=phone,
        phone_verified=phone_verified,
        free_text=free_text,
        status=ApplicationStatus.new,
        is_repeat=force,
    )
    await repo.add_event(
        session,
        type="consult_submitted",
        user_id=user.id,
        payload={"ticket": con.ticket, "direction": direction.value, "is_repeat": force},
    )
    return SubmitResult(created=True, duplicate=False, consultation=con)
