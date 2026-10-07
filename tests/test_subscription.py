"""Тесты проверки подписки на канал."""

from typing import Any

import pytest
from aiogram.methods import GetChatMember
from aiogram.types import ChatMemberAdministrator, ChatMemberRestricted
from telegram_fakes import build_rights_json, build_user_json

from mwa_bot.subscription import is_subscribed

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
