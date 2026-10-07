"""Подключение к базе: движок, фабрика сессий, создание таблиц."""

import logging
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from mwa_bot.db.models import Base

logger = logging.getLogger(__name__)


def create_db_engine(database_url: str) -> AsyncEngine:
    """Создаёт async-движок; для SQLite заранее создаёт папку под файл базы."""
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database:
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    return create_async_engine(url)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Создаёт фабрику сессий; объекты остаются читаемыми после commit."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_tables(engine: AsyncEngine) -> None:
    """Создаёт недостающие таблицы; существующие не меняет, для этого нужны миграции."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    logger.info("Таблицы базы данных готовы")
