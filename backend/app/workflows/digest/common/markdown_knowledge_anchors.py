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

_INLINE_ANCHOR_RE = re.compile(r"\{#(?P<anchor>ku_[A-Za-z0-9_-]+)\}")
_COMMENT_ANCHOR_RE = re.compile(r"<!--\s*ATM_KU:\s*(?P<anchor>ku_[A-Za-z0-9_-]+)\s*-->")
_ANCHOR_RE = re.compile(r"(?:\{#(?P<inline>ku_[A-Za-z0-9_-]+)\}|<!--\s*ATM_KU:\s*(?P<comment>ku_[A-Za-z0-9_-]+)\s*-->)")
_HEADING_RE = re.compile(r"^(?P<prefix>\s{0,3}#{1,6}\s+)(?P<title>.+?)(?P<trailing>\s*)$")
_TAG_RE = re.compile(r"\[(?P<key>type|prerequisite|related):\s*(?P<value>[^\]]+)\]", re.IGNORECASE)
_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)]+)\)")
_LABEL_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?"
    r"(?P<label>定义|定理|公式|例题|示例|练习|证明|备注|Definition|Theorem|Formula|Example|Exercise|Proof|Remark)"
    r"(?:\*\*)?\s*[:：]",
    re.IGNORECASE,
)
_MARKDOWN_DECORATION_RE = re.compile(r"[#*_`>{}\[\]()]")
_MULTISPACE_RE = re.compile(r"\s+")

_LABEL_TYPE_MAP = {
    "定义": "definition",
    "definition": "definition",
    "定理": "theorem",
    "theorem": "theorem",
    "公式": "formula",
    "formula": "formula",
    "例题": "example",
    "示例": "example",
    "example": "example",
    "练习": "exercise",
    "exercise": "exercise",
    "证明": "proof_step",
    "proof": "proof_step",
    "备注": "remark",
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

    lines = markdown.splitlines()
    units: list[MarkdownKnowledgeUnit] = []
    used_anchors = set(extract_knowledge_unit_anchor_ids(markdown))
    heading_indexes = [
        index
        for index, line in enumerate(lines)
        if _HEADING_RE.match(line) and not _is_skippable_heading(_HEADING_RE.match(line).group("title"))  # type: ignore[union-attr]
    ]

    for position, index in enumerate(heading_indexes):
        line = lines[index]
        heading_match = _HEADING_RE.match(line)
        prefix = heading_match.group("prefix") if heading_match else "# "
        heading_level = max(1, min(6, prefix.count("#")))
        name = _extract_unit_name(line)
        if not name:
            continue
        anchor = _extract_anchor_from_line(line) or build_knowledge_unit_anchor(name, used=used_anchors)
        tags = _extract_tags(line)
        knowledge_unit_type = _infer_node_type(line, tags.get("type", ""))
        next_index = heading_indexes[position + 1] if position + 1 < len(heading_indexes) else len(lines)
        section_lines = lines[index:next_index]
        body_markdown = _build_body_markdown(section_lines)
        summary = _build_summary(section_lines)
        units.append(
            MarkdownKnowledgeUnit(
                anchor=anchor,
                name=name,
                knowledge_unit_type=knowledge_unit_type,
                summary=summary,
                body_markdown=body_markdown,
                knowledge_images=_extract_knowledge_images(body_markdown),
                prerequisites=_split_tag_values(tags.get("prerequisite", "")),
                related=_split_tag_values(tags.get("related", "")),
                line_no=index + 1,
                heading_level=heading_level,
            )
        )
    return units


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
    return lowered in {
        "table of contents",
        "knowledge document overview",
        "目录",
        "知识文档总览",
        "参考资料与延伸阅读",
    }


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
    "MarkdownKnowledgeUnit",
    "build_knowledge_unit_anchor",
    "ensure_markdown_knowledge_unit_anchors",
    "extract_all_anchor_ids",
    "extract_knowledge_unit_anchor_ids",
    "extract_markdown_knowledge_units",
    "validate_knowledge_unit_anchors",
]
