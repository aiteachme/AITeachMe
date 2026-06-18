from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401 - register SQLModel tables
from app.models import Course, User
from app.schemas.profile import CourseProfileSummary, UserProfileSummary
from app.workflows.digest.docgen.lib import learner_profile
from app.workflows.profile.common.lib.user_profile import build_user_profile_summary


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def test_user_profile_summary_renders_prompt_ready_text() -> None:
    with _session() as session:
        session.add(User(id="u1", username="local"))
        session.add(Course(id="c1", user_id="u1", name="初中数学"))
        session.commit()

        summary = build_user_profile_summary(session, user_id="u1")

    assert summary.profile_text
    assert "用户画像" in summary.profile_text
    assert "活跃课程" in summary.profile_text


def test_docgen_learner_profile_loader_reads_persisted_profile_text(monkeypatch) -> None:
    with _session() as session:
        user_profile = UserProfileSummary(
            user_id="u1",
            generated_at=datetime.now(timezone.utc),
            active_course_count=1,
            explanation_style="guided",
            pace_preference="quick_cycle",
            consistency_level="steady",
            profile_text="用户画像：更适合分步引导和短周期复盘。",
        )
        course_profile = CourseProfileSummary(
            course_id="c1",
            generated_at=datetime.now(timezone.utc),
            avg_mastery=0.42,
            weak_knowledge_unit_count=3,
            due_review_count=2,
            profile_text="课程画像：函数部分薄弱，需要例题和错因辨析。",
        )
        session.add(User(id="u1", username="local", profile_json=user_profile.model_dump_json()))
        session.add(
            Course(
                id="c1",
                user_id="u1",
                name="初中数学",
                profile_json=course_profile.model_dump_json(),
            )
        )
        session.commit()

        @contextmanager
        def fake_managed_session() -> Iterator[Session]:
            yield session

        monkeypatch.setattr(learner_profile, "managed_session", fake_managed_session)

        context = learner_profile.load_docgen_learner_profile_context(course_id="c1")

    assert context["has_profile"] is True
    assert context["user_id"] == "u1"
    assert "分步引导" in context["profile_text"]
    assert "函数部分薄弱" in context["profile_text"]
    assert context["user_profile_text"].startswith("用户画像")
    assert context["course_profile_text"].startswith("课程画像")
    assert context["user_profile"]["profile_text"].startswith("用户画像")
    assert context["course_profile"]["profile_text"].startswith("课程画像")
