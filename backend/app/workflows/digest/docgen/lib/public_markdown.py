"""Public-facing markdown cleanup for generated knowledge documents."""

from __future__ import annotations

import re


_REFERENCE_HEADING_RE = re.compile(
    r"(?ms)^##[ \t]+参考资料与延伸阅读[^\n]*\n.*?(?=^#{1,2}[ \t]+|\Z)"
)
_LLM_SOURCE_SECTION_RE = re.compile(
    r"(?ms)^##[ \t]+LLM 预选的本地资料切片[^\n]*\n.*?(?=^#{1,2}[ \t]+|\Z)"
)
_SOURCE_SLICE_SUBSECTION_RE = re.compile(
    r"(?ms)^###[ \t]+来源切片：[^\n]*\n.*?(?=^#{1,3}[ \t]+|\Z)"
)


def _strip_source_debug_lines(markdown: str) -> str:
    lines = str(markdown or "").splitlines()
    cleaned: list[str] = []
    skipping_context_hint = False

    for line in lines:
        stripped = line.strip()
        if stripped == "可以回看材料中的两条线索：":
            skipping_context_hint = True
            continue
        if skipping_context_hint:
            if stripped.startswith("- ") or not stripped:
                continue
            skipping_context_hint = False

        if "LLM 预选的本地资料切片" in stripped or stripped.startswith("来源切片："):
            continue
        cleaned.append(line)

    return "\n".join(cleaned)


def _strip_post_reading_note(markdown: str) -> str:
    lines = str(markdown or "").splitlines()
    cleaned: list[str] = []
    skipping_note = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("读完《") and "可以把剩下的注意力收回到" in stripped:
            skipping_note = True
            continue
        if skipping_note:
            if stripped.startswith("#"):
                skipping_note = False
                cleaned.append(line)
            continue
        cleaned.append(line)

    return "\n".join(cleaned)


def sanitize_public_markdown(markdown: str) -> str:
    """Remove source/debug appendices that should not be shown in learner docs."""

    text = str(markdown or "")
    if not text.strip():
        return ""
    text = _REFERENCE_HEADING_RE.sub("", text)
    text = _LLM_SOURCE_SECTION_RE.sub("", text)
    text = _SOURCE_SLICE_SUBSECTION_RE.sub("", text)
    text = _strip_source_debug_lines(text)
    text = _strip_post_reading_note(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


__all__ = ["sanitize_public_markdown"]
