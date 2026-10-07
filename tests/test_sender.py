"""Тесты отправки материалов дня."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiogram.types import BufferedInputFile

from mwa_bot.content.loader import (
    ContentError,
    DayItem,
    PhotoItem,
    TextItem,
    VideoItem,
    VideoRefItem,
    hash_media_file,
)
from mwa_bot.content.sender import UPLOAD_TIMEOUT_SECONDS, MaterialSender


class FakeBot:
    """Подменяет aiogram.Bot: записывает вызовы и отвечает как Telegram."""

    def __init__(self, bot_id: int = 42, *, returns_video: bool = True) -> None:
        self.id = bot_id
        self.returns_video = returns_video
        self.calls: list[tuple[str, int, object]] = []
        self.video_timeouts: list[int | None] = []
        self.photo_options: list[tuple[str | None, object]] = []
        # Кнопки каждого отправленного сообщения или видео, в порядке отправки.
        self.markups: list[object] = []

    async def send_message(self, chat_id: int, text: str, reply_markup: object = None) -> None:
        self.calls.append(("message", chat_id, text))
        self.markups.append(reply_markup)

    async def send_video(
        self,
        chat_id: int,
        video: object,
        request_timeout: int | None = None,
        reply_markup: object = None,
    ) -> SimpleNamespace:
        self.calls.append(("video", chat_id, video))
        self.markups.append(reply_markup)
        self.video_timeouts.append(request_timeout)
        # Пауза как у сетевого запроса: даёт параллельным отправкам вклиниться.
        await asyncio.sleep(0.01)
        uploaded = SimpleNamespace(file_id=f"file-id-{self.id}") if self.returns_video else None
        return SimpleNamespace(video=uploaded)

    async def send_photo(
        self,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        reply_markup: object = None,
        request_timeout: int | None = None,
    ) -> SimpleNamespace:
        self.calls.append(("photo", chat_id, photo))
        self.photo_options.append((caption, reply_markup))
        sizes = [SimpleNamespace(file_id=f"photo-{size}-{self.id}") for size in (90, 1280)]
        return SimpleNamespace(photo=sizes)

    def list_uploads(self) -> list[BufferedInputFile]:
        """Видео, отправленные файлом, а не по file_id."""
        return [video for kind, _, video in self.calls if isinstance(video, BufferedInputFile)]


@pytest.fixture
def video_path(tmp_path: Path) -> Path:
    path = tmp_path / "01_video.mp4"
    path.write_bytes(b"original video bytes")
    return path


@pytest.fixture
def day(video_path: Path) -> tuple[DayItem, ...]:
    video = VideoItem(path=video_path, sha256=hash_media_file(video_path, 1024))
    return (video, TextItem("text"), TextItem("practice"))


async def test_day_is_sent_in_order_and_video_reused_by_file_id(session_factory, day):
    bot = FakeBot()
    sender = MaterialSender(bot, session_factory)

    await sender.send_day(1, day)
    await sender.send_day(2, day)

    assert [(kind, chat_id) for kind, chat_id, _ in bot.calls] == [
        ("video", 1), ("message", 1), ("message", 1),
        ("video", 2), ("message", 2), ("message", 2),
    ]  # fmt: skip
    [upload] = bot.list_uploads()
    assert upload.data == b"original video bytes"
    assert upload.filename == "01_video.mp4"
    assert bot.calls[3][2] == "file-id-42"


async def test_only_upload_gets_long_timeout(session_factory, day):
    bot = FakeBot()
    sender = MaterialSender(bot, session_factory)

    await sender.send_day(1, day)
    await sender.send_day(2, day)

    assert bot.video_timeouts == [UPLOAD_TIMEOUT_SECONDS, None]


async def test_parallel_sends_upload_video_once(session_factory, day):
    bot = FakeBot()
    sender = MaterialSender(bot, session_factory)

    await asyncio.gather(*(sender.send_day(chat_id, day) for chat_id in range(5)))

    assert len(bot.list_uploads()) == 1
    assert sum(1 for kind, _, _ in bot.calls if kind == "video") == 5


async def test_file_id_cache_survives_restart_but_not_bot_change(session_factory, day):
    await MaterialSender(FakeBot(bot_id=42), session_factory).send_day(1, day)

    restarted = FakeBot(bot_id=42)
    await MaterialSender(restarted, session_factory).send_day(1, day)
    other_bot = FakeBot(bot_id=7)
    await MaterialSender(other_bot, session_factory).send_day(1, day)

    assert restarted.list_uploads() == []
    assert len(other_bot.list_uploads()) == 1


async def test_video_replaced_after_start_is_not_uploaded(session_factory, day, video_path):
    bot = FakeBot()
    video_path.write_bytes(b"new version copied while bot runs")

    with pytest.raises(ContentError, match="перезапусти"):
        await MaterialSender(bot, session_factory).send_day(1, day)

    assert bot.calls == []


async def test_video_turned_into_animation_is_reported(session_factory, day):
    sender = MaterialSender(FakeBot(returns_video=False), session_factory)

    with pytest.raises(RuntimeError, match="GIF"):
        await sender.send_day(1, day)


async def test_photo_is_uploaded_once_and_keeps_caption_and_buttons(session_factory, tmp_path):
    photo_path = tmp_path / "welcome.jpg"
    photo_path.write_bytes(b"jpeg bytes")
    photo = PhotoItem(path=photo_path, sha256=hash_media_file(photo_path, 1024))
    bot = FakeBot()
    sender = MaterialSender(bot, session_factory)

    await sender.send_photo(1, photo, "caption", reply_markup="keyboard")
    await sender.send_photo(2, photo, "caption", reply_markup="keyboard")

    [upload] = bot.list_uploads()
    assert upload.data == b"jpeg bytes"
    assert bot.calls[1][2] == "photo-1280-42"
    assert bot.photo_options == [("caption", "keyboard"), ("caption", "keyboard")]


async def test_video_by_file_id_is_sent_without_upload(session_factory):
    bot = FakeBot()
    sender = MaterialSender(bot, session_factory)

    await sender.send_day(1, (VideoRefItem(file_id="BAACAgIAAxkBAAIBY2c_test"), TextItem("text")))

    assert bot.calls == [("video", 1, "BAACAgIAAxkBAAIBY2c_test"), ("message", 1, "text")]
    assert bot.list_uploads() == []


async def test_day_buttons_go_under_last_message_only(session_factory, day):
    bot = FakeBot()

    await MaterialSender(bot, session_factory).send_day(1, day, reply_markup="buttons")
    await MaterialSender(bot, session_factory).send_day(
        2, (TextItem("text"), VideoRefItem(file_id="BAACAgIAAxkBAAIBY2c_last")), "buttons"
    )

    assert bot.markups == [None, None, "buttons", None, "buttons"]
