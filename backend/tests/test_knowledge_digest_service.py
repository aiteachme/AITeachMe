from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.models import IngestStatus, RawFile, RetrievalChunk, Subject, TaskStatus
from app.models.build_planner import ConfirmedBuildPlan
from app.schemas.knowledge import KnowledgeBuildPrecheckConflictData, SubjectVectorStatusResponse
from app.services.knowledge.digest_service import trigger_docgen_build
from app.shared.infra.exceptions import ConfirmedBuildPlanRequiredError, SubjectBuildLockConflictError


def _seed_subject(session: Session, *, subject_slug: str) -> Subject:
    subject = Subject(user_id="local", slug=subject_slug, name="Test Subject")
    session.add(subject)
    session.commit()
    session.refresh(subject)
    return subject


def _seed_ready_raw_file(session: Session, *, subject_slug: str, uid: str) -> RawFile:
    raw_file = RawFile(
        uid=uid,
        subject=subject_slug,
        filename=f"{uid}.md",
        filetype="md",
        file_path=f"/tmp/{uid}.md",
        status=TaskStatus.COMPLETED.value,
        ingest_status=IngestStatus.READY_FOR_DIGEST.value,
        markdown_content=f"# {uid}\n\nsample content",
    )
    session.add(raw_file)
    session.commit()
    session.refresh(raw_file)
    return raw_file


def _seed_confirmed_plan(
    session: Session,
    *,
    plan_id: str,
    subject_slug: str,
    selected_file_ids: list[int],
    status: str = "confirmed",
    planner_session_id: str = "planner-session",
    user_goal: str = "Plan-guided build",
    plan_summary: str = "Fallback summary",
    digest_mode: str = "systematic",
    tone: str = "encouraging",
) -> ConfirmedBuildPlan:
    plan = ConfirmedBuildPlan(
        id=plan_id,
        subject=subject_slug,
        planner_session_id=planner_session_id,
        user_id="local",
        status=status,
        user_goal=user_goal,
        digest_mode=digest_mode,
        tone=tone,
        selected_file_ids_json=selected_file_ids,
        chapter_plan_json=[],
        research_queries_json=[],
        media_plan_json={},
        build_constraints_json={},
        plan_summary=plan_summary,
        plan_json={
            "subject": subject_slug,
            "user_goal": user_goal,
            "digest_mode": digest_mode,
            "tone": tone,
            "chapter_plan": [],
            "research_queries": [],
            "media_plan": {},
            "build_constraints": {},
            "plan_summary": plan_summary,
        },
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def _vector_status(*, mode: str = "enabled") -> SubjectVectorStatusResponse:
    return SubjectVectorStatusResponse(
        mode=mode,
        embedding_model="text-embedding-v4",
        vector_table="chunk_embeddings_test_subject",
    )


def test_trigger_docgen_build_force_full_rebuild_clears_chunk_vector_metadata(
    session: Session,
) -> None:
    subject = _seed_subject(session, subject_slug="subj_digest_rebuild")
    first_file = _seed_ready_raw_file(session, subject_slug=subject.slug, uid="raw_digest_a")
    second_file = _seed_ready_raw_file(session, subject_slug=subject.slug, uid="raw_digest_b")

    chunk = RetrievalChunk(
        subject=subject.slug,
        document_id=int(first_file.id or 0),
        title="sample",
        level=1,
        header_path="sample",
        chunk_index=0,
        digest_chunk_uid="chunk-subj-digest-rebuild",
        build_session_id="build-1",
        content="sample content",
        embedding_model="text-embedding-v3",
        vector_ref="chunk_embeddings",
    )
    session.add(chunk)
    session.commit()
    session.refresh(chunk)

    conflict = KnowledgeBuildPrecheckConflictData(
        reason="legacy_vector_table",
        subject_model=None,
        subject_dim=None,
        runtime_model="text-embedding-v4",
        runtime_dim=1024,
        requires_full_rebuild=True,
        vector_enabled_after_continue=False,
    )

    with patch(
        "app.services.knowledge.digest_service.inspect_subject_build_precheck",
        return_value=conflict,
    ), patch(
        "app.services.knowledge.digest_service.resolve_subject_build_vector_status",
        return_value=_vector_status(),
    ), patch(
        "app.services.knowledge.digest_service.acquire_knowledge_build_lock",
        return_value=True,
    ), patch(
        "app.services.knowledge.digest_service.clear_docgen_staging",
    ), patch(
        "app.services.knowledge.digest_service.update_knowledge_build_status",
    ):
        data, accepted_file_ids = trigger_docgen_build(
            session,
            subject=subject,
            user_id="local",
            file_uids=[first_file.uid],
            prompt="  review me  ",
            embedding_resolution=None,
            confirmed_plan_id=None,
            build_type="graph",
        )

    session.refresh(chunk)

    assert accepted_file_ids == [int(first_file.id or 0)]
    assert data.accepted_file_uids == [first_file.uid]
    assert data.ready_file_count == 2
    assert data.prompt == "review me"
    assert data.vector_status.mode == "enabled"
    assert chunk.embedding_model is None
    assert chunk.vector_ref is None
    assert second_file.uid not in data.accepted_file_uids


def test_trigger_docgen_build_calls_direct_clear_chunk_vector_metadata(session: Session) -> None:
    subject = _seed_subject(session, subject_slug="subj_digest_direct_import")
    ready_file = _seed_ready_raw_file(session, subject_slug=subject.slug, uid="raw_digest_direct")

    conflict = KnowledgeBuildPrecheckConflictData(
        reason="legacy_vector_table",
        subject_model=None,
        subject_dim=None,
        runtime_model="text-embedding-v4",
        runtime_dim=1024,
        requires_full_rebuild=True,
        vector_enabled_after_continue=False,
    )

    with patch(
        "app.services.knowledge.digest_service.inspect_subject_build_precheck",
        return_value=conflict,
    ), patch(
        "app.services.knowledge.digest_service.resolve_subject_build_vector_status",
        return_value=_vector_status(),
    ), patch(
        "app.services.knowledge.digest_service.clear_chunk_vector_metadata",
    ) as clear_mock, patch(
        "app.services.knowledge.digest_service.acquire_knowledge_build_lock",
        return_value=True,
    ), patch(
        "app.services.knowledge.digest_service.clear_docgen_staging",
    ), patch(
        "app.services.knowledge.digest_service.update_knowledge_build_status",
    ):
        data, accepted_file_ids = trigger_docgen_build(
            session,
            subject=subject,
            user_id="local",
            file_uids=[ready_file.uid],
            prompt=None,
            embedding_resolution=None,
            confirmed_plan_id=None,
            build_type="graph",
        )

    clear_mock.assert_called_once_with(session, subject=subject.slug)
    assert accepted_file_ids == [int(ready_file.id or 0)]
    assert data.accepted_file_uids == [ready_file.uid]


def test_trigger_docgen_build_uses_confirmed_plan_selection_and_prompt(session: Session) -> None:
    subject = _seed_subject(session, subject_slug="subj_digest_confirmed_plan")
    first_file = _seed_ready_raw_file(session, subject_slug=subject.slug, uid="raw_digest_plan_a")
    second_file = _seed_ready_raw_file(session, subject_slug=subject.slug, uid="raw_digest_plan_b")
    plan = _seed_confirmed_plan(
        session,
        plan_id="plan-docgen-1",
        subject_slug=subject.slug,
        selected_file_ids=[int(second_file.id or 0)],
        planner_session_id="planner-docgen-1",
        user_goal="Plan-guided build",
        plan_summary="Fallback summary",
        digest_mode="systematic",
        tone="encouraging",
    )

    with patch(
        "app.services.knowledge.digest_service.inspect_subject_build_precheck",
        return_value=None,
    ), patch(
        "app.services.knowledge.digest_service.resolve_subject_build_vector_status",
        return_value=_vector_status(),
    ), patch(
        "app.services.knowledge.digest_service.acquire_knowledge_build_lock",
        return_value=True,
    ), patch(
        "app.services.knowledge.digest_service.clear_docgen_staging",
    ), patch(
        "app.services.knowledge.digest_service.update_knowledge_build_status",
    ):
        data, accepted_file_ids = trigger_docgen_build(
            session,
            subject=subject,
            user_id="local",
            file_uids=[first_file.uid],
            prompt="manual override",
            embedding_resolution=None,
            confirmed_plan_id=plan.id,
            build_type="docs",
        )

    assert accepted_file_ids == [int(second_file.id or 0)]
    assert data.accepted_file_uids == [second_file.uid]
    assert data.prompt == "Plan-guided build"
    assert data.planner_session_id == "planner-docgen-1"
    assert data.confirmed_plan_id == plan.id
    assert data.digest_mode == "systematic"
    assert first_file.uid not in data.accepted_file_uids


def test_trigger_docgen_build_allows_search_only_docs_for_confirmed_plan(session: Session) -> None:
    subject = _seed_subject(session, subject_slug="subj_digest_search_only")
    plan = _seed_confirmed_plan(
        session,
        plan_id="plan-docgen-search-only",
        subject_slug=subject.slug,
        selected_file_ids=[],
        planner_session_id="planner-docgen-search-only",
        user_goal="系统整理微积分核心知识",
        plan_summary="按章节检索并生成系统讲义",
        digest_mode="systematic",
        tone="encouraging",
    )

    with patch(
        "app.services.knowledge.digest_service.inspect_subject_build_precheck",
        return_value=None,
    ), patch(
        "app.services.knowledge.digest_service.resolve_subject_build_vector_status",
        return_value=_vector_status(),
    ), patch(
        "app.services.knowledge.digest_service.acquire_knowledge_build_lock",
        return_value=True,
    ), patch(
        "app.services.knowledge.digest_service.clear_docgen_staging",
    ), patch(
        "app.services.knowledge.digest_service.update_knowledge_build_status",
    ):
        data, accepted_file_ids = trigger_docgen_build(
            session,
            subject=subject,
            user_id="local",
            file_uids=None,
            prompt=None,
            embedding_resolution=None,
            confirmed_plan_id=plan.id,
            build_type="docs",
        )

    assert accepted_file_ids == []
    assert data.accepted_file_uids == []
    assert data.ready_file_count == 0
    assert data.prompt == "系统整理微积分核心知识"
    assert data.planner_session_id == "planner-docgen-search-only"
    assert data.confirmed_plan_id == plan.id
    assert data.digest_mode == "systematic"


def test_trigger_docgen_build_rejects_building_confirmed_plan(session: Session) -> None:
    subject = _seed_subject(session, subject_slug="subj_digest_building_plan")
    ready_file = _seed_ready_raw_file(session, subject_slug=subject.slug, uid="raw_digest_locked")
    plan = _seed_confirmed_plan(
        session,
        plan_id="plan-building",
        subject_slug=subject.slug,
        selected_file_ids=[int(ready_file.id or 0)],
        status="building",
    )

    with patch(
        "app.services.knowledge.digest_service.inspect_subject_build_precheck",
        return_value=None,
    ), patch(
        "app.services.knowledge.digest_service.resolve_subject_build_vector_status",
        return_value=_vector_status(),
    ), patch(
        "app.services.knowledge.digest_service.acquire_knowledge_build_lock",
        return_value=True,
    ) as lock_mock:
        with pytest.raises(SubjectBuildLockConflictError):
            trigger_docgen_build(
                session,
                subject=subject,
                user_id="local",
                file_uids=[ready_file.uid],
                prompt="try again",
                embedding_resolution=None,
                confirmed_plan_id=plan.id,
                build_type="docs",
            )

    lock_mock.assert_not_called()


def test_trigger_docgen_build_requires_confirmed_plan_for_docs(session: Session) -> None:
    subject = _seed_subject(session, subject_slug="subj_digest_missing_plan")
    ready_file = _seed_ready_raw_file(session, subject_slug=subject.slug, uid="raw_digest_missing_plan")

    with patch(
        "app.services.knowledge.digest_service.inspect_subject_build_precheck",
        return_value=None,
    ), patch(
        "app.services.knowledge.digest_service.resolve_subject_build_vector_status",
        return_value=_vector_status(),
    ):
        with pytest.raises(ConfirmedBuildPlanRequiredError):
            trigger_docgen_build(
                session,
                subject=subject,
                user_id="local",
                file_uids=[ready_file.uid],
                prompt="direct docs build",
                embedding_resolution=None,
                confirmed_plan_id=None,
                build_type="docs",
            )
