"""Тесты повтора запросов после ограничения частоты Telegram."""

import time

import pytest
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage

from mwa_bot.middlewares.flood_control import RetryAfterMiddleware

FLOOD = "Too Many Requests: retry after 1"


async def test_request_is_retried_after_flood_control(bot, telegram):
    bot.session.middleware(RetryAfterMiddleware())
    telegram.fail_next(SendMessage, 429, FLOOD, retry_after=1)

    started = time.monotonic()
    message = await bot.send_message(1, "text")

    assert time.monotonic() - started >= 1
    assert message.text == "text"
    assert len(telegram.list_requests(SendMessage)) == 2


async def test_flood_error_is_raised_when_retries_run_out(bot, telegram):
    bot.session.middleware(RetryAfterMiddleware(max_retries=1))
    telegram.fail_next(SendMessage, 429, FLOOD, retry_after=1, times=2)

    with pytest.raises(TelegramRetryAfter):
        await bot.send_message(1, "text")

    assert len(telegram.list_requests(SendMessage)) == 2
