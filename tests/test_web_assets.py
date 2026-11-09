import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src" / "jobscout" / "web"
PLACEHOLDER = re.compile(r"\{(\w+)\}")
# The only px values app.css may use: borders and the focus ring, plus layout widths.
ALLOWED_PX = {"1", "2", "260", "480", "720", "800", "1000"}


def test_locales_have_the_same_keys_and_placeholders():
    en = json.loads((WEB / "locales" / "en.json").read_text(encoding="utf-8"))
    pt = json.loads((WEB / "locales" / "pt-BR.json").read_text(encoding="utf-8"))
    assert set(en) == set(pt)
    for key, value in en.items():
        assert set(PLACEHOLDER.findall(value)) == set(PLACEHOLDER.findall(pt[key])), key


def test_no_page_code_writes_html_from_data():
    banned = ("innerHTML", "outerHTML", "insertAdjacentHTML")
    offenders = [
        f"{path.relative_to(WEB)}: {word}"
        for path in WEB.rglob("*.js")
        if path.relative_to(WEB).as_posix() != "js/icons.js"
        for word in banned
        if word in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_page_css_uses_tokens_only():
    css = (WEB / "app.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "raw colour literal"
    used = set(re.findall(r"(?<![\w.-])(\d+(?:\.\d+)?)px", css))
    assert used <= ALLOWED_PX, used - ALLOWED_PX
