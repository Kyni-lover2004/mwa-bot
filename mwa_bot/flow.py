"""Прогресс пользователя по этапам: что отправить следующим и когда."""

import logging
from datetime import UTC, datetime, timedelta

from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from mwa_bot.content.loader import Content
from mwa_bot.content.sender import UPLOAD_TIMEOUT_SECONDS, MaterialSender
from mwa_bot.db.models import Stage, User
from mwa_bot.db.users import finish_sending, try_lock_sending

logger = logging.getLogger(__name__)

NEXT_STAGE = {
    Stage.START: Stage.DAY1,
    Stage.DAY1: Stage.DAY2,
    Stage.DAY2: Stage.DAY3,
    Stage.DAY3: Stage.FINAL,
}

# Под какими днями кнопки программы, заявки и канала. В DAY 3 их нет: финал с теми же
# кнопками приходит сразу следом.
DAYS_WITH_PROGRAM_BUTTONS = frozenset({Stage.DAY1, Stage.DAY2})

# Через столько планировщик считает отправку оборвавшейся (сбой, перезапуск) и повторяет её.
# Хватает на одну загрузку видео с запасом; более долгую отправку внутри процесса
# от повтора защищает Delivery._in_flight.
SEND_LOCK = timedelta(seconds=UPLOAD_TIMEOUT_SECONDS) + timedelta(minutes=5)


def has_passed_onboarding(user: User) -> bool:
    """True, если пользователь прошёл проверку подписки."""
    return user.subscribed_at is not None


def is_paused(user: User) -> bool:
    """True, если этапы не закончены, но отправка остановлена: пользователь блокировал бота."""
    return (
        has_passed_onboarding(user) and user.stage is not Stage.FINAL and user.next_send_at is None
    )


class Delivery:
    """Доставляет пользователю следующий этап и планирует отправку после него."""

    def __init__(
        self,
        sender: MaterialSender,
        content: Content,
        day_interval: timedelta,
        program_keyboard: InlineKeyboardMarkup,
    ) -> None:
        self._sender = sender
        self._content = content
        self._day_interval = day_interval
        self._program_keyboard = program_keyboard
        self._in_flight: set[int] = set()

    async def deliver_due(self, session: AsyncSession, telegram_id: int, stage: Stage) -> None:
        """Отправляет этап, следующий за stage, а после DAY 3 сразу и финал."""
        # Блокировка в базе может истечь посреди очень долгой отправки (очередь на загрузку
        # видео, повторы после 429); вторую параллельную отправку тому же человеку не начинаем.
        if telegram_id in self._in_flight:
            return
        self._in_flight.add(telegram_id)
        try:
            delivered = await self._deliver_next(session, telegram_id, stage)
            if delivered is Stage.DAY3:
                await self._deliver_next(session, telegram_id, Stage.DAY3)
        finally:
            self._in_flight.discard(telegram_id)

    async def send_final(self, chat_id: int) -> None:
        """Отправляет финальное сообщение с кнопками перехода к программе и каналу."""
        await self._sender.send_text(chat_id, self._content.final, self._program_keyboard)

    async def _deliver_next(
        self, session: AsyncSession, telegram_id: int, stage: Stage
    ) -> Stage | None:
        """Отправляет этап после stage; None - его уже отправляет или отправил кто-то другой."""
        next_stage = NEXT_STAGE[stage]
        now = datetime.now(UTC)
        if not await try_lock_sending(session, telegram_id, stage, now, now + SEND_LOCK):
            return None

        await self._send_stage(telegram_id, next_stage)
        await finish_sending(
            session, telegram_id, stage, next_stage, self._plan_next_send(next_stage)
        )
        logger.info("Пользователю %s отправлен этап %s", telegram_id, next_stage)
        return next_stage

    async def _send_stage(self, chat_id: int, stage: Stage) -> None:
        """Отправляет материалы этапа: день целиком или финальное сообщение."""
        if stage is Stage.FINAL:
            await self.send_final(chat_id)
        else:
            keyboard = self._program_keyboard if stage in DAYS_WITH_PROGRAM_BUTTONS else None
            await self._sender.send_day(chat_id, self._content.days[stage], keyboard)

    def _plan_next_send(self, delivered: Stage) -> datetime | None:
        """Когда слать этап после delivered; таймер по ТЗ идёт от конца отправки."""
        now = datetime.now(UTC)
        match delivered:
            case Stage.FINAL:
                return None
            case Stage.DAY3:
                # Финал по договорённости приходит сразу после DAY 3.
                return now
            case _:
                return now + self._day_interval
