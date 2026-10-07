"""Настройка логирования для всего приложения."""

import logging

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def setup_logging(level: str) -> None:
    """Настраивает корневой логгер и приглушает шумные логгеры библиотек."""
    logging.basicConfig(level=level, format=LOG_FORMAT)

    # aiogram пишет INFO-строку на каждый апдейт; оставляем её только для отладки.
    if level != "DEBUG":
        logging.getLogger("aiogram.event").setLevel(logging.WARNING)
