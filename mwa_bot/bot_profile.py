"""Профиль бота в Telegram: описание, которое видно до первого запуска."""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat

from mwa_bot.config import Settings
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


async def publish_admin_commands(bot: Bot, settings: Settings) -> None:
    """Показывает админам из ADMIN_IDS команду /admin в меню бота."""
    commands = [BotCommand(command="admin", description="Рассылка всем пользователям")]
    for admin_id in settings.admin_ids:
        try:
            await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=admin_id))
        except TelegramAPIError as exc:
            # Telegram не знает чат, пока человек сам ни разу не написал боту.
            logger.info("Команда /admin для %s не установлена: %s", admin_id, exc)
