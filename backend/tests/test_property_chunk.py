"""
属性测试：Digest 引擎 — 分块不变量（Property 2: Chunk Invariant）

验证：
- len(chunks) >= 1（至少产生一个 Chunk）
- 无内容丢失：原文中的段落文本、列表项、标题文本均可在某个 chunk 中找到
- 每个 chunk.level 值在 1~3 之间
"""

import os
import re

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

os.environ.setdefault("LLM_API_KEY", "test-key-for-testing")
os.environ.setdefault("DATA_DIR", "./test_data")

from app.ai.digest.chunker import chunk_markdown

# ═══════════════════════════════════════════════════════════════
# Strategies
# ═══════════════════════════════════════════════════════════════

_heading_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), blacklist_characters="\r\n\x00"),
    min_size=1,
    max_size=40,
).map(str.strip).filter(lambda s: len(s) > 0)

_safe_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\r\n\x00",
    ),
    min_size=1,
    max_size=80,
).map(str.strip).filter(lambda s: len(s) > 0 and not s.startswith("#"))


@st.composite
def markdown_documents(draw):
    """Generate Markdown documents with H1-H3 headings, paragraphs, and lists."""
    parts: list[str] = []
    num_sections = draw(st.integers(min_value=1, max_value=8))

    for _ in range(num_sections):
        block_type = draw(st.sampled_from(["heading_para", "paragraph", "list"]))

        if block_type == "heading_para":
            level = draw(st.integers(min_value=1, max_value=3))
            title = draw(_heading_text)
            parts.append(f"{'#' * level} {title}")
            parts.append("")
            for _ in range(draw(st.integers(min_value=1, max_value=3))):
                parts.append(draw(_safe_text))
            parts.append("")

        elif block_type == "paragraph":
            for _ in range(draw(st.integers(min_value=1, max_value=3))):
                parts.append(draw(_safe_text))
            parts.append("")

        elif block_type == "list":
            for _ in range(draw(st.integers(min_value=1, max_value=4))):
                parts.append(f"- {draw(_safe_text)}")
            parts.append("")

    return "\n".join(parts)


@st.composite
def markdown_with_deep_headings(draw):
    """Generate Markdown that includes H4-H6 headings (should stay inside parent chunk)."""
    parts: list[str] = []
    title = draw(_heading_text)
    parts.append(f"## {title}")
    parts.append("")
    parts.append(draw(_safe_text))
    parts.append("")

    # Add H4-H6 sub-headings
    for sub_level in draw(st.lists(st.integers(min_value=4, max_value=6), min_size=1, max_size=3)):
        sub_title = draw(_heading_text)
        parts.append(f"{'#' * sub_level} {sub_title}")
        parts.append("")
        parts.append(draw(_safe_text))
        parts.append("")

    return "\n".join(parts)


@st.composite
def plain_text_only(draw):
    """Generate Markdown with no headings at all — should produce a single root chunk."""
    parts: list[str] = []
    for _ in range(draw(st.integers(min_value=1, max_value=5))):
        parts.append(draw(_safe_text))
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _non_blank_lines(text: str) -> set[str]:
    """Return set of stripped non-blank lines from text."""
    return {line.strip() for line in text.splitlines() if line.strip()}


def _all_chunk_text(chunks) -> str:
    """Concatenate all chunk content plus header_path info into one string."""
    parts = []
    for c in chunks:
        parts.append(c.content)
        parts.append(c.title)
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# Property 2: Chunk Invariant — at least one chunk
# ═══════════════════════════════════════════════════════════════

@given(md=markdown_documents())
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_chunk_always_produces_at_least_one(md: str):
    """P2: For any valid Markdown, chunk_markdown produces >= 1 chunk."""
    chunks = chunk_markdown(md)
    assert len(chunks) >= 1, "chunk_markdown must produce at least one chunk"


@given(md=st.text(min_size=0, max_size=200))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_chunk_at_least_one_for_arbitrary_input(md: str):
    """P2: Even for arbitrary (possibly invalid) input, at least one chunk is produced."""
    chunks = chunk_markdown(md)
    assert len(chunks) >= 1


# ═══════════════════════════════════════════════════════════════
# Property 2: Chunk Invariant — level in 1~3
# ═══════════════════════════════════════════════════════════════

@given(md=markdown_documents())
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_chunk_levels_in_valid_range(md: str):
    """P2: Every chunk.level must be in {1, 2, 3}."""
    chunks = chunk_markdown(md)
    for chunk in chunks:
        assert 1 <= chunk.level <= 3, (
            f"chunk.level={chunk.level} out of range for title='{chunk.title}'"
        )


@given(md=markdown_with_deep_headings())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_chunk_levels_valid_with_deep_headings(md: str):
    """P2: H4-H6 headings don't create chunks with level > 3."""
    chunks = chunk_markdown(md)
    for chunk in chunks:
        assert 1 <= chunk.level <= 3, (
            f"H4+ heading leaked as chunk level={chunk.level}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 2: Chunk Invariant — no content loss
# ═══════════════════════════════════════════════════════════════

@given(md=markdown_documents())
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_chunk_no_content_loss(md: str):
    """P2: All non-blank, non-heading lines from the source appear in some chunk's content."""
    chunks = chunk_markdown(md)
    combined = _all_chunk_text(chunks)

    for line in md.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # H1-H3 headings become chunk titles, not content lines
        m = _HEADING_RE.match(stripped)
        if m and len(m.group(1)) <= 3:
            title = m.group(2).strip()
            assert any(c.title == title for c in chunks), (
                f"H1-H3 heading '{title}' not found as any chunk title"
            )
            continue
        # Everything else (paragraphs, list items, H4-H6 headings) must be in chunk content
        assert stripped in combined, (
            f"Content line lost: '{stripped[:60]}...'"
        )


@given(md=plain_text_only())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_chunk_no_heading_produces_root(md: str):
    """P2: A document with no headings produces exactly one root chunk (level=1)."""
    chunks = chunk_markdown(md)
    assert len(chunks) == 1, "No-heading doc should produce exactly one chunk"
    assert chunks[0].level == 1
    assert chunks[0].title == "(root)"
    # All content should be in the root chunk
    for line in md.splitlines():
        stripped = line.strip()
        if stripped:
            assert stripped in chunks[0].content, (
                f"Content line lost in root chunk: '{stripped[:60]}'"
            )


# ═══════════════════════════════════════════════════════════════
# Property 2: Chunk Invariant — chunk_index ordering
# ═══════════════════════════════════════════════════════════════

@given(md=markdown_documents())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_chunk_indices_are_sequential(md: str):
    """P2: chunk_index values are 0, 1, 2, ... in order."""
    chunks = chunk_markdown(md)
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == i, (
            f"Expected chunk_index={i}, got {chunk.chunk_index}"
        )
