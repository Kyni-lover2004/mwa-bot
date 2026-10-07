"""Онбординг по кнопкам: WELCOME -> проверка подписки -> DAY 1."""

import logging
from datetime import UTC, datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from mwa_bot.config import Settings
from mwa_bot.content.loader import Content
from mwa_bot.db.models import Stage
from mwa_bot.db.users import get_or_create_user, mark_subscribed
from mwa_bot.flow import Delivery, has_passed_onboarding
from mwa_bot.handlers.callbacks import answer_callback, remove_keyboard
from mwa_bot.keyboards import (
    CHECK_SUBSCRIPTION_CALLBACK,
    WELCOME_CALLBACK,
    build_subscribe_keyboard,
)
from mwa_bot.subscription import is_subscribed

logger = logging.getLogger(__name__)

NOT_SUBSCRIBED_ALERT = (
    "Подписка пока не найдена. Подпишитесь на канал MWA и нажмите кнопку ещё раз."
)
CHECK_FAILED_ALERT = "Не получилось проверить подписку. Попробуйте ещё раз через минуту."


def create_router() -> Router:
    """Создаёт роутер кнопок онбординга."""
    router = Router(name=__name__)
    router.callback_query.register(handle_welcome_button, F.data == WELCOME_CALLBACK)
    router.callback_query.register(
        handle_check_subscription_button, F.data == CHECK_SUBSCRIPTION_CALLBACK
    )
    return router


async def handle_welcome_button(
    callback: CallbackQuery,
    bot: Bot,
    session: AsyncSession,
    content: Content,
    delivery: Delivery,
    settings: Settings,
) -> None:
    """WELCOME -> DAY 1, если пользователь подписан, иначе просьба подписаться."""
    user = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
    if has_passed_onboarding(user):
        await dismiss_button(callback)
        return
    subscribed = await check_subscription(callback, bot, settings, user.telegram_id)
    if subscribed is None:
        return

    await answer_callback(callback)
    if not await remove_keyboard(callback):
        return
    if subscribed:
        await start_days(session, delivery, user.telegram_id)
    else:
        await bot.send_message(
            user.telegram_id,
            content.not_subscribed,
            reply_markup=build_subscribe_keyboard(settings.channel_url),
        )


async def handle_check_subscription_button(
    callback: CallbackQuery,
    bot: Bot,
    session: AsyncSession,
    content: Content,
    delivery: Delivery,
    settings: Settings,
) -> None:
    """Повторная проверка подписки; при успехе отправляет DAY 1."""
    user = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
    if has_passed_onboarding(user):
        await dismiss_button(callback)
        return
    subscribed = await check_subscription(callback, bot, settings, user.telegram_id)
    if subscribed is None:
        return
    if not subscribed:
        await answer_callback(callback, NOT_SUBSCRIBED_ALERT, show_alert=True)
        return

    await answer_callback(callback)
    if not await remove_keyboard(callback):
        return
    await start_days(session, delivery, user.telegram_id)


async def start_days(session: AsyncSession, delivery: Delivery, telegram_id: int) -> None:
    """Фиксирует пройденную проверку подписки и отправляет DAY 1."""
    await mark_subscribed(session, telegram_id, datetime.now(UTC))
    await delivery.deliver_due(session, telegram_id, Stage.START)


async def check_subscription(
    callback: CallbackQuery, bot: Bot, settings: Settings, user_id: int
) -> bool | None:
    """Проверяет подписку; если Telegram ответил ошибкой, сообщает пользователю и даёт None."""
    try:
        return await is_subscribed(bot, settings.channel_id, user_id)
    except TelegramAPIError as exc:
        logger.error(
            "Не удалось проверить подписку пользователя %s на %s: %s. "
            "Проверь CHANNEL_ID и что бот - администратор канала",
            user_id,
            settings.channel_id,
            exc,
        )
        await answer_callback(callback, CHECK_FAILED_ALERT, show_alert=True)
        return None


async def dismiss_button(callback: CallbackQuery) -> None:
    """Гасит нажатие старой кнопки: пользователь уже прошёл этот шаг."""
    await answer_callback(callback)
    await remove_keyboard(callback)
