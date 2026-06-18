"""Normalize and persist the editable planner draft."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import structlog

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.planner_events import emit_planner_event
from app.workflows.digest.planner.lib.plans import (
    compose_effective_planner_request_text,
    normalize_planner_diagnosis_draft,
    normalize_planner_draft,
)
from app.workflows.digest.planner.lib.requested_structure import extract_explicit_learning_topic
from app.workflows.digest.planner.lib.store import save_planner_result
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _diagnose_answer_map(raw_answers: Any) -> dict[str, str]:
    if not isinstance(raw_answers, list):
        return {}
    answers: dict[str, str] = {}
    for raw in raw_answers:
        if not isinstance(raw, Mapping):
            continue
        question = _clean_text(raw.get("question"))
        answer = _clean_text(raw.get("answer"))
        if question and answer:
            answers[question.casefold()] = answer
    return answers


def _merge_diagnose_resolution(plan: dict[str, Any], state: BuildPlannerState) -> dict[str, Any]:
    answers = _diagnose_answer_map(state.get("diagnose_answers"))
    status = _clean_text(state.get("diagnose_status"))
    note = _clean_text(state.get("diagnose_note"))
    if not answers and not status and not note:
        return plan

    next_plan = dict(plan)
    latest_plan = state.get("latest_plan") if isinstance(state.get("latest_plan"), Mapping) else {}
    latest_diagnose = list(latest_plan.get("diagnose") or []) if latest_plan else []
    diagnose_source = (
        latest_diagnose
        if (answers or status == "skipped") and latest_diagnose
        else list(next_plan.get("diagnose") or [])
    )
    diagnose: list[dict[str, Any]] = []
    for raw in diagnose_source:
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        question = _clean_text(item.get("question"))
        answer = answers.get(question.casefold()) if question else None
        if answer:
            item["answer"] = answer
        diagnose.append(item)
    if diagnose:
        next_plan["diagnose"] = diagnose

    if status in {"answered", "skipped"}:
        next_plan["diagnose_status"] = status
    elif answers:
        next_plan["diagnose_status"] = "answered"
    if note:
        next_plan["diagnose_note"] = note
    return next_plan


def build_save_planner_draft_node(*, context: WorkflowContext):
    """构建方案草案保存节点。

    把模型输出的 build_plan_draft 规范化成稳定合同，并写入 planner
    session / chat mirror。这里保存的是 latest_plan，用户确认后才会冻结为
    confirmed plan。
    """

    async def save_planner_draft_node(state: BuildPlannerState) -> dict:
        """保存当前方案草案并返回 API 响应所需状态。"""

        if state.get("error"):
            return {}

        logger.info(
            "planner_normalize_started",
            planner_session_id=state.get("planner_session_id", ""),
            course_id=state.get("course_id", ""),
            has_build_plan_draft=bool(state.get("build_plan_draft")),
            state_error=state.get("error"),
        )
        material_context = state["material_context"]
        digest_mode = state.get("digest_mode") or material_context.course_mode_decision.mode.value
        raw_draft = dict(state.get("build_plan_draft") or {})
        request_prompt = compose_effective_planner_request_text(
            state.get("user_prompt") or raw_draft.get("user_prompt") or "",
            state.get("feedback_message") or "",
        )
        is_diagnosis_draft = str(raw_draft.get("planner_stage") or "").strip() == "diagnosis"
        # 上一个节点已经完成“生成”；这里把极简 JSON 合同补齐成 API/DocGen 稳定结构并落库。
        explicit_topic = extract_explicit_learning_topic(request_prompt)
        generated_course_name = str(state.get("generated_course_name") or "").strip()
        generated_course_icon = str(state.get("generated_course_icon_key") or "").strip()
        effective_course_name = explicit_topic or generated_course_name
        if is_diagnosis_draft:
            plan = normalize_planner_diagnosis_draft(
                raw_draft,
                course_id=state["course_id"],
                user_prompt=request_prompt,
                requested_digest_mode=digest_mode,
                shared_inputs=material_context,
                latest_plan=state.get("latest_plan"),
            )
            if effective_course_name:
                plan["course_name"] = effective_course_name
            if generated_course_icon:
                plan["course_icon"] = generated_course_icon
            logger.info(
                "planner_diagnosis_normalize_completed",
                planner_session_id=state.get("planner_session_id", ""),
                diagnose_count=len(plan.get("diagnose") or []),
                generated_course_name=effective_course_name or None,
                generated_course_icon_key=generated_course_icon or None,
            )
            await emit_planner_event(
                state,
                event="planner.saved",
                detail="前置诊断已生成，选择后继续生成正式方案。",
                payload={
                    "diagnose_count": len(plan.get("diagnose") or []),
                    "digest_mode": str(plan.get("digest_mode") or digest_mode),
                    "plan": "",
                    "outline_items": [],
                },
            )
            result = {
                "plan": plan,
                "digest_mode": str(plan.get("digest_mode") or digest_mode),
                "generated_course_name": effective_course_name,
            }
            persist_update = save_planner_result(
                {**state, **result},
                plan=plan,
                material_context=material_context,
            )
            logger.info(
                "planner_diagnosis_persist_completed",
                planner_session_id=state.get("planner_session_id", ""),
                persisted=bool(persist_update),
                planner_turn_count=len(persist_update.get("planner_turns", []) or []),
            )
            return {**result, **persist_update}

        draft = normalize_planner_draft(
            raw_draft,
            course_id=state["course_id"],
            user_prompt=request_prompt,
            requested_digest_mode=digest_mode,
            shared_inputs=material_context,
            latest_plan=state.get("latest_plan"),
        )
        if effective_course_name:
            draft.course_name = effective_course_name
        if generated_course_icon:
            draft.course_icon = generated_course_icon
        logger.info(
            "planner_normalize_completed",
            planner_session_id=state.get("planner_session_id", ""),
            chapter_count=len(draft.chapters),
            digest_mode=draft.digest_mode,
            plan_chars=len(draft.plan or ""),
            suggestion_chars=len(draft.suggestion or ""),
            generated_course_name=effective_course_name or None,
            generated_course_icon_key=generated_course_icon or None,
        )
        plan = _merge_diagnose_resolution(draft.model_dump(mode="json"), state)
        outline_items = [
            {
                "title": chapter.title,
                "objective": chapter.objective,
            }
            for chapter in draft.chapters
        ]
        await emit_planner_event(
            state,
            event="planner.saved",
            detail="已提炼出计划大纲，可以确认或继续修改。",
            payload={
                "chapter_count": len(draft.chapters),
                "digest_mode": draft.digest_mode,
                "plan": draft.plan,
                "outline_items": outline_items,
            },
        )
        result = {
            "plan": plan,
            "digest_mode": str(plan.get("digest_mode") or draft.digest_mode),
            "generated_course_name": effective_course_name,
        }
        persist_update = save_planner_result(
            {**state, **result},
            plan=plan,
            material_context=material_context,
        )
        logger.info(
            "planner_persist_completed",
            planner_session_id=state.get("planner_session_id", ""),
            persisted=bool(persist_update),
            planner_turn_count=len(persist_update.get("planner_turns", []) or []),
        )
        return {**result, **persist_update}

    return save_planner_draft_node


__all__ = ["build_save_planner_draft_node"]
