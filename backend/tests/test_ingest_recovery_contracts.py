from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.workflows.ingest as ingest_package
from app.models import IngestStatus, RawFile, TaskStatus, User
from app.shared.infra.exceptions import InvalidRawFileStateError
from app.shared.infra.runtime.tasks import BackgroundTaskRegistry
from app.utils.time import utcnow
from app.workflows.ingest.intake import parse_dispatch
from app.workflows.ingest.parsing.lib import lifecycle, recovery
from app.workflows.ingest.parsing.nodes import enhance


def _install_database(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine, tables=[User.__table__, RawFile.__table__])

    @contextmanager
    def fake_managed_session():
        with Session(engine, expire_on_commit=False) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    monkeypatch.setattr(recovery, "managed_session", fake_managed_session)
    monkeypatch.setattr(lifecycle, "managed_session", fake_managed_session)
    monkeypatch.setattr(parse_dispatch, "managed_session", fake_managed_session)
    return engine


def _raw_file(
    file_id: str,
    *,
    status: str,
    ingest_status: str,
    updated_at,
) -> RawFile:
    return RawFile(
        id=file_id,
        user_id="user-a",
        filename=f"{file_id}.pdf",
        filetype="pdf",
        file_path=f"raw/{file_id}.pdf",
        status=status,
        ingest_status=ingest_status,
        updated_at=updated_at,
    )


class _RecordingRegistry:
    def __init__(self) -> None:
        self.spawned: list[dict[str, object]] = []

    def spawn(self, coro, **kwargs):
        coro.close()
        self.spawned.append(kwargs)
        return object()


def test_phase_one_recovery_only_claims_retry_pending_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _install_database(monkeypatch)
    now = utcnow()
    stale_at = now - recovery.STALLED_INGEST_TTL - timedelta(seconds=1)
    with Session(engine, expire_on_commit=False) as session:
        session.add_all(
            [
                _raw_file(
                    "file-active-stale",
                    status=TaskStatus.PROCESSING.value,
                    ingest_status=IngestStatus.CLASSIFYING.value,
                    updated_at=stale_at,
                ),
                _raw_file(
                    "file-retry",
                    status=TaskStatus.PENDING.value,
                    ingest_status=IngestStatus.RETRY_PENDING.value,
                    updated_at=now,
                ),
            ]
        )
        session.commit()

    registry = _RecordingRegistry()
    assert asyncio.run(recovery.recover_stalled_parses(task_registry=registry)) == 1
    assert len(registry.spawned) == 1
    assert asyncio.run(recovery.recover_stalled_parses(task_registry=registry)) == 0

    with Session(engine, expire_on_commit=False) as session:
        active = session.get(RawFile, "file-active-stale")
        retry = session.get(RawFile, "file-retry")
        assert active is not None and retry is not None
        assert (active.status, active.ingest_status) == (
            TaskStatus.PROCESSING.value,
            IngestStatus.CLASSIFYING.value,
        )
        assert (retry.status, retry.ingest_status, retry.current_step) == (
            TaskStatus.PROCESSING.value,
            IngestStatus.CLASSIFYING.value,
            "ingest.parse.recovery_queued",
        )


def test_parse_spawn_failure_returns_files_to_retry_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _install_database(monkeypatch)
    with Session(engine, expire_on_commit=False) as session:
        session.add(
            _raw_file(
                "file-spawn-failed",
                status=TaskStatus.PROCESSING.value,
                ingest_status=IngestStatus.CLASSIFYING.value,
                updated_at=utcnow(),
            )
        )
        session.commit()

    class _FailingRegistry:
        @staticmethod
        def spawn(coro, **_kwargs):
            raise RuntimeError("spawn failed")

    with pytest.raises(RuntimeError, match="spawn failed"):
        parse_dispatch.spawn_parse_files_background(
            _FailingRegistry(),
            user_id="user-a",
            file_ids=["file-spawn-failed"],
        )

    with Session(engine, expire_on_commit=False) as session:
        raw_file = session.get(RawFile, "file-spawn-failed")
        assert raw_file is not None
        assert (raw_file.status, raw_file.ingest_status, raw_file.current_step) == (
            TaskStatus.PENDING.value,
            IngestStatus.RETRY_PENDING.value,
            "ingest.parse.retry_pending",
        )


def test_phase_one_initial_claim_rolls_back_batch_after_cas_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _install_database(monkeypatch)
    now = utcnow()
    with Session(engine, expire_on_commit=False) as session:
        session.add_all(
            [
                _raw_file(
                    "file-a",
                    status=TaskStatus.PENDING.value,
                    ingest_status=IngestStatus.PENDING.value,
                    updated_at=now,
                ),
                _raw_file(
                    "file-b",
                    status=TaskStatus.PENDING.value,
                    ingest_status=IngestStatus.PENDING.value,
                    updated_at=now,
                ),
            ]
        )
        session.commit()
        stale_rows = [
            session.get(RawFile, "file-a").model_copy(deep=True),
            session.get(RawFile, "file-b").model_copy(deep=True),
        ]
        session.exec(
            sa.update(RawFile)
            .where(RawFile.id == "file-b")
            .values(
                status=TaskStatus.PROCESSING.value,
                ingest_status=IngestStatus.CLASSIFYING.value,
                updated_at=utcnow(),
            )
            .execution_options(synchronize_session=False)
        )
        session.commit()
        monkeypatch.setattr(
            parse_dispatch,
            "get_user_files_or_raise",
            lambda *args, **kwargs: stale_rows,
        )

        with pytest.raises(InvalidRawFileStateError):
            parse_dispatch._start_parse_for_files(
                session,
                owner_user_id="user-a",
                course_id=None,
                file_ids=["file-a", "file-b"],
            )

        session.expire_all()
        first = session.get(RawFile, "file-a")
        second = session.get(RawFile, "file-b")
        assert first is not None and second is not None
        assert (first.status, first.ingest_status) == (
            TaskStatus.PENDING.value,
            IngestStatus.PENDING.value,
        )
        assert (second.status, second.ingest_status) == (
            TaskStatus.PROCESSING.value,
            IngestStatus.CLASSIFYING.value,
        )


def test_cancelled_active_parse_is_not_requeued_without_fencing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _install_database(monkeypatch)
    with Session(engine, expire_on_commit=False) as session:
        session.add(
            _raw_file(
                "file-cancelled",
                status=TaskStatus.PROCESSING.value,
                ingest_status=IngestStatus.CLASSIFYING.value,
                updated_at=utcnow(),
            )
        )
        session.commit()

    async def scenario() -> None:
        started = asyncio.Event()
        never_finishes = asyncio.Event()

        async def fake_run_parse_file_workflow(**_kwargs):
            started.set()
            await never_finishes.wait()

        monkeypatch.setattr(
            ingest_package,
            "run_parse_file_workflow",
            fake_run_parse_file_workflow,
        )
        task = asyncio.create_task(
            parse_dispatch.run_parse_files_background(
                user_id="user-a",
                file_ids=["file-cancelled"],
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    with Session(engine, expire_on_commit=False) as session:
        raw_file = session.get(RawFile, "file-cancelled")
        assert raw_file is not None
        assert (raw_file.status, raw_file.ingest_status) == (
            TaskStatus.PROCESSING.value,
            IngestStatus.CLASSIFYING.value,
        )


def test_registry_requeues_phase_one_only_after_confirmed_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _install_database(monkeypatch)
    with Session(engine, expire_on_commit=False) as session:
        session.add(
            _raw_file(
                "file-shutdown",
                status=TaskStatus.PROCESSING.value,
                ingest_status=IngestStatus.CLASSIFYING.value,
                updated_at=utcnow(),
            )
        )
        session.commit()

    async def scenario() -> None:
        started = asyncio.Event()
        never_finishes = asyncio.Event()

        async def fake_run_parse_file_workflow(**_kwargs):
            started.set()
            await never_finishes.wait()

        monkeypatch.setattr(
            ingest_package,
            "run_parse_file_workflow",
            fake_run_parse_file_workflow,
        )
        registry = BackgroundTaskRegistry()
        task = parse_dispatch.spawn_parse_files_background(
            registry,
            user_id="user-a",
            file_ids=["file-shutdown"],
        )
        await asyncio.wait_for(started.wait(), timeout=1.0)
        await registry.shutdown(cancel_timeout_s=1.0)
        assert task.cancelled()

    asyncio.run(scenario())

    with Session(engine, expire_on_commit=False) as session:
        raw_file = session.get(RawFile, "file-shutdown")
        assert raw_file is not None
        assert (raw_file.status, raw_file.ingest_status, raw_file.current_step) == (
            TaskStatus.PENDING.value,
            IngestStatus.RETRY_PENDING.value,
            "ingest.parse.retry_pending",
        )
        assert raw_file.error_message == "parse_worker_cancelled"


def test_phase_two_recovery_claims_fast_parsed_but_never_active_enhancing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _install_database(monkeypatch)
    now = utcnow()
    stale_at = now - recovery.STALLED_INGEST_TTL - timedelta(seconds=1)
    with Session(engine, expire_on_commit=False) as session:
        session.add_all(
            [
                _raw_file(
                    "file-fast-parsed",
                    status=TaskStatus.COMPLETED.value,
                    ingest_status=IngestStatus.FAST_PARSED.value,
                    updated_at=stale_at,
                ),
                _raw_file(
                    "file-active-enhancing",
                    status=TaskStatus.COMPLETED.value,
                    ingest_status=IngestStatus.ENHANCING.value,
                    updated_at=stale_at,
                ),
                _raw_file(
                    "file-fresh-fast-parsed",
                    status=TaskStatus.COMPLETED.value,
                    ingest_status=IngestStatus.FAST_PARSED.value,
                    updated_at=now,
                ),
            ]
        )
        session.commit()

    async def fake_enhance(**_kwargs) -> None:
        return None

    monkeypatch.setattr(enhance, "_run_deep_enhance_background", fake_enhance)
    registry = _RecordingRegistry()
    assert asyncio.run(
        recovery.recover_stalled_enhancements(task_registry=registry, now=now)
    ) == 1
    assert len(registry.spawned) == 1
    assert asyncio.run(
        recovery.recover_stalled_enhancements(task_registry=registry, now=now)
    ) == 0

    with Session(engine, expire_on_commit=False) as session:
        claimed = session.get(RawFile, "file-fast-parsed")
        active = session.get(RawFile, "file-active-enhancing")
        fresh = session.get(RawFile, "file-fresh-fast-parsed")
        assert claimed is not None and active is not None and fresh is not None
        assert (claimed.ingest_status, claimed.current_step) == (
            IngestStatus.ENHANCING.value,
            "ingest.enhance.recovery_queued",
        )
        assert active.ingest_status == IngestStatus.ENHANCING.value
        assert fresh.ingest_status == IngestStatus.FAST_PARSED.value


@pytest.mark.parametrize("is_recovery", [False, True])
def test_registry_requeues_only_unstarted_phase_two_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    is_recovery: bool,
) -> None:
    engine = _install_database(monkeypatch)
    suffix = "recovery" if is_recovery else "normal"
    running_id = f"file-enhance-running-{suffix}"
    queued_id = f"file-enhance-queued-{suffix}"
    with Session(engine, expire_on_commit=False) as session:
        session.add_all(
            [
                _raw_file(
                    running_id,
                    status=TaskStatus.COMPLETED.value,
                    ingest_status=IngestStatus.FAST_PARSED.value,
                    updated_at=utcnow(),
                ),
                _raw_file(
                    queued_id,
                    status=TaskStatus.COMPLETED.value,
                    ingest_status=IngestStatus.FAST_PARSED.value,
                    updated_at=utcnow(),
                ),
            ]
        )
        session.commit()

    class _SingleEnhanceRegistry(BackgroundTaskRegistry):
        def spawn(self, coro, **kwargs):
            return super().spawn(coro, max_concurrency=1, **kwargs)

    async def scenario() -> None:
        started = asyncio.Event()
        never_finishes = asyncio.Event()

        async def fake_enhance(**_kwargs) -> None:
            started.set()
            await never_finishes.wait()

        monkeypatch.setattr(enhance, "_run_deep_enhance_background", fake_enhance)
        registry = _SingleEnhanceRegistry()
        assert lifecycle.dispatch_enhancement_for_file(
            user_id="user-a",
            file_id=running_id,
            course_id="course-a",
            background_task_registry=registry,
            recovery=is_recovery,
        )
        await asyncio.wait_for(started.wait(), timeout=1.0)
        assert lifecycle.dispatch_enhancement_for_file(
            user_id="user-a",
            file_id=queued_id,
            course_id="course-a",
            background_task_registry=registry,
            recovery=is_recovery,
        )
        await asyncio.sleep(0)
        await registry.shutdown(cancel_timeout_s=1.0)

    asyncio.run(scenario())

    with Session(engine, expire_on_commit=False) as session:
        running = session.get(RawFile, running_id)
        queued = session.get(RawFile, queued_id)
        assert running is not None and queued is not None
        assert (running.ingest_status, running.current_step) == (
            IngestStatus.ENHANCING.value,
            "ingest.enhance.running",
        )
        assert (queued.ingest_status, queued.current_step, queued.error_message) == (
            IngestStatus.FAST_PARSED.value,
            "ingest.enhance.retry_pending",
            "enhance_worker_cancelled",
        )
