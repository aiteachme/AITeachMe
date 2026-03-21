"""测评与掌握度数据访问层。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, func, select

from app.models import (
    CurriculumSnapshot,
    ExamGenerateJob,
    ExamGradeJob,
    ExamPaper,
    ExamPaperGenerationContext,
    ExamPaperItem,
    PrereqDagVersion,
    QuestionBuildJob,
    QuestionTemplate,
    QuestionTemplateNodeLink,
    ReviewTask,
    TeachingUnit,
    UnitDependency,
    UnitTreeMembership,
    UserAnswerAttempt,
    UserKnowledgeState,
)
from app.repositories.knowledge import curriculum_repo
from app.utils.time import utcnow


# ---------------------------------------------------------------------------
# QuestionTemplate CRUD
# ---------------------------------------------------------------------------


def create_question_template(
    session: Session,
    template: QuestionTemplate,
) -> QuestionTemplate:
    """创建题目模板。"""

    session.add(template)
    session.commit()
    session.refresh(template)
    return template


def create_template_node_links(
    session: Session,
    links: list[QuestionTemplateNodeLink],
) -> list[QuestionTemplateNodeLink]:
    """批量创建模板-知识节点关联。"""

    for item in links:
        session.add(item)
    session.commit()
    for item in links:
        session.refresh(item)
    return links


def find_templates_by_unit(
    session: Session,
    unit_id: int,
    *,
    status: str = "active",
) -> list[QuestionTemplate]:
    """按教学单元查询题目模板。"""

    stmt = select(QuestionTemplate).where(QuestionTemplate.teaching_unit_id == unit_id)
    if status:
        stmt = stmt.where(QuestionTemplate.status == status)
    return list(session.exec(stmt.order_by(QuestionTemplate.id)).all())


def find_templates_by_node(
    session: Session,
    node_id: int,
    *,
    status: str = "active",
) -> list[QuestionTemplate]:
    """按知识节点查询题目模板。"""

    stmt = (
        select(QuestionTemplate)
        .join(
            QuestionTemplateNodeLink,
            QuestionTemplateNodeLink.question_template_id == QuestionTemplate.id,
        )
        .where(QuestionTemplateNodeLink.knowledge_node_id == node_id)
    )
    if status:
        stmt = stmt.where(QuestionTemplate.status == status)
    return list(session.exec(stmt.distinct().order_by(QuestionTemplate.id)).all())


def find_template_by_stem_hash(
    session: Session,
    subject: str,
    unit_id: int,
    stem_hash: str,
) -> QuestionTemplate | None:
    """按题干哈希查询模板。"""

    stmt = select(QuestionTemplate).where(
        QuestionTemplate.subject == subject,
        QuestionTemplate.teaching_unit_id == unit_id,
        QuestionTemplate.stem_hash == stem_hash,
    )
    return session.exec(stmt).first()


def find_node_links_by_template(
    session: Session,
    template_id: int,
) -> list[QuestionTemplateNodeLink]:
    """查询模板关联的知识节点映射。"""

    stmt = select(QuestionTemplateNodeLink).where(
        QuestionTemplateNodeLink.question_template_id == template_id
    )
    return list(session.exec(stmt.order_by(QuestionTemplateNodeLink.id)).all())


# ---------------------------------------------------------------------------
# ExamPaper CRUD
# ---------------------------------------------------------------------------


def create_exam_paper(session: Session, paper: ExamPaper) -> ExamPaper:
    """创建试卷。"""

    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


def create_exam_paper_items(
    session: Session,
    items: list[ExamPaperItem],
) -> list[ExamPaperItem]:
    """批量创建试卷题目条目。"""

    for item in items:
        session.add(item)
    session.commit()
    for item in items:
        session.refresh(item)
    return items


def create_generation_context(
    session: Session,
    ctx: ExamPaperGenerationContext,
) -> ExamPaperGenerationContext:
    """创建组卷上下文。"""

    session.add(ctx)
    session.commit()
    session.refresh(ctx)
    return ctx


def get_exam_paper_by_id(session: Session, paper_id: int) -> ExamPaper | None:
    """按 ID 查询试卷。"""

    return session.get(ExamPaper, paper_id)


def list_exam_papers(
    session: Session,
    *,
    subject: str,
    user_id: str,
    limit: int,
    offset: int,
) -> tuple[list[ExamPaper], int]:
    """分页查询用户试卷。"""

    total = session.exec(
        select(func.count())
        .select_from(ExamPaper)
        .where(ExamPaper.subject == subject, ExamPaper.user_id == user_id)
    ).one()
    rows = list(
        session.exec(
            select(ExamPaper)
            .where(ExamPaper.subject == subject, ExamPaper.user_id == user_id)
            .order_by(ExamPaper.created_at.desc())  # type: ignore[union-attr]
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return rows, total


def list_teaching_unit_ids_by_subject(
    session: Session,
    *,
    subject: str,
    status: str | None = "active",
) -> list[int]:
    """按学科查询教学单元 ID。"""

    stmt = select(TeachingUnit.id).where(TeachingUnit.subject == subject)
    if status is not None:
        stmt = stmt.where(TeachingUnit.status == status)
    stmt = stmt.order_by(TeachingUnit.id)
    return [int(item) for item in session.exec(stmt).all() if item is not None]


def count_active_question_templates(
    session: Session,
    *,
    subject: str,
    question_types: set[str] | None = None,
) -> int:
    """统计学科下可用题模板数量。"""

    stmt = (
        select(func.count())
        .select_from(QuestionTemplate)
        .where(
            QuestionTemplate.subject == subject,
            QuestionTemplate.status == "active",
        )
    )
    if question_types:
        stmt = stmt.where(QuestionTemplate.question_type.in_(question_types))  # type: ignore[union-attr]
    return int(session.exec(stmt).one())


def list_exam_item_snapshots_by_user(
    session: Session,
    *,
    subject: str,
    user_id: str,
) -> list[tuple[ExamPaperItem, datetime, int]]:
    """查询用户在学科下所有出过的题目快照。"""

    stmt = (
        select(ExamPaperItem, ExamPaper.created_at, ExamPaper.id)
        .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
        .where(
            ExamPaper.subject == subject,
            ExamPaper.user_id == user_id,
        )
        .order_by(ExamPaper.created_at.desc(), ExamPaper.id.desc(), ExamPaperItem.item_order.asc())  # type: ignore[union-attr]
    )
    rows = list(session.exec(stmt).all())
    normalized: list[tuple[ExamPaperItem, datetime, int]] = []
    for row in rows:
        item, asked_at, exam_paper_id = row
        normalized.append((item, asked_at, int(exam_paper_id)))
    return normalized


def delete_exam_paper_cascade(
    session: Session,
    *,
    paper_id: int,
) -> bool:
    """删除试卷及其关联数据。"""

    paper = session.get(ExamPaper, paper_id)
    if paper is None:
        return False

    item_ids = [
        int(item_id)
        for item_id in session.exec(
            select(ExamPaperItem.id).where(ExamPaperItem.exam_paper_id == paper_id)
        ).all()
        if item_id is not None
    ]

    if item_ids:
        attempts = list(
            session.exec(
                select(UserAnswerAttempt).where(UserAnswerAttempt.exam_paper_item_id.in_(item_ids))  # type: ignore[union-attr]
            ).all()
        )
        for item in attempts:
            session.delete(item)

        paper_items = list(
            session.exec(
                select(ExamPaperItem).where(ExamPaperItem.id.in_(item_ids))  # type: ignore[union-attr]
            ).all()
        )
        for item in paper_items:
            session.delete(item)

    generation_contexts = list(
        session.exec(
            select(ExamPaperGenerationContext).where(ExamPaperGenerationContext.exam_paper_id == paper_id)
        ).all()
    )
    for item in generation_contexts:
        session.delete(item)

    grade_jobs = list(
        session.exec(select(ExamGradeJob).where(ExamGradeJob.exam_paper_id == paper_id)).all()
    )
    for item in grade_jobs:
        session.delete(item)

    generate_jobs = list(
        session.exec(select(ExamGenerateJob).where(ExamGenerateJob.exam_paper_id == paper_id)).all()
    )
    for item in generate_jobs:
        session.delete(item)

    review_tasks = list(
        session.exec(select(ReviewTask).where(ReviewTask.source_exam_paper_id == paper_id)).all()
    )
    for item in review_tasks:
        session.delete(item)

    session.delete(paper)
    session.commit()
    return True


# ---------------------------------------------------------------------------
# UserAnswerAttempt CRUD
# ---------------------------------------------------------------------------


def create_answer_attempts(
    session: Session,
    attempts: list[UserAnswerAttempt],
) -> list[UserAnswerAttempt]:
    """批量创建作答记录。"""

    for item in attempts:
        session.add(item)
    session.commit()
    for item in attempts:
        session.refresh(item)
    return attempts


def list_attempts_by_paper(
    session: Session,
    paper_id: int,
) -> list[UserAnswerAttempt]:
    """查询试卷下全部作答记录。"""

    stmt = (
        select(UserAnswerAttempt)
        .join(
            ExamPaperItem,
            UserAnswerAttempt.exam_paper_item_id == ExamPaperItem.id,
        )
        .where(ExamPaperItem.exam_paper_id == paper_id)
        .order_by(UserAnswerAttempt.id)
    )
    return list(session.exec(stmt).all())


# ---------------------------------------------------------------------------
# UserKnowledgeState CRUD
# ---------------------------------------------------------------------------


def upsert_knowledge_state(
    session: Session,
    state: UserKnowledgeState,
) -> UserKnowledgeState:
    """按唯一键 upsert 用户知识状态。"""

    now = utcnow()
    insert_values = {
        "user_id": state.user_id,
        "subject": state.subject,
        "granularity": state.granularity,
        "target_id": state.target_id,
        "mastery_score": state.mastery_score,
        "confidence_score": state.confidence_score,
        "stability_score": state.stability_score,
        "forgetting_due_at": state.forgetting_due_at,
        "review_priority": state.review_priority,
        "total_attempts": state.total_attempts,
        "correct_attempts": state.correct_attempts,
        "last_attempt_at": state.last_attempt_at,
        "state_version": state.state_version,
        "last_recomputed_at": state.last_recomputed_at,
        "updated_at": now,
    }

    stmt = sqlite_insert(UserKnowledgeState).values(**insert_values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "subject", "granularity", "target_id"],
        set_={
            "mastery_score": insert_values["mastery_score"],
            "confidence_score": insert_values["confidence_score"],
            "stability_score": insert_values["stability_score"],
            "forgetting_due_at": insert_values["forgetting_due_at"],
            "review_priority": insert_values["review_priority"],
            "total_attempts": insert_values["total_attempts"],
            "correct_attempts": insert_values["correct_attempts"],
            "last_attempt_at": insert_values["last_attempt_at"],
            "state_version": insert_values["state_version"],
            "last_recomputed_at": insert_values["last_recomputed_at"],
            "updated_at": insert_values["updated_at"],
        },
    )

    session.exec(stmt)
    session.commit()
    persisted = get_knowledge_state(
        session,
        user_id=state.user_id,
        subject=state.subject,
        granularity=state.granularity,
        target_id=state.target_id,
    )
    if persisted is None:
        raise ValueError("UserKnowledgeState upsert failed.")
    return persisted


def get_knowledge_state(
    session: Session,
    *,
    user_id: str,
    subject: str,
    granularity: str,
    target_id: int,
) -> UserKnowledgeState | None:
    """按唯一键查询知识状态。"""

    stmt = select(UserKnowledgeState).where(
        UserKnowledgeState.user_id == user_id,
        UserKnowledgeState.subject == subject,
        UserKnowledgeState.granularity == granularity,
        UserKnowledgeState.target_id == target_id,
    )
    return session.exec(stmt).first()


def list_knowledge_states(
    session: Session,
    *,
    user_id: str,
    subject: str,
    granularity: str | None = None,
) -> list[UserKnowledgeState]:
    """查询知识状态列表。"""

    stmt = select(UserKnowledgeState).where(
        UserKnowledgeState.user_id == user_id,
        UserKnowledgeState.subject == subject,
    )
    if granularity is not None:
        stmt = stmt.where(UserKnowledgeState.granularity == granularity)
    return list(session.exec(stmt.order_by(UserKnowledgeState.updated_at.desc())).all())  # type: ignore[union-attr]


def list_weak_knowledge_states(
    session: Session,
    *,
    user_id: str,
    subject: str,
    threshold: float = 0.8,
) -> list[UserKnowledgeState]:
    """查询薄弱知识状态（mastery_score < threshold）。"""

    stmt = (
        select(UserKnowledgeState)
        .where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.subject == subject,
            UserKnowledgeState.mastery_score < threshold,  # type: ignore[operator]
        )
        .order_by(UserKnowledgeState.mastery_score.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


def list_due_knowledge_states(
    session: Session,
    *,
    user_id: str,
    subject: str,
    as_of: datetime,
) -> list[UserKnowledgeState]:
    """查询到期复习知识状态（forgetting_due_at <= as_of）。"""

    stmt = (
        select(UserKnowledgeState)
        .where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.subject == subject,
            UserKnowledgeState.forgetting_due_at.is_not(None),  # type: ignore[union-attr]
            UserKnowledgeState.forgetting_due_at <= as_of,  # type: ignore[operator]
        )
        .order_by(UserKnowledgeState.forgetting_due_at.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


# ---------------------------------------------------------------------------
# ReviewTask CRUD
# ---------------------------------------------------------------------------


def upsert_review_task(
    session: Session,
    task: ReviewTask,
) -> ReviewTask:
    """创建或更新复习任务。

    说明：受限于 SQLite 部分唯一索引声明式 upsert 支持，本函数采用
    事务内 select + update-or-insert 语义，保证同一 target 的 pending 去重。
    """

    if task.status == "pending":
        existing = find_pending_review(
            session,
            user_id=task.user_id,
            subject=task.subject,
            target_id=task.target_id,
            target_granularity=task.target_granularity,
        )
        if existing is not None:
            existing.task_type = task.task_type
            existing.priority = task.priority
            existing.scheduled_at = task.scheduled_at
            existing.interval_days = task.interval_days
            existing.ease_factor = task.ease_factor
            existing.repetition_count = task.repetition_count
            existing.reason = task.reason
            existing.source_state_id = task.source_state_id
            existing.source_exam_paper_id = task.source_exam_paper_id
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing

    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def find_pending_review(
    session: Session,
    *,
    user_id: str,
    subject: str,
    target_id: int,
    target_granularity: str,
) -> ReviewTask | None:
    """查询目标上的 pending 复习任务。"""

    stmt = select(ReviewTask).where(
        ReviewTask.user_id == user_id,
        ReviewTask.subject == subject,
        ReviewTask.target_id == target_id,
        ReviewTask.target_granularity == target_granularity,
        ReviewTask.status == "pending",
    )
    return session.exec(stmt).first()


def list_pending_reviews(
    session: Session,
    *,
    user_id: str,
    subject: str,
) -> list[ReviewTask]:
    """按优先级查询待处理复习任务。"""

    stmt = (
        select(ReviewTask)
        .where(
            ReviewTask.user_id == user_id,
            ReviewTask.subject == subject,
            ReviewTask.status == "pending",
        )
        .order_by(
            ReviewTask.priority.desc(),  # type: ignore[union-attr]
            ReviewTask.scheduled_at.asc(),  # type: ignore[union-attr]
            ReviewTask.id.asc(),  # type: ignore[union-attr]
        )
    )
    return list(session.exec(stmt).all())


def complete_review_task(
    session: Session,
    *,
    task_id: int,
    user_id: str,
    subject: str,
) -> ReviewTask | None:
    """标记复习任务完成。"""

    stmt = select(ReviewTask).where(
        ReviewTask.id == task_id,
        ReviewTask.user_id == user_id,
        ReviewTask.subject == subject,
    )
    task = session.exec(stmt).first()
    if task is None:
        return None

    task.status = "completed"
    task.completed_at = utcnow()
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


# ---------------------------------------------------------------------------
# Job CRUD
# ---------------------------------------------------------------------------


def create_question_build_job(session: Session, job: QuestionBuildJob) -> QuestionBuildJob:
    """创建题目构建任务。"""

    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def create_exam_generate_job(session: Session, job: ExamGenerateJob) -> ExamGenerateJob:
    """创建组卷任务。"""

    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def create_exam_grade_job(session: Session, job: ExamGradeJob) -> ExamGradeJob:
    """创建判卷任务。"""

    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def get_question_build_job(session: Session, job_id: int) -> QuestionBuildJob | None:
    """查询题目构建任务。"""

    return session.get(QuestionBuildJob, job_id)


def get_exam_generate_job(session: Session, job_id: int) -> ExamGenerateJob | None:
    """查询组卷任务。"""

    return session.get(ExamGenerateJob, job_id)


def find_active_generate_job(
    session: Session,
    *,
    subject: str,
    user_id: str,
) -> ExamGenerateJob | None:
    """查询用户当前是否存在进行中的组卷任务。"""

    stmt = (
        select(ExamGenerateJob)
        .where(
            ExamGenerateJob.subject == subject,
            ExamGenerateJob.user_id == user_id,
            ExamGenerateJob.status.in_(["pending", "running"]),  # type: ignore[union-attr]
        )
        .order_by(ExamGenerateJob.created_at.desc(), ExamGenerateJob.id.desc())  # type: ignore[union-attr]
    )
    return session.exec(stmt).first()


def get_exam_grade_job(session: Session, job_id: int) -> ExamGradeJob | None:
    """查询判卷任务。"""

    return session.get(ExamGradeJob, job_id)


def find_active_grade_job(
    session: Session,
    exam_paper_id: int,
) -> ExamGradeJob | None:
    """查询试卷上的活跃判卷任务（pending/running）。"""

    stmt = (
        select(ExamGradeJob)
        .where(
            ExamGradeJob.exam_paper_id == exam_paper_id,
            ExamGradeJob.status.in_(["pending", "running"]),  # type: ignore[union-attr]
        )
        .order_by(ExamGradeJob.created_at.desc())  # type: ignore[union-attr]
    )
    return session.exec(stmt).first()


def find_latest_grade_job_by_paper(
    session: Session,
    exam_paper_id: int,
) -> ExamGradeJob | None:
    """查询试卷最近一次判卷任务（任意状态）。"""

    stmt = (
        select(ExamGradeJob)
        .where(ExamGradeJob.exam_paper_id == exam_paper_id)
        .order_by(ExamGradeJob.created_at.desc(), ExamGradeJob.id.desc())  # type: ignore[union-attr]
    )
    return session.exec(stmt).first()


# ---------------------------------------------------------------------------
# Cross-table reads for paper assembly
# ---------------------------------------------------------------------------


def get_published_curriculum_snapshot(
    session: Session,
    subject: str,
) -> CurriculumSnapshot | None:
    """获取当前发布的课程快照。"""

    return curriculum_repo.get_current_curriculum_snapshot(session, subject)


def resolve_teaching_units_from_theme_tree_node(
    session: Session,
    theme_tree_node_id: int,
) -> list[int]:
    """由主题树节点解析关联教学单元 ID 集合。"""

    stmt = (
        select(UnitTreeMembership.teaching_unit_id)
        .where(UnitTreeMembership.tree_node_id == theme_tree_node_id)
        .distinct()
        .order_by(UnitTreeMembership.teaching_unit_id)
    )
    return [int(item) for item in session.exec(stmt).all()]


def list_prereq_units(
    session: Session,
    unit_id: int,
) -> list[int]:
    """查询指定教学单元的先修依赖单元 ID。"""

    unit = session.get(TeachingUnit, unit_id)
    if unit is None:
        return []

    dag_id = session.exec(
        select(PrereqDagVersion.id)
        .where(
            PrereqDagVersion.subject == unit.subject,
            PrereqDagVersion.status == "published",
        )
        .order_by(PrereqDagVersion.version_no.desc())  # type: ignore[union-attr]
        .limit(1)
    ).first()
    if dag_id is None:
        return []

    stmt = (
        select(UnitDependency.source_unit_id)
        .where(
            UnitDependency.dag_version_id == dag_id,
            UnitDependency.target_unit_id == unit_id,
            UnitDependency.dependency_type == "prerequisite",
        )
        .distinct()
        .order_by(UnitDependency.source_unit_id)
    )
    return [int(item) for item in session.exec(stmt).all()]


def list_recent_exam_template_ids_for_user(
    session: Session,
    user_id: str,
    subject: str,
    *,
    limit: int = 3,
) -> list[int]:
    """查询用户近 N 次考试已使用的模板 ID 集合。"""

    if limit <= 0:
        return []

    recent_exam_ids_subquery = (
        select(ExamPaper.id)
        .where(ExamPaper.user_id == user_id, ExamPaper.subject == subject)
        .order_by(ExamPaper.created_at.desc())  # type: ignore[union-attr]
        .limit(limit)
        .subquery()
    )

    stmt = (
        select(ExamPaperItem.question_template_id)
        .where(
            ExamPaperItem.exam_paper_id.in_(
                select(recent_exam_ids_subquery.c.id)
            )
        )
        .distinct()
    )
    return [int(item) for item in session.exec(stmt).all()]
