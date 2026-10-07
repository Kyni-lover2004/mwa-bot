"""Тесты доставки этапов."""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import update

from mwa_bot.content.loader import Content, DayItem, PhotoItem, TextItem
from mwa_bot.db.models import Stage, User
from mwa_bot.db.users import get_or_create_user
from mwa_bot.flow import SEND_LOCK, Delivery, has_passed_onboarding, is_paused
from mwa_bot.keyboards import build_program_keyboard

USER_ID = 1001
DAY_INTERVAL = timedelta(hours=24)
PROGRAM_KEYBOARD = build_program_keyboard(
    "https://program.test", "https://apply.test", "https://t.me/channel_test"
)

CONTENT = Content(
    description="description",
    welcome="welcome",
    welcome_photo=PhotoItem(path=Path("welcome.jpg"), sha256="0" * 64),
    not_subscribed="not subscribed",
    in_progress="in progress",
    final="final",
    days={stage: (TextItem(f"text {stage}"),) for stage in (Stage.DAY1, Stage.DAY2, Stage.DAY3)},
)


class FakeSender:
    """Подменяет MaterialSender: запоминает отправленное или падает как Telegram."""

    def __init__(self, *, fail_on: set[str] | None = None, send_seconds: float = 0) -> None:
        self.fail_on = fail_on or set()
        self.send_seconds = send_seconds
        self.sent: list[str] = []
        # Под каким отправленным текстом какие были кнопки.
        self.keyboards: dict[str, InlineKeyboardMarkup | None] = {}
        self.finished_at: datetime | None = None

    async def send_day(
        self,
        chat_id: int,
        items: Sequence[DayItem],
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        [item] = items
        assert isinstance(item, TextItem)
        # Отправка дня занимает время, как загрузка видео в Telegram.
        await asyncio.sleep(self.send_seconds)
        self._record(item.text)
        self.keyboards[item.text] = reply_markup
        self.finished_at = datetime.now(UTC)

    async def send_text(
        self, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None
    ) -> None:
        self._record(text)
        self.keyboards[text] = reply_markup

    def _record(self, text: str) -> None:
        if text in self.fail_on:
            raise RuntimeError("Telegram недоступен")
        self.sent.append(text)


def build_delivery(sender: FakeSender) -> Delivery:
    return Delivery(sender, CONTENT, DAY_INTERVAL, PROGRAM_KEYBOARD)


async def create_user(session_factory, stage: Stage, next_send_at: datetime | None) -> None:
    """Пользователь, уже прошедший проверку подписки, на этапе stage."""
    async with session_factory() as session:
        await get_or_create_user(session, USER_ID, None)
        await session.execute(
            update(User)
            .where(User.telegram_id == USER_ID)
            .values(stage=stage, next_send_at=next_send_at, subscribed_at=datetime.now(UTC))
        )
        await session.commit()


async def load_user(session_factory) -> User:
    async with session_factory() as session:
        return await session.get_one(User, USER_ID)


async def deliver(session_factory, sender: FakeSender, stage: Stage) -> None:
    async with session_factory() as session:
        await build_delivery(sender).deliver_due(session, USER_ID, stage)


async def test_day1_is_sent_and_timer_starts_after_sending(session_factory):
    await create_user(session_factory, Stage.START, None)
    sender = FakeSender(send_seconds=0.2)

    await deliver(session_factory, sender, Stage.START)
    after = datetime.now(UTC)

    assert sender.sent == ["text day1"]
    user = await load_user(session_factory)
    assert user.stage is Stage.DAY1
    assert sender.finished_at + DAY_INTERVAL <= user.next_send_at <= after + DAY_INTERVAL


async def test_second_delivery_waits_out_long_send_in_same_process(session_factory):
    await create_user(session_factory, Stage.START, None)
    sender = FakeSender(send_seconds=0.3)
    delivery = build_delivery(sender)

    async def deliver_with_expired_lock() -> None:
        # Пока первая отправка ещё идёт, её блокировка в базе "истекла".
        await asyncio.sleep(0.1)
        async with session_factory() as session:
            await session.execute(
                update(User)
                .where(User.telegram_id == USER_ID)
                .values(next_send_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await session.commit()
            await delivery.deliver_due(session, USER_ID, Stage.START)

    async def deliver_once() -> None:
        async with session_factory() as session:
            await delivery.deliver_due(session, USER_ID, Stage.START)

    await asyncio.gather(deliver_once(), deliver_with_expired_lock())

    assert sender.sent == ["text day1"]


async def test_day3_is_followed_by_final_right_away(session_factory):
    await create_user(session_factory, Stage.DAY2, datetime.now(UTC))
    sender = FakeSender()

    await deliver(session_factory, sender, Stage.DAY2)

    assert sender.sent == ["text day3", "final"]
    keyboard = sender.keyboards["final"]
    assert [(button.text, button.url) for [button] in keyboard.inline_keyboard] == [
        ("ОТКРЫТЬ ПРОГРАММУ MWA", "https://program.test"),
        ("ОФОРМИТЬ УЧАСТИЕ", "https://apply.test"),
        ("TELEGRAM-КАНАЛ MWA", "https://t.me/channel_test"),
    ]
    user = await load_user(session_factory)
    assert (user.stage, user.next_send_at) == (Stage.FINAL, None)


async def test_same_stage_is_not_delivered_twice(session_factory):
    await create_user(session_factory, Stage.START, None)
    sender = FakeSender()

    await deliver(session_factory, sender, Stage.START)
    await deliver(session_factory, sender, Stage.START)

    assert sender.sent == ["text day1"]


async def test_failed_send_keeps_stage_and_leaves_lock_for_retry(session_factory):
    await create_user(session_factory, Stage.DAY1, datetime.now(UTC))

    before = datetime.now(UTC)
    with pytest.raises(RuntimeError):
        await deliver(session_factory, FakeSender(fail_on={"text day2"}), Stage.DAY1)

    user = await load_user(session_factory)
    assert user.stage is Stage.DAY1
    assert before + SEND_LOCK <= user.next_send_at <= datetime.now(UTC) + SEND_LOCK


async def test_failed_final_is_retried_without_resending_day3(session_factory):
    await create_user(session_factory, Stage.DAY2, datetime.now(UTC))
    with pytest.raises(RuntimeError):
        await deliver(session_factory, FakeSender(fail_on={"final"}), Stage.DAY2)
    assert (await load_user(session_factory)).stage is Stage.DAY3

    await create_user(session_factory, Stage.DAY3, datetime.now(UTC))
    retry_sender = FakeSender()
    await deliver(session_factory, retry_sender, Stage.DAY3)

    assert retry_sender.sent == ["final"]
    assert (await load_user(session_factory)).stage is Stage.FINAL


MOMENT = datetime(2026, 10, 6, tzinfo=UTC)


@pytest.mark.parametrize(
    ("stage", "subscribed_at", "next_send_at", "passed", "paused"),
    [
        (Stage.START, None, None, False, False),
        (Stage.START, MOMENT, MOMENT, True, False),
        (Stage.START, MOMENT, None, True, True),
        (Stage.DAY1, MOMENT, MOMENT, True, False),
        (Stage.DAY2, MOMENT, None, True, True),
        (Stage.DAY3, MOMENT, None, True, True),
        (Stage.FINAL, MOMENT, None, True, False),
    ],
    ids=["new", "day1-in-flight", "start-paused", "day1", "day2-paused", "day3-paused", "final"],
)
def test_user_state_checks(stage, subscribed_at, next_send_at, passed, paused):
    user = User(
        telegram_id=USER_ID, stage=stage, subscribed_at=subscribed_at, next_send_at=next_send_at
    )

    assert has_passed_onboarding(user) is passed
    assert is_paused(user) is paused


async def test_day1_and_day2_come_with_program_buttons(session_factory):
    await create_user(session_factory, Stage.START, None)
    sender = FakeSender()

    await deliver(session_factory, sender, Stage.START)
    await create_user(session_factory, Stage.DAY1, datetime.now(UTC))
    await deliver(session_factory, sender, Stage.DAY1)

    assert sender.keyboards["text day1"] is PROGRAM_KEYBOARD
    assert sender.keyboards["text day2"] is PROGRAM_KEYBOARD


async def test_day3_has_no_buttons_because_final_brings_them(session_factory):
    await create_user(session_factory, Stage.DAY2, datetime.now(UTC))
    sender = FakeSender()

    await deliver(session_factory, sender, Stage.DAY2)

    assert sender.keyboards["text day3"] is None
    assert sender.keyboards["final"] is PROGRAM_KEYBOARD
