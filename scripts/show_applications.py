#!/usr/bin/env python3
"""Показывает сохранённые заявки прямо из БД.

Нужен, когда уведомления операторам ещё не настроены (пустые ADMIN_CHAT_*)
или чтобы просто убедиться, что заявка записалась.

Запуск на сервере:
    cd /opt/bot_svo
    docker compose -f docker-compose.prod.yml exec -T bot python scripts/show_applications.py

Опции:
    --limit N   показать только последние N записей каждого типа
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import texts  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import repo  # noqa: E402
from app.db import session as db  # noqa: E402
from app.services.notifier import MSK  # noqa: E402


def _dt(value) -> str:
    return value.astimezone(MSK).strftime("%d.%m.%Y %H:%M")


async def main(limit: int | None) -> None:
    settings = get_settings()
    db.init_engine(settings.database_url)
    try:
        async with db.session_scope() as session:
            apps = await repo.list_applications(session)
            cons = await repo.list_consultations(session)
            stats = await repo.stats(session)
    finally:
        await db.dispose_engine()

    if limit:
        apps, cons = apps[-limit:], cons[-limit:]

    print("=" * 78)
    print(f"ВСТУПЛЕНИЕ В АССОЦИАЦИЮ — {len(apps)} запис(ь/и)")
    print("=" * 78)
    for a in apps:
        verified = " (подтверждён MAX)" if a.phone_verified else ""
        print(
            f"{a.ticket}  {_dt(a.created_at)}  [{a.status.value}]\n"
            f"   ФИО:      {a.fio}\n"
            f"   Телефон:  {a.phone}{verified}\n"
            f"   Нас. пункт: {a.city or '—'}\n"
            f"   Участник СВО: {texts.yes_no(a.is_svo_participant)}\n"
            f"   max_user_id: {a.user.max_user_id if a.user else '—'}"
        )

    print()
    print("=" * 78)
    print(f"КОНСУЛЬТАЦИИ — {len(cons)} запис(ь/и)")
    print("=" * 78)
    for c in cons:
        verified = " (подтверждён MAX)" if c.phone_verified else ""
        print(
            f"{c.ticket}  {_dt(c.created_at)}  [{c.status.value}]\n"
            f"   Направление: {texts.DIRECTION_TITLES[c.direction.value]}\n"
            f"   ФИО:      {c.fio}\n"
            f"   Телефон:  {c.phone}{verified}\n"
            f"   max_user_id: {c.user.max_user_id if c.user else '—'}"
        )

    print()
    print("-" * 78)
    print(
        f"Итого: вступление {stats['j_total']} (сегодня {stats['j_today']}), "
        f"консультации {stats['c_total']} (сегодня {stats['c_today']})"
    )

    # Подсказка, если уведомления операторам ещё не настроены
    chats = [
        settings.admin_chat_default_id, settings.admin_chat_join_id,
        settings.admin_chat_job_id, settings.admin_chat_psy_id,
        settings.admin_chat_law_id, settings.admin_chat_other_id,
    ]
    if not any(c is not None for c in chats):
        print()
        print("ВНИМАНИЕ: ни один ADMIN_CHAT_* не задан в .env — уведомления")
        print("операторам не отправляются, заявки только пишутся в БД.")
        print("Добавьте бота в чат: он сам пришлёт туда ID для .env.")
    if not settings.admin_user_ids:
        print()
        print("ВНИМАНИЕ: ADMIN_USER_IDS пуст — команды /stats и /export недоступны.")
        print("Узнать свой ID: отправьте боту /whoami")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Показать заявки из БД")
    p.add_argument("--limit", type=int, default=None, help="последние N записей")
    asyncio.run(main(p.parse_args().limit))
