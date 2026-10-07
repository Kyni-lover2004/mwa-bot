"""Общие фикстуры тестов."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram_fakes import TEST_BOT_TOKEN, FakeTelegramSession

from mwa_bot.db.engine import create_db_engine, create_session_factory, create_tables


@pytest.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Фабрика сессий поверх отдельной SQLite-базы во временной папке."""
    engine = create_db_engine(f"sqlite+aiosqlite:///{tmp_path / 'nested' / 'test.db'}")
    await create_tables(engine)
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
def telegram() -> FakeTelegramSession:
    return FakeTelegramSession()


@pytest.fixture
def bot(telegram: FakeTelegramSession) -> Bot:
    """Бот с фейковой сессией и теми же настройками по умолчанию, что в __main__."""
    return Bot(
        TEST_BOT_TOKEN, session=telegram, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
