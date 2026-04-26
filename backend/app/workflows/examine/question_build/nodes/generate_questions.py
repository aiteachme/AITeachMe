"""Generate exam questions and emit compact progress events."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.workflow import emit_progress
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.examine.question_build.lib.generator import (
    ExamQuestionBlueprint,
    ExamQuestionGenerationFailure,
    generate_exam_questions_for_units,
)
from app.workflows.examine.question_build.state import QuestionBuildState


def build_generate_questions_node(*, context: WorkflowContext):
    del context

    async def generate_questions_node(state: QuestionBuildState) -> dict:
        if state.get("error"):
            return {}

        started_at = perf_counter()
        await emit_progress(
            state,
            stage="generate_exam_questions",
            detail="正在基于知识点生成高质量考题...",
            step="generate_questions",
        )
        try:
            blueprints = [
                ExamQuestionBlueprint.model_validate(item)
                for item in list(state.get("question_blueprints") or [])
            ]
            if not blueprints:
                raise ValueError("question blueprint planning returned no items")
            specs = [blueprint.to_generation_spec() for blueprint in blueprints]

            generated_count = 0
            failed_count = 0
            failed_questions: list[dict] = []

            async def handle_question_generated(question) -> None:
                nonlocal generated_count
                generated_count += 1
                await emit_progress(
                    state,
                    stage="generate_exam_questions",
                    detail=f"已生成第 {question.item_order} 题。",
                    step="generate_question",
                    extra={
                        "generated_question": question.model_dump(mode="json"),
                        "generated_question_count": generated_count,
                        "question_count": len(specs),
                    },
                )

            async def handle_question_failed(failure: ExamQuestionGenerationFailure) -> None:
                nonlocal failed_count
                failed_count += 1
                failed_payload = failure.model_dump(mode="json")
                failed_questions.append(failed_payload)
                await emit_progress(
                    state,
                    stage="generate_exam_questions",
                    detail=f"第 {failure.item_order} 题生成失败，已跳过。",
                    step="generate_question_failed",
                    extra={
                        "failed_question": failed_payload,
                        "failed_question_count": failed_count,
                        "question_count": len(specs),
                    },
                )

            questions = await generate_exam_questions_for_units(
                units=list(state.get("units") or []),
                specs=specs,
                on_question_generated=handle_question_generated,
                on_question_failed=handle_question_failed,
                allow_partial=True,
            )
        except Exception as exc:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            await emit_progress(
                state,
                stage="generate_exam_questions",
                detail="考题生成失败，请稍后重试。",
                step="generate_questions",
                elapsed_ms=elapsed_ms,
            )
            return {
                "generated_questions": [],
                "failed_questions": [],
                "generate_ms": elapsed_ms,
                "error": str(exc),
            }

        elapsed_ms = int((perf_counter() - started_at) * 1000)
        await emit_progress(
            state,
            stage="generate_exam_questions",
            detail=f"已生成 {len(questions)} 道考题，跳过 {len(failed_questions)} 道失败题。",
            step="generate_questions",
            elapsed_ms=elapsed_ms,
        )
        return {
            "generated_questions": [item.model_dump(mode="json") for item in questions],
            "generate_ms": elapsed_ms,
            "failed_questions": failed_questions,
            "failed_question_count": len(failed_questions),
            "error": "",
        }

    return generate_questions_node


__all__ = ["build_generate_questions_node"]
