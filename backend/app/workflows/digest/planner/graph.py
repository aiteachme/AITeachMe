"""Planner graph."""

from __future__ import annotations

import asyncio
import inspect
import re
from collections import Counter
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph

from app.models.subject import Subject
from app.repositories.files_repo import list_raw_files_by_ids
from app.shared.infra.database import managed_session
from app.shared.infra.llm_support import acompletion_stream
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.skills import collect_recommended_tool_tags, render_prompt_scoped_skillpacks
from app.workflows.common.context import WorkflowContext, create_langgraph_dev_context
from app.workflows.common.runtime_stats import emit_progress, get_runtime_steps, tracked_step
from app.workflows.digest.observability import traced_digest_node
from app.workflows.digest.planner.concept_grounding import collect_planner_concept_briefing
from app.workflows.digest.planner.models import (
    _resolve_subject_display_name,
    build_fallback_plan,
    normalize_planner_draft,
)
from app.workflows.digest.prompts import build_planner_prompt
from app.workflows.digest.planner.state import BuildPlannerState
from app.workflows.digest.shared.contracts import (
    resolve_digest_course_type,
    resolve_planner_retrieval_profile,
)
from app.workflows.digest.shared.models import FastTopicHints, SharedInputs, SourcePacket, SubjectProfile
from app.workflows.digest.shared.prepare import prepare_shared_inputs

_PLANNER_STREAM_MAX_TOKENS = 260
_PLANNER_STREAM_TIMEOUT_S = 10
_SUBJECT_SLUG_RE = re.compile(r"^subj_[a-z0-9]+$", re.IGNORECASE)
_SUBJECT_SLUG_INLINE_RE = re.compile(r"\bsubj_[a-z0-9]+\b", re.IGNORECASE)
_TASK_LINE_RE = re.compile(r"^\((\d+)\)\s*(.+)$")
_HEADER_LINES = {"研究任务", "研究网站", "分析结果", "生成报告"}
_LEADING_VERB_RE = re.compile(r"^(?:梳理|理解|调研|整理|分析|掌握|比较|构建|明确|总结|回顾|聚焦|说明|建立|打通|认识|学习|覆盖|提炼)")


def _guess_topic_hints_from_filenames(filenames: list[str], *, subject: str, user_goal: str | None) -> list[str]:
    seeds: list[str] = []
    if user_goal and user_goal.strip():
        seeds.append(user_goal.strip())
    for filename in filenames:
        stem = Path(filename).stem.strip()
        if not stem:
            continue
        cleaned = stem.replace("_", " ").replace("-", " ").strip()
        if cleaned:
            seeds.append(cleaned)
    if subject and not _SUBJECT_SLUG_RE.fullmatch(subject.strip()):
        seeds.append(subject)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in seeds:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= 8:
            break
    return deduped


def _build_seed_shared_inputs(*, subject: str, file_ids: list[int], user_goal: str | None) -> SharedInputs:
    with managed_session() as session:
        raw_files = list_raw_files_by_ids(session, subject, file_ids)
        subject_row = session.query(Subject).filter(Subject.slug == subject).first()

    filenames = [raw_file.original_filename for raw_file in raw_files if raw_file.original_filename]
    topic_hints = _guess_topic_hints_from_filenames(filenames, subject=subject, user_goal=user_goal)
    discipline_counts = Counter(
        str(raw_file.detected_discipline).strip()
        for raw_file in raw_files
        if raw_file.detected_discipline
    )
    sub_discipline_counts = Counter(
        str(raw_file.detected_sub_discipline).strip()
        for raw_file in raw_files
        if raw_file.detected_sub_discipline
    )
    content_type_counts = Counter(
        str(raw_file.detected_content_type).strip()
        for raw_file in raw_files
        if raw_file.detected_content_type
    )

    source_packets = [
        SourcePacket(
            file_id=int(raw_file.id),
            filename=raw_file.original_filename,
            filetype=raw_file.file_ext,
            markdown_path=raw_file.markdown_path or "",
            asset_dir=raw_file.asset_dir or "",
            normalized_content=f"文件名：{raw_file.original_filename}",
            char_count=0,
            has_formulas=False,
            has_tables=False,
            has_images=bool(raw_file.image_count),
            image_refs=[],
        )
        for raw_file in raw_files
        if raw_file.id is not None
    ]

    return SharedInputs(
        source_packets=source_packets,
        fast_hints=FastTopicHints(chapter_candidates=topic_hints),
        subject_profile=SubjectProfile(
            subject_slug=subject,
            subject_name=(subject_row.name or "").strip() if subject_row is not None else "",
            discipline=(discipline_counts.most_common(1)[0][0] if discipline_counts else ""),
            sub_discipline=(sub_discipline_counts.most_common(1)[0][0] if sub_discipline_counts else ""),
            content_type=(content_type_counts.most_common(1)[0][0] if content_type_counts else ""),
            key_topics=topic_hints,
        ),
    )


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


def _build_preview_tail(tasks: list[str]) -> str:
    lines = [f"({index}) {task}" for index, task in enumerate(tasks, start=1)]
    lines.extend(["分析结果", "生成报告"])
    return "\n".join(lines)


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
    if not preview_tasks:
        preview_tasks = [
            _clean_preview_line(_replace_subject_slug(task, display_subject))
            for task in list(fallback_plan.research_queries[:6])
            if _clean_preview_line(_replace_subject_slug(task, display_subject))
        ]

    chapter_count = max(len(preview_tasks), len(fallback_plan.chapter_plan)) if preview_tasks else len(fallback_plan.chapter_plan)
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
    if not text:
        return
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


def _merge_planner_topic_hints(shared_inputs: SharedInputs, topic_hints: list[str]) -> SharedInputs:
    if not topic_hints:
        return shared_inputs

    merged_candidates = list(shared_inputs.fast_hints.chapter_candidates)
    merged_topics = list(shared_inputs.subject_profile.key_topics)
    for item in topic_hints:
        if item not in merged_candidates:
            merged_candidates.append(item)
        if item not in merged_topics:
            merged_topics.append(item)

    next_inputs = shared_inputs.model_copy(deep=True)
    next_inputs.fast_hints.chapter_candidates = merged_candidates[:12]
    next_inputs.subject_profile.key_topics = merged_topics[:12]
    return next_inputs


def _runtime_steps_patch(state: BuildPlannerState) -> dict[str, Any]:
    return {"runtime_steps": get_runtime_steps(state)}


def build_planner_graph(*, context: WorkflowContext) -> StateGraph:
    workflow = StateGraph(BuildPlannerState)
    workflow.add_node(
        "load_context",
        build_load_context_node(context=context),
    )
    workflow.add_node(
        "ground_concepts",
        build_ground_concepts_node(context=context),
    )
    workflow.add_node(
        "draft_plan",
        build_draft_plan_node(context=context),
    )
    workflow.set_entry_point("load_context")
    workflow.add_conditional_edges("load_context", route_after_step, {"continue": "ground_concepts", "fail": END})
    workflow.add_conditional_edges("ground_concepts", route_after_step, {"continue": "draft_plan", "fail": END})
    workflow.add_edge("draft_plan", END)
    return workflow


def route_after_step(state: BuildPlannerState) -> str:
    return "fail" if state.get("error") else "continue"


def build_load_context_node(*, context: WorkflowContext):
    @traced_digest_node(
        workflow_name=context.workflow_name,
        lane="planner",
        node_name="load_context",
        output_keys=("digest_mode", "course_type", "retrieval_profile"),
    )
    async def load_context_node(state: BuildPlannerState) -> dict:
        async with tracked_step(
            state,
            name="load_context",
            kind="node",
            phase="planner",
            running_message="正在读取用户目标和已上传资料...",
            completed_message="已读取资料、目标与基础上下文。",
            failed_message="读取资料与上下文失败。",
            trace_enabled=False,
        ):
            async with tracked_step(
                state,
                name="prepare_shared_inputs",
                kind="substep",
                trace_metadata={"file_count": len(state.get("file_ids", []))},
                trace_inputs={"user_goal_present": bool(str(state.get("user_goal") or "").strip())},
            ) as step:
                shared_inputs = await prepare_shared_inputs(
                    state["subject"],
                    state.get("file_ids", []),
                    user_prompt=state.get("user_goal"),
                )
                source_mode = "prepared"
                if not shared_inputs.source_packets:
                    shared_inputs = _build_seed_shared_inputs(
                        subject=state["subject"],
                        file_ids=list(state.get("file_ids", [])),
                        user_goal=state.get("user_goal"),
                    )
                    source_mode = "seeded"
                step.set_outputs(
                    source_packet_count=len(shared_inputs.source_packets),
                    section_count=len(shared_inputs.section_packets),
                    topic_hint_count=len(shared_inputs.fast_hints.chapter_candidates),
                    source_mode=source_mode,
                )

            digest_mode = state.get("digest_mode") or shared_inputs.digest_mode_decision.mode.value
            return {
                "shared_inputs": shared_inputs,
                "digest_mode": digest_mode,
                "course_type": resolve_digest_course_type(digest_mode),
                "retrieval_profile": resolve_planner_retrieval_profile(),
                "teaching_action": "plan_course",
                "tone": state.get("tone") or "encouraging",
                **_runtime_steps_patch(state),
            }

    return load_context_node


def build_ground_concepts_node(*, context: WorkflowContext):
    @traced_digest_node(
        workflow_name=context.workflow_name,
        lane="planner",
        node_name="ground_concepts",
        output_keys=("concept_local_hit_count", "concept_web_hit_count"),
    )
    async def ground_concepts_node(state: BuildPlannerState) -> dict:
        shared_inputs = state["shared_inputs"]
        async with tracked_step(
            state,
            name="ground_concepts",
            kind="node",
            phase="planner",
            running_message="正在快速检索基础概念与知识框架，补充事实锚点...",
            failed_message="概念锚点补充失败。",
            trace_enabled=False,
        ):
            async with tracked_step(
                state,
                name="concept_grounding",
                kind="substep",
                trace_metadata={"subject": state["subject"]},
                trace_inputs={"latest_plan_present": bool(state.get("latest_plan"))},
            ) as step:
                concept_brief = await collect_planner_concept_briefing(
                    subject=state["subject"],
                    user_goal=state.get("user_goal") or "",
                    shared_inputs=shared_inputs,
                    latest_plan=state.get("latest_plan"),
                )
                step.set_outputs(
                    query_count=len(concept_brief.queries),
                    topic_hint_count=len(concept_brief.topic_hints),
                    local_hits=concept_brief.local_hit_count,
                    web_hits=concept_brief.web_hit_count,
                )

            enhanced_inputs = _merge_planner_topic_hints(shared_inputs, concept_brief.topic_hints)
            local_message = f"已补充 {concept_brief.local_hit_count} 条本地概念锚点"
            web_message = (
                f"，{concept_brief.web_hit_count} 条外部概念锚点"
                if concept_brief.web_hit_count
                else ""
            )
            await emit_progress(
                state,
                phase="planner",
                step="ground_concepts",
                status="completed",
                message=f"{local_message}{web_message}。",
            )
            return {
                "shared_inputs": enhanced_inputs,
                "concept_queries": concept_brief.queries,
                "concept_briefing": concept_brief.briefing,
                "concept_topic_hints": concept_brief.topic_hints,
                "concept_local_hit_count": concept_brief.local_hit_count,
                "concept_web_hit_count": concept_brief.web_hit_count,
                **_runtime_steps_patch(state),
            }

    return ground_concepts_node


def build_draft_plan_node(*, context: WorkflowContext):
    @traced_digest_node(
        workflow_name=context.workflow_name,
        lane="planner",
        node_name="draft_plan",
        output_keys=("fallback_used", "planner_generation_mode"),
    )
    async def draft_plan_node(state: BuildPlannerState) -> dict:
        shared_inputs = state["shared_inputs"]
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
        async with tracked_step(
            state,
            name="draft_plan",
            kind="node",
            phase="planner",
            running_message="正在流式生成研究任务草案...",
            completed_message="方案已整理完成，准备返回前端。",
            failed_message="规划草案生成失败。",
            trace_enabled=False,
        ):
            async with tracked_step(
                state,
                name="plan_prompt_build",
                kind="substep",
                trace_metadata={
                    "digest_mode": digest_mode,
                    "selected_skillpack_count": len(state.get("selected_skillpacks") or []),
                },
                trace_inputs={"message_count": len(state.get("message_history") or [])},
            ) as step:
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
                step.set_outputs(prompt_chars=len(prompt))

            await _emit_planner_tokens(state, preview_prefix)

            streamed_tokens: list[str] = []
            stream_failed = False
            async with tracked_step(
                state,
                name="planner_stream_generate",
                kind="substep",
                trace_metadata={
                    "digest_mode": digest_mode,
                    "course_type": course_type,
                    "retrieval_profile": retrieval_profile,
                    "teaching_action": teaching_action,
                },
                trace_inputs={"max_tokens": _PLANNER_STREAM_MAX_TOKENS},
            ) as step:
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
                except Exception:
                    stream_failed = True
                    step.set_status("failed")
                step.set_outputs(
                    token_chunk_count=len(streamed_tokens),
                    stream_failed=stream_failed,
                )

            preview_text = preview_prefix + "".join(streamed_tokens)
            raw_draft, preview_tasks = _build_raw_plan_from_preview(
                preview_text=preview_text,
                display_subject=display_subject,
                user_goal=state.get("user_goal") or "",
                digest_mode=digest_mode,
                tone=tone,
                fallback_plan=fallback_plan,
            )
            fallback_used = stream_failed
            generation_mode = "stream_plaintext_partial" if stream_failed else "stream_plaintext"
            if stream_failed and not streamed_tokens:
                async with tracked_step(
                    state,
                    name="planner_fallback_build",
                    kind="substep",
                    phase="planner",
                    progress_step="draft_plan",
                    running_message="模型响应较慢，正在用本地快速方案补齐研究任务...",
                    trace_metadata={"preview_task_count": len(preview_tasks[:6])},
                ) as step:
                    await _emit_planner_tokens(state, _build_preview_tail(preview_tasks[:6]))
                    generation_mode = "fallback_plan"
                    step.set_outputs(preview_task_count=len(preview_tasks[:6]))

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
            plan = draft.model_dump(mode="json")
            return {
                "plan": plan,
                "plan_summary": draft.plan_summary,
                "digest_mode": draft.digest_mode,
                "course_type": resolve_digest_course_type(draft.digest_mode),
                "retrieval_profile": resolve_planner_retrieval_profile(),
                "teaching_action": teaching_action,
                "tone": draft.tone,
                "selected_skillpacks": list(draft.selected_skillpacks),
                "fallback_used": fallback_used,
                "planner_generation_mode": generation_mode,
                **_runtime_steps_patch(state),
            }

    return draft_plan_node


def create_planner_initial_state(
    *,
    subject: str,
    file_ids: list[int],
    user_goal: str,
    digest_mode: str,
    tone: str,
    selected_skillpacks: list[str],
    planner_session_id: str,
    message_history: list[str],
    latest_plan: dict | None = None,
    progress_callback: object | None = None,
    token_callback: object | None = None,
) -> BuildPlannerState:
    course_type = resolve_digest_course_type(digest_mode)
    return {
        "subject": subject,
        "file_ids": file_ids,
        "user_goal": user_goal,
        "digest_mode": digest_mode,
        "course_type": course_type,
        "retrieval_profile": resolve_planner_retrieval_profile(),
        "teaching_action": "plan_course",
        "tone": tone,
        "selected_skillpacks": list(selected_skillpacks),
        "planner_session_id": planner_session_id,
        "message_history": message_history,
        "latest_plan": latest_plan,
        "runtime_steps": [],
        "_runtime_step_starts": {},
        "progress_callback": progress_callback,
        "token_callback": token_callback,
        "error": None,
    }


def get_langgraph_dev_planner_graph() -> StateGraph:
    return build_planner_graph(context=create_langgraph_dev_context("digest.planner.langgraph_dev"))


__all__ = ["build_planner_graph", "create_planner_initial_state"]
