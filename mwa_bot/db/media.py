"""Кеш file_id загруженных в Telegram видео."""

from sqlalchemy.ext.asyncio import AsyncSession

from mwa_bot.db.models import MediaFile


async def get_file_id(session: AsyncSession, bot_id: int, sha256: str) -> str | None:
    """Возвращает file_id видео с таким содержимым или None, если бот его ещё не загружал."""
    media = await session.get(MediaFile, (bot_id, sha256))
    return media.file_id if media is not None else None


async def save_file_id(session: AsyncSession, bot_id: int, sha256: str, file_id: str) -> None:
    """Запоминает file_id загруженного видео."""
    await session.merge(MediaFile(bot_id=bot_id, sha256=sha256, file_id=file_id))
    await session.commit()
