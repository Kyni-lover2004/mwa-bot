"""Сценарий онбординга целиком: апдейты идут через настоящий диспетчер и фейковый Telegram."""

import asyncio
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageReplyMarkup,
    GetChatMember,
    SendMessage,
    SendPhoto,
    SendVideo,
)
from aiogram.types import BufferedInputFile, Update
from sqlalchemy import update
from telegram_fakes import TEST_BOT_TOKEN, FakeTelegramSession, build_user_json

from mwa_bot.app import build_dispatcher
from mwa_bot.config import Settings
from mwa_bot.content.loader import Content, load_content
from mwa_bot.content.sender import MaterialSender
from mwa_bot.db.models import Stage, User
from mwa_bot.db.users import pause_sending
from mwa_bot.flow import Delivery
from mwa_bot.handlers.onboarding import CHECK_FAILED_ALERT, NOT_SUBSCRIBED_ALERT
from mwa_bot.keyboards import CHECK_SUBSCRIPTION_CALLBACK, WELCOME_CALLBACK
from mwa_bot.scheduler import Scheduler

USER_ID = 1001
REPO_CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"


class PrivateChat:
    """Пользователь в личке с ботом: шлёт команды и жмёт кнопки."""

    def __init__(self, dispatcher: Dispatcher, bot: Bot) -> None:
        self.dispatcher = dispatcher
        self.bot = bot
        self._update_ids = count(1)

    async def send_text(self, text: str) -> None:
        update_id = next(self._update_ids)
        message = {
            "message_id": update_id,
            "date": 0,
            "chat": {"id": USER_ID, "type": "private"},
            "from": build_user_json(USER_ID),
            "text": text,
        }
        await self.feed_raw({"update_id": update_id, "message": message})

    async def press(self, callback_data: str, message_id: int | None = None) -> None:
        """Нажимает кнопку; message_id задаёт, на каком сообщении она была (для двойных нажатий)."""
        update_id = next(self._update_ids)
        button = {"text": "button", "callback_data": callback_data}
        message = {
            "message_id": message_id or update_id,
            "date": 0,
            "chat": {"id": USER_ID, "type": "private"},
            "text": "screen",
            "reply_markup": {"inline_keyboard": [[button]]},
        }
        callback_query = {
            "id": str(update_id),
            "from": build_user_json(USER_ID),
            "chat_instance": "chat",
            "data": callback_data,
            "message": message,
        }
        await self.feed_raw({"update_id": update_id, "callback_query": callback_query})

    async def feed_raw(self, raw_update: dict[str, Any]) -> None:
        update = Update.model_validate(raw_update, context={"bot": self.bot})
        await self.dispatcher.feed_update(self.bot, update)


@pytest.fixture
def content() -> Content:
    return load_content(REPO_CONTENT_DIR)


@pytest.fixture
def make_chat(bot, session_factory, content):
    """Собирает диспетчер так же, как __main__, и возвращает чат с ним."""

    def _make_chat(**settings_overrides: Any) -> PrivateChat:
        settings_values = {
            "bot_token": TEST_BOT_TOKEN,
            "channel_id": "@mwa_test",
            **settings_overrides,
        }
        settings = Settings(_env_file=None, **settings_values)
        sender = MaterialSender(bot, session_factory)
        delivery = Delivery(sender, content, settings)
        scheduler = Scheduler(session_factory, delivery)
        dispatcher = build_dispatcher(
            settings, content, sender, delivery, scheduler, session_factory
        )
        return PrivateChat(dispatcher, bot)

    return _make_chat


async def load_user(session_factory) -> User:
    async with session_factory() as session:
        return await session.get_one(User, USER_ID)


def list_texts(telegram: FakeTelegramSession) -> list[str]:
    return [request.text for request in telegram.list_requests(SendMessage)]


async def test_first_start_shows_welcome_photo_and_saves_user(
    make_chat, telegram, content, session_factory
):
    await make_chat().send_text("/start")

    [welcome] = telegram.list_requests(SendPhoto)
    assert isinstance(welcome.photo, BufferedInputFile)
    assert welcome.caption == content.welcome
    assert welcome.reply_markup.inline_keyboard[0][0].callback_data == WELCOME_CALLBACK
    assert telegram.list_requests(SendMessage) == []
    user = await load_user(session_factory)
    assert (user.stage, user.username) == (Stage.START, f"user{USER_ID}")


async def test_repeated_start_before_onboarding_resends_welcome_by_file_id(make_chat, telegram):
    chat = make_chat()

    await chat.send_text("/start")
    await chat.send_text("/start")

    first, second = telegram.list_requests(SendPhoto)
    assert isinstance(first.photo, BufferedInputFile)
    assert second.photo == "photo-1280"


async def test_subscribed_user_reaches_day1(make_chat, telegram, content, session_factory):
    telegram.subscribe(USER_ID)
    chat = make_chat()

    await chat.send_text("/start")

    before = datetime.now(UTC)
    await chat.press(WELCOME_CALLBACK)

    assert len(telegram.list_requests(GetChatMember)) == 1
    assert len(telegram.list_requests(SendVideo)) == 1
    day1_texts = [item.text for item in content.days[Stage.DAY1][1:]]
    assert list_texts(telegram)[-2:] == day1_texts
    assert len(telegram.list_requests(EditMessageReplyMarkup)) == 1
    user = await load_user(session_factory)
    assert user.stage is Stage.DAY1
    assert user.next_send_at is not None
    assert user.next_send_at >= before + timedelta(hours=24)


async def test_unsubscribed_user_is_asked_to_subscribe_until_subscribed(
    make_chat, telegram, content, session_factory
):
    chat = make_chat(channel_url="https://t.me/mwa_test")
    await chat.send_text("/start")
    await chat.press(WELCOME_CALLBACK)

    prompt = telegram.list_requests(SendMessage)[-1]
    assert prompt.text == content.not_subscribed
    [[subscribe_button], [check_button]] = prompt.reply_markup.inline_keyboard
    assert subscribe_button.url == "https://t.me/mwa_test"
    assert check_button.callback_data == CHECK_SUBSCRIPTION_CALLBACK

    await chat.press(CHECK_SUBSCRIPTION_CALLBACK)
    alert = telegram.list_requests(AnswerCallbackQuery)[-1]
    assert (alert.text, alert.show_alert) == (NOT_SUBSCRIBED_ALERT, True)
    assert telegram.list_requests(SendVideo) == []
    user = await load_user(session_factory)
    assert (user.stage, user.next_send_at) == (Stage.START, None)

    telegram.subscribe(USER_ID)
    await chat.press(CHECK_SUBSCRIPTION_CALLBACK)

    assert len(telegram.list_requests(SendVideo)) == 1
    assert (await load_user(session_factory)).stage is Stage.DAY1


async def test_disabled_check_lets_user_through_without_asking_telegram(
    make_chat, telegram, session_factory
):
    chat = make_chat(channel_id=None)
    await chat.send_text("/start")
    await chat.press(WELCOME_CALLBACK)

    assert telegram.list_requests(GetChatMember) == []
    assert (await load_user(session_factory)).stage is Stage.DAY1


async def test_parallel_presses_send_day1_once(make_chat, telegram, session_factory):
    telegram.subscribe(USER_ID)
    chat = make_chat()
    await chat.send_text("/start")

    await asyncio.gather(chat.press(WELCOME_CALLBACK), chat.press(WELCOME_CALLBACK))

    assert len(telegram.list_requests(SendVideo)) == 1
    assert (await load_user(session_factory)).stage is Stage.DAY1


async def test_repeated_start_and_old_buttons_keep_progress(
    make_chat, telegram, content, session_factory
):
    telegram.subscribe(USER_ID)
    chat = make_chat()
    await chat.send_text("/start")
    await chat.press(WELCOME_CALLBACK)
    progress = await load_user(session_factory)
    sent_before = len(telegram.requests)

    await chat.send_text("/start")
    await chat.press(WELCOME_CALLBACK)
    await chat.press(CHECK_SUBSCRIPTION_CALLBACK)

    assert list_texts(telegram)[-1] == content.in_progress
    new_sends = [
        request
        for request in telegram.requests[sent_before:]
        if isinstance(request, SendMessage | SendVideo | SendPhoto)
    ]
    assert len(new_sends) == 1
    user = await load_user(session_factory)
    assert (user.stage, user.next_send_at) == (progress.stage, progress.next_send_at)


async def test_start_after_final_shows_final_with_site_button(
    make_chat, telegram, content, session_factory
):
    chat = make_chat(
        program_url="https://program.test",
        apply_url="https://apply.test",
        channel_url="https://t.me/channel_test",
    )
    await chat.send_text("/start")
    async with session_factory() as session:
        await session.execute(
            update(User).where(User.telegram_id == USER_ID).values(stage=Stage.FINAL)
        )
        await session.commit()

    await chat.send_text("/start")

    final = telegram.list_requests(SendMessage)[-1]
    assert final.text == content.final
    assert [(button.text, button.url) for [button] in final.reply_markup.inline_keyboard] == [
        ("ОТКРЫТЬ ПРОГРАММУ MWA", "https://program.test"),
        ("ОФОРМИТЬ УЧАСТИЕ", "https://apply.test"),
        ("TELEGRAM-КАНАЛ MWA", "https://t.me/channel_test"),
    ]


async def test_group_chats_are_ignored(make_chat, telegram):
    chat = make_chat()
    update_json = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 0,
            "chat": {"id": -100, "type": "group", "title": "group"},
            "from": build_user_json(USER_ID),
            "text": "/start",
        },
    }

    await chat.feed_raw(update_json)

    assert telegram.requests == []


async def test_user_who_left_channel_is_not_rechecked_by_old_buttons(
    make_chat, telegram, session_factory
):
    telegram.subscribe(USER_ID)
    chat = make_chat()
    await chat.send_text("/start")
    await chat.press(WELCOME_CALLBACK)
    telegram.chat_members.clear()
    sent_before = len(telegram.requests)

    await chat.press(WELCOME_CALLBACK)
    await chat.press(CHECK_SUBSCRIPTION_CALLBACK)

    new_requests = telegram.requests[sent_before:]
    assert not [r for r in new_requests if isinstance(r, GetChatMember | SendMessage | SendVideo)]
    assert (await load_user(session_factory)).stage is Stage.DAY1


async def test_double_tap_shows_next_screen_once(make_chat, telegram, content):
    chat = make_chat()
    await chat.send_text("/start")

    await asyncio.gather(
        chat.press(WELCOME_CALLBACK, message_id=500), chat.press(WELCOME_CALLBACK, message_id=500)
    )

    assert list_texts(telegram).count(content.not_subscribed) == 1


@pytest.mark.parametrize("button", [WELCOME_CALLBACK, CHECK_SUBSCRIPTION_CALLBACK])
async def test_failed_subscription_check_shows_alert_and_keeps_button(
    make_chat, telegram, session_factory, button
):
    telegram.subscribe(USER_ID)
    chat = make_chat()
    await chat.send_text("/start")
    telegram.fail_next(GetChatMember, 400, "Bad Request: member list is inaccessible")

    await chat.press(button)

    alert = telegram.list_requests(AnswerCallbackQuery)[-1]
    assert (alert.text, alert.show_alert) == (CHECK_FAILED_ALERT, True)
    assert telegram.list_requests(EditMessageReplyMarkup) == []
    user = await load_user(session_factory)
    assert (user.stage, user.next_send_at) == (Stage.START, None)

    await chat.press(button)

    assert (await load_user(session_factory)).stage is Stage.DAY1


async def test_stale_callback_does_not_block_transitions(
    make_chat, telegram, content, session_factory
):
    telegram.subscribe(USER_ID)
    chat = make_chat()
    await chat.send_text("/start")
    stale = "Bad Request: query is too old and response timeout expired or query ID is invalid"
    telegram.fail_next(AnswerCallbackQuery, 400, stale)

    await chat.press(WELCOME_CALLBACK)

    assert (await load_user(session_factory)).stage is Stage.DAY1


async def test_user_back_after_blocking_gets_next_day_right_away(
    make_chat, telegram, content, session_factory
):
    telegram.subscribe(USER_ID)
    chat = make_chat()
    await chat.send_text("/start")
    await chat.press(WELCOME_CALLBACK)
    async with session_factory() as session:
        await pause_sending(session, USER_ID)
    videos_before = len(telegram.list_requests(SendVideo))

    await chat.send_text("/start")

    assert len(telegram.list_requests(SendVideo)) == videos_before + 1
    day2_texts = [item.text for item in content.days[Stage.DAY2][1:]]
    assert list_texts(telegram)[-2:] == day2_texts
    user = await load_user(session_factory)
    assert user.stage is Stage.DAY2
    assert user.next_send_at is not None


async def test_user_who_blocked_before_day1_gets_it_on_return_without_recheck(
    make_chat, telegram, session_factory
):
    telegram.subscribe(USER_ID)
    chat = make_chat()
    await chat.send_text("/start")
    telegram.blocked_chat_ids.add(USER_ID)
    # В polling aiogram пишет эту ошибку в лог; повтор планировщика затем ставит паузу.
    with pytest.raises(TelegramForbiddenError):
        await chat.press(WELCOME_CALLBACK)
    async with session_factory() as session:
        await pause_sending(session, USER_ID)
    telegram.blocked_chat_ids.clear()
    telegram.chat_members.clear()
    checks_before = len(telegram.list_requests(GetChatMember))

    await chat.send_text("/start")

    assert len(telegram.list_requests(GetChatMember)) == checks_before
    assert (await load_user(session_factory)).stage is Stage.DAY1


def test_apply_button_leads_to_participation_section_by_default():
    settings = Settings(_env_file=None, bot_token=TEST_BOT_TOKEN)

    assert settings.apply_url == "https://mwamethod.com/#participation"


async def test_day1_ends_with_single_program_button(make_chat, telegram, content):
    telegram.subscribe(USER_ID)
    chat = make_chat(program_url="https://program.test")
    await chat.send_text("/start")

    await chat.press(WELCOME_CALLBACK)

    last = telegram.list_requests(SendMessage)[-1]
    assert last.text == content.days[Stage.DAY1][-1].text
    [[button]] = last.reply_markup.inline_keyboard
    assert (button.text, button.url) == ("ОТКРЫТЬ ПРОГРАММУ MWA", "https://program.test")


def test_program_button_leads_to_program_section_by_default():
    settings = Settings(_env_file=None, bot_token=TEST_BOT_TOKEN)

    assert settings.program_url == "https://mwamethod.com/#program"
