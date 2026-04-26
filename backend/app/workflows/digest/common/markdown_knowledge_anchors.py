"""Markdown-carried KnowledgeUnit extraction helpers.

The stable identity is still carried by Markdown anchors internally, while the
workflow extracts richer KnowledgeUnit content from the knowledge document
itself, including body markdown and inline knowledge images.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from app.models.knowledge_taxonomy import normalize_knowledge_unit_type

ANCHOR_PREFIX = "ku_"
ANCHOR_COMMENT_PREFIX = "ATM_KU:"

_ANCHOR_ID_PATTERN = r"ku_[\w-]+"
_INLINE_ANCHOR_RE = re.compile(rf"\{{#(?P<anchor>{_ANCHOR_ID_PATTERN})\}}")
_COMMENT_ANCHOR_RE = re.compile(rf"<!--\s*ATM_KU:\s*(?P<anchor>{_ANCHOR_ID_PATTERN})\s*-->")
_ANCHOR_RE = re.compile(rf"(?:\{{#(?P<inline>{_ANCHOR_ID_PATTERN})\}}|<!--\s*ATM_KU:\s*(?P<comment>{_ANCHOR_ID_PATTERN})\s*-->)")
_HEADING_RE = re.compile(r"^(?P<prefix>\s{0,3}#{1,6}\s+)(?P<title>.+?)(?P<trailing>\s*)$")
_TAG_RE = re.compile(r"\[(?P<key>type|prerequisite|related):\s*(?P<value>[^\]]+)\]", re.IGNORECASE)
_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)]+)\)")
_LABEL_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?"
    r"(?P<label>\u5b9a\u4e49|\u5b9a\u7406|\u516c\u5f0f|\u4f8b\u9898|\u793a\u4f8b|\u7ec3\u4e60|\u8bc1\u660e|\u5907\u6ce8|Definition|Theorem|Formula|Example|Exercise|Proof|Remark)"
    r"(?:\*\*)?\s*[:\uff1a]",
    re.IGNORECASE,
)
_MARKDOWN_DECORATION_RE = re.compile(r"[#*_`>{}\[\]()]")
_MULTISPACE_RE = re.compile(r"\s+")
_SKIPPABLE_HEADING_PATTERNS = (
    re.compile(
        r"(?:^|[\s:\uff1a-])(how to read|how to use|reading guide|user guide|overview|learning goals?|learning objectives?)(?:$|[\s:\uff1a-])",
        re.IGNORECASE,
    ),
    re.compile(r"\u600e\u4e48\u8bfb"),
    re.compile(r"\u5982\u4f55\u9605\u8bfb"),
    re.compile(r"\u9605\u8bfb\u6307\u5357"),
    re.compile(r"\u4f7f\u7528\u8bf4\u660e"),
    re.compile(r"\u5982\u4f55\u4f7f\u7528"),
    re.compile(r"\u5b66\u4e60\u76ee\u6807"),
    re.compile(r"\u5b66\u4e60\u5efa\u8bae"),
    re.compile(r"\u672c\u7ae0\u5bfc\u8bfb"),
    re.compile(r"\u7ae0\u8282\u5bfc\u8bfb"),
    re.compile(r"\u5148\u770b\u4ec0\u4e48"),
)
_SKIPPABLE_HEADING_EXACT = {
    "table of contents",
    "knowledge document overview",
    "\u76ee\u5f55",
    "\u77e5\u8bc6\u6587\u6863\u603b\u89c8",
    "\u53c2\u8003\u8d44\u6599\u4e0e\u5ef6\u4f38\u9605\u8bfb",
    "\u8fd9\u4efd\u6587\u6863\u600e\u4e48\u8bfb",
    "\u7ae0\u8282\u8def\u7ebf\u56fe",
    "\u672c\u7ae0\u81ea\u68c0",
    "\u8fd9\u51e0\u9879\u4e0d\u80fd\u6f0f",
    "\u56de\u770b\u65f6\u4f18\u5148\u95ee\u81ea\u5df1",
}
_SKIPPABLE_HEADING_PREFIXES = (
    "\u8003\u524d\u6700\u540e",
    "\u518d\u628a\u5173\u952e\u70b9\u538b\u5b9e",
    "\u518d\u628a\u5173\u952e\u7ed3\u6784\u8865\u7a33",
    "\u6700\u7ec8\u56de\u987e",
    "\u4e34\u8003\u901f\u8bb0",
    "\u672c\u7ae0\u5728\u8003\u4ec0\u4e48",
    "\u672c\u7ae0\u6838\u5fc3\u8003\u70b9",
    "\u672c\u7ae0\u6838\u5fc3\u5730\u4f4d",
    "\u672c\u7ae0\u4e3a\u4f55",
    "\u6613\u9519\u70b9\u590d\u76d8",
    "\u9ad8\u9891\u9677\u9631",
)

_LABEL_TYPE_MAP = {
    "\u5b9a\u4e49": "definition",
    "definition": "definition",
    "\u5b9a\u7406": "theorem",
    "theorem": "theorem",
    "\u516c\u5f0f": "formula",
    "formula": "formula",
    "\u4f8b\u9898": "example",
    "\u793a\u4f8b": "example",
    "example": "example",
    "\u7ec3\u4e60": "exercise",
    "exercise": "exercise",
    "\u8bc1\u660e": "proof_step",
    "proof": "proof_step",
    "\u5907\u6ce8": "remark",
    "remark": "remark",
}


@dataclass(frozen=True)
class MarkdownKnowledgeUnit:
    """A KnowledgeUnit candidate extracted from knowledge markdown."""

    anchor: str
    name: str
    knowledge_unit_type: str = "concept"
    summary: str = ""
    body_markdown: str = ""
    knowledge_images: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    line_no: int = 0
    heading_level: int = 1
    source_kind: str = "markdown"
    knowledge_document_id: int | None = None
    chapter_index: int = 0
    source_file_ids: list[int] = field(default_factory=list)
    quote_text: str = ""


@dataclass(frozen=True)
class MarkdownSectionChunk:
    """A heading-scoped markdown chunk used for downstream extraction."""

    title: str
    anchor: str
    header_path: str
    body_markdown: str = ""
    summary: str = ""
    knowledge_images: list[str] = field(default_factory=list)
    line_no: int = 0
    heading_level: int = 1


@dataclass(frozen=True)
class AnchorValidationResult:
    """Validation result for Markdown-carried KnowledgeUnit anchors."""

    anchors: list[str]
    duplicate_anchors: list[str]
    invalid_anchors: list[str]

    @property
    def ok(self) -> bool:
        return not self.duplicate_anchors and not self.invalid_anchors


def build_knowledge_unit_anchor(text: str, *, used: set[str] | None = None) -> str:
    """Build a stable ``ku_`` anchor from display text."""

    base = _slugify_anchor(_strip_tags_and_anchor(text)) or "unit"
    anchor = f"{ANCHOR_PREFIX}{base}"
    if used is None:
        return anchor

    candidate = anchor
    suffix = 2
    while candidate in used:
        candidate = f"{anchor}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def ensure_markdown_knowledge_unit_anchors(markdown: str) -> str:
    """Add hidden ``ATM_KU`` anchors to headings and typed labeled blocks."""

    used = set(extract_knowledge_unit_anchor_ids(markdown))
    output: list[str] = []
    for line in markdown.splitlines():
        if _extract_anchor_from_line(line):
            output.append(line)
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            title = heading.group("title").strip()
            if _is_skippable_heading(title):
                output.append(line)
                continue
            anchor = build_knowledge_unit_anchor(title, used=used)
            output.append(f"{heading.group('prefix')}{title} <!-- {ANCHOR_COMMENT_PREFIX} {anchor} -->{heading.group('trailing')}")
            continue

        if _LABEL_RE.match(line):
            anchor = build_knowledge_unit_anchor(line, used=used)
            output.append(line.rstrip() + f" <!-- {ANCHOR_COMMENT_PREFIX} {anchor} -->")
            continue

        output.append(line)
    return "\n".join(output).rstrip() + ("\n" if markdown.endswith("\n") else "")


def validate_knowledge_unit_anchors(markdown: str) -> AnchorValidationResult:
    """Check uniqueness and prefix validity for Markdown KnowledgeUnit anchors."""

    all_anchors = extract_all_anchor_ids(markdown)
    seen: set[str] = set()
    duplicates: list[str] = []
    invalid: list[str] = []
    for anchor in all_anchors:
        if not anchor.startswith(ANCHOR_PREFIX):
            invalid.append(anchor)
            continue
        if anchor in seen and anchor not in duplicates:
            duplicates.append(anchor)
        seen.add(anchor)
    return AnchorValidationResult(
        anchors=[anchor for anchor in all_anchors if anchor.startswith(ANCHOR_PREFIX)],
        duplicate_anchors=duplicates,
        invalid_anchors=invalid,
    )


def extract_knowledge_unit_anchor_ids(markdown: str) -> list[str]:
    """Return all explicit KnowledgeUnit anchor ids."""

    return [anchor for anchor in extract_all_anchor_ids(markdown) if anchor.startswith(ANCHOR_PREFIX)]


def extract_all_anchor_ids(markdown: str) -> list[str]:
    """Return all inline/comment KnowledgeUnit anchor declarations."""

    anchors: list[str] = []
    for match in _ANCHOR_RE.finditer(markdown):
        anchor = match.group("inline") or match.group("comment") or ""
        if anchor:
            anchors.append(anchor)
    anchors.extend(
        anchor
        for anchor in re.findall(r"\{#([^}]+)\}", markdown)
        if not anchor.startswith(ANCHOR_PREFIX)
    )
    return anchors


def extract_markdown_knowledge_units(markdown: str) -> list[MarkdownKnowledgeUnit]:
    """Extract KnowledgeUnit candidates from Markdown sections."""

    chunks = extract_markdown_section_chunks(markdown)
    return [
        MarkdownKnowledgeUnit(
            anchor=chunk.anchor,
            name=chunk.title,
            knowledge_unit_type="concept",
            summary=chunk.summary,
            body_markdown=chunk.body_markdown,
            knowledge_images=chunk.knowledge_images,
            prerequisites=[],
            related=[],
            line_no=chunk.line_no,
            heading_level=chunk.heading_level,
        )
        for chunk in chunks
    ]


def extract_markdown_section_chunks(markdown: str) -> list[MarkdownSectionChunk]:
    """Extract heading-scoped markdown chunks for chunk-level knowledge parsing."""

    lines = markdown.splitlines()
    chunks: list[MarkdownSectionChunk] = []
    used_anchors = set(extract_knowledge_unit_anchor_ids(markdown))
    heading_indexes = [
        index
        for index, line in enumerate(lines)
        if _HEADING_RE.match(line) and not _is_skippable_heading(_HEADING_RE.match(line).group("title"))  # type: ignore[union-attr]
    ]
    heading_meta: list[tuple[int, str, int, str]] = []

    path_stack: list[tuple[int, str]] = []
    for index in heading_indexes:
        line = lines[index]
        heading_match = _HEADING_RE.match(line)
        prefix = heading_match.group("prefix") if heading_match else "# "
        heading_level = max(1, min(6, prefix.count("#")))
        title = _extract_unit_name(line)
        if not title:
            continue
        while path_stack and path_stack[-1][0] >= heading_level:
            path_stack.pop()
        path_stack.append((heading_level, title))
        header_path = " > ".join(part for _, part in path_stack)
        heading_meta.append((index, title, heading_level, header_path))

    for position, (index, title, heading_level, header_path) in enumerate(heading_meta):
        line = lines[index]
        anchor = _extract_anchor_from_line(line) or build_knowledge_unit_anchor(title, used=used_anchors)
        next_index = heading_meta[position + 1][0] if position + 1 < len(heading_meta) else len(lines)
        section_lines = lines[index:next_index]
        body_markdown = _build_body_markdown(section_lines)
        summary = _build_summary(section_lines)
        chunks.append(
            MarkdownSectionChunk(
                title=title,
                anchor=anchor,
                header_path=header_path,
                summary=summary,
                body_markdown=body_markdown,
                knowledge_images=_extract_knowledge_images(body_markdown),
                line_no=index + 1,
                heading_level=heading_level,
            )
        )
    return chunks


def extract_markdown_chapter_chunks(markdown: str) -> list[MarkdownSectionChunk]:
    """Extract top-level chapter chunks delimited by level-1 headings."""

    lines = markdown.splitlines()
    heading_meta: list[tuple[int, str, str]] = []
    used_anchors = set(extract_knowledge_unit_anchor_ids(markdown))

    for index, line in enumerate(lines):
        heading_match = _HEADING_RE.match(line)
        if heading_match is None:
            continue
        prefix = heading_match.group("prefix")
        if prefix.count("#") != 1:
            continue
        title = _extract_unit_name(line)
        if not title or _is_skippable_heading(title):
            continue
        anchor = _extract_anchor_from_line(line) or build_knowledge_unit_anchor(title, used=used_anchors)
        heading_meta.append((index, title, anchor))

    if len(heading_meta) == 1:
        h2_chunks = [
            chunk
            for chunk in extract_markdown_section_chunks(markdown)
            if chunk.heading_level == 2
        ]
        if len(h2_chunks) >= 2:
            return [
                MarkdownSectionChunk(
                    title=chunk.title,
                    anchor=chunk.anchor,
                    header_path=chunk.title,
                    summary=chunk.summary,
                    body_markdown=chunk.body_markdown,
                    knowledge_images=chunk.knowledge_images,
                    line_no=chunk.line_no,
                    heading_level=1,
                )
                for chunk in h2_chunks
            ]

    if not heading_meta:
        section_chunks = extract_markdown_section_chunks(markdown)
        if section_chunks:
            first = section_chunks[0]
            body_markdown = _build_body_markdown(lines)
            return [
                MarkdownSectionChunk(
                    title=first.title,
                    anchor=first.anchor,
                    header_path=first.title,
                    summary=_build_summary(lines) or first.summary,
                    body_markdown=body_markdown,
                    knowledge_images=_extract_knowledge_images(body_markdown),
                    line_no=first.line_no,
                    heading_level=1,
                )
            ]
        if markdown.strip():
            body_markdown = _build_body_markdown(lines)
            return [
                MarkdownSectionChunk(
                    title="Knowledge Document",
                    anchor=build_knowledge_unit_anchor("Knowledge Document", used=used_anchors),
                    header_path="Knowledge Document",
                    summary=_build_summary(lines),
                    body_markdown=body_markdown,
                    knowledge_images=_extract_knowledge_images(body_markdown),
                    line_no=1,
                    heading_level=1,
                )
            ]
        return []

    chunks: list[MarkdownSectionChunk] = []
    for position, (index, title, anchor) in enumerate(heading_meta):
        next_index = heading_meta[position + 1][0] if position + 1 < len(heading_meta) else len(lines)
        chapter_lines = lines[index:next_index]
        body_markdown = _build_body_markdown(chapter_lines)
        chunks.append(
            MarkdownSectionChunk(
                title=title,
                anchor=anchor,
                header_path=title,
                summary=_build_summary(chapter_lines),
                body_markdown=body_markdown,
                knowledge_images=_extract_knowledge_images(body_markdown),
                line_no=index + 1,
                heading_level=1,
            )
        )
    return chunks


def _strip_tags_and_anchor(text: str) -> str:
    text = _ANCHOR_RE.sub("", text)
    text = _INLINE_ANCHOR_RE.sub("", text)
    text = _COMMENT_ANCHOR_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    text = _MARKDOWN_DECORATION_RE.sub(" ", text)
    return _MULTISPACE_RE.sub(" ", text).strip()


def _extract_anchor_from_line(line: str) -> str | None:
    match = _ANCHOR_RE.search(line)
    if match is None:
        return None
    return match.group("inline") or match.group("comment")


def _slugify_anchor(text: str) -> str:
    cleaned = text.strip().lower()
    cleaned = re.sub(r"[^\w\s-]", "", cleaned)
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned.strip("-")


def _is_skippable_heading(title: str) -> bool:
    lowered = _strip_tags_and_anchor(title).casefold()
    if lowered in _SKIPPABLE_HEADING_EXACT:
        return True
    if any(lowered.startswith(prefix.casefold()) for prefix in _SKIPPABLE_HEADING_PREFIXES):
        return True
    return any(pattern.search(lowered) for pattern in _SKIPPABLE_HEADING_PATTERNS)


def _extract_tags(line: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for match in _TAG_RE.finditer(line):
        tags[match.group("key").lower()] = match.group("value").strip()
    return tags


def _split_tag_values(value: str) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[,，;；、]", value)
    return [part.strip() for part in parts if part.strip()]


def _extract_unit_name(line: str) -> str:
    heading = _HEADING_RE.match(line)
    if heading:
        return _strip_tags_and_anchor(heading.group("title"))

    without_anchor = _ANCHOR_RE.sub("", line).strip()
    without_tags = _TAG_RE.sub("", without_anchor).strip()
    label = _LABEL_RE.match(without_tags)
    if label:
        name = without_tags[label.end() :].strip()
        return _strip_tags_and_anchor(name or label.group("label"))
    return _strip_tags_and_anchor(without_tags)


def _infer_node_type(line: str, explicit_type: str) -> str:
    if explicit_type:
        return normalize_knowledge_unit_type(explicit_type)
    label = _LABEL_RE.match(line)
    if label:
        return normalize_knowledge_unit_type(_LABEL_TYPE_MAP.get(label.group("label").lower(), "concept"))
    return "concept"


def _collect_unit_section_lines(lines: list[str], index: int) -> list[str]:
    section: list[str] = [lines[index]]
    for line in lines[index + 1 :]:
        if _extract_anchor_from_line(line):
            break
        section.append(line)
    return section


def _build_body_markdown(lines: list[str]) -> str:
    body = "\n".join(line.rstrip() for line in lines).strip()
    return body[:8000]


def _extract_knowledge_images(body_markdown: str) -> list[str]:
    seen: set[str] = set()
    images: list[str] = []
    for match in _IMAGE_RE.finditer(body_markdown):
        image_markdown = match.group(0).strip()
        if image_markdown and image_markdown not in seen:
            seen.add(image_markdown)
            images.append(image_markdown)
    return images


def _build_summary(lines: list[str]) -> str:
    parts: list[str] = []
    for line in lines:
        stripped = _strip_tags_and_anchor(line)
        if not stripped:
            continue
        if _IMAGE_RE.search(line):
            continue
        parts.append(stripped)
        if len(" ".join(parts)) >= 500:
            break
    return " ".join(parts)[:500]


__all__ = [
    "ANCHOR_PREFIX",
    "AnchorValidationResult",
    "MarkdownSectionChunk",
    "MarkdownKnowledgeUnit",
    "build_knowledge_unit_anchor",
    "ensure_markdown_knowledge_unit_anchors",
    "extract_all_anchor_ids",
    "extract_knowledge_unit_anchor_ids",
    "extract_markdown_chapter_chunks",
    "extract_markdown_section_chunks",
    "extract_markdown_knowledge_units",
    "validate_knowledge_unit_anchors",
]
