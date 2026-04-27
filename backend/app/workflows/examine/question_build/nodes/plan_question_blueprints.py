"""Plan question blueprints before concrete generation."""

from __future__ import annotations

import asyncio
from time import perf_counter

from app.shared.infra.workflow import emit_progress
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.examine.question_build.lib.generator import (
    plan_exam_question_blueprints,
)
from app.workflows.examine.question_build.state import QuestionBuildState


def build_plan_question_blueprints_node(*, context: WorkflowContext):
    del context

    async def plan_question_blueprints_node(state: QuestionBuildState) -> dict:
        if state.get("error"):
            return {}

        started_at = perf_counter()
        await emit_progress(
            state,
            stage="plan_exam_questions",
            detail="正在根据学科目标、知识单元和掌握情况编排题目蓝图...",
            step="plan_question_blueprints",
        )
        try:
            planned = await plan_exam_question_blueprints(
                subject_name=str(state.get("subject_name") or ""),
                subject_description=str(state.get("subject_description") or ""),
                subject_user_intent=str(state.get("subject_user_intent") or ""),
                exam_mode=str(state.get("exam_mode") or "web_practice"),
                units=list(state.get("units") or []),
                question_count=int(state.get("question_count") or 1),
                mastery_by_unit_id=dict(state.get("mastery_by_unit_id") or {}),
                user_prompt=str(state.get("user_prompt") or ""),
                system_constraints=str(state.get("system_constraints") or ""),
            )
            blueprint_payload = [item.model_dump(mode="json") for item in planned]

            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="plan_exam_questions",
                detail=f"已编排 {len(blueprint_payload)} 道题的题型与知识点组合。",
                step="plan_question_blueprints",
                elapsed_ms=elapsed_ms,
                extra={"question_blueprints": blueprint_payload},
            )
            return {"question_blueprints": blueprint_payload, "plan_ms": elapsed_ms, "error": ""}
        except asyncio.CancelledError:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="plan_exam_questions",
                detail="题目蓝图编排被取消，试卷生成失败。",
                step="plan_question_blueprints",
                elapsed_ms=elapsed_ms,
            )
            return {
                "question_blueprints": [],
                "plan_ms": elapsed_ms,
                "error": "Question blueprint planning was cancelled.",
            }
        except Exception as exc:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="plan_exam_questions",
                detail="题目蓝图编排失败，请稍后重试。",
                step="plan_question_blueprints",
                elapsed_ms=elapsed_ms,
            )
            return {"question_blueprints": [], "plan_ms": elapsed_ms, "error": str(exc)}

    return plan_question_blueprints_node


__all__ = ["build_plan_question_blueprints_node"]
