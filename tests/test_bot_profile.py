"""Тесты обновления описания бота."""

from pathlib import Path

from aiogram.methods import SetMyDescription

from mwa_bot.bot_profile import publish_description
from mwa_bot.content.loader import Content, PhotoItem


def build_content(description: str) -> Content:
    return Content(
        description=description,
        welcome="",
        welcome_photo=PhotoItem(path=Path("welcome.jpg"), sha256="0" * 64),
        not_subscribed="",
        in_progress="",
        final="",
        days={},
    )


async def test_changed_description_is_published(bot, telegram):
    telegram.bot_description = "старое описание"

    await publish_description(bot, build_content("новое описание"))

    assert telegram.bot_description == "новое описание"


async def test_same_description_is_not_rewritten(bot, telegram):
    telegram.bot_description = "описание"

    await publish_description(bot, build_content("описание"))

    assert telegram.list_requests(SetMyDescription) == []


async def test_failed_update_does_not_stop_startup(bot, telegram, caplog):
    telegram.fail_next(SetMyDescription, 400, "Bad Request: description is too long")

    await publish_description(bot, build_content("описание"))

    assert "Не удалось обновить описание бота" in caplog.text
