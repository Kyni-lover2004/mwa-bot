"""Фейковый Telegram для тестов: сессия aiogram без сети."""

import json
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteWebhook,
    EditMessageReplyMarkup,
    GetChatMember,
    GetMyDescription,
    SendMessage,
    SendPhoto,
    SendVideo,
    SetMyDescription,
    SetWebhook,
    TelegramMethod,
)
from pydantic import BaseModel

TEST_BOT_TOKEN = "123456:TEST"


def build_rights_json(model: type[BaseModel], *, exclude: set[str]) -> dict[str, Any]:
    """Все обязательные поля модели участника канала, кроме exclude, со значением False."""
    return {
        name: False
        for name, field in model.model_fields.items()
        if field.is_required() and name not in exclude
    }


def build_error(
    status_code: int, description: str, *, retry_after: int | None = None
) -> tuple[int, dict[str, Any]]:
    """Ответ Telegram с ошибкой: HTTP-код и JSON-тело."""
    body: dict[str, Any] = {"ok": False, "error_code": status_code, "description": description}
    if retry_after is not None:
        body["parameters"] = {"retry_after": retry_after}
    return status_code, body


def build_user_json(user_id: int) -> dict[str, Any]:
    """Пользователь Telegram в формате Bot API."""
    return {"id": user_id, "is_bot": False, "first_name": "Test", "username": f"user{user_id}"}


class FakeTelegramSession(BaseSession):
    """Сессия aiogram без сети: записывает запросы и отвечает JSON-ом, как Telegram.

    Ответы проходят через check_response, то есть через настоящий разбор aiogram.
    """

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self.chat_members: dict[int, dict[str, Any]] = {}
        self.blocked_chat_ids: set[int] = set()
        self.bot_description = ""
        self._failures: dict[type, list[tuple[int, dict[str, Any]]]] = {}
        self._keyboards_removed: set[tuple[int | str, int | None]] = set()
        self._last_message_id = 0

    def fail_next(
        self,
        method_type: type,
        status_code: int,
        description: str,
        *,
        retry_after: int | None = None,
        times: int = 1,
    ) -> None:
        """Следующие times запросов этого типа получат ошибку вместо ответа."""
        error = build_error(status_code, description, retry_after=retry_after)
        self._failures.setdefault(method_type, []).extend([error] * times)

    def subscribe(self, user_id: int) -> None:
        """Делает пользователя участником канала."""
        self.chat_members[user_id] = {"status": "member", "user": build_user_json(user_id)}

    def list_requests[MethodT](self, method_type: type[MethodT]) -> list[MethodT]:
        """Запросы к Telegram указанного типа в порядке отправки."""
        return [request for request in self.requests if isinstance(request, method_type)]

    async def make_request(
        self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None
    ) -> Any:
        self.requests.append(method)
        status_code, body = self._build_response(method)
        response = self.check_response(
            bot=bot, method=method, status_code=status_code, content=json.dumps(body)
        )
        return response.result

    def _build_response(self, method: TelegramMethod[Any]) -> tuple[int, dict[str, Any]]:
        """HTTP-код и JSON-тело, которыми Telegram ответил бы на запрос."""
        if queued := self._failures.get(type(method)):
            return queued.pop(0)
        is_send = isinstance(method, SendMessage | SendVideo | SendPhoto)
        if is_send and method.chat_id in self.blocked_chat_ids:
            return build_error(403, "Forbidden: bot was blocked by the user")
        if isinstance(method, EditMessageReplyMarkup):
            message_key = (method.chat_id, method.message_id)
            if message_key in self._keyboards_removed:
                return build_error(400, "Bad Request: message is not modified")
            self._keyboards_removed.add(message_key)
        return 200, {"ok": True, "result": self._build_result(method)}

    def _build_result(self, method: TelegramMethod[Any]) -> Any:
        """Ответ Telegram на запрос в формате Bot API."""
        match method:
            case GetChatMember():
                left = {"status": "left", "user": build_user_json(method.user_id)}
                return self.chat_members.get(method.user_id, left)
            case SendMessage() | SendVideo() | SendPhoto():
                self._last_message_id += 1
                message: dict[str, Any] = {
                    "message_id": self._last_message_id,
                    "date": 0,
                    "chat": {"id": method.chat_id, "type": "private"},
                }
                if isinstance(method, SendPhoto):
                    message["photo"] = [
                        {
                            "file_id": f"photo-{size}",
                            "file_unique_id": f"u{size}",
                            "width": size,
                            "height": size,
                        }
                        for size in (90, 320, 1280)
                    ]
                    message["caption"] = method.caption
                elif isinstance(method, SendVideo):
                    message["video"] = {
                        "file_id": "video-file-id",
                        "file_unique_id": "video-unique-id",
                        "width": 640,
                        "height": 360,
                        "duration": 4,
                    }
                else:
                    message["text"] = method.text
                return message
            case GetMyDescription():
                return {"description": self.bot_description}
            case SetMyDescription():
                self.bot_description = method.description or ""
                return True
            case AnswerCallbackQuery() | EditMessageReplyMarkup() | SetWebhook() | DeleteWebhook():
                return True
        raise AssertionError(f"Тест не ожидал запрос {type(method).__name__}")

    async def stream_content(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def close(self) -> None:
        pass
