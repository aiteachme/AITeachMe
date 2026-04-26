"""Exams API endpoints."""

from __future__ import annotations

import hashlib
import json
import re
import uuid

import structlog
from fastapi import APIRouter, BackgroundTasks, Body, Depends, Path, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlmodel import Session, select

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.models import ExamPaper, ExamPaperItem, QuestionTemplate, QuestionTypeRegistry, exam_mode_value
from app.models.knowledge_unit import KnowledgeUnit
from app.models.subject import Subject
from app.repositories import exams_repo, knowledge_relation_repo
from app.repositories import profile_repo
from app.schemas.common import ApiResponse, PageParams, PaginatedData, build_paginated_data, ok_response
from app.schemas.exams import (
    ExamGenerateRequest,
    ExamGenerateResponse,
    ExamGradeResponse,
    ExamHistoryItem,
    ExamPaperDeleteResponse,
    ExamPaperDetailResponse,
    ExamPaperItemResponse,
    QuestionTemplateItemResponse,
    QuestionTypeRegistryItemResponse,
    PaperPreview,
    ExamStudyGuideFocusUnit,
    ExamStudyGuideResponse,
    ExamSubmitRequest,
)
from app.shared.infra.exceptions import AITeachMeError
from app.shared.infra.database import managed_session
from app.shared.infra.workflow.live_stream import (
    format_sse_event,
    publish_workflow_stream_event,
    subscribe_workflow_stream,
)
from app.utils.time import utcnow
from app.workflows.examine import (
    run_exam_grade_workflow,
    run_exam_study_guide_workflow,
    run_question_build_workflow,
)
from app.workflows.profile import schedule_reviews, update_mastery_from_exam
from app.workflows.support.subjects.learning_context import load_subject_llm_context

router = APIRouter(prefix="/api/v1/subjects/{subject}/exams", tags=["exams"])
logger = structlog.get_logger(__name__)

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")
PAPER_PREVIEW_ROW_LIMIT = 7
RECENT_EXAM_STEM_AVOID_LIMIT = 18


def _exam_stream_channel(subject: str, paper_id: int) -> str:
    return f"exam:{subject}:{paper_id}"


def _publish_exam_event(subject: str, paper_id: int, event: str, data: dict[str, object]) -> None:
    publish_workflow_stream_event(_exam_stream_channel(subject, paper_id), event, data)


def _ensure_subject(session: Session, subject: str, user_id: str) -> Subject:
    record = session.exec(select(Subject).where(Subject.slug == subject, Subject.user_id == user_id)).first()
    if record is None:
        _raise_not_found(f"Subject `{subject}` not found.", error_code="SUBJECT_NOT_FOUND")
    return record


def _json_list(raw: str | None) -> list[dict[str, object]]:
    try:
        payload = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _json_dict(raw: str | None) -> dict[str, object]:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _hash_stem(stem: str) -> str:
    return hashlib.sha1(stem.encode("utf-8")).hexdigest()


def _raise_not_found(detail: str, error_code: str = "EXAM_NOT_FOUND") -> None:
    raise AITeachMeError(detail=detail, error_code=error_code, status_code=404)


def _clean_exam_text(value: str | None) -> str:
    text = str(value or "")
    text = _HTML_COMMENT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def _build_exam_diversity_prompt(*, run_id: str, recent_stems: list[str]) -> str:
    lines = [
        "Generation diversity constraints:",
        f"- This exam generation run id is `{run_id}`. Use it only to vary scenarios, numbers, wording, examples, and distractors.",
        "- Do not reuse exact or near-duplicate stems, options, answers, or worked examples from recent exams.",
        "- Prefer fresh surface contexts while preserving the requested knowledge units, difficulty, and question types.",
    ]
    if recent_stems:
        lines.append("- Recent stems to avoid:")
        lines.extend(f"  {index}. {stem}" for index, stem in enumerate(recent_stems, start=1))
    return "\n".join(lines)


def _build_exam_title(paper: ExamPaper) -> str:
    return f"{paper.exam_mode} · {paper.created_at.strftime('%m/%d %H:%M')}"


def _preview_density(difficulty: str | None) -> int:
    normalized = str(difficulty or "").lower()
    if normalized == "easy":
        return 1
    if normalized == "hard":
        return 3
    return 2


def _preview_result_status(is_correct: bool | None) -> str:
    if is_correct is True:
        return "correct"
    if is_correct is False:
        return "incorrect"
    return "ungraded"


def _preview_shape(question_type: str | None) -> str:
    normalized = str(question_type or "").lower()
    if "choice" in normalized or normalized in {"single", "multiple"}:
        return "choice"
    if "blank" in normalized or "fill" in normalized:
        return "blank"
    if "judge" in normalized or "true_false" in normalized or "boolean" in normalized:
        return "judge"
    if "chart" in normalized or "graph" in normalized:
        return "chart"
    if "formula" in normalized or "calc" in normalized or "math" in normalized:
        return "formula"
    if "code" in normalized or "program" in normalized:
        return "code"
    if "short" in normalized or "essay" in normalized or "answer" in normalized:
        return "short"
    return "text"


def _dedupe_preview_keywords(values: list[str]) -> list[str]:
    seen: set[str] = set()
    keywords: list[str] = []
    for value in values:
        cleaned = _clean_exam_text(value)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        keywords.append(cleaned[:18])
        if len(keywords) >= 3:
            break
    return keywords


def _build_paper_preview(
    items: list[ExamPaperItem],
    *,
    knowledge_unit_by_id: dict[int, KnowledgeUnit],
    links_by_item_id: dict[int, list[dict[str, object]]],
) -> PaperPreview:
    ordered_items = sorted(items, key=lambda item: item.item_order)
    keyword_candidates: list[str] = []
    for item in ordered_items:
        for ref in links_by_item_id.get(int(item.id or 0), []):
            knowledge_unit_id = int(ref.get("knowledge_unit_id", 0) or 0)
            unit = knowledge_unit_by_id.get(knowledge_unit_id)
            if unit is not None:
                keyword_candidates.append(unit.canonical_name)

    return PaperPreview(
        keywords=_dedupe_preview_keywords(keyword_candidates),
        question_types=_dedupe_preview_keywords([item.question_type for item in ordered_items]),
        rows=[
            {
                "order": item.item_order,
                "type": item.question_type,
                "shape": _preview_shape(item.question_type),
                "difficulty": item.difficulty,
                "density": _preview_density(item.difficulty),
                "result_status": _preview_result_status(item.is_correct),
            }
            for item in ordered_items[:PAPER_PREVIEW_ROW_LIMIT]
        ],
        overflow_count=max(0, len(ordered_items) - PAPER_PREVIEW_ROW_LIMIT),
    )


def _build_placeholder_paper_preview(*, question_count: int) -> PaperPreview:
    count = max(1, int(question_count or 1))
    return PaperPreview(
        rows=[
            {
                "order": order,
                "type": "pending",
                "shape": "text",
                "difficulty": "medium",
                "density": 2,
                "result_status": "ungraded",
            }
            for order in range(1, min(count, PAPER_PREVIEW_ROW_LIMIT) + 1)
        ],
        overflow_count=max(0, count - PAPER_PREVIEW_ROW_LIMIT),
    )


def _build_blueprint_paper_preview(
    blueprints: list[dict[str, object]],
    *,
    question_count: int,
    unit_name_by_id: dict[int, str],
) -> PaperPreview:
    def blueprint_order(item: dict[str, object]) -> int:
        try:
            return int(item.get("item_order", 0) or 0)
        except (TypeError, ValueError):
            return 0

    ordered_blueprints = sorted(
        [item for item in blueprints if isinstance(item, dict)],
        key=blueprint_order,
    )
    rows: list[dict[str, object]] = []
    keyword_candidates: list[str] = []
    question_types: list[str] = []
    blueprint_by_order: dict[int, dict[str, object]] = {}
    for blueprint in ordered_blueprints:
        try:
            order = int(blueprint.get("item_order", 0) or 0)
        except (TypeError, ValueError):
            continue
        if order <= 0:
            continue
        blueprint_by_order[order] = blueprint
        question_type = str(blueprint.get("question_type") or "").strip()
        if question_type:
            question_types.append(question_type)
        for unit_id in list(blueprint.get("knowledge_unit_ids") or []):
            try:
                name = unit_name_by_id.get(int(unit_id))
            except (TypeError, ValueError):
                name = None
            if name:
                keyword_candidates.append(name)

    count = max(1, int(question_count or len(blueprint_by_order) or 1))
    for order in range(1, min(count, PAPER_PREVIEW_ROW_LIMIT) + 1):
        blueprint = blueprint_by_order.get(order, {})
        question_type = str(blueprint.get("question_type") or "pending")
        difficulty = str(blueprint.get("difficulty") or "medium")
        rows.append(
            {
                "order": order,
                "type": question_type,
                "shape": _preview_shape(question_type),
                "difficulty": difficulty,
                "density": _preview_density(difficulty),
                "result_status": "ungraded",
            }
        )

    return PaperPreview(
        keywords=_dedupe_preview_keywords(keyword_candidates),
        question_types=_dedupe_preview_keywords(question_types),
        rows=rows,
        overflow_count=max(0, count - PAPER_PREVIEW_ROW_LIMIT),
    )


def _paper_preview_from_json(raw: str | None) -> PaperPreview:
    payload = _json_dict(raw)
    if not payload:
        return PaperPreview()
    try:
        return PaperPreview.model_validate(payload)
    except Exception:
        return PaperPreview()


def _paper_preview_for_response(
    paper: ExamPaper,
    items: list[ExamPaperItem],
    *,
    knowledge_unit_by_id: dict[int, KnowledgeUnit],
    links_by_item_id: dict[int, list[dict[str, object]]],
) -> PaperPreview:
    saved_preview = _paper_preview_from_json(getattr(paper, "paper_preview_json", "{}"))
    expected_row_count = min(len(items), PAPER_PREVIEW_ROW_LIMIT)
    saved_preview_is_complete = not items or len(saved_preview.rows) >= expected_row_count
    graded_orders = {item.item_order for item in items if item.is_correct is not None}
    saved_result_by_order = {row.order: row.result_status for row in saved_preview.rows}
    saved_preview_has_current_results = not graded_orders or all(
        saved_result_by_order.get(order) in {"correct", "incorrect"}
        for order in graded_orders
        if order <= PAPER_PREVIEW_ROW_LIMIT
    )
    if (
        (saved_preview.rows or saved_preview.keywords or saved_preview.question_types)
        and saved_preview_is_complete
        and saved_preview_has_current_results
    ):
        return saved_preview
    if not items:
        return saved_preview
    return _build_paper_preview(
        items,
        knowledge_unit_by_id=knowledge_unit_by_id,
        links_by_item_id=links_by_item_id,
    )


def _paper_generation_event_payload(
    paper: ExamPaper,
    *,
    preview: PaperPreview | None = None,
    stage: str | None = None,
    error_message: str | None = None,
) -> dict[str, object]:
    context = _json_dict(paper.selection_context_json)
    effective_preview = preview or _paper_preview_from_json(getattr(paper, "paper_preview_json", "{}"))
    payload: dict[str, object] = {
        "exam_paper_id": int(paper.id or 0),
        "status": paper.status,
        "num_questions": paper.total_items,
        "paper_preview": effective_preview.model_dump(mode="json"),
        "error_message": error_message if error_message is not None else context.get("error_message"),
        "updated_at": paper.updated_at,
    }
    if stage:
        payload["stage"] = stage
    return payload


def _links_for_items(session: Session, items: list[ExamPaperItem]) -> dict[int, list[dict[str, object]]]:
    return exams_repo.list_links_for_exam_items(session, [int(item.id or 0) for item in items])


def _knowledge_units_for_item_links(
    session: Session,
    links_by_item_id: dict[int, list[dict[str, object]]],
) -> dict[int, KnowledgeUnit]:
    knowledge_unit_ids = {
        knowledge_unit_id
        for refs in links_by_item_id.values()
        for ref in refs
        for knowledge_unit_id in [int(ref.get("knowledge_unit_id", 0) or 0)]
        if knowledge_unit_id > 0
    }
    return {
        unit.id: unit
        for unit in session.exec(
            select(KnowledgeUnit).where(KnowledgeUnit.id.in_(knowledge_unit_ids))
        ).all()
        if unit.id is not None
    } if knowledge_unit_ids else {}


def _is_exam_eligible_unit(unit: KnowledgeUnit) -> bool:
    name = _clean_exam_text(unit.canonical_name)
    summary = _clean_exam_text(unit.summary)
    if not name or len(name) <= 1:
        return False
    if len(name) > 80:
        return False
    if summary and len(summary) > 1000:
        return False
    return True


def _list_exam_eligible_units(
    session: Session,
    *,
    subject: str,
) -> list[KnowledgeUnit]:
    stmt = select(KnowledgeUnit).where(
        KnowledgeUnit.subject == subject,
        KnowledgeUnit.status == "active",
    )
    units = list(session.exec(stmt.order_by(KnowledgeUnit.id)).all())
    return [unit for unit in units if _is_exam_eligible_unit(unit)]


def _exam_knowledge_graph_edges(
    session: Session,
    *,
    subject: str,
    unit_ids: list[int],
) -> list[dict[str, object]]:
    allowed_ids = {int(unit_id) for unit_id in unit_ids if int(unit_id or 0) > 0}
    if not allowed_ids:
        return []
    edges: list[dict[str, object]] = []
    for edge in knowledge_relation_repo.list_all_edges_by_subject(session, subject):
        source_id = int(edge.source_node_id or 0)
        target_id = int(edge.target_node_id or 0)
        if source_id not in allowed_ids or target_id not in allowed_ids:
            continue
        edges.append(
            {
                "source_id": source_id,
                "target_id": target_id,
            }
        )
    return edges


def _exam_priority_unit_ids(
    session: Session,
    *,
    user_id: str,
    subject: str,
    exam_mode: str,
) -> list[int]:
    priority_ids: list[int] = []
    if exam_mode == "web_practice":
        due_states = profile_repo.list_due_knowledge_states(
            session,
            user_id=user_id,
            subject=subject,
            as_of=utcnow(),
            target_kind="knowledge_unit",
        )
        weak_states = profile_repo.list_weak_knowledge_states(
            session,
            user_id=user_id,
            subject=subject,
            target_kind="knowledge_unit",
        )
        for state in [*due_states, *weak_states]:
            if state.knowledge_unit_id is not None:
                priority_ids.append(int(state.knowledge_unit_id))

    if exam_mode == "paper_exam":
        weak_states = profile_repo.list_weak_knowledge_states(
            session,
            user_id=user_id,
            subject=subject,
            target_kind="knowledge_unit",
        )
        priority_ids.extend(
            int(state.knowledge_unit_id)
            for state in weak_states
            if state.knowledge_unit_id is not None
        )

    deduped: list[int] = []
    seen: set[int] = set()
    for unit_id in priority_ids:
        if unit_id <= 0 or unit_id in seen:
            continue
        seen.add(unit_id)
        deduped.append(unit_id)
    return deduped


def _mastery_by_unit_id(session: Session, *, user_id: str, subject: str) -> dict[int, float]:
    return {
        int(state.knowledge_unit_id): float(state.mastery_score)
        for state in profile_repo.list_knowledge_states(
            session,
            user_id=user_id,
            subject=subject,
            target_kind="knowledge_unit",
        )
        if state.knowledge_unit_id is not None
    }


def _question_type_for_order(*, exam_mode: str, difficulty: str, item_order: int) -> str:
    del exam_mode, difficulty
    cycle = ["single_choice", "fill_blank"]
    return cycle[(item_order - 1) % len(cycle)]


def _build_exam_selection_context(
    *,
    source: str,
    knowledge_unit_ids: list[int],
    user_prompt: str | None,
    sample_file_uids: list[str],
    generation_status: str = "generating",
    error_message: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "source": source,
        "knowledge_unit_ids": knowledge_unit_ids,
        "user_prompt": user_prompt,
        "sample_file_uids": sample_file_uids,
        "generation_status": generation_status,
    }
    if error_message:
        payload["error_message"] = error_message
    return json.dumps(payload, ensure_ascii=False)


def _set_exam_generation_status(
    session: Session,
    paper: ExamPaper,
    *,
    status: str,
    error_message: str | None = None,
) -> ExamPaper:
    context = _json_dict(paper.selection_context_json)
    context["generation_status"] = status
    if error_message:
        context["error_message"] = error_message
    else:
        context.pop("error_message", None)
    paper.selection_context_json = json.dumps(context, ensure_ascii=False)
    paper.status = status
    paper.updated_at = utcnow()
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


def _require_generated_questions_by_order(
    *,
    build_result,
    expected_orders: list[int],
) -> dict[int, dict[str, object]]:
    if build_result.failed:
        detail = str(build_result.error.detail if build_result.error is not None else "").strip()
        raise AITeachMeError(
            detail=detail or "Exam question generation failed.",
            error_code="EXAM_QUESTION_BUILD_FAILED",
            status_code=502,
        )

    state = build_result.require_value()
    build_error = str(state.get("error") or "").strip()
    if build_error:
        raise AITeachMeError(
            detail=build_error,
            error_code="EXAM_QUESTION_BUILD_FAILED",
            status_code=502,
        )

    generated_questions = state.get("generated_questions") or []
    generated_by_order: dict[int, dict[str, object]] = {}
    invalid_orders: list[object] = []
    for item in generated_questions:
        if not isinstance(item, dict):
            invalid_orders.append(item)
            continue
        try:
            item_order = int(item["item_order"])
        except (KeyError, TypeError, ValueError):
            invalid_orders.append(item.get("item_order"))
            continue
        generated_by_order[item_order] = item

    if invalid_orders:
        raise AITeachMeError(
            detail=f"Exam question generation returned invalid item_order values: {invalid_orders}",
            error_code="EXAM_QUESTION_BUILD_INVALID",
            status_code=502,
        )

    missing_orders = [order for order in expected_orders if order not in generated_by_order]
    if missing_orders:
        raise AITeachMeError(
            detail=f"Exam question generation returned incomplete results; missing item_order values: {missing_orders}",
            error_code="EXAM_QUESTION_BUILD_INCOMPLETE",
            status_code=502,
        )

    return generated_by_order


def _upsert_generated_template(
    session: Session,
    *,
    subject: str,
    unit: KnowledgeUnit,
    question_type: str,
    difficulty: str,
    stem: str,
    answer: str,
    explanation: str,
    options: list[str] | None,
    knowledge_unit_refs: list[dict[str, object]] | None = None,
    rationale: str = "",
) -> QuestionTemplate:
    stem_hash = _hash_stem(stem)
    refs = knowledge_unit_refs or [{"knowledge_unit_id": unit.id, "coverage_weight": 1.0, "role": "primary"}]
    selection_hints = {"rationale": rationale.strip()} if rationale.strip() else {}
    existing = exams_repo.find_template_by_stem_hash(session, subject, int(unit.id or 0), stem_hash)
    if existing is not None:
        existing.question_type = question_type
        existing.difficulty = difficulty
        existing.stem = stem
        existing.answer = answer
        existing.explanation = explanation
        existing.options_json = json.dumps(options, ensure_ascii=False) if options else None
        existing_hints = _json_dict(existing.selection_hints_json)
        if selection_hints:
            existing_hints.update(selection_hints)
            existing.selection_hints_json = json.dumps(existing_hints, ensure_ascii=False)
        existing.updated_at = utcnow()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        exams_repo.replace_question_template_links(session, template_id=int(existing.id or 0), refs=refs)
        return existing

    template = QuestionTemplate(
        subject=subject,
        question_type=question_type,
        difficulty=difficulty,
        stem=stem,
        stem_hash=stem_hash,
        answer=answer,
        explanation=explanation,
        options_json=json.dumps(options, ensure_ascii=False) if options else None,
        selection_hints_json=json.dumps(selection_hints, ensure_ascii=False),
    )
    template = exams_repo.create_question_template(session, template)
    exams_repo.replace_question_template_links(session, template_id=int(template.id or 0), refs=refs)
    return template


async def _run_exam_generation_background(
    *,
    subject: str,
    user_id: str,
    paper_id: int,
    exam_mode: str,
    unit_ids: list[int],
    question_count: int,
    user_prompt: str | None,
) -> None:
    _publish_exam_event(
        subject,
        paper_id,
        "snapshot",
        {"exam_paper_id": paper_id, "status": "generating", "stage": "question_build"},
    )
    try:
        with managed_session() as session:
            paper = exams_repo.get_exam_paper_by_id(session, paper_id)
            if paper is None or paper.subject != subject or paper.user_id != user_id:
                return
            _publish_exam_event(
                subject,
                paper_id,
                "snapshot",
                _paper_generation_event_payload(paper, stage="question_build"),
            )
            subject_row = _ensure_subject(session, subject, user_id)
            units = list(
                session.exec(
                    select(KnowledgeUnit).where(
                        KnowledgeUnit.subject == subject,
                        KnowledgeUnit.id.in_(unit_ids),
                    )
                ).all()
            )
            unit_by_id = {int(unit.id): unit for unit in units if unit.id is not None}
            exam_units = [unit_by_id[unit_id] for unit_id in unit_ids if unit_id in unit_by_id]
            unit_name_by_id = {
                int(unit.id): unit.canonical_name
                for unit in exam_units
                if unit.id is not None and unit.canonical_name
            }
            if not exam_units:
                raise AITeachMeError(
                    detail="No persisted KnowledgeUnits are available for exam generation.",
                    error_code="NO_PERSISTED_KNOWLEDGE_UNITS_FOR_EXAM",
                    status_code=409,
                )
            subject_context = load_subject_llm_context(session, subject=subject)

            mastery_by_unit_id = _mastery_by_unit_id(session, user_id=user_id, subject=subject)
            priority_unit_ids = _exam_priority_unit_ids(
                session,
                user_id=user_id,
                subject=subject,
                exam_mode=exam_mode,
            )
            knowledge_graph_edges = _exam_knowledge_graph_edges(
                session,
                subject=subject,
                unit_ids=[int(unit.id or 0) for unit in exam_units],
            )
            recent_stems: list[str] = []
            for item, _asked_at, recent_paper_id in exams_repo.list_exam_item_snapshots_by_user(
                session,
                subject=subject,
                user_id=user_id,
                limit=RECENT_EXAM_STEM_AVOID_LIMIT + question_count,
            ):
                if int(recent_paper_id) == paper_id:
                    continue
                stem = _clean_exam_text(item.stem_snapshot)
                if stem:
                    recent_stems.append(stem[:220])
                if len(recent_stems) >= RECENT_EXAM_STEM_AVOID_LIMIT:
                    break

        diversity_prompt = _build_exam_diversity_prompt(
            run_id=uuid.uuid4().hex,
            recent_stems=recent_stems,
        )

        async def handle_question_build_progress(payload: dict[str, object]) -> None:
            candidate_unit_ids = payload.get("candidate_unit_ids")
            if isinstance(candidate_unit_ids, list):
                candidate_ids = [
                    int(unit_id)
                    for unit_id in candidate_unit_ids
                    if isinstance(unit_id, int | str) and int(unit_id or 0) > 0
                ]
                with managed_session() as session:
                    paper = exams_repo.get_exam_paper_by_id(session, paper_id)
                    if paper is None or paper.subject != subject or paper.user_id != user_id:
                        return
                    context = _json_dict(paper.selection_context_json)
                    context["source"] = "knowledge_unit_candidate_pool"
                    context["knowledge_unit_ids"] = candidate_ids
                    for key in (
                        "candidate_unit_limit",
                        "input_unit_count",
                        "knowledge_graph_edge_count",
                        "candidate_unit_count",
                        "scope_include_terms",
                        "scope_exclude_terms",
                        "scope_strict",
                        "filter_strategy",
                        "filter_rationale",
                    ):
                        if key in payload:
                            context[key] = payload[key]
                    paper.selection_context_json = json.dumps(context, ensure_ascii=False)
                    paper.updated_at = utcnow()
                    session.add(paper)
                    session.commit()
                    session.refresh(paper)
                    event_payload = _paper_generation_event_payload(
                        paper,
                        stage=str(payload.get("stage") or "filter_exam_units"),
                    )
                _publish_exam_event(subject, paper_id, "snapshot", event_payload)

            blueprints = payload.get("question_blueprints")
            if not isinstance(blueprints, list):
                return
            blueprint_payload = [item for item in blueprints if isinstance(item, dict)]
            preview = _build_blueprint_paper_preview(
                blueprint_payload,
                question_count=question_count,
                unit_name_by_id=unit_name_by_id,
            )
            with managed_session() as session:
                paper = exams_repo.get_exam_paper_by_id(session, paper_id)
                if paper is None or paper.subject != subject or paper.user_id != user_id:
                    return
                paper.total_items = question_count
                paper.total_score = float(question_count)
                paper.paper_preview_json = preview.model_dump_json()
                paper.updated_at = utcnow()
                session.add(paper)
                session.commit()
                session.refresh(paper)
                event_payload = _paper_generation_event_payload(
                    paper,
                    preview=preview,
                    stage=str(payload.get("stage") or "plan_exam_questions"),
                )
            _publish_exam_event(subject, paper_id, "snapshot", event_payload)

        build_result = await run_question_build_workflow(
            subject=subject,
            subject_name=subject_row.name,
            subject_description=subject_row.description,
            subject_user_intent=subject_row.user_intent,
            exam_mode=exam_mode,
            units=exam_units,
            knowledge_graph_edges=knowledge_graph_edges,
            question_count=question_count,
            mastery_by_unit_id=mastery_by_unit_id,
            priority_unit_ids=priority_unit_ids,
            subject_context=subject_context,
            user_prompt=user_prompt or "",
            system_constraints=diversity_prompt,
            progress_callback=handle_question_build_progress,
        )
        generated_by_order = _require_generated_questions_by_order(
            build_result=build_result,
            expected_orders=list(range(1, question_count + 1)),
        )
        question_blueprints = build_result.value.get("question_blueprints") if build_result.value else []
        blueprint_by_order = {
            int(item.get("item_order", 0) or 0): item
            for item in question_blueprints
            if isinstance(item, dict)
        }

        with managed_session() as session:
            paper = exams_repo.get_exam_paper_by_id(session, paper_id)
            if paper is None or paper.subject != subject or paper.user_id != user_id:
                return
            units = list(
                session.exec(
                    select(KnowledgeUnit).where(
                        KnowledgeUnit.subject == subject,
                        KnowledgeUnit.id.in_(unit_ids),
                    )
                ).all()
            )
            unit_by_id = {int(unit.id): unit for unit in units if unit.id is not None}
            items: list[ExamPaperItem] = []
            refs_by_order: dict[int, list[dict[str, object]]] = {}
            for order in range(1, question_count + 1):
                generated = generated_by_order[order]
                refs = [
                    ref
                    for ref in list(generated.get("knowledge_unit_refs") or [])
                    if isinstance(ref, dict) and int(ref.get("knowledge_unit_id", 0) or 0) in unit_by_id
                ]
                primary_unit_id = int((refs[0] if refs else {}).get("knowledge_unit_id", 0) or 0)
                unit = unit_by_id.get(primary_unit_id)
                if unit is None:
                    continue
                if not refs:
                    refs = [{"knowledge_unit_id": primary_unit_id, "coverage_weight": 1.0, "role": "primary"}]
                refs_by_order[order] = refs
                blueprint = blueprint_by_order.get(order, {})
                rationale = str(blueprint.get("rationale") or "")
                blueprint_unit_ids = [
                    int(unit_id)
                    for unit_id in list(blueprint.get("knowledge_unit_ids") or [])
                    if int(unit_id or 0) > 0
                ]
                if not blueprint_unit_ids:
                    blueprint_unit_ids = [
                        int(ref.get("knowledge_unit_id", 0) or 0)
                        for ref in refs
                        if int(ref.get("knowledge_unit_id", 0) or 0) > 0
                    ]
                item_selection_context = {
                    "blueprint": {
                        "item_order": int(blueprint.get("item_order") or order),
                        "knowledge_unit_ids": blueprint_unit_ids,
                        "question_type": str(blueprint.get("question_type") or generated["question_type"]),
                        "difficulty": str(blueprint.get("difficulty") or generated["difficulty"]),
                        "rationale": rationale,
                        "generation_prompt": str(blueprint.get("generation_prompt") or ""),
                    }
                }
                template = _upsert_generated_template(
                    session,
                    subject=subject,
                    unit=unit,
                    difficulty=str(generated["difficulty"]),
                    question_type=str(generated["question_type"]),
                    stem=str(generated["stem"]),
                    answer=str(generated["correct_answer"]),
                    explanation=str(generated["explanation"]),
                    options=list(generated.get("options") or []) or None,
                    knowledge_unit_refs=refs,
                    rationale=rationale,
                )
                items.append(
                    ExamPaperItem(
                        exam_paper_id=paper.id or 0,
                        question_template_id=template.id or 0,
                        item_order=order,
                        stem_snapshot=template.stem,
                        options_snapshot_json=template.options_json,
                        answer_snapshot=template.answer,
                        explanation_snapshot=template.explanation,
                        selection_context_json=json.dumps(item_selection_context, ensure_ascii=False),
                        difficulty=template.difficulty,
                        question_type=template.question_type,
                        score=1.0,
                    )
                )
            exams_repo.create_exam_paper_items(session, items)
            links_by_item_id: dict[int, list[dict[str, object]]] = {}
            for item in items:
                refs = refs_by_order.get(item.item_order, [])
                exams_repo.replace_exam_paper_item_links(
                    session,
                    item_id=int(item.id or 0),
                    refs=refs,
                    auto_commit=False,
                )
                links_by_item_id[int(item.id or 0)] = refs
            session.commit()
            paper.total_items = len(items)
            paper.total_score = float(len(items))
            paper.paper_preview_json = _build_paper_preview(
                items,
                knowledge_unit_by_id=unit_by_id,
                links_by_item_id=links_by_item_id,
            ).model_dump_json()
            _set_exam_generation_status(session, paper, status="ready")
            done_payload = _paper_generation_event_payload(
                paper,
                stage="ready",
                preview=_paper_preview_from_json(paper.paper_preview_json),
            )

        _publish_exam_event(
            subject,
            paper_id,
            "done",
            done_payload,
        )
    except Exception as exc:
        error_message = str(getattr(exc, "detail", None) or exc or "Exam question generation failed.")
        logger.exception(
            "exam_generation_background_failed",
            subject=subject,
            user_id=user_id,
            paper_id=paper_id,
            exam_mode=exam_mode,
            question_count=question_count,
            error_message=error_message,
        )
        with managed_session() as session:
            paper = exams_repo.get_exam_paper_by_id(session, paper_id)
            if paper is not None:
                paper = _set_exam_generation_status(session, paper, status="failed", error_message=error_message)
                failure_payload = _paper_generation_event_payload(
                    paper,
                    stage="failed",
                    error_message=error_message,
                )
            else:
                failure_payload = {
                    "exam_paper_id": paper_id,
                    "status": "failed",
                    "error_message": error_message,
                }
        _publish_exam_event(
            subject,
            paper_id,
            "done",
            failure_payload,
        )


async def _spawn_exam_generation_after_response(
    request: Request,
    *,
    subject: str,
    user_id: str,
    paper_id: int,
    exam_mode: str,
    unit_ids: list[int],
    question_count: int,
    user_prompt: str | None,
) -> None:
    request.app.state.background_task_registry.spawn(
        _run_exam_generation_background(
            subject=subject,
            user_id=user_id,
            paper_id=paper_id,
            exam_mode=exam_mode,
            unit_ids=unit_ids,
            question_count=question_count,
            user_prompt=user_prompt,
        ),
        kind="exam.generate",
        subject=subject,
        name=f"exam.generate:{subject}:{paper_id}",
    )


def _paper_item_response(
    item: ExamPaperItem,
    *,
    knowledge_unit_by_id: dict[int, KnowledgeUnit],
    mastery_by_unit_id: dict[int, float],
    knowledge_unit_refs: list[dict[str, object]],
) -> ExamPaperItemResponse:
    return ExamPaperItemResponse(
        id=item.id,
        item_order=item.item_order,
        question_template_id=item.question_template_id,
        question_type=item.question_type,
        difficulty=item.difficulty,
        stem=item.stem_snapshot,
        options=json.loads(item.options_snapshot_json) if item.options_snapshot_json else None,
        correct_answer=item.answer_snapshot,
        explanation=item.feedback_text or item.explanation_snapshot,
        knowledge_unit_links=[
            {
                "knowledge_unit_id": knowledge_unit_id,
                "knowledge_unit_name": (
                    knowledge_unit_by_id[knowledge_unit_id].canonical_name
                    if knowledge_unit_id in knowledge_unit_by_id
                    else ""
                ),
                "coverage_weight": float(ref.get("coverage_weight", 1.0) or 1.0),
                "role": str(ref.get("role", "primary")),
                "mastery_score": mastery_by_unit_id.get(knowledge_unit_id),
            }
            for ref in knowledge_unit_refs
            for knowledge_unit_id in [int(ref.get("knowledge_unit_id", 0) or 0)]
            if knowledge_unit_id > 0
        ],
        selection_context=_json_dict(item.selection_context_json),
        user_answer=item.answer_content or None,
        is_correct=item.is_correct,
        score_obtained=item.score_obtained,
        score_max=item.score_max,
        error_cause_label=item.error_cause_label,
    )


def _question_template_response(
    template: QuestionTemplate,
    *,
    knowledge_unit_refs: list[dict[str, object]],
) -> QuestionTemplateItemResponse:
    options_payload = None
    if template.options_json:
        try:
            decoded_options = json.loads(template.options_json)
            if isinstance(decoded_options, list):
                options_payload = [str(item) for item in decoded_options]
        except json.JSONDecodeError:
            options_payload = None

    return QuestionTemplateItemResponse(
        id=template.id or 0,
        subject=template.subject,
        question_type=template.question_type,
        difficulty=template.difficulty,
        stem=template.stem,
        options=options_payload,
        answer=template.answer,
        explanation=template.explanation,
        knowledge_unit_refs=knowledge_unit_refs,
        selection_hints=_json_dict(template.selection_hints_json),
        template_version=template.template_version,
        status=template.status,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def _question_type_response(item: QuestionTypeRegistry) -> QuestionTypeRegistryItemResponse:
    return QuestionTypeRegistryItemResponse(
        id=item.id or 0,
        type_key=item.type_key,
        display_name=item.display_name,
        scope=item.scope,
        subject=item.subject,
        description=item.description,
        answer_format=item.answer_format,
        grading_method=item.grading_method,
        option_schema=_json_dict(item.option_schema_json),
        rubric=_json_dict(item.rubric_json),
        source=item.source,
        confidence=item.confidence,
        is_system=item.is_system,
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _paper_detail(session: Session, paper: ExamPaper) -> ExamPaperDetailResponse:
    items = exams_repo.list_items_by_paper(session, paper.id or 0)
    links_by_item_id = _links_for_items(session, items)
    knowledge_unit_by_id = _knowledge_units_for_item_links(session, links_by_item_id)
    mastery_by_unit_id = {
        int(state.knowledge_unit_id): state.mastery_score
        for state in profile_repo.list_knowledge_states(
            session,
            user_id=paper.user_id,
            subject=paper.subject,
            target_kind="knowledge_unit",
        )
        if state.knowledge_unit_id is not None
    }
    return ExamPaperDetailResponse(
        id=paper.id,
        subject=paper.subject,
        user_id=paper.user_id,
        exam_mode=paper.exam_mode,
        status=paper.status,
        total_items=paper.total_items,
        score_obtained=paper.score_obtained,
        total_score=paper.total_score,
        submitted_at=paper.submitted_at,
        graded_at=paper.graded_at,
        created_at=paper.created_at,
        selection_context=json.loads(paper.selection_context_json or "{}"),
        paper_preview=_paper_preview_for_response(
            paper,
            items,
            knowledge_unit_by_id=knowledge_unit_by_id,
            links_by_item_id=links_by_item_id,
        ),
        items=[
            _paper_item_response(
                item,
                knowledge_unit_by_id=knowledge_unit_by_id,
                mastery_by_unit_id=mastery_by_unit_id,
                knowledge_unit_refs=links_by_item_id.get(int(item.id or 0), []),
            )
            for item in items
        ],
    )


async def _study_guide_detail(session: Session, paper: ExamPaper) -> ExamStudyGuideResponse:
    items = exams_repo.list_items_by_paper(session, paper.id or 0)
    links_by_item_id = _links_for_items(session, items)
    knowledge_unit_ids = {
        knowledge_unit_id
        for refs in links_by_item_id.values()
        for ref in refs
        for knowledge_unit_id in [int(ref.get("knowledge_unit_id", 0) or 0)]
        if knowledge_unit_id > 0
    }
    knowledge_unit_by_id = {
        unit.id: unit
        for unit in session.exec(
            select(KnowledgeUnit).where(KnowledgeUnit.id.in_(knowledge_unit_ids))
        ).all()
        if unit.id is not None
    } if knowledge_unit_ids else {}

    weak_states = profile_repo.list_weak_knowledge_states(
        session,
        user_id=paper.user_id,
        subject=paper.subject,
        target_kind="knowledge_unit",
    )
    pending_reviews = profile_repo.list_pending_reviews(
        session,
        user_id=paper.user_id,
        subject=paper.subject,
    )
    wrong_question_summaries = profile_repo.list_recent_wrong_attempt_summaries(
        session,
        user_id=paper.user_id,
        subject=paper.subject,
        knowledge_unit_ids=[
            int(state.knowledge_unit_id)
            for state in weak_states
            if state.knowledge_unit_id is not None
        ],
        limit=5,
    )

    score_summary = (
        f"得分 {paper.score_obtained or 0:.1f}/{paper.total_score or 0:.1f}，"
        f"共 {paper.total_items} 题，"
        f"正确 {sum(1 for item in items if item.is_correct)} 题，"
        f"错误或未作答 {sum(1 for item in items if item.is_correct is not True)} 题。"
    )
    weak_point_payload = [
        {
            "knowledge_unit_id": int(state.knowledge_unit_id) if state.knowledge_unit_id is not None else None,
            "knowledge_unit_name": (
                knowledge_unit_by_id[int(state.knowledge_unit_id)].canonical_name
                if state.knowledge_unit_id is not None and int(state.knowledge_unit_id) in knowledge_unit_by_id
                else "未命名知识点"
            ),
            "mastery_score": round(float(state.mastery_score), 3),
            "reason": (
                f"掌握度 {float(state.mastery_score):.0%}，"
                f"累计 {state.total_attempts} 次练习，"
                f"正确 {state.correct_attempts} 次。"
            ),
        }
        for state in weak_states[:5]
    ]
    review_payload = [
        {
            "knowledge_unit_name": (
                knowledge_unit_by_id[int(state.knowledge_unit_id)].canonical_name
                if state.knowledge_unit_id is not None and int(state.knowledge_unit_id) in knowledge_unit_by_id
                else "未命名知识点"
            ),
            "reason": state.review_reason or "建议尽快回顾",
            "priority": round(float(state.review_priority), 3),
        }
        for state in pending_reviews[:5]
    ]

    response = await run_exam_study_guide_workflow(
        exam_paper_id=paper.id or 0,
        subject=paper.subject,
        exam_title=_build_exam_title(paper),
        score_summary=score_summary,
        wrong_question_summaries=wrong_question_summaries,
        weak_points=weak_point_payload,
        pending_reviews=review_payload,
        generated_at=utcnow(),
    )
    if response.focus_units:
        normalized_focus_units: list[ExamStudyGuideFocusUnit] = []
        for item in response.focus_units:
            if item.knowledge_unit_name.strip():
                normalized_focus_units.append(item)
        response.focus_units = normalized_focus_units
    return response


async def _grade_exam(session: Session, paper: ExamPaper) -> ExamGradeResponse:
    items = exams_repo.list_items_by_paper(session, paper.id or 0)
    decisions = await run_exam_grade_workflow(subject=paper.subject, items=items)
    total_score = 0.0
    score_obtained = 0.0
    now = utcnow()
    for item, decision in zip(items, decisions, strict=False):
        item.is_correct = decision.is_correct
        item.score_max = decision.score_max
        item.score_obtained = decision.score_obtained
        item.error_cause_label = decision.error_cause_label
        item.feedback_text = decision.feedback_text
        item.graded_at = now
        item.updated_at = now
        total_score += item.score
        score_obtained += item.score_obtained or 0.0
        session.add(item)

    paper.status = "graded"
    paper.total_score = total_score
    paper.score_obtained = score_obtained
    paper.graded_at = now
    paper.updated_at = now
    session.add(paper)
    session.commit()
    session.refresh(paper)

    mastery = update_mastery_from_exam(session, paper.id or 0)
    reviews = schedule_reviews(
        session,
        user_id=paper.user_id,
        subject=paper.subject,
        updated_state_ids=mastery.updated_state_ids,
    )
    return ExamGradeResponse(
        id=paper.id or 0,
        status="completed",
        error_message=None,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
        exam_paper_id=paper.id or 0,
        score=score_obtained,
        states_updated=mastery.states_updated,
        tasks_created=len(reviews),
        mastery_consumed=True,
    )


@router.post(
    "/generate",
    response_model=ApiResponse[ExamGenerateResponse],
    summary="Generate an exam from KnowledgeUnits",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def generate_exam(
    request: Request,
    background_tasks: BackgroundTasks,
    subject: str = Path(...),
    body: ExamGenerateRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamGenerateResponse]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    question_count = max(1, int(body.num_questions or 5))
    units = _list_exam_eligible_units(
        session,
        subject=normalized,
    )
    if not units:
        raise AITeachMeError(
            detail="No active KnowledgeUnits are available for exam generation.",
            error_code="NO_KNOWLEDGE_UNITS_FOR_EXAM",
            status_code=409,
        )
    exam_units = [unit for unit in units if unit.id is not None]
    if not exam_units:
        raise AITeachMeError(
            detail="No persisted KnowledgeUnits are available for exam generation.",
            error_code="NO_PERSISTED_KNOWLEDGE_UNITS_FOR_EXAM",
            status_code=409,
        )

    mode = exam_mode_value(body.exam_mode)
    initial_preview = _build_placeholder_paper_preview(question_count=question_count)
    paper = exams_repo.create_exam_paper(
        session,
        ExamPaper(
            subject=normalized,
            user_id=user.user_id,
            exam_mode=mode,
            status="generating",
            total_items=question_count,
            total_score=float(question_count),
            paper_preview_json=initial_preview.model_dump_json(),
            selection_context_json=_build_exam_selection_context(
                source="knowledge_unit_pool",
                knowledge_unit_ids=[int(unit.id or 0) for unit in exam_units],
                user_prompt=body.user_prompt,
                sample_file_uids=body.sample_file_uids or [],
            ),
        ),
    )
    paper_id = paper.id or 0
    background_tasks.add_task(
        _spawn_exam_generation_after_response,
        request,
        subject=normalized,
        user_id=user.user_id,
        paper_id=paper_id,
        exam_mode=mode,
        unit_ids=[int(unit.id or 0) for unit in exam_units],
        question_count=question_count,
        user_prompt=body.user_prompt,
    )
    return ok_response(
        ExamGenerateResponse(
            id=paper_id,
            status=paper.status,
            error_message=None,
            created_at=paper.created_at,
            updated_at=paper.updated_at,
            subject=paper.subject,
            user_id=paper.user_id,
            exam_mode=paper.exam_mode,
            num_questions=question_count,
            exam_paper_id=paper_id,
            sample_file_uids=body.sample_file_uids or [],
        )
    )


@router.get(
    "/history",
    response_model=ApiResponse[PaginatedData[ExamHistoryItem]],
    summary="List exam history",
    responses=build_error_responses([400, 404, 500]),
)
async def exam_history(
    subject: str = Path(...),
    page: int = 1,
    size: int = 20,
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[ExamHistoryItem]]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    rows, total = exams_repo.list_exam_papers(
        session,
        subject=normalized,
        user_id=user.user_id,
        limit=size,
        offset=PageParams(page=page, size=size).offset,
    )
    items_by_paper_id = {
        int(paper.id or 0): exams_repo.list_items_by_paper(session, int(paper.id or 0))
        for paper in rows
        if paper.id is not None
    }
    all_items = [item for items in items_by_paper_id.values() for item in items]
    links_by_item_id = _links_for_items(session, all_items)
    knowledge_unit_by_id = _knowledge_units_for_item_links(session, links_by_item_id)
    return ok_response(
        build_paginated_data(
            items=[
                ExamHistoryItem(
                    id=paper.id,
                    subject=paper.subject,
                    user_id=paper.user_id,
                    exam_mode=paper.exam_mode,
                    status=paper.status,
                    total_items=paper.total_items,
                    score_obtained=paper.score_obtained,
                    total_score=paper.total_score,
                    created_at=paper.created_at,
                    submitted_at=paper.submitted_at,
                    graded_at=paper.graded_at,
                    paper_preview=_paper_preview_for_response(
                        paper,
                        items_by_paper_id.get(int(paper.id or 0), []),
                        knowledge_unit_by_id=knowledge_unit_by_id,
                        links_by_item_id=links_by_item_id,
                    ),
                )
                for paper in rows
            ],
            page=page,
            size=size,
            total=total,
        )
    )


@router.get(
    "/question-templates",
    response_model=ApiResponse[list[QuestionTemplateItemResponse]],
    summary="List question templates for the subject",
    responses=build_error_responses([400, 404, 500]),
)
async def question_templates(
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[QuestionTemplateItemResponse]]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    rows = list(
        session.exec(
            select(QuestionTemplate)
            .where(QuestionTemplate.subject == normalized)
            .order_by(QuestionTemplate.created_at.desc(), QuestionTemplate.id.desc())
        ).all()
    )
    links_by_template_id = exams_repo.list_links_for_templates(session, [int(item.id or 0) for item in rows])
    return ok_response([
        _question_template_response(
            item,
            knowledge_unit_refs=links_by_template_id.get(int(item.id or 0), []),
        )
        for item in rows
    ])


@router.get(
    "/question-types",
    response_model=ApiResponse[list[QuestionTypeRegistryItemResponse]],
    summary="List global and subject question types",
    responses=build_error_responses([400, 404, 500]),
)
async def question_types(
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[QuestionTypeRegistryItemResponse]]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    rows = list(
        session.exec(
            select(QuestionTypeRegistry)
            .where(
                QuestionTypeRegistry.is_active == True,  # noqa: E712
                or_(
                    QuestionTypeRegistry.scope == "global",
                    QuestionTypeRegistry.subject == normalized,
                ),
            )
            .order_by(
                QuestionTypeRegistry.scope.asc(),
                QuestionTypeRegistry.subject.asc(),
                QuestionTypeRegistry.type_key.asc(),
            )
        ).all()
    )
    return ok_response([_question_type_response(item) for item in rows])


@router.get(
    "/{exam_paper_id}/stream",
    summary="SSE stream for exam generation status",
    responses=build_error_responses([400, 404, 500]),
)
async def exam_generation_stream(
    request: Request,
    subject: str = Path(...),
    exam_paper_id: int = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.subject != normalized or paper.user_id != user.user_id:
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")

    async def event_generator():
        def snapshot_payload() -> dict[str, object]:
            with managed_session() as stream_session:
                current = exams_repo.get_exam_paper_by_id(stream_session, exam_paper_id)
                if current is None:
                    return {
                        "exam_paper_id": exam_paper_id,
                        "status": "failed",
                        "error_message": "Exam paper no longer exists.",
                    }
                return _paper_generation_event_payload(current)

        initial = snapshot_payload()
        yield format_sse_event("snapshot", initial)
        if str(initial.get("status") or "") in {"ready", "failed", "graded", "submitted"}:
            yield format_sse_event("done", initial)
            return

        with subscribe_workflow_stream(_exam_stream_channel(normalized, exam_paper_id)) as queue:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await queue.get()
                except Exception:
                    break
                yield format_sse_event(event.event, event.data)
                if event.event == "done":
                    break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get(
    "/{exam_paper_id}",
    response_model=ApiResponse[ExamPaperDetailResponse],
    summary="Fetch exam detail",
    responses=build_error_responses([400, 404, 500]),
)
async def exam_detail(
    subject: str = Path(...),
    exam_paper_id: int = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamPaperDetailResponse]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.subject != normalized or paper.user_id != user.user_id:
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")
    return ok_response(_paper_detail(session, paper))


@router.delete(
    "/{exam_paper_id}",
    response_model=ApiResponse[ExamPaperDeleteResponse],
    summary="Delete exam paper",
    responses=build_error_responses([400, 404, 500]),
)
async def delete_exam_paper(
    subject: str = Path(...),
    exam_paper_id: int = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamPaperDeleteResponse]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.subject != normalized or paper.user_id != user.user_id:
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")

    exams_repo.delete_exam_paper_cascade(session, paper_id=exam_paper_id)
    return ok_response(ExamPaperDeleteResponse(deleted=True, exam_paper_id=exam_paper_id))


@router.get(
    "/{exam_paper_id}/study-guide",
    response_model=ApiResponse[ExamStudyGuideResponse],
    summary="Generate study guide from a graded exam",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def exam_study_guide(
    subject: str = Path(...),
    exam_paper_id: int = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamStudyGuideResponse]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.subject != normalized or paper.user_id != user.user_id:
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")
    if paper.status != "graded":
        raise AITeachMeError(
            detail="Study guide is available only after grading is complete.",
            error_code="EXAM_NOT_GRADED",
            status_code=409,
        )
    return ok_response(await _study_guide_detail(session, paper))


@router.post(
    "/{exam_paper_id}/submit",
    response_model=ApiResponse[ExamGradeResponse],
    summary="Submit answers and update KnowledgeUnit mastery",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def submit_exam(
    subject: str = Path(...),
    exam_paper_id: int = Path(...),
    body: ExamSubmitRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamGradeResponse]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.subject != normalized or paper.user_id != user.user_id:
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")
    if paper.status == "generating":
        raise AITeachMeError(detail="Exam is still generating.", error_code="EXAM_STILL_GENERATING", status_code=409)
    if paper.status == "failed":
        raise AITeachMeError(detail="Exam generation failed.", error_code="EXAM_GENERATION_FAILED", status_code=409)
    if paper.status == "graded":
        raise AITeachMeError(detail="Exam already graded.", error_code="EXAM_ALREADY_GRADED", status_code=409)

    answer_by_id = {item.exam_paper_item_id: item.answer for item in body.answers if item.exam_paper_item_id is not None}
    answer_by_order = {item.item_order: item.answer for item in body.answers if item.item_order is not None}
    now = utcnow()
    for item in exams_repo.list_items_by_paper(session, exam_paper_id):
        item.answer_content = answer_by_id.get(item.id) or answer_by_order.get(item.item_order) or ""
        item.answered_at = now
        item.updated_at = now
        session.add(item)
    paper.status = "submitted"
    paper.submitted_at = now
    paper.updated_at = now
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return ok_response(await _grade_exam(session, paper))
