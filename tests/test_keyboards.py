"""Тесты сборки inline-клавиатур."""

from maxapi.enums.button_type import ButtonType

from app import keyboards


def _rows(markup):
    return markup[0].payload.buttons


def _texts(markup):
    return [btn.text for row in _rows(markup) for btn in row]


def _payloads(markup):
    return [getattr(btn, "payload", None) for row in _rows(markup) for btn in row]


def test_main_menu_order_and_count():
    kb = keyboards.main_menu()
    rows = _rows(kb)
    # Ровно две кнопки, по одной в ряд, «Вступить» — первая
    assert len(rows) == 2
    assert len(rows[0]) == 1 and len(rows[1]) == 1
    assert _payloads(kb) == [keyboards.P_MENU_JOIN, keyboards.P_MENU_CONSULT]


def test_consent_has_link_when_url_given():
    kb = keyboards.consent("https://example.ru/policy")
    types = [btn.type for row in _rows(kb) for btn in row]
    assert ButtonType.LINK in types
    assert keyboards.P_CONSENT_YES in _payloads(kb)
    assert keyboards.P_CONSENT_NO in _payloads(kb)


def test_consent_without_url_has_no_link():
    kb = keyboards.consent("")
    types = [btn.type for row in _rows(kb) for btn in row]
    assert ButtonType.LINK not in types


def test_consult_directions_all_four_in_order():
    kb = keyboards.consult_directions()
    payloads = _payloads(kb)
    assert payloads[:4] == [
        keyboards.CONSULT_DIRECTION_PAYLOAD["job"],
        keyboards.CONSULT_DIRECTION_PAYLOAD["psy"],
        keyboards.CONSULT_DIRECTION_PAYLOAD["law"],
        keyboards.CONSULT_DIRECTION_PAYLOAD["other"],
    ]


def test_phone_step_has_request_contact():
    kb = keyboards.phone_step()
    types = [btn.type for row in _rows(kb) for btn in row]
    assert ButtonType.REQUEST_CONTACT in types


def test_operator_actions_carry_ticket():
    kb = keyboards.operator_actions("ASV-2026-000042")
    payloads = _payloads(kb)
    assert f"{keyboards.P_ADMIN_TAKE}ASV-2026-000042" in payloads
    assert f"{keyboards.P_ADMIN_DONE}ASV-2026-000042" in payloads


def test_join_confirm_buttons():
    kb = keyboards.join_confirm()
    payloads = _payloads(kb)
    assert keyboards.P_JOIN_SUBMIT in payloads
    assert keyboards.P_JOIN_RESTART in payloads
    assert keyboards.P_CANCEL in payloads


def test_consult_confirm_buttons():
    payloads = _payloads(keyboards.consult_confirm())
    assert keyboards.P_CONSULT_SUBMIT in payloads
    assert keyboards.P_CONSULT_RESTART in payloads
    assert keyboards.P_CANCEL in payloads


def test_text_step_with_and_without_back():
    with_back = _payloads(keyboards.text_step(back=True))
    assert keyboards.P_BACK in with_back
    assert keyboards.P_CANCEL in with_back
    no_back = _payloads(keyboards.text_step(back=False))
    assert keyboards.P_BACK not in no_back
    assert keyboards.P_CANCEL in no_back


def test_svo_step_has_yes_no_and_nav():
    payloads = _payloads(keyboards.svo_step())
    assert keyboards.P_SVO_YES in payloads
    assert keyboards.P_SVO_NO in payloads
    assert keyboards.P_BACK in payloads
    assert keyboards.P_CANCEL in payloads


def test_to_menu_single_button():
    kb = keyboards.to_menu()
    assert _payloads(kb) == [keyboards.P_MENU]


def test_duplicate_keyboard_carries_force_payload():
    payloads = _payloads(keyboards.duplicate(keyboards.P_JOIN_FORCE))
    assert keyboards.P_JOIN_FORCE in payloads
    assert keyboards.P_MENU in payloads


def test_contact_operator_with_and_without_url():
    types = [b.type for row in _rows(keyboards.contact_operator("https://t.me/x")) for b in row]
    assert ButtonType.LINK in types
    # Без URL — только кнопка «В меню»
    assert _payloads(keyboards.contact_operator("")) == [keyboards.P_MENU]
