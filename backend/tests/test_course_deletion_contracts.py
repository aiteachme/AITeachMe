from __future__ import annotations

from collections.abc import Coroutine
from datetime import timedelta
from threading import get_ident
from typing import Any

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models import Course, CourseShare, User
from app.utils.time import utcnow
from app.workflows.support.courses import deletion as course_deletion
from app.workflows.support.courses.lib import deletion as course_deletion_lib

TEST_COURSE_ID = "course_123456789abc"


class _FakeBackgroundRegistry:
    def __init__(self) -> None:
        self.cancel_calls: list[dict[str, str | None]] = []
        self.spawned: list[dict[str, str | None]] = []
        self.spawn_thread_ids: list[int] = []

    async def cancel_matching(
        self,
        *,
        kind: str | None = None,
        course_id: str | None = None,
        timeout_s: float = 3.0,
    ) -> int:
        del timeout_s
        self.cancel_calls.append({"kind": kind, "course_id": course_id})
        return 1

    def spawn(
        self,
        coro: Coroutine[Any, Any, Any],
        *,
        kind: str,
        course_id: str | None = None,
        name: str | None = None,
        dedupe_key: str | None = None,
    ) -> None:
        self.spawn_thread_ids.append(get_ident())
        coro.close()
        self.spawned.append({"kind": kind, "course_id": course_id, "name": name, "dedupe_key": dedupe_key})


@pytest.mark.anyio
async def test_delete_course_cancels_tasks_and_revokes_active_shares(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    registry = _FakeBackgroundRegistry()
    cancel_build_calls: list[str] = []
    snapshot_cleanup_calls: list[list[str]] = []
    deletion_thread_ids: list[int] = []
    deletion_session_ids: list[int] = []
    event_loop_thread_id = get_ident()
    original_delete_course_with_all_content = course_deletion.delete_course_with_all_content

    async def fake_cancel_knowledge_build(
        session: Session,
        *,
        course: Course,
        user_id: str,
        background_task_registry: Any | None = None,
    ) -> Any:
        del session, user_id, background_task_registry
        cancel_build_calls.append(course.id)

    monkeypatch.setattr(
        "app.workflows.digest.common.build_lifecycle.cancel_knowledge_build",
        fake_cancel_knowledge_build,
    )
    monkeypatch.setattr(
        "app.workflows.support.courses.lib.deletion._delete_course_share_snapshots_best_effort",
        lambda storage_keys: snapshot_cleanup_calls.append(storage_keys),
    )

    def observed_delete_course_with_all_content(*args: Any, **kwargs: Any) -> dict[str, int]:
        deletion_thread_ids.append(get_ident())
        deletion_session_ids.append(id(args[0]))
        return original_delete_course_with_all_content(*args, **kwargs)

    monkeypatch.setattr(
        course_deletion,
        "delete_course_with_all_content",
        observed_delete_course_with_all_content,
    )

    with Session(engine, expire_on_commit=False) as session:
        session.add(User(id="owner", username="owner"))
        session.add(Course(id=TEST_COURSE_ID, user_id="owner", name="待删除课程", description=""))
        now = utcnow()
        session.add(
            CourseShare(
                id="share_delete",
                owner_user_id="owner",
                source_course_id=TEST_COURSE_ID,
                token="cshr_delete",
                token_hash="hash",
                storage_key="shared/course_snapshots/share_delete.atmx",
                course_name="待删除课程",
                course_description="",
                status="active",
                import_count=0,
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(days=30),
            )
        )
        session.commit()

        data = await course_deletion.delete_course_record(
            session,
            owner_user_id="owner",
            course_id=TEST_COURSE_ID,
            force=True,
            background_task_registry=registry,
        )

        share = session.get(CourseShare, "share_delete")
        assert data.deleted is True
        assert data.deleted_counts["course_share"] == 1
        assert session.get(Course, TEST_COURSE_ID) is None
        assert share is not None
        assert share.status == "revoked"
        assert share.revoked_at is not None
        assert snapshot_cleanup_calls == [["shared/course_snapshots/share_delete.atmx"]]
        assert cancel_build_calls == [TEST_COURSE_ID]
        assert {"kind": None, "course_id": TEST_COURSE_ID} in registry.cancel_calls
        assert deletion_thread_ids
        assert deletion_thread_ids[0] != event_loop_thread_id
        assert deletion_session_ids
        assert all(session_id != id(session) for session_id in deletion_session_ids)
        assert registry.spawn_thread_ids == [event_loop_thread_id]


def test_delete_course_commit_ack_loss_finishes_external_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    snapshot_cleanup_calls: list[list[str]] = []
    external_cleanup_calls: list[tuple[str, str | None]] = []

    monkeypatch.setattr(
        course_deletion_lib,
        "_delete_course_share_snapshots_best_effort",
        lambda storage_keys: snapshot_cleanup_calls.append(storage_keys),
    )
    monkeypatch.setattr(
        course_deletion_lib,
        "schedule_course_external_cleanup",
        lambda course_id, *, owner_user_id, background_task_registry: external_cleanup_calls.append(
            (course_id, owner_user_id)
        ),
    )

    with Session(engine, expire_on_commit=False) as session:
        session.add(User(id="owner", username="owner"))
        session.add(Course(id=TEST_COURSE_ID, user_id="owner", name="ACK 丢失课程"))
        now = utcnow()
        session.add(
            CourseShare(
                id="share_delete_ack_loss",
                owner_user_id="owner",
                source_course_id=TEST_COURSE_ID,
                token="cshr_delete_ack_loss",
                token_hash="delete-ack-loss-hash",
                storage_key="shared/course_snapshots/share_delete_ack_loss.atmx",
                course_name="ACK 丢失课程",
                status="active",
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(days=30),
            )
        )
        session.commit()
        course = session.get(Course, TEST_COURSE_ID)
        assert course is not None
        original_commit = session.commit

        def commit_then_lose_ack() -> None:
            original_commit()
            raise RuntimeError("injected course delete commit acknowledgement loss")

        monkeypatch.setattr(session, "commit", commit_then_lose_ack)
        deleted_counts = course_deletion_lib.delete_course_with_all_content(
            session,
            course=course,
            counts={"course_share": 1},
        )

    assert deleted_counts["course"] == 1
    assert snapshot_cleanup_calls == [["shared/course_snapshots/share_delete_ack_loss.atmx"]]
    assert external_cleanup_calls == [(TEST_COURSE_ID, "owner")]
    with Session(engine) as verification_session:
        assert verification_session.get(Course, TEST_COURSE_ID) is None
        share = verification_session.get(CourseShare, "share_delete_ack_loss")
        assert share is not None
        assert share.status == "revoked"


def test_delete_course_commit_failure_preserves_external_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    snapshot_cleanup_calls: list[list[str]] = []
    external_cleanup_calls: list[str] = []

    monkeypatch.setattr(
        course_deletion_lib,
        "_delete_course_share_snapshots_best_effort",
        lambda storage_keys: snapshot_cleanup_calls.append(storage_keys),
    )
    monkeypatch.setattr(
        course_deletion_lib,
        "schedule_course_external_cleanup",
        lambda course_id, **_kwargs: external_cleanup_calls.append(course_id),
    )

    with Session(engine, expire_on_commit=False) as session:
        session.add(User(id="owner", username="owner"))
        session.add(Course(id=TEST_COURSE_ID, user_id="owner", name="提交失败课程"))
        now = utcnow()
        session.add(
            CourseShare(
                id="share_delete_commit_failure",
                owner_user_id="owner",
                source_course_id=TEST_COURSE_ID,
                token="cshr_delete_commit_failure",
                token_hash="delete-commit-failure-hash",
                storage_key="shared/course_snapshots/share_delete_commit_failure.atmx",
                course_name="提交失败课程",
                status="active",
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(days=30),
            )
        )
        session.commit()
        course = session.get(Course, TEST_COURSE_ID)
        assert course is not None

        def fail_before_commit() -> None:
            raise RuntimeError("injected course delete commit failure")

        monkeypatch.setattr(session, "commit", fail_before_commit)
        with pytest.raises(RuntimeError, match="injected course delete commit failure"):
            course_deletion_lib.delete_course_with_all_content(
                session,
                course=course,
                counts={"course_share": 1},
            )

    assert snapshot_cleanup_calls == []
    assert external_cleanup_calls == []
    with Session(engine) as verification_session:
        assert verification_session.get(Course, TEST_COURSE_ID) is not None
        share = verification_session.get(CourseShare, "share_delete_commit_failure")
        assert share is not None
        assert share.status == "active"
