"""Проверка подписки на канал MWA."""

from aiogram import Bot
from aiogram.types import (
    ChatMemberAdministrator,
    ChatMemberMember,
    ChatMemberOwner,
    ChatMemberRestricted,
)


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
