"""Общие примитивы для handler'ов: отправка, ack, работа с пользователем."""

from __future__ import annotations

from typing import Any

from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated

from app import keyboards, texts
from app.db import repo
from app.db.session import session_scope


async def ack(event: Any, notification: str | None = None) -> None:
    """Подтверждает callback (обязательно, иначе у пользователя виснет спиннер)."""
    if isinstance(event, MessageCallback):
        try:
            await event.ack(notification)
        except Exception:  # noqa: BLE001
            pass


async def send(event: Any, text: str, attachments=None) -> None:
    """Единая отправка ответа: для callback сперва ack, затем новое сообщение."""
    if isinstance(event, MessageCallback):
        await ack(event)
        if event.message is not None:
            await event.message.answer(text, attachments=attachments)
        elif event.bot is not None:
            chat_id, user_id = event.get_ids()
            await event.bot.send_message(
                chat_id=chat_id, user_id=user_id, text=text, attachments=attachments
            )
    elif isinstance(event, MessageCreated):
        await event.message.answer(text, attachments=attachments)


def user_meta(event: Any) -> tuple[int, int | None, str | None, str | None]:
    """(max_user_id, chat_id, username, display_name) из любого события."""
    if isinstance(event, MessageCreated):
        chat_id, user_id = event.get_ids()
        sender = event.message.sender
        username = sender.username if sender else None
        display = None
        if sender:
            display = " ".join(p for p in (sender.first_name, sender.last_name) if p)
        return int(user_id), chat_id, username, display or None
    if isinstance(event, MessageCallback):
        chat_id, user_id = event.get_ids()
        u = event.callback.user
        display = " ".join(p for p in (u.first_name, u.last_name) if p)
        return int(user_id), chat_id, u.username, display or None
    # bot_started
    return int(event.user.user_id), getattr(event, "chat_id", None), event.user.username, (
        " ".join(p for p in (event.user.first_name, event.user.last_name) if p) or None
    )


async def ensure_user(event: Any):
    """Создаёт/обновляет пользователя, возвращает (user_orm_id, has_consent, max_user_id)."""
    max_user_id, chat_id, username, display = user_meta(event)
    async with session_scope() as session:
        user = await repo.get_or_create_user(
            session, max_user_id, chat_id=chat_id, username=username, display_name=display
        )
        return user.id, user.has_consent, max_user_id


async def show_main_menu(event: Any) -> None:
    await send(event, texts.MAIN_MENU, keyboards.main_menu())


# --- Работа со счётчиком ошибок ввода (3 попытки) ---
async def bump_error(context, field: str) -> int:
    data = await context.get_data()
    key = f"err_{field}"
    count = int(data.get(key, 0)) + 1
    await context.update_data(**{key: count})
    return count


async def reset_error(context, field: str) -> None:
    data = await context.get_data()
    key = f"err_{field}"
    if data.get(key):
        await context.update_data(**{key: 0})
