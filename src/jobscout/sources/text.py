"""Turn job-board HTML (sometimes HTML-escaped HTML) into plain text."""

import html
import re
from html.parser import HTMLParser

_WS_RE = re.compile(r"\s+")
_SKIPPED_ELEMENTS = {"script", "style"}
_BLOCK_ELEMENTS = {
    "p",
    "div",
    "br",
    "li",
    "ul",
    "ol",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "tr",
    "table",
    "section",
    "article",
    "header",
    "footer",
    "blockquote",
    "pre",
    "hr",
    "td",
    "th",
    "dt",
    "dd",
    "thead",
    "tbody",
    "dl",
    "caption",
}


class _TextExtractor(HTMLParser):
    """Collects text nodes, skipping script/style content; block-level tags become line breaks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_ELEMENTS:
            self._skip_depth += 1
        elif tag in _BLOCK_ELEMENTS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_ELEMENTS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_ELEMENTS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_ELEMENTS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


_ESCAPED_TAG_RE = re.compile(
    r"&lt;/?(?:p|br|div|span|ul|ol|li|strong|b|em|i|u|h[1-6]|a|table|thead|tbody|tr|td|th"
    r"|section|article|header|footer|hr|img|blockquote|pre|code)(?:\s|/?&gt;)",
    re.IGNORECASE,
)


def _looks_double_encoded(value: str) -> bool:
    # Some boards return "&lt;p&gt;..." instead of "<p>...". Require an escaped *HTML tag*
    # (not just any "&lt;") so plain text like "&lt;COMPANY_NAME&gt;" is left alone.
    return "<" not in value and _ESCAPED_TAG_RE.search(value) is not None


def html_to_text(value: str) -> str:
    if not value:
        return ""
    if _looks_double_encoded(value):
        value = html.unescape(value)
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    text = "".join(parser.parts).replace("\xa0", " ")
    return _WS_RE.sub(" ", text).strip()
