"""Общие команды и глобальная навигация: /start, /menu, /help, /cancel."""

from __future__ import annotations

from maxapi import Router
from maxapi.context import BaseContext
from maxapi.filters import StateFilter
from maxapi.filters.command import Command, CommandStart

from app import keyboards, texts
from app.config import get_settings
from app.handlers import helpers
from app.handlers.helpers import render, send
from app.states import ConsentSG, ConsultSG, JoinSG
from app.utils.filters import Payload

router = Router()
# Роутер-«ловушка» для неопознанных событий — подключается последним.
fallback_router = Router()


# --------------------------------------------------------------------------- #
# Старт / меню
# --------------------------------------------------------------------------- #
@router.message_created(CommandStart())
async def cmd_start(event, context: BaseContext) -> None:
    # /start начинает диалог заново — новый экран здесь уместен
    await context.clear()
    await helpers.ensure_user(event)
    await helpers.show_main_menu(event, context)


@router.bot_started()
async def on_bot_started(event, context: BaseContext) -> None:
    await context.clear()
    await helpers.ensure_user(event)
    await helpers.show_main_menu(event, context)


@router.message_created(Command("menu"))
async def cmd_menu(event, context: BaseContext) -> None:
    await helpers.clear_keeping_screen(context)
    await helpers.show_main_menu(event, context)


@router.message_callback(Payload(keyboards.P_MENU))
async def cb_menu(event, context: BaseContext) -> None:
    await helpers.clear_keeping_screen(context)
    await helpers.show_main_menu(event, context)


# --------------------------------------------------------------------------- #
# Помощь
# --------------------------------------------------------------------------- #
@router.message_created(Command("help"))
async def cmd_help(event, context: BaseContext) -> None:
    s = get_settings()
    await send(event, texts.HELP.format(phone=s.org_phone or "—", email=s.org_email or "—"))


# --------------------------------------------------------------------------- #
# Отмена
# --------------------------------------------------------------------------- #
@router.message_created(Command("cancel"))
async def cmd_cancel(event, context: BaseContext) -> None:
    await helpers.clear_keeping_screen(context)
    await render(event, context, texts.CANCELLED, keyboards.main_menu())


@router.message_callback(Payload(keyboards.P_CANCEL))
async def cb_cancel(event, context: BaseContext) -> None:
    await helpers.clear_keeping_screen(context)
    await render(event, context, texts.CANCELLED, keyboards.main_menu())


# --------------------------------------------------------------------------- #
# Fallback-роутер (последний): устаревшие кнопки и текст вне шага
# --------------------------------------------------------------------------- #
async def _rerender_current(event, context: BaseContext) -> bool:
    """Повторно показывает актуальный шаг сценария. True — если удалось."""
    from app.handlers import consult, join
    from app.handlers.consent import request_consent

    state = str(await context.get_state() or "")
    join_map = {
        str(JoinSG.fio): join.ask_fio,
        str(JoinSG.phone): join.ask_phone,
        str(JoinSG.city): join.ask_city,
        str(JoinSG.svo): join.ask_svo,
        str(JoinSG.confirm): join.show_confirm,
    }
    consult_map = {
        str(ConsultSG.direction): consult.ask_direction,
        str(ConsultSG.fio): consult.ask_fio,
        str(ConsultSG.phone): consult.ask_phone,
        str(ConsultSG.free_text): consult.ask_free_text,
        str(ConsultSG.confirm): consult.show_confirm,
    }
    if state in join_map:
        await join_map[state](event, context)
        return True
    if state in consult_map:
        await consult_map[state](event, context)
        return True
    if state == str(ConsentSG.wait):
        data = await context.get_data()
        await request_consent(
            event, context, data.get("pending_flow", "join"), data.get("pending_direction")
        )
        return True
    return False


@fallback_router.message_callback()
async def stale_callback(event, context: BaseContext) -> None:
    """Нажата устаревшая кнопка (payload не совпал с текущим состоянием)."""
    if not await _rerender_current(event, context):
        await helpers.show_main_menu(event, context)


@fallback_router.message_created(StateFilter(None))
async def free_text_no_state(event, context: BaseContext) -> None:
    """Произвольный текст вне активного сценария → главное меню."""
    await render(event, context, texts.USE_BUTTONS + "\n\n" + texts.MAIN_MENU, keyboards.main_menu())


@fallback_router.message_created()
async def free_text_in_state(event, context: BaseContext) -> None:
    """Произвольный текст на шаге без специального обработчика.

    Повторно показываем актуальный шаг на том же экране — отдельное
    сообщение «воспользуйтесь кнопками» только засоряло бы диалог.
    """
    if not await _rerender_current(event, context):
        await render(event, context, texts.USE_BUTTONS + "\n\n" + texts.MAIN_MENU, keyboards.main_menu())
