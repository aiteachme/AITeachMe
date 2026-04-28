"""Prompt assembly for the interact workflow."""

from __future__ import annotations

import hashlib
import re
from typing import Literal

from app.schemas.chats import ChatSelectionContext
from app.schemas.llm import ASSISTANT, ChatMessage, USER
from app.shared.infra.observability.trace import traceable_with_context as traceable
from app.shared.infra.prompt_loader import populate_prompt
from app.shared.infra.strategies import StrategyMode
from app.shared.infra.llm_support.context_window import ContextWindowManager
from app.workflows.interact.chat.lib.intent import ChatPromptScene, resolve_prompt_scene
from app.workflows.interact.chat.prompts.prompts import get_strategy_instruction, get_system_prompt_template
from app.workflows.interact.chat.lib.types import (
    MistakeSummary,
    RecentMessage,
    RetrievedContext,
    SubjectContextSummary,
    WeakPointSummary,
)


_TOKEN_RE = re.compile(r"[\w]+|[\u4e00-\u9fff]", re.UNICODE)
_LOW_INFORMATION_TOKENS = {
    "一",
    "二",
    "三",
    "四",
    "五",
    "六",
    "七",
    "八",
    "九",
    "十",
    "第",
    "本",
    "章",
    "节",
    "与",
    "和",
    "及",
    "的",
    "了",
    "是",
    "在",
    "：",
}
_MAX_RELEVANT_WEAK_POINTS = 4
_MAX_RECENT_MISTAKES = 3
_MAX_RETRIEVAL_ITEMS_WITH_PRIMARY = 2
_MAX_RETRIEVAL_ITEMS_WITHOUT_PRIMARY = 4
_DOCUMENT_SELECTION_PRIMARY_CONTEXT_SUFFICIENT_CHARS = 360
_SubjectBackgroundMode = Literal["full", "chat_scope", "entry_context"]


@traceable(name="interact.build_chat_messages", run_type="prompt")
def build_chat_messages(
    *,
    subject: str,
    strategy_mode: StrategyMode,
    retrieval_results: list[RetrievedContext],
    recent_messages: list[RecentMessage],
    weak_points: list[WeakPointSummary],
    recent_mistakes: list[MistakeSummary],
    question: str,
    subject_context: SubjectContextSummary | None = None,
    source: str | None = None,
    selected_context: str | None = None,
    selection_context: ChatSelectionContext | None = None,
    source_chunk_id: int | None = None,
    context_window: ContextWindowManager | None = None,
) -> list[ChatMessage]:
    """Build the full LLM message list for one tutoring turn."""

    manager = context_window or ContextWindowManager()
    primary_context = _format_selected_context(source, selection_context, selected_context, source_chunk_id)
    has_primary_context = bool(primary_context.strip() and primary_context.strip() != "无。")
    prompt_scene = resolve_prompt_scene(
        question=question,
        source=source,
        has_primary_context=has_primary_context,
    )
    use_subject_grounding = prompt_scene != ChatPromptScene.GENERAL
    focus_text = _build_focus_text(
        question=question,
        selected_context=selected_context,
        selection_context=selection_context,
    )
    compact_mistakes = _should_compact_mistakes(
        source=source,
        question=question,
        primary_context=primary_context,
    )
    system_prompt = populate_prompt(
        get_system_prompt_template(prompt_scene),
        subject_name=_subject_display_name(subject, subject_context),
        subject_background=_format_subject_background(
            subject,
            subject_context,
            mode=_subject_background_mode(prompt_scene),
        ),
        teaching_strategy=(
            get_strategy_instruction(strategy_mode)
            if prompt_scene != ChatPromptScene.GENERAL
            else "通用对话模式：先回应用户当下感受；可以轻松陪聊或给一个很小的可选行动，不主动讲授课程知识。"
        ),
        weak_points_context=(
            _format_weak_points_context(
                weak_points,
                focus_text=focus_text,
                only_relevant=has_primary_context,
            )
            if use_subject_grounding
            else "本轮为通用对话，暂不使用薄弱项画像。"
        ),
        mistakes_context=(
            _format_mistakes_context(recent_mistakes, compact=compact_mistakes)
            if use_subject_grounding
            else "本轮为通用对话，暂不使用近期错题。"
        ),
        interaction_entry=_format_interaction_entry(
            source,
            scene=prompt_scene,
        ),
        selected_context=primary_context,
    )
    history_messages = [
        {
            "role": ASSISTANT if item.role == "assistant" else USER,
            "content": item.content,
        }
        for item in recent_messages
    ]
    retrieval_chunks = build_retrieval_context_items(
        retrieval_results if use_subject_grounding else [],
        question=question,
        selected_context=selected_context,
        selection_context=selection_context,
        primary_context=primary_context,
        prompt_scene=prompt_scene,
    )
    return manager.build_context(
        system_prompt=system_prompt,
        retrieval_chunks=retrieval_chunks,
        chat_history=history_messages,
        user_query=question,
    )


def build_retrieval_context_items(
    retrieval_results: list[RetrievedContext],
    *,
    question: str,
    selected_context: str | None = None,
    selection_context: ChatSelectionContext | None = None,
    primary_context: str | None = None,
    prompt_scene: ChatPromptScene | None = None,
) -> list[str]:
    """Build compact, de-duplicated retrieval blocks for the prompt."""

    if not retrieval_results:
        return []

    has_primary_context = bool((primary_context or "").strip() and (primary_context or "").strip() != "无。")
    if (
        prompt_scene == ChatPromptScene.DOCUMENT_SELECTION
        and _has_sufficient_document_selection_context(primary_context)
    ):
        return []

    focus_text = _build_focus_text(
        question=question,
        selected_context=selected_context,
        selection_context=selection_context,
    )
    unique_results = _dedupe_retrieval_results(retrieval_results)
    high_relevance = [item for item in unique_results if not item.low_relevance]

    if has_primary_context:
        chosen_count = 1 if prompt_scene == ChatPromptScene.DOCUMENT_SELECTION else _MAX_RETRIEVAL_ITEMS_WITH_PRIMARY
        chosen = high_relevance[:chosen_count]
    else:
        chosen = unique_results[:_MAX_RETRIEVAL_ITEMS_WITHOUT_PRIMARY]

    return [
        format_retrieval_context_item(
            item,
            focus_text=focus_text,
            include_content=not (has_primary_context and item.low_relevance),
        )
        for item in chosen
    ]


def _has_sufficient_document_selection_context(primary_context: str | None) -> bool:
    text = (primary_context or "").strip()
    if not text or text == "无。":
        return False
    return len(text) >= _DOCUMENT_SELECTION_PRIMARY_CONTEXT_SUFFICIENT_CHARS


def format_retrieval_context_item(
    result: RetrievedContext,
    *,
    focus_text: str | None = None,
    include_content: bool = True,
) -> str:
    """Format one retrieval record for the prompt context block."""

    relevance_label = "低相关" if result.low_relevance else "高相关"
    unit_lines = []
    if result.knowledge_unit_id is not None:
        unit_lines.append(
            f"KnowledgeUnit：#{result.knowledge_unit_id} {result.knowledge_unit_name or result.title}"
        )
    if result.knowledge_unit_type:
        unit_lines.append(f"类型：{result.knowledge_unit_type}")
    if result.relation_path:
        unit_lines.append(f"图路径：{result.relation_path}")
    if result.mastery_score is not None:
        unit_lines.append(f"用户掌握度：{result.mastery_score:.0%}")
    if result.evidence_quote:
        unit_lines.append(f"证据摘录：{_clip_text(result.evidence_quote, 360)}")
    unit_context = "\n".join(unit_lines)
    if unit_context:
        unit_context = f"{unit_context}\n"
    content = _format_retrieval_content(
        result,
        focus_text=focus_text,
        include_content=include_content,
    )
    return (
        f"[资料:{result.retrieval_source}] 标题：{result.title}\n"
        f"{unit_context}"
        f"路径：{result.header_path}\n"
        f"相关性：{relevance_label}，分数：{result.score:.4f}\n"
        f"{content}"
    )


def _format_retrieval_content(
    result: RetrievedContext,
    *,
    focus_text: str | None,
    include_content: bool,
) -> str:
    if not include_content:
        if result.evidence_quote:
            return f"摘录：{_clip_text(result.evidence_quote, 360)}"
        return "正文：已省略（低相关，已有本轮主证据；仅作背景线索）。"

    excerpt = _focused_excerpt(
        result.content,
        focus_text=focus_text,
        title=result.title,
        header_path=result.header_path,
    )
    if not excerpt:
        return "内容：无可用正文。"
    label = "摘录" if len(excerpt) < len((result.content or "").strip()) else "内容"
    return f"{label}：\n{excerpt}"


def _build_focus_text(
    *,
    question: str,
    selected_context: str | None,
    selection_context: ChatSelectionContext | None,
) -> str:
    parts = [question, selected_context or ""]
    if selection_context is not None:
        parts.extend(
            [
                selection_context.selected_text or "",
                selection_context.anchor_title or "",
                selection_context.section_title or "",
                " ".join(selection_context.heading_path or []),
            ]
        )
    return "\n".join(part.strip() for part in parts if part and part.strip())


def _dedupe_retrieval_results(results: list[RetrievedContext]) -> list[RetrievedContext]:
    """Drop repeated chunk bodies while preserving useful ordering."""

    seen: set[str] = set()
    deduped: list[RetrievedContext] = []
    for result in results:
        key = _retrieval_identity(result)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def _retrieval_identity(result: RetrievedContext) -> str:
    if result.chunk_id and result.file_id:
        return f"chunk:{result.file_id}:{result.chunk_id}"
    normalized = " ".join((result.content or "").split())
    if normalized:
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
        return f"content:{digest}"
    return f"meta:{result.retrieval_source}:{result.title}:{result.header_path}"


def _focused_excerpt(
    content: str | None,
    *,
    focus_text: str | None,
    title: str | None,
    header_path: str | None,
    max_chars: int = 900,
) -> str:
    text = (content or "").strip()
    if not text:
        return ""

    focus = (focus_text or "").strip()
    if focus:
        direct = _direct_match_excerpt(text, focus, max_chars=max_chars)
        if direct:
            return direct

    anchors = [title or "", header_path or ""]
    for anchor in anchors:
        anchor = anchor.strip()
        if not anchor:
            continue
        index = text.casefold().find(anchor.casefold())
        if index >= 0:
            return _window_excerpt(text, index, max_chars=max_chars)

    focus_tokens = set(_tokens(focus))
    if not focus_tokens:
        return _clip_text(text, max_chars)

    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if not blocks:
        return _clip_text(text, max_chars)

    best_block = max(
        blocks,
        key=lambda block: (_overlap_score(focus_tokens, set(_tokens(block))), -len(block)),
    )
    if _overlap_score(focus_tokens, set(_tokens(best_block))) <= 0:
        return _clip_text(text, max_chars)
    return _clip_text(best_block, max_chars)


def _direct_match_excerpt(text: str, focus: str, *, max_chars: int) -> str:
    candidates = [
        line.strip()
        for line in focus.splitlines()
        if len(line.strip()) >= 8
    ]
    candidates.sort(key=len, reverse=True)
    folded_text = text.casefold()
    for candidate in candidates:
        index = folded_text.find(candidate.casefold())
        if index >= 0:
            return _window_excerpt(text, index, max_chars=max_chars)
    return ""


def _window_excerpt(text: str, index: int, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    start = max(0, index - half)
    end = min(len(text), start + max_chars)
    start = max(0, end - max_chars)
    excerpt = text[start:end].strip()
    if start > 0:
        excerpt = "..." + excerpt
    if end < len(text):
        excerpt += "..."
    return excerpt


def _overlap_score(left: set[str], right: set[str]) -> int:
    return len(left & right)


def _tokens(text: str) -> list[str]:
    return [
        token
        for match in _TOKEN_RE.finditer(text or "")
        if (token := match.group(0).casefold()) not in _LOW_INFORMATION_TOKENS
    ]


def _subject_display_name(subject: str, context: SubjectContextSummary | None) -> str:
    name = (context.subject_name if context else "").strip()
    if name:
        return name
    if _is_global_subject_label(subject):
        return "通用"
    return subject or "当前学习空间"


def _format_subject_background(
    subject: str,
    context: SubjectContextSummary | None,
    *,
    mode: _SubjectBackgroundMode = "full",
) -> str:
    display_name = _subject_display_name(subject, context)
    if mode == "chat_scope":
        return "\n".join(
            [
                f"- 当前学习空间：{display_name}",
                "- 使用规则：仅在用户明确聊到学习、课程内容、练习、计划，或对话历史需要延续学科主题时使用；本轮普通闲聊不要主动展开学科内容。",
            ]
        )

    if mode == "entry_context":
        lines = [
            f"- 学科：{display_name}",
            "- 使用规则：本轮以用户入口上下文为主；学科背景只用于术语理解和难度调节，不展开建课意图或完整学科摘要。",
        ]
        profile_summary = _format_profile_summary(context)
        if profile_summary:
            lines.append(profile_summary)
        return "\n".join(lines)

    if context is None:
        return f"- 学科：{display_name}"

    lines = [f"- 学科：{display_name}"]
    if context.discipline or context.sub_discipline:
        discipline = " / ".join(
            item for item in [context.discipline, context.sub_discipline] if item
        )
        lines.append(f"- 学科领域：{discipline}")
    if context.description:
        lines.append(f"- 学科说明：{_clip_text(context.description, 180)}")
    if context.user_intent:
        lines.append(f"- 用户建课意图：{_clip_text(context.user_intent, 180)}")
    if context.learning_intent:
        lines.append(f"- 学习目标：{_clip_text(context.learning_intent, 180)}")
    if context.subject_intro:
        lines.append(f"- 学科简介：{_clip_text(context.subject_intro, 220)}")
    if context.llm_context:
        lines.append(f"- 教学背景摘要：{_clip_text(context.llm_context, 260)}")

    profile_summary = _format_profile_summary(context)
    if profile_summary:
        lines.append(profile_summary)

    if context.recommended_question_types:
        lines.append("- 推荐练习题型：" + "、".join(context.recommended_question_types[:3]))
    if context.recommended_exam_mode:
        lines.append(f"- 推荐练习模式：{context.recommended_exam_mode}")

    return "\n".join(lines)


def _subject_background_mode(scene: ChatPromptScene) -> _SubjectBackgroundMode:
    if scene == ChatPromptScene.GENERAL:
        return "chat_scope"
    if scene in {ChatPromptScene.DOCUMENT_SELECTION, ChatPromptScene.EXAM_QUESTION}:
        return "entry_context"
    return "full"


def _format_profile_summary(context: SubjectContextSummary | None) -> str:
    if context is None:
        return ""
    profile_items = []
    if context.avg_mastery is not None:
        profile_items.append(f"平均掌握度 {context.avg_mastery:.0%}")
    if context.weak_knowledge_unit_count is not None:
        profile_items.append(f"薄弱知识点 {context.weak_knowledge_unit_count} 个")
    if context.pending_review_count is not None:
        profile_items.append(f"待复习 {context.pending_review_count} 项")
    if context.due_review_count is not None:
        profile_items.append(f"已到期复习 {context.due_review_count} 项")
    if context.difficulty_focus:
        profile_items.append(f"建议难度 {context.difficulty_focus}")
    if not profile_items:
        return ""
    return "- 用户整体画像：" + "；".join(profile_items)


def _format_weak_points_context(
    weak_points: list[WeakPointSummary],
    *,
    focus_text: str | None = None,
    only_relevant: bool = False,
) -> str:
    if not weak_points:
        return "暂无薄弱项数据。"
    ranked = _rank_weak_points(weak_points, focus_text=focus_text)
    if only_relevant:
        ranked = [item for item in ranked if item[1] > 0]
        if not ranked:
            return "本轮没有明显相关薄弱项，已省略无关画像。"
    visible = [item for item, _score in ranked[:_MAX_RELEVANT_WEAK_POINTS]]
    lines = [
        f"- {item.knowledge_point}（掌握度：{item.mastery_text}）"
        for item in visible
    ]
    hidden_count = len(weak_points) - len(visible)
    if hidden_count > 0:
        lines.append(f"- 另有 {hidden_count} 项无关或低相关画像已省略。")
    return "\n".join(lines)


def _rank_weak_points(
    weak_points: list[WeakPointSummary],
    *,
    focus_text: str | None,
) -> list[tuple[WeakPointSummary, int]]:
    focus = (focus_text or "").strip()
    ranked = [
        (index, item, _text_relevance_score(focus, item.knowledge_point))
        for index, item in enumerate(weak_points)
    ]
    ranked.sort(key=lambda item: (-item[2], item[0]))
    return [(item, score) for _index, item, score in ranked]


def _text_relevance_score(focus_text: str, candidate: str) -> int:
    focus = (focus_text or "").casefold()
    text = (candidate or "").casefold()
    if not focus or not text:
        return 0
    score = 0
    if text in focus:
        score += 20
    focus_tokens = set(_tokens(focus))
    candidate_tokens = set(_tokens(text))
    score += len(focus_tokens & candidate_tokens)
    return score


def _format_mistakes_context(mistakes: list[MistakeSummary], *, compact: bool = False) -> str:
    if not mistakes:
        return "暂无近期错题。"
    visible = mistakes[:_MAX_RECENT_MISTAKES]
    prefix = "近期错题只用于调整讲解深浅；除非用户明确要求复盘错题，否则不要把它当成本轮主题。"
    if compact:
        analysis_counts: dict[str, int] = {}
        for item in mistakes:
            analysis = _normalize_mistake_analysis(item.analysis)
            analysis_counts[analysis] = analysis_counts.get(analysis, 0) + 1
        summaries = [
            f"- 错因倾向：{analysis}（{count} 次）"
            for analysis, count in sorted(analysis_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:3]
        ]
        hidden_count = len(mistakes) - len(visible)
        if hidden_count > 0:
            summaries.append(f"- 另有 {hidden_count} 道近期错题已省略。")
        return "\n".join([prefix, "本轮为划选内容提问，错题题干和答案已省略。", *summaries])

    body = "\n\n".join(
        (
            f"题干：{_clip_text(item.question_stem, 220)}\n"
            f"用户答案：{_clip_text(item.user_answer, 120) or '（空）'}\n"
            f"参考答案要点：{_clip_text(item.correct_answer, 220)}\n"
            f"错因：{_clip_text(item.analysis, 120)}"
        )
        for item in visible
    )
    hidden_count = len(mistakes) - len(visible)
    if hidden_count > 0:
        body += f"\n\n另有 {hidden_count} 道近期错题已省略。"
    return "\n\n".join(
        item for item in [prefix, body] if item
    )


def _should_compact_mistakes(
    *,
    source: str | None,
    question: str,
    primary_context: str | None,
) -> bool:
    has_primary_context = bool((primary_context or "").strip() and (primary_context or "").strip() != "无。")
    if (source or "").strip() != "quick_chat" or not has_primary_context:
        return False
    return not _asks_for_mistake_review(question)


def _asks_for_mistake_review(question: str) -> bool:
    normalized = (question or "").strip()
    if not normalized:
        return False
    review_markers = ("错题", "复盘", "错因", "为什么错", "哪里错", "改错", "答案")
    return any(marker in normalized for marker in review_markers)


def _normalize_mistake_analysis(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return "未标注错因"
    prefix = "Possible error cause:"
    if text.startswith(prefix):
        text = text[len(prefix):].strip()
    return _clip_text(text, 80) or "未标注错因"


def _format_interaction_entry(source: str | None, *, scene: ChatPromptScene) -> str:
    normalized = (source or "").strip()
    if scene == ChatPromptScene.DOCUMENT_SELECTION:
        return (
            "知识文档划选提问。回答时必须优先解释用户划选内容，并把它放回原知识脉络中；"
            "近期错题和薄弱项只能辅助讲解，不能作为本轮问题主题。"
        )
    if scene == ChatPromptScene.EXAM_QUESTION:
        return "考卷题目触发。回答时优先围绕当前题目、题干、选项、用户答案或批改结果。"
    if scene == ChatPromptScene.BUILD_ASSISTANT:
        return "知识库构建过程触发。回答时优先解释当前构建阶段、资料处理或知识文档生成结果。"
    if scene == ChatPromptScene.SUBJECT_LEARNING and normalized == "quick_chat":
        return "普通侧边栏学习对话：当前没有划选主证据；可以使用当前学习空间背景，但不要虚构具体划选内容。"
    if scene == ChatPromptScene.SUBJECT_LEARNING and normalized:
        return f"外部入口触发：{normalized}。回答时保留入口上下文，但不要虚构来源。"
    if scene == ChatPromptScene.SUBJECT_LEARNING:
        return "常规学习对话：可以使用当前学习空间背景，但以用户最后一句问题为准。"
    if normalized == "quick_chat":
        return "普通侧边栏通用对话：当前没有划选主证据；不要把知识文档或当前学科当作默认主题。"
    return "通用对话：当前没有用户入口上下文；自然回应用户，只有用户明确提出学习需求时才进入教学。"


def _is_global_subject_label(subject: str | None) -> bool:
    return (subject or "").strip().casefold() in {"", "global", "_global", "__global__"}


def _clip_text(value: str | None, max_chars: int) -> str:
    text = (value or "").strip()
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return text[:max_chars]
    return f"{text[: max_chars - 1]}…"


def _format_selected_context(
    source: str | None,
    selection_context: ChatSelectionContext | None,
    selected_context: str | None,
    source_chunk_id: int | None,
) -> str:
    if selection_context is not None:
        return _format_structured_selection_context(source, selection_context, selected_context, source_chunk_id)
    if not selected_context:
        return "无。"
    selected = _clip_text(selected_context, 2400)
    if source_chunk_id is None:
        return selected
    return f"[chunk_id={source_chunk_id}]\n{selected}"


def _format_structured_selection_context(
    source: str | None,
    context: ChatSelectionContext,
    fallback_selected_context: str | None,
    source_chunk_id: int | None,
) -> str:
    lines: list[str] = []
    if source_chunk_id is not None:
        lines.append(f"[chunk_id={source_chunk_id}]")

    selected = _clip_text(context.selected_text or fallback_selected_context, 1000)
    if selected:
        selected_label = "题目内容" if (source or "").strip() == "exam_question" else "划选原文"
        lines.append(f"{selected_label}：\n{selected}")

    heading_path = " > ".join(
        part.strip()
        for part in context.heading_path
        if part and part.strip()
    )
    if heading_path:
        lines.append(f"标题路径：{_clip_text(heading_path, 300)}")
    elif context.anchor_title:
        lines.append(f"所在标题：{_clip_text(context.anchor_title, 160)}")

    before_text = _clip_text(context.before_text, 650)
    after_text = _clip_text(context.after_text, 650)
    if before_text or after_text:
        local_parts = []
        if before_text:
            local_parts.append(f"上文：{before_text}")
        if after_text:
            local_parts.append(f"下文：{after_text}")
        suffix = "（已截断）" if context.local_context_truncated else ""
        lines.append(f"局部上下文{suffix}：\n" + "\n".join(local_parts))

    should_include_section = not (selected and before_text and after_text)
    section_excerpt = _clip_text(context.section_excerpt, 1600)
    if section_excerpt and should_include_section:
        section_title = _clip_text(context.section_title or context.anchor_title, 160)
        suffix = "（已截断）" if context.section_truncated else ""
        heading = f"本节摘录{suffix}"
        if section_title:
            heading += f"：{section_title}"
        lines.append(f"{heading}\n{section_excerpt}")

    formatted = "\n\n".join(lines).strip()
    return _clip_text(formatted, 3200) or "无。"


__all__ = [
    "build_retrieval_context_items",
    "build_chat_messages",
    "format_retrieval_context_item",
]
