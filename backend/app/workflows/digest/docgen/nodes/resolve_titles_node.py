"""Resolve final chapter titles from research context before writing."""

from __future__ import annotations

import asyncio
from copy import deepcopy

from app.shared.infra.config import get_settings
from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.llm_support.routing import TaskType
from app.teaching.documents import (
    build_chapter_title_resolution_messages,
    coerce_resolved_chapter_title,
)
from app.utils.docgen_store import append_knowledge_build_recent_event, update_knowledge_build_status, upsert_knowledge_build_chapter_progress
from app.utils.time import utcnow
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.nodes.common import get_effective_chapter_title, publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def _extract_source_titles(material: dict[str, object]) -> list[str]:
    explicit_titles = [str(item).strip() for item in material.get("source_titles", []) if str(item).strip()]
    if explicit_titles:
        return explicit_titles[:4]
    titles: list[str] = []
    seen: set[str] = set()
    for item in material.get("source_details", []) or []:
        title = str((item or {}).get("title") or "").strip()
        if not title:
            continue
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        titles.append(title)
        if len(titles) >= 4:
            break
    return titles


async def _resolve_material_title(material: dict[str, object], state: DocGenState) -> dict[str, object]:
    resolved = deepcopy(material)
    chapter_index = int(resolved.get("chapter_index", 0) or 0)
    fallback_title = get_effective_chapter_title(resolved, fallback_index=chapter_index)
    dense_context = str(resolved.get("dense_context") or "").strip()
    source_titles = _extract_source_titles(resolved)
    search_queries = [str(item).strip() for item in resolved.get("search_queries", []) if str(item).strip()]

    if not any([dense_context, source_titles, search_queries, str(resolved.get("objective") or "").strip()]):
        resolved["resolved_title"] = fallback_title
        return resolved

    messages = build_chapter_title_resolution_messages(
        subject=state["subject"],
        digest_mode=str(state.get("digest_mode") or ""),
        objective=str(resolved.get("objective") or ""),
        required_elements=[str(item) for item in resolved.get("required_elements", []) if str(item).strip()],
        search_queries=search_queries,
        writing_instructions=str(resolved.get("writing_instructions") or ""),
        dense_context=dense_context,
        source_titles=source_titles,
        local_hits=int(resolved.get("local_hits", 0) or 0),
        web_hits=int(resolved.get("web_hits", 0) or 0),
    )
    raw_title = await acompletion_with_fallback(
        messages,
        task_type=TaskType.DOCGEN_LIGHT,
        tier="light",
        max_tokens=48,
        temperature=0.2,
        extra_metadata={
            "planner_session_id": state.get("planner_session_id") or "",
            "confirmed_plan_id": state.get("confirmed_plan_id") or "",
            "build_session_id": state.get("build_session_id") or "",
            "digest_mode": state.get("digest_mode") or "",
            "course_type": state.get("course_type") or "",
            "retrieval_profile": state.get("retrieval_profile") or "",
            "teaching_action": "chapter_title_resolve",
            "chapter_index": chapter_index,
        },
    )

    resolved["resolved_title"] = coerce_resolved_chapter_title(
        str(raw_title or ""),
        chapter=resolved,
        chapter_index=chapter_index,
    )
    return resolved


def build_resolve_titles_node(*, context: WorkflowContext):
    async def resolve_titles_node(state: DocGenState) -> dict:
        materials = sorted(
            deepcopy(list(state.get("chapter_materials", []))),
            key=lambda item: item.get("chapter_index", 0),
        )
        if not materials:
            return {"error": "当前没有可用于标题解析的章节研究结果。"}

        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="drafting",
            digest_mode=state.get("digest_mode") or None,
            processed_chunks=len(materials),
            total_chunks=len(materials),
            current_chunk=len(materials),
            current_stage_description=f"已完成 {len(materials)} 章研究，正在根据研究结果确定最终章节标题。",
        )

        semaphore = asyncio.Semaphore(max(1, int(get_settings().docgen_max_parallel_chapters)))

        async def _run_with_limit(material: dict[str, object]) -> dict[str, object]:
            async with semaphore:
                return await _resolve_material_title(material, state)

        resolved_materials = await asyncio.gather(*(_run_with_limit(material) for material in materials))
        for material in resolved_materials:
            chapter_index = int(material.get("chapter_index", 0) or 0)
            chapter_title = get_effective_chapter_title(material, fallback_index=chapter_index)
            upsert_knowledge_build_chapter_progress(
                state["subject"],
                requested_at=state["requested_at"],
                chapter_progress={
                    "chapter_index": chapter_index,
                    "title": chapter_title,
                    "status": "researched",
                    "source_count": len(list(material.get("sources") or [])),
                    "local_hits": int(material.get("local_hits", 0) or 0),
                    "web_hits": int(material.get("web_hits", 0) or 0),
                    "query_count": int(material.get("query_count", 0) or 0),
                    "fallback_used": bool(material.get("fallback_used", False)),
                },
            )

        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "title_resolution_completed",
                "summary": f"章节研究标题已收口，共 {len(resolved_materials)} 章，开始进入教学写作。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="title_resolution_completed",
            payload={
                "chapter_count": len(resolved_materials),
                "resolved_title_count": sum(1 for item in resolved_materials if str(item.get("resolved_title") or "").strip()),
            },
        )
        return {"chapter_materials": resolved_materials}

    return resolve_titles_node


__all__ = ["build_resolve_titles_node"]


