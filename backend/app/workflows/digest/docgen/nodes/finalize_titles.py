"""Finalize chapter titles before publishing."""

from __future__ import annotations

import re
from time import perf_counter

from app.shared.infra.tools.builtin.markdown_processing import prepend_table_of_contents
from app.shared.infra.workflow.context import WorkflowContext
from app.utils.docgen_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.publish import build_merged_markdown
from app.workflows.digest.docgen.nodes.common import get_effective_chapter_title, publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState

_GENERIC_TITLE_RE = re.compile(r"^第\s*\d+\s*章$|^untitled", re.IGNORECASE)


def _clean_title(title: str) -> str:
    cleaned = " ".join(str(title or "").strip().split())
    cleaned = re.sub(r"^#+\s*", "", cleaned).strip()
    return cleaned


def _final_title(*, chapter: dict, assignment: dict | None, chapter_index: int) -> str:
    current = _clean_title(str(chapter.get("resolved_title") or chapter.get("title") or ""))
    confirmed = _clean_title(
        get_effective_chapter_title(
            assignment or {},
            fallback_index=chapter_index,
        )
    )
    if not current or _GENERIC_TITLE_RE.match(current):
        return confirmed or f"第 {chapter_index} 章"
    return current


def build_finalize_titles_node(*, context: WorkflowContext):
    async def finalize_titles_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        chapter_metadatas = sorted(
            list(state.get("chapter_metadatas") or []),
            key=lambda item: int(item.get("chapter_index", 0) or 0),
        )
        if not chapter_metadatas:
            return {"error": "没有可收口标题的章节元数据。"}
        assignments_by_index = {
            int(item.get("chapter_index", index + 1) or index + 1): item
            for index, item in enumerate(list(state.get("chapter_assignments") or []))
        }
        title_records: list[dict[str, object]] = []
        updated_chapters: list[dict] = []
        changed_count = 0
        for chapter in chapter_metadatas:
            chapter_index = int(chapter.get("chapter_index", 0) or 0)
            if chapter_index <= 0:
                chapter_index = len(updated_chapters) + 1
            before = _clean_title(str(chapter.get("title") or ""))
            final_title = _final_title(
                chapter=chapter,
                assignment=assignments_by_index.get(chapter_index),
                chapter_index=chapter_index,
            )
            updated = dict(chapter)
            updated["title"] = final_title
            updated["resolved_title"] = final_title
            updated_chapters.append(updated)
            changed = before != final_title
            changed_count += 1 if changed else 0
            title_records.append(
                {
                    "chapter_index": chapter_index,
                    "before": before,
                    "after": final_title,
                    "changed": changed,
                }
            )
        merged_markdown = prepend_table_of_contents(
            build_merged_markdown(
                updated_chapters,
                document_context=dict(state.get("document_context") or {}),
            ),
            min_level=2,
            max_level=4,
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="titles_finalized",
            digest_mode=state.get("digest_mode") or None,
            staged_chapter_count=len(updated_chapters),
            draft_available=bool(merged_markdown.strip()),
            current_stage_description=f"章节标题收口完成，调整 {changed_count} 个标题。",
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "titles_finalized",
                "summary": f"章节标题收口完成，调整 {changed_count} 个标题。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="titles_finalized",
            payload={"changed_title_count": changed_count, "chapter_count": len(updated_chapters)},
        )
        return {
            "chapter_metadatas": updated_chapters,
            "merged_markdown": merged_markdown,
            "enriched_markdown": merged_markdown,
            "final_chapter_titles": title_records,
            "title_review_report": {
                "changed_count": changed_count,
                "chapter_count": len(updated_chapters),
            },
            "finalize_ms": elapsed_ms,
        }

    return finalize_titles_node


__all__ = ["build_finalize_titles_node"]
