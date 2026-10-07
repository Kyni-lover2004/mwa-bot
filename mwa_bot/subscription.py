"""Проверка подписки на канал MWA."""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    ChatMemberAdministrator,
    ChatMemberMember,
    ChatMemberOwner,
    ChatMemberRestricted,
)

from mwa_bot.config import Settings

logger = logging.getLogger(__name__)


async def is_subscribed(bot: Bot, channel_id: str | None, user_id: int) -> bool:
    """Проверяет, состоит ли пользователь в канале; без channel_id проверка выключена.

    Telegram отвечает на запрос, только если бот - администратор канала.
    """
    if channel_id is None:
        return True
    member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
    if isinstance(member, ChatMemberRestricted):
        return member.is_member
    return isinstance(member, ChatMemberOwner | ChatMemberAdministrator | ChatMemberMember)


async def check_channel_access(bot: Bot, settings: Settings) -> None:
    """При старте проверяет, что бот - администратор канала; иначе пишет в лог, что исправить."""
    if settings.channel_id is None:
        logger.warning("CHANNEL_ID=off: проверка подписки выключена, проходят все")
        return
    try:
        member = await bot.get_chat_member(chat_id=settings.channel_id, user_id=bot.id)
    except TelegramAPIError as exc:
        logger.error(
            "Проверка подписки не будет работать: Telegram не отдаёт участников %s (%s). "
            "Добавь бота администратором канала и проверь CHANNEL_ID",
            settings.channel_id,
            exc,
        )
        return
    if not isinstance(member, ChatMemberAdministrator):
        logger.error(
            "Проверка подписки не будет работать: бот в канале %s со статусом %s, "
            "а нужен администратор",
            settings.channel_id,
            member.status,
        )
        return
    logger.info("Проверка подписки включена, канал %s", settings.channel_id)
