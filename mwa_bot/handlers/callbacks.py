"""Общие действия с нажатиями inline-кнопок."""

import logging

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)


async def answer_callback(
    callback: CallbackQuery, text: str | None = None, *, show_alert: bool = False
) -> None:
    """Отвечает на нажатие; сбой ответа не должен мешать самому переходу."""
    try:
        await callback.answer(text, show_alert=show_alert)
    except TelegramAPIError as exc:
        # Типичный случай - нажатие пролежало в очереди, пока бот перезапускался.
        logger.info("Не удалось ответить на нажатие кнопки: %s", exc)


async def remove_keyboard(callback: CallbackQuery) -> bool:
    """Убирает кнопки у сообщения; False - их уже убрало другое нажатие этой же кнопки."""
    # Сообщения старше 48 часов приходят как InaccessibleMessage, их уже не отредактировать.
    if not isinstance(callback.message, Message) or callback.message.reply_markup is None:
        return True
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError as exc:
        if isinstance(exc, TelegramBadRequest) and "message is not modified" in exc.message:
            return False
        logger.warning("Не удалось убрать кнопки: %s", exc)
    return True
