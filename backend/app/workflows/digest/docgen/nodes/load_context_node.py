"""Load context node for the DocGen lane."""

from __future__ import annotations

from copy import deepcopy

from pydantic import ValidationError

from app.shared.infra.skills import (
    collect_recommended_tool_tags,
    collect_skillpack_defaults,
    render_prompt_scoped_skillpacks,
    resolve_skillpacks,
)
from app.utils.docgen_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docgen.nodes.common import (
    get_effective_chapter_title,
    normalize_confirmed_plan_contract,
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

        digest_mode = state.get("digest_mode") or shared_inputs.digest_mode_decision.mode.value
        tone = str(state.get("tone") or "").strip()
        raw_plan_payload = deepcopy(state.get("confirmed_plan") or {})
        if not raw_plan_payload:
            return {"error": "DocGen 缺少已确认的构建方案，不能直接进入文档生成。"}

        try:
            plan_contract = normalize_confirmed_plan_contract(raw_plan_payload)
        except ValidationError as exc:
            first_error = exc.errors()[0] if exc.errors() else {}
            location = ".".join(str(item) for item in list(first_error.get("loc") or []))
            location = location or "confirmed_plan"
            return {"error": f"已确认的构建方案字段不完整或格式错误：{location}"}

        if not plan_contract.chapter_plan:
            return {"error": "已确认的构建方案缺少章节规划，无法继续生成知识文档。"}

        digest_mode = str(plan_contract.digest_mode or digest_mode)
        course_type = plan_contract.resolve_course_type()
        retrieval_profile = plan_contract.resolve_retrieval_profile()
        selected_skillpacks = [definition.name for definition in resolve_skillpacks(plan_contract.selected_skillpacks)]
        skillpack_defaults = collect_skillpack_defaults(selected_skillpacks, prompt_scope="digest.docgen")
        tone = str(plan_contract.tone or tone or skillpack_defaults.get("tone") or "encouraging")
        assignments = plan_contract.to_chapter_assignments(
            default_source_file_ids=list(state.get("file_ids", [])),
        )
        if not assignments:
            return {"error": "已确认的构建方案中没有可执行的章节。"}
        plan_payload = plan_contract.to_payload()
        plan_payload["course_type"] = course_type
        plan_payload["retrieval_profile"] = retrieval_profile
        plan_payload["selected_skillpacks"] = selected_skillpacks

        has_local_materials = bool(shared_inputs.source_packets)
        document_context = {
            "subject": state["subject"],
            "digest_mode": digest_mode,
            "course_type": course_type,
            "retrieval_profile": retrieval_profile,
            "teaching_action": str(state.get("teaching_action") or "docgen_build"),
            "tone": tone,
            "user_goal": str(plan_contract.user_goal or state.get("user_prompt") or ""),
            "plan_summary": str(plan_contract.plan_summary or ""),
            "source_strategy": "local_first" if has_local_materials else "web_first",
            "selected_skillpacks": selected_skillpacks,
            "skillpack_defaults": skillpack_defaults,
            "recommended_tool_tags": collect_recommended_tool_tags(
                selected_skillpacks,
                prompt_scope="digest.docgen",
            ),
            "skillpack_guidance": render_prompt_scoped_skillpacks(
                selected_skillpacks,
                prompt_scope="digest.docgen",
                bindings={
                    "subject": state["subject"],
                    "user_goal": str(plan_contract.user_goal or state.get("user_prompt") or ""),
                    "topic": state["subject"],
                    "concept": state["subject"],
                },
            ),
        }

        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="planner_confirmed",
            planner_session_id=state.get("planner_session_id") or None,
            confirmed_plan_id=state.get("confirmed_plan_id") or None,
            digest_mode=digest_mode,
            mode_reason=(plan_contract.mode_reason or "confirmed_build_plan"),
            current_stage_description=(
                str(plan_contract.plan_summary or "方案已确认，开始按章节执行。")
                if has_local_materials
                else str(plan_contract.plan_summary or "方案已确认，当前没有本地资料，将优先执行联网研究。")
            ),
            total_chunks=len(assignments),
            processed_chunks=0,
            current_chunk=0,
            plan_summary=str(plan_contract.plan_summary or ""),
            chapter_progress=[
                {
                    "chapter_index": int(item.get("chapter_index", index + 1) or (index + 1)),
                    "title": get_effective_chapter_title(
                        item,
                        fallback_index=int(item.get("chapter_index", index + 1) or (index + 1)),
                    ),
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
                "summary": (
                    f"方案已确认，共 {len(assignments)} 章，开始准备章节研究。"
                    if has_local_materials
                    else f"方案已确认，共 {len(assignments)} 章，当前没有本地资料，将直接进入联网研究。"
                ),
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="plan_ready",
            payload={
                "digest_mode": digest_mode,
                "course_type": course_type,
                "retrieval_profile": retrieval_profile,
                "chapter_count": len(assignments),
                "planner_session_id": state.get("planner_session_id", ""),
                "confirmed_plan_id": state.get("confirmed_plan_id", ""),
                "local_source_count": len(shared_inputs.source_packets),
            },
        )
        return {
            "shared_inputs": shared_inputs,
            "raw_chunks": [serialize_section(section) for section in shared_inputs.section_packets],
            "subject_profile": shared_inputs.subject_profile.model_dump(mode="json"),
            "chapter_assignments": assignments,
            "confirmed_plan": plan_payload,
            "digest_mode": digest_mode,
            "course_type": course_type,
            "retrieval_profile": retrieval_profile,
            "teaching_action": str(state.get("teaching_action") or "docgen_build"),
            "tone": tone,
            "selected_skillpacks": selected_skillpacks,
            "document_context": document_context,
            "planner_ms": 0,
        }

    return load_context_node


__all__ = ["build_load_context_node"]
