"""Настройки бота из переменных окружения и файла .env."""

from datetime import timedelta
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
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

    # Канал для проверки подписки (@username или числовой id); без него проверка выключена.
    channel_id: str | None = None
    channel_url: str = "https://t.me/mwamethod"
    site_url: str = "https://mwamethod.com"
    day_interval_minutes: int = Field(default=24 * 60, gt=0)

    # Публичный адрес бота. Задан - апдейты приходят по webhook (так бот живёт на хостинге),
    # пуст - бот сам забирает их polling-ом (локальный запуск). Render выставляет
    # RENDER_EXTERNAL_URL сам, поэтому там ничего вписывать не нужно.
    webhook_base_url: str | None = Field(
        default=None, validation_alias=AliasChoices("WEBHOOK_BASE_URL", "RENDER_EXTERNAL_URL")
    )
    port: int = 8080

    @property
    def day_interval(self) -> timedelta:
        """Пауза между днями."""
        return timedelta(minutes=self.day_interval_minutes)
