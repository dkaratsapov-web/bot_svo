"""Общие фикстуры тестов."""

import pytest_asyncio

from app.db import session as db


@pytest_asyncio.fixture
async def sessionmaker(tmp_path):
    """Инициализирует изолированную SQLite-БД на время теста."""
    url = f"sqlite+aiosqlite:///{tmp_path/'test.db'}"
    db.init_engine(url)
    await db.create_all()
    try:
        yield db.get_sessionmaker()
    finally:
        await db.dispose_engine()
