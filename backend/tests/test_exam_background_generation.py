from __future__ import annotations

from datetime import timedelta

from sqlmodel import Session, SQLModel, create_engine

from app.api.exams import _reserve_exam_prewarm_paper
from app.models import (
    ExamPaper,
    ExamPaperItem,
    ExamStudyGuideCache,
    QuestionKnowledgeUnitLink,
    QuestionTemplate,
)
from app.repositories import exams_repo
from app.utils.time import utcnow


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(
        engine,
        tables=[
            QuestionTemplate.__table__,
            ExamPaper.__table__,
            ExamPaperItem.__table__,
            QuestionKnowledgeUnitLink.__table__,
            ExamStudyGuideCache.__table__,
        ],
    )
    return engine


def test_hidden_prepared_exam_is_excluded_until_claimed() -> None:
    engine = _engine()
    now = utcnow()
    with Session(engine) as session:
        visible = ExamPaper(
            course_id="course_math00000000",
            user_id="user-a",
            exam_mode="web_practice",
            status="ready",
            visibility="visible",
            generation_origin="user",
            total_items=3,
        )
        hidden = ExamPaper(
            course_id="course_math00000000",
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
            course_id="course_math00000000",
            user_id="user-a",
            limit=20,
            offset=0,
        )
        assert total == 1
        assert [row.visibility for row in rows] == ["visible"]

        claimed = exams_repo.claim_prepared_exam_paper(
            session,
            course_id="course_math00000000",
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
            course_id="course_math00000000",
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
                course_id="course_math00000000",
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
                course_id="course_math00000000",
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
            course_id="course_math00000000",
            user_id="user-a",
            config_hash="hash-a",
        )
        assert exams_repo.has_active_prepared_exam(
            session,
            course_id="course_math00000000",
            user_id="user-a",
            config_hash="hash-b",
        )

        claimed = exams_repo.claim_prepared_exam_paper(
            session,
            course_id="course_math00000000",
            user_id="user-a",
            config_hash="hash-b",
        )
        assert claimed is not None
        assert claimed.status == "generating"
        assert claimed.visibility == "visible"


def test_reserved_in_progress_prewarm_is_visible_and_reused() -> None:
    engine = _engine()
    with Session(engine) as session:
        config_snapshot = {"version": 1, "course": "math", "num_questions": 8}
        reserved, created = _reserve_exam_prewarm_paper(
            session,
            course_id="course_math00000000",
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
        assert reserved.visibility == "visible"
        assert reserved.generation_origin == "prewarm"
        assert reserved.status == "generating"

        repeated, repeated_created = _reserve_exam_prewarm_paper(
            session,
            course_id="course_math00000000",
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

        reused = exams_repo.get_visible_active_exam_candidate(
            session,
            course_id="course_math00000000",
            user_id="user-a",
            config_hash="hash-a",
            question_count=8,
        )
        mismatched = exams_repo.get_visible_active_exam_candidate(
            session,
            course_id="course_math00000000",
            user_id="user-a",
            config_hash="hash-a",
            question_count=10,
        )

        assert reused is not None
        assert reused.id == reserved.id
        assert reused.status == "generating"
        assert reused.visibility == "visible"
        assert mismatched is None


def test_visible_active_exam_candidate_ignores_stale_generating_stock() -> None:
    engine = _engine()
    now = utcnow()
    with Session(engine) as session:
        stale = ExamPaper(
            course_id="course_math00000000",
            user_id="user-a",
            exam_mode="web_practice",
            status="generating",
            visibility="visible",
            generation_origin="prewarm",
            config_hash="hash-a",
            total_items=8,
            updated_at=now - timedelta(minutes=30),
        )
        fresh = ExamPaper(
            course_id="course_math00000000",
            user_id="user-a",
            exam_mode="web_practice",
            status="generating",
            visibility="visible",
            generation_origin="prewarm",
            config_hash="hash-b",
            total_items=8,
            updated_at=now - timedelta(minutes=1),
        )
        session.add(stale)
        session.add(fresh)
        session.commit()

        assert exams_repo.get_visible_active_exam_candidate(
            session,
            course_id="course_math00000000",
            user_id="user-a",
            config_hash="hash-a",
            question_count=8,
            stale_before=now - timedelta(minutes=20),
        ) is None
        reusable = exams_repo.get_visible_active_exam_candidate(
            session,
            course_id="course_math00000000",
            user_id="user-a",
            config_hash="hash-b",
            question_count=8,
            stale_before=now - timedelta(minutes=20),
        )
        assert reusable is not None
        assert reusable.id == fresh.id


def test_prepared_exam_candidate_prefers_active_ready_stock() -> None:
    engine = _engine()
    now = utcnow()
    with Session(engine) as session:
        ready = ExamPaper(
            course_id="course_math00000000",
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
                course_id="course_math00000000",
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
            course_id="course_math00000000",
            user_id="user-a",
            config_hash="hash-a",
            question_count=8,
        )
        mismatched = exams_repo.get_prepared_exam_candidate(
            session,
            course_id="course_math00000000",
            user_id="user-a",
            config_hash="hash-a",
            question_count=10,
        )

        assert candidate is not None
        assert candidate.id == ready.id
        assert mismatched is None


def test_study_guide_cache_upserts_by_exam_paper() -> None:
    engine = _engine()
    with Session(engine) as session:
        paper = ExamPaper(
            course_id="course_math00000000",
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
            course_id="course_math00000000",
            user_id="user-a",
            status="completed",
            guide_json='{"overall_summary":"old"}',
            generated_at=utcnow(),
        )
        second = exams_repo.upsert_study_guide_cache(
            session,
            exam_paper_id=int(paper.id or 0),
            course_id="course_math00000000",
            user_id="user-a",
            status="completed",
            guide_json='{"overall_summary":"new"}',
            generated_at=utcnow(),
        )

        assert second.id == first.id
        assert exams_repo.get_study_guide_cache(session, exam_paper_id=int(paper.id or 0)).guide_json == '{"overall_summary":"new"}'


def test_list_items_by_papers_batches_and_preserves_order() -> None:
    engine = _engine()
    with Session(engine) as session:
        template = exams_repo.create_question_template(
            session,
            QuestionTemplate(
                course_id="course_math00000000",
                question_type="single_choice",
                difficulty="easy",
                stem="template stem",
                stem_hash="template-hash",
                answer="A",
                explanation="explain",
            ),
        )
        first_paper = ExamPaper(
            course_id="course_math00000000",
            user_id="user-a",
            exam_mode="web_practice",
            status="ready",
            visibility="visible",
            total_items=2,
        )
        second_paper = ExamPaper(
            course_id="course_math00000000",
            user_id="user-a",
            exam_mode="web_practice",
            status="ready",
            visibility="visible",
            total_items=1,
        )
        session.add(first_paper)
        session.add(second_paper)
        session.commit()
        session.refresh(first_paper)
        session.refresh(second_paper)

        session.add_all([
            ExamPaperItem(
                exam_paper_id=int(first_paper.id or 0),
                question_template_id=int(template.id or 0),
                item_order=2,
                stem_snapshot="second",
                answer_snapshot="B",
                explanation_snapshot="explain",
                difficulty="medium",
                question_type="single_choice",
            ),
            ExamPaperItem(
                exam_paper_id=int(first_paper.id or 0),
                question_template_id=int(template.id or 0),
                item_order=1,
                stem_snapshot="first",
                answer_snapshot="A",
                explanation_snapshot="explain",
                difficulty="easy",
                question_type="single_choice",
            ),
            ExamPaperItem(
                exam_paper_id=int(second_paper.id or 0),
                question_template_id=int(template.id or 0),
                item_order=1,
                stem_snapshot="only",
                answer_snapshot="C",
                explanation_snapshot="explain",
                difficulty="hard",
                question_type="fill_blank",
            ),
        ])
        session.commit()

        grouped = exams_repo.list_items_by_papers(
            session,
            [int(second_paper.id or 0), int(first_paper.id or 0), int(first_paper.id or 0), 0],
        )

        assert list(grouped) == [int(first_paper.id or 0), int(second_paper.id or 0)]
        assert [item.item_order for item in grouped[int(first_paper.id or 0)]] == [1, 2]
        assert [item.stem_snapshot for item in grouped[int(second_paper.id or 0)]] == ["only"]


def test_find_template_by_stem_hash_respects_course_and_unit_link() -> None:
    engine = _engine()
    with Session(engine) as session:
        course_template = exams_repo.create_question_template(
            session,
            QuestionTemplate(
                course_id="course_math00000000",
                question_type="single_choice",
                difficulty="easy",
                stem="shared stem",
                stem_hash="same-hash",
                answer="A",
                explanation="explain",
            ),
        )
        other_course_template = exams_repo.create_question_template(
            session,
            QuestionTemplate(
                course_id="course_physics000000",
                question_type="single_choice",
                difficulty="easy",
                stem="shared stem",
                stem_hash="same-hash",
                answer="B",
                explanation="explain",
            ),
        )
        exams_repo.replace_question_template_links(
            session,
            template_id=int(course_template.id or 0),
            refs=[{"knowledge_unit_id": 1, "coverage_weight": 1.0}],
        )
        exams_repo.replace_question_template_links(
            session,
            template_id=int(other_course_template.id or 0),
            refs=[{"knowledge_unit_id": 2, "coverage_weight": 1.0}],
        )

        matched = exams_repo.find_template_by_stem_hash(
            session,
            "course_math00000000",
            1,
            "same-hash",
        )
        assert matched is not None
        assert matched.id == course_template.id
        assert exams_repo.find_template_by_stem_hash(
            session,
            "course_math00000000",
            2,
            "same-hash",
        ) is None
