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


def test_inline_tags_do_not_split_words():
    assert html_to_text("Java<b>Script</b> and Type<i>Script</i>") == "JavaScript and TypeScript"


def test_block_tags_separate_text():
    assert html_to_text("<p>a</p><p>b</p>") == "a b"
    assert html_to_text("<ul><li>x</li><li>y</li></ul>") == "x y"
    assert html_to_text("a<br>b<br/>c") == "a b c"
    assert html_to_text("<h2>Title</h2>Body") == "Title Body"
    assert html_to_text("<table><tr><td>a</td><td>b</td></tr></table>") == "a b"
    assert html_to_text("<dl><dt>Level</dt><dd>Senior</dd></dl>") == "Level Senior"


def test_escaped_body_with_a_real_html_footer_is_still_unescaped():
    """Arbeitnow returns both in one field: an escaped body plus its own unescaped footer.

    A single literal "<" used to disable unescaping for the whole document, so the escaped
    part came through as visible markup — `convert_charrefs` turned `&lt;p&gt;` into the
    text `<p>` instead of a tag. 398 of 808 stored descriptions were affected.
    """
    value = (
        "&lt;p&gt;Real content here.&lt;/p&gt;<p>Find more on <a href='https://x'>the board</a></p>"
    )

    assert html_to_text(value) == "Real content here. Find more on the board"


def test_a_lone_escaped_placeholder_is_still_left_alone():
    """The stage-2a guard must survive: only an escaped *known tag* triggers unescaping."""
    assert html_to_text("Contact &lt;COMPANY_NAME&gt; today") == "Contact <COMPANY_NAME> today"


def test_escaped_attributes_do_not_leak_into_the_text():
    value = "&lt;div class=&quot;intro&quot;&gt;&lt;strong&gt;About&lt;/strong&gt; us&lt;/div&gt;"

    assert html_to_text(value) == "About us"
