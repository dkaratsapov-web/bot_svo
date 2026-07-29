"""Тесты «одного экрана»: шаги сценария правят одно сообщение, а не плодят новые."""

from types import SimpleNamespace

import pytest

from app.handlers import helpers
from app.handlers.helpers import SCREEN_KEY


class FakeContext:
    """Минимальный аналог FSM-контекста maxapi."""

    def __init__(self, data=None):
        self._data = dict(data or {})
        self._state = None

    async def get_data(self):
        return dict(self._data)

    async def set_data(self, data):
        self._data = dict(data)

    async def update_data(self, **kw):
        self._data.update(kw)
        return dict(self._data)

    async def get_state(self):
        return self._state

    async def set_state(self, state=None):
        self._state = state

    async def clear(self):
        self._data = {}
        self._state = None


class FakeBot:
    def __init__(self, *, edit_fails=False):
        self.edit_fails = edit_fails
        self.edited = []
        self.sent = []

    async def edit_message(self, message_id=None, text=None, attachments=None):
        if self.edit_fails:
            raise RuntimeError("message not found")
        self.edited.append((message_id, text))
        return SimpleNamespace()

    async def send_message(self, chat_id=None, user_id=None, text=None, attachments=None):
        self.sent.append(text)
        mid = f"mid-new-{len(self.sent)}"
        return SimpleNamespace(message=SimpleNamespace(body=SimpleNamespace(mid=mid)))


def make_message_created(bot, mid="mid-user"):
    """Событие «пользователь написал текст»."""
    from maxapi.types.updates.message_created import MessageCreated

    event = MessageCreated.model_construct(
        message=SimpleNamespace(
            body=SimpleNamespace(mid=mid, text="Иванов Иван"),
            answer=None,
            recipient=SimpleNamespace(chat_id=1, user_id=2),
        ),
    )
    object.__setattr__(event, "bot", bot)

    async def _answer(text=None, attachments=None):
        bot.sent.append(text)
        return SimpleNamespace(
            message=SimpleNamespace(body=SimpleNamespace(mid=f"mid-new-{len(bot.sent)}"))
        )

    event.message.answer = _answer
    return event


# MessageCallback — pydantic-модель и не даёт присваивать методы, поэтому
# используем подкласс, а журнал вызовов держим отдельно по id экземпляра.
_JOURNAL: dict[int, dict] = {}


def _make_stub_callback_cls():
    from maxapi.types.updates.message_callback import MessageCallback

    class StubCallback(MessageCallback):
        async def edit(self, text=None, attachments=None, **kwargs):
            journal = _JOURNAL[id(self)]
            if journal["edit_fails"]:
                raise RuntimeError("cannot edit")
            journal["edit"].append(text)

        async def ack(self, notification=None):
            _JOURNAL[id(self)]["ack"] += 1

        def get_ids(self):
            return (1, 2)

    return StubCallback


def make_callback(bot, clicked_mid="mid-screen", edit_fails=False):
    """Событие «нажата кнопка» с фиксацией вызовов edit()/ack()."""
    cls = _make_stub_callback_cls()
    event = cls.model_construct(
        message=SimpleNamespace(body=SimpleNamespace(mid=clicked_mid)),
        callback=SimpleNamespace(callback_id="cb-1", payload="x", user=SimpleNamespace(user_id=2)),
        bot=bot,
    )
    calls = {"edit": [], "ack": 0, "edit_fails": edit_fails}
    _JOURNAL[id(event)] = calls
    return event, calls


# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_first_render_sends_and_remembers_screen():
    bot = FakeBot()
    ctx = FakeContext()
    event = make_message_created(bot)

    await helpers.render(event, ctx, "Шаг 1", None)

    assert bot.sent == ["Шаг 1"]           # экрана не было — отправили новый
    data = await ctx.get_data()
    assert data[SCREEN_KEY] == "mid-new-1"  # и запомнили его id


@pytest.mark.asyncio
async def test_text_reply_edits_stored_screen_instead_of_sending():
    """Пользователь ответил текстом: экран правим, новое сообщение не отправляем."""
    bot = FakeBot()
    ctx = FakeContext({SCREEN_KEY: "mid-screen"})
    event = make_message_created(bot)

    await helpers.render(event, ctx, "Шаг 2", None)

    assert bot.edited == [("mid-screen", "Шаг 2")]
    assert bot.sent == []


@pytest.mark.asyncio
async def test_callback_on_current_screen_uses_fast_path():
    bot = FakeBot()
    ctx = FakeContext({SCREEN_KEY: "mid-screen"})
    event, calls = make_callback(bot, clicked_mid="mid-screen")

    await helpers.render(event, ctx, "Шаг 3", None)

    assert calls["edit"] == ["Шаг 3"]   # правим через ответ на callback
    assert bot.edited == []             # отдельный edit_message не нужен
    assert bot.sent == []


@pytest.mark.asyncio
async def test_callback_on_stale_message_edits_current_screen():
    """Кнопка нажата в старом сообщении — экран не должен «уехать» назад."""
    bot = FakeBot()
    ctx = FakeContext({SCREEN_KEY: "mid-screen"})
    event, calls = make_callback(bot, clicked_mid="mid-OLD")

    await helpers.render(event, ctx, "Шаг 4", None)

    assert calls["edit"] == []                        # старое сообщение не трогаем
    assert bot.edited == [("mid-screen", "Шаг 4")]    # обновляем актуальный экран
    assert calls["ack"] == 1                          # но callback подтверждаем
    data = await ctx.get_data()
    assert data[SCREEN_KEY] == "mid-screen"           # экран остался тем же


@pytest.mark.asyncio
async def test_falls_back_to_new_message_when_edit_fails():
    """Экран удалён/слишком старый — сценарий не должен встать."""
    bot = FakeBot(edit_fails=True)
    ctx = FakeContext({SCREEN_KEY: "mid-gone"})
    event = make_message_created(bot)

    await helpers.render(event, ctx, "Шаг 5", None)

    assert bot.sent == ["Шаг 5"]
    data = await ctx.get_data()
    assert data[SCREEN_KEY] == "mid-new-1"   # запомнили новый экран


@pytest.mark.asyncio
async def test_callback_edit_failure_falls_back_to_edit_message():
    bot = FakeBot()
    ctx = FakeContext({SCREEN_KEY: "mid-screen"})
    event, calls = make_callback(bot, clicked_mid="mid-screen", edit_fails=True)

    await helpers.render(event, ctx, "Шаг 6", None)

    assert bot.edited == [("mid-screen", "Шаг 6")]
    assert calls["ack"] == 1


@pytest.mark.asyncio
async def test_clear_keeping_screen_preserves_only_screen():
    ctx = FakeContext({SCREEN_KEY: "mid-screen", "fio": "Иванов", "err_fio": 2})
    await ctx.set_state("JoinSG:fio")

    await helpers.clear_keeping_screen(ctx)

    data = await ctx.get_data()
    assert data == {SCREEN_KEY: "mid-screen"}   # анкета сброшена, экран сохранён
    assert await ctx.get_state() is None


@pytest.mark.asyncio
async def test_clear_keeping_screen_without_screen_is_noop():
    ctx = FakeContext({"fio": "Иванов"})
    await helpers.clear_keeping_screen(ctx)
    assert await ctx.get_data() == {}


# --- счётчик неудачных попыток ввода (правило «три попытки») --------------- #
@pytest.mark.asyncio
async def test_bump_error_counts_per_field():
    ctx = FakeContext()
    assert await helpers.bump_error(ctx, "fio") == 1
    assert await helpers.bump_error(ctx, "fio") == 2
    assert await helpers.bump_error(ctx, "fio") == 3
    # Счётчики полей независимы
    assert await helpers.bump_error(ctx, "phone") == 1


@pytest.mark.asyncio
async def test_reset_error_zeroes_counter():
    ctx = FakeContext()
    await helpers.bump_error(ctx, "phone")
    await helpers.bump_error(ctx, "phone")
    await helpers.reset_error(ctx, "phone")
    # После сброса отсчёт начинается заново
    assert await helpers.bump_error(ctx, "phone") == 1
