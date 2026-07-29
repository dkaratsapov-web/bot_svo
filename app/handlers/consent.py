"""Согласие на обработку персональных данных (152-ФЗ)."""

from __future__ import annotations

from maxapi import Router
from maxapi.context import BaseContext
from maxapi.filters import StateFilter

from app import keyboards, texts
from app.config import get_settings
from app.db import repo
from app.db.session import session_scope
from app.handlers import helpers
from app.handlers.helpers import render
from app.states import ConsentSG
from app.utils.filters import Payload

router = Router()


async def request_consent(event, context: BaseContext, flow: str, direction: str | None = None) -> None:
    """Показывает экран согласия и сохраняет отложенный сценарий."""
    settings = get_settings()
    await context.set_state(ConsentSG.wait)
    await context.update_data(pending_flow=flow, pending_direction=direction)
    await render(event, context, texts.CONSENT, keyboards.consent(settings.privacy_policy_url))


async def _resume_pending(event, context: BaseContext) -> None:
    """Продолжает отложенный сценарий после получения согласия."""
    data = await context.get_data()
    flow = data.get("pending_flow")
    direction = data.get("pending_direction")

    # Импортируем здесь, чтобы избежать циклических импортов.
    from app.handlers import consult, join

    if flow == "join":
        await join.ask_fio(event, context)
    elif flow == "consult":
        await consult.start_after_direction(event, context, direction)
    else:
        await helpers.show_main_menu(event, context)


@router.message_callback(Payload(keyboards.P_CONSENT_YES))
async def consent_yes(event, context: BaseContext) -> None:
    max_user_id = helpers.user_meta(event)[0]
    settings = get_settings()
    async with session_scope() as session:
        user = await repo.get_or_create_user(session, max_user_id)
        if not user.has_consent:
            await repo.set_consent(session, user, settings.consent_version)
            await repo.add_event(
                session,
                type="consent_given",
                user_id=user.id,
                payload={"version": settings.consent_version},
            )
    await _resume_pending(event, context)


@router.message_callback(Payload(keyboards.P_CONSENT_NO))
async def consent_no(event, context: BaseContext) -> None:
    await helpers.clear_keeping_screen(context)
    await render(event, context, texts.CONSENT_DECLINED, keyboards.main_menu())


@router.message_created(StateFilter(ConsentSG.wait))
async def consent_text_fallback(event, context: BaseContext) -> None:
    """Пользователь пишет текст вместо нажатия кнопки согласия."""
    settings = get_settings()
    await render(event, context, texts.USE_BUTTONS + "\n\n" + texts.CONSENT, keyboards.consent(settings.privacy_policy_url))
