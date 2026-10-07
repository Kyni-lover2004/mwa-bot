"""ORM-модели бота."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class Stage(StrEnum):
    """Последний доставленный пользователю этап 3-дневного знакомства."""

    START = "start"
    DAY1 = "day1"
    DAY2 = "day2"
    DAY3 = "day3"
    FINAL = "final"


class UtcDateTime(TypeDecorator[datetime]):
    """Пишет время в базу как UTC без зоны и читает обратно как aware-datetime в UTC.

    SQLite не хранит часовой пояс, а сравнение naive и aware datetime в Python падает.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        """Приводит aware-datetime к UTC и отбрасывает зону; naive отклоняет."""
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(f"Ожидается datetime с часовым поясом, получен naive: {value}")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        """Помечает прочитанное из базы время как UTC."""
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    """Базовый класс для всех моделей."""


class User(Base):
    """Пользователь бота и его прогресс по дням."""

    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64))
    stage: Mapped[Stage] = mapped_column(
        Enum(
            Stage,
            native_enum=False,
            length=16,
            values_callable=lambda stage_enum: [member.value for member in stage_enum],
        ),
        default=Stage.START,
    )
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(UTC))
    # Когда пользователь прошёл проверку подписки; None - ещё не проходил.
    subscribed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    # Когда слать следующий этап. Пока идёт отправка, тут время конца блокировки:
    # если отправка не завершилась, после него этап отправится повторно. None - ничего не ждём.
    next_send_at: Mapped[datetime | None] = mapped_column(UtcDateTime, index=True)


class MediaFile(Base):
    """Кеш file_id: локальное видео, уже загруженное в Telegram.

    file_id действует только для бота, который загрузил файл, поэтому ключ включает bot_id.
    """

    __tablename__ = "media_files"

    bot_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_id: Mapped[str] = mapped_column(String(255))
