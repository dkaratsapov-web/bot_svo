"""Точка входа: инициализация и запуск бота (webhook | polling)."""

from __future__ import annotations

import asyncio
import contextlib
from http import HTTPStatus

from aiohttp import web
from maxapi import Bot, Dispatcher
from maxapi.context import MemoryContext, RedisContext
from maxapi.enums.update import UpdateType
from maxapi.types.command import BotCommand
from maxapi.webhook.aiohttp import AiohttpMaxWebhook

from app.config import Settings, get_settings
from app.db import session as db
from app.handlers import admin, common, consent, consult, join
from app.logging_setup import configure_logging, get_logger
from app.middlewares.core import AntiFloodMiddleware, IdempotencyMiddleware
from app.runtime import runtime
from app.services.idempotency import IdempotencyStore
from app.services.notifier import Notifier
from app.utils.rate_limit import limiter
from app.utils.throttling import AntiFlood

log = get_logger("main")

BOT_COMMANDS = [
    BotCommand(name="start", description="Начать / главное меню"),
    BotCommand(name="menu", description="Главное меню"),
    BotCommand(name="help", description="Справка и контакты"),
    BotCommand(name="cancel", description="Отменить текущую заявку"),
]


def build_bot(settings: Settings) -> Bot:
    bot = Bot(token=settings.bot_token, format="markdown")
    if settings.api_base_url and hasattr(bot, "set_api_url"):
        bot.set_api_url(settings.api_base_url)
    return bot


def build_dispatcher(settings: Settings, redis_client) -> Dispatcher:
    if settings.use_redis and redis_client is not None:
        dp = Dispatcher(storage=RedisContext, redis_client=redis_client, use_create_task=True)
    else:
        dp = Dispatcher(storage=MemoryContext, use_create_task=True)

    # Outer-middleware: сначала идемпотентность, затем анти-флуд.
    dp.register_outer_middleware(IdempotencyMiddleware())
    dp.register_outer_middleware(AntiFloodMiddleware())

    # Порядок важен: специфичные роутеры раньше, fallback — последним.
    dp.include_routers(
        common.router,
        consent.router,
        join.router,
        consult.router,
        admin.router,
        common.fallback_router,
    )
    return dp


def _make_redis(settings: Settings):
    if not settings.use_redis:
        return None
    import redis.asyncio as aioredis

    return aioredis.from_url(settings.redis_url, decode_responses=True)


def init_runtime(settings: Settings, bot: Bot, redis_client) -> None:
    runtime.settings = settings
    runtime.antiflood = AntiFlood(limit=20, window_sec=60.0)
    runtime.idempotency = IdempotencyStore(redis_client=redis_client)
    runtime.notifier = Notifier(bot, settings, limiter=limiter)


async def _healthz(request: web.Request) -> web.Response:
    """Проверка БД и Redis."""
    status = {"db": False, "redis": None}
    try:
        status["db"] = await db.healthcheck()
    except Exception as exc:  # noqa: BLE001
        log.error("healthz_db_failed", error=str(exc))

    redis_client = request.app.get("redis")
    if redis_client is not None:
        try:
            status["redis"] = bool(await redis_client.ping())
        except Exception as exc:  # noqa: BLE001
            log.error("healthz_redis_failed", error=str(exc))
            status["redis"] = False

    healthy = status["db"] and (status["redis"] is not False)
    code = HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE
    return web.json_response(status, status=code)


async def run_webhook(bot: Bot, dp: Dispatcher, settings: Settings, redis_client) -> None:
    app = web.Application()
    app["redis"] = redis_client
    app.router.add_get("/healthz", _healthz)

    webhook = AiohttpMaxWebhook(dp=dp, bot=bot, secret=settings.webhook_secret or None)
    app.on_startup.append(webhook.on_startup)
    webhook.setup(app, path=settings.webhook_path)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.web_host, port=settings.web_port)
    await site.start()
    log.info("webhook_started", host=settings.web_host, port=settings.web_port, path=settings.webhook_path)

    # Регистрируем подписку на webhook в MAX.
    if settings.webhook_url:
        try:
            await bot.subscribe_webhook(
                url=settings.webhook_url, secret=settings.webhook_secret or None
            )
            log.info("webhook_subscribed", url=settings.webhook_url)
        except Exception as exc:  # noqa: BLE001
            log.error("webhook_subscribe_failed", error=str(exc))

    stop = asyncio.Event()
    try:
        await stop.wait()
    finally:
        await runner.cleanup()


async def async_main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    db.init_engine(settings.database_url)
    await db.create_all()  # idempotent; для прод-схемы используйте alembic upgrade head

    redis_client = _make_redis(settings)
    bot = build_bot(settings)
    dp = build_dispatcher(settings, redis_client)
    init_runtime(settings, bot, redis_client)

    runtime.notifier.start()
    with contextlib.suppress(Exception):
        await bot.set_my_commands(*BOT_COMMANDS)

    log.info("bot_starting", mode=settings.mode)
    try:
        if settings.use_webhook:
            await run_webhook(bot, dp, settings, redis_client)
        else:
            await dp.start_polling(bot)
    finally:
        log.info("shutting_down")
        with contextlib.suppress(Exception):
            await dp.stop_polling()
        await runtime.notifier.stop()
        with contextlib.suppress(Exception):
            await bot.close_session()
        await db.dispose_engine()
        if redis_client is not None:
            with contextlib.suppress(Exception):
                await redis_client.aclose()


def main() -> None:
    try:
        asyncio.run(async_main())
    except (KeyboardInterrupt, SystemExit):
        log.info("stopped")


if __name__ == "__main__":
    main()
