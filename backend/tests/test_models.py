"""
测试数据模型：枚举、SQLModel 表模型创建和基本字段
"""

from datetime import datetime


class TestEnums:
    def test_parse_status_values(self):
        from app.repositories.models import ParseStatus
        assert ParseStatus.PENDING == "pending"
        assert ParseStatus.PARSING == "parsing"
        assert ParseStatus.PARSED == "parsed"
        assert ParseStatus.PARSE_FAILED == "parse_failed"

    def test_pipeline_stage_values(self):
        from app.repositories.models import PipelineStage
        assert PipelineStage.PENDING == "pending"
        assert PipelineStage.CLEANED == "cleaned"
        assert PipelineStage.OUTLINED == "outlined"
        assert PipelineStage.STORED == "stored"
        assert PipelineStage.CHUNKED == "chunked"
        assert PipelineStage.EMBEDDED == "embedded"
        assert PipelineStage.FAILED == "failed"

    def test_question_type_values(self):
        from app.repositories.models import QuestionType
        assert QuestionType.SINGLE_CHOICE == "single_choice"
        assert QuestionType.FILL_BLANK == "fill_blank"
        assert QuestionType.SHORT_ANSWER == "short_answer"

    def test_difficulty_values(self):
        from app.repositories.models import Difficulty
        assert Difficulty.EASY == "easy"
        assert Difficulty.MEDIUM == "medium"
        assert Difficulty.HARD == "hard"


class TestModelDefaults:
    def test_raw_file_defaults(self):
        from app.repositories.models import RawFile, ParseStatus
        rf = RawFile(subject="math", filename="test.pdf", filetype="pdf", file_path="/tmp/test.pdf")
        assert rf.parse_status == ParseStatus.PENDING
        assert rf.id is None

    def test_knowledge_defaults(self):
        from app.repositories.models import Knowledge, PipelineStage
        k = Knowledge(subject="math", raw_file_id=1, title="Test")
        assert k.pipeline_stage == PipelineStage.PENDING
        assert k.markdown_content == ""

    def test_chat_message_defaults(self):
        from app.repositories.models import ChatMessage
        msg = ChatMessage(subject="math", turn_id="uuid-123", role="user", content="hello")
        assert msg.user_id == "local"
        assert msg.contexts is None

    def test_user_profile_defaults(self):
        from app.repositories.models import UserProfile
        p = UserProfile(subject="math", knowledge_point="algebra")
        assert p.user_id == "local"
        assert p.mastery is None
        assert p.attempts == 0
        assert p.correct == 0


class TestModelPersistence:
    def test_raw_file_crud(self, session):
        from app.repositories.models import RawFile
        rf = RawFile(subject="math", filename="test.pdf", filetype="pdf", file_path="/tmp/test.pdf")
        session.add(rf)
        session.commit()
        session.refresh(rf)
        assert rf.id is not None
        assert rf.id > 0

    def test_knowledge_with_foreign_key(self, session):
        from app.repositories.models import RawFile, Knowledge
        rf = RawFile(subject="math", filename="test.pdf", filetype="pdf", file_path="/tmp/test.pdf")
        session.add(rf)
        session.commit()
        session.refresh(rf)

        k = Knowledge(subject="math", raw_file_id=rf.id, title="Test Knowledge")
        session.add(k)
        session.commit()
        session.refresh(k)
        assert k.id is not None
        assert k.raw_file_id == rf.id

    def test_all_tables_created(self, engine):
        """验证所有 11 个表都已创建。"""
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        expected = {
            "raw_file", "knowledge", "chunk", "knowledge_graph_node",
            "chat_message", "exam", "question", "exam_submission",
            "answer_record", "mistake", "user_profile",
        }
        assert expected.issubset(tables)
