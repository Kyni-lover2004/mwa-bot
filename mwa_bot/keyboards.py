"""Inline-кнопки бота и данные, которые они присылают при нажатии."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

WELCOME_CALLBACK = "onboarding:welcome"
CHECK_SUBSCRIPTION_CALLBACK = "onboarding:check_subscription"


def build_welcome_keyboard() -> InlineKeyboardMarkup:
    """Кнопка экрана WELCOME TO MWA."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="НАЧАТЬ", callback_data=WELCOME_CALLBACK)]]
    )


def build_subscribe_keyboard(channel_url: str) -> InlineKeyboardMarkup:
    """Кнопки для пользователя, который ещё не подписан на канал."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="ПОДПИСАТЬСЯ НА MWA", url=channel_url)],
            [
                InlineKeyboardButton(
                    text="ПРОВЕРИТЬ ПОДПИСКУ", callback_data=CHECK_SUBSCRIPTION_CALLBACK
                )
            ],
        ]
    )


def build_final_keyboard(site_url: str) -> InlineKeyboardMarkup:
    """Кнопка финального сообщения."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="УЗНАТЬ О MWA METHOD", url=site_url)]]
    )
