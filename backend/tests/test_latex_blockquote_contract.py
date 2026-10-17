"""Keep math containers intact through the real chapter enhancement boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.tools.builtin.latex_processing import normalize_math_delimiters, validate_latex
from app.workflows.digest.docgen.lib import chapter_enhancement
from app.workflows.digest.docgen.lib.models import ChapterDraft
from app.workflows.digest.docgen.lib.presentation_policy import find_docgen_presentation_issues


@pytest.mark.parametrize("prefix", ["", "> ", "> > ", ">> "])
@pytest.mark.parametrize("delimiters", [(r"\[", r"\]"), ("$$", "$$")])
@pytest.mark.parametrize("multiline", [False, True])
def test_math_normalizers_preserve_display_formula_quote_depth(prefix, delimiters, multiline) -> None:
    opening, closing = delimiters
    formula = r"\boxed{a-b=a+(-b)}"
    raw = "\n".join(prefix + line for line in (
        [opening, formula, closing] if multiline else [opening + formula + closing]
    )) + "\n"
    expected = "\n".join(prefix + line for line in ["$$", formula, "$$"]) + "\n"

    normalized = normalize_math_delimiters(raw)
    assert normalized == expected
    assert validate_latex(normalized) == expected
    assert validate_latex(validate_latex(normalized)) == expected


@pytest.mark.parametrize("prefix", ["", "> ", "> > "])
@pytest.mark.parametrize("fence", ["```", "````", "~~~"])
def test_math_normalizers_leave_complete_code_fences_unchanged(prefix, fence) -> None:
    code = "\n".join(prefix + line for line in [
        fence + "text", r"\[literal\]", "$$literal$$", "$unclosed", fence,
    ]) + "\n"
    raw = code + "\n正文：\\(a-b\\)。\n"

    normalized = normalize_math_delimiters(raw)
    assert normalized.startswith(code)
    assert normalized.endswith("正文：$a-b$。\n")
    assert validate_latex(normalized).startswith(code)


@pytest.mark.parametrize("prefix", ["", "> ", "> > "])
def test_math_normalizers_preserve_inline_code_and_single_character_formulas(prefix) -> None:
    raw = prefix + r"`$$` 与 `\[literal\]`、`PROMPT $P$G`；公式：\(x\)。" + "\n"
    expected = prefix + r"`$$` 与 `\[literal\]`、`PROMPT $P$G`；公式：$x$。" + "\n"
    assert normalize_math_delimiters(raw) == expected
    assert validate_latex(normalize_math_delimiters(raw)) == expected
    assert normalize_math_delimiters(prefix + "$$x$$\n") == prefix + "$$\n" + prefix + "x\n" + prefix + "$$\n"


@pytest.mark.parametrize("prefix", ["", "> ", "> > "])
def test_greater_than_relations_inside_math_are_not_new_quote_containers(prefix) -> None:
    raw = "\n".join(prefix + line for line in [r"\[", "x", "> 0", r"\]"]) + "\n"
    expected = "\n".join(prefix + line for line in ["$$", "x", "> 0", "$$"]) + "\n"
    assert normalize_math_delimiters(raw) == expected
    assert validate_latex(normalize_math_delimiters(raw)) == expected


@pytest.mark.parametrize("prefix", ["> ", "> > "])
@pytest.mark.parametrize("delimiters", [(r"\[", r"\]"), ("$$", "$$")])
def test_math_closing_after_formula_does_not_capture_following_prose(prefix, delimiters) -> None:
    opening, closing = delimiters
    raw = prefix + opening + "\n" + prefix + "a=b" + closing + "\n\n正常正文\\(x\\)。\n"

    normalized = validate_latex(normalize_math_delimiters(raw))
    assert prefix + "$$\n" + prefix + "a=b\n" + prefix + "$$\n" in normalized
    assert normalized.endswith("\n\n正常正文$x$。\n")
    assert prefix + "正常正文" not in normalized


def test_longer_code_fences_protect_inner_fences_and_unclosed_code() -> None:
    raw = "````markdown\n```text\n$$literal$$\n```\n````\n\n~~~text\n\\[literal\\]\n$unclosed\n"
    assert normalize_math_delimiters(raw) == raw
    validated = validate_latex(raw)
    assert validated.startswith("````markdown\n```text\n$$literal$$\n```\n````\n")
    assert validated.endswith("~~~text\n\\[literal\\]\n$unclosed\n")


@pytest.mark.anyio
@pytest.mark.parametrize("delimiters", [(r"\[", r"\]"), ("$$", "$$")])
@pytest.mark.parametrize("multiline", [False, True])
async def test_real_chapter_enhancement_keeps_core_formula_renderable(monkeypatch, delimiters, multiline) -> None:
    monkeypatch.setattr(chapter_enhancement, "DocGenAssetRuntime", lambda context: object())
    monkeypatch.setattr(chapter_enhancement, "get_settings", lambda: SimpleNamespace(
        docgen=SimpleNamespace(generate_interactive_html=False),
    ))
    opening, closing = delimiters
    formula = r"\boxed{a-b=a+(-b)}"
    quoted_formula = "\n".join("> " + line for line in (
        [opening, formula, closing] if multiline else [opening + formula + closing]
    ))
    draft = ChapterDraft(chapter_index=2, title="整数减法", markdown=(
        "# 整数减法\n\n## 减法转化\n\n"
        "> [!IMPORTANT]\n>\n> 减去一个数，等于加上这个数的相反数。\n>\n"
        + quoted_formula + "\n\n减数为负数时仍须取整个减数的相反数。\n"
    ))

    enhanced, _, _ = await chapter_enhancement.enhance_chapter_draft(
        draft, traced_context=TracedExecutionContext(course_id="math_quote_test", build_session_id="test"),
        digest_mode="sprint",
    )
    assert "> $$\n> " + formula + "\n> $$" in enhanced.markdown
    assert find_docgen_presentation_issues(enhanced.markdown) == []
    assert "减数为负数时仍须取整个减数的相反数。" in enhanced.markdown
