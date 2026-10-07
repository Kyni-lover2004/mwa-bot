"""Настройки бота из переменных окружения и файла .env."""

from datetime import timedelta
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    """Конфигурация бота: переменные окружения имеют приоритет над .env в текущей папке."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_ignore_empty=True, extra="ignore"
    )

    bot_token: SecretStr
    log_level: LogLevel = "INFO"
    database_url: str = "sqlite+aiosqlite:///data/mwa_bot.db"
    content_dir: Path = Path("content")

    # Канал для проверки подписки (@username или числовой id вида -100...); бот должен быть
    # его администратором. Значение off выключает проверку, например для тестового бота.
    channel_id: str | None = "@mwamethod"
    channel_url: str = "https://t.me/mwamethod"
    # Кнопки финала: страница основной программы и страница заявки или оплаты.
    program_url: str = "https://mwamethod.com"
    apply_url: str = "https://mwamethod.com/#participation"
    day_interval_minutes: int = Field(default=24 * 60, gt=0)

    # Публичный адрес бота. Задан - апдейты приходят по webhook (так бот живёт на хостинге),
    # пуст - бот сам забирает их polling-ом (локальный запуск). Render выставляет
    # RENDER_EXTERNAL_URL сам, поэтому там ничего вписывать не нужно.
    webhook_base_url: str | None = Field(
        default=None, validation_alias=AliasChoices("WEBHOOK_BASE_URL", "RENDER_EXTERNAL_URL")
    )
    port: int = 8080

    @field_validator("channel_id")
    @classmethod
    def disable_channel_check(cls, value: str | None) -> str | None:
        """Превращает CHANNEL_ID=off в None: проверка подписки выключена."""
        if value is not None and value.strip().lower() == "off":
            return None
        return value

    @property
    def day_interval(self) -> timedelta:
        """Пауза между днями."""
        return timedelta(minutes=self.day_interval_minutes)
