from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.schemas.profile import CourseProfileSummary
from app.workflows.interact.chat.lib import course_readers


def test_read_course_document_returns_empty_state_without_published_docs(monkeypatch) -> None:
    monkeypatch.setattr(
        course_readers.docgen_repo,
        "get_current_published_docs",
        lambda session, course_id: [],
    )

    result = course_readers.read_course_document_context(
        object(),
        course_id="course_empty",
    )

    assert result == "当前课程暂无已发布知识文档。"


def test_read_course_document_can_find_section_across_multiple_docs(monkeypatch) -> None:
    docs = [
        SimpleNamespace(
            id=1,
            title="前置内容",
            summary="",
            markdown_content="# 前置内容\n这里不是目标章节。",
            content_markdown="",
        ),
        SimpleNamespace(
            id=2,
            title="核心文档",
            summary="",
            markdown_content="# 变量与数据类型\n变量用于保存程序运行中的数据。",
            content_markdown="",
        ),
    ]
    monkeypatch.setattr(
        course_readers.docgen_repo,
        "get_current_published_docs",
        lambda session, course_id: docs,
    )

    result = course_readers.read_course_document_context(
        object(),
        course_id="course_python",
        anchor_id="变量与数据类型",
    )

    assert "知识文档：核心文档" in result
    assert "变量用于保存程序运行中的数据" in result


def test_read_course_exams_returns_empty_state_without_papers(monkeypatch) -> None:
    monkeypatch.setattr(
        course_readers.exams_repo,
        "list_exam_papers",
        lambda session, **kwargs: ([], 0),
    )

    result = course_readers.read_course_exam_context(
        object(),
        course_id="course_empty",
        user_id="user_empty",
    )

    assert result == "当前暂无测验或试卷记录。"


def test_read_course_profile_empty_state_does_not_invent_weak_units(monkeypatch) -> None:
    monkeypatch.setattr(
        course_readers,
        "build_course_profile_summary",
        lambda session, **kwargs: CourseProfileSummary(
            course_id=kwargs["course_id"],
            generated_at=datetime.now(timezone.utc),
            avg_mastery=None,
            weak_knowledge_unit_count=0,
            pending_review_count=0,
            due_review_count=0,
            recommended_question_count=0,
        ),
    )
    monkeypatch.setattr(course_readers.profile_repo, "list_weak_knowledge_unit_summaries", lambda session, **kwargs: [])
    monkeypatch.setattr(course_readers.profile_repo, "list_pending_reviews", lambda session, **kwargs: [])
    monkeypatch.setattr(course_readers.profile_repo, "list_recent_wrong_attempt_summaries", lambda session, **kwargs: [])

    result = course_readers.read_course_profile_context(
        object(),
        course_id="course_empty",
        user_id="user_empty",
    )

    assert "课程画像摘要" in result
    assert "薄弱知识点：0 个" in result
    assert "优先补的知识点" not in result
    assert "近期错题线索" not in result
