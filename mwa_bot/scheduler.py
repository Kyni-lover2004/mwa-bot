"""Фоновая рассылка дней по расписанию."""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mwa_bot.db.models import Stage
from mwa_bot.db.users import list_due_users, pause_sending
from mwa_bot.flow import Delivery

logger = logging.getLogger(__name__)

POLL_INTERVAL = timedelta(seconds=30)
# Сколько пользователей обслуживаем одновременно: каждый день - несколько сообщений подряд,
# а Telegram ограничивает бота примерно 30 сообщениями в секунду.
MAX_PARALLEL_USERS = 5


class Scheduler:
    """Периодически находит пользователей, которым пора слать следующий этап, и шлёт его."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        delivery: Delivery,
        poll_interval: timedelta = POLL_INTERVAL,
    ) -> None:
        self._session_factory = session_factory
        self._delivery = delivery
        self._poll_interval = poll_interval
        self._semaphore = asyncio.Semaphore(MAX_PARALLEL_USERS)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Запускает фоновую задачу; вызывается при старте диспетчера."""
        self._task = asyncio.create_task(self.run_forever(), name="scheduler")
        logger.info("Планировщик запущен, опрос раз в %s", self._poll_interval)

    async def stop(self) -> None:
        """Останавливает фоновую задачу и дожидается её завершения."""
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("Планировщик остановлен")

    async def run_forever(self) -> None:
        """Проходит по расписанию до отмены задачи; сбой одного прохода не останавливает цикл."""
        while True:
            try:
                await self.run_once(datetime.now(UTC))
            except Exception:
                logger.exception(
                    "Проход планировщика упал, следующий через %s", self._poll_interval
                )
            await asyncio.sleep(self._poll_interval.total_seconds())

    async def run_once(self, now: datetime) -> None:
        """Шлёт следующий этап всем, у кого время отправки не позже now."""
        async with self._session_factory() as session:
            due = [(user.telegram_id, user.stage) for user in await list_due_users(session, now)]
        if due:
            logger.info("Пора отправлять: %s польз.", len(due))
        await asyncio.gather(
            *(self._deliver_to_user(telegram_id, stage) for telegram_id, stage in due)
        )

    async def _deliver_to_user(self, telegram_id: int, stage: Stage) -> None:
        """Доставляет пользователю всё, что ему положено сейчас; ошибки пишет в лог."""
        async with self._semaphore, self._session_factory() as session:
            try:
                await self._delivery.deliver_due(session, telegram_id, stage)
            except TelegramForbiddenError:
                await pause_sending(session, telegram_id)
                logger.info("Пользователь %s заблокировал бота, отправка остановлена", telegram_id)
            except Exception:
                # Этап не сдвинут, блокировка истечёт - и следующий проход повторит отправку.
                logger.exception(
                    "Не удалось отправить этап пользователю %s, будет повтор", telegram_id
                )
