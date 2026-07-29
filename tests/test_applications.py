"""Тесты сервиса заявок: тикеты, антидубль, черновики, повтор."""

import pytest

from app.db import repo
from app.db.models import ApplicationStatus, Direction
from app.services import applications


async def _user(session, max_id=1001):
    return await repo.get_or_create_user(session, max_id, chat_id=1)


@pytest.mark.asyncio
async def test_join_ticket_format_and_sequence(sessionmaker):
    async with sessionmaker() as s:
        u = await _user(s)
        r1 = await applications.submit_join(
            s, u, fio="Иванов Иван", phone="+79001112233", phone_verified=True,
            city="Тверь", is_svo_participant=True, window_hours=24, force=True,
        )
        r2 = await applications.submit_join(
            s, u, fio="Иванов Иван", phone="+79001112233", phone_verified=True,
            city="Тверь", is_svo_participant=True, window_hours=24, force=True,
        )
        await s.commit()
    assert r1.application.ticket == "ASV-2026-000001"
    assert r2.application.ticket == "ASV-2026-000002"


@pytest.mark.asyncio
async def test_consult_ticket_prefix(sessionmaker):
    async with sessionmaker() as s:
        u = await _user(s)
        r = await applications.submit_consult(
            s, u, direction=Direction.law, fio="Пётр Петров", phone="+79001112233",
            phone_verified=False, free_text=None, window_hours=24,
        )
        await s.commit()
    assert r.consultation.ticket.startswith("CON-2026-")


@pytest.mark.asyncio
async def test_join_duplicate_within_window(sessionmaker):
    async with sessionmaker() as s:
        u = await _user(s)
        first = await applications.submit_join(
            s, u, fio="Иванов Иван", phone="+79001112233", phone_verified=True,
            city="Тверь", is_svo_participant=True, window_hours=24,
        )
        dup = await applications.submit_join(
            s, u, fio="Иванов Иван", phone="+79001112233", phone_verified=True,
            city="Тверь", is_svo_participant=True, window_hours=24,
        )
        await s.commit()
    assert first.created and not first.duplicate
    assert dup.duplicate
    assert dup.application.ticket == first.application.ticket


@pytest.mark.asyncio
async def test_join_force_creates_repeat(sessionmaker):
    async with sessionmaker() as s:
        u = await _user(s)
        await applications.submit_join(
            s, u, fio="Иванов Иван", phone="+79001112233", phone_verified=True,
            city="Тверь", is_svo_participant=True, window_hours=24,
        )
        forced = await applications.submit_join(
            s, u, fio="Иванов Иван", phone="+79001112233", phone_verified=True,
            city="Тверь", is_svo_participant=True, window_hours=24, force=True,
        )
        await s.commit()
    assert forced.created
    assert forced.application.is_repeat is True


@pytest.mark.asyncio
async def test_consult_duplicate_is_per_direction(sessionmaker):
    async with sessionmaker() as s:
        u = await _user(s)
        a = await applications.submit_consult(
            s, u, direction=Direction.job, fio="Пётр Петров", phone="+79001112233",
            phone_verified=False, free_text=None, window_hours=24,
        )
        # Другое направление — не дубликат
        b = await applications.submit_consult(
            s, u, direction=Direction.psy, fio="Пётр Петров", phone="+79001112233",
            phone_verified=False, free_text=None, window_hours=24,
        )
        # То же направление — дубликат
        c = await applications.submit_consult(
            s, u, direction=Direction.job, fio="Пётр Петров", phone="+79001112233",
            phone_verified=False, free_text=None, window_hours=24,
        )
        await s.commit()
    assert a.created and b.created
    assert not b.duplicate
    assert c.duplicate


@pytest.mark.asyncio
async def test_draft_not_counted_as_duplicate(sessionmaker):
    async with sessionmaker() as s:
        u = await _user(s)
        await repo.create_application(
            s, u, fio="", phone="", phone_verified=False, city=None,
            is_svo_participant=None, status=ApplicationStatus.draft,
        )
        # Черновик не должен блокировать новую заявку
        r = await applications.submit_join(
            s, u, fio="Иванов Иван", phone="+79001112233", phone_verified=True,
            city="Тверь", is_svo_participant=True, window_hours=24,
        )
        await s.commit()
    assert r.created and not r.duplicate
