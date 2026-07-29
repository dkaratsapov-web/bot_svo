"""Сценарий 2 — консультация."""

from __future__ import annotations

from maxapi import Router
from maxapi.context import BaseContext
from maxapi.filters import Contact, StateFilter

from app import keyboards, texts
from app.config import get_settings
from app.db import repo
from app.db.models import ApplicationStatus, Direction
from app.db.session import session_scope
from app.handlers import helpers
from app.handlers.helpers import send
from app.logging_setup import get_logger
from app.runtime import runtime
from app.services import applications
from app.states import ConsultSG
from app.utils import validators
from app.utils.filters import Payload

router = Router()
log = get_logger("consult")

MAX_ERRORS = 3

_PAYLOAD_TO_DIRECTION = {v: k for k, v in keyboards.CONSULT_DIRECTION_PAYLOAD.items()}


# --------------------------------------------------------------------------- #
# Шаги
# --------------------------------------------------------------------------- #
async def ask_direction(event, context: BaseContext) -> None:
    await context.set_state(ConsultSG.direction)
    await context.update_data(flow="consult")
    await send(event, texts.CONSULT_CHOOSE_DIRECTION, keyboards.consult_directions())


async def ask_fio(event, context: BaseContext) -> None:
    await context.set_state(ConsultSG.fio)
    await send(event, texts.ASK_FIO, keyboards.text_step(back=True))


async def ask_phone(event, context: BaseContext) -> None:
    await context.set_state(ConsultSG.phone)
    await send(event, texts.ASK_PHONE, keyboards.phone_step(back=True))


async def ask_free_text(event, context: BaseContext) -> None:
    await context.set_state(ConsultSG.free_text)
    await send(event, texts.ASK_FREE_TEXT, keyboards.text_step(back=True))


async def show_confirm(event, context: BaseContext) -> None:
    await context.set_state(ConsultSG.confirm)
    data = await context.get_data()
    direction = data.get("direction", "other")
    text = texts.CONSULT_CONFIRM.format(
        direction=texts.DIRECTION_TITLES.get(direction, direction),
        fio=data.get("fio", "—"),
        phone=data.get("phone", "—"),
    )
    await send(event, text, keyboards.consult_confirm())


# --------------------------------------------------------------------------- #
# Вход в сценарий
# --------------------------------------------------------------------------- #
@router.message_callback(Payload(keyboards.P_MENU_CONSULT))
async def start(event, context: BaseContext) -> None:
    await context.clear()
    await ask_direction(event, context)


@router.message_callback(Payload("consult:", prefix=True), StateFilter(ConsultSG.direction))
async def choose_direction(event, context: BaseContext, suffix: str) -> None:
    direction = suffix  # job|psy|law|other
    if direction not in _PAYLOAD_TO_DIRECTION.values() and direction not in Direction.__members__:
        # Неизвестное направление — переспрашиваем
        await send(event, texts.STALE_BUTTON, keyboards.consult_directions())
        return
    await context.update_data(direction=direction)
    _, has_consent, _ = await helpers.ensure_user(event)
    if has_consent:
        await start_after_direction(event, context, direction)
    else:
        from app.handlers.consent import request_consent

        await request_consent(event, context, flow="consult", direction=direction)


async def start_after_direction(event, context: BaseContext, direction: str | None) -> None:
    """Продолжение после выбора направления и согласия — спрашиваем ФИО."""
    if direction:
        await context.update_data(direction=direction)
    await ask_fio(event, context)


# --------------------------------------------------------------------------- #
# ФИО
# --------------------------------------------------------------------------- #
@router.message_created(StateFilter(ConsultSG.fio))
async def input_fio(event, context: BaseContext) -> None:
    res = validators.validate_fio(event.message.body.text or "")
    if not res.ok:
        await _handle_invalid(event, context, "fio", texts.ERR_FIO, keyboards.text_step(back=True))
        return
    await helpers.reset_error(context, "fio")
    await context.update_data(fio=res.value)
    await ask_phone(event, context)


# --------------------------------------------------------------------------- #
# Телефон
# --------------------------------------------------------------------------- #
@router.message_created(StateFilter(ConsultSG.phone), Contact())
async def input_phone_contact(event, context: BaseContext, contact) -> None:
    phone_raw = None
    payload = getattr(contact, "payload", None)
    if payload is not None:
        phone_raw = payload.vcf.phone
    res = validators.validate_phone(phone_raw or "")
    phone = res.value if res.ok else (phone_raw or "")
    await helpers.reset_error(context, "phone")
    await context.update_data(phone=phone, phone_verified=True)
    await _after_phone(event, context)


@router.message_created(StateFilter(ConsultSG.phone))
async def input_phone_text(event, context: BaseContext) -> None:
    res = validators.validate_phone(event.message.body.text or "")
    if not res.ok:
        await _handle_invalid(event, context, "phone", texts.ERR_PHONE, keyboards.phone_step(back=True))
        return
    await helpers.reset_error(context, "phone")
    await context.update_data(phone=res.value, phone_verified=False)
    await _after_phone(event, context)


async def _after_phone(event, context: BaseContext) -> None:
    settings = get_settings()
    data = await context.get_data()
    if settings.ask_free_text_for_other and data.get("direction") == "other":
        await ask_free_text(event, context)
    else:
        await show_confirm(event, context)


# --------------------------------------------------------------------------- #
# Свободный текст (feature-flag)
# --------------------------------------------------------------------------- #
@router.message_created(StateFilter(ConsultSG.free_text))
async def input_free_text(event, context: BaseContext) -> None:
    text = (event.message.body.text or "").strip()
    if not text:
        await send(event, texts.ASK_FREE_TEXT, keyboards.text_step(back=True))
        return
    await context.update_data(free_text=text[:2000])
    await show_confirm(event, context)


# --------------------------------------------------------------------------- #
# Назад
# --------------------------------------------------------------------------- #
@router.message_callback(Payload(keyboards.P_BACK), StateFilter(ConsultSG))
async def go_back(event, context: BaseContext) -> None:
    settings = get_settings()
    state = str(await context.get_state() or "")
    data = await context.get_data()
    is_free = settings.ask_free_text_for_other and data.get("direction") == "other"

    if state == str(ConsultSG.fio):
        await ask_direction(event, context)
    elif state == str(ConsultSG.phone):
        await ask_fio(event, context)
    elif state == str(ConsultSG.free_text):
        await ask_phone(event, context)
    elif state == str(ConsultSG.confirm):
        await (ask_free_text if is_free else ask_phone)(event, context)
    else:
        await context.clear()
        await helpers.show_main_menu(event)


# --------------------------------------------------------------------------- #
# Подтверждение / отправка
# --------------------------------------------------------------------------- #
@router.message_callback(Payload(keyboards.P_CONSULT_RESTART), StateFilter(ConsultSG))
async def restart(event, context: BaseContext) -> None:
    await context.set_data({})
    await ask_direction(event, context)


@router.message_callback(Payload(keyboards.P_CONSULT_SUBMIT), StateFilter(ConsultSG.confirm))
async def submit(event, context: BaseContext) -> None:
    await _do_submit(event, context, force=False)


@router.message_callback(Payload(keyboards.P_CONSULT_FORCE), StateFilter(ConsultSG.confirm))
async def submit_force(event, context: BaseContext) -> None:
    await _do_submit(event, context, force=True)


async def _do_submit(event, context: BaseContext, *, force: bool) -> None:
    data = await context.get_data()
    settings = get_settings()
    max_user_id = helpers.user_meta(event)[0]
    direction = Direction(data.get("direction", "other"))

    async with session_scope() as session:
        user = await repo.get_or_create_user(session, max_user_id)
        result = await applications.submit_consult(
            session,
            user,
            direction=direction,
            fio=data.get("fio", ""),
            phone=data.get("phone", ""),
            phone_verified=bool(data.get("phone_verified", False)),
            free_text=data.get("free_text"),
            window_hours=settings.duplicate_window_hours,
            force=force,
        )

    if result.duplicate and result.consultation is not None:
        await send(
            event,
            texts.DUPLICATE.format(ticket=result.consultation.ticket),
            keyboards.duplicate(keyboards.P_CONSULT_FORCE),
        )
        return

    con = result.consultation
    await context.clear()
    await send(
        event,
        texts.CONSULT_DONE.format(
            ticket=con.ticket,
            direction=texts.DIRECTION_TITLES[con.direction.value],
        ),
        keyboards.to_menu(),
    )
    try:
        await runtime.notifier.notify(con)
    except Exception as exc:  # noqa: BLE001
        log.error("notify_failed", ticket=con.ticket, error=str(exc))


# --------------------------------------------------------------------------- #
# Фолбэк
# --------------------------------------------------------------------------- #
@router.message_created(StateFilter(ConsultSG.direction))
async def direction_text_fallback(event, context: BaseContext) -> None:
    await send(event, texts.USE_BUTTONS, keyboards.consult_directions())


@router.message_created(StateFilter(ConsultSG.confirm))
async def confirm_text_fallback(event, context: BaseContext) -> None:
    await send(event, texts.USE_BUTTONS, keyboards.consult_confirm())


# --------------------------------------------------------------------------- #
# 3 попытки
# --------------------------------------------------------------------------- #
async def _handle_invalid(event, context: BaseContext, field: str, err_text: str, kb) -> None:
    count = await helpers.bump_error(context, field)
    if count >= MAX_ERRORS:
        await _save_draft(context, event)
        await send(event, texts.TOO_MANY_ERRORS, keyboards.contact_operator(runtime.operator_url()))
        return
    await send(event, err_text, kb)


async def _save_draft(context: BaseContext, event) -> None:
    data = await context.get_data()
    max_user_id = helpers.user_meta(event)[0]
    direction = Direction(data.get("direction", "other"))
    async with session_scope() as session:
        user = await repo.get_or_create_user(session, max_user_id)
        await repo.create_consultation(
            session,
            user,
            direction=direction,
            fio=data.get("fio", ""),
            phone=data.get("phone", ""),
            phone_verified=bool(data.get("phone_verified", False)),
            free_text=data.get("free_text"),
            status=ApplicationStatus.draft,
        )
        await repo.add_event(session, type="consult_draft_saved", user_id=user.id)
    await context.clear()
