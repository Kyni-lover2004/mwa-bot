"""Сборка диспетчера: роутеры, middleware и общие зависимости хендлеров."""

from aiogram import Dispatcher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mwa_bot.bot_profile import publish_description
from mwa_bot.config import Settings
from mwa_bot.content.loader import Content
from mwa_bot.content.sender import MaterialSender
from mwa_bot.flow import Delivery
from mwa_bot.handlers import onboarding, start
from mwa_bot.middlewares.db import DbSessionMiddleware
from mwa_bot.scheduler import Scheduler


def build_dispatcher(
    settings: Settings,
    content: Content,
    sender: MaterialSender,
    delivery: Delivery,
    scheduler: Scheduler,
    session_factory: async_sessionmaker[AsyncSession],
) -> Dispatcher:
    """Собирает диспетчер со всеми роутерами и зависимостями."""
    # Именованные аргументы диспетчера aiogram передаёт в хендлеры по имени параметра.
    dispatcher = Dispatcher(settings=settings, content=content, sender=sender, delivery=delivery)
    dispatcher.update.middleware(DbSessionMiddleware(session_factory))
    dispatcher.include_routers(start.create_router(), onboarding.create_router())
    # Хуки shutdown срабатывают до закрытия сессии бота, поэтому планировщик успевает остановиться.
    dispatcher.startup.register(publish_description)
    dispatcher.startup.register(scheduler.start)
    dispatcher.shutdown.register(scheduler.stop)
    return dispatcher
