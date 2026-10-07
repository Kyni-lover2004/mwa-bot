"""Тесты планировщика: настоящая доставка через фейковый Telegram."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aiogram.methods import GetChatMember, SendMessage, SendVideo
from sqlalchemy import update

from mwa_bot.app import build_dispatcher
from mwa_bot.config import Settings
from mwa_bot.content.loader import Content, load_content
from mwa_bot.content.sender import MaterialSender
from mwa_bot.db.models import Stage, User
from mwa_bot.db.users import get_or_create_user
from mwa_bot.flow import SEND_LOCK, Delivery
from mwa_bot.keyboards import build_final_keyboard
from mwa_bot.scheduler import Scheduler

REPO_CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"
DAY_INTERVAL = timedelta(hours=24)
# Блокировка отправки сверяется с реальными часами, поэтому "сейчас" в тестах - настоящее.
NOW = datetime.now(UTC)


@pytest.fixture
def content() -> Content:
    return load_content(REPO_CONTENT_DIR)


@pytest.fixture
def scheduler(bot, session_factory, content) -> Scheduler:
    final_keyboard = build_final_keyboard(
        "https://program.test", "https://apply.test", "https://t.me/channel_test"
    )
    delivery = Delivery(MaterialSender(bot, session_factory), content, DAY_INTERVAL, final_keyboard)
    return Scheduler(session_factory, delivery, poll_interval=timedelta(milliseconds=10))


async def create_user(
    session_factory, telegram_id: int, stage: Stage, next_send_at: datetime | None
) -> None:
    async with session_factory() as session:
        await get_or_create_user(session, telegram_id, None)
        await session.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(stage=stage, next_send_at=next_send_at, subscribed_at=NOW)
        )
        await session.commit()


async def load_user(session_factory, telegram_id: int) -> User:
    async with session_factory() as session:
        return await session.get_one(User, telegram_id)


def list_recipients(telegram, method_type) -> list[int]:
    return [request.chat_id for request in telegram.list_requests(method_type)]


async def test_only_due_users_get_next_day(scheduler, session_factory, telegram):
    await create_user(session_factory, 1, Stage.DAY1, NOW - timedelta(seconds=1))
    await create_user(session_factory, 2, Stage.DAY1, NOW + timedelta(minutes=1))
    await create_user(session_factory, 3, Stage.START, None)

    await scheduler.run_once(NOW)

    assert list_recipients(telegram, SendVideo) == [1]
    assert (await load_user(session_factory, 1)).stage is Stage.DAY2
    assert (await load_user(session_factory, 2)).stage is Stage.DAY1
    assert (await load_user(session_factory, 3)).stage is Stage.START


async def test_day3_and_final_go_out_together(scheduler, session_factory, telegram, content):
    await create_user(session_factory, 1, Stage.DAY2, NOW)

    await scheduler.run_once(NOW)

    final = telegram.list_requests(SendMessage)[-1]
    assert final.text == content.final
    assert [(button.text, button.url) for [button] in final.reply_markup.inline_keyboard] == [
        ("ОТКРЫТЬ ПРОГРАММУ MWA", "https://program.test"),
        ("ОФОРМИТЬ УЧАСТИЕ", "https://apply.test"),
        ("TELEGRAM-КАНАЛ MWA", "https://t.me/channel_test"),
    ]
    user = await load_user(session_factory, 1)
    assert (user.stage, user.next_send_at) == (Stage.FINAL, None)


async def test_day1_is_retried_after_failed_first_attempt(scheduler, session_factory, telegram):
    # Пользователь прошёл проверку подписки, но отправка DAY 1 упала и блокировка истекла.
    await create_user(session_factory, 1, Stage.START, NOW - timedelta(seconds=1))

    await scheduler.run_once(NOW)

    assert list_recipients(telegram, SendVideo) == [1]
    assert (await load_user(session_factory, 1)).stage is Stage.DAY1


async def test_failed_send_is_retried_after_lock_expires(scheduler, session_factory, telegram):
    await create_user(session_factory, 1, Stage.DAY1, NOW)
    telegram.fail_next(SendVideo, 500, "Internal Server Error")

    await scheduler.run_once(NOW)

    user = await load_user(session_factory, 1)
    assert user.stage is Stage.DAY1
    assert user.next_send_at > datetime.now(UTC) + SEND_LOCK - timedelta(minutes=1)

    # Блокировка истекла: как будто прошло SEND_LOCK.
    await create_user(session_factory, 1, Stage.DAY1, datetime.now(UTC) - timedelta(seconds=1))
    await scheduler.run_once(datetime.now(UTC))

    assert (await load_user(session_factory, 1)).stage is Stage.DAY2


async def test_user_who_blocked_bot_is_paused_and_others_still_served(
    scheduler, session_factory, telegram
):
    await create_user(session_factory, 1, Stage.DAY1, NOW)
    await create_user(session_factory, 2, Stage.DAY1, NOW)
    telegram.blocked_chat_ids.add(1)

    await scheduler.run_once(NOW)

    blocked = await load_user(session_factory, 1)
    assert (blocked.stage, blocked.next_send_at) == (Stage.DAY1, None)
    assert (await load_user(session_factory, 2)).stage is Stage.DAY2

    await scheduler.run_once(NOW + timedelta(days=30))
    assert list_recipients(telegram, SendVideo).count(1) == 1


async def test_background_loop_survives_failed_pass(scheduler, session_factory, telegram):
    await create_user(session_factory, 1, Stage.DAY1, NOW)
    original_run_once = scheduler.run_once
    calls = 0

    async def fail_first_pass(now: datetime) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("база недоступна")
        await original_run_once(now)

    scheduler.run_once = fail_first_pass
    await scheduler.start()
    try:
        async with asyncio.timeout(5):
            while (await load_user(session_factory, 1)).stage is not Stage.DAY2:
                await asyncio.sleep(0.01)
    finally:
        await scheduler.stop()

    assert calls >= 2


async def test_dispatcher_hooks_publish_description_and_run_scheduler(
    bot, telegram, scheduler, session_factory, content
):
    settings = Settings(_env_file=None, bot_token="123456:TEST")
    sender = MaterialSender(bot, session_factory)
    delivery = Delivery(sender, content, DAY_INTERVAL, build_final_keyboard("", "", ""))
    dispatcher = build_dispatcher(settings, content, sender, delivery, scheduler, session_factory)
    await create_user(session_factory, 1, Stage.DAY1, NOW)

    # Так же, как start_polling: хукам передаются бот и общие зависимости диспетчера.
    await dispatcher.emit_startup(bot=bot, **dispatcher.workflow_data)
    try:
        async with asyncio.timeout(5):
            while (await load_user(session_factory, 1)).stage is not Stage.DAY2:
                await asyncio.sleep(0.01)
    finally:
        await dispatcher.emit_shutdown(bot=bot, **dispatcher.workflow_data)

    await create_user(session_factory, 2, Stage.DAY1, NOW)
    await asyncio.sleep(0.1)
    assert (await load_user(session_factory, 2)).stage is Stage.DAY1
    assert telegram.bot_description == content.description
    # При старте бот проверил, что он администратор канала подписки.
    assert [(r.chat_id, r.user_id) for r in telegram.list_requests(GetChatMember)] == [
        ("@mwamethod", bot.id)
    ]
