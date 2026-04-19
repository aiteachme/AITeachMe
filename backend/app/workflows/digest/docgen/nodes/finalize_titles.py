"""Finalize chapter titles before publishing."""

from __future__ import annotations

import re
from time import perf_counter

from pydantic import BaseModel, Field

from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.tools.builtin.markdown_processing import prepend_table_of_contents
from app.shared.infra.workflow.context import WorkflowContext
from app.utils.docgen_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.publish import build_merged_markdown
from app.workflows.digest.docgen.nodes.common import get_effective_chapter_title, publish_docgen_progress
from app.workflows.digest.docgen.prompts import build_finalize_chapter_titles_messages
from app.workflows.digest.docgen.state import DocGenState

_GENERIC_TITLE_RE = re.compile(r"^第\s*\d+\s*章$|^untitled", re.IGNORECASE)
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)


class FinalChapterTitle(BaseModel):
    chapter_index: int
    title: str
    reason: str = ""


class FinalChapterTitleBatch(BaseModel):
    titles: list[FinalChapterTitle] = Field(default_factory=list)


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


def _replace_first_h1(markdown: str, title: str) -> str:
    cleaned = str(markdown or "").strip()
    final_title = _clean_title(title) or "本章内容"
    if not cleaned:
        return f"# {final_title}\n"
    lines = cleaned.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# "):
            lines[index] = f"# {final_title}"
            return "\n".join(lines).strip() + "\n"
        if line.startswith("#"):
            lines[index] = f"# {final_title}"
            return "\n".join(lines).strip() + "\n"
    return f"# {final_title}\n\n{cleaned}\n"


def _chapter_title_context(*, chapter: dict, assignment: dict | None, chapter_index: int) -> dict:
    markdown = str(chapter.get("markdown") or "")
    headings = [
        match.group(2).strip()
        for match in _HEADING_RE.finditer(markdown)
        if match.group(2).strip()
    ][:8]
    return {
        "chapter_index": chapter_index,
        "confirmed_title": get_effective_chapter_title(assignment or {}, fallback_index=chapter_index),
        "current_title": str(chapter.get("title") or chapter.get("resolved_title") or ""),
        "summary": str(chapter.get("summary") or "")[:500],
        "headings": headings,
        "excerpt": markdown[:1200],
    }


async def _resolve_titles_with_llm(
    *,
    state: DocGenState,
    chapter_metadatas: list[dict],
    assignments_by_index: dict[int, dict],
) -> tuple[dict[int, str], dict[str, object]]:
    title_contexts = [
        _chapter_title_context(
            chapter=chapter,
            assignment=assignments_by_index.get(int(chapter.get("chapter_index", index + 1) or index + 1)),
            chapter_index=int(chapter.get("chapter_index", index + 1) or index + 1),
        )
        for index, chapter in enumerate(chapter_metadatas)
    ]
    try:
        result = await acompletion_with_fallback(
            build_finalize_chapter_titles_messages(
                digest_mode=state.get("digest_mode") or "",
                chapters=title_contexts,
            ),
            task_type=TaskType.DOCGEN_LIGHT,
            model="light",
            response_model=FinalChapterTitleBatch,
            extra_metadata={
                "substep": "finalize_chapter_titles",
                "chapter_count": len(chapter_metadatas),
            },
        )
        assert isinstance(result, FinalChapterTitleBatch)
    except Exception as exc:
        return {}, {
            "mode": "rule_fallback",
            "fallback_used": True,
            "error": str(exc)[:180],
        }
    resolved: dict[int, str] = {}
    seen: set[str] = set()
    for item in result.titles:
        title = _clean_title(item.title)
        if not title:
            continue
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        resolved[int(item.chapter_index)] = title
    return resolved, {
        "mode": "llm_structured",
        "fallback_used": False,
        "requested_chapter_count": len(chapter_metadatas),
        "resolved_title_count": len(resolved),
    }


def build_finalize_titles_node(*, context: WorkflowContext):
    """构建最终标题收口节点。

    在整本合并检查之后，统一复核章节标题，保证 metadata 标题和每章
    Markdown 一级标题一致。标题可以优化表达，但不能改变 confirmed plan
    的章节数量、顺序和语义边界。
    """

    async def finalize_titles_node(state: DocGenState) -> dict:
        """复核最终章节标题并重建整本 Markdown。"""

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
        llm_titles, title_review_report = await _resolve_titles_with_llm(
            state=state,
            chapter_metadatas=chapter_metadatas,
            assignments_by_index=assignments_by_index,
        )
        for chapter in chapter_metadatas:
            chapter_index = int(chapter.get("chapter_index", 0) or 0)
            if chapter_index <= 0:
                chapter_index = len(updated_chapters) + 1
            before = _clean_title(str(chapter.get("title") or ""))
            fallback_title = _final_title(
                chapter=chapter,
                assignment=assignments_by_index.get(chapter_index),
                chapter_index=chapter_index,
            )
            final_title = llm_titles.get(chapter_index) or fallback_title
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
                    "source": "llm" if chapter_index in llm_titles else "fallback",
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
                **title_review_report,
                "changed_count": changed_count,
                "chapter_count": len(updated_chapters),
            },
            "finalize_ms": elapsed_ms,
            "llm_calls_total": 0 if title_review_report.get("fallback_used") else 1,
        }

    return finalize_titles_node


__all__ = ["build_finalize_titles_node"]
