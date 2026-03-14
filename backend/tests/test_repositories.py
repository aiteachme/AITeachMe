"""
测试仓储层 CRUD 操作
"""

import uuid
import pytest
from app.repositories.models import (
    RawFile, Knowledge, Chunk, KnowledgeGraphNode,
    ChatMessage, Exam, Question, ExamSubmission, AnswerRecord,
    Mistake, UserProfile, ParseStatus, PipelineStage,
)


# ─── IngestRepo ───


class TestIngestRepo:
    def test_create_raw_file(self, session):
        from app.repositories.ingest_repo import create_raw_file
        rf = RawFile(subject="math", filename="test.pdf", filetype="pdf", file_path="/tmp/test.pdf")
        result = create_raw_file(session, rf)
        assert result.id is not None
        assert result.subject == "math"

    def test_get_raw_file_by_id(self, session):
        from app.repositories.ingest_repo import create_raw_file, get_raw_file_by_id
        rf = create_raw_file(session, RawFile(
            subject="math", filename="test.pdf", filetype="pdf", file_path="/tmp/test.pdf"
        ))
        found = get_raw_file_by_id(session, rf.id)
        assert found is not None
        assert found.filename == "test.pdf"

    def test_get_raw_file_not_found(self, session):
        from app.repositories.ingest_repo import get_raw_file_by_id
        assert get_raw_file_by_id(session, 9999) is None

    def test_update_parse_status(self, session):
        from app.repositories.ingest_repo import create_raw_file, update_parse_status
        rf = create_raw_file(session, RawFile(
            subject="math", filename="test.pdf", filetype="pdf", file_path="/tmp/test.pdf"
        ))
        updated = update_parse_status(session, rf.id, ParseStatus.PARSED)
        assert updated.parse_status == ParseStatus.PARSED

    def test_delete_raw_file(self, session):
        from app.repositories.ingest_repo import create_raw_file, delete_raw_file, get_raw_file_by_id
        rf = create_raw_file(session, RawFile(
            subject="math", filename="test.pdf", filetype="pdf", file_path="/tmp/test.pdf"
        ))
        assert delete_raw_file(session, rf.id) is True
        assert get_raw_file_by_id(session, rf.id) is None

    def test_list_raw_files_by_subject(self, session):
        from app.repositories.ingest_repo import create_raw_file, list_raw_files_by_subject
        for i in range(3):
            create_raw_file(session, RawFile(
                subject="math", filename=f"file{i}.pdf", filetype="pdf", file_path=f"/tmp/file{i}.pdf"
            ))
        create_raw_file(session, RawFile(
            subject="physics", filename="other.pdf", filetype="pdf", file_path="/tmp/other.pdf"
        ))
        items, total = list_raw_files_by_subject(session, "math")
        assert total == 3
        assert len(items) == 3

    def test_list_raw_files_pagination(self, session):
        from app.repositories.ingest_repo import create_raw_file, list_raw_files_by_subject
        for i in range(5):
            create_raw_file(session, RawFile(
                subject="math", filename=f"file{i}.pdf", filetype="pdf", file_path=f"/tmp/file{i}.pdf"
            ))
        items, total = list_raw_files_by_subject(session, "math", limit=2, offset=0)
        assert total == 5
        assert len(items) == 2


# ─── KnowledgeRepo ───


class TestKnowledgeRepo:
    def _create_raw_file(self, session):
        rf = RawFile(subject="math", filename="test.pdf", filetype="pdf", file_path="/tmp/test.pdf")
        session.add(rf)
        session.commit()
        session.refresh(rf)
        return rf

    def test_create_knowledge(self, session):
        from app.repositories.knowledge_repo import create_knowledge
        rf = self._create_raw_file(session)
        k = create_knowledge(session, Knowledge(subject="math", raw_file_id=rf.id, title="Test"))
        assert k.id is not None

    def test_get_knowledge_by_raw_file_id(self, session):
        from app.repositories.knowledge_repo import create_knowledge, get_knowledge_by_raw_file_id
        rf = self._create_raw_file(session)
        create_knowledge(session, Knowledge(subject="math", raw_file_id=rf.id, title="Test"))
        found = get_knowledge_by_raw_file_id(session, rf.id)
        assert found is not None
        assert found.title == "Test"

    def test_update_pipeline_stage(self, session):
        from app.repositories.knowledge_repo import create_knowledge, update_pipeline_stage
        rf = self._create_raw_file(session)
        k = create_knowledge(session, Knowledge(subject="math", raw_file_id=rf.id, title="Test"))
        updated = update_pipeline_stage(session, k.id, PipelineStage.CLEANED)
        assert updated.pipeline_stage == PipelineStage.CLEANED

    def test_bulk_create_graph_nodes(self, session):
        from app.repositories.knowledge_repo import create_knowledge, bulk_create_graph_nodes
        rf = self._create_raw_file(session)
        k = create_knowledge(session, Knowledge(subject="math", raw_file_id=rf.id, title="Test"))
        nodes = [
            KnowledgeGraphNode(knowledge_id=k.id, title="Chapter 1", level=1, order_index=0),
            KnowledgeGraphNode(knowledge_id=k.id, title="Section 1.1", level=2, order_index=1),
        ]
        result = bulk_create_graph_nodes(session, nodes)
        assert len(result) == 2
        assert all(n.id is not None for n in result)

    def test_bulk_create_chunks(self, session):
        from app.repositories.knowledge_repo import create_knowledge, bulk_create_chunks
        rf = self._create_raw_file(session)
        k = create_knowledge(session, Knowledge(subject="math", raw_file_id=rf.id, title="Test"))
        chunks = [
            Chunk(knowledge_id=k.id, title="Intro", level=1, header_path="Intro", chunk_index=0, content="Hello"),
            Chunk(knowledge_id=k.id, title="Body", level=2, header_path="Intro > Body", chunk_index=1, content="World"),
        ]
        result = bulk_create_chunks(session, chunks)
        assert len(result) == 2

    def test_list_knowledge_by_subject(self, session):
        from app.repositories.knowledge_repo import create_knowledge, list_knowledge_by_subject
        rf1 = self._create_raw_file(session)
        create_knowledge(session, Knowledge(subject="math", raw_file_id=rf1.id, title="K1"))

        rf2 = RawFile(subject="physics", filename="p.pdf", filetype="pdf", file_path="/tmp/p.pdf")
        session.add(rf2)
        session.commit()
        session.refresh(rf2)
        create_knowledge(session, Knowledge(subject="physics", raw_file_id=rf2.id, title="K2"))

        items, total = list_knowledge_by_subject(session, "math")
        assert total == 1
        assert items[0].title == "K1"


# ─── ChatRepo ───


class TestChatRepo:
    def test_create_message_pair(self, session):
        from app.repositories.chat_repo import create_message_pair
        user_msg, asst_msg = create_message_pair(
            session, subject="math", user_content="What is 2+2?",
            assistant_content="4", contexts=[{"chunk_id": 1}],
        )
        assert user_msg.role == "user"
        assert asst_msg.role == "assistant"
        assert user_msg.turn_id == asst_msg.turn_id
        assert user_msg.contexts is None
        assert asst_msg.contexts == [{"chunk_id": 1}]

    def test_get_recent_turns(self, session):
        from app.repositories.chat_repo import create_message_pair, get_recent_turns
        for i in range(3):
            create_message_pair(
                session, subject="math",
                user_content=f"Q{i}", assistant_content=f"A{i}",
            )
        msgs = get_recent_turns(session, "math", n_turns=2)
        # 2 turns × 2 messages = 4 messages
        assert len(msgs) == 4

    def test_list_messages_by_subject(self, session):
        from app.repositories.chat_repo import create_message_pair, list_messages_by_subject
        create_message_pair(session, subject="math", user_content="Q", assistant_content="A")
        create_message_pair(session, subject="physics", user_content="Q2", assistant_content="A2")
        items, total = list_messages_by_subject(session, "math")
        assert total == 2  # user + assistant
        assert len(items) == 2


# ─── ExamRepo ───


class TestExamRepo:
    def _create_exam_with_questions(self, session):
        from app.repositories.exam_repo import create_exam_with_questions
        exam = Exam(subject="math")
        questions = [
            Question(
                exam_id=0, question_key="q1", type="single_choice",
                stem="1+1=?", options=["1", "2", "3"], answer="2",
                explanation="Basic", knowledge_point="arithmetic", difficulty="easy",
            ),
            Question(
                exam_id=0, question_key="q2", type="fill_blank",
                stem="2+2=___", answer="4",
                explanation="Basic", knowledge_point="arithmetic", difficulty="easy",
            ),
        ]
        return create_exam_with_questions(session, exam, questions)

    def test_create_exam_with_questions(self, session):
        exam, questions = self._create_exam_with_questions(session)
        assert exam.id is not None
        assert len(questions) == 2
        assert all(q.exam_id == exam.id for q in questions)

    def test_get_exam_by_id(self, session):
        from app.repositories.exam_repo import get_exam_by_id
        exam, _ = self._create_exam_with_questions(session)
        found = get_exam_by_id(session, exam.id)
        assert found is not None
        assert found.subject == "math"

    def test_get_questions_by_exam_id(self, session):
        from app.repositories.exam_repo import get_questions_by_exam_id
        exam, _ = self._create_exam_with_questions(session)
        qs = get_questions_by_exam_id(session, exam.id)
        assert len(qs) == 2

    def test_create_submission_with_records(self, session):
        from app.repositories.exam_repo import create_submission_with_records
        exam, questions = self._create_exam_with_questions(session)
        submission = ExamSubmission(exam_id=exam.id, score=50.0)
        records = [
            AnswerRecord(submission_id=0, question_id=questions[0].id, user_answer="2", is_correct=True),
            AnswerRecord(submission_id=0, question_id=questions[1].id, user_answer="3", is_correct=False),
        ]
        sub, recs = create_submission_with_records(session, submission, records)
        assert sub.id is not None
        assert len(recs) == 2

    def test_create_and_list_mistakes(self, session):
        from app.repositories.exam_repo import (
            create_submission_with_records, bulk_create_mistakes, list_mistakes_by_subject,
        )
        exam, questions = self._create_exam_with_questions(session)
        submission = ExamSubmission(exam_id=exam.id, score=50.0)
        records = [
            AnswerRecord(submission_id=0, question_id=questions[0].id, user_answer="1", is_correct=False),
        ]
        sub, recs = create_submission_with_records(session, submission, records)
        mistakes = [Mistake(answer_record_id=recs[0].id, analysis="Wrong choice")]
        bulk_create_mistakes(session, mistakes)

        items, total = list_mistakes_by_subject(session, "math")
        assert total == 1
        assert items[0]["analysis"] == "Wrong choice"

    def test_list_exam_history(self, session):
        from app.repositories.exam_repo import list_exam_history_by_subject
        self._create_exam_with_questions(session)
        items, total = list_exam_history_by_subject(session, "math")
        assert total == 1


# ─── ProfileRepo ───


class TestProfileRepo:
    def test_upsert_create(self, session):
        from app.repositories.profile_repo import upsert_profile
        p = upsert_profile(
            session, user_id="local", subject="math",
            knowledge_point="algebra", attempts=10, correct=7,
        )
        assert p.id is not None
        assert p.mastery == pytest.approx(0.7)

    def test_upsert_update(self, session):
        from app.repositories.profile_repo import upsert_profile
        upsert_profile(
            session, user_id="local", subject="math",
            knowledge_point="algebra", attempts=10, correct=7,
        )
        p = upsert_profile(
            session, user_id="local", subject="math",
            knowledge_point="algebra", attempts=20, correct=15,
        )
        assert p.mastery == pytest.approx(0.75)
        assert p.attempts == 20

    def test_upsert_zero_attempts(self, session):
        from app.repositories.profile_repo import upsert_profile
        p = upsert_profile(
            session, user_id="local", subject="math",
            knowledge_point="algebra", attempts=0, correct=0,
        )
        assert p.mastery is None

    def test_list_profiles_by_subject(self, session):
        from app.repositories.profile_repo import upsert_profile, list_profiles_by_subject
        upsert_profile(session, user_id="local", subject="math", knowledge_point="algebra", attempts=10, correct=7)
        upsert_profile(session, user_id="local", subject="math", knowledge_point="geometry", attempts=5, correct=2)
        upsert_profile(session, user_id="local", subject="physics", knowledge_point="mechanics", attempts=3, correct=3)

        items, total = list_profiles_by_subject(session, "math")
        assert total == 2

    def test_get_weak_points(self, session):
        from app.repositories.profile_repo import upsert_profile, get_weak_points
        upsert_profile(session, user_id="local", subject="math", knowledge_point="algebra", attempts=10, correct=7)
        upsert_profile(session, user_id="local", subject="math", knowledge_point="geometry", attempts=10, correct=3)
        upsert_profile(session, user_id="local", subject="math", knowledge_point="calculus", attempts=10, correct=9)

        weak = get_weak_points(session, "math")
        assert len(weak) == 1  # only geometry (0.3 < 0.6)
        assert weak[0].knowledge_point == "geometry"

    def test_get_weak_points_excludes_null_mastery(self, session):
        from app.repositories.profile_repo import upsert_profile, get_weak_points
        upsert_profile(session, user_id="local", subject="math", knowledge_point="untested", attempts=0, correct=0)
        weak = get_weak_points(session, "math")
        assert len(weak) == 0
