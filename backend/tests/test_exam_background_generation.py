from __future__ import annotations

from datetime import timedelta

from sqlmodel import Session, SQLModel, create_engine

from app.api.exams import _reserve_exam_prewarm_paper
from app.models import ExamPaper, ExamStudyGuideCache
from app.repositories import exams_repo
from app.utils.time import utcnow


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(
        engine,
        tables=[ExamPaper.__table__, ExamStudyGuideCache.__table__],
    )
    return engine


def test_hidden_prepared_exam_is_excluded_until_claimed() -> None:
    engine = _engine()
    now = utcnow()
    with Session(engine) as session:
        visible = ExamPaper(
            subject="math",
            user_id="user-a",
            exam_mode="web_practice",
            status="ready",
            visibility="visible",
            generation_origin="user",
            total_items=3,
        )
        hidden = ExamPaper(
            subject="math",
            user_id="user-a",
            exam_mode="web_practice",
            status="ready",
            visibility="hidden",
            generation_origin="prewarm",
            config_hash="hash-a",
            total_items=8,
            prepared_at=now,
            expires_at=now + timedelta(hours=2),
        )
        session.add(visible)
        session.add(hidden)
        session.commit()

        rows, total = exams_repo.list_exam_papers(
            session,
            subject="math",
            user_id="user-a",
            limit=20,
            offset=0,
        )
        assert total == 1
        assert [row.visibility for row in rows] == ["visible"]

        claimed = exams_repo.claim_prepared_exam_paper(
            session,
            subject="math",
            user_id="user-a",
            config_hash="hash-a",
        )

        assert claimed is not None
        assert claimed.id == hidden.id
        assert claimed.visibility == "visible"
        assert claimed.claimed_at is not None
        assert claimed.expires_at is None

        rows, total = exams_repo.list_exam_papers(
            session,
            subject="math",
            user_id="user-a",
            limit=20,
            offset=0,
        )
        assert total == 2
        assert {row.id for row in rows} == {visible.id, hidden.id}


def test_active_prepared_exam_ignores_expired_stock() -> None:
    engine = _engine()
    now = utcnow()
    with Session(engine) as session:
        session.add(
            ExamPaper(
                subject="math",
                user_id="user-a",
                exam_mode="web_practice",
                status="ready",
                visibility="hidden",
                generation_origin="prewarm",
                config_hash="hash-a",
                total_items=8,
                prepared_at=now - timedelta(days=3),
                expires_at=now - timedelta(minutes=1),
            )
        )
        session.add(
            ExamPaper(
                subject="math",
                user_id="user-a",
                exam_mode="web_practice",
                status="generating",
                visibility="hidden",
                generation_origin="prewarm",
                config_hash="hash-b",
                total_items=8,
                expires_at=now + timedelta(hours=2),
            )
        )
        session.commit()

        assert not exams_repo.has_active_prepared_exam(
            session,
            subject="math",
            user_id="user-a",
            config_hash="hash-a",
        )
        assert exams_repo.has_active_prepared_exam(
            session,
            subject="math",
            user_id="user-a",
            config_hash="hash-b",
        )

        claimed = exams_repo.claim_prepared_exam_paper(
            session,
            subject="math",
            user_id="user-a",
            config_hash="hash-b",
        )
        assert claimed is not None
        assert claimed.status == "generating"
        assert claimed.visibility == "visible"


def test_reserved_in_progress_prewarm_can_be_claimed_as_new_exam() -> None:
    engine = _engine()
    with Session(engine) as session:
        config_snapshot = {"version": 1, "subject": "math", "num_questions": 8}
        reserved, created = _reserve_exam_prewarm_paper(
            session,
            subject="math",
            user_id="user-a",
            exam_mode="web_practice",
            question_count=8,
            user_prompt=None,
            sample_file_ids=[],
            unit_ids=[1, 2],
            config_snapshot=config_snapshot,
            config_hash="hash-a",
        )

        assert created
        assert reserved.visibility == "hidden"
        assert reserved.status == "generating"

        repeated, repeated_created = _reserve_exam_prewarm_paper(
            session,
            subject="math",
            user_id="user-a",
            exam_mode="web_practice",
            question_count=8,
            user_prompt=None,
            sample_file_ids=[],
            unit_ids=[1, 2],
            config_snapshot=config_snapshot,
            config_hash="hash-a",
        )
        assert not repeated_created
        assert repeated.id == reserved.id

        claimed = exams_repo.claim_prepared_exam_paper(
            session,
            subject="math",
            user_id="user-a",
            config_hash="hash-a",
        )

        assert claimed is not None
        assert claimed.id == reserved.id
        assert claimed.status == "generating"
        assert claimed.visibility == "visible"


def test_prepared_exam_candidate_prefers_active_ready_stock() -> None:
    engine = _engine()
    now = utcnow()
    with Session(engine) as session:
        ready = ExamPaper(
            subject="math",
            user_id="user-a",
            exam_mode="web_practice",
            status="ready",
            visibility="hidden",
            generation_origin="prewarm",
            config_hash="hash-a",
            total_items=8,
            prepared_at=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=2),
            updated_at=now - timedelta(hours=1),
        )
        session.add(ready)
        session.add(
            ExamPaper(
                subject="math",
                user_id="user-a",
                exam_mode="web_practice",
                status="failed",
                visibility="hidden",
                generation_origin="prewarm",
                config_hash="hash-a",
                total_items=8,
                updated_at=now,
            )
        )
        session.commit()

        candidate = exams_repo.get_prepared_exam_candidate(
            session,
            subject="math",
            user_id="user-a",
            config_hash="hash-a",
        )

        assert candidate is not None
        assert candidate.id == ready.id


def test_study_guide_cache_upserts_by_exam_paper() -> None:
    engine = _engine()
    with Session(engine) as session:
        paper = ExamPaper(
            subject="math",
            user_id="user-a",
            exam_mode="web_practice",
            status="graded",
            visibility="visible",
            total_items=1,
        )
        session.add(paper)
        session.commit()
        session.refresh(paper)

        first = exams_repo.upsert_study_guide_cache(
            session,
            exam_paper_id=int(paper.id or 0),
            subject="math",
            user_id="user-a",
            status="completed",
            guide_json='{"overall_summary":"old"}',
            generated_at=utcnow(),
        )
        second = exams_repo.upsert_study_guide_cache(
            session,
            exam_paper_id=int(paper.id or 0),
            subject="math",
            user_id="user-a",
            status="completed",
            guide_json='{"overall_summary":"new"}',
            generated_at=utcnow(),
        )

        assert second.id == first.id
        assert exams_repo.get_study_guide_cache(session, exam_paper_id=int(paper.id or 0)).guide_json == '{"overall_summary":"new"}'
