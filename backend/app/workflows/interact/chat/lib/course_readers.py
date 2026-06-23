"""Interact 课程只读上下文读取器。"""

from __future__ import annotations

import re
from datetime import datetime

from sqlmodel import Session, select

from app.models import ExamPaper, ExamPaperItem, KnowledgeDoc, KnowledgeUnit
from app.repositories import exams_repo, profile_repo
from app.repositories.knowledge import docgen_repo
from app.workflows.profile.common.lib.course_profile import build_course_profile_summary

_MAX_RESULT_CHARS = 2200
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def read_course_document_context(
    session: Session,
    *,
    course_id: str,
    doc_id: str | None = None,
    anchor_id: str | None = None,
    topic: str | None = None,
    mode: str | None = None,
) -> str:
    """读取当前课程已发布知识文档的一小段上下文。"""

    docs = docgen_repo.get_current_published_docs(session, course_id)
    if not docs:
        return "当前课程暂无已发布知识文档。"

    if (mode or "").strip().lower() in {"outline", "toc", "catalog", "目录", "大纲"}:
        return _clip(_format_docs_outline(docs), _MAX_RESULT_CHARS)

    doc = _pick_doc(docs, doc_id=doc_id, topic=topic)
    if doc is None:
        section = _section_from_any_doc(docs, anchor_id or topic or "")
        if section:
            return _clip(section, _MAX_RESULT_CHARS)
        return _clip(_format_docs_outline(docs), _MAX_RESULT_CHARS)

    body = _doc_body(doc)
    section = _section_by_heading(body, anchor_id or topic or "")
    lines = [f"知识文档：{_clean(doc.title) or f'文档 {doc.id}'}"]
    if doc.summary:
        lines.append(f"摘要：{_clean(doc.summary)}")
    if section:
        lines.extend(["", section])
    else:
        outline = _outline_lines(body, limit=8)
        if outline:
            lines.extend(["", "主要章节：", *outline])
        excerpt = _first_excerpt(body)
        if excerpt:
            lines.extend(["", f"内容摘录：{excerpt}"])
    return _clip("\n".join(lines), _MAX_RESULT_CHARS)


def _section_from_any_doc(docs: list[KnowledgeDoc], heading: str) -> str:
    if not _anchor_key(heading):
        return ""
    for doc in docs:
        section = _section_by_heading(_doc_body(doc), heading)
        if section:
            title = _clean(doc.title) or f"文档 {doc.id}"
            return f"知识文档：{title}\n\n{section}"
    return ""


def read_course_profile_context(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    focus: str | None = None,
    limit: int = 8,
) -> str:
    """读取课程画像摘要、薄弱点和复习提醒。"""

    limit = _limit(limit, default=8, maximum=10)
    summary = build_course_profile_summary(session, course_id=course_id, user_id=user_id)
    weak_units = profile_repo.list_weak_knowledge_unit_summaries(
        session,
        user_id=user_id,
        course_id=course_id,
        limit=limit,
    )
    pending = profile_repo.list_pending_reviews(
        session,
        user_id=user_id,
        course_id=course_id,
        target_kind="knowledge_unit",
    )[:limit]
    wrong_items = profile_repo.list_recent_wrong_attempt_summaries(
        session,
        user_id=user_id,
        course_id=course_id,
        limit=3,
    )

    lines = [
        "课程画像摘要",
        f"- 平均掌握度：{_percent(summary.avg_mastery)}",
        f"- 薄弱知识点：{summary.weak_knowledge_unit_count} 个",
        f"- 复习提醒：{summary.pending_review_count} 个，到期 {summary.due_review_count} 个",
        f"- 推荐练习：{_exam_mode(summary.recommended_exam_mode)}，约 {summary.recommended_question_count or 0} 题",
    ]
    if focus:
        lines.insert(1, f"关注点：{_clean(focus)}")
    if weak_units:
        lines.extend(["", "优先补的知识点："])
        lines.extend(f"- {name}：掌握度 {_percent(score)}" for name, score in weak_units)
    if pending:
        lines.extend(["", "复习提醒："])
        for state in pending[:5]:
            lines.append(f"- {_unit_name(session, state.knowledge_unit_id)}：{_clean(state.review_reason or '需要回顾')}")
    if wrong_items:
        lines.extend(["", "近期错题线索："])
        for item in wrong_items:
            lines.append(f"- {_clip(_clean(item.get('question_stem', '')), 120)}")
    return _clip("\n".join(lines), _MAX_RESULT_CHARS)


def read_course_exam_context(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    focus: str | None = None,
    paper_id: int | None = None,
    question_order: int | None = None,
    limit: int = 3,
) -> str:
    """读取最近测验、指定试卷或近期错题摘要。"""

    limit = _limit(limit, default=3, maximum=6)
    if paper_id:
        paper = exams_repo.get_exam_paper_by_id(session, int(paper_id))
        if paper is None or paper.course_id != course_id or paper.user_id != user_id or paper.visibility == "hidden":
            return "未找到可读取的测验或试卷。"
        return _clip(_format_paper(paper, exams_repo.list_items_by_paper(session, int(paper.id or 0)), question_order), _MAX_RESULT_CHARS)

    if (focus or "").strip().lower() in {"wrong", "mistake", "mistakes", "错题", "最近错题"}:
        return _clip(_format_wrong_items(session, course_id=course_id, user_id=user_id, limit=limit), _MAX_RESULT_CHARS)

    papers, total = exams_repo.list_exam_papers(
        session,
        course_id=course_id,
        user_id=user_id,
        limit=limit,
        offset=0,
    )
    if not papers:
        return "当前暂无测验或试卷记录。"

    grouped = exams_repo.list_items_by_papers(session, [int(paper.id or 0) for paper in papers])
    lines = [f"最近测验/试卷：共 {total} 份。"]
    for paper in papers:
        items = grouped.get(int(paper.id or 0), [])
        answered = [item for item in items if item.is_correct is not None]
        wrong_count = sum(1 for item in answered if item.is_correct is False)
        lines.append(
            f"- #{paper.id} {_exam_mode(paper.exam_mode)}｜{_status(paper.status)}｜"
            f"{len(items) or paper.total_items} 题｜正确 {_ratio(answered)}｜错题 {wrong_count}｜{_time(paper.created_at)}"
        )
    return _clip("\n".join(lines), _MAX_RESULT_CHARS)


def _pick_doc(docs: list[KnowledgeDoc], *, doc_id: str | None, topic: str | None) -> KnowledgeDoc | None:
    wanted_id = _int_or_none(doc_id)
    if wanted_id is not None:
        return next((doc for doc in docs if doc.id == wanted_id), None)
    needle = _clean(topic).casefold()
    if needle:
        return next((doc for doc in docs if needle in f"{doc.title} {doc.summary}".casefold()), None)
    return docs[0] if len(docs) == 1 else None


def _format_docs_outline(docs: list[KnowledgeDoc]) -> str:
    lines = [f"当前课程共有 {len(docs)} 篇已发布知识文档："]
    for doc in docs:
        lines.append(f"- #{doc.id} {_clean(doc.title) or '未命名文档'}")
        lines.extend(f"  {line}" for line in _outline_lines(_doc_body(doc), limit=3))
    return "\n".join(lines)


def _doc_body(doc: KnowledgeDoc) -> str:
    return str(doc.markdown_content or doc.content_markdown or "").strip()


def _section_by_heading(body: str, heading: str) -> str:
    needle = _anchor_key(heading)
    if not needle:
        return ""
    matches = list(_HEADING_RE.finditer(body or ""))
    for index, match in enumerate(matches):
        if needle not in _anchor_key(match.group(2)):
            continue
        start = match.start()
        level = len(match.group(1))
        end = len(body)
        for next_match in matches[index + 1 :]:
            if len(next_match.group(1)) <= level:
                end = next_match.start()
                break
        return _clip(body[start:end].strip(), 1100)
    return ""


def _outline_lines(body: str, *, limit: int) -> list[str]:
    lines: list[str] = []
    for match in _HEADING_RE.finditer(body or ""):
        if len(match.group(1)) > 3:
            continue
        lines.append("- " + _clean(match.group(2)))
        if len(lines) >= limit:
            break
    return lines


def _first_excerpt(body: str) -> str:
    cleaned = _clean(re.sub(r"^#{1,6}\s+.+$", "", body or "", flags=re.MULTILINE))
    return _clip(cleaned, 800)


def _format_paper(paper: ExamPaper, items: list[ExamPaperItem], question_order: int | None) -> str:
    if question_order:
        items = [item for item in items if item.item_order == question_order]
    if not items:
        return f"试卷 #{paper.id} 暂无可读取题目。"
    answered = [item for item in items if item.is_correct is not None]
    lines = [
        f"试卷 #{paper.id}：{_exam_mode(paper.exam_mode)}｜{_status(paper.status)}",
        f"题量：{len(items) if question_order else paper.total_items or len(items)}｜正确率：{_ratio(answered)}｜创建：{_time(paper.created_at)}",
    ]
    for item in items[:4]:
        lines.extend(["", _format_item(item)])
    return "\n".join(lines)


def _format_item(item: ExamPaperItem) -> str:
    lines = [
        f"Q{item.item_order:02d}｜{item.question_type}｜{item.difficulty}",
        f"题目：{_clip(_clean(item.stem_snapshot), 220)}",
        f"参考答案：{_clip(_clean(item.answer_snapshot), 140)}",
    ]
    if item.answer_content:
        lines.append(f"用户答案：{_clip(_clean(item.answer_content), 120)}")
    if item.is_correct is not None:
        lines.append("结果：" + ("正确" if item.is_correct else "错误"))
    if item.explanation_snapshot:
        lines.append(f"解析：{_clip(_clean(item.explanation_snapshot), 220)}")
    return "\n".join(lines)


def _format_wrong_items(session: Session, *, course_id: str, user_id: str, limit: int) -> str:
    items = profile_repo.list_recent_wrong_attempt_summaries(
        session,
        user_id=user_id,
        course_id=course_id,
        limit=limit,
    )
    if not items:
        return "当前暂无近期错题记录。"
    lines = ["近期错题摘要"]
    for index, item in enumerate(items, start=1):
        lines.append(f"{index}. {_clip(_clean(item.get('question_stem', '')), 150)}")
        lines.append(f"   参考答案：{_clip(_clean(item.get('correct_answer', '')), 100)}")
        if item.get("analysis"):
            lines.append(f"   线索：{_clip(_clean(item['analysis']), 120)}")
    return "\n".join(lines)


def _unit_name(session: Session, unit_id: int | None) -> str:
    if unit_id is None:
        return "未关联知识点"
    unit = session.exec(select(KnowledgeUnit).where(KnowledgeUnit.id == int(unit_id))).first()
    return _clean(unit.canonical_name) if unit is not None else f"知识点 #{unit_id}"


def _exam_mode(value: str | None) -> str:
    return {"web_practice": "网页练习", "paper_exam": "整卷练习", "quiz": "测验"}.get(str(value or ""), str(value or "练习"))


def _status(value: str | None) -> str:
    return {
        "draft": "草稿",
        "generating": "生成中",
        "ready": "可作答",
        "in_progress": "作答中",
        "submitted": "已提交",
        "graded": "已批改",
        "failed": "失败",
    }.get(str(value or ""), str(value or "未知"))


def _ratio(items: list[ExamPaperItem]) -> str:
    if not items:
        return "暂无作答"
    return f"{sum(1 for item in items if item.is_correct is True)}/{len(items)}"


def _percent(value: float | None) -> str:
    if value is None:
        return "暂无"
    return f"{max(0.0, min(1.0, float(value))) * 100:.0f}%"


def _time(value: datetime | None) -> str:
    return value.strftime("%m/%d %H:%M") if value is not None else "未知时间"


def _int_or_none(value: object) -> int | None:
    try:
        parsed = int(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _limit(value: int | None, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(maximum, parsed))


def _anchor_key(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", _clean(value).casefold())


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clip(value: str, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "…"


__all__ = [
    "read_course_document_context",
    "read_course_exam_context",
    "read_course_profile_context",
]
