"""Проверка текста по правилам HTML-разметки Telegram до отправки.

Правила: https://core.telegram.org/bots/api#html-style
"""

from html.parser import HTMLParser

SUPPORTED_TAGS = frozenset(
    {
        "b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "span",
        "tg-spoiler", "a", "tg-emoji", "code", "pre", "blockquote",
    }
)  # fmt: skip
# Из именованных сущностей Telegram понимает только эти; числовые (&#169;) - любые.
SUPPORTED_ENTITIES = frozenset({"lt", "gt", "amp", "quot"})
ESCAPES = {"<": "&lt;", ">": "&gt;", "&": "&amp;"}


class _TelegramHtmlChecker(HTMLParser):
    """Разбирает текст, собирает нарушения разметки и считает видимую длину."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.errors: list[str] = []
        self.visible_length = 0
        self._open_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in SUPPORTED_TAGS:
            self.errors.append(f"тег <{tag}> Telegram не поддерживает")
        self._open_tags.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self._open_tags or self._open_tags[-1] != tag:
            self.errors.append(f"закрывающий тег </{tag}> без открывающего или не по порядку")
            return
        self._open_tags.pop()

    def handle_data(self, data: str) -> None:
        for char, escape in ESCAPES.items():
            if char in data:
                self.errors.append(f"символ {char} в тексте нужно писать как {escape}")
        self.visible_length += count_utf16_units(data)

    def handle_entityref(self, name: str) -> None:
        if name not in SUPPORTED_ENTITIES:
            self.errors.append(f"сущность &{name}; Telegram не поддерживает")
        self.visible_length += 1

    def handle_charref(self, name: str) -> None:
        self.visible_length += 1

    def close(self) -> None:
        super().close()
        self.errors.extend(f"тег <{tag}> не закрыт" for tag in self._open_tags)


def find_markup_errors(text: str, max_length: int) -> list[str]:
    """Нарушения, из-за которых Telegram не примет текст; пустой список - всё в порядке."""
    checker = _TelegramHtmlChecker()
    checker.feed(text)
    checker.close()
    if checker.visible_length > max_length:
        checker.errors.append(f"текст длиннее {max_length} символов ({checker.visible_length})")
    return checker.errors


def count_utf16_units(text: str) -> int:
    """Длина строки так, как её считает Telegram: в кодовых единицах UTF-16."""
    return len(text.encode("utf-16-le")) // 2
