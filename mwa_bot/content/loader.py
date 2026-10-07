"""Загрузка контента из папки при старте бота."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from mwa_bot.content.telegram_html import count_utf16_units, find_markup_errors
from mwa_bot.db.models import Stage

# Лимиты загрузки через обычный Bot API; для больших видео нужен локальный Bot API сервер.
MAX_VIDEO_BYTES = 50 * 1024 * 1024
MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_MESSAGE_LENGTH = 4096
MAX_CAPTION_LENGTH = 1024
MAX_DESCRIPTION_LENGTH = 512

DAY_DIRS = {Stage.DAY1: "day1", Stage.DAY2: "day2", Stage.DAY3: "day3"}
WELCOME_PHOTO_NAMES = ("welcome.jpg", "welcome.jpeg", "welcome.png")
# file_id Telegram - строка из латиницы, цифр, _ и -.
FILE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{20,}")


class ContentError(Exception):
    """Контент в папке неполный или в неподдерживаемом формате."""


@dataclass(frozen=True)
class TextItem:
    """Текстовое сообщение в HTML-разметке Telegram."""

    text: str


@dataclass(frozen=True)
class VideoItem:
    """Локальное видео; sha256 нужен, чтобы заметить замену файла."""

    path: Path
    sha256: str


@dataclass(frozen=True)
class PhotoItem:
    """Локальная картинка; sha256 нужен, чтобы заметить замену файла."""

    path: Path
    sha256: str


@dataclass(frozen=True)
class VideoRefItem:
    """Видео, уже загруженное в Telegram: бот отправляет его по file_id без ограничения размера."""

    file_id: str


DayItem = TextItem | VideoItem | VideoRefItem
MediaItem = VideoItem | PhotoItem


@dataclass(frozen=True)
class Content:
    """Все тексты и материалы, которые отправляет бот."""

    # Описание бота («Что умеет этот бот?»): обычный текст без разметки.
    description: str
    welcome: str
    welcome_photo: PhotoItem
    not_subscribed: str
    in_progress: str
    final: str
    days: dict[Stage, tuple[DayItem, ...]]


def load_content(content_dir: Path) -> Content:
    """Читает тексты экранов и материалы дней; при любой проблеме бросает ContentError."""
    return Content(
        description=read_plain_text(content_dir / "description.txt", MAX_DESCRIPTION_LENGTH),
        welcome=read_text(content_dir / "welcome.html", MAX_CAPTION_LENGTH),
        welcome_photo=find_welcome_photo(content_dir),
        not_subscribed=read_text(content_dir / "not_subscribed.html"),
        in_progress=read_text(content_dir / "in_progress.html"),
        final=read_text(content_dir / "final.html"),
        days={stage: load_day(content_dir / dirname) for stage, dirname in DAY_DIRS.items()},
    )


def find_welcome_photo(content_dir: Path) -> PhotoItem:
    """Находит картинку экрана WELCOME под одним из допустимых имён."""
    for name in WELCOME_PHOTO_NAMES:
        path = content_dir / name
        if path.is_file():
            return PhotoItem(path=path, sha256=hash_media_file(path, MAX_PHOTO_BYTES))
    raise ContentError(
        f"Нет картинки WELCOME: положи в {content_dir} {' или '.join(WELCOME_PHOTO_NAMES)}"
    )


def load_day(day_dir: Path) -> tuple[DayItem, ...]:
    """Читает файлы дня в порядке имён, пропуская скрытые (.DS_Store и т.п.)."""
    if not day_dir.is_dir():
        raise ContentError(f"Нет папки дня: {day_dir}")
    paths = sorted(path for path in day_dir.iterdir() if not path.name.startswith("."))
    if not paths:
        raise ContentError(f"Папка дня пустая: {day_dir}")
    return tuple(load_item(path) for path in paths)


def load_item(path: Path) -> DayItem:
    """Превращает файл дня в элемент для отправки по его расширению."""
    match path.suffix.lower():
        case ".html":
            return TextItem(read_text(path))
        case ".mp4":
            return VideoItem(path=path, sha256=hash_media_file(path, MAX_VIDEO_BYTES))
        case ".fileid":
            return load_video_ref(path)
    raise ContentError(f"Неподдерживаемый файл {path}: в папке дня допустимы .html, .mp4 и .fileid")


def load_video_ref(path: Path) -> VideoRefItem:
    """Читает file_id видео, которое админ канала отправил боту."""
    file_id = read_file_text(path)
    if not FILE_ID_PATTERN.fullmatch(file_id):
        raise ContentError(
            f"В {path} должна быть одна строка - file_id, который прислал бот в ответ на видео"
        )
    return VideoRefItem(file_id=file_id)


def hash_media_file(path: Path, max_bytes: int) -> str:
    """Проверяет, что файл пролезает в лимит Bot API, и считает его sha256."""
    size = path.stat().st_size
    if size > max_bytes:
        raise ContentError(
            f"Файл {path} весит {size / 1024 / 1024:.1f} МБ, "
            f"Bot API принимает до {max_bytes // 1024 // 1024} МБ. Большое видео отправь боту "
            f"с аккаунта админа канала и положи присланный file_id в файл .fileid"
        )
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def read_media_bytes(item: MediaItem) -> bytes:
    """Читает файл с диска и проверяет, что это тот же файл, что был при старте бота."""
    data = item.path.read_bytes()
    if hashlib.sha256(data).hexdigest() != item.sha256:
        raise ContentError(
            f"Файл {item.path} изменился после запуска бота, перезапусти бота, "
            f"чтобы он подхватил новую версию"
        )
    return data


def read_text(path: Path, max_length: int = MAX_MESSAGE_LENGTH) -> str:
    """Читает непустой текст в UTF-8 и проверяет, что Telegram примет его разметку и длину."""
    text = read_file_text(path)
    # Ошибку разметки Telegram повторял бы на каждой попытке, а бот слал бы день заново.
    if errors := find_markup_errors(text, max_length):
        raise ContentError(f"Telegram не примет текст {path}: {'; '.join(errors)}")
    return text


def read_plain_text(path: Path, max_length: int) -> str:
    """Читает непустой текст без разметки и проверяет его длину."""
    text = read_file_text(path)
    if (length := count_utf16_units(text)) > max_length:
        raise ContentError(f"Текст {path} длиннее {max_length} символов ({length})")
    return text


def read_file_text(path: Path) -> str:
    """Читает непустой текстовый файл в UTF-8 без пробелов по краям."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise ContentError(f"Нет файла контента: {path}") from exc
    if not text:
        raise ContentError(f"Файл контента пустой: {path}")
    return text
