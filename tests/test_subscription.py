"""Тесты проверки подписки на канал."""

import logging
from typing import Any

import pytest
from aiogram.methods import GetChatMember
from aiogram.types import ChatMemberAdministrator, ChatMemberRestricted
from telegram_fakes import TEST_BOT_TOKEN, build_rights_json, build_user_json

from mwa_bot.config import Settings
from mwa_bot.subscription import check_channel_access, is_subscribed

USER_ID = 1001


def build_member_json(status: str, **fields: Any) -> dict[str, Any]:
    """Участник канала в формате Bot API."""
    return {"status": status, "user": build_user_json(USER_ID), **fields}


@pytest.mark.parametrize(
    ("member_json", "expected"),
    [
        (build_member_json("creator", is_anonymous=False), True),
        (
            build_member_json(
                "administrator",
                **build_rights_json(ChatMemberAdministrator, exclude={"status", "user"}),
            ),
            True,
        ),
        (build_member_json("member"), True),
        (build_member_json("left"), False),
        (build_member_json("kicked", until_date=0), False),
    ],
    ids=["creator", "administrator", "member", "left", "kicked"],
)
async def test_subscription_by_member_status(bot, telegram, member_json, expected):
    telegram.chat_members[USER_ID] = member_json

    assert await is_subscribed(bot, "@mwa_test", USER_ID) is expected


@pytest.mark.parametrize("is_member", [True, False])
async def test_restricted_member_counts_only_if_still_in_channel(bot, telegram, is_member):
    rights = build_rights_json(
        ChatMemberRestricted, exclude={"status", "user", "is_member", "until_date"}
    )
    telegram.chat_members[USER_ID] = build_member_json(
        "restricted", is_member=is_member, until_date=0, **rights
    )

    assert await is_subscribed(bot, "@mwa_test", USER_ID) is is_member


async def test_disabled_check_does_not_call_telegram(bot, telegram):
    assert await is_subscribed(bot, None, USER_ID) is True
    assert telegram.list_requests(GetChatMember) == []


def build_settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, bot_token=TEST_BOT_TOKEN, **overrides)


def test_check_is_on_for_mwa_channel_by_default_and_off_disables_it():
    assert build_settings().channel_id == "@mwamethod"
    assert build_settings(channel_id=" OFF ").channel_id is None
    assert build_settings(channel_id="-1003986030435").channel_id == "-1003986030435"


async def test_startup_confirms_bot_is_channel_admin(bot, telegram, caplog):
    caplog.set_level(logging.INFO)
    admin_rights = build_rights_json(ChatMemberAdministrator, exclude={"status", "user"})
    telegram.chat_members[bot.id] = {
        "status": "administrator",
        "user": build_user_json(bot.id),
        **admin_rights,
    }

    await check_channel_access(bot, build_settings())

    assert "Проверка подписки включена" in caplog.text
    assert "ERROR" not in caplog.text


async def test_startup_reports_bot_that_is_not_admin(bot, telegram, caplog):
    telegram.chat_members[bot.id] = {"status": "member", "user": build_user_json(bot.id)}

    await check_channel_access(bot, build_settings())

    assert "нужен администратор" in caplog.text


async def test_startup_reports_inaccessible_channel(bot, telegram, caplog):
    telegram.fail_next(GetChatMember, 400, "Bad Request: member list is inaccessible")

    await check_channel_access(bot, build_settings())

    assert "Добавь бота администратором канала" in caplog.text


async def test_startup_warns_when_check_is_off(bot, telegram, caplog):
    await check_channel_access(bot, build_settings(channel_id="off"))

    assert "проверка подписки выключена" in caplog.text
    assert telegram.list_requests(GetChatMember) == []
