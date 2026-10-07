"""Режим webhook: Telegram сам присылает апдейты HTTP-запросами."""

import asyncio
import hashlib
import logging
import signal

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/telegram/webhook"
HEALTH_PATH = "/health"


def build_webhook_secret(bot_token: str) -> str:
    """Секрет заголовка X-Telegram-Bot-Api-Secret-Token, выведенный из токена бота."""
    # Telegram допускает в секрете только A-Z, a-z, 0-9, _ и -; hex подходит.
    return hashlib.sha256(bot_token.encode()).hexdigest()


def build_web_app(dispatcher: Dispatcher, bot: Bot, base_url: str, secret: str) -> web.Application:
    """Собирает HTTP-приложение: приём апдейтов от Telegram и проверка живости для хостинга."""
    app = web.Application()
    app.router.add_get(HEALTH_PATH, handle_health)
    dispatcher.startup.register(register_webhook)
    # Порядок важен: shutdown-хуки aiohttp идут по порядку регистрации, и планировщик
    # должен остановиться раньше, чем обработчик webhook закроет сессию бота.
    setup_application(
        app, dispatcher, bot=bot, webhook_url=base_url.rstrip("/") + WEBHOOK_PATH, secret=secret
    )
    SimpleRequestHandler(dispatcher=dispatcher, bot=bot, secret_token=secret).register(
        app, path=WEBHOOK_PATH
    )
    return app


async def register_webhook(bot: Bot, dispatcher: Dispatcher, webhook_url: str, secret: str) -> None:
    """Сообщает Telegram, куда присылать апдейты."""
    # Старый webhook не снимаем при остановке: при передеплое новый экземпляр
    # уже мог поставить свой, и снятие сломало бы его.
    await bot.set_webhook(
        webhook_url,
        secret_token=secret,
        allowed_updates=dispatcher.resolve_used_update_types(),
    )
    logger.info("Webhook установлен: %s", webhook_url)


async def handle_health(request: web.Request) -> web.Response:
    """Отвечает хостингу, что процесс жив."""
    return web.Response(text="ok")


async def serve_webhook(app: web.Application, port: int) -> None:
    """Поднимает HTTP-сервер и держит его до SIGTERM или SIGINT."""
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        # Хостинг проксирует запросы снаружи, поэтому слушаем все интерфейсы.
        await web.TCPSite(runner, host="0.0.0.0", port=port).start()
        logger.info("Бот принимает апдейты по webhook на порту %s", port)
        await wait_for_stop_signal()
    finally:
        await runner.cleanup()


async def wait_for_stop_signal() -> None:
    """Ждёт SIGTERM (остановка на хостинге) или SIGINT (Ctrl+C)."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    signals = (signal.SIGTERM, signal.SIGINT)
    for stop_signal in signals:
        loop.add_signal_handler(stop_signal, stop.set)
    try:
        await stop.wait()
    finally:
        for stop_signal in signals:
            loop.remove_signal_handler(stop_signal)
    logger.info("Получен сигнал остановки")
