"""Рассылка сообщения всем пользователям бота; доступна только админам из ADMIN_IDS."""

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, TelegramObject

from mwa_bot.broadcast import Broadcaster
from mwa_bot.config import Settings
from mwa_bot.handlers.callbacks import answer_callback, remove_keyboard
from mwa_bot.keyboards import (
    BROADCAST_CANCEL_CALLBACK,
    BROADCAST_CONFIRM_CALLBACK,
    CANCEL_BUTTON,
    SEND_BUTTON,
    build_admin_keyboard,
    build_broadcast_confirm_keyboard,
    build_cancel_keyboard,
)


class BroadcastStates(StatesGroup):
    """Шаги рассылки: ждём сообщение, ждём подтверждение."""

    waiting_message = State()
    confirming = State()


class IsBotAdmin(Filter):
    """Пропускает только пользователей из ADMIN_IDS."""

    async def __call__(self, event: TelegramObject, settings: Settings) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and user.id in settings.admin_ids


def create_router() -> Router:
    """Создаёт роутер рассылки; сообщения остальных пользователей идут мимо него."""
    router = Router(name=__name__)
    router.message.filter(F.chat.type == ChatType.PRIVATE, IsBotAdmin())
    router.callback_query.filter(IsBotAdmin())
    router.message.register(handle_admin_menu, Command("admin"))
    router.message.register(handle_cancel, F.text == CANCEL_BUTTON)
    router.message.register(handle_send_button, F.text == SEND_BUTTON)
    router.message.register(handle_draft, StateFilter(BroadcastStates.waiting_message))
    router.callback_query.register(
        handle_confirm,
        F.data == BROADCAST_CONFIRM_CALLBACK,
        StateFilter(BroadcastStates.confirming),
    )
    router.callback_query.register(handle_cancel_button, F.data == BROADCAST_CANCEL_CALLBACK)
    return router


async def handle_admin_menu(message: Message) -> None:
    """Показывает админу кнопку рассылки."""
    await message.answer(
        "Меню администратора. «Отправить сообщение» - рассылка всем, кто запускал бота.",
        reply_markup=build_admin_keyboard(),
    )


async def handle_send_button(message: Message, state: FSMContext) -> None:
    """Начинает рассылку: просит прислать сообщение."""
    await state.set_state(BroadcastStates.waiting_message)
    await message.answer(
        "Пришлите сообщение для рассылки: текст, фото или видео с подписью. "
        "Его получат все пользователи бота в том виде, в каком вы его отправите.",
        reply_markup=build_cancel_keyboard(),
    )


async def handle_draft(
    message: Message, bot: Bot, state: FSMContext, broadcaster: Broadcaster
) -> None:
    """Показывает предпросмотр сообщения и просит подтвердить рассылку."""
    recipients = await broadcaster.count_recipients(message.chat.id)
    if recipients == 0:
        await state.clear()
        await message.answer(
            "Пока некому отправлять: кроме вас, бота никто не запускал.",
            reply_markup=build_admin_keyboard(),
        )
        return

    await state.update_data(from_chat_id=message.chat.id, message_id=message.message_id)
    await state.set_state(BroadcastStates.confirming)
    await message.answer("Так сообщение увидят пользователи:")
    await bot.copy_message(
        chat_id=message.chat.id, from_chat_id=message.chat.id, message_id=message.message_id
    )
    await message.answer(
        f"Отправить всем? Получателей: {recipients}.",
        reply_markup=build_broadcast_confirm_keyboard(recipients),
    )


async def handle_confirm(
    callback: CallbackQuery, bot: Bot, state: FSMContext, broadcaster: Broadcaster
) -> None:
    """Запускает рассылку после подтверждения."""
    await answer_callback(callback)
    # Удаление кнопок служит защитой: второе нажатие той же кнопки рассылку не повторит.
    if not await remove_keyboard(callback):
        return
    draft = await state.get_data()
    await state.clear()
    broadcaster.start(bot, callback.from_user.id, draft["from_chat_id"], draft["message_id"])
    await bot.send_message(
        callback.from_user.id,
        "Рассылка началась. Пришлю итог, когда закончится.",
        reply_markup=build_admin_keyboard(),
    )


async def handle_cancel(message: Message, state: FSMContext) -> None:
    """Отменяет рассылку по кнопке «Отмена» внизу."""
    await state.clear()
    await message.answer("Рассылка отменена.", reply_markup=build_admin_keyboard())


async def handle_cancel_button(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    """Отменяет рассылку по кнопке под предпросмотром."""
    await answer_callback(callback)
    await remove_keyboard(callback)
    await state.clear()
    await bot.send_message(
        callback.from_user.id, "Рассылка отменена.", reply_markup=build_admin_keyboard()
    )
