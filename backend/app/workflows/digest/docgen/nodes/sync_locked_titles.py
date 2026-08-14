"""Synchronize locked DocGen titles before publishing."""

from __future__ import annotations

import re
from time import perf_counter

from app.shared.infra.tools.builtin.markdown_processing import build_draft_excerpt
from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.knowledge.build_store import (
    append_knowledge_build_recent_event,
    update_knowledge_build_merge_preview,
    update_knowledge_build_status,
)
from app.workflows.digest.common.pedagogy import (
    clean_generated_chapter_title,
    is_usable_resolved_chapter_title,
    resolve_effective_chapter_title,
)
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.publish import build_merged_markdown
from app.workflows.digest.docgen.lib.title_lock import prefer_confirmed_catalog_title
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState

_GENERIC_TITLE_RE = re.compile(r"^第\s*\d+\s*章$|^untitled(?:\s+chapter)?$|^未命名章节$|^本章内容$", re.IGNORECASE)
_TITLE_ENUMERATION_SEPARATORS = ("、", "，", ",", "；", ";", "：", ":", "/", "／")
_TITLE_EXPOSITION_MARKERS = (
    "的定义",
    "几何意义",
    "求导法则",
    "判定",
    "关系及",
    "常用运算",
    "重要极限",
    "适用条件",
)


def _clean_title(title: str) -> str:
    cleaned = " ".join(str(title or "").strip().split())
    cleaned = re.sub(r"^#+\s*", "", cleaned).strip()
    cleaned = clean_generated_chapter_title(cleaned)
    return cleaned


def _prefer_catalog_title(*, catalog_title: str, current_title: str) -> bool:
    catalog = _clean_title(catalog_title)
    current = _clean_title(current_title)
    if not catalog or not is_usable_resolved_chapter_title(catalog):
        return False
    if not current or _GENERIC_TITLE_RE.match(current) or not is_usable_resolved_chapter_title(current):
        return True
    return prefer_confirmed_catalog_title(confirmed_title=catalog, candidate_title=current)


def _looks_overexpanded_title(title: str) -> bool:
    cleaned = _clean_title(title)
    if len(cleaned) > 14:
        return True
    return any(marker in cleaned for marker in (*_TITLE_ENUMERATION_SEPARATORS, *_TITLE_EXPOSITION_MARKERS))


def _meaningful_title_chars(title: str) -> set[str]:
    return {
        char
        for char in _clean_title(title)
        if char.strip() and char not in set("的与和及、，,；;：:/／（）()【】[]")
    }


def _prefer_compact_enhanced_title(*, confirmed_title: str, enhanced_title: str) -> bool:
    confirmed = _clean_title(confirmed_title)
    enhanced = _clean_title(enhanced_title)
    if not enhanced or _GENERIC_TITLE_RE.match(enhanced) or not is_usable_resolved_chapter_title(enhanced):
        return False
    if not confirmed or not is_usable_resolved_chapter_title(confirmed):
        return True
    if not _looks_overexpanded_title(confirmed):
        return False
    if len(enhanced) >= len(confirmed) or len(enhanced) > 14:
        return False
    if any(separator in enhanced for separator in _TITLE_ENUMERATION_SEPARATORS):
        return False
    return bool(_meaningful_title_chars(confirmed) & _meaningful_title_chars(enhanced))


def _locked_title(*, chapter: dict, chapter_index: int, locked_title: dict | None = None) -> tuple[str, str]:
    locked = locked_title or {}
    confirmed = _clean_title(str(locked.get("confirmed_title") or chapter.get("confirmed_title") or ""))
    enhanced = _clean_title(str(locked.get("enhanced_title") or chapter.get("enhanced_title") or ""))
    current = _clean_title(str(chapter.get("resolved_title") or chapter.get("title") or ""))
    if _prefer_compact_enhanced_title(confirmed_title=confirmed, enhanced_title=enhanced):
        return enhanced, "locked_compact_title"
    if confirmed and is_usable_resolved_chapter_title(confirmed):
        return confirmed, "confirmed_plan_title"
    if _prefer_catalog_title(catalog_title=confirmed, current_title=current or enhanced):
        return confirmed, "confirmed_plan_title"
    if enhanced and is_usable_resolved_chapter_title(enhanced) and not _GENERIC_TITLE_RE.match(enhanced):
        if not confirmed or not _prefer_catalog_title(catalog_title=confirmed, current_title=enhanced):
            return enhanced, "locked_enhanced_title"
    if current and not _GENERIC_TITLE_RE.match(current) and is_usable_resolved_chapter_title(current):
        return current, "chapter_metadata_title"
    derived = resolve_effective_chapter_title(chapter, chapter_index=chapter_index, fallback_title=current)
    if is_usable_resolved_chapter_title(derived):
        return derived, "derived_title"
    return f"第 {chapter_index} 章", "fallback_chapter_index"


def _replace_first_h1(markdown: str, title: str) -> str:
    cleaned = str(markdown or "").strip()
    final_title = _clean_title(title) or "本章内容"
    if not cleaned:
        return f"# {final_title}\n"
    lines = cleaned.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("#"):
            lines[index] = f"# {final_title}"
            return "\n".join(lines).strip() + "\n"
    return f"# {final_title}\n\n{cleaned}\n"


def build_sync_locked_titles_node(*, context: WorkflowContext):
    """构建标题同步节点。

    标题在 `lock_titles_for_chapters` 阶段已经锁定。这里只同步 metadata 和每章 Markdown 一级标题，不再
    调用 LLM，也不重新发明标题。
    """

    async def sync_locked_titles_node(state: DocGenState) -> dict:
        """把已锁定标题同步到章节 metadata、正文 H1 和整本 Markdown。"""

        started_at = perf_counter()
        chapter_metadatas = sorted(
            list(state.get("chapter_metadatas") or []),
            key=lambda item: int(item.get("chapter_index", 0) or 0),
        )
        if not chapter_metadatas:
            return {"error": "没有可同步标题的章节元数据。"}

        title_records: list[dict[str, object]] = []
        updated_chapters: list[dict] = []
        changed_count = 0
        locked_by_index = {
            int(item.get("chapter_index", 0) or 0): dict(item)
            for item in list(state.get("locked_titles") or [])
            if isinstance(item, dict)
        }
        for chapter in chapter_metadatas:
            chapter_index = int(chapter.get("chapter_index", 0) or 0) or len(updated_chapters) + 1
            before = _clean_title(str(chapter.get("title") or ""))
            final_title, title_source = _locked_title(
                chapter=chapter,
                chapter_index=chapter_index,
                locked_title=locked_by_index.get(chapter_index),
            )
            updated = dict(chapter)
            updated["title"] = final_title
            updated["resolved_title"] = final_title
            updated["markdown"] = _replace_first_h1(str(updated.get("markdown") or ""), final_title)
            updated_chapters.append(updated)
            changed = before != final_title
            changed_count += 1 if changed else 0
            title_records.append(
                {
                    "chapter_index": chapter_index,
                    "before": before,
                    "after": final_title,
                    "changed": changed,
                    "source": title_source,
                }
            )

        cover_artifact = dict(state.get("cover_artifact") or {})
        cover_markdown = str(state.get("cover_markdown") or "").strip()

        merged_markdown = build_merged_markdown(
            updated_chapters,
            document_context=dict(state.get("document_context") or {}),
            cover_markdown=cover_markdown,
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        update_knowledge_build_status(
            state["course_id"],
            requested_at=state["requested_at"],
            build_group_id=state.get("build_group_id") or None,
            status="running",
            stage="titles_finalized",
            digest_mode=state.get("digest_mode") or None,
            staged_chapter_count=len(updated_chapters),
            draft_available=bool(merged_markdown.strip()),
            current_stage_description="章节标题已按前置执行合同同步。",
        )
        update_knowledge_build_merge_preview(
            state["course_id"],
            requested_at=state["requested_at"],
            build_group_id=state.get("build_group_id") or None,
            merge_preview={
                "latest_chapter_titles": [chapter["title"] for chapter in updated_chapters],
                "draft_excerpt": build_draft_excerpt(merged_markdown, max_chars=1600),
            },
        )
        append_knowledge_build_recent_event(
            state["course_id"],
            requested_at=state["requested_at"],
            build_group_id=state.get("build_group_id") or None,
            event={
                "stage": "titles_finalized",
                "summary": "章节标题已按前置执行合同同步，未进行二次生成。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="titles_finalized",
            payload={
                "changed_title_count": changed_count,
                "chapter_count": len(updated_chapters),
                "mode": "locked_dispatch_title",
            },
        )
        return {
            "chapter_metadatas": updated_chapters,
            "cover_artifact": cover_artifact,
            "cover_markdown": cover_markdown,
            "merged_markdown": merged_markdown,
            "enriched_markdown": merged_markdown,
            "final_chapter_titles": title_records,
            "title_review_report": {
                "mode": "locked_dispatch_title",
                "fallback_used": False,
                "llm_used": False,
                "changed_count": changed_count,
                "chapter_count": len(updated_chapters),
            },
            "finalize_ms": elapsed_ms,
            "llm_calls_total": 0,
        }

    return sync_locked_titles_node


__all__ = ["build_sync_locked_titles_node"]
