"""Load context node for the DocGen lane."""

from __future__ import annotations

from copy import deepcopy

from pydantic import ValidationError

from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.nodes.common import (
    get_effective_chapter_title,
    normalize_confirmed_plan_contract,
    publish_docgen_progress,
    serialize_section,
)
from app.workflows.digest.docgen.lib.models import DocGenContext
from app.workflows.digest.docgen.state import DocGenState
from app.workflows.digest.common.prepare import prepare_shared_inputs


def build_load_context_node(*, context: WorkflowContext):
    """构建 DocGen 上下文加载节点。

    这是 DocGen 图的入口：读取 confirmed plan 和 shared_inputs，校验章节
    合同，解析 digest mode / retrieval profile，并初始化前端可见的构建状态。
    """

    async def load_context_node(state: DocGenState) -> dict:
        """把构建请求转换成 DocGen 后续节点可消费的基础状态。"""

        shared_inputs = state.get("shared_inputs")
        if shared_inputs is None:
            shared_inputs = await prepare_shared_inputs(
                state["subject"],
                state.get("file_ids", []),
                user_prompt=state.get("user_prompt"),
            )
        

        digest_mode = state.get("digest_mode") or shared_inputs.digest_mode_decision.mode.value
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
        retrieval_profile = plan_contract.resolve_retrieval_profile()
        assignments = plan_contract.to_chapter_assignments(
            default_source_file_ids=list(state.get("file_ids", [])),
        )
        if not assignments:
            return {"error": "已确认的构建方案中没有可执行的章节。"}
        plan_payload = plan_contract.to_payload()
        plan_payload["retrieval_profile"] = retrieval_profile
        planner_context = dict(plan_payload.get("planner_context") or {})
        docgen_history_brief = str(
            plan_payload.get("docgen_history_brief")
            or planner_context.get("docgen_history_brief")
            or ""
        ).strip()

        has_local_materials = bool(shared_inputs.source_packets)
        plan_subject_label = str(plan_contract.subject or plan_contract.user_prompt or "").strip()
        document_context = {
            "subject": state["subject"],
            "subject_display_name": plan_subject_label,
            "digest_mode": digest_mode,
            "retrieval_profile": retrieval_profile,
            "teaching_action": str(state.get("teaching_action") or "docgen_build"),
            "user_prompt": str(plan_contract.user_prompt or state.get("user_prompt") or ""),
            "plan_summary": str(plan_contract.plan_summary or ""),
            "docgen_history_brief": docgen_history_brief,
            "planner_context": planner_context,
            "source_strategy": "local_first" if has_local_materials else "web_first",
            "include_sources": bool((plan_payload.get("build_constraints") or {}).get("include_sources", True)),
        }
        docgen_context = DocGenContext(
            subject=state["subject"],
            subject_display_name=plan_subject_label,
            digest_mode=digest_mode,
            retrieval_profile=retrieval_profile,
            user_prompt=str(plan_contract.user_prompt or state.get("user_prompt") or ""),
            plan_summary=str(plan_contract.plan_summary or ""),
            docgen_history_brief=docgen_history_brief,
            planner_context=planner_context,
            source_strategy="local_first" if has_local_materials else "web_first",
            include_sources=bool((plan_payload.get("build_constraints") or {}).get("include_sources", True)),
            local_source_count=len(shared_inputs.source_packets),
            section_count=len(shared_inputs.section_packets),
        )

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
            "docgen_context": docgen_context.model_dump(mode="json"),
            "digest_mode": digest_mode,
            "retrieval_profile": retrieval_profile,
            "teaching_action": str(state.get("teaching_action") or "docgen_build"),
            "document_context": document_context,
            "planner_ms": 0,
        }

    return load_context_node


__all__ = ["build_load_context_node"]
