"""
属性测试：Ingest 引擎

Property 1  — 解析器往返一致性（Parser Round-Trip）
Property 11 — 学科名称校验（Subject Validation）
Property 10 — 流水线状态机（Pipeline State Machine）
"""

import os
import re

import pytest
from hypothesis import given, assume, settings, HealthCheck
from hypothesis import strategies as st

# 设置测试环境变量
os.environ.setdefault("LLM_API_KEY", "test-key-for-testing")
os.environ.setdefault("DATA_DIR", "./test_data")

from app.ai.ingest.orchestrator import pretty_print
from app.utils.subject import validate_subject
from app.core.exceptions import InvalidSubjectError
from app.repositories.models import ParseStatus, PipelineStage


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

# Markdown heading regex
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
# List item regex (unordered and ordered)
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(.+)$", re.MULTILINE)


def _extract_headings(md: str) -> list[tuple[int, str]]:
    """Extract (level, text) pairs from Markdown headings."""
    return [(len(m.group(1)), m.group(2).strip()) for m in _HEADING_RE.finditer(md)]


def _extract_plain_text(md: str) -> str:
    """Extract non-empty, non-heading, non-list plain text lines, sorted."""
    lines = []
    for line in md.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _HEADING_RE.match(stripped):
            continue
        if re.match(r"^\s*(?:[-*+]|\d+\.)\s+", line):
            continue
        lines.append(stripped)
    return "\n".join(sorted(lines))


def _extract_list_items(md: str) -> list[str]:
    """Extract list item texts in order."""
    return [m.group(1).strip() for m in _LIST_RE.finditer(md)]


# ═══════════════════════════════════════════════════════════════
# Strategies
# ═══════════════════════════════════════════════════════════════

# Printable text without leading '#' (to avoid accidental headings)
_safe_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S", "Z"), blacklist_characters="\r\n\x00"),
    min_size=1,
    max_size=80,
).map(lambda s: s.strip()).filter(lambda s: len(s) > 0 and not s.startswith("#"))

_heading_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), blacklist_characters="\r\n\x00"),
    min_size=1,
    max_size=40,
).map(lambda s: s.strip()).filter(lambda s: len(s) > 0)


@st.composite
def markdown_documents(draw):
    """Generate a valid Markdown document with headings, paragraphs, and lists."""
    parts: list[str] = []
    num_sections = draw(st.integers(min_value=1, max_value=6))

    for _ in range(num_sections):
        block_type = draw(st.sampled_from(["heading_para", "paragraph", "list"]))

        if block_type == "heading_para":
            level = draw(st.integers(min_value=1, max_value=3))
            title = draw(_heading_text)
            parts.append(f"{'#' * level} {title}")
            parts.append("")
            # Add a paragraph under the heading
            num_lines = draw(st.integers(min_value=1, max_value=3))
            for _ in range(num_lines):
                parts.append(draw(_safe_text))
            parts.append("")

        elif block_type == "paragraph":
            num_lines = draw(st.integers(min_value=1, max_value=3))
            for _ in range(num_lines):
                parts.append(draw(_safe_text))
            parts.append("")

        elif block_type == "list":
            num_items = draw(st.integers(min_value=1, max_value=5))
            for _ in range(num_items):
                item_text = draw(_safe_text)
                parts.append(f"- {item_text}")
            parts.append("")

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# Property 1: Parser Round-Trip
# ═══════════════════════════════════════════════════════════════

@given(md=markdown_documents())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_pretty_print_round_trip(md: str):
    """Property 1: parse(pretty_print(parse(doc))) ≡ parse(doc)

    Since the actual file parsers (PDF, DOCX, etc.) require real files and
    external libraries, we test the round-trip property on the pretty_print
    normalizer which is the common output stage for all parsers.

    Invariant: pretty_print(pretty_print(md)) == pretty_print(md)
    And the structural equivalence: headings, plain text, list order are preserved.
    """
    pp1 = pretty_print(md)
    pp2 = pretty_print(pp1)

    # Idempotence: applying pretty_print twice yields the same result
    assert pp2 == pp1, "pretty_print is not idempotent"

    # Structural equivalence checks
    headings_1 = _extract_headings(pp1)
    headings_2 = _extract_headings(pp2)
    assert headings_1 == headings_2, "Heading levels differ after round-trip"

    plain_1 = _extract_plain_text(pp1)
    plain_2 = _extract_plain_text(pp2)
    assert plain_1 == plain_2, "Plain text content differs after round-trip"

    list_items_1 = _extract_list_items(pp1)
    list_items_2 = _extract_list_items(pp2)
    assert list_items_1 == list_items_2, "List item order differs after round-trip"


@given(md=markdown_documents())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_pretty_print_preserves_content(md: str):
    """Verify pretty_print does not lose headings, text, or list items."""
    pp = pretty_print(md)

    # All headings from the original should be present after normalization
    orig_headings = _extract_headings(md)
    pp_headings = _extract_headings(pp)
    assert orig_headings == pp_headings, "pretty_print altered heading structure"

    # List items should be preserved in order
    orig_lists = _extract_list_items(md)
    pp_lists = _extract_list_items(pp)
    assert orig_lists == pp_lists, "pretty_print altered list item order"


# ═══════════════════════════════════════════════════════════════
# Property 11: Subject Validation
# ═══════════════════════════════════════════════════════════════

# Strategy: valid subject names matching [a-zA-Z0-9_-]{1,64}
_valid_subject_chars = st.text(
    alphabet=st.sampled_from(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    ),
    min_size=1,
    max_size=64,
)


@given(subject=_valid_subject_chars)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_subject_validation_accepts_valid_names(subject: str):
    """Property 11: validate_subject accepts all strings matching [a-zA-Z0-9_-]{1,64}."""
    result = validate_subject(subject)
    assert result == subject.lower(), "Valid subject should be stored as lowercase"


@given(subject=_valid_subject_chars)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_subject_validation_stores_lowercase(subject: str):
    """Property 11: validate_subject always returns lowercase."""
    result = validate_subject(subject)
    assert result == result.lower(), "Result must be fully lowercase"
    # Round-trip: lowercased input produces same output
    assert validate_subject(result) == result, "Lowercase input should be idempotent"


# Strategy: strings containing path traversal characters (built, not filtered)
_safe_filler = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789"),
    min_size=0,
    max_size=20,
)
_path_traversal_subjects = st.one_of(
    # Inject forward slash
    st.tuples(_safe_filler, _safe_filler).map(lambda t: t[0] + "/" + t[1]),
    # Inject backslash
    st.tuples(_safe_filler, _safe_filler).map(lambda t: t[0] + "\\" + t[1]),
    # Inject ".."
    st.tuples(_safe_filler, _safe_filler).map(lambda t: t[0] + ".." + t[1]),
)


@given(subject=_path_traversal_subjects)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_subject_validation_rejects_path_traversal(subject: str):
    """Property 11: validate_subject rejects any input with path traversal characters."""
    with pytest.raises(InvalidSubjectError):
        validate_subject(subject)


# Strategy: strings that don't match the valid pattern
_invalid_subjects = st.one_of(
    # Empty string
    st.just(""),
    # Too long (65+ chars)
    st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
        min_size=65,
        max_size=128,
    ),
    # Contains invalid characters (spaces, dots, special chars)
    st.text(min_size=1, max_size=64).filter(
        lambda s: not re.match(r"^[a-zA-Z0-9_-]{1,64}$", s)
        and "/" not in s
        and "\\" not in s
        and ".." not in s
    ),
)


@given(subject=_invalid_subjects)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_subject_validation_rejects_invalid_names(subject: str):
    """Property 11: validate_subject rejects strings not matching [a-zA-Z0-9_-]{1,64}."""
    with pytest.raises(InvalidSubjectError):
        validate_subject(subject)
