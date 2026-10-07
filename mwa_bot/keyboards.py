"""Inline-кнопки бота и данные, которые они присылают при нажатии."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

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


def build_program_keyboard(
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


SEND_BUTTON = "Отправить сообщение"
CANCEL_BUTTON = "Отмена"
BROADCAST_CONFIRM_CALLBACK = "broadcast:confirm"
BROADCAST_CANCEL_CALLBACK = "broadcast:cancel"


def build_admin_keyboard() -> ReplyKeyboardMarkup:
    """Кнопка рассылки внизу чата у админа."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=SEND_BUTTON)]], resize_keyboard=True, is_persistent=True
    )


def build_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Кнопка отмены, пока админ готовит сообщение для рассылки."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CANCEL_BUTTON)]], resize_keyboard=True
    )


def build_broadcast_confirm_keyboard(recipients: int) -> InlineKeyboardMarkup:
    """Подтверждение рассылки под предпросмотром."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Отправить всем ({recipients})", callback_data=BROADCAST_CONFIRM_CALLBACK
                )
            ],
            [InlineKeyboardButton(text="Отмена", callback_data=BROADCAST_CANCEL_CALLBACK)],
        ]
    )
