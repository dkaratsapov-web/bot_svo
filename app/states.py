"""FSM-состояния сценариев."""

from __future__ import annotations

from maxapi.context import State, StatesGroup


class ConsentSG(StatesGroup):
    """Ожидание согласия на обработку ПДн."""

    wait = State()


class JoinSG(StatesGroup):
    """Сценарий 1 — вступление в Ассоциацию."""

    fio = State()
    phone = State()
    city = State()
    svo = State()
    confirm = State()


class ConsultSG(StatesGroup):
    """Сценарий 2 — консультация."""

    direction = State()
    fio = State()
    phone = State()
    free_text = State()  # используется только при ASK_FREE_TEXT_FOR_OTHER=true
    confirm = State()
