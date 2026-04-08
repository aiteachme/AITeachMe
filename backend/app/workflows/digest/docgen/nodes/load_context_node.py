"""Load context node for the DocGen lane."""

from __future__ import annotations

from copy import deepcopy

from app.utils.docgen_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docgen.nodes.common import (
    normalize_chapter_assignments,
    publish_docgen_progress,
    serialize_section,
)
from app.workflows.digest.docgen.state import DocGenState
from app.workflows.digest.shared.prepare import prepare_shared_inputs


def build_load_context_node(*, context: WorkflowContext):
    async def load_context_node(state: DocGenState) -> dict:
        shared_inputs = state.get("shared_inputs")
        if shared_inputs is None:
            build_session_id = state.get("build_session_id", "")
            if build_session_id:
                try:
                    from app.workflows.digest.unified.session import get_unified_build_session

                    shared_inputs = get_unified_build_session(build_session_id).shared_inputs
                except KeyError:
                    shared_inputs = None
        if shared_inputs is None:
            shared_inputs = await prepare_shared_inputs(
                state["subject"],
                state.get("file_ids", []),
                user_prompt=state.get("user_prompt"),
            )
        if not shared_inputs.source_packets:
            return {"error": "当前没有可用于文档构建的已解析资料。"}

        digest_mode = state.get("digest_mode") or shared_inputs.digest_mode_decision.mode.value
        tone = state.get("tone") or "encouraging"
        plan_payload = deepcopy(state.get("confirmed_plan") or {})
        if not plan_payload:
            return {"error": "DocGen 缺少已确认的构建方案，不能直接进入文档生成。"}
        if not plan_payload.get("chapter_plan"):
            return {"error": "已确认的构建方案缺少章节规划，无法继续生成知识文档。"}

        digest_mode = str(plan_payload.get("digest_mode") or digest_mode)
        tone = str(plan_payload.get("tone") or tone)
        assignments = normalize_chapter_assignments(
            plan_payload.get("chapter_plan") or [],
            default_source_file_ids=list(state.get("file_ids", [])),
        )
        if not assignments:
            return {"error": "已确认的构建方案中没有可执行的章节。"}

        document_context = {
            "subject": state["subject"],
            "digest_mode": digest_mode,
            "tone": tone,
            "user_goal": str(plan_payload.get("user_goal") or state.get("user_prompt") or ""),
            "plan_summary": str(plan_payload.get("plan_summary") or ""),
        }

        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="planner_confirmed",
            planner_session_id=state.get("planner_session_id") or None,
            confirmed_plan_id=state.get("confirmed_plan_id") or None,
            digest_mode=digest_mode,
            mode_reason=(plan_payload.get("mode_reason") or "confirmed_build_plan"),
            current_stage_description=str(plan_payload.get("plan_summary") or "方案已确认，开始按章节执行。"),
            total_chunks=len(assignments),
            processed_chunks=0,
            current_chunk=0,
            plan_summary=str(plan_payload.get("plan_summary") or ""),
            chapter_progress=[
                {
                    "chapter_index": int(item.get("chapter_index", index + 1) or (index + 1)),
                    "title": str(item.get("title") or f"第 {index + 1} 章").strip() or f"第 {index + 1} 章",
                    "status": "planned",
                    "source_count": 0,
                    "local_hits": 0,
                    "web_hits": 0,
                    "query_count": 0,
                    "word_count": 0,
                    "fallback_used": False,
                }
                for index, item in enumerate(assignments)
            ],
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "planner_confirmed",
                "summary": f"方案已确认，共 {len(assignments)} 章，开始准备章节研究。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="plan_ready",
            payload={
                "digest_mode": digest_mode,
                "chapter_count": len(assignments),
                "planner_session_id": state.get("planner_session_id", ""),
                "confirmed_plan_id": state.get("confirmed_plan_id", ""),
            },
        )
        return {
            "shared_inputs": shared_inputs,
            "raw_chunks": [serialize_section(section) for section in shared_inputs.section_packets],
            "subject_profile": shared_inputs.subject_profile.model_dump(mode="json"),
            "chapter_assignments": assignments,
            "confirmed_plan": plan_payload,
            "digest_mode": digest_mode,
            "tone": tone,
            "document_context": document_context,
            "planner_ms": 0,
        }

    return load_context_node


__all__ = ["build_load_context_node"]
