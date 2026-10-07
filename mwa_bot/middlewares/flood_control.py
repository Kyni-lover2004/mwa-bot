"""Middleware запросов к Telegram: повтор после ограничения частоты (429)."""

import asyncio
import logging

from aiogram import Bot
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import Response, TelegramMethod
from aiogram.methods.base import TelegramType

logger = logging.getLogger(__name__)


class RetryAfterMiddleware(BaseRequestMiddleware):
    """Повторяет запрос, на который Telegram ответил 429, выждав указанное им время.

    Повтор идёт на уровне одного запроса, поэтому день не пересылается целиком.
    """

    def __init__(self, max_retries: int = 3) -> None:
        self.max_retries = max_retries

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        for attempt in range(1, self.max_retries + 1):
            try:
                return await make_request(bot, method)
            except TelegramRetryAfter as exc:
                logger.warning(
                    "Telegram ограничил частоту на %s, повтор %s/%s через %s с",
                    type(method).__name__,
                    attempt,
                    self.max_retries,
                    exc.retry_after,
                )
                await asyncio.sleep(exc.retry_after)
        return await make_request(bot, method)
