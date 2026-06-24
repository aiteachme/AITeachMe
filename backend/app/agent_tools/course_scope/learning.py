"""当前课程内的学习只读工具。"""

from __future__ import annotations

from app.shared.infra.database import managed_session
from app.shared.infra.tools.decorator import tool
from app.workflows.interact.chat.lib.course_readers import (
    read_course_document_context,
    read_course_exam_context,
    read_course_profile_context,
)


@tool(
    "read_course_document",
    "读取当前课程已发布知识文档。",
    usage=(
        "当用户询问当前文档、章节大纲、某个标题或课程文档中已有主题时使用。"
    ),
    tags=["course", "learning", "knowledge_doc", "read"],
    source="agent_tools.course_scope",
    risk_level="low",
    scopes=["course", "knowledge_doc:read"],
    requires_course=True,
    hidden_args=["course_id"],
)
async def read_course_document_tool(
    doc_id: str = "",
    anchor_id: str = "",
    topic: str = "",
    mode: str = "",
    course_id: str | None = None,
) -> str:
    resolved_course_id = (course_id or "").strip()
    if not resolved_course_id:
        return "需要进入课程后才能读取知识文档。"
    with managed_session() as session:
        return read_course_document_context(
            session,
            course_id=resolved_course_id,
            doc_id=doc_id,
            anchor_id=anchor_id,
            topic=topic,
            mode=mode,
        )


@tool(
    "read_course_profile",
    "读取当前用户的课程画像摘要。",
    usage=(
        "当用户询问现在该补哪里、哪里薄弱、掌握情况或复习提醒时使用。"
    ),
    tags=["course", "learning", "profile", "read"],
    source="agent_tools.course_scope",
    risk_level="low",
    scopes=["course", "profile:read"],
    requires_course=True,
    hidden_args=["course_id", "user_id"],
)
async def read_course_profile_tool(
    focus: str = "",
    limit: int = 8,
    course_id: str | None = None,
    user_id: str | None = None,
) -> str:
    resolved_course_id = (course_id or "").strip()
    resolved_user_id = (user_id or "").strip()
    if not resolved_course_id:
        return "需要进入课程后才能读取课程画像。"
    if not resolved_user_id:
        return "需要确认当前用户身份后才能读取课程画像，请登录后重试。"
    with managed_session() as session:
        return read_course_profile_context(
            session,
            course_id=resolved_course_id,
            user_id=resolved_user_id,
            focus=focus,
            limit=limit,
        )


@tool(
    "read_course_exams",
    "读取当前课程的最近测验、指定试卷、指定题目或近期错题。",
    usage=(
        "当用户询问最近测验、某张试卷、某道题、答案解析或错题共性时使用。"
    ),
    tags=["course", "learning", "exam", "read"],
    source="agent_tools.course_scope",
    risk_level="low",
    scopes=["course", "exam:read"],
    requires_course=True,
    hidden_args=["course_id", "user_id"],
)
async def read_course_exams_tool(
    focus: str = "",
    paper_id: int = 0,
    question_order: int = 0,
    limit: int = 3,
    course_id: str | None = None,
    user_id: str | None = None,
) -> str:
    resolved_course_id = (course_id or "").strip()
    resolved_user_id = (user_id or "").strip()
    if not resolved_course_id:
        return "需要进入课程后才能读取测验记录。"
    if not resolved_user_id:
        return "需要确认当前用户身份后才能读取测验记录，请登录后重试。"
    with managed_session() as session:
        return read_course_exam_context(
            session,
            course_id=resolved_course_id,
            user_id=resolved_user_id,
            focus=focus,
            paper_id=paper_id or None,
            question_order=question_order or None,
            limit=limit,
        )
