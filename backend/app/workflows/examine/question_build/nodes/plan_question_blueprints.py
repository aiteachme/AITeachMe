"""Plan question blueprints before concrete generation."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.workflow import emit_progress
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.examine.question_build.lib.generator import (
    ExamQuestionGenerationSpec,
    plan_exam_question_blueprints,
)
from app.workflows.examine.question_build.state import QuestionBuildState


def build_plan_question_blueprints_node(*, context: WorkflowContext):
    del context

    async def plan_question_blueprints_node(state: QuestionBuildState) -> dict:
        started_at = perf_counter()
        await emit_progress(
            state,
            stage="plan_exam_questions",
            detail="正在根据学科目标、知识单元和掌握情况编排题目蓝图...",
            step="plan_question_blueprints",
        )
        try:
            explicit_specs = list(state.get("specs") or [])
            if explicit_specs:
                blueprints = [
                    spec if isinstance(spec, ExamQuestionGenerationSpec) else ExamQuestionGenerationSpec.model_validate(spec)
                    for spec in explicit_specs
                ]
                blueprint_payload = [
                    {
                        "item_order": spec.item_order,
                        "knowledge_unit_ids": spec.knowledge_unit_ids,
                        "question_type": spec.question_type,
                        "difficulty": spec.difficulty,
                        "rationale": "Provided by caller.",
                    }
                    for spec in blueprints
                ]
            else:
                planned = await plan_exam_question_blueprints(
                    subject=str(state.get("subject") or ""),
                    subject_name=str(state.get("subject_name") or ""),
                    subject_description=str(state.get("subject_description") or ""),
                    subject_user_intent=str(state.get("subject_user_intent") or ""),
                    subject_context=str(state.get("subject_context") or ""),
                    exam_mode=str(state.get("exam_mode") or "web_practice"),
                    units=list(state.get("units") or []),
                    question_count=int(state.get("question_count") or 1),
                    requested_difficulty=str(state.get("requested_difficulty") or "medium"),
                    mastery_by_unit_id=dict(state.get("mastery_by_unit_id") or {}),
                    focus_prompt=str(state.get("focus_prompt") or ""),
                    user_prompt=str(state.get("user_prompt") or ""),
                    style_prompt=str(state.get("style_prompt") or ""),
                )
                blueprint_payload = [item.model_dump(mode="json") for item in planned]

            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="plan_exam_questions",
                detail=f"已编排 {len(blueprint_payload)} 道题的题型与知识点组合。",
                step="plan_question_blueprints",
                elapsed_ms=elapsed_ms,
            )
            return {"question_blueprints": blueprint_payload, "plan_ms": elapsed_ms, "error": ""}
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
