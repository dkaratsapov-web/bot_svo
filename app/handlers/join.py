"""Сценарий 1 — вступление в Ассоциацию."""

from __future__ import annotations

from maxapi import Router
from maxapi.context import BaseContext
from maxapi.filters import Contact, StateFilter

from app import keyboards, texts
from app.config import get_settings
from app.db import repo
from app.db.models import ApplicationStatus
from app.db.session import session_scope
from app.handlers import helpers
from app.handlers.helpers import render
from app.logging_setup import get_logger
from app.runtime import runtime
from app.services import applications
from app.states import JoinSG
from app.utils import validators
from app.utils.filters import Payload

router = Router()
log = get_logger("join")

MAX_ERRORS = 3


# --------------------------------------------------------------------------- #
# Шаги
# --------------------------------------------------------------------------- #
async def ask_fio(event, context: BaseContext) -> None:
    await context.set_state(JoinSG.fio)
    await context.update_data(flow="join")
    await render(event, context, texts.ASK_FIO, keyboards.text_step(back=True))


async def ask_phone(event, context: BaseContext) -> None:
    await context.set_state(JoinSG.phone)
    await render(event, context, texts.ASK_PHONE, keyboards.phone_step(back=True))


async def ask_city(event, context: BaseContext) -> None:
    await context.set_state(JoinSG.city)
    await render(event, context, texts.ASK_CITY, keyboards.text_step(back=True))


async def ask_svo(event, context: BaseContext) -> None:
    await context.set_state(JoinSG.svo)
    await render(event, context, texts.ASK_SVO, keyboards.svo_step())


async def show_confirm(event, context: BaseContext) -> None:
    await context.set_state(JoinSG.confirm)
    data = await context.get_data()
    text = texts.JOIN_CONFIRM.format(
        fio=data.get("fio", "—"),
        phone=data.get("phone", "—"),
        city=data.get("city", "—"),
        svo=texts.yes_no(data.get("svo")),
    )
    await render(event, context, text, keyboards.join_confirm())


# --------------------------------------------------------------------------- #
# Вход в сценарий
# --------------------------------------------------------------------------- #
@router.message_callback(Payload(keyboards.P_MENU_JOIN))
async def start(event, context: BaseContext) -> None:
    await context.clear()
    _, has_consent, _ = await helpers.ensure_user(event)
    if has_consent:
        await ask_fio(event, context)
    else:
        from app.handlers.consent import request_consent

        await request_consent(event, context, flow="join")


# --------------------------------------------------------------------------- #
# Ввод ФИО
# --------------------------------------------------------------------------- #
@router.message_created(StateFilter(JoinSG.fio))
async def input_fio(event, context: BaseContext) -> None:
    res = validators.validate_fio(event.message.body.text or "")
    if not res.ok:
        await _handle_invalid(event, context, "fio", texts.ERR_FIO, keyboards.text_step(back=True))
        return
    await helpers.reset_error(context, "fio")
    await context.update_data(fio=res.value)
    await ask_phone(event, context)


# --------------------------------------------------------------------------- #
# Телефон (контакт или текст)
# --------------------------------------------------------------------------- #
@router.message_created(StateFilter(JoinSG.phone), Contact())
async def input_phone_contact(event, context: BaseContext, contact) -> None:
    phone_raw = None
    payload = getattr(contact, "payload", None)
    if payload is not None:
        phone_raw = payload.vcf.phone
    res = validators.validate_phone(phone_raw or "")
    phone = res.value if res.ok else (phone_raw or "")
    await helpers.reset_error(context, "phone")
    await context.update_data(phone=phone, phone_verified=True)
    await ask_city(event, context)


@router.message_created(StateFilter(JoinSG.phone))
async def input_phone_text(event, context: BaseContext) -> None:
    res = validators.validate_phone(event.message.body.text or "")
    if not res.ok:
        await _handle_invalid(event, context, "phone", texts.ERR_PHONE, keyboards.phone_step(back=True))
        return
    await helpers.reset_error(context, "phone")
    await context.update_data(phone=res.value, phone_verified=False)
    await ask_city(event, context)


# --------------------------------------------------------------------------- #
# Населённый пункт
# --------------------------------------------------------------------------- #
@router.message_created(StateFilter(JoinSG.city))
async def input_city(event, context: BaseContext) -> None:
    res = validators.validate_city(event.message.body.text or "")
    if not res.ok:
        await _handle_invalid(event, context, "city", texts.ERR_CITY, keyboards.text_step(back=True))
        return
    await helpers.reset_error(context, "city")
    await context.update_data(city=res.value)
    await ask_svo(event, context)


# --------------------------------------------------------------------------- #
# Участие в СВО
# --------------------------------------------------------------------------- #
@router.message_callback(Payload(keyboards.P_SVO_YES), StateFilter(JoinSG.svo))
async def svo_yes(event, context: BaseContext) -> None:
    await context.update_data(svo=True)
    await show_confirm(event, context)


@router.message_callback(Payload(keyboards.P_SVO_NO), StateFilter(JoinSG.svo))
async def svo_no(event, context: BaseContext) -> None:
    await context.update_data(svo=False)
    await show_confirm(event, context)


# --------------------------------------------------------------------------- #
# Назад
# --------------------------------------------------------------------------- #
@router.message_callback(Payload(keyboards.P_BACK), StateFilter(JoinSG))
async def go_back(event, context: BaseContext) -> None:
    state = await context.get_state()
    state = str(state) if state else ""
    steps = {
        str(JoinSG.fio): helpers.show_main_menu,  # с первого шага — в меню
        str(JoinSG.phone): ask_fio,
        str(JoinSG.city): ask_phone,
        str(JoinSG.svo): ask_city,
        str(JoinSG.confirm): ask_svo,
    }
    handler = steps.get(state, helpers.show_main_menu)
    if handler is helpers.show_main_menu:
        await helpers.clear_keeping_screen(context)
    await handler(event, context)


# --------------------------------------------------------------------------- #
# Подтверждение / отправка
# --------------------------------------------------------------------------- #
@router.message_callback(Payload(keyboards.P_JOIN_RESTART), StateFilter(JoinSG))
async def restart(event, context: BaseContext) -> None:
    # Сбрасываем данные анкеты (согласие уже дано), но сохраняем экран.
    await helpers.clear_keeping_screen(context)
    await ask_fio(event, context)


@router.message_callback(Payload(keyboards.P_JOIN_SUBMIT), StateFilter(JoinSG.confirm))
async def submit(event, context: BaseContext) -> None:
    await _do_submit(event, context, force=False)


@router.message_callback(Payload(keyboards.P_JOIN_FORCE), StateFilter(JoinSG.confirm))
async def submit_force(event, context: BaseContext) -> None:
    await _do_submit(event, context, force=True)


async def _do_submit(event, context: BaseContext, *, force: bool) -> None:
    data = await context.get_data()
    settings = get_settings()
    max_user_id = helpers.user_meta(event)[0]

    async with session_scope() as session:
        user = await repo.get_or_create_user(session, max_user_id)
        result = await applications.submit_join(
            session,
            user,
            fio=data.get("fio", ""),
            phone=data.get("phone", ""),
            phone_verified=bool(data.get("phone_verified", False)),
            city=data.get("city"),
            is_svo_participant=data.get("svo"),
            window_hours=settings.duplicate_window_hours,
            force=force,
        )

    if result.duplicate and result.application is not None:
        await render(
            event,
            context,
            texts.DUPLICATE.format(ticket=result.application.ticket),
            keyboards.duplicate(keyboards.P_JOIN_FORCE),
        )
        return

    app = result.application
    # Рендерим до clear(): иначе id экрана пропадёт и финал уедет новым сообщением
    await render(
        event,
        context,
        texts.JOIN_DONE.format(ticket=app.ticket, sla=settings.response_sla_days),
        keyboards.to_menu(),
    )
    await context.clear()
    try:
        await runtime.notifier.notify(app)
    except Exception as exc:  # noqa: BLE001
        log.error("notify_failed", ticket=app.ticket, error=str(exc))


# --------------------------------------------------------------------------- #
# Фолбэк: текст на шаге с кнопками
# --------------------------------------------------------------------------- #
@router.message_created(StateFilter(JoinSG.svo))
async def svo_text_fallback(event, context: BaseContext) -> None:
    await render(event, context, texts.USE_BUTTONS + "\n\n" + texts.ASK_SVO, keyboards.svo_step())


@router.message_created(StateFilter(JoinSG.confirm))
async def confirm_text_fallback(event, context: BaseContext) -> None:
    await render(event, context, texts.USE_BUTTONS, keyboards.join_confirm())


# --------------------------------------------------------------------------- #
# Обработка неверного ввода + 3 попытки
# --------------------------------------------------------------------------- #
async def _handle_invalid(event, context: BaseContext, field: str, err_text: str, kb) -> None:
    count = await helpers.bump_error(context, field)
    if count >= MAX_ERRORS:
        await _save_draft(context, event)
        await render(event, context, texts.TOO_MANY_ERRORS, keyboards.contact_operator(runtime.operator_url()))
        return
    await render(event, context, err_text, kb)


async def _save_draft(context: BaseContext, event) -> None:
    """Сохраняет черновик заявки (status=draft) при трёх ошибках подряд."""
    data = await context.get_data()
    max_user_id = helpers.user_meta(event)[0]
    async with session_scope() as session:
        user = await repo.get_or_create_user(session, max_user_id)
        await repo.create_application(
            session,
            user,
            fio=data.get("fio", ""),
            phone=data.get("phone", ""),
            phone_verified=bool(data.get("phone_verified", False)),
            city=data.get("city"),
            is_svo_participant=data.get("svo"),
            status=ApplicationStatus.draft,
        )
        await repo.add_event(session, type="join_draft_saved", user_id=user.id)
    await helpers.clear_keeping_screen(context)
