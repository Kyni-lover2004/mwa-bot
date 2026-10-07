"""Обработчик команды /start."""

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from mwa_bot.content.loader import Content
from mwa_bot.content.sender import MaterialSender
from mwa_bot.db.models import Stage
from mwa_bot.db.users import get_or_create_user
from mwa_bot.flow import Delivery, has_passed_onboarding, is_paused
from mwa_bot.keyboards import build_welcome_keyboard


def create_router() -> Router:
    """Создаёт роутер команды /start для личных чатов."""
    router = Router(name=__name__)
    router.message.filter(F.chat.type == ChatType.PRIVATE)
    router.message.register(handle_start, CommandStart())
    return router


async def handle_start(
    message: Message,
    session: AsyncSession,
    content: Content,
    sender: MaterialSender,
    delivery: Delivery,
) -> None:
    """Показывает экран по этапу пользователя; повторный /start прогресс не сбрасывает."""
    if message.from_user is None:
        return
    user = await get_or_create_user(session, message.from_user.id, message.from_user.username)

    if user.stage is Stage.FINAL:
        await delivery.send_final(message.chat.id)
    elif is_paused(user):
        # Вернулся после блокировки бота: следующий день сразу, дальше снова по расписанию.
        await delivery.deliver_due(session, user.telegram_id, user.stage)
    elif has_passed_onboarding(user):
        await message.answer(content.in_progress)
    else:
        # Экран START - это описание бота и кнопка «Начать» самого Telegram, дальше сразу WELCOME.
        await sender.send_photo(
            message.chat.id, content.welcome_photo, content.welcome, build_welcome_keyboard()
        )
