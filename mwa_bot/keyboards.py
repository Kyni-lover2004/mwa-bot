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


def build_final_keyboard(
    program_url: str, apply_url: str, channel_url: str
) -> InlineKeyboardMarkup:
    """Кнопки финального сообщения: программа, заявка, канал."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="ОТКРЫТЬ ПРОГРАММУ MWA", url=program_url)],
            [InlineKeyboardButton(text="ОФОРМИТЬ УЧАСТИЕ", url=apply_url)],
            [InlineKeyboardButton(text="TELEGRAM-КАНАЛ MWA", url=channel_url)],
        ]
    )
