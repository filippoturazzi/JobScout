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


def test_literal_lt_entity_next_to_real_tag_is_preserved():
    assert html_to_text("Salary &lt; 100k for <p>this role</p>") == "Salary < 100k for this role"


def test_script_and_style_contents_are_dropped():
    html = '<p>Great job</p><script>trackEvent("view");</script><style>.x{color:red}</style>'
    assert html_to_text(html) == "Great job"


def test_bare_less_than_in_text_survives():
    assert html_to_text("<p>&lt; 5 years experience</p>") == "< 5 years experience"


def test_plain_text_with_escaped_placeholder_is_not_treated_as_html():
    text = "Please replace &lt;COMPANY_NAME&gt; in your cover letter."
    assert html_to_text(text) == "Please replace <COMPANY_NAME> in your cover letter."


def test_plain_text_with_escaped_generics_is_preserved():
    assert html_to_text("Generics like Vector&lt;int&gt; are a plus.") == (
        "Generics like Vector<int> are a plus."
    )


def test_double_escaped_entity_stays_literal():
    assert html_to_text("<p>Write &amp;lt;tag&amp;gt; to show a tag</p>") == (
        "Write &lt;tag&gt; to show a tag"
    )
