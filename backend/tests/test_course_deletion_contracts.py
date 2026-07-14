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

TEST_COURSE_ID = "course_123456789abc"


class _FakeBackgroundRegistry:
    def __init__(self) -> None:
        self.cancel_calls: list[dict[str, str | None]] = []
        self.spawned: list[dict[str, str | None]] = []

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
