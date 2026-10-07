"""Операции с пользователями в базе.

Отправка этапа идёт в три шага: try_lock_sending -> отправка -> finish_sending.
Если отправка упала или бот перезапустился, stage остаётся прежним, а после
истечения блокировки пользователь снова попадает в list_due_users.
"""

from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mwa_bot.db.models import Stage, User


async def get_or_create_user(session: AsyncSession, telegram_id: int, username: str | None) -> User:
    """Возвращает пользователя, создавая его при первом обращении; обновляет username."""
    user = await session.get(User, telegram_id)
    if user is not None:
        if user.username != username:
            user.username = username
        # Commit и без изменений: завершает транзакцию чтения, чтобы не держать
        # соединение из пула, пока хендлер ходит в Telegram.
        await session.commit()
        return user

    user = User(telegram_id=telegram_id, username=username)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        # Двойной /start: параллельный апдейт успел создать запись первым.
        await session.rollback()
        user = await session.get_one(User, telegram_id)
        await session.commit()
    return user


async def mark_subscribed(session: AsyncSession, telegram_id: int, now: datetime) -> None:
    """Запоминает, что пользователь прошёл проверку подписки; повторный вызов ничего не меняет."""
    await session.execute(
        update(User)
        .where(User.telegram_id == telegram_id, User.subscribed_at.is_(None))
        .values(subscribed_at=now)
    )
    await session.commit()


async def try_lock_sending(
    session: AsyncSession, telegram_id: int, stage: Stage, now: datetime, lock_until: datetime
) -> bool:
    """Занимает отправку следующего этапа для пользователя на этапе stage до lock_until.

    False значит, что этап уже другой или отправку занял кто-то ещё: так день не уйдёт дважды.
    """
    result = await session.execute(
        update(User)
        .where(
            User.telegram_id == telegram_id,
            User.stage == stage,
            or_(User.next_send_at.is_(None), User.next_send_at <= now),
        )
        .values(next_send_at=lock_until)
    )
    await session.commit()
    return result.rowcount == 1


async def finish_sending(
    session: AsyncSession,
    telegram_id: int,
    sent_from: Stage,
    sent_to: Stage,
    next_send_at: datetime | None,
) -> bool:
    """Фиксирует доставку этапа sent_to и время следующей отправки; None - слать больше нечего."""
    result = await session.execute(
        update(User)
        .where(User.telegram_id == telegram_id, User.stage == sent_from)
        .values(stage=sent_to, next_send_at=next_send_at)
    )
    await session.commit()
    return result.rowcount == 1


async def pause_sending(session: AsyncSession, telegram_id: int) -> None:
    """Останавливает отправку следующих этапов, не трогая прогресс."""
    await session.execute(
        update(User).where(User.telegram_id == telegram_id).values(next_send_at=None)
    )
    await session.commit()


async def list_due_users(session: AsyncSession, now: datetime) -> list[User]:
    """Возвращает пользователей, у которых подошло время следующей отправки."""
    result = await session.scalars(
        select(User).where(User.next_send_at <= now).order_by(User.next_send_at)
    )
    return list(result)


async def list_user_ids(session: AsyncSession) -> list[int]:
    """Telegram ID всех, кто запускал бота, в порядке первого запуска."""
    result = await session.scalars(select(User.telegram_id).order_by(User.started_at))
    return list(result)
