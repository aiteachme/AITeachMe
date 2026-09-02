from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401 - register every SQLModel table
from app.api import exams as exams_api
from app.api.deps import CurrentUserContext
from app.models import Course, ExamPaper, ExamStudyGuideCache, User
from app.repositories import exams_repo
from app.shared.infra.exceptions import AITeachMeError


@pytest.mark.anyio
async def test_completed_exam_deletion_returns_explicit_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    course_id = "course_123456789abc"
    paper = SimpleNamespace(
        course_id=course_id,
        user_id="user-delete",
        visibility="visible",
        status="graded",
    )
    cascade_called = False

    monkeypatch.setattr(exams_api, "_ensure_course", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        exams_api.exams_repo,
        "get_exam_paper_by_id",
        lambda *_args, **_kwargs: paper,
    )

    def track_cascade(*_args: object, **_kwargs: object) -> bool:
        nonlocal cascade_called
        cascade_called = True
        return True

    monkeypatch.setattr(exams_api.exams_repo, "delete_exam_paper_cascade", track_cascade)

    with pytest.raises(AITeachMeError) as error_info:
        await exams_api.delete_exam_paper(
            course_id=course_id,
            exam_paper_id=17,
            user=CurrentUserContext(user_id="user-delete", email=None, is_local=True),
            session=object(),  # type: ignore[arg-type]
        )

    assert error_info.value.status_code == 409
    assert error_info.value.error_code == "EXAM_COMPLETED_DELETE_NOT_ALLOWED"
    assert error_info.value.detail == "系统暂不允许删除已完成的训练记录。"
    assert cascade_called is False


def test_failed_exam_with_study_guide_cache_can_be_deleted() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys = ON")  # type: ignore[attr-defined]

    SQLModel.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        user_id = "user-delete-failed"
        course_id = "course_abcdef123456"
        session.add(User(id=user_id, username=user_id))
        session.commit()
        session.add(Course(id=course_id, user_id=user_id, name="Delete failed exam"))
        session.commit()

        paper = ExamPaper(
            course_id=course_id,
            user_id=user_id,
            exam_mode="paper_exam",
            status="failed",
            total_items=24,
        )
        session.add(paper)
        session.commit()
        session.refresh(paper)
        paper_id = int(paper.id or 0)

        session.add(
            ExamStudyGuideCache(
                exam_paper_id=paper_id,
                course_id=course_id,
                user_id=user_id,
                status="completed",
            )
        )
        session.commit()

        assert exams_repo.delete_exam_paper_cascade(session, paper_id=paper_id) is True
        assert session.get(ExamPaper, paper_id) is None
        assert session.exec(
            select(ExamStudyGuideCache).where(ExamStudyGuideCache.exam_paper_id == paper_id)
        ).first() is None
