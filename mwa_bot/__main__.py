"""Точка входа: python -m mwa_bot."""

import asyncio
import logging
import sys

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from pydantic import ValidationError

from mwa_bot.app import build_dispatcher
from mwa_bot.config import Settings
from mwa_bot.content.loader import Content, ContentError, load_content
from mwa_bot.content.sender import MaterialSender
from mwa_bot.db.engine import create_db_engine, create_session_factory, create_tables
from mwa_bot.flow import Delivery
from mwa_bot.keyboards import build_final_keyboard
from mwa_bot.logging_setup import setup_logging
from mwa_bot.middlewares.flood_control import RetryAfterMiddleware
from mwa_bot.scheduler import Scheduler
from mwa_bot.webhook import build_web_app, build_webhook_secret, serve_webhook

logger = logging.getLogger(__name__)


async def run_bot(settings: Settings, content: Content) -> None:
    """Готовит базу, собирает бота и диспетчер и принимает апдейты: webhook или polling."""
    engine = create_db_engine(settings.database_url)
    await create_tables(engine)
    session_factory = create_session_factory(engine)

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    bot.session.middleware(RetryAfterMiddleware())
    sender = MaterialSender(bot, session_factory)
    final_keyboard = build_final_keyboard(
        settings.program_url, settings.apply_url, settings.channel_url
    )
    delivery = Delivery(sender, content, settings.day_interval, final_keyboard)
    scheduler = Scheduler(session_factory, delivery)
    dispatcher = build_dispatcher(settings, content, sender, delivery, scheduler, session_factory)

    try:
        if settings.webhook_base_url:
            secret = build_webhook_secret(settings.bot_token.get_secret_value())
            app = build_web_app(dispatcher, bot, settings.webhook_base_url, secret)
            await serve_webhook(app, settings.port)
        else:
            # Один токен - один способ получать апдейты: снимаем webhook, оставшийся
            # от запуска на хостинге, иначе getUpdates упрётся в конфликт.
            await bot.delete_webhook()
            await dispatcher.start_polling(bot)
    finally:
        # Обычно сессию уже закрыли polling или webhook; здесь - на случай падения на старте.
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    """Загружает настройки и контент, включает логирование и запускает бота."""
    try:
        settings = Settings()
    except ValidationError as exc:
        sys.exit(f"Ошибка конфигурации, проверь .env или переменные окружения:\n{exc}")

    setup_logging(settings.log_level)
    try:
        content = load_content(settings.content_dir)
    except ContentError as exc:
        sys.exit(f"Ошибка контента: {exc}")

    if settings.channel_id is None:
        logger.warning("CHANNEL_ID не задан: проверка подписки выключена, проходят все")

    asyncio.run(run_bot(settings, content))


if __name__ == "__main__":
    main()
