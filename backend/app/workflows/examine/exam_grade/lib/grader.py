"""Rule-based objective grading and LLM-backed subjective grading."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models import ExamPaperItem
from app.shared.kernel.question_type_runtime import RUBRIC_WEIGHT_SUM_TOLERANCE
from app.shared.kernel.question_types import (
    require_supported_question_type_key,
    question_type_grading_kind,
)
from app.shared.infra.llm_support import run_llm_tasks
from app.workflows.examine.question_types.llm import llm as acompletion_with_fallback
from app.shared.infra.observability.trace import traceable_with_context
from app.workflows.examine.exam_grade.lib.model_policy import (
    ExamGradeModelStep,
    exam_grade_completion_kwargs_with_metadata,
)
from app.workflows.examine.exam_grade.prompts import (
    build_subjective_grade_messages,
)
from app.workflows.examine.question_types.grading import (
    build_custom_rubric_grade_messages,
)

_MULTI_CHOICE_SPLIT_RE = re.compile(r"[\s,，;；/、|]+")


class SubjectiveGradePayload(BaseModel):
    is_correct: bool
    score_obtained: float = Field(ge=0.0, le=1.0)
    feedback_text: str = Field(min_length=8, max_length=1600)
    error_cause_label: str | None = Field(default=None, max_length=80)

    @field_validator("feedback_text")
    @classmethod
    def _strip_feedback_text(cls, value: str) -> str:
        return " ".join(str(value or "").split()).strip()


class CustomEvidencePayload(BaseModel):
    field_key: str = Field(min_length=2, max_length=32)
    quote: str = Field(min_length=1, max_length=2000)


class CustomRubricCriterionPayload(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    score_ratio: float = Field(ge=0.0, le=1.0)
    field_key: str | None = Field(default=None, min_length=2, max_length=32)
    evidence: list[str | CustomEvidencePayload] = Field(default_factory=list, max_length=3)
    note: str = Field(default="", max_length=400)


class CustomRubricGradePayload(BaseModel):
    criteria: list[CustomRubricCriterionPayload] = Field(min_length=1, max_length=12)
    feedback_text: str = Field(min_length=8, max_length=1600)
    error_cause_label: Literal[
        "knowledge_gap",
        "reasoning_gap",
        "example_gap",
        "boundary_gap",
        "expression_issue",
        "unknown",
    ] | None = None

    @field_validator("feedback_text")
    @classmethod
    def _strip_feedback_text(cls, value: str) -> str:
        return " ".join(str(value or "").split()).strip()


@dataclass(frozen=True)
class ExamItemGradeDecision:
    is_correct: bool
    score_obtained: float
    score_max: float
    feedback_text: str
    error_cause_label: str | None
    grading_mode: Literal[
        "objective_rule",
        "subjective_llm",
        "subjective_fallback",
        "custom_rubric_llm",
    ]
    grading_detail: dict[str, object] = field(default_factory=dict)


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").casefold().split()).strip()


def _split_multi_choice_tokens(value: str | None) -> set[str]:
    normalized = _normalize_text(value)
    if not normalized:
        return set()
    return {
        token
        for token in _MULTI_CHOICE_SPLIT_RE.split(normalized)
        if token
    }


def _normalize_true_false_token(value: str | None) -> str:
    normalized = _normalize_text(value)
    if normalized in {"true", "t", "yes", "y", "正确", "对", "是"}:
        return "true"
    if normalized in {"false", "f", "no", "n", "错误", "错", "否"}:
        return "false"
    return normalized


def _build_default_feedback(*, item: ExamPaperItem, is_correct: bool, subjective: bool = False) -> str:
    user_answer = (item.answer_content or "").strip()
    if not user_answer:
        return (
            f"你本题未作答。参考答案是：{item.answer_snapshot}。"
            f"建议先回顾这道题考查的关键点，再结合解析重新整理思路。"
        )
    if is_correct:
        return (
            "本题判定正确。你的作答与标准答案在关键结论上保持一致，"
            "可以继续关注表达的清晰度与步骤的完整性。"
        )
    if subjective:
        return (
            f"本题未判为完全正确。参考答案是：{item.answer_snapshot}。"
            "你的作答与标准结论或关键推理之间仍有差距，建议对照解析补齐核心步骤。"
        )
    return (
        f"本题判定错误。参考答案是：{item.answer_snapshot}。"
        "建议回看题干条件与对应知识点，确认自己为何会选择当前答案。"
    )


def _build_objective_rule_feedback(*, item: ExamPaperItem, is_correct: bool) -> str:
    """Use authored feedback so objective grading never waits for an LLM."""

    explanation = str(item.explanation_snapshot or "").strip()
    if explanation:
        return explanation
    return _build_default_feedback(item=item, is_correct=is_correct)


def _grade_objective_correctness(item: ExamPaperItem) -> bool:
    question_type = require_supported_question_type_key(item.question_type)
    expected = _normalize_text(item.answer_snapshot)
    answer = _normalize_text(item.answer_content)
    if not expected or not answer:
        return False
    if question_type == "multiple_choice":
        return _split_multi_choice_tokens(expected) == _split_multi_choice_tokens(answer)
    if question_type == "true_false":
        return _normalize_true_false_token(expected) == _normalize_true_false_token(answer)
    return answer == expected


@traceable_with_context(
    name="考试：主观题判分",
    run_type="chain",
    metadata_factory=lambda course_name, item: {
        "substep": "exam.grade.subjective_item",
        "question_type": item.question_type,
        "item_order": item.item_order,
        "question_template_id": item.question_template_id,
    },
    tags_factory=lambda course_name, item: [
        "exam-grade",
        "subjective",
        f"question-type:{str(item.question_type or '').strip().lower() or 'unknown'}",
    ],
)
async def _grade_subjective_item(course_name: str, item: ExamPaperItem) -> ExamItemGradeDecision:
    user_answer = _normalize_text(item.answer_content)
    if not user_answer:
        return ExamItemGradeDecision(
            is_correct=False,
            score_obtained=0.0,
            score_max=float(item.score or 1.0),
            feedback_text=_build_default_feedback(item=item, is_correct=False, subjective=True),
            error_cause_label="knowledge_gap",
            grading_mode="subjective_fallback",
            grading_detail={},
        )

    try:
        result = await acompletion_with_fallback(
            build_subjective_grade_messages(
                course_name=course_name,
                question_type=item.question_type,
                stem=item.stem_snapshot,
                correct_answer=item.answer_snapshot,
                reference_explanation=item.explanation_snapshot,
                user_answer=item.answer_content,
            ),
            **exam_grade_completion_kwargs_with_metadata(
                ExamGradeModelStep.SUBJECTIVE_GRADE,
                extra_metadata={
                    "substep": "exam.grade.subjective_judge",
                    "question_type": item.question_type,
                },
            ),
            response_model=SubjectiveGradePayload,
        )
        assert isinstance(result, SubjectiveGradePayload)
        bounded_score = max(0.0, min(float(item.score or 1.0), float(item.score or 1.0) * result.score_obtained))
        return ExamItemGradeDecision(
            is_correct=bool(result.is_correct),
            score_obtained=bounded_score,
            score_max=float(item.score or 1.0),
            feedback_text=result.feedback_text,
            error_cause_label=None if result.is_correct else (result.error_cause_label or "knowledge_gap"),
            grading_mode="subjective_llm",
            grading_detail={},
        )
    except Exception as exc:
        raise RuntimeError(f"subjective grading model failed for item_order={item.item_order}: {exc}") from exc


def _json_object(raw: str) -> dict[str, object]:
    try:
        payload = json.loads(raw or "{}")
    except (TypeError, ValueError) as exc:
        raise RuntimeError("custom question snapshot is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("custom question snapshot must be a JSON object")
    return payload


def _custom_rubric(item: ExamPaperItem) -> tuple[dict[str, object], list[dict[str, object]]]:
    runtime = _json_object(item.runtime_snapshot_json)
    grading_spec = _json_object(item.grading_spec_snapshot_json)
    if runtime.get("grader_key") != "rubric_llm_v1":
        raise RuntimeError("custom question references an unavailable grader")
    rubric = [dict(value) for value in list(grading_spec.get("rubric") or []) if isinstance(value, dict)]
    keys = [str(value.get("key") or "") for value in rubric]
    weights = [float(value.get("weight") or 0.0) for value in rubric]
    if not rubric or any(not key for key in keys) or len(keys) != len(set(keys)):
        raise RuntimeError("custom question rubric is invalid")
    weight_total = sum(weights)
    if (
        any(not math.isfinite(weight) or not 0.0 < weight <= 1.0 for weight in weights)
        or abs(weight_total - 1.0) > RUBRIC_WEIGHT_SUM_TOLERANCE
    ):
        raise RuntimeError("custom question rubric weights must total 1")
    # Import accepts rounded weights within this same tolerance. Normalize the
    # scoring view so a perfect answer earns full marks; leave snapshots intact.
    rubric = [
        {**criterion, "weight": weight / weight_total}
        for criterion, weight in zip(rubric, weights, strict=True)
    ]
    pass_score = float(grading_spec.get("pass_score") or 0.0)
    if not 0.0 <= pass_score <= 1.0:
        raise RuntimeError("custom question pass score is invalid")
    return grading_spec, rubric


def _validate_custom_grade_payload(
    result: CustomRubricGradePayload,
    *,
    rubric: list[dict[str, object]],
    original_answer_by_field: dict[str, str],
    require_field_key: bool,
) -> list[dict[str, object]]:
    expected_keys = [str(value.get("key") or "") for value in rubric]
    actual_keys = [value.key for value in result.criteria]
    if actual_keys != expected_keys:
        raise RuntimeError("custom grader returned criteria outside the frozen rubric")
    details: list[dict[str, object]] = []
    for definition, criterion in zip(rubric, result.criteria, strict=True):
        spans = [
            {"field_key": value.field_key if isinstance(value, CustomEvidencePayload) else criterion.field_key,
             "quote": value.quote.strip() if isinstance(value, CustomEvidencePayload) else value.strip()}
            for value in criterion.evidence
        ]
        spans = [span for span in spans if span["quote"]]
        evidence = [span["quote"] for span in spans]
        if criterion.score_ratio > 0.0 and not evidence:
            raise RuntimeError(f"custom grader returned a positive score without evidence for {criterion.key}")
        field_key = str(criterion.field_key or "").strip() or None
        for span in spans:
            span_key = span["field_key"]
            if require_field_key and span_key is None:
                raise RuntimeError(f"custom grader must locate evidence to an answer field for {criterion.key}")
            if span_key is not None and span_key not in original_answer_by_field:
                raise RuntimeError(f"custom grader returned an unknown answer field for {criterion.key}")
            evidence_source = original_answer_by_field[span_key] if span_key else "\n".join(original_answer_by_field.values())
            if span["quote"] not in evidence_source:
                raise RuntimeError(f"custom grader returned evidence not found in the learner answer for {criterion.key}")
        details.append(
            {
                "key": criterion.key,
                "label": str(definition.get("label") or criterion.key),
                "weight": float(definition.get("weight") or 0.0),
                "score_ratio": float(criterion.score_ratio),
                "field_key": field_key,
                "evidence": evidence,
                "evidence_spans": spans,
                "note": criterion.note,
            }
        )
    return details


@traceable_with_context(
    name="考试：自定义题型判分",
    run_type="chain",
    metadata_factory=lambda course_name, item: {
        "substep": "exam.grade.custom_rubric_item",
        "question_type": item.question_type,
        "item_order": item.item_order,
        "question_type_version_id": item.question_type_version_id,
    },
    tags_factory=lambda course_name, item: ["exam-grade", "custom-rubric"],
)
async def _grade_custom_rubric_item(
    course_name: str,
    item: ExamPaperItem,
) -> ExamItemGradeDecision:
    grading_spec, rubric = _custom_rubric(item)
    answer_payload = {
        str(key): str(value)
        for key, value in _json_object(item.answer_payload_json).items()
        if isinstance(value, str)
    }
    answer_schema = _json_object(item.answer_schema_snapshot_json)
    answer_fields = [
        dict(value)
        for value in list(answer_schema.get("fields") or [])
        if isinstance(value, dict) and str(value.get("key") or "").strip()
    ]
    answer_field_keys = [str(value["key"]) for value in answer_fields]
    answer_payload = {
        key: answer_payload.get(key, "")
        for key in answer_field_keys
    } if answer_field_keys else answer_payload
    original_answer = "\n".join(answer_payload.values())
    score_max = float(item.score or 1.0)
    pass_score = float(grading_spec.get("pass_score") or 0.0)
    if not original_answer.strip():
        criteria = [
            {
                "key": str(value.get("key") or ""),
                "label": str(value.get("label") or value.get("key") or ""),
                "weight": float(value.get("weight") or 0.0),
                "score_ratio": 0.0,
                "evidence": [],
                "note": "未作答",
            }
            for value in rubric
        ]
        return ExamItemGradeDecision(
            is_correct=False,
            score_obtained=0.0,
            score_max=score_max,
            feedback_text="本题未作答，暂时无法展示你对该知识点的理解。请按题目要求完整说明后再提交。",
            error_cause_label="knowledge_gap",
            grading_mode="custom_rubric_llm",
            grading_detail={"score_ratio": 0.0, "pass_score": pass_score, "criteria": criteria},
        )

    messages = build_custom_rubric_grade_messages(
        course_name=course_name,
        stem=item.stem_snapshot,
        answer_payload=answer_payload,
        reference_answer=_json_object(item.reference_answer_snapshot_json),
        reference_explanation=item.explanation_snapshot,
        grading_spec=grading_spec,
        answer_schema=answer_schema,
        difficulty=item.difficulty,
    )
    last_error: Exception | None = None
    for _attempt in range(2):
        validating_result = False
        try:
            result = await acompletion_with_fallback(
                messages,
                **exam_grade_completion_kwargs_with_metadata(
                    ExamGradeModelStep.SUBJECTIVE_GRADE,
                    extra_metadata={
                        "substep": "exam.grade.custom_rubric_judge",
                        "question_type": item.question_type,
                        "question_type_version_id": item.question_type_version_id,
                    },
                ),
                response_model=CustomRubricGradePayload,
            )
            assert isinstance(result, CustomRubricGradePayload)
            validating_result = True
            criteria = _validate_custom_grade_payload(
                result,
                rubric=rubric,
                original_answer_by_field=answer_payload,
                require_field_key=len(answer_field_keys) > 1,
            )
            labels = {str(field["key"]): str(field.get("label") or field["key"]) for field in answer_fields}
            for criterion in criteria:
                for span in criterion.get("evidence_spans", []):
                    span["field_label"] = labels.get(span["field_key"], "")
            # Use the frozen decimal weights, before their float normalization
            # for display. Compare weighted totals before division so reaching
            # the pass line does not depend on binary rounding or a tolerance.
            with localcontext() as scoring_context:
                scoring_context.prec = 50
                scoring_weights = {
                    str(value["key"]): Decimal(str(value["weight"]))
                    for value in grading_spec["rubric"]
                    if isinstance(value, dict)
                }
                weight_total = sum(scoring_weights.values(), Decimal(0))
                weighted_total = sum(
                    (
                        scoring_weights[str(value["key"])] * Decimal(str(value["score_ratio"]))
                        for value in criteria
                    ),
                    Decimal(0),
                )
                passed = weighted_total >= Decimal(str(pass_score)) * weight_total
                decimal_ratio = weighted_total / weight_total
                score_ratio = float(decimal_ratio)
                score_obtained = float(Decimal(str(score_max)) * decimal_ratio)
            return ExamItemGradeDecision(
                is_correct=passed,
                score_obtained=score_obtained,
                score_max=score_max,
                feedback_text=result.feedback_text,
                error_cause_label=None if passed else (result.error_cause_label or "knowledge_gap"),
                grading_mode="custom_rubric_llm",
                grading_detail={
                    "score_ratio": score_ratio,
                    "pass_score": pass_score,
                    "criteria": criteria,
                },
            )
        except Exception as exc:  # noqa: BLE001 - retry invalid model evidence once
            last_error = exc
            if validating_result:
                # Only include our own validator's bounded diagnostic. Provider
                # errors can contain credentials and never enter a retry prompt.
                messages = [*messages, {
                    "role": "user",
                    "content": (
                        "The server rejected the previous grade: " + str(exc)[:240]
                        + ". Re-evaluate all rubric criteria. Copy short contiguous evidence "
                        "verbatim from the specified learner_answer field, preserving exact "
                        "characters and punctuation. Do not join separate passages or quote "
                        "the reference answer. Return the complete structured grade."
                    ),
                }]
    raise RuntimeError(
        f"custom rubric grading failed for item_order={item.item_order}: {last_error}"
    ) from last_error


@traceable_with_context(
    name="考试：整卷判题",
    run_type="chain",
    metadata_factory=lambda *, course_name, items: {
        "substep": "exam.grade.paper",
        "course_name": course_name,
        "item_count": len(items),
    },
    tags_factory=lambda *, course_name, items: [
        "exam-grade",
        "paper-grading",
    ],
)
async def grade_exam_items_with_workflow(
    *,
    course_name: str,
    items: list[ExamPaperItem],
) -> list[ExamItemGradeDecision]:
    decisions: list[ExamItemGradeDecision | None] = [None] * len(items)
    subjective_items: list[tuple[int, ExamPaperItem]] = []
    custom_items: list[tuple[int, ExamPaperItem]] = []

    for index, item in enumerate(items):
        if item.question_type_version_id is not None:
            custom_items.append((index, item))
            continue
        grading_kind = question_type_grading_kind(item.question_type)
        if grading_kind == "objective":
            is_correct = _grade_objective_correctness(item)
            decisions[index] = ExamItemGradeDecision(
                is_correct=is_correct,
                score_obtained=float(item.score or 1.0) if is_correct else 0.0,
                score_max=float(item.score or 1.0),
                feedback_text=_build_objective_rule_feedback(item=item, is_correct=is_correct),
                error_cause_label=None if is_correct else "knowledge_gap",
                grading_mode="objective_rule",
                grading_detail={},
            )
            continue

        if grading_kind != "subjective":  # pragma: no cover - exhaustive guard
            raise AssertionError(f"Unhandled grading kind: {grading_kind}")
        subjective_items.append((index, item))

    if subjective_items:
        subjective_decisions = await run_llm_tasks(
            subjective_items,
            lambda payload: _grade_subjective_item(course_name, payload[1]),
        )
        for (index, _item), decision in zip(subjective_items, subjective_decisions, strict=True):
            decisions[index] = decision

    if custom_items:
        custom_decisions = await run_llm_tasks(
            custom_items,
            lambda payload: _grade_custom_rubric_item(course_name, payload[1]),
        )
        for (index, _item), decision in zip(custom_items, custom_decisions, strict=True):
            decisions[index] = decision

    if any(decision is None for decision in decisions):  # pragma: no cover - defensive guard
        raise AssertionError("Exam grading did not produce a decision for every item")
    return [decision for decision in decisions if decision is not None]


__all__ = [
    "ExamItemGradeDecision",
    "CustomRubricCriterionPayload",
    "CustomRubricGradePayload",
    "SubjectiveGradePayload",
    "grade_exam_items_with_workflow",
]
