"""Markdown-carried KnowledgeUnit anchor helpers.

The P2 contract keeps the stable identity in Markdown itself. A knowledge
unit anchor is written as a hidden HTML comment on a heading or labeled block.
Optional inline tags such as ``[type: definition]`` and
``[prerequisite: Linear function]`` can guide graph extraction.
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
_LABEL_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?"
    r"(?P<label>定义|定理|公式|例题|示例|练习|证明|备注|Definition|Theorem|Formula|Example|Exercise|Proof|Remark)"
    r"(?:\*\*)?\s*[:：]",
    re.IGNORECASE,
)
_MARKDOWN_DECORATION_RE = re.compile(r"[#*_`>{}\[\]()]")
_MULTISPACE_RE = re.compile(r"\s+")
_SKIPPABLE_HEADING_EXACT = {
    "table of contents",
    "knowledge document overview",
    "目录",
    "知识文档总览",
    "参考资料与延伸阅读",
    "这份文档怎么读",
    "章节路线图",
    "本章自检",
    "这几项不能漏",
    "回看时优先问自己",
}
_SKIPPABLE_HEADING_PREFIXES = (
    "考前最后",
    "再把关键点压实",
    "再把关键结构补稳",
    "最终回顾",
    "临考速记",
    "本章在考什么",
    "本章核心考点",
    "本章核心地位",
    "本章为何",
    "易错点复盘",
    "高频陷阱",
)

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
    """A KnowledgeUnit candidate declared by a Markdown anchor."""

    anchor: str
    name: str
    knowledge_unit_type: str = "concept"
    summary: str = ""
    prerequisites: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    line_no: int = 0


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
    """Extract KnowledgeUnit candidates from Markdown anchor declarations."""

    lines = markdown.splitlines()
    units: list[MarkdownKnowledgeUnit] = []
    for index, line in enumerate(lines):
        anchor = _extract_anchor_from_line(line)
        if anchor is None:
            continue

        name = _extract_unit_name(line)
        if not name:
            continue
        if _is_skippable_heading(name):
            continue

        tags = _extract_tags(line)
        knowledge_unit_type = _infer_node_type(line, tags.get("type", ""))
        summary = _build_summary(lines, index)
        units.append(
            MarkdownKnowledgeUnit(
                anchor=anchor,
                name=name,
                knowledge_unit_type=knowledge_unit_type,
                summary=summary,
                prerequisites=_split_tag_values(tags.get("prerequisite", "")),
                related=_split_tag_values(tags.get("related", "")),
                line_no=index + 1,
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
    if lowered in _SKIPPABLE_HEADING_EXACT:
        return True
    return any(lowered.startswith(prefix.casefold()) for prefix in _SKIPPABLE_HEADING_PREFIXES)


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


def _build_summary(lines: list[str], index: int) -> str:
    parts: list[str] = []
    for line in lines[index : index + 4]:
        stripped = _strip_tags_and_anchor(line)
        if stripped:
            parts.append(stripped)
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
