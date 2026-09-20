"""Turn job-board HTML (sometimes HTML-escaped HTML) into plain text."""

import html
import re
from html.parser import HTMLParser

_WS_RE = re.compile(r"\s+")
_SKIPPED_ELEMENTS = {"script", "style"}


class _TextExtractor(HTMLParser):
    """Collects text nodes, skipping script/style content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_ELEMENTS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_ELEMENTS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def _looks_double_encoded(value: str) -> bool:
    # Some boards return "&lt;p&gt;..." instead of "<p>...": no real tags, but escaped ones.
    return "<" not in value and "&lt;" in value


def html_to_text(value: str) -> str:
    if not value:
        return ""
    if _looks_double_encoded(value):
        value = html.unescape(value)
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    text = " ".join(parser.parts).replace("\xa0", " ")
    return _WS_RE.sub(" ", text).strip()
