"""Служебное для админов: file_id видео для материалов дней."""

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from mwa_bot.config import Settings
from mwa_bot.subscription import is_channel_admin

FILE_ID_REPLY = (
    "file_id этого видео:\n\n<code>{file_id}</code>\n\n"
    "Чтобы бот отправлял это видео в день, положи эту строку в файл "
    "content/dayN/01_video.fileid вместо 01_video.mp4. "
    "file_id работает только у этого бота."
)
SENT_AS_FILE_REPLY = (
    "Видео пришло файлом. Отправь его как видео, без «Отправить как файл»: "
    "иначе пользователи получат документ, который надо скачивать, а не ролик с плеером."
)


def create_router() -> Router:
    """Создаёт роутер служебных сообщений админов в личке с ботом."""
    router = Router(name=__name__)
    router.message.filter(F.chat.type == ChatType.PRIVATE)
    router.message.register(handle_admin_video, F.video)
    router.message.register(handle_video_sent_as_file, F.document.mime_type.startswith("video/"))
    return router


async def handle_admin_video(message: Message, bot: Bot, settings: Settings) -> None:
    """Отвечает админу канала file_id присланного видео; остальным не отвечает."""
    if message.from_user is None or message.video is None:
        return
    if not await is_admin(bot, settings, message.from_user.id):
        return
    await message.answer(FILE_ID_REPLY.format(file_id=message.video.file_id))


async def handle_video_sent_as_file(message: Message, bot: Bot, settings: Settings) -> None:
    """Подсказывает админу, что видео нужно отправить как видео, а не файлом."""
    if message.from_user is None:
        return
    if await is_admin(bot, settings, message.from_user.id):
        await message.answer(SENT_AS_FILE_REPLY)


async def is_admin(bot: Bot, settings: Settings, user_id: int) -> bool:
    """Загружать видео могут админы из ADMIN_IDS и админы канала."""
    return user_id in settings.admin_ids or await is_channel_admin(
        bot, settings.channel_id, user_id
    )
