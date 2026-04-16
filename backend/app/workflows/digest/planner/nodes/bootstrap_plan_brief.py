"""Bootstrap a visible plan sketch and structured learning intent in parallel."""

from __future__ import annotations

import asyncio
import re
import time

import structlog

from app.shared.infra.llm_support import acompletion_stream, acompletion_with_fallback
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.planner_events import emit_planner_event, emit_planner_token
from app.workflows.digest.planner.lib.plans import _resolve_subject_display_name, build_fallback_plan
from app.workflows.digest.planner.lib.research_probe import (
    LearningIntentProfile,
    PlanSketch,
    build_default_intent_profile,
    build_fallback_plan_sketch,
)
from app.workflows.digest.planner.prompts import build_learning_intent_messages, build_plan_sketch_prompt
from app.workflows.digest.planner.state import BuildPlannerState

_TASK_LINE_RE = re.compile(r"^\s*(?:[-*]|\(?\d+[).、])\s*(.+)$")
_HEADING_RE = re.compile(r"^##\s+(.+)$")
logger = structlog.get_logger(__name__)


def _extract_section_lines(text: str, heading: str) -> list[str]:
    lines = [line.rstrip() for line in str(text or "").replace("\r", "").splitlines()]
    captured: list[str] = []
    current_heading = ""
    for line in lines:
        heading_match = _HEADING_RE.match(line.strip())
        if heading_match:
            current_heading = heading_match.group(1).strip()
            continue
        if current_heading == heading:
            if line.strip().startswith("## "):
                break
            captured.append(line)
    return captured


def _extract_first_blockquote_summary(text: str) -> str:
    lines = [line.strip() for line in str(text or "").replace("\r", "").splitlines()]
    summary_lines = [line.lstrip("> ").strip() for line in lines if line.startswith(">")]
    for line in summary_lines:
        if line.startswith("一句话摘要"):
            return line.split("：", 1)[-1].split(":", 1)[-1].strip()
    return summary_lines[-1] if summary_lines else ""


def _parse_plan_sketch_text(text: str, *, fallback: PlanSketch) -> PlanSketch:
    cleaned_lines = [line.strip() for line in str(text or "").replace("\r", "").splitlines() if line.strip()]
    tasks: list[str] = []
    for line in _extract_section_lines(text, "研究任务") or cleaned_lines:
        match = _TASK_LINE_RE.match(line)
        if match:
            candidate = match.group(1).strip()
            if 4 <= len(candidate) <= 80 and "http" not in candidate.lower():
                tasks.append(candidate)
        if len(tasks) >= 8:
            break
    chapters = []
    for line in _extract_section_lines(text, "暂定章节"):
        match = _TASK_LINE_RE.match(line.strip())
        if match:
            chapters.append(match.group(1).strip())
    assumptions = []
    for line in _extract_section_lines(text, "规划假设"):
        match = _TASK_LINE_RE.match(line.strip())
        if match:
            assumptions.append(match.group(1).strip())
    clarifications = []
    for line in _extract_section_lines(text, "待确认点"):
        match = _TASK_LINE_RE.match(line.strip())
        if match:
            clarifications.append(match.group(1).strip())
    title = cleaned_lines[0].lstrip("# ").strip() if cleaned_lines else fallback.title
    return PlanSketch(
        title=title[:40] or fallback.title,
        summary=_extract_first_blockquote_summary(text) or fallback.summary,
        research_tasks=tasks or fallback.research_tasks,
        provisional_chapters=chapters or fallback.provisional_chapters,
        assumptions=assumptions or fallback.assumptions,
        missing_clarifications=clarifications or fallback.missing_clarifications,
        raw_text=text or fallback.raw_text,
    )


async def _stream_plan_sketch(state: BuildPlannerState, fallback: PlanSketch) -> PlanSketch:
    material_context = state["material_context"]
    subject_name = _resolve_subject_display_name(
        state["subject"],
        shared_inputs=material_context,
        user_goal=state.get("user_goal") or "",
    )
    prompt = build_plan_sketch_prompt(
        subject=subject_name,
        user_goal=state.get("user_goal") or "",
        digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
        tone=state.get("tone") or "encouraging",
        material_context=material_context,
        message_history=list(state.get("message_history", [])),
    )
    tokens: list[str] = []
    started_at = time.monotonic()
    first_token_ms: int | None = None
    await emit_planner_event(state, event="planner.sketch.started", detail="正在生成可视化规划草稿...")
    try:
        stream = acompletion_stream(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.REASONING,
            model="reason",
            temperature=0.2,
            max_tokens=420,
            extra_metadata={
                "planner_session_id": state.get("planner_session_id") or "",
                "substep": "stream_plan_sketch",
            },
        )
        async for token in stream:
            if first_token_ms is None:
                first_token_ms = int((time.monotonic() - started_at) * 1000)
                logger.info(
                    "planner_sketch_first_token_received",
                    planner_session_id=state.get("planner_session_id") or "",
                    subject=state["subject"],
                    first_token_ms=first_token_ms,
                )
            tokens.append(token)
            await emit_planner_token(state, token)
            await emit_planner_event(
                state,
                event="planner.sketch.delta",
                detail="规划草稿生成中...",
                payload={"token": token},
            )
    except Exception:
        logger.exception(
            "planner_sketch_failed",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state["subject"],
            token_count=len(tokens),
            first_token_ms=first_token_ms,
        )
        await emit_planner_event(
            state,
            event="planner.fallback.used",
            detail="规划草稿生成失败，已使用规则草稿继续。",
        )
        if not tokens:
            for line in fallback.raw_text.splitlines(keepends=True):
                await emit_planner_token(state, line)
        return fallback
    if not tokens:
        await emit_planner_event(
            state,
            event="planner.fallback.used",
            detail="规划草稿未返回任何增量内容，已使用规则草稿继续。",
        )
        for line in fallback.raw_text.splitlines(keepends=True):
            await emit_planner_token(state, line)
        return fallback
    return _parse_plan_sketch_text("".join(tokens).strip(), fallback=fallback)


async def _extract_learning_intent(state: BuildPlannerState) -> LearningIntentProfile:
    material_context = state["material_context"]
    fallback = build_default_intent_profile(
        material_context=material_context,
        user_goal=state.get("user_goal") or "",
        digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
    )
    try:
        return await acompletion_with_fallback(
            build_learning_intent_messages(
                subject=state["subject"],
                user_goal=state.get("user_goal") or "",
                digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
                material_context=material_context,
                message_history=list(state.get("message_history", [])),
            ),
            task_type=TaskType.DOCGEN_LIGHT,
            model="primary",
            response_model=LearningIntentProfile,
            temperature=0.1,
            max_tokens=650,
            extra_metadata={
                "planner_session_id": state.get("planner_session_id") or "",
                "substep": "extract_learning_intent",
            },
        )
    except Exception:
        logger.exception(
            "planner_intent_failed",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state["subject"],
        )
        await emit_planner_event(
            state,
            event="planner.fallback.used",
            detail="意图识别失败，已使用规则意图继续。",
        )
        return fallback


def build_bootstrap_plan_brief_node(*, context: WorkflowContext):
    async def bootstrap_plan_brief_node(state: BuildPlannerState) -> dict:
        material_context = state["material_context"]
        fallback_plan = build_fallback_plan(
            subject=state["subject"],
            user_goal=state.get("user_goal") or "",
            digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
            tone=state.get("tone") or "encouraging",
            shared_inputs=material_context,
        )
        fallback_sketch = build_fallback_plan_sketch(fallback_plan)
        sketch, intent = await asyncio.gather(
            _stream_plan_sketch(state, fallback_sketch),
            _extract_learning_intent(state),
        )
        await emit_planner_event(
            state,
            event="planner.intent.ready",
            detail=f"已识别学习目标：{intent.goal_type}。",
            payload={
                "goal_type": intent.goal_type,
                "source_policy": intent.source_policy,
                "local_query_count": len(intent.research_probe_plan.local_queries),
                "web_query_count": len(intent.research_probe_plan.web_queries),
                "local_queries": [query.query for query in intent.research_probe_plan.local_queries[:4]],
                "web_queries": [query.query for query in intent.research_probe_plan.web_queries[:3]],
                "success_criteria": list(intent.success_criteria[:3]),
            },
        )
        return {
            "plan_sketch_markdown": sketch.raw_text,
            "plan_sketch_text": sketch.raw_text,
            "plan_sketch": sketch.model_dump(mode="json"),
            "learning_intent_profile": intent.model_dump(mode="json"),
            "research_probe_plan": intent.research_probe_plan.model_dump(mode="json"),
            "concept_queries": [query.query for query in intent.research_probe_plan.local_queries],
        }

    return bootstrap_plan_brief_node


__all__ = ["build_bootstrap_plan_brief_node"]
