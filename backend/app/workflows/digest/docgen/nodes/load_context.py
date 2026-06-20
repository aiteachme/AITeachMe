"""Load context node for the DocGen lane."""

from __future__ import annotations

from copy import deepcopy

from pydantic import ValidationError

from app.shared.infra.settings import get_settings
from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.nodes.common import (
    get_effective_chapter_title,
    normalize_confirmed_plan_contract,
    publish_docgen_progress,
    serialize_section,
)
from app.workflows.digest.docgen.lib.learner_profile import load_docgen_learner_profile_context
from app.workflows.digest.docgen.lib.models import DocGenContext
from app.workflows.digest.docgen.state import DocGenState
from app.workflows.digest.common.contracts import build_digest_retrieval_policy
from app.workflows.digest.common.diagnose_policy import diagnose_answer_action, render_diagnose_action_policy
from app.workflows.digest.common.indexing import materialize_course_inputs_for_retrieval
from app.workflows.digest.common.prepare import prepare_shared_inputs


def _render_diagnose_brief(
    items: list[dict],
    *,
    status: str = "",
    note: str = "",
) -> str:
    lines: list[str] = []
    normalized_status = " ".join(str(status or "").split()).strip()
    normalized_note = " ".join(str(note or "").split()).strip()
    if normalized_status == "skipped":
        lines.append("用户跳过了前置诊断。")
    if normalized_note:
        lines.append(f"用户补充：{normalized_note}")
    for index, raw in enumerate(items[:5], start=1):
        if not isinstance(raw, dict):
            continue
        question = " ".join(str(raw.get("question") or "").split()).strip()
        if not question:
            continue
        purpose = " ".join(str(raw.get("purpose") or "").split()).strip()
        answer = " ".join(str(raw.get("answer") or "").split()).strip()
        options = [
            " ".join(str(item or "").split()).strip()
            for item in list(raw.get("options") or raw.get("sample_answers") or [])[:4]
            if str(item or "").strip()
        ]
        suffix_parts = []
        if answer:
            suffix_parts.append(f"用户回答：{answer}")
        if purpose:
            purpose_text = purpose.removeprefix("文档落点：").removeprefix("文档落点:").strip()
            suffix_parts.append(f"文档落点：{purpose_text}")
        if answer:
            action = diagnose_answer_action(answer, question=question, purpose=purpose)
            if action:
                suffix_parts.append(f"执行策略：{action}")
        if options and not answer:
            suffix_parts.append("可选项：" + " / ".join(options))
        suffix = "；" + "；".join(suffix_parts) if suffix_parts else ""
        lines.append(f"{index}. {question}{suffix}")
    if not lines:
        return ""
    if normalized_status == "answered":
        lines.append("")
        lines.append("诊断选项执行策略：")
        lines.append(render_diagnose_action_policy(items, status=normalized_status))
        lines.append(
            "硬性生成约束：每章至少在讲解起点、例题/练习配置、文档内解析方式、错因提醒或章末小测配置中响应上述诊断；"
            "优先补用户回答暴露的薄弱点，不要只复述问卷。"
        )
    return "前置诊断信号：\n" + "\n".join(lines)


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
                state["course_id"],
                state.get("file_ids", []),
                user_prompt=state.get("user_prompt"),
            )
        await materialize_course_inputs_for_retrieval(
            course_id=state["course_id"],
            shared_inputs=shared_inputs,
            reason="digest.docgen.load_context",
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

        if not plan_contract.chapters:
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
        build_constraints = dict(plan_payload.get("build_constraints") or {})
        planner_context = dict(plan_payload.get("planner_context") or {})
        diagnose = [
            dict(item)
            for item in list(plan_payload.get("diagnose") or [])
            if isinstance(item, dict)
        ][:5]
        diagnose_status = str(plan_payload.get("diagnose_status") or "").strip()
        diagnose_note = str(plan_payload.get("diagnose_note") or "").strip()
        diagnose_brief = _render_diagnose_brief(
            diagnose,
            status=diagnose_status,
            note=diagnose_note,
        )
        docgen_history_brief = str(
            plan_payload.get("docgen_history_brief")
            or planner_context.get("docgen_history_brief")
            or ""
        ).strip()
        try:
            learner_profile_context = load_docgen_learner_profile_context(
                course_id=state["course_id"],
                user_id=state.get("user_id") or None,
            )
        except Exception:
            learner_profile_context = {
                "schema_version": 1,
                "course_id": state["course_id"],
                "user_id": state.get("user_id") or "",
                "has_profile": False,
                "profile_text": "",
                "user_profile_text": "",
                "course_profile_text": "",
                "user_profile": {},
                "course_profile": {},
            }
        learner_profile_text = str(learner_profile_context.get("profile_text") or "").strip()
        if diagnose_brief:
            learner_profile_text = "\n\n".join(
                item for item in [learner_profile_text, diagnose_brief] if item
            )

        has_local_materials = bool(shared_inputs.source_packets)
        plan_course_label = str(plan_contract.course_name or plan_contract.user_prompt or "").strip()
        settings = get_settings()
        retrieval_policy = build_digest_retrieval_policy(
            retrieval_profile,
            has_local_materials=has_local_materials,
            allow_external_search=bool(settings.docgen.allow_external_search),
            digest_mode=digest_mode,
            user_prompt=str(plan_contract.user_prompt or state.get("user_prompt") or ""),
            course_name=plan_course_label,
        )
        document_context = {
            "course_id": state["course_id"],
            "course_name": plan_course_label,
            "digest_mode": digest_mode,
            "retrieval_profile": retrieval_profile,
            "retrieval_policy": retrieval_policy,
            "teaching_action": str(state.get("teaching_action") or "docgen_build"),
            "user_prompt": str(plan_contract.user_prompt or state.get("user_prompt") or ""),
            "plan": str(plan_contract.plan or ""),
            "docgen_history_brief": docgen_history_brief,
            "learner_profile_text": learner_profile_text,
            "learner_profile_context": learner_profile_context,
            "diagnose": diagnose,
            "diagnose_status": diagnose_status,
            "diagnose_note": diagnose_note,
            "diagnose_brief": diagnose_brief,
            "planner_context": planner_context,
            "build_constraints": build_constraints,
            "source_strategy": "local_first" if has_local_materials else "web_first",
            "include_sources": False,
        }
        docgen_context = DocGenContext(
            course_id=state["course_id"],
            course_name=plan_course_label,
            digest_mode=digest_mode,
            retrieval_profile=retrieval_profile,
            user_prompt=str(plan_contract.user_prompt or state.get("user_prompt") or ""),
            plan=str(plan_contract.plan or ""),
            docgen_history_brief=docgen_history_brief,
            learner_profile_text=learner_profile_text,
            learner_profile_context=learner_profile_context,
            planner_context=planner_context,
            diagnose=diagnose,
            diagnose_status=diagnose_status,
            diagnose_note=diagnose_note,
            build_constraints=build_constraints,
            source_strategy="local_first" if has_local_materials else "web_first",
            include_sources=False,
            local_source_count=len(shared_inputs.source_packets),
            section_count=len(shared_inputs.section_packets),
        )

        update_knowledge_build_status(
            state["course_id"],
            requested_at=state["requested_at"],
            status="running",
            stage="planner_confirmed",
            planner_session_id=state.get("planner_session_id") or None,
            confirmed_plan_id=state.get("confirmed_plan_id") or None,
            digest_mode=digest_mode,
            mode_reason=(plan_contract.mode_reason or "confirmed_build_plan"),
            current_stage_description=(
                str(plan_contract.plan or "方案已确认，开始按章节执行。")
                if has_local_materials
                else str(plan_contract.plan or "方案已确认，当前没有本地资料，将优先执行联网研究。")
            ),
            total_chunks=len(assignments),
            processed_chunks=0,
            current_chunk=0,
            plan=str(plan_contract.plan or ""),
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
            state["course_id"],
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
                "retrieval_policy": retrieval_policy,
                "chapter_count": len(assignments),
                "planner_session_id": state.get("planner_session_id", ""),
                "confirmed_plan_id": state.get("confirmed_plan_id", ""),
                "local_source_count": len(shared_inputs.source_packets),
            },
        )
        return {
            "shared_inputs": shared_inputs,
            "raw_chunks": [serialize_section(section) for section in shared_inputs.section_packets],
            "course_profile": shared_inputs.course_profile.model_dump(mode="json"),
            "learner_profile_context": learner_profile_context,
            "learner_profile_text": learner_profile_text,
            "course_name": plan_course_label,
            "chapter_assignments": assignments,
            "confirmed_plan": plan_payload,
            "docgen_context": docgen_context.model_dump(mode="json"),
            "digest_mode": digest_mode,
            "retrieval_profile": retrieval_profile,
            "retrieval_policy": retrieval_policy,
            "teaching_action": str(state.get("teaching_action") or "docgen_build"),
            "document_context": document_context,
            "planner_ms": 0,
        }

    return load_context_node


__all__ = ["build_load_context_node"]
