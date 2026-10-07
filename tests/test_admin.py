"""Тесты служебных сообщений админов: file_id присланного видео."""

from pathlib import Path
from typing import Any

import pytest
from aiogram.methods import SendMessage
from aiogram.types import Update
from telegram_fakes import TEST_BOT_TOKEN, build_user_json

from mwa_bot.app import build_dispatcher
from mwa_bot.config import Settings
from mwa_bot.content.loader import load_content
from mwa_bot.content.sender import MaterialSender
from mwa_bot.flow import Delivery
from mwa_bot.handlers.admin import SENT_AS_FILE_REPLY
from mwa_bot.keyboards import build_program_keyboard
from mwa_bot.scheduler import Scheduler

REPO_CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"
ADMIN_ID = 500
FILE_ID = "BAACAgIAAxkBAAIBY2c_admin-video"


@pytest.fixture
def send_from(bot, session_factory):
    """Отправляет боту сообщение от пользователя через собранный диспетчер."""

    async def _send_from(user_id: int, payload: dict[str, Any], **settings: Any) -> None:
        config = Settings(_env_file=None, bot_token=TEST_BOT_TOKEN, **settings)
        content = load_content(REPO_CONTENT_DIR)
        sender = MaterialSender(bot, session_factory)
        delivery = Delivery(
            sender, content, config.day_interval, build_program_keyboard("", "", "")
        )
        scheduler = Scheduler(session_factory, delivery)
        dispatcher = build_dispatcher(config, content, sender, delivery, scheduler, session_factory)
        message = {
            "message_id": 1,
            "date": 0,
            "chat": {"id": user_id, "type": "private"},
            "from": build_user_json(user_id),
            **payload,
        }
        update = Update.model_validate({"update_id": 1, "message": message}, context={"bot": bot})
        await dispatcher.feed_update(bot, update)

    return _send_from


VIDEO = {
    "video": {
        "file_id": FILE_ID,
        "file_unique_id": "unique",
        "width": 1920,
        "height": 1080,
        "duration": 2613,
    }
}
VIDEO_AS_FILE = {
    "document": {
        "file_id": "BQACAgIAAxkBAAIBY2c_document",
        "file_unique_id": "unique-doc",
        "file_name": "IMG_3105.MOV",
        "mime_type": "video/quicktime",
    }
}


def make_channel_owner(telegram, user_id: int) -> None:
    telegram.chat_members[user_id] = {
        "status": "creator",
        "user": build_user_json(user_id),
        "is_anonymous": False,
    }


async def test_channel_admin_gets_file_id_of_sent_video(send_from, telegram):
    make_channel_owner(telegram, ADMIN_ID)

    await send_from(ADMIN_ID, VIDEO)

    [reply] = telegram.list_requests(SendMessage)
    assert f"<code>{FILE_ID}</code>" in reply.text
    assert "01_video.fileid" in reply.text


async def test_regular_user_video_is_ignored(send_from, telegram):
    await send_from(1001, VIDEO)

    assert telegram.list_requests(SendMessage) == []


async def test_admin_is_told_to_send_video_not_as_file(send_from, telegram):
    make_channel_owner(telegram, ADMIN_ID)

    await send_from(ADMIN_ID, VIDEO_AS_FILE)

    [reply] = telegram.list_requests(SendMessage)
    assert reply.text == SENT_AS_FILE_REPLY


async def test_nobody_is_admin_when_channel_check_is_off(send_from, telegram):
    make_channel_owner(telegram, ADMIN_ID)

    await send_from(ADMIN_ID, VIDEO, channel_id="off")

    assert telegram.list_requests(SendMessage) == []
