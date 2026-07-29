"""Сборка inline-клавиатур."""

from __future__ import annotations

from maxapi.enums.intent import Intent
from maxapi.types.attachments.buttons import (
    CallbackButton,
    LinkButton,
    RequestContactButton,
)
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from app import texts

# --- payload-константы ---
P_MENU_JOIN = "menu:join"
P_MENU_CONSULT = "menu:consult"
P_CONSENT_YES = "consent:yes"
P_CONSENT_NO = "consent:no"
P_BACK = "common:back"
P_CANCEL = "common:cancel"
P_MENU = "common:menu"
P_SVO_YES = "svo:yes"
P_SVO_NO = "svo:no"
P_JOIN_SUBMIT = "join:submit"
P_JOIN_RESTART = "join:restart"
P_JOIN_FORCE = "join:force"
P_CONSULT_SUBMIT = "consult:submit"
P_CONSULT_RESTART = "consult:restart"
P_CONSULT_FORCE = "consult:force"
P_ADMIN_TAKE = "admin:take:"
P_ADMIN_DONE = "admin:done:"

CONSULT_DIRECTION_PAYLOAD = {
    "job": "consult:job",
    "psy": "consult:psy",
    "law": "consult:law",
    "other": "consult:other",
}


def _markup(builder: InlineKeyboardBuilder):
    return [builder.as_markup()]


def main_menu():
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text=texts.BTN_JOIN, payload=P_MENU_JOIN))
    kb.row(CallbackButton(text=texts.BTN_CONSULT, payload=P_MENU_CONSULT))
    return _markup(kb)


def consent(policy_url: str | None):
    kb = InlineKeyboardBuilder()
    kb.row(
        CallbackButton(
            text=texts.BTN_CONSENT_YES, payload=P_CONSENT_YES, intent=Intent.POSITIVE
        )
    )
    if policy_url:
        kb.row(LinkButton(text=texts.BTN_CONSENT_MORE, url=policy_url))
    kb.row(
        CallbackButton(
            text=texts.BTN_CONSENT_NO, payload=P_CONSENT_NO, intent=Intent.NEGATIVE
        )
    )
    return _markup(kb)


def _nav_row(kb: InlineKeyboardBuilder, *, back: bool = True) -> None:
    if back:
        kb.row(CallbackButton(text=texts.BTN_BACK, payload=P_BACK))
    kb.row(CallbackButton(text=texts.BTN_CANCEL, payload=P_CANCEL, intent=Intent.NEGATIVE))


def text_step(*, back: bool = True):
    """Клавиатура шага с текстовым вводом: Назад / Отмена."""
    kb = InlineKeyboardBuilder()
    _nav_row(kb, back=back)
    return _markup(kb)


def phone_step(*, back: bool = True):
    """Шаг телефона: Поделиться контактом + Назад / Отмена."""
    kb = InlineKeyboardBuilder()
    kb.row(RequestContactButton(text=texts.BTN_SHARE_CONTACT))
    _nav_row(kb, back=back)
    return _markup(kb)


def svo_step():
    kb = InlineKeyboardBuilder()
    kb.row(
        CallbackButton(text=texts.BTN_YES, payload=P_SVO_YES),
        CallbackButton(text=texts.BTN_NO, payload=P_SVO_NO),
    )
    _nav_row(kb, back=True)
    return _markup(kb)


def consult_directions():
    kb = InlineKeyboardBuilder()
    for key in ("job", "psy", "law", "other"):
        kb.row(
            CallbackButton(
                text=texts.DIRECTION_TITLES[key],
                payload=CONSULT_DIRECTION_PAYLOAD[key],
            )
        )
    _nav_row(kb, back=False)
    return _markup(kb)


def join_confirm():
    kb = InlineKeyboardBuilder()
    kb.row(
        CallbackButton(text=texts.BTN_SUBMIT, payload=P_JOIN_SUBMIT, intent=Intent.POSITIVE)
    )
    kb.row(CallbackButton(text=texts.BTN_RESTART, payload=P_JOIN_RESTART))
    kb.row(CallbackButton(text=texts.BTN_CANCEL, payload=P_CANCEL, intent=Intent.NEGATIVE))
    return _markup(kb)


def consult_confirm():
    kb = InlineKeyboardBuilder()
    kb.row(
        CallbackButton(text=texts.BTN_SUBMIT, payload=P_CONSULT_SUBMIT, intent=Intent.POSITIVE)
    )
    kb.row(CallbackButton(text=texts.BTN_RESTART, payload=P_CONSULT_RESTART))
    kb.row(CallbackButton(text=texts.BTN_CANCEL, payload=P_CANCEL, intent=Intent.NEGATIVE))
    return _markup(kb)


def to_menu():
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text=texts.BTN_TO_MENU, payload=P_MENU))
    return _markup(kb)


def duplicate(force_payload: str):
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text=texts.BTN_FORCE_NEW, payload=force_payload))
    kb.row(CallbackButton(text=texts.BTN_TO_MENU, payload=P_MENU))
    return _markup(kb)


def contact_operator(operator_url: str | None):
    kb = InlineKeyboardBuilder()
    if operator_url:
        kb.row(LinkButton(text=texts.BTN_CONTACT_OPERATOR, url=operator_url))
    kb.row(CallbackButton(text=texts.BTN_TO_MENU, payload=P_MENU))
    return _markup(kb)


def operator_actions(ticket: str):
    kb = InlineKeyboardBuilder()
    kb.row(
        CallbackButton(text=texts.BTN_TAKE, payload=f"{P_ADMIN_TAKE}{ticket}"),
        CallbackButton(text=texts.BTN_MARK_DONE, payload=f"{P_ADMIN_DONE}{ticket}"),
    )
    return _markup(kb)
