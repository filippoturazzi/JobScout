from jobscout.sources.text import html_to_text


def test_strips_tags_and_collapses_whitespace():
    html = "<p>Hello <strong>world</strong></p>\n\n<ul><li>one</li><li>two</li></ul>"
    assert html_to_text(html) == "Hello world one two"


def test_handles_html_escaped_html():
    escaped = "&lt;div class=&quot;x&quot;&gt;&lt;h2&gt;Brief&amp;nbsp;info&lt;/h2&gt;&lt;/div&gt;"
    assert html_to_text(escaped) == "Brief info"


def test_plain_text_unchanged():
    assert html_to_text("Just text.") == "Just text."


def test_empty():
    assert html_to_text("") == ""
