"""Профиль бота в Telegram: описание, которое видно до первого запуска."""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from mwa_bot.content.loader import Content

logger = logging.getLogger(__name__)


async def publish_description(bot: Bot, content: Content) -> None:
    """Обновляет описание бота («Что умеет этот бот?»), если текст в content/ изменился."""
    # Сначала читаем текущее: менять описание на каждом старте незачем, а частые
    # изменения Telegram ограничивает и заставил бы старт ждать.
    try:
        current = await bot.get_my_description()
        if current.description == content.description:
            return
        await bot.set_my_description(description=content.description)
    except TelegramAPIError as exc:
        logger.warning("Не удалось обновить описание бота, останется прежнее: %s", exc)
        return
    logger.info("Описание бота обновлено")
