"""Тесты режима webhook: HTTP-приложение и остановка по сигналу."""

import asyncio
import os
import signal
import socket
from datetime import timedelta
from pathlib import Path

import aiohttp
import pytest
from aiogram.methods import SendPhoto, SetWebhook
from aiohttp.test_utils import TestClient, TestServer
from telegram_fakes import TEST_BOT_TOKEN, build_user_json

from mwa_bot.app import build_dispatcher
from mwa_bot.config import Settings
from mwa_bot.content.loader import Content, load_content
from mwa_bot.content.sender import MaterialSender
from mwa_bot.flow import Delivery
from mwa_bot.scheduler import Scheduler
from mwa_bot.webhook import (
    HEALTH_PATH,
    WEBHOOK_PATH,
    build_web_app,
    build_webhook_secret,
    serve_webhook,
)

REPO_CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"
BASE_URL = "https://mwa-bot.example"
SECRET = build_webhook_secret(TEST_BOT_TOKEN)
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
START_UPDATE = {
    "update_id": 1,
    "message": {
        "message_id": 1,
        "date": 0,
        "chat": {"id": 1001, "type": "private"},
        "from": build_user_json(1001),
        "text": "/start",
    },
}


@pytest.fixture
def content() -> Content:
    return load_content(REPO_CONTENT_DIR)


@pytest.fixture
def web_app(bot, session_factory, content):
    """HTTP-приложение поверх диспетчера, собранного так же, как в __main__."""
    settings = Settings(_env_file=None, bot_token=TEST_BOT_TOKEN)
    sender = MaterialSender(bot, session_factory)
    delivery = Delivery(sender, content, settings)
    scheduler = Scheduler(session_factory, delivery, poll_interval=timedelta(seconds=1))
    dispatcher = build_dispatcher(settings, content, sender, delivery, scheduler, session_factory)
    return build_web_app(dispatcher, bot, BASE_URL + "/", SECRET)


async def wait_for_requests(telegram, method_type, count: int = 1) -> list:
    """Ждёт, пока фоновая обработка апдейта дойдёт до запросов к Telegram."""
    async with asyncio.timeout(5):
        while len(telegram.list_requests(method_type)) < count:
            await asyncio.sleep(0.01)
    return telegram.list_requests(method_type)


async def test_startup_registers_webhook_with_secret(web_app, telegram):
    async with TestClient(TestServer(web_app)):
        [set_webhook] = telegram.list_requests(SetWebhook)

    assert set_webhook.url == BASE_URL + WEBHOOK_PATH
    assert set_webhook.secret_token == SECRET
    assert {"message", "callback_query"} <= set(set_webhook.allowed_updates)


async def test_update_with_secret_is_handled(web_app, telegram, content):
    async with TestClient(TestServer(web_app)) as client:
        response = await client.post(
            WEBHOOK_PATH, json=START_UPDATE, headers={SECRET_HEADER: SECRET}
        )
        [welcome] = await wait_for_requests(telegram, SendPhoto)

    assert response.status == 200
    assert welcome.caption == content.welcome


async def test_update_without_valid_secret_is_rejected(web_app, telegram):
    async with TestClient(TestServer(web_app)) as client:
        response = await client.post(WEBHOOK_PATH, json=START_UPDATE, headers={SECRET_HEADER: "x"})
        await asyncio.sleep(0.1)

    assert response.status == 401
    assert telegram.list_requests(SendPhoto) == []


async def test_health_endpoint_answers_ok(web_app):
    async with TestClient(TestServer(web_app)) as client:
        response = await client.get(HEALTH_PATH)

        assert (response.status, await response.text()) == (200, "ok")


def find_free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


async def test_server_stops_cleanly_on_sigterm(web_app):
    port = find_free_port()
    server = asyncio.create_task(serve_webhook(web_app, port))

    async with aiohttp.ClientSession() as http, asyncio.timeout(5):
        while True:
            try:
                async with http.get(f"http://127.0.0.1:{port}{HEALTH_PATH}") as response:
                    if response.status == 200:
                        break
            except aiohttp.ClientConnectionError:
                await asyncio.sleep(0.05)

    os.kill(os.getpid(), signal.SIGTERM)
    async with asyncio.timeout(5):
        await server

    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL
