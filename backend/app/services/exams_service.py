"""Exam services backed by the new schema."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from http import HTTPStatus

from sqlmodel import Session, select

from app.core.exceptions import AITeachMeError
from app.models import (
    CurriculumVersion,
    ExamMode,
    ExamPaper,
    ExamPaperItem,
    ExamPaperStatus,
    QuestionTemplate,
    QuestionTemplateNodeLink,
    QuestionType,
    ReviewTask,
    Subject,
    TeachingUnit,
    TeachingUnitMembership,
    UserAnswerAttempt,
    UserKnowledgeState,
)
from app.repositories.user_repo import get_or_create_user_by_username
from app.schemas.common import PaginatedData, build_paginated_data
from app.utils.time import utcnow


@dataclass(frozen=True)
class ExamPaperDetail:
    paper: dict[str, object]
    items: list[dict[str, object]]


@dataclass(frozen=True)
class QuestionBankItem:
    question_template_id: int
    stem: str
    question_type: str
    difficulty: str
    teaching_unit_id: int
    times_asked: int
    last_asked_at: datetime
    last_exam_paper_id: int


@dataclass(frozen=True)
class ExamGenerateResult:
    id: int
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    subject: str
    user_id: str
    exam_mode: str
    num_questions: int
    exam_paper_id: int | None
    theme_tree_node_id: int | None
    teaching_unit_ids_json: str


@dataclass(frozen=True)
class ExamGradeResult:
    id: int
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    exam_paper_id: int
    score: float | None
    states_updated: int
    tasks_created: int
    mastery_consumed: bool


def _not_found(detail: str, code: str) -> None:
    raise AITeachMeError(detail=detail, status_code=HTTPStatus.NOT_FOUND, error_code=code)


def _conflict(detail: str, code: str) -> None:
    raise AITeachMeError(detail=detail, status_code=HTTPStatus.CONFLICT, error_code=code)


def _job_id() -> int:
    return (int(utcnow().timestamp() * 1_000_000) % 2_000_000_000) + 1


def _subject_user(session: Session, subject: str, user_id: str) -> tuple[Subject, int]:
    subject_record = session.exec(select(Subject).where(Subject.slug == subject)).first()
    if subject_record is None or subject_record.id is None:
        _not_found(f"学科 `{subject}` 不存在。", "SUBJECT_NOT_FOUND")
    user = get_or_create_user_by_username(session, username=user_id)
    if user.id is None:
        raise ValueError("runtime user persistence failed")
    return subject_record, int(user.id)


def _current_curriculum_version_id(session: Session, subject_id: int) -> int | None:
    version = session.exec(
        select(CurriculumVersion)
        .where(CurriculumVersion.subject_id == subject_id, CurriculumVersion.status == "published")
        .order_by(CurriculumVersion.version_no.desc())  # type: ignore[union-attr]
    ).first()
    return int(version.id) if version is not None and version.id is not None else None


def _normalize_answer(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "")).strip().lower()


def _parse_json_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _ensure_templates(
    session: Session,
    *,
    subject_record: Subject,
    teaching_units: list[TeachingUnit],
    question_types: list[str],
    minimum_count: int,
) -> list[QuestionTemplate]:
    unit_ids = [int(unit.id) for unit in teaching_units if unit.id is not None]
    templates = list(
        session.exec(
            select(QuestionTemplate).where(
                QuestionTemplate.subject_id == int(subject_record.id or 0),
                QuestionTemplate.status == "active",
                QuestionTemplate.teaching_unit_id.in_(unit_ids),  # type: ignore[union-attr]
                QuestionTemplate.question_type.in_(question_types),  # type: ignore[union-attr]
            )
        ).all()
    )
    if len(templates) >= minimum_count or not teaching_units:
        return templates

    membership_rows = list(
        session.exec(
            select(TeachingUnitMembership).where(TeachingUnitMembership.unit_id.in_(unit_ids))  # type: ignore[union-attr]
        ).all()
    )
    links_by_unit: dict[int, list[TeachingUnitMembership]] = {}
    for row in membership_rows:
        links_by_unit.setdefault(row.unit_id, []).append(row)

    curriculum_version_id = _current_curriculum_version_id(session, int(subject_record.id or 0))
    for unit in teaching_units:
        if unit.id is None:
            continue
        summary = (unit.summary or unit.canonical_name).strip() or unit.canonical_name
        for question_type in question_types:
            if len(templates) >= minimum_count:
                session.commit()
                return templates
            stem = {
                QuestionType.SINGLE_CHOICE.value: f"关于《{unit.canonical_name}》，下列哪项最符合资料中的核心内容？",
                QuestionType.FILL_BLANK.value: f"请填空：{unit.canonical_name} 的核心内容可以概括为 ______。",
            }.get(question_type, f"请简述 {unit.canonical_name} 的核心内容。")
            options = None
            if question_type == QuestionType.SINGLE_CHOICE.value:
                options = json.dumps(
                    [summary[:40], f"{unit.canonical_name} 的错误表述", "与本单元无关的描述", "相反结论"],
                    ensure_ascii=False,
                )
            stem_hash = hashlib.sha256(f"{unit.id}:{question_type}:{stem}".encode("utf-8")).hexdigest()
            exists = session.exec(
                select(QuestionTemplate).where(
                    QuestionTemplate.subject_id == int(subject_record.id or 0),
                    QuestionTemplate.teaching_unit_id == int(unit.id),
                    QuestionTemplate.stem_hash == stem_hash,
                )
            ).first()
            if exists is not None:
                templates.append(exists)
                continue
            template = QuestionTemplate(
                user_id=subject_record.user_id,
                subject_id=int(subject_record.id or 0),
                teaching_unit_id=int(unit.id),
                curriculum_version_id=curriculum_version_id,
                question_type=question_type,
                difficulty="medium",
                stem=stem,
                stem_hash=stem_hash,
                options=options,
                answer=summary[:40] if question_type == QuestionType.SINGLE_CHOICE.value else summary,
                explanation="回到知识文档中的定义、方法或结论部分，提炼核心信息。",
                metadata_json=json.dumps({"generator": "auto_exam_seed"}, ensure_ascii=False),
            )
            session.add(template)
            session.flush()
            for membership in links_by_unit.get(int(unit.id), [])[:4]:
                session.add(
                    QuestionTemplateNodeLink(
                        question_template_id=int(template.id or 0),
                        knowledge_node_id=membership.knowledge_node_id,
                        coverage_weight=max(0.1, membership.score or 0.5),
                        role="primary" if membership.role == "core" else "secondary",
                    )
                )
            templates.append(template)
    session.commit()
    return templates


async def trigger_exam_generate(
    session: Session,
    *,
    subject: str,
    user_id: str,
    exam_mode: ExamMode | str,
    num_questions: int | None = None,
    user_prompt: str | None = None,
    theme_tree_node_id: int | None = None,
    teaching_unit_ids: list[int] | None = None,
) -> ExamGenerateResult:
    subject_record, runtime_user_id = _subject_user(session, subject, user_id)
    unit_stmt = select(TeachingUnit).where(
        TeachingUnit.subject_id == int(subject_record.id or 0),
        TeachingUnit.status == "active",
    )
    if teaching_unit_ids:
        unit_stmt = unit_stmt.where(TeachingUnit.id.in_(teaching_unit_ids))  # type: ignore[union-attr]
    teaching_units = list(session.exec(unit_stmt.order_by(TeachingUnit.id.asc())).all())  # type: ignore[union-attr]
    if not teaching_units:
        _conflict("当前学科没有可用教学单元，无法自动组卷。", "EXAM_GENERATE_NO_TEACHING_UNITS")

    mode = exam_mode.value if isinstance(exam_mode, ExamMode) else str(exam_mode).strip().lower()
    requested_count = num_questions or 10
    prompt_match = re.search(r"(\d{1,3})\s*(?:题|道|questions?)", user_prompt or "", re.IGNORECASE)
    if prompt_match:
        requested_count = max(1, min(200, int(prompt_match.group(1))))
    question_types = [QuestionType.SINGLE_CHOICE.value, QuestionType.FILL_BLANK.value, QuestionType.SHORT_ANSWER.value]
    if mode == ExamMode.REVIEW.value:
        question_types = [QuestionType.SINGLE_CHOICE.value]
    templates = _ensure_templates(
        session,
        subject_record=subject_record,
        teaching_units=teaching_units,
        question_types=question_types,
        minimum_count=max(1, requested_count),
    )
    if not templates:
        _conflict("当前没有可用题目模板，无法自动组卷。", "EXAM_GENERATE_NO_TEMPLATES")

    selected = [templates[index % len(templates)] for index in range(max(1, requested_count))]
    paper = ExamPaper(
        user_id=runtime_user_id,
        subject_id=int(subject_record.id or 0),
        exam_mode=mode,
        curriculum_version_id=_current_curriculum_version_id(session, int(subject_record.id or 0)),
        metadata_json=json.dumps(
            {"selection_reason_json": {"mode": mode, "prompt": user_prompt}, "target_theme_tree_node_id": theme_tree_node_id},
            ensure_ascii=False,
        ),
        status=ExamPaperStatus.READY.value,
        total_items=len(selected),
        total_score=float(len(selected)),
    )
    session.add(paper)
    session.flush()

    template_ids = [int(template.id) for template in selected if template.id is not None]
    node_links = list(
        session.exec(
            select(QuestionTemplateNodeLink).where(
                QuestionTemplateNodeLink.question_template_id.in_(template_ids)  # type: ignore[union-attr]
            )
        ).all()
    )
    links_by_template: dict[int, list[dict]] = {}
    for link in node_links:
        links_by_template.setdefault(link.question_template_id, []).append(
            {"knowledge_node_id": link.knowledge_node_id, "coverage_weight": link.coverage_weight, "role": link.role}
        )
    for order, template in enumerate(selected, start=1):
        session.add(
            ExamPaperItem(
                exam_paper_id=int(paper.id or 0),
                question_template_id=int(template.id or 0),
                item_order=order,
                snapshot_stem=template.stem,
                snapshot_options=template.options,
                snapshot_answer=template.answer,
                snapshot_explanation=template.explanation,
                snapshot_teaching_unit_id=template.teaching_unit_id,
                snapshot_node_links_json=json.dumps(links_by_template.get(int(template.id or 0), []), ensure_ascii=False),
                snapshot_difficulty=template.difficulty,
                snapshot_question_type=template.question_type,
            )
        )
    session.commit()
    session.refresh(paper)
    now = utcnow()
    return ExamGenerateResult(
        id=_job_id(),
        status="completed",
        error_message=None,
        created_at=now,
        updated_at=now,
        subject=subject,
        user_id=user_id,
        exam_mode=mode,
        num_questions=len(selected),
        exam_paper_id=int(paper.id or 0),
        theme_tree_node_id=theme_tree_node_id,
        teaching_unit_ids_json=json.dumps([int(unit.id) for unit in teaching_units if unit.id is not None], ensure_ascii=False),
    )


async def get_exam_generate_job_status(session: Session, *, subject: str, job_id: int, user_id: str) -> ExamGenerateResult:
    del session, subject, user_id
    _not_found(f"组卷任务 `{job_id}` 不存在（ExamGenerateJob 已移除）。", "EXAM_GENERATE_JOB_NOT_FOUND")


def _load_paper(session: Session, *, subject: str, user_id: str, exam_paper_id: int) -> tuple[Subject, int, ExamPaper]:
    subject_record, runtime_user_id = _subject_user(session, subject, user_id)
    paper = session.get(ExamPaper, exam_paper_id)
    if paper is None or paper.subject_id != int(subject_record.id or 0) or paper.user_id != runtime_user_id:
        _not_found(f"试卷 `{exam_paper_id}` 不存在。", "EXAM_PAPER_NOT_FOUND")
    return subject_record, runtime_user_id, paper


async def submit_exam_answers(
    session: Session,
    *,
    subject: str,
    exam_paper_id: int,
    user_id: str,
    answers: dict[int | str, str],
) -> dict[str, object]:
    _, runtime_user_id, paper = _load_paper(session, subject=subject, user_id=user_id, exam_paper_id=exam_paper_id)
    if paper.status not in {ExamPaperStatus.READY.value, ExamPaperStatus.IN_PROGRESS.value}:
        _conflict(f"试卷 `{exam_paper_id}` 当前状态 `{paper.status}`，不可提交。", "INVALID_EXAM_PAPER_STATUS")
    items = list(session.exec(select(ExamPaperItem).where(ExamPaperItem.exam_paper_id == exam_paper_id)).all())
    normalized = {}
    for key, value in answers.items():
        try:
            normalized[int(key)] = value
        except (TypeError, ValueError):
            continue
    for item in items:
        if item.id is None:
            continue
        latest = session.exec(
            select(UserAnswerAttempt)
            .where(UserAnswerAttempt.exam_paper_item_id == int(item.id), UserAnswerAttempt.user_id == runtime_user_id)
            .order_by(UserAnswerAttempt.attempt_no.desc())  # type: ignore[union-attr]
        ).first()
        session.add(
            UserAnswerAttempt(
                exam_paper_item_id=int(item.id),
                user_id=runtime_user_id,
                attempt_no=1 if latest is None else latest.attempt_no + 1,
                user_answer=normalized.get(int(item.id), normalized.get(item.item_order, "")),
            )
        )
    paper.status = ExamPaperStatus.SUBMITTED.value
    paper.submitted_at = utcnow()
    paper.updated_at = utcnow()
    session.add(paper)
    session.commit()
    return {"id": int(paper.id or 0), "status": paper.status}


def _upsert_state(
    session: Session,
    *,
    user_id: int,
    subject_id: int,
    granularity: str,
    target_id: int,
    is_correct: bool,
    now: datetime,
) -> UserKnowledgeState:
    state = session.exec(
        select(UserKnowledgeState).where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.subject_id == subject_id,
            UserKnowledgeState.granularity == granularity,
            UserKnowledgeState.target_id == target_id,
        )
    ).first()
    if state is None:
        state = UserKnowledgeState(user_id=user_id, subject_id=subject_id, granularity=granularity, target_id=target_id)
    state.total_attempts += 1
    state.correct_attempts += 1 if is_correct else 0
    state.mastery_score = state.correct_attempts / max(state.total_attempts, 1)
    state.confidence_score = min(1.0, 0.4 + state.total_attempts * 0.08)
    state.stability_score = min(1.0, 0.3 + state.correct_attempts * 0.1)
    state.forgetting_due_at = now + timedelta(days=max(1, int(14 * max(state.mastery_score, 0.2))))
    state.review_priority = round(1.0 - state.mastery_score, 4)
    state.last_attempt_at = now
    state.last_recomputed_at = now
    state.updated_at = now
    session.add(state)
    session.flush()
    return state


def _queue_review_task(session: Session, *, user_id: int, subject_id: int, granularity: str, target_id: int, priority: float, state_id: int | None, paper_id: int) -> int:
    existing = session.exec(
        select(ReviewTask).where(
            ReviewTask.user_id == user_id,
            ReviewTask.subject_id == subject_id,
            ReviewTask.status == "pending",
            ReviewTask.target_granularity == granularity,
            ReviewTask.target_id == target_id,
        )
    ).first()
    if existing is not None:
        existing.priority = max(existing.priority, priority)
        session.add(existing)
        return 0
    session.add(
        ReviewTask(
            user_id=user_id,
            subject_id=subject_id,
            task_type="review_unit" if granularity == "unit" else "review_node",
            target_id=target_id,
            target_granularity=granularity,
            priority=priority,
            scheduled_at=utcnow(),
            status="pending",
            interval_days=1,
            ease_factor=2.3,
            repetition_count=0,
            reason="repeated_wrong",
            source_state_id=state_id,
            source_exam_paper_id=paper_id,
        )
    )
    return 1


async def trigger_exam_grade(session: Session, *, exam_paper_id: int, regrade: bool = False) -> ExamGradeResult:
    del regrade
    paper = session.get(ExamPaper, exam_paper_id)
    if paper is None:
        _not_found(f"试卷 `{exam_paper_id}` 不存在。", "EXAM_PAPER_NOT_FOUND")
    if paper.status != ExamPaperStatus.SUBMITTED.value:
        _conflict(f"试卷 `{exam_paper_id}` 当前状态 `{paper.status}`，仅 submitted 可触发判卷。", "INVALID_EXAM_PAPER_STATUS")
    items = list(session.exec(select(ExamPaperItem).where(ExamPaperItem.exam_paper_id == exam_paper_id)).all())
    attempts = list(
        session.exec(
            select(UserAnswerAttempt)
            .where(UserAnswerAttempt.exam_paper_item_id.in_([int(item.id) for item in items if item.id is not None]))  # type: ignore[union-attr]
            .order_by(UserAnswerAttempt.exam_paper_item_id.asc(), UserAnswerAttempt.attempt_no.desc())  # type: ignore[union-attr]
        ).all()
    )
    latest = {}
    for attempt in attempts:
        latest.setdefault(attempt.exam_paper_item_id, attempt)
    now = utcnow()
    score = 0.0
    states_updated = 0
    tasks_created = 0
    for item in items:
        if item.id is None:
            continue
        attempt = latest.get(int(item.id))
        if attempt is None:
            continue
        correct = _normalize_answer(attempt.user_answer) == _normalize_answer(item.snapshot_answer)
        if item.snapshot_question_type == QuestionType.SHORT_ANSWER.value:
            correct_answer = _normalize_answer(item.snapshot_answer)
            user_answer = _normalize_answer(attempt.user_answer)
            correct = bool(correct_answer and user_answer and (correct_answer in user_answer or user_answer in correct_answer))
        attempt.is_correct = correct
        attempt.score_max = 1.0
        attempt.score_obtained = 1.0 if correct else 0.0
        attempt.error_cause_label = None if correct else "unknown"
        session.add(attempt)
        score += float(attempt.score_obtained or 0.0)
        unit_state = _upsert_state(session, user_id=paper.user_id, subject_id=paper.subject_id, granularity="unit", target_id=item.snapshot_teaching_unit_id, is_correct=correct, now=now)
        states_updated += 1
        if not correct:
            tasks_created += _queue_review_task(session, user_id=paper.user_id, subject_id=paper.subject_id, granularity="unit", target_id=item.snapshot_teaching_unit_id, priority=max(0.6, unit_state.review_priority), state_id=int(unit_state.id or 0), paper_id=int(paper.id or 0))
        for node_link in _parse_json_list(item.snapshot_node_links_json):
            node_id = int(node_link.get("knowledge_node_id", 0))
            if node_id <= 0:
                continue
            node_state = _upsert_state(session, user_id=paper.user_id, subject_id=paper.subject_id, granularity="node", target_id=node_id, is_correct=correct, now=now)
            states_updated += 1
            if not correct:
                tasks_created += _queue_review_task(session, user_id=paper.user_id, subject_id=paper.subject_id, granularity="node", target_id=node_id, priority=max(0.6, node_state.review_priority), state_id=int(node_state.id or 0), paper_id=int(paper.id or 0))
    paper.status = ExamPaperStatus.GRADED.value
    paper.graded_at = now
    paper.updated_at = now
    paper.total_score = float(len(items))
    paper.score_obtained = score
    session.add(paper)
    session.commit()
    return ExamGradeResult(_job_id(), "completed", None, now, now, exam_paper_id, score, states_updated, tasks_created, False)


async def get_exam_grade_job_status(session: Session, *, subject: str, job_id: int, user_id: str) -> ExamGradeResult:
    del session, subject, user_id
    _not_found(f"判卷任务 `{job_id}` 不存在（ExamGradeJob 已移除）。", "EXAM_GRADE_JOB_NOT_FOUND")


async def get_exam_history(session: Session, *, subject: str, user_id: str, page: int, size: int) -> PaginatedData[dict[str, object]]:
    subject_record, runtime_user_id = _subject_user(session, subject, user_id)
    rows = list(
        session.exec(
            select(ExamPaper)
            .where(ExamPaper.subject_id == int(subject_record.id or 0), ExamPaper.user_id == runtime_user_id)
            .order_by(ExamPaper.created_at.desc())  # type: ignore[union-attr]
        ).all()
    )
    payload = [
        {
            "id": int(row.id or 0),
            "subject": subject,
            "user_id": user_id,
            "exam_mode": row.exam_mode,
            "status": row.status,
            "total_items": row.total_items,
            "score_obtained": row.score_obtained,
            "total_score": row.total_score,
            "created_at": row.created_at,
            "submitted_at": row.submitted_at,
            "graded_at": row.graded_at,
        }
        for row in rows[(page - 1) * size : (page - 1) * size + size]
    ]
    return build_paginated_data(items=payload, page=page, size=size, total=len(rows))


async def get_question_bank(session: Session, *, subject: str, user_id: str) -> list[QuestionBankItem]:
    subject_record, runtime_user_id = _subject_user(session, subject, user_id)
    papers = {
        int(paper.id): paper
        for paper in session.exec(
            select(ExamPaper).where(ExamPaper.subject_id == int(subject_record.id or 0), ExamPaper.user_id == runtime_user_id)
        ).all()
        if paper.id is not None
    }
    if not papers:
        return []
    items = list(session.exec(select(ExamPaperItem).where(ExamPaperItem.exam_paper_id.in_(list(papers.keys())))).all())  # type: ignore[union-attr]
    agg: dict[int, QuestionBankItem] = {}
    for item in items:
        asked_at = papers[item.exam_paper_id].created_at
        template_id = int(item.question_template_id)
        current = agg.get(template_id)
        if current is None:
            agg[template_id] = QuestionBankItem(template_id, item.snapshot_stem, item.snapshot_question_type, item.snapshot_difficulty, item.snapshot_teaching_unit_id, 1, asked_at, item.exam_paper_id)
            continue
        agg[template_id] = QuestionBankItem(template_id, current.stem, current.question_type, current.difficulty, current.teaching_unit_id, current.times_asked + 1, max(current.last_asked_at, asked_at), item.exam_paper_id if asked_at >= current.last_asked_at else current.last_exam_paper_id)
    return sorted(agg.values(), key=lambda item: item.last_asked_at, reverse=True)


async def delete_exam_paper(session: Session, *, subject: str, user_id: str, exam_paper_id: int) -> None:
    _, _, paper = _load_paper(session, subject=subject, user_id=user_id, exam_paper_id=exam_paper_id)
    items = list(session.exec(select(ExamPaperItem).where(ExamPaperItem.exam_paper_id == exam_paper_id)).all())
    item_ids = [int(item.id) for item in items if item.id is not None]
    if item_ids:
        for attempt in session.exec(select(UserAnswerAttempt).where(UserAnswerAttempt.exam_paper_item_id.in_(item_ids))).all():  # type: ignore[union-attr]
            session.delete(attempt)
    for task in session.exec(select(ReviewTask).where(ReviewTask.source_exam_paper_id == exam_paper_id)).all():
        session.delete(task)
    for item in items:
        session.delete(item)
    session.delete(paper)
    session.commit()


async def get_exam_paper_detail(session: Session, *, subject: str, user_id: str, exam_paper_id: int) -> ExamPaperDetail:
    _, runtime_user_id, paper = _load_paper(session, subject=subject, user_id=user_id, exam_paper_id=exam_paper_id)
    items = list(
        session.exec(
            select(ExamPaperItem).where(ExamPaperItem.exam_paper_id == exam_paper_id).order_by(ExamPaperItem.item_order.asc())  # type: ignore[union-attr]
        ).all()
    )
    attempts = list(
        session.exec(
            select(UserAnswerAttempt)
            .where(
                UserAnswerAttempt.exam_paper_item_id.in_([int(item.id) for item in items if item.id is not None]),  # type: ignore[union-attr]
                UserAnswerAttempt.user_id == runtime_user_id,
            )
            .order_by(UserAnswerAttempt.exam_paper_item_id.asc(), UserAnswerAttempt.attempt_no.desc())  # type: ignore[union-attr]
        ).all()
    )
    latest = {}
    for attempt in attempts:
        latest.setdefault(attempt.exam_paper_item_id, attempt)
    return ExamPaperDetail(
        paper={
            "id": int(paper.id or 0),
            "subject": subject,
            "user_id": user_id,
            "exam_mode": paper.exam_mode,
            "status": paper.status,
            "total_items": paper.total_items,
            "score_obtained": paper.score_obtained,
            "total_score": paper.total_score,
            "submitted_at": paper.submitted_at,
            "graded_at": paper.graded_at,
            "created_at": paper.created_at,
        },
        items=[
            {
                "id": int(item.id or 0),
                "item_order": item.item_order,
                "question_template_id": item.question_template_id,
                "question_type": item.snapshot_question_type,
                "difficulty": item.snapshot_difficulty,
                "stem": item.snapshot_stem,
                "options": [str(option) for option in _parse_json_list(item.snapshot_options)] or None,
                "explanation": item.snapshot_explanation,
                "teaching_unit_id": item.snapshot_teaching_unit_id,
                "node_links": _parse_json_list(item.snapshot_node_links_json),
                "user_answer": latest[int(item.id or 0)].user_answer if int(item.id or 0) in latest else None,
                "is_correct": latest[int(item.id or 0)].is_correct if int(item.id or 0) in latest else None,
                "score_obtained": latest[int(item.id or 0)].score_obtained if int(item.id or 0) in latest else None,
                "score_max": latest[int(item.id or 0)].score_max if int(item.id or 0) in latest else None,
                "error_cause_label": latest[int(item.id or 0)].error_cause_label if int(item.id or 0) in latest else None,
            }
            for item in items
        ],
    )
