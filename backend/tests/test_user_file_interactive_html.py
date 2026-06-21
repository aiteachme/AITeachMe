from app.api.user_files import _sanitize_interactive_html


def test_sanitize_interactive_html_strips_executable_content() -> None:
    raw = """
    <div onclick="alert(1)">
      <script>alert("x")</script>
      <a href="javascript:alert(1)">bad</a>
      <a href="/safe/path">safe</a>
      <p style="color: red; background-image: url(javascript:alert(1)); font-weight: 700">Text</p>
      <img src="x" onerror="alert(1)" />
      <details open><summary>Hint</summary><input type="checkbox" checked /></details>
    </div>
    """

    cleaned = _sanitize_interactive_html(raw)

    assert "script" not in cleaned
    assert "onclick" not in cleaned
    assert "onerror" not in cleaned
    assert "javascript:" not in cleaned
    assert "<img" not in cleaned
    assert "<a>bad</a>" in cleaned
    assert 'href="/safe/path"' in cleaned
    assert 'rel="noreferrer noopener"' in cleaned
    assert "color: red" in cleaned
    assert "font-weight: 700" in cleaned
    assert "background-image" not in cleaned
    assert "<details" in cleaned
    assert "<input" in cleaned
