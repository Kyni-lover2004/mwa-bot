"""Рассылка копии сообщения всем пользователям бота."""

import asyncio
import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mwa_bot.db.users import list_user_ids, pause_sending

logger = logging.getLogger(__name__)

# Telegram пропускает от бота около 30 сообщений в секунду; держимся ниже с запасом.
SEND_INTERVAL_SECONDS = 0.05


@dataclass
class BroadcastResult:
    """Итог рассылки."""

    delivered: int = 0
    blocked: int = 0
    failed: int = 0


class Broadcaster:
    """Рассылает копию сообщения в фоне и присылает админу итог."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._tasks: set[asyncio.Task[None]] = set()

    async def count_recipients(self, admin_id: int) -> int:
        """Сколько человек получит рассылку: все пользователи, кроме самого админа."""
        return len(await self._list_recipients(admin_id))

    def start(self, bot: Bot, admin_id: int, from_chat_id: int, message_id: int) -> None:
        """Запускает рассылку в фоне, чтобы не держать обработку нажатия кнопки."""
        task = asyncio.create_task(
            self._run(bot, admin_id, from_chat_id, message_id), name="broadcast"
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_until_idle(self) -> None:
        """Дожидается окончания всех запущенных рассылок."""
        await asyncio.gather(*self._tasks)

    async def _run(self, bot: Bot, admin_id: int, from_chat_id: int, message_id: int) -> None:
        """Рассылает и сообщает админу итог; сбой тоже сообщает, а не теряет молча."""
        try:
            result = await self._send_to_all(bot, admin_id, from_chat_id, message_id)
        except Exception:
            logger.exception("Рассылка оборвалась")
            await bot.send_message(
                admin_id, "Рассылка оборвалась из-за ошибки, подробности в логах."
            )
            return
        logger.info("Рассылка завершена: %s", result)
        await bot.send_message(
            admin_id,
            f"Рассылка завершена.\nДоставлено: {result.delivered}\n"
            f"Заблокировали бота: {result.blocked}\n"
            f"Не доставлено по другим причинам: {result.failed}",
        )

    async def _send_to_all(
        self, bot: Bot, admin_id: int, from_chat_id: int, message_id: int
    ) -> BroadcastResult:
        """Копирует сообщение каждому пользователю по очереди."""
        result = BroadcastResult()
        for telegram_id in await self._list_recipients(admin_id):
            try:
                await bot.copy_message(
                    chat_id=telegram_id, from_chat_id=from_chat_id, message_id=message_id
                )
            except TelegramForbiddenError:
                result.blocked += 1
                # Так же, как планировщик: заблокировавшему бота дни больше не шлём.
                async with self._session_factory() as session:
                    await pause_sending(session, telegram_id)
            except TelegramAPIError as exc:
                result.failed += 1
                logger.warning("Рассылка: не доставлено пользователю %s: %s", telegram_id, exc)
            else:
                result.delivered += 1
            await asyncio.sleep(SEND_INTERVAL_SECONDS)
        return result

    async def _list_recipients(self, admin_id: int) -> list[int]:
        """Все пользователи бота, кроме админа: он уже видел сообщение в предпросмотре."""
        async with self._session_factory() as session:
            return [user_id for user_id in await list_user_ids(session) if user_id != admin_id]
