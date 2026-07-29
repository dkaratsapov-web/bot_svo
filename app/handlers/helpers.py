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


SCREEN_KEY = "screen_mid"


def _bot(event: Any):
    return getattr(event, "bot", None)


def _mid_of(sent: Any) -> str | None:
    """Достаёт message_id из результата send_message."""
    message = getattr(sent, "message", None)
    body = getattr(message, "body", None)
    return getattr(body, "mid", None)


async def _send_new_screen(event: Any, context, text: str, attachments) -> None:
    """Отправляет новое сообщение-экран и запоминает его id."""
    sent = None
    if isinstance(event, MessageCreated):
        sent = await event.message.answer(text, attachments=attachments)
    else:
        bot = _bot(event)
        if bot is None:
            return
        chat_id, user_id = event.get_ids()
        sent = await bot.send_message(
            chat_id=chat_id, user_id=user_id, text=text, attachments=attachments
        )

    mid = _mid_of(sent)
    if mid:
        await context.update_data(**{SCREEN_KEY: mid})


async def render(event: Any, context, text: str, attachments=None) -> None:
    """Показывает шаг сценария, обновляя одно и то же сообщение-«экран».

    Вместо нового сообщения на каждом шаге правим предыдущее: диалог
    остаётся коротким. Id экрана храним в FSM, поэтому обновление работает
    и когда пользователь отвечает текстом (тогда callback'а нет).

    Если отредактировать не удалось (сообщение удалено, слишком старое,
    ошибка API) — отправляем новое, чтобы сценарий не встал.
    """
    data = await context.get_data()
    screen_mid = data.get(SCREEN_KEY)
    bot = _bot(event)

    # Быстрый путь: кнопка нажата на самом экране. Один вызов и подтверждает
    # callback (иначе у пользователя виснет индикатор), и правит сообщение.
    # Важно: только если это действительно текущий экран. Иначе (нажатие в
    # старом сообщении) мы бы отредактировали устаревшее сообщение и «увели»
    # экран назад по истории диалога.
    if (
        isinstance(event, MessageCallback)
        and event.message is not None
        and event.message.body is not None
    ):
        clicked_mid = event.message.body.mid
        if screen_mid is None or screen_mid == clicked_mid:
            try:
                await event.edit(text=text, attachments=attachments)
                if clicked_mid:
                    await context.update_data(**{SCREEN_KEY: clicked_mid})
                return
            except Exception:  # noqa: BLE001
                pass  # ниже попробуем обычное редактирование

    if screen_mid and bot is not None:
        try:
            await bot.edit_message(
                message_id=screen_mid, text=text, attachments=attachments
            )
            await ack(event)  # для callback: снять индикатор загрузки
            return
        except Exception:  # noqa: BLE001
            pass  # экран потерян (удалён/слишком старый) — отправим новый

    await ack(event)
    await _send_new_screen(event, context, text, attachments)


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


async def clear_keeping_screen(context) -> None:
    """Сбрасывает состояние и данные, но сохраняет id сообщения-экрана.

    Обычный clear() стёр бы screen_mid, и следующий шаг ушёл бы новым
    сообщением вместо обновления текущего.
    """
    data = await context.get_data()
    mid = data.get(SCREEN_KEY)
    await context.clear()
    if mid:
        await context.update_data(**{SCREEN_KEY: mid})


async def show_main_menu(event: Any, context=None) -> None:
    """Главное меню. С context обновляет экран, без него отправляет заново."""
    if context is None:
        await send(event, texts.MAIN_MENU, keyboards.main_menu())
    else:
        await render(event, context, texts.MAIN_MENU, keyboards.main_menu())


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
