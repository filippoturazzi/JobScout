"""Turn job-board HTML (sometimes HTML-escaped HTML) into plain text."""

import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def html_to_text(value: str) -> str:
    if not value:
        return ""
    # Some boards double-encode: "&lt;p&gt;" instead of "<p>". Unescape first so tags
    # become real tags, strip them, then unescape again for entities inside the text.
    text = html.unescape(value)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    return _WS_RE.sub(" ", text).strip()
