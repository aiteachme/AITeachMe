"""Shared DocGen artifact selectors for chapter-level branches."""

from __future__ import annotations

from typing import Any


def _compact_profile_text(value: str) -> str:
    return " ".join(str(value or "").split())


def merge_unique_profile_texts(*values: str) -> str:
    """Merge prompt profile fragments without repeating the same signal."""

    chunks: list[str] = []
    compact_chunks: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        compact = _compact_profile_text(text)
        if not compact:
            continue
        if any(compact == existing or compact in existing for existing in compact_chunks):
            continue
        superseded = [index for index, existing in enumerate(compact_chunks) if existing in compact]
        for index in reversed(superseded):
            del chunks[index]
            del compact_chunks[index]
        chunks.append(text)
        compact_chunks.append(compact)
    return "\n".join(chunks).strip()


def mapping_list(value: object) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)]


def contract_item_for_chapter(payload: dict[str, Any], chapter_index: int) -> dict[str, Any]:
    for item in mapping_list(payload.get("items") or payload.get("chapters")):
        if int(item.get("chapter_index", 0) or 0) == chapter_index:
            return item
    return {}


def guideline_summary_for_chapter(guideline: dict[str, Any], chapter_index: int) -> dict[str, Any]:
    def scoped_items(key: str, *, limit: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in mapping_list(guideline.get(key)):
            targets = [int(value or 0) for value in list(item.get("target_chapters") or [])]
            if not targets or chapter_index in targets:
                items.append(item)
            if len(items) >= limit:
                break
        return items

    return {
        "writing_rules": list(guideline.get("writing_rules") or [])[:12],
        "canonical_glossary": scoped_items("canonical_glossary", limit=12),
        "notation_rules": scoped_items("notation_rules", limit=8),
        "confusion_checks": scoped_items("confusion_checks", limit=8),
        "global_claim_count": int(guideline.get("claim_count", 0) or 0),
    }


def evidence_items_for_chapter(summary_enhanced: dict[str, Any], chapter_index: int) -> list[dict[str, Any]]:
    wanted: set[str] = set()
    for item in mapping_list(summary_enhanced.get("chapter_evidence_map")):
        if int(item.get("chapter_index", 0) or 0) == chapter_index:
            wanted.update(str(value) for value in list(item.get("evidence_ids") or []) if str(value).strip())
    items = mapping_list(summary_enhanced.get("high_confidence_evidence") or summary_enhanced.get("high_confidence_evidence_units"))
    if wanted:
        return [item for item in items if str(item.get("evidence_id") or "") in wanted][:16]
    return [
        item
        for item in items
        if chapter_index in [int(value or 0) for value in list(item.get("chapter_indices") or [])]
    ][:16]


def learner_profile_text_for_branch(
    *,
    docgen_context_text: str = "",
    state_profile_text: str = "",
    user_profile: dict[str, Any] | None = None,
) -> str:
    return merge_unique_profile_texts(
        docgen_context_text,
        state_profile_text,
        str((user_profile or {}).get("prompt_addendum") or "").strip(),
    ).strip()


__all__ = [
    "contract_item_for_chapter",
    "evidence_items_for_chapter",
    "guideline_summary_for_chapter",
    "learner_profile_text_for_branch",
    "mapping_list",
    "merge_unique_profile_texts",
]
