"""Отправка сообщений и материалов в чат."""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mwa_bot.content.loader import (
    DayItem,
    MediaItem,
    PhotoItem,
    TextItem,
    VideoItem,
    VideoRefItem,
    read_media_bytes,
)
from mwa_bot.db.media import get_file_id, save_file_id

logger = logging.getLogger(__name__)

# Стандартный таймаут aiogram (60 с) покрывает и загрузку тела запроса:
# видео на 50 МБ при канале медленнее ~7 Мбит/с в него не укладывается.
UPLOAD_TIMEOUT_SECONDS = 600


class MaterialSender:
    """Отправляет сообщения и материалы дней; каждый файл загружается в Telegram один раз."""

    def __init__(self, bot: Bot, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._bot = bot
        self._session_factory = session_factory
        self._upload_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def send_text(
        self, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None
    ) -> None:
        """Отправляет одно текстовое сообщение, при необходимости с кнопками."""
        await self._bot.send_message(chat_id, text, reply_markup=reply_markup)

    async def send_photo(
        self,
        chat_id: int,
        photo: PhotoItem,
        caption: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        """Отправляет картинку с подписью и кнопками."""
        await self._send_media(chat_id, photo, caption=caption, reply_markup=reply_markup)

    async def send_day(
        self,
        chat_id: int,
        items: Sequence[DayItem],
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        """Отправляет материалы дня по порядку; кнопки reply_markup - под последним сообщением."""
        last_index = len(items) - 1
        for index, item in enumerate(items):
            markup = reply_markup if index == last_index else None
            match item:
                case TextItem(text=text):
                    await self._bot.send_message(chat_id, text, reply_markup=markup)
                case VideoItem():
                    await self._send_media(chat_id, item, reply_markup=markup)
                case VideoRefItem(file_id=file_id):
                    await self._bot.send_video(chat_id, file_id, reply_markup=markup)

    async def _send_media(self, chat_id: int, item: MediaItem, **options: Any) -> None:
        """Шлёт файл по сохранённому file_id, а в первый раз загружает его."""
        # Пока файл грузится, остальные отправки этого же файла ждут его file_id,
        # иначе при наплыве пользователей он загрузился бы несколько раз.
        async with self._upload_locks[item.sha256]:
            async with self._session_factory() as session:
                file_id = await get_file_id(session, self._bot.id, item.sha256)
            if file_id is None:
                await self._upload_media(chat_id, item, **options)
                return
        await self._call_send_method(chat_id, item, file_id, **options)

    async def _upload_media(self, chat_id: int, item: MediaItem, **options: Any) -> None:
        """Загружает файл и сохраняет его file_id под хешем загруженных байтов."""
        # Грузим ровно те байты, что сверили с хешем: иначе файл, заменённый на диске
        # после старта, закешировался бы под хешем старой версии.
        data = await asyncio.to_thread(read_media_bytes, item)
        message = await self._call_send_method(
            chat_id,
            item,
            BufferedInputFile(data, filename=item.path.name),
            request_timeout=UPLOAD_TIMEOUT_SECONDS,
            **options,
        )
        file_id = extract_file_id(message, item)
        async with self._session_factory() as session:
            await save_file_id(session, self._bot.id, item.sha256, file_id)
        logger.info("Файл %s загружен в Telegram, file_id сохранён", item.path)

    async def _call_send_method(
        self, chat_id: int, item: MediaItem, media: BufferedInputFile | str, **options: Any
    ) -> Message:
        """Вызывает sendVideo или sendPhoto в зависимости от типа файла."""
        if isinstance(item, VideoItem):
            return await self._bot.send_video(chat_id, media, **options)
        return await self._bot.send_photo(chat_id, media, **options)


def extract_file_id(message: Message, item: MediaItem) -> str:
    """Достаёт file_id загруженного файла из ответа Telegram."""
    if isinstance(item, PhotoItem):
        if not message.photo:
            raise RuntimeError(f"Telegram не распознал {item.path} как картинку")
        # Telegram возвращает несколько размеров картинки, последний - самый крупный.
        return message.photo[-1].file_id
    if message.video is None:
        raise RuntimeError(
            f"Telegram не распознал {item.path} как видео "
            f"(видео без звука он превращает в GIF-анимацию)"
        )
    return message.video.file_id
