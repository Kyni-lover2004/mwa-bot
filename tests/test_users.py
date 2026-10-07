"""Тесты операций с пользователями."""

import asyncio
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import StatementError

from mwa_bot.db.models import Stage, User
from mwa_bot.db.users import finish_sending, get_or_create_user, list_due_users, try_lock_sending

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
LOCK = timedelta(minutes=10)


async def test_new_user_starts_at_start_stage(session_factory):
    async with session_factory() as session:
        user = await get_or_create_user(session, 1, "alice")

    assert user.stage is Stage.START
    assert user.next_send_at is None
    assert user.started_at.tzinfo is UTC


async def test_existing_user_keeps_progress_and_gets_new_username(session_factory):
    async with session_factory() as session:
        await get_or_create_user(session, 1, "alice")
        await finish_sending(session, 1, Stage.START, Stage.DAY1, NOW + timedelta(hours=24))

    async with session_factory() as session:
        user = await get_or_create_user(session, 1, "alice_new")

    assert user.username == "alice_new"
    assert user.stage is Stage.DAY1


async def test_parallel_start_creates_single_user(session_factory):
    async def start_once(index: int) -> User:
        async with session_factory() as session:
            return await get_or_create_user(session, 1, f"name{index}")

    users = await asyncio.gather(*(start_once(index) for index in range(5)))

    assert {user.telegram_id for user in users} == {1}
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == 1


async def test_lock_blocks_second_attempt_until_it_expires(session_factory):
    async with session_factory() as session:
        await get_or_create_user(session, 1, None)

        assert await try_lock_sending(session, 1, Stage.START, NOW, NOW + LOCK) is True
        assert await try_lock_sending(session, 1, Stage.START, NOW, NOW + LOCK) is False
        later = NOW + LOCK + timedelta(seconds=1)
        assert await try_lock_sending(session, 1, Stage.START, later, later + LOCK) is True


async def test_parallel_locks_let_only_one_through(session_factory):
    async with session_factory() as session:
        await get_or_create_user(session, 1, None)

    async def lock_once() -> bool:
        async with session_factory() as session:
            return await try_lock_sending(session, 1, Stage.START, NOW, NOW + LOCK)

    results = await asyncio.gather(*(lock_once() for _ in range(5)))

    assert results.count(True) == 1


async def test_lock_fails_for_wrong_stage_or_unknown_user(session_factory):
    async with session_factory() as session:
        await get_or_create_user(session, 1, None)

        assert await try_lock_sending(session, 1, Stage.DAY1, NOW, NOW + LOCK) is False
        assert await try_lock_sending(session, 999, Stage.START, NOW, NOW + LOCK) is False


async def test_failed_send_is_retried_after_lock_expires(session_factory):
    async with session_factory() as session:
        await get_or_create_user(session, 1, None)
        await finish_sending(session, 1, Stage.START, Stage.DAY1, NOW)
        assert await try_lock_sending(session, 1, Stage.DAY1, NOW, NOW + LOCK) is True
        # Отправка DAY 2 упала: finish_sending не вызван.

        assert await list_due_users(session, NOW + LOCK - timedelta(seconds=1)) == []
        due = await list_due_users(session, NOW + LOCK)

    assert [(user.telegram_id, user.stage) for user in due] == [(1, Stage.DAY1)]


async def test_finish_sending_moves_stage_and_schedules_next(session_factory):
    next_time = NOW + timedelta(hours=24)
    async with session_factory() as session:
        await get_or_create_user(session, 1, None)
        await try_lock_sending(session, 1, Stage.START, NOW, NOW + LOCK)

        assert await finish_sending(session, 1, Stage.START, Stage.DAY1, next_time) is True
        assert await finish_sending(session, 1, Stage.START, Stage.DAY1, next_time) is False

    async with session_factory() as session:
        user = await session.get_one(User, 1)
    assert user.stage is Stage.DAY1
    assert user.next_send_at == next_time


async def test_list_due_users_compares_moments_across_timezones(session_factory):
    moscow = timezone(timedelta(hours=3))
    async with session_factory() as session:
        for telegram_id in (1, 2, 3):
            await get_or_create_user(session, telegram_id, None)
        # 14:59 по Москве = 11:59 UTC, уже наступило; 15:01 по Москве ещё нет.
        await finish_sending(
            session, 1, Stage.START, Stage.DAY1, datetime(2026, 10, 6, 14, 59, tzinfo=moscow)
        )
        await finish_sending(
            session, 2, Stage.START, Stage.DAY1, datetime(2026, 10, 6, 15, 1, tzinfo=moscow)
        )

        due = await list_due_users(session, NOW)

    assert [user.telegram_id for user in due] == [1]
    assert due[0].next_send_at == datetime(2026, 10, 6, 11, 59, tzinfo=UTC)


async def test_naive_datetime_is_rejected(session_factory):
    async with session_factory() as session:
        await get_or_create_user(session, 1, None)
        with pytest.raises(StatementError, match="naive"):
            await finish_sending(session, 1, Stage.START, Stage.DAY1, datetime(2026, 10, 6, 12))


async def test_get_or_create_user_never_leaves_open_transaction(session_factory):
    async def start_once(index: int) -> bool:
        async with session_factory() as session:
            await get_or_create_user(session, 1, f"name{index}")
            return session.in_transaction()

    results = await asyncio.gather(*(start_once(index) for index in range(5)))

    assert results == [False] * 5
