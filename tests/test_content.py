"""Тесты загрузки контента."""

import os
import re
from pathlib import Path

import pytest

from mwa_bot.content.loader import (
    DAY_DIRS,
    MAX_CAPTION_LENGTH,
    MAX_DESCRIPTION_LENGTH,
    MAX_PHOTO_BYTES,
    MAX_VIDEO_BYTES,
    ContentError,
    TextItem,
    VideoItem,
    VideoRefItem,
    load_content,
    load_day,
)
from mwa_bot.db.models import Stage

REPO_CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"


@pytest.fixture
def content_dir(tmp_path: Path) -> Path:
    """Минимальная валидная папка контента."""
    for name in ("welcome", "not_subscribed", "in_progress", "final"):
        (tmp_path / f"{name}.html").write_text(f"<b>{name}</b>", encoding="utf-8")
    (tmp_path / "description.txt").write_text("Описание бота", encoding="utf-8")
    (tmp_path / "welcome.jpg").write_bytes(b"fake jpeg")
    for dirname in DAY_DIRS.values():
        day_dir = tmp_path / dirname
        day_dir.mkdir()
        (day_dir / "01_video.mp4").write_bytes(b"fake video " + dirname.encode())
        (day_dir / "02_text.html").write_text(f"text {dirname}", encoding="utf-8")
    return tmp_path


def test_repo_content_placeholders_are_valid():
    content = load_content(REPO_CONTENT_DIR)

    assert set(content.days) == {Stage.DAY1, Stage.DAY2, Stage.DAY3}
    for items in content.days.values():
        video, text, practice = items
        # Видео дня - локальная заглушка или настоящее видео, уже загруженное в Telegram.
        assert isinstance(video, VideoItem | VideoRefItem)
        assert isinstance(text, TextItem)
        assert isinstance(practice, TextItem)
    assert isinstance(content.days[Stage.DAY3][0], VideoRefItem)
    assert content.welcome.startswith("<b>WELCOME TO MWA</b>")
    assert content.welcome_photo.path.name == "welcome.jpg"
    assert content.description.startswith("Ваше первое касание с MWA METHOD.")


def test_day_items_follow_file_name_order_and_skip_hidden(content_dir):
    day_dir = content_dir / "day1"
    (day_dir / "03_practice.html").write_text("practice", encoding="utf-8")
    (day_dir / ".DS_Store").write_bytes(b"\x00")

    items = load_day(day_dir)

    assert [type(item) for item in items] == [VideoItem, TextItem, TextItem]
    assert [item.text for item in items if isinstance(item, TextItem)] == ["text day1", "practice"]


def test_missing_screen_text_is_reported(content_dir):
    (content_dir / "not_subscribed.html").unlink()

    with pytest.raises(ContentError, match=r"not_subscribed\.html"):
        load_content(content_dir)


def test_blank_text_is_reported(content_dir):
    (content_dir / "day2" / "02_text.html").write_text("  \n", encoding="utf-8")

    with pytest.raises(ContentError, match="пустой"):
        load_content(content_dir)


def test_unsupported_file_is_reported(content_dir):
    (content_dir / "day3" / "03_practice.mp3").write_bytes(b"audio")

    with pytest.raises(ContentError, match=r"03_practice\.mp3"):
        load_content(content_dir)


def test_missing_or_empty_day_is_reported(content_dir):
    for path in (content_dir / "day2").iterdir():
        path.unlink()
    with pytest.raises(ContentError, match="пустая"):
        load_content(content_dir)

    (content_dir / "day2").rmdir()
    with pytest.raises(ContentError, match="Нет папки"):
        load_content(content_dir)


def test_oversized_video_is_reported(content_dir):
    video = content_dir / "day1" / "01_video.mp4"
    os.truncate(video, MAX_VIDEO_BYTES + 1)

    with pytest.raises(ContentError, match="МБ"):
        load_content(content_dir)


def test_replaced_video_gets_new_hash(content_dir):
    video = content_dir / "day1" / "01_video.mp4"
    before = load_day(content_dir / "day1")[0]
    video.write_bytes(b"another video")
    after = load_day(content_dir / "day1")[0]

    assert isinstance(before, VideoItem)
    assert isinstance(after, VideoItem)
    assert before.sha256 != after.sha256


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("a < b", "&lt;"),
        ("Tom & Jerry", "&amp;"),
        ("<b>bold", "не закрыт"),
        ("<b><i>x</b></i>", "не по порядку"),
        ("line<br>", "<br>"),
        ("&nbsp;", "&nbsp;"),
        ("я" * 4097, "4096"),
        ("😀" * 2049, "4096"),
    ],
    ids=["lt", "amp", "unclosed", "misnested", "br", "named-entity", "too-long", "utf16-length"],
)
def test_text_telegram_would_reject_is_reported(content_dir, text, problem):
    (content_dir / "day2" / "02_text.html").write_text(text, encoding="utf-8")

    with pytest.raises(ContentError, match=re.escape(problem)):
        load_content(content_dir)


def test_valid_telegram_markup_is_accepted(content_dir):
    text = (
        '<b>Жирный</b>, <i>курсив</i>, <a href="https://mwamethod.com">ссылка</a>, '
        "&lt;3 &amp; &#169;"
    )
    (content_dir / "day2" / "02_text.html").write_text(text + " " + "я" * 4000, encoding="utf-8")

    content = load_content(content_dir)

    assert content.days[Stage.DAY2][1].text.startswith("<b>Жирный</b>")


def test_welcome_photo_may_be_png(content_dir):
    (content_dir / "welcome.jpg").rename(content_dir / "welcome.png")

    assert load_content(content_dir).welcome_photo.path.name == "welcome.png"


def test_missing_welcome_photo_is_reported(content_dir):
    (content_dir / "welcome.jpg").unlink()

    with pytest.raises(ContentError, match="Нет картинки WELCOME"):
        load_content(content_dir)


def test_oversized_welcome_photo_is_reported(content_dir):
    os.truncate(content_dir / "welcome.jpg", MAX_PHOTO_BYTES + 1)

    with pytest.raises(ContentError, match="МБ"):
        load_content(content_dir)


def test_welcome_caption_longer_than_telegram_allows_is_reported(content_dir):
    (content_dir / "welcome.html").write_text("я" * (MAX_CAPTION_LENGTH + 1), encoding="utf-8")

    with pytest.raises(ContentError, match=str(MAX_CAPTION_LENGTH)):
        load_content(content_dir)


def test_description_is_plain_text_with_its_own_limit(content_dir):
    description = content_dir / "description.txt"
    description.write_text("3 < 4 & <b>не тег</b>", encoding="utf-8")
    assert load_content(content_dir).description == "3 < 4 & <b>не тег</b>"

    description.write_text("я" * (MAX_DESCRIPTION_LENGTH + 1), encoding="utf-8")
    with pytest.raises(ContentError, match=str(MAX_DESCRIPTION_LENGTH)):
        load_content(content_dir)


def test_day_video_can_be_telegram_file_id(content_dir):
    day_dir = content_dir / "day3"
    (day_dir / "01_video.mp4").unlink()
    (day_dir / "01_video.fileid").write_text("BAACAgIAAxkBAAIBY2c_test-file_ID\n", encoding="utf-8")

    items = load_day(day_dir)

    assert items[0] == VideoRefItem(file_id="BAACAgIAAxkBAAIBY2c_test-file_ID")


def test_broken_file_id_is_reported(content_dir):
    (content_dir / "day3" / "01_video.fileid").write_text("скопировал не то", encoding="utf-8")

    with pytest.raises(ContentError, match="file_id"):
        load_content(content_dir)


def test_oversized_video_error_suggests_file_id(content_dir):
    os.truncate(content_dir / "day1" / "01_video.mp4", MAX_VIDEO_BYTES + 1)

    with pytest.raises(ContentError, match=r"\.fileid"):
        load_content(content_dir)
