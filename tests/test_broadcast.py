"""Рассылка админа всем пользователям: апдейты идут через настоящий диспетчер."""

import asyncio
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import Any

import pytest
from aiogram.methods import CopyMessage, SendMessage, SetMyCommands
from aiogram.types import Update
from sqlalchemy import update
from telegram_fakes import TEST_BOT_TOKEN, build_callback_update, build_message_update

from mwa_bot.app import build_dispatcher
from mwa_bot.config import Settings
from mwa_bot.content.loader import load_content
from mwa_bot.content.sender import MaterialSender
from mwa_bot.db.models import Stage, User
from mwa_bot.db.users import get_or_create_user
from mwa_bot.flow import Delivery
from mwa_bot.keyboards import (
    BROADCAST_CANCEL_CALLBACK,
    BROADCAST_CONFIRM_CALLBACK,
    CANCEL_BUTTON,
    SEND_BUTTON,
    build_final_keyboard,
)
from mwa_bot.scheduler import Scheduler

REPO_CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"
ADMIN_ID = 500
OTHER_ADMIN_ID = 501
USER_IDS = (1001, 1002, 1003)


class BotChats:
    """Пользователи в личке с ботом: пишут и жмут кнопки через собранный диспетчер."""

    def __init__(self, bot, session_factory, **settings: Any) -> None:
        config = Settings(
            _env_file=None,
            bot_token=TEST_BOT_TOKEN,
            admin_ids=f"{ADMIN_ID},{OTHER_ADMIN_ID}",
            **settings,
        )
        content = load_content(REPO_CONTENT_DIR)
        sender = MaterialSender(bot, session_factory)
        delivery = Delivery(sender, content, config.day_interval, build_final_keyboard("", "", ""))
        scheduler = Scheduler(session_factory, delivery)
        self.dispatcher = build_dispatcher(
            config, content, sender, delivery, scheduler, session_factory
        )
        self.broadcaster = self.dispatcher.workflow_data["broadcaster"]
        self.bot = bot
        self._update_ids = count(1)

    async def send(self, user_id: int, **payload: Any) -> None:
        await self._feed(build_message_update(next(self._update_ids), user_id, **payload))

    async def press(self, user_id: int, data: str, message_id: int = 900) -> None:
        await self._feed(build_callback_update(next(self._update_ids), user_id, data, message_id))

    async def _feed(self, raw_update: dict[str, Any]) -> None:
        update = Update.model_validate(raw_update, context={"bot": self.bot})
        await self.dispatcher.feed_update(self.bot, update)


@pytest.fixture
async def chats(bot, session_factory) -> BotChats:
    async with session_factory() as session:
        for user_id in (ADMIN_ID, *USER_IDS):
            await get_or_create_user(session, user_id, None)
    return BotChats(bot, session_factory)


async def prepare_broadcast(chats: BotChats, **payload: Any) -> None:
    await chats.send(ADMIN_ID, text=SEND_BUTTON)
    await chats.send(ADMIN_ID, **payload)


def list_copies(telegram) -> list[CopyMessage]:
    return telegram.list_requests(CopyMessage)


async def test_admin_menu_shows_send_button(chats, telegram):
    await chats.send(ADMIN_ID, text="/admin")

    [menu] = telegram.list_requests(SendMessage)
    assert menu.reply_markup.keyboard[0][0].text == SEND_BUTTON


async def test_regular_user_has_no_broadcast(chats, telegram):
    await chats.send(USER_IDS[0], text="/admin")
    await chats.send(USER_IDS[0], text=SEND_BUTTON)
    await chats.send(USER_IDS[0], text="всем привет")

    assert telegram.list_requests(SendMessage) == []
    assert list_copies(telegram) == []


async def test_draft_is_previewed_and_needs_confirmation(chats, telegram):
    await prepare_broadcast(chats, text="Новость <b>MWA</b>")

    [preview] = list_copies(telegram)
    assert (preview.chat_id, preview.from_chat_id) == (ADMIN_ID, ADMIN_ID)
    confirm = telegram.list_requests(SendMessage)[-1]
    assert "Получателей: 3" in confirm.text
    assert confirm.reply_markup.inline_keyboard[0][0].callback_data == BROADCAST_CONFIRM_CALLBACK


async def test_confirmed_broadcast_reaches_everyone_but_admin(chats, telegram):
    await prepare_broadcast(chats, text="Новость")
    draft_message_id = list_copies(telegram)[0].message_id

    await chats.press(ADMIN_ID, BROADCAST_CONFIRM_CALLBACK)
    await chats.broadcaster.wait_until_idle()

    sent = list_copies(telegram)[1:]
    assert sorted(copy.chat_id for copy in sent) == sorted(USER_IDS)
    assert {(copy.from_chat_id, copy.message_id) for copy in sent} == {(ADMIN_ID, draft_message_id)}
    report = telegram.list_requests(SendMessage)[-1]
    assert report.chat_id == ADMIN_ID
    assert "Доставлено: 3" in report.text


async def test_any_message_type_is_broadcast_as_copy(chats, telegram):
    photo = [{"file_id": "photo-id", "file_unique_id": "u", "width": 90, "height": 90}]
    await prepare_broadcast(chats, photo=photo, caption="Фото дня")

    await chats.press(ADMIN_ID, BROADCAST_CONFIRM_CALLBACK)
    await chats.broadcaster.wait_until_idle()

    assert len(list_copies(telegram)) == 1 + len(USER_IDS)


async def test_blocked_users_are_counted_and_paused(chats, telegram, session_factory):
    # Пользователь посреди курса: следующий день уже запланирован.
    async with session_factory() as session:
        await session.execute(
            update(User)
            .where(User.telegram_id == USER_IDS[1])
            .values(stage=Stage.DAY1, next_send_at=datetime.now(UTC) + timedelta(hours=5))
        )
        await session.commit()
    telegram.blocked_chat_ids.add(USER_IDS[1])
    await prepare_broadcast(chats, text="Новость")

    await chats.press(ADMIN_ID, BROADCAST_CONFIRM_CALLBACK)
    await chats.broadcaster.wait_until_idle()

    report = telegram.list_requests(SendMessage)[-1].text
    assert "Доставлено: 2" in report
    assert "Заблокировали бота: 1" in report
    async with session_factory() as session:
        blocked = await session.get_one(User, USER_IDS[1])
    assert blocked.next_send_at is None


@pytest.mark.parametrize("cancel", ["text", "button"])
async def test_cancelled_broadcast_sends_nothing(chats, telegram, cancel):
    await prepare_broadcast(chats, text="Опечатка")

    if cancel == "text":
        await chats.send(ADMIN_ID, text=CANCEL_BUTTON)
    else:
        await chats.press(ADMIN_ID, BROADCAST_CANCEL_CALLBACK)
    await chats.press(ADMIN_ID, BROADCAST_CONFIRM_CALLBACK)
    await chats.broadcaster.wait_until_idle()

    assert len(list_copies(telegram)) == 1
    assert telegram.list_requests(SendMessage)[-1].text != "Рассылка началась."


async def test_cancel_while_waiting_does_not_become_broadcast(chats, telegram):
    await chats.send(ADMIN_ID, text=SEND_BUTTON)

    await chats.send(ADMIN_ID, text=CANCEL_BUTTON)
    await chats.send(ADMIN_ID, text="обычное сообщение после отмены")

    assert list_copies(telegram) == []


async def test_double_confirm_sends_once(chats, telegram):
    await prepare_broadcast(chats, text="Новость")

    await asyncio.gather(
        chats.press(ADMIN_ID, BROADCAST_CONFIRM_CALLBACK, message_id=777),
        chats.press(ADMIN_ID, BROADCAST_CONFIRM_CALLBACK, message_id=777),
    )
    await chats.broadcaster.wait_until_idle()

    assert len(list_copies(telegram)) == 1 + len(USER_IDS)


async def test_second_admin_can_broadcast_too(chats, telegram):
    await chats.send(OTHER_ADMIN_ID, text=SEND_BUTTON)
    await chats.send(OTHER_ADMIN_ID, text="От второго админа")
    await chats.press(OTHER_ADMIN_ID, BROADCAST_CONFIRM_CALLBACK)
    await chats.broadcaster.wait_until_idle()

    recipients = {copy.chat_id for copy in list_copies(telegram)[1:]}
    assert recipients == {ADMIN_ID, *USER_IDS}


async def test_startup_shows_admin_command_to_admins(chats, bot, telegram):
    await chats.dispatcher.emit_startup(bot=bot, **chats.dispatcher.workflow_data)
    await chats.dispatcher.emit_shutdown(bot=bot, **chats.dispatcher.workflow_data)

    scopes = {request.scope.chat_id for request in telegram.list_requests(SetMyCommands)}
    assert scopes == {ADMIN_ID, OTHER_ADMIN_ID}


def test_admin_ids_are_read_from_comma_separated_env(monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "500, 501")

    settings = Settings(_env_file=None, bot_token=TEST_BOT_TOKEN)

    assert settings.admin_ids == frozenset({500, 501})


async def test_admin_video_during_broadcast_is_broadcast_not_file_id(chats, telegram):
    video = {
        "file_id": "BAACAgIAAxkBAAIBY2c_broadcast-video",
        "file_unique_id": "unique",
        "width": 1920,
        "height": 1080,
        "duration": 60,
    }
    await prepare_broadcast(chats, video=video, caption="Видео для всех")

    assert len(list_copies(telegram)) == 1
    assert "file_id" not in telegram.list_requests(SendMessage)[-1].text
