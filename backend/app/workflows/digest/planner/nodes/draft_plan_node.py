"""Draft the confirmed plan from grounded context."""

from __future__ import annotations

import asyncio
import inspect
import re
from typing import Any

from langsmith import traceable
from pydantic import BaseModel, Field

from app.shared.infra.llm_support import acompletion_stream, acompletion_with_fallback
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.skills import collect_recommended_tool_tags, render_prompt_scoped_skillpacks
from app.shared.infra.workflow import emit_progress
from app.shared.infra.workflow.context import WorkflowContext
from app.teaching.documents import coerce_resolved_chapter_title
from app.workflows.digest.planner.internal.plans import (
    _dedupe_chapter_plan_titles,
    _resolve_subject_display_name,
    build_fallback_plan,
    normalize_planner_draft,
)
from app.workflows.digest.planner.state import BuildPlannerState
from app.workflows.digest.prompts import build_planner_chapter_title_messages, build_planner_prompt
from app.workflows.digest.shared.contracts import (
    resolve_digest_course_type,
    resolve_planner_retrieval_profile,
)
from app.workflows.digest.shared.models import SharedInputs

_PLANNER_STREAM_MAX_TOKENS = 260
_PLANNER_STREAM_TIMEOUT_S = 10
_SUBJECT_SLUG_INLINE_RE = re.compile(r"\bsubj_[a-z0-9]+\b", re.IGNORECASE)
_TASK_LINE_RE = re.compile(r"^\((\d+)\)\s*(.+)$")
_HEADER_LINES = {"研究任务", "研究网站", "分析结果", "生成报告"}
_LEADING_VERB_RE = re.compile(r"^(?:梳理|理解|调研|整理|分析|掌握|比较|构建|明确|总结|回顾|聚焦|说明|建立|打通|认识|学习|覆盖|提炼)")


class _PlannerChapterTitleItem(BaseModel):
    chapter_index: int
    title: str = ""


class _PlannerChapterTitlePayload(BaseModel):
    chapters: list[_PlannerChapterTitleItem] = Field(default_factory=list)


def _clean_preview_line(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _replace_subject_slug(value: str, replacement: str) -> str:
    return _SUBJECT_SLUG_INLINE_RE.sub(replacement, str(value or ""))


def _extract_preview_title(raw_text: str) -> str:
    lines = [_clean_preview_line(line) for line in str(raw_text or "").replace("\r", "").split("\n")]
    for line in lines:
        if not line or line in _HEADER_LINES:
            continue
        if _TASK_LINE_RE.match(line):
            continue
        return line
    return ""


def _extract_preview_tasks(raw_text: str) -> list[str]:
    tasks: list[str] = []
    seen: set[str] = set()
    lines = [_clean_preview_line(line) for line in str(raw_text or "").replace("\r", "").split("\n")]
    for line in lines:
        match = _TASK_LINE_RE.match(line)
        if match is None:
            continue
        text = _clean_preview_line(match.group(2))
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        tasks.append(text)
        if len(tasks) >= 8:
            break
    return tasks


def _truncate_text(value: str, *, limit: int) -> str:
    text = _clean_preview_line(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip("，。；：,. ") + "…"


def _build_preview_title(*, display_subject: str, user_goal: str, digest_mode: str) -> str:
    goal = _clean_preview_line(_replace_subject_slug(user_goal, display_subject))
    subject = _clean_preview_line(display_subject) or "当前主题"
    if goal and goal != subject and len(goal) <= 18 and "知识文档" not in goal:
        topic = goal
    else:
        topic = subject
    suffix = "冲刺学习计划" if digest_mode == "sprint" else "学习与应用指南"
    return topic if topic.endswith(suffix) else f"{topic}{suffix}"


def _suggest_provisional_title_from_task(task: str, fallback_title: str) -> str:
    cleaned = _clean_preview_line(task)
    if not cleaned:
        return fallback_title
    cleaned = re.split(r"[，。；：,.!?！？]", cleaned, maxsplit=1)[0].strip()
    cleaned = _LEADING_VERB_RE.sub("", cleaned).strip(" ：:,-")
    if 4 <= len(cleaned) <= 16:
        return cleaned
    return fallback_title


def _merge_task_queries(task: str, fallback_queries: list[str]) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()
    for candidate in [task, *fallback_queries]:
        text = _clean_preview_line(candidate)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        queries.append(text)
        if len(queries) >= 4:
            break
    return queries


def _build_plan_summary(
    *,
    display_subject: str,
    digest_mode: str,
    tasks: list[str],
    fallback_summary: str,
) -> str:
    if not tasks:
        return fallback_summary
    plan_kind = "冲刺型" if digest_mode == "sprint" else "系统型"
    focus = "；".join(_truncate_text(task, limit=18) for task in tasks[:2])
    return _truncate_text(
        f"围绕 {display_subject} 生成一份{plan_kind}知识文档，研究重点包括 {focus}。",
        limit=110,
    )


@traceable(name="digest.planner.generate_titles", run_type="tool")
async def _generate_planner_titles(
    *,
    subject: str,
    user_goal: str,
    digest_mode: str,
    chapter_plan: list[dict[str, Any]],
    planner_session_id: str,
    course_type: str,
    retrieval_profile: str,
    teaching_action: str,
) -> dict[int, str]:
    if not chapter_plan:
        return {}

    messages = build_planner_chapter_title_messages(
        subject=subject,
        user_goal=user_goal,
        digest_mode=digest_mode,
        chapters=chapter_plan,
    )
    payload = await acompletion_with_fallback(
        messages,
        task_type=TaskType.DOCGEN_LIGHT,
        tier="light",
        response_model=_PlannerChapterTitlePayload,
        temperature=0.1,
        max_tokens=240,
        extra_metadata={
            "planner_session_id": planner_session_id,
            "digest_mode": digest_mode,
            "course_type": course_type,
            "retrieval_profile": retrieval_profile,
            "teaching_action": teaching_action,
            "substep": "planner_title_generate",
        },
    )
    return {
        int(item.chapter_index): str(item.title).strip()
        for item in payload.chapters
        if int(item.chapter_index or 0) > 0 and str(item.title).strip()
    }


def _apply_generated_titles_to_draft(
    draft,
    *,
    generated_titles: dict[int, str],
    subject_display_name: str,
):
    if not generated_titles:
        return draft

    updated_plan = []
    changed = False
    for chapter in draft.chapter_plan:
        current_title = str(chapter.title or "").strip()
        candidate_title = generated_titles.get(int(chapter.chapter_index or 0))
        if candidate_title:
            resolved_title = coerce_resolved_chapter_title(
                candidate_title,
                chapter={"title": current_title},
                chapter_index=int(chapter.chapter_index or 0),
            )
        else:
            resolved_title = current_title
        if resolved_title != current_title:
            changed = True
        updated_plan.append(chapter.model_copy(update={"title": resolved_title}))

    deduped_plan = _dedupe_chapter_plan_titles(
        updated_plan,
        subject_display_name=subject_display_name,
    )
    if changed or [chapter.title for chapter in deduped_plan] != [chapter.title for chapter in draft.chapter_plan]:
        return draft.model_copy(update={"chapter_plan": deduped_plan})
    return draft


def _build_raw_plan_from_preview(
    *,
    preview_text: str,
    display_subject: str,
    user_goal: str,
    digest_mode: str,
    tone: str,
    fallback_plan,
) -> tuple[dict[str, Any], list[str]]:
    preview_title = _clean_preview_line(_replace_subject_slug(_extract_preview_title(preview_text), display_subject))
    preview_tasks = [
        _clean_preview_line(_replace_subject_slug(task, display_subject))
        for task in _extract_preview_tasks(preview_text)
        if _clean_preview_line(_replace_subject_slug(task, display_subject))
    ]

    chapter_count = (
        max(len(preview_tasks), len(fallback_plan.chapter_plan))
        if preview_tasks
        else len(fallback_plan.chapter_plan)
    )
    chapter_plan: list[dict[str, Any]] = []
    for index in range(chapter_count):
        fallback = fallback_plan.chapter_plan[min(index, len(fallback_plan.chapter_plan) - 1)]
        task = preview_tasks[index] if index < len(preview_tasks) else ""
        chapter_payload = fallback.model_dump(mode="json")
        if task:
            chapter_payload["title"] = _suggest_provisional_title_from_task(task, chapter_payload["title"])
            chapter_payload["objective"] = _truncate_text(task, limit=32)
            chapter_payload["search_queries"] = _merge_task_queries(
                task,
                list(chapter_payload.get("search_queries") or []),
            )
        chapter_plan.append(chapter_payload)

    plan_summary = _build_plan_summary(
        display_subject=display_subject,
        digest_mode=digest_mode,
        tasks=preview_tasks,
        fallback_summary=fallback_plan.plan_summary,
    )
    if preview_title:
        plan_summary = _truncate_text(f"{preview_title}：{plan_summary}", limit=118)

    return (
        {
            "subject": display_subject,
            "user_goal": user_goal,
            "digest_mode": digest_mode,
            "tone": tone,
            "chapter_plan": chapter_plan,
            "research_queries": preview_tasks,
            "media_plan": fallback_plan.media_plan,
            "build_constraints": fallback_plan.build_constraints,
            "plan_summary": plan_summary,
        },
        preview_tasks,
    )


async def _emit_planner_token(state: BuildPlannerState, token: str) -> None:
    callback = state.get("token_callback")
    if callback is None or not callable(callback) or not token:
        return
    try:
        maybe_awaitable = callback(token)
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable
    except Exception:
        return


async def _emit_planner_tokens(state: BuildPlannerState, text: str) -> None:
    if text:
        await _emit_planner_token(state, text)


def _build_fast_planner_prompt(base_prompt: str) -> str:
    return (
        f"{base_prompt}\n\n"
        "额外执行要求：\n"
        "1. 这一步只负责生成可确认的研究任务，不写正文，不写 JSON，不写 Markdown 代码块。\n"
        "2. 前端已经提前输出了标题和“研究任务”这一行，你不要重复它们。\n"
        "3. 你只继续输出下面这些行：\n"
        "(1) 第一条研究任务\n"
        "(2) 第二条研究任务\n"
        "按实际任务数继续列到 5 到 8 条。\n"
        "然后固定输出两行：\n"
        "分析结果\n"
        "生成报告\n"
        "4. 每条研究任务控制在 18 到 36 个中文字符之间，务必具体、可检索、可执行。\n"
        "5. 任务必须强依赖当前主题、用户目标和资料提示，不要输出空泛模板。\n"
        "6. 不要解释你的思路，不要额外加前言、后记、总结段落。"
    )


def build_draft_plan_node(*, context: WorkflowContext):
    async def draft_plan_node(state: BuildPlannerState) -> dict:
        shared_inputs: SharedInputs = state["shared_inputs"]
        digest_mode = state.get("digest_mode") or shared_inputs.digest_mode_decision.mode.value
        tone = state.get("tone") or "encouraging"
        display_subject = _resolve_subject_display_name(
            state["subject"],
            shared_inputs=shared_inputs,
            user_goal=state.get("user_goal") or "",
        )
        course_type = str(state.get("course_type") or resolve_digest_course_type(digest_mode))
        retrieval_profile = str(state.get("retrieval_profile") or resolve_planner_retrieval_profile())
        teaching_action = str(state.get("teaching_action") or "plan_course")
        fallback_plan = build_fallback_plan(
            subject=state["subject"],
            user_goal=state.get("user_goal") or "",
            digest_mode=digest_mode,
            tone=tone,
            shared_inputs=shared_inputs,
        )
        preview_prefix = (
            f"{_build_preview_title(display_subject=display_subject, user_goal=state.get('user_goal') or '', digest_mode=digest_mode)}\n"
            "研究任务\n"
        )
        await emit_progress(
            state,
            stage="draft_plan",
            step="draft_plan",
            detail="正在流式生成研究任务草案...",
        )
        prompt = _build_fast_planner_prompt(
            build_planner_prompt(
                subject=display_subject,
                user_goal=state.get("user_goal") or "",
                digest_mode=digest_mode,
                tone=tone,
                shared_inputs=shared_inputs,
                message_history=list(state.get("message_history", [])),
                latest_plan=state.get("latest_plan"),
                concept_briefing=state.get("concept_briefing") or "",
                skillpack_guidance=render_prompt_scoped_skillpacks(
                    state.get("selected_skillpacks") or [],
                    prompt_scope="digest.planner",
                    bindings={
                        "subject": display_subject,
                        "user_goal": state.get("user_goal") or "",
                        "topic": display_subject,
                        "concept": display_subject,
                    },
                ),
                recommended_tool_tags=collect_recommended_tool_tags(
                    state.get("selected_skillpacks") or [],
                    prompt_scope="digest.planner",
                ),
            )
        )

        await _emit_planner_tokens(state, preview_prefix)

        streamed_tokens: list[str] = []
        stream_failed = False
        stream_error: Exception | None = None
        try:
            async with asyncio.timeout(_PLANNER_STREAM_TIMEOUT_S):
                stream = acompletion_stream(
                    [{"role": "user", "content": prompt}],
                    task_type=TaskType.DOCGEN_LIGHT,
                    temperature=0.1,
                    max_tokens=_PLANNER_STREAM_MAX_TOKENS,
                    extra_metadata={
                        "planner_session_id": state.get("planner_session_id") or "",
                        "digest_mode": digest_mode,
                        "course_type": course_type,
                        "retrieval_profile": retrieval_profile,
                        "teaching_action": teaching_action,
                    },
                )
                async for token in stream:
                    streamed_tokens.append(token)
                    await _emit_planner_token(state, token)
        except Exception as exc:
            stream_failed = True
            stream_error = exc

        if stream_failed:
            assert stream_error is not None
            raise stream_error
        if not streamed_tokens:
            raise RuntimeError("主模型调用失败，未生成结果。")

        preview_text = preview_prefix + "".join(streamed_tokens)
        raw_draft, preview_tasks = _build_raw_plan_from_preview(
            preview_text=preview_text,
            display_subject=display_subject,
            user_goal=state.get("user_goal") or "",
            digest_mode=digest_mode,
            tone=tone,
            fallback_plan=fallback_plan,
        )
        if not preview_tasks:
            raise RuntimeError("主模型调用失败，未生成有效研究任务。")

        draft = normalize_planner_draft(
            raw_draft,
            subject=state["subject"],
            user_goal=state.get("user_goal") or "",
            requested_digest_mode=digest_mode,
            requested_tone=tone,
            selected_skillpacks=list(state.get("selected_skillpacks") or []),
            shared_inputs=shared_inputs,
            latest_plan=state.get("latest_plan"),
        )
        generated_titles = await _generate_planner_titles(
            subject=display_subject,
            user_goal=state.get("user_goal") or "",
            digest_mode=digest_mode,
            chapter_plan=[
                {
                    **chapter.model_dump(mode="json"),
                    "task_hint": preview_tasks[index] if index < len(preview_tasks) else "",
                }
                for index, chapter in enumerate(draft.chapter_plan)
            ],
            planner_session_id=state.get("planner_session_id") or "",
            course_type=course_type,
            retrieval_profile=retrieval_profile,
            teaching_action=teaching_action,
        )
        draft = _apply_generated_titles_to_draft(
            draft,
            generated_titles=generated_titles,
            subject_display_name=display_subject,
        )
        plan = draft.model_dump(mode="json")
        await emit_progress(
            state,
            stage="draft_plan",
            step="draft_plan",
            detail="方案已整理完成，准备返回前端。",
        )
        return {
            "plan": plan,
            "plan_summary": draft.plan_summary,
            "digest_mode": draft.digest_mode,
            "course_type": resolve_digest_course_type(draft.digest_mode),
            "retrieval_profile": resolve_planner_retrieval_profile(),
            "teaching_action": teaching_action,
            "tone": draft.tone,
            "selected_skillpacks": list(draft.selected_skillpacks),
            "planner_generation_mode": "stream_plaintext",
        }

    return draft_plan_node


__all__ = ["build_draft_plan_node"]
