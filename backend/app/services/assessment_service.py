"""Assessment 服务编排层。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from http import HTTPStatus

from sqlmodel import Session, select

from app.agents.examine.exam_grade_workflow import ExamGradeWorkflow
from app.agents.examine.paper_assembler import assemble_paper
from app.agents.examine.question_build_workflow import QuestionBuildWorkflow
from app.core.exceptions import AITeachMeError, NoPublishedCurriculumSnapshotError
from app.models import (
    ExamGenerateJob,
    ExamGradeJob,
    ExamMode,
    ExamPaper,
    ExamPaperItem,
    ExamPaperStatus,
    QuestionBuildJob,
    ReviewTask,
    UserAnswerAttempt,
    UserKnowledgeState,
    validate_status_transition,
)
from app.repositories import assessment_repo
from app.schemas.common import PaginatedData, build_paginated_data
from app.utils.time import utcnow


@dataclass(frozen=True)
class MasteryOverview:
    subject: str
    user_id: str
    unit_states: list[UserKnowledgeState]
    node_states: list[UserKnowledgeState]
    weak_unit_count: int
    weak_node_count: int


@dataclass(frozen=True)
class ExamPaperDetail:
    paper: ExamPaper
    items: list[ExamPaperItem]
    attempts_by_item_id: dict[int, UserAnswerAttempt]


def _raise_not_found(detail: str, *, error_code: str = "NOT_FOUND") -> None:
    raise AITeachMeError(
        detail=detail,
        status_code=HTTPStatus.NOT_FOUND,
        error_code=error_code,
    )


def _raise_conflict(detail: str, *, error_code: str = "CONFLICT") -> None:
    raise AITeachMeError(
        detail=detail,
        status_code=HTTPStatus.CONFLICT,
        error_code=error_code,
    )


def _normalize_answers_payload(
    *,
    answers: dict[int | str, str],
) -> dict[int, str]:
    normalized: dict[int, str] = {}
    for raw_key, value in answers.items():
        try:
            key = int(raw_key)
        except (TypeError, ValueError):
            continue
        normalized[key] = value
    return normalized


async def trigger_question_build(
    session: Session,
    *,
    subject: str,
    unit_ids: list[int],
    questions_per_unit: int,
) -> QuestionBuildJob:
    """创建 QuestionBuildJob 并执行 QuestionBuildWorkflow。"""

    job = assessment_repo.create_question_build_job(
        session,
        QuestionBuildJob(
            subject=subject,
            target_unit_ids_json=json.dumps(sorted(set(unit_ids))),
            questions_per_unit=max(1, int(questions_per_unit)),
            status="pending",
            progress=0,
            templates_created=0,
            warnings_json="[]",
            created_at=utcnow(),
            updated_at=utcnow(),
        ),
    )

    try:
        await QuestionBuildWorkflow.run(
            subject=subject,
            unit_ids=unit_ids,
            questions_per_unit=max(1, int(questions_per_unit)),
            job_id=job.id or 0,
            session=session,
        )
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error_message = str(exc)
        job.updated_at = utcnow()
        session.add(job)
        session.commit()
        session.refresh(job)
    return job


async def get_question_build_job_status(
    session: Session,
    *,
    subject: str,
    job_id: int,
) -> QuestionBuildJob:
    job = assessment_repo.get_question_build_job(session, job_id)
    if job is None or job.subject != subject:
        _raise_not_found(
            f"题目构建任务 `{job_id}` 不存在。",
            error_code="QUESTION_BUILD_JOB_NOT_FOUND",
        )
    return job


async def trigger_exam_generate(
    session: Session,
    *,
    subject: str,
    user_id: str,
    exam_mode: ExamMode | str,
    num_questions: int,
    theme_tree_node_id: int | None = None,
    teaching_unit_ids: list[int] | None = None,
) -> ExamGenerateJob:
    """创建 ExamGenerateJob 并组卷。"""

    job = assessment_repo.create_exam_generate_job(
        session,
        ExamGenerateJob(
            subject=subject,
            user_id=user_id,
            exam_mode=(exam_mode.value if isinstance(exam_mode, ExamMode) else str(exam_mode)),
            num_questions=max(1, int(num_questions)),
            status="pending",
            exam_paper_id=None,
            theme_tree_node_id=theme_tree_node_id,
            teaching_unit_ids_json=json.dumps(teaching_unit_ids or []),
            created_at=utcnow(),
            updated_at=utcnow(),
        ),
    )

    snapshot = assessment_repo.get_published_curriculum_snapshot(session, subject)
    if snapshot is None:
        job.status = "failed"
        job.error_message = NoPublishedCurriculumSnapshotError(subject).detail
        job.updated_at = utcnow()
        session.add(job)
        session.commit()
        session.refresh(job)
        return job

    try:
        job.status = "running"
        job.updated_at = utcnow()
        session.add(job)
        session.commit()

        paper = assemble_paper(
            session,
            subject=subject,
            user_id=user_id,
            exam_mode=exam_mode,
            num_questions=max(1, int(num_questions)),
            theme_tree_node_id=theme_tree_node_id,
            teaching_unit_ids=teaching_unit_ids,
        )
        job.exam_paper_id = paper.id
        job.status = "completed"
        job.error_message = None
        job.updated_at = utcnow()
        session.add(job)
        session.commit()
        session.refresh(job)
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error_message = str(exc)
        job.updated_at = utcnow()
        session.add(job)
        session.commit()
        session.refresh(job)

    return job


async def get_exam_generate_job_status(
    session: Session,
    *,
    subject: str,
    job_id: int,
    user_id: str,
) -> ExamGenerateJob:
    job = assessment_repo.get_exam_generate_job(session, job_id)
    if job is None or job.subject != subject or job.user_id != user_id:
        _raise_not_found(
            f"组卷任务 `{job_id}` 不存在。",
            error_code="EXAM_GENERATE_JOB_NOT_FOUND",
        )
    return job


async def submit_exam_answers(
    session: Session,
    *,
    subject: str,
    exam_paper_id: int,
    user_id: str,
    answers: dict[int | str, str],
) -> ExamPaper:
    """提交答案（仅落库，不触发判卷）。"""

    paper = assessment_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.subject != subject:
        _raise_not_found(f"试卷 `{exam_paper_id}` 不存在。", error_code="EXAM_PAPER_NOT_FOUND")
    if paper.user_id != user_id:
        _raise_conflict(
            f"用户 `{user_id}` 无权提交试卷 `{exam_paper_id}`。",
            error_code="EXAM_PAPER_USER_MISMATCH",
        )

    if paper.status in {"submitted", "grading", "graded"}:
        _raise_conflict(
            f"试卷 `{exam_paper_id}` 当前状态 `{paper.status}`，不允许重复提交。",
            error_code="EXAM_ALREADY_SUBMITTED",
        )
    if paper.status not in {"ready", "in_progress"}:
        _raise_conflict(
            f"试卷 `{exam_paper_id}` 当前状态 `{paper.status}`，不可提交。",
            error_code="INVALID_EXAM_PAPER_STATUS",
        )

    items = list(
        session.exec(
            select(ExamPaperItem).where(ExamPaperItem.exam_paper_id == exam_paper_id).order_by(ExamPaperItem.item_order)
        ).all()
    )
    answer_map = _normalize_answers_payload(answers=answers)

    if paper.status == "ready":
        # 服务层未暴露 start 接口，提交时补齐 ready -> in_progress -> submitted 迁移链
        validate_status_transition(ExamPaperStatus.READY, ExamPaperStatus.IN_PROGRESS)
        paper.status = "in_progress"

    validate_status_transition(ExamPaperStatus.IN_PROGRESS, ExamPaperStatus.SUBMITTED)

    attempts: list[UserAnswerAttempt] = []
    for item in items:
        if item.id is None:
            continue
        answer_text = answer_map.get(item.id)
        if answer_text is None:
            answer_text = answer_map.get(item.item_order, "")
        attempts.append(
            UserAnswerAttempt(
                exam_paper_item_id=item.id,
                user_id=user_id,
                attempt_no=1,
                user_answer=answer_text,
                created_at=utcnow(),
            )
        )

    if attempts:
        assessment_repo.create_answer_attempts(session, attempts)

    paper.status = "submitted"
    paper.submitted_at = utcnow()
    paper.updated_at = utcnow()
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


def _reset_attempts_for_regrade(session: Session, exam_paper_id: int) -> None:
    attempts = assessment_repo.list_attempts_by_paper(session, exam_paper_id)
    for attempt in attempts:
        attempt.is_correct = None
        attempt.score_obtained = None
        attempt.score_max = None
        attempt.error_cause_label = None
        session.add(attempt)
    session.commit()


async def trigger_exam_grade(
    session: Session,
    *,
    exam_paper_id: int,
    regrade: bool = False,
) -> ExamGradeJob:
    """触发判卷（提交与判卷解耦）。"""

    paper = assessment_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None:
        _raise_not_found(f"试卷 `{exam_paper_id}` 不存在。", error_code="EXAM_PAPER_NOT_FOUND")

    active_job = assessment_repo.find_active_grade_job(session, exam_paper_id)
    if active_job is not None:
        _raise_conflict(
            f"试卷 `{exam_paper_id}` 已有执行中的判卷任务 `{active_job.id}`。",
            error_code="EXAM_GRADE_JOB_CONFLICT",
        )

    if paper.status == "graded":
        if not regrade:
            _raise_conflict(
                f"试卷 `{exam_paper_id}` 已判分，需传 `regrade=true` 才可重判。",
                error_code="EXAM_ALREADY_GRADED",
            )
        _reset_attempts_for_regrade(session, exam_paper_id)
        paper.status = "submitted"
        paper.graded_at = None
        paper.updated_at = utcnow()
        session.add(paper)
        session.commit()
        session.refresh(paper)

    if paper.status != "submitted":
        _raise_conflict(
            f"试卷 `{exam_paper_id}` 当前状态 `{paper.status}`，仅 submitted 可触发判卷。",
            error_code="INVALID_EXAM_PAPER_STATUS",
        )

    job = assessment_repo.create_exam_grade_job(
        session,
        ExamGradeJob(
            exam_paper_id=exam_paper_id,
            status="pending",
            mastery_consumed=bool(regrade),
            created_at=utcnow(),
            updated_at=utcnow(),
        ),
    )

    try:
        await ExamGradeWorkflow.run(
            exam_paper_id=exam_paper_id,
            job_id=job.id or 0,
            session=session,
        )
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error_message = str(exc)
        job.updated_at = utcnow()
        session.add(job)
        session.commit()
        session.refresh(job)

    return job


async def get_exam_grade_job_status(
    session: Session,
    *,
    subject: str,
    job_id: int,
    user_id: str,
) -> ExamGradeJob:
    job = assessment_repo.get_exam_grade_job(session, job_id)
    if job is None:
        _raise_not_found(f"判卷任务 `{job_id}` 不存在。", error_code="EXAM_GRADE_JOB_NOT_FOUND")
    paper = assessment_repo.get_exam_paper_by_id(session, job.exam_paper_id)
    if paper is None or paper.subject != subject or paper.user_id != user_id:
        _raise_not_found(f"判卷任务 `{job_id}` 不存在。", error_code="EXAM_GRADE_JOB_NOT_FOUND")
    return job


async def get_exam_history(
    session: Session,
    *,
    subject: str,
    user_id: str,
    page: int,
    size: int,
) -> PaginatedData[ExamPaper]:
    rows, total = assessment_repo.list_exam_papers(
        session,
        subject=subject,
        user_id=user_id,
        limit=size,
        offset=(page - 1) * size,
    )
    return build_paginated_data(items=rows, page=page, size=size, total=total)


async def get_exam_paper_detail(
    session: Session,
    *,
    subject: str,
    user_id: str,
    exam_paper_id: int,
) -> ExamPaperDetail:
    paper = assessment_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.subject != subject or paper.user_id != user_id:
        _raise_not_found(f"试卷 `{exam_paper_id}` 不存在。", error_code="EXAM_PAPER_NOT_FOUND")

    items = list(
        session.exec(
            select(ExamPaperItem)
            .where(ExamPaperItem.exam_paper_id == exam_paper_id)
            .order_by(ExamPaperItem.item_order)
        ).all()
    )
    attempts = assessment_repo.list_attempts_by_paper(session, exam_paper_id)
    attempts_by_item_id: dict[int, UserAnswerAttempt] = {}
    for attempt in attempts:
        current = attempts_by_item_id.get(attempt.exam_paper_item_id)
        if current is None or attempt.attempt_no > current.attempt_no:
            attempts_by_item_id[attempt.exam_paper_item_id] = attempt

    return ExamPaperDetail(paper=paper, items=items, attempts_by_item_id=attempts_by_item_id)


async def get_mastery_overview(
    session: Session,
    *,
    subject: str,
    user_id: str,
) -> MasteryOverview:
    states = assessment_repo.list_knowledge_states(session, user_id=user_id, subject=subject)
    unit_states = [item for item in states if item.granularity == "unit"]
    node_states = [item for item in states if item.granularity == "node"]
    return MasteryOverview(
        subject=subject,
        user_id=user_id,
        unit_states=unit_states,
        node_states=node_states,
        weak_unit_count=sum(1 for item in unit_states if item.mastery_score < 0.8),
        weak_node_count=sum(1 for item in node_states if item.mastery_score < 0.8),
    )


async def get_mastery_detail(
    session: Session,
    *,
    subject: str,
    user_id: str,
    target_id: int,
    granularity: str,
) -> UserKnowledgeState:
    state = assessment_repo.get_knowledge_state(
        session,
        user_id=user_id,
        subject=subject,
        granularity=granularity,
        target_id=target_id,
    )
    if state is None:
        _raise_not_found(
            f"未找到掌握度记录：user_id={user_id}, subject={subject}, granularity={granularity}, target_id={target_id}。",
            error_code="MASTERY_STATE_NOT_FOUND",
        )
    return state


async def get_review_tasks(
    session: Session,
    *,
    subject: str,
    user_id: str,
) -> list[ReviewTask]:
    return assessment_repo.list_pending_reviews(session, user_id=user_id, subject=subject)


async def complete_review_task(
    session: Session,
    *,
    task_id: int,
    user_id: str,
) -> ReviewTask:
    task = assessment_repo.complete_review_task(session, task_id=task_id, user_id=user_id)
    if task is None:
        _raise_not_found(f"复习任务 `{task_id}` 不存在。", error_code="REVIEW_TASK_NOT_FOUND")
    return task
