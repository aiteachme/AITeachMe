"""Tiny persistence API for the planner workflow.

只有 ``__all__`` 里的函数给外部用。Planner 节点只调用一个很小的 store
函数，避免业务节点里直接铺满 SQL/repo 细节。
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

import structlog
from sqlmodel import Session, select

from app.models import ChatMessage, ChatSession
from app.models.build_planner import ConfirmedBuildPlan
from app.models.raw_file import RawFile
from app.models.course import Course
from app.repositories.confirmed_plan_repo import (
    create_confirmed_plan,
    get_confirmed_plan,
    next_confirmed_plan_version_no,
    update_confirmed_plan,
)
from app.repositories.chats_repo import (
    create_chat_message,
    create_chat_session,
    get_chat_session,
    touch_chat_session,
)
from app.repositories.files_repo import list_all_raw_files_by_course, list_raw_files_by_ids
from app.shared.infra.database import managed_session
from app.shared.infra.llm_support.model_choices import normalize_runtime_model_override
from app.schemas.knowledge import (
    BuildPlannerConfirmResponse,
    BuildPlannerPlanResponse,
    BuildPlannerRuntimeStatsResponse,
    BuildPlannerSessionResponse,
    BuildPlannerStepStatsResponse,
    BuildPlannerTurnResponse,
)
from app.shared.infra.exceptions import (
    BuildPlannerEmptyPlanError,
    BuildPlannerSessionBusyError,
    BuildPlannerSessionNotFoundError,
    ConfirmedBuildPlanNotFoundError,
    PlannerMaterialsNotReadyError,
    RawFileNotFoundError,
)
from app.utils.presenters import require_id
from app.utils.time import utcnow
from app.workflows.digest.common.file_status import is_markdown_ready_for_digest
from app.workflows.digest.common.runtime_config import get_teaching_runtime_config
from app.workflows.digest.planner.lib.plans import (
    normalize_planner_payload,
    planner_mode_label,
)
from app.workflows.digest.planner.lib.steps import STEP_TIMING_FIELDS
from app.workflows.support.courses.icons import normalize_course_icon_key, set_course_icon_key

logger = structlog.get_logger(__name__)
PLANNER_CHAT_SOURCE = "build_planner"
_AUTO_TITLE_PLACEHOLDERS = {"", "untitled course", "新课程", "无标题", "未命名", "未命名课程"}


def _select_planner_files(
    session: Session,
    *,
    course_id: str,
    file_ids: list[str] | None,
) -> list[RawFile]:
    available_files = [item for item in list_all_raw_files_by_course(session, course_id) if item.id]
    if not file_ids:
        return available_files
    requested = list_raw_files_by_ids(session, course_id, file_ids)
    requested_by_id = {require_id(item.id, "RawFile.id"): item for item in requested}
    found_ids = set(requested_by_id)
    missing = [file_id for file_id in file_ids if file_id not in found_ids]
    if missing:
        raise RawFileNotFoundError(missing[0])
    available_ids = {require_id(item.id, "RawFile.id") for item in available_files}
    ordered: list[RawFile] = []
    seen: set[str] = set()
    for file_id in file_ids:
        if file_id in seen:
            continue
        item = requested_by_id.get(file_id)
        if item is not None and item.id and require_id(item.id, "RawFile.id") in available_ids:
            ordered.append(item)
            seen.add(file_id)
    return ordered


def _select_planner_workflow_files(raw_files: list[RawFile]) -> list[RawFile]:
    ready = [item for item in raw_files if is_markdown_ready_for_digest(item)]
    return ready or raw_files


def _file_ids(raw_files: list[RawFile]) -> list[str]:
    return [require_id(item.id, "RawFile.id") for item in raw_files if item.id]


def _turn_response_from_snapshot(turn: Mapping[str, Any]) -> BuildPlannerTurnResponse:
    raw_plan = turn.get("plan_json")
    return BuildPlannerTurnResponse(
        id=turn.get("id"),
        role=str(turn.get("role") or ""),
        content=str(turn.get("content") or ""),
        plan_json=dict(raw_plan) if isinstance(raw_plan, Mapping) and raw_plan else None,
        created_at=turn["created_at"],
    )


def _planner_meta(session_item: ChatSession) -> dict[str, Any]:
    return dict(session_item.meta_json or {})


def _planner_status(session_item: ChatSession) -> str:
    return str(_planner_meta(session_item).get("planner_status") or "draft")


def _planner_plan(session_item: ChatSession) -> dict[str, Any]:
    return dict(_planner_meta(session_item).get("latest_plan") or {})


def _planner_selected_file_ids(session_item: ChatSession) -> list[str]:
    values = _planner_meta(session_item).get("selected_file_ids") or []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        file_id = str(value or "").strip()
        if not file_id or file_id in seen:
            continue
        seen.add(file_id)
        result.append(file_id)
    return result


def _planner_model_override(session_item: ChatSession) -> str | None:
    return normalize_runtime_model_override(_planner_meta(session_item).get("model_override"))


def _planner_session_meta(
    *,
    session_id: str,
    status: str,
    user_prompt: str,
    digest_mode: str,
    selected_file_ids: list[str],
    model_override: str | None = None,
    latest_plan: dict[str, Any] | None = None,
    latest_summary: str = "",
    confirmed_plan_id: str | None = None,
) -> dict[str, Any]:
    return {
        "source": PLANNER_CHAT_SOURCE,
        "planner_session_id": session_id,
        "planner_status": status,
        "user_prompt": user_prompt,
        "digest_mode": digest_mode,
        "selected_file_ids": list(selected_file_ids),
        "model_override": normalize_runtime_model_override(model_override),
        "latest_plan": dict(latest_plan or {}),
        "latest_summary": latest_summary,
        "confirmed_plan_id": confirmed_plan_id,
    }


def _needs_auto_course_name(value: str | None) -> bool:
    return str(value or "").strip().casefold() in _AUTO_TITLE_PLACEHOLDERS


def _clean_course_metadata_text(value: str | None, *, max_chars: int = 800) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()


def _build_course_description_from_plan(
    plan_payload: Mapping[str, Any],
    *,
    material_context: Any,
) -> str:
    profile = getattr(material_context, "learning_domain_profile", None)
    profile_description = _clean_course_metadata_text(
        getattr(profile, "course_description", "") if profile is not None else "",
        max_chars=360,
    )
    discipline = _clean_course_metadata_text(
        getattr(profile, "discipline", "") if profile is not None else "",
        max_chars=80,
    )
    sub_discipline = _clean_course_metadata_text(
        getattr(profile, "sub_discipline", "") if profile is not None else "",
        max_chars=80,
    )
    topics = (
        [
            _clean_course_metadata_text(str(item), max_chars=40)
            for item in list(getattr(profile, "key_topics", []) or [])[:6]
            if str(item or "").strip()
        ]
        if profile is not None
        else []
    )
    plan_text = _clean_course_metadata_text(str(plan_payload.get("plan") or ""), max_chars=420)

    parts: list[str] = []
    if profile_description:
        parts.append(profile_description)
    elif discipline or sub_discipline or topics:
        label = " > ".join(item for item in [discipline, sub_discipline] if item)
        topic_text = "、".join(topics)
        if label and topic_text:
            parts.append(f"{label}学习空间，围绕{topic_text}展开。")
        elif label:
            parts.append(f"{label}学习空间。")
        elif topic_text:
            parts.append(f"围绕{topic_text}展开的学习空间。")
    if plan_text and plan_text not in parts:
        parts.append(plan_text)
    return _clean_course_metadata_text(" ".join(parts), max_chars=800)


def _build_course_user_intent_from_state(state: Mapping[str, Any]) -> str:
    intent = _clean_course_metadata_text(str(state.get("intent") or ""), max_chars=420)
    if intent:
        return intent
    return _clean_course_metadata_text(str(state.get("user_prompt") or ""), max_chars=420)


def _maybe_update_course_from_planner(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    generated_name: str,
    generated_icon_key: str | None = None,
    description: str = "",
    user_intent: str = "",
) -> None:
    title = " ".join(str(generated_name or "").strip().split())
    should_apply_title = bool(title) and title.casefold() not in _AUTO_TITLE_PLACEHOLDERS
    description = _clean_course_metadata_text(description, max_chars=800)
    user_intent = _clean_course_metadata_text(user_intent, max_chars=420)
    course_row = session.exec(
        select(Course).where(Course.id == course_id, Course.user_id == user_id)
    ).first()
    if course_row is None:
        return

    updated = False
    if should_apply_title and _needs_auto_course_name(course_row.name):
        course_row.name = title
        icon_key = normalize_course_icon_key(generated_icon_key)
        if icon_key:
            set_course_icon_key(course_row, icon_key)
        updated = True
    if description and course_row.description != description:
        course_row.description = description
        updated = True
    if user_intent and course_row.user_intent != user_intent:
        course_row.user_intent = user_intent
        updated = True
    if not updated:
        return

    course_row.updated_at = utcnow()
    session.add(course_row)
    session.commit()
    logger.info(
        "planner_course_metadata_updated",
        course_id=course_id,
        generated_name=title or None,
        description_chars=len(description),
        user_intent_chars=len(user_intent),
    )


def _apply_generated_course_identity(
    plan_payload: dict[str, Any],
    *,
    generated_name: str,
    generated_icon_key: str,
) -> str:
    title = " ".join(str(generated_name or "").strip().split())
    if title and title.casefold() not in _AUTO_TITLE_PLACEHOLDERS:
        plan_payload["course_name"] = title
    icon_key = normalize_course_icon_key(generated_icon_key)
    if icon_key:
        plan_payload["course_icon"] = icon_key
    return title if title and title.casefold() not in _AUTO_TITLE_PLACEHOLDERS else ""


def _update_planner_session_meta(
    session: Session,
    session_item: ChatSession,
    **updates: Any,
) -> ChatSession:
    meta = _planner_meta(session_item)
    meta.update(updates)
    session_item.meta_json = meta
    session_item.updated_at = utcnow()
    session_item.last_message_at = session_item.updated_at
    session.add(session_item)
    session.commit()
    session.refresh(session_item)
    return session_item


def _get_planner_session(
    session: Session,
    *,
    course_id: str,
    session_id: str,
    user_id: str,
) -> ChatSession | None:
    item = get_chat_session(session, course_id=course_id, session_id=session_id, user_id=user_id)
    if item is None or item.source != PLANNER_CHAT_SOURCE:
        return None
    return item


def _get_latest_planner_session(session: Session, *, course_id: str, user_id: str) -> ChatSession | None:
    stmt = (
        select(ChatSession)
        .where(
            ChatSession.course_id == course_id,
            ChatSession.user_id == user_id,
            ChatSession.source == PLANNER_CHAT_SOURCE,
        )
        .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
        .limit(1)
    )
    return session.exec(stmt).first()


def _get_active_planning_session(session: Session, *, course_id: str, user_id: str) -> ChatSession | None:
    stmt = (
        select(ChatSession)
        .where(
            ChatSession.course_id == course_id,
            ChatSession.user_id == user_id,
            ChatSession.source == PLANNER_CHAT_SOURCE,
        )
        .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
    )
    for item in session.exec(stmt).all():
        if _planner_status(item) == "planning":
            return item
    return None


def _list_planner_turns(session: Session, *, session_id: str, course_id: str, user_id: str) -> list[ChatMessage]:
    stmt = (
        select(ChatMessage)
        .where(
            ChatMessage.session_id == session_id,
            ChatMessage.course_id == course_id,
            ChatMessage.user_id == user_id,
            ChatMessage.source == PLANNER_CHAT_SOURCE,
        )
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
    )
    return list(session.exec(stmt).all())


def _plan_response(
    *,
    course_id: str,
    selected_file_ids: list[str],
    session_id: str,
    confirmed_plan_id: str | None,
    status: str,
    plan: dict[str, Any],
    model_override: str | None = None,
) -> BuildPlannerPlanResponse:
    return BuildPlannerPlanResponse(
        course_id=course_id,
        selected_file_ids=selected_file_ids,
        course_name=str(plan.get("course_name") or ""),
        course_icon=str(plan.get("course_icon") or ""),
        user_prompt=str(plan.get("user_prompt") or ""),
        digest_mode=str(plan.get("digest_mode") or "systematic"),
        intent=str(plan.get("intent") or ""),
        summary=str(plan.get("summary") or ""),
        suggestion=str(plan.get("suggestion") or ""),
        plan=str(plan.get("plan") or ""),
        chapters=list(plan.get("chapters") or []),
        build_constraints=dict(plan.get("build_constraints") or {}),
        status=status,
        planner_session_id=session_id,
        confirmed_plan_id=confirmed_plan_id,
        model_override=normalize_runtime_model_override(model_override),
    )


def _runtime_stats_response(final_state: Mapping[str, Any] | None) -> BuildPlannerRuntimeStatsResponse | None:
    if not isinstance(final_state, Mapping):
        return None

    steps: list[BuildPlannerStepStatsResponse] = []
    for name, field_name in STEP_TIMING_FIELDS:
        elapsed_ms = int(final_state.get(field_name, 0) or 0)
        if elapsed_ms <= 0:
            continue
        steps.append(
            BuildPlannerStepStatsResponse(
                name=name,
                elapsed_ms=elapsed_ms,
                status="ok",
            )
        )
    return BuildPlannerRuntimeStatsResponse(
        elapsed_ms=int(final_state.get("workflow_elapsed_ms", 0) or 0),
        steps=steps,
    )


def planner_session_response_from_state(final_state: Mapping[str, Any]) -> BuildPlannerSessionResponse:
    record = dict(final_state.get("planner_record") or {})
    plan = dict(final_state.get("plan") or {})
    turns = [dict(turn) for turn in list(final_state.get("planner_turns") or [])]
    course_id = str(record.get("course_id") or final_state.get("course_id") or "")
    session_id = str(record.get("id") or final_state.get("planner_session_id") or "")
    status = str(record.get("status") or "draft")
    model_override = normalize_runtime_model_override(final_state.get("model_override") or record.get("model_override"))
    logger.info(
        "planner_response_from_state",
        planner_session_id=session_id,
        has_state_plan=bool(final_state.get("plan")),
        has_record_latest_plan=bool(record.get("latest_plan_json")),
        state_error=final_state.get("error"),
        plan_chapter_count=len(list(plan.get("chapters") or [])),
    )
    return BuildPlannerSessionResponse(
        session_id=session_id,
        course_id=course_id,
        title=str(record.get("title") or ""),
        status=status,
        revision=len(turns),
        model_override=model_override,
        latest_plan=_plan_response(
            course_id=course_id,
            selected_file_ids=list(final_state.get("selected_file_ids") or []),
            session_id=session_id,
            confirmed_plan_id=record.get("confirmed_plan_id"),
            status=status,
            plan=plan,
            model_override=model_override,
        ),
        turns=[_turn_response_from_snapshot(turn) for turn in turns],
        runtime_stats=_runtime_stats_response(final_state),
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def _planner_session_response(
    record: ChatSession,
    *,
    course_id: str,
    selected_file_ids: list[str],
    plan: dict[str, Any],
    turns: list[ChatMessage],
) -> BuildPlannerSessionResponse:
    meta = _planner_meta(record)
    model_override = _planner_model_override(record)
    return BuildPlannerSessionResponse(
        session_id=record.id,
        course_id=course_id,
        title=record.title,
        status=_planner_status(record),
        revision=len(turns),
        model_override=model_override,
        latest_plan=_plan_response(
            course_id=course_id,
            selected_file_ids=selected_file_ids,
            session_id=record.id,
            confirmed_plan_id=meta.get("confirmed_plan_id"),
            status=_planner_status(record),
            plan=plan,
            model_override=model_override,
        ),
        turns=[_turn_response_from_snapshot(_turn_snapshot(turn)) for turn in turns],
        runtime_stats=None,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _workflow_files_or_raise(
    *,
    course_id: str,
    planner_files: list[RawFile],
) -> list[RawFile]:
    workflow_files = _select_planner_workflow_files(planner_files)
    if planner_files and not workflow_files:
        raise PlannerMaterialsNotReadyError(course_id)
    return workflow_files


def _turn_snapshot(turn: ChatMessage) -> dict[str, Any]:
    return {
        "id": turn.id,
        "role": turn.role,
        "content": turn.content,
        "created_at": turn.created_at,
        "plan_json": dict((turn.meta_json or {}).get("plan_json") or {}),
    }


def _create_planner_message(
    session: Session,
    *,
    record: ChatSession,
    role: str,
    content: str,
    plan: dict[str, Any] | None = None,
) -> ChatMessage:
    message = create_chat_message(
        session,
        course_id=record.course_id,
        user_id=record.user_id,
        session_id=record.id,
        role=role,
        content=content,
        turn_id=f"planner:{record.id}:{uuid.uuid4().hex}",
        source=PLANNER_CHAT_SOURCE,
        anchor_id=record.id,
        meta_json={
            "source": PLANNER_CHAT_SOURCE,
            "message_kind": "planner_plan" if role == "assistant" else "planner_user_request",
            "planner_session_id": record.id,
            "plan_json": plan if role == "assistant" else None,
            "plan": str((plan or {}).get("plan") or ""),
        },
    )
    touch_chat_session(
        session,
        course_id=record.course_id,
        user_id=record.user_id,
        session_id=record.id,
        title=record.title,
        touched_at=message.created_at,
    )
    return message


def _record_snapshot(record: ChatSession) -> dict[str, Any]:
    meta = _planner_meta(record)
    return {
        "id": record.id,
        "course_id": record.course_id,
        "user_id": record.user_id,
        "title": record.title,
        "status": _planner_status(record),
        "user_prompt": str(meta.get("user_prompt") or ""),
        "digest_mode": str(meta.get("digest_mode") or ""),
        "selected_file_ids": _planner_selected_file_ids(record),
        "latest_plan_json": _planner_plan(record),
        "latest_summary": str(meta.get("latest_summary") or ""),
        "confirmed_plan_id": meta.get("confirmed_plan_id"),
        "model_override": _planner_model_override(record),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _render_final_plan_markdown(plan_payload: dict[str, Any]) -> str:
    plan_text = str(plan_payload.get("plan") or "").strip()
    suggestion = str(plan_payload.get("suggestion") or "").strip()
    chapters = [
        item
        for item in list(plan_payload.get("chapters") or [])
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    ]
    lines = [
        "# Planner",
        "",
        f"> 模式：{planner_mode_label(plan_payload.get('digest_mode'))}",
        f"> plan：{plan_text or '已生成一份可确认的构建方案。'}",
    ]
    if suggestion:
        lines.extend(["", "## suggestion", suggestion])
    chapter_lines = []
    for index, chapter in enumerate(chapters, start=1):
        title = str(chapter.get("title") or "").strip()
        required_text = "；".join(
            str(item).strip()
            for item in list(chapter.get("required_elements") or [])[:3]
            if str(item).strip()
        )
        chapter_lines.append(f"{index}. {title}：{required_text}")
    lines.extend(
        [
            "",
            "## 章节安排",
            *chapter_lines,
        ]
    )
    return "\n".join(lines).strip()


def _build_docgen_history_brief(turns: list[ChatMessage]) -> str:
    lines: list[str] = []
    for turn in turns:
        role = "用户" if turn.role == "user" else "规划器"
        content = str(turn.content or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _recent_planner_turns(turns: list[ChatMessage], *, history_turns: int) -> list[ChatMessage]:
    if history_turns <= 0:
        return list(turns)

    selected: list[ChatMessage] = []
    user_turns = 0
    for turn in reversed(turns):
        selected.append(turn)
        if turn.role == "user":
            user_turns += 1
        if user_turns >= history_turns:
            break
    return list(reversed(selected))


def _planner_history_turns() -> int:
    try:
        return max(1, int(get_teaching_runtime_config().planner.history_turns or 10))
    except Exception:
        return 10


def _build_planner_message_history(turns: list[ChatMessage]) -> list[str]:
    lines: list[str] = []
    recent_turns = _recent_planner_turns(turns, history_turns=_planner_history_turns())
    for turn in recent_turns:
        role = "用户" if turn.role == "user" else "规划器"
        content = str(turn.content or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return lines


def _planner_plan_chapter_count(plan: Mapping[str, Any] | None) -> int:
    if not plan:
        return 0
    chapters = plan.get("chapters") or []
    if isinstance(chapters, list):
        return len(chapters)
    return 0


def _build_planner_context_stats(
    *,
    turns: list[ChatMessage],
    message_history: list[str],
    latest_plan: Mapping[str, Any] | None,
    feedback_message: str,
    user_prompt: str,
) -> dict[str, Any]:
    return {
        "stored_turn_count": len(turns),
        "prompt_message_count": len(message_history),
        "history_turn_limit": _planner_history_turns(),
        "latest_plan_chapter_count": _planner_plan_chapter_count(latest_plan),
        "latest_feedback_chars": len(feedback_message or ""),
        "user_prompt_chars": len(user_prompt or ""),
    }


def _build_planner_context_payload(
    record: ChatSession,
    *,
    turns: list[ChatMessage],
    plan: dict[str, Any],
) -> dict[str, Any]:
    meta = _planner_meta(record)
    assistant_turns = [turn for turn in turns if turn.role == "assistant"]
    user_turns = [turn for turn in turns if turn.role == "user"]
    latest_outline = assistant_turns[-1].content if assistant_turns else _render_final_plan_markdown(plan)
    return {
        "planner_session_id": record.id,
        "planner_turn_count": len(turns),
        "user_revision_count": max(0, len(user_turns) - 1),
        "assistant_revision_count": len(assistant_turns),
        "latest_plan": str(plan.get("plan") or meta.get("latest_summary") or ""),
        "planner_outline_markdown": str(latest_outline or "").strip(),
        "docgen_history_brief": _build_docgen_history_brief(turns),
    }


def _normalize_persisted_plan(
    plan: dict[str, Any] | None,
    *,
    course_id: str,
    user_prompt: str,
    digest_mode: str,
    material_context: Any | None = None,
    latest_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return normalize_planner_payload(
        plan or {},
        course_id=course_id,
        user_prompt=user_prompt,
        requested_digest_mode=digest_mode,
        shared_inputs=material_context,
        latest_plan=latest_plan,
    )


def _operation(state: Mapping[str, Any]) -> str:
    return str(state.get("planner_operation") or "generate_only").strip().lower() or "generate_only"


def prepare_planner_run(state: Mapping[str, Any]) -> dict[str, Any]:
    """Prepare persisted planner run data before material loading.

    Called by the normal `collect_planner_context` node. This keeps session DB
    IO inside the real workflow path without adding a separate "session node".
    """

    operation = _operation(state)
    logger.info(
        "planner_prepare_run_started",
        operation=operation,
        course_id=state.get("course_id"),
        planner_session_id=state.get("planner_session_id"),
        requested_file_id_count=len(state.get("requested_file_ids") or []),
    )
    if operation == "generate_only":
        logger.info("planner_prepare_run_skipped_for_generate_only")
        return {}

    course_id = str(state["course_id"])
    user_id = str(state.get("user_id") or "local")

    if operation == "create":
        # 第一轮规划：创建 DB session、绑定文件选择，只返回后续 graph 需要的字段。
        planner_defaults = get_teaching_runtime_config().planner
        user_prompt = str(state.get("user_prompt") or "").strip()
        digest_mode = (
            state.get("digest_mode") or planner_defaults.default_digest_mode
        ).strip() or planner_defaults.default_digest_mode

        with managed_session() as session:
            course_row = session.exec(
                select(Course).where(Course.id == course_id, Course.user_id == user_id)
            ).first()
            active_planning = _get_active_planning_session(session, course_id=course_id, user_id=user_id)
            if active_planning is not None:
                raise BuildPlannerSessionBusyError(active_planning.id)
            planner_files = _select_planner_files(
                session,
                course_id=course_id,
                file_ids=list(state.get("requested_file_ids") or []),
            )
            workflow_files = _workflow_files_or_raise(
                course_id=course_id,
                planner_files=planner_files,
            )
            selected_file_ids = _file_ids(planner_files)
            workflow_file_ids = _file_ids(workflow_files)
            selected_file_ids = _file_ids(planner_files)
            session_title = str(
                state.get("session_title")
                or user_prompt
                or getattr(course_row, "name", "")
                or "学习规划"
            )
            record = create_chat_session(
                session,
                course_id=course_id,
                user_id=user_id,
                session_id=str(state["planner_session_id"]),
                title=session_title,
                source=PLANNER_CHAT_SOURCE,
                meta_json=_planner_session_meta(
                    session_id=str(state["planner_session_id"]),
                    status="planning",
                    user_prompt=user_prompt,
                    digest_mode=digest_mode,
                    selected_file_ids=selected_file_ids,
                    model_override=state.get("model_override"),
                ),
            )
            user_turn = _create_planner_message(
                session,
                record=record,
                role="user",
                content=user_prompt,
            )
            logger.info(
                "planner_prepare_run_created_session",
                course_id=course_id,
                planner_session_id=record.id,
                selected_file_count=len(selected_file_ids),
                workflow_file_count=len(workflow_file_ids),
                selected_file_ids=selected_file_ids,
            )
            message_history = _build_planner_message_history([user_turn])
            return {
                "file_ids": workflow_file_ids,
                "selected_file_ids": selected_file_ids,
                "user_prompt": user_prompt,
                "digest_mode": digest_mode,
                "message_history": message_history,
                "planner_context_stats": _build_planner_context_stats(
                    turns=[user_turn],
                    message_history=message_history,
                    latest_plan=None,
                    feedback_message="",
                    user_prompt=user_prompt,
                ),
                "planner_record": _record_snapshot(record),
                "planner_turns": [_turn_snapshot(user_turn)],
            }

    if operation == "append":
        # 修订规划：读取已有 session，追加用户反馈，并补齐 latest_plan/message_history。
        feedback = str(state.get("feedback_message") or "").strip()
        with managed_session() as session:
            record = _get_planner_session(
                session,
                course_id=course_id,
                session_id=str(state["planner_session_id"]),
                user_id=user_id,
            )
            if record is None:
                raise BuildPlannerSessionNotFoundError(str(state["planner_session_id"]))
            if _planner_status(record) == "planning":
                raise BuildPlannerSessionBusyError(record.id)
            meta = _planner_meta(record)
            logger.info(
                "planner_prepare_run_loaded_session",
                course_id=course_id,
                planner_session_id=record.id,
                has_latest_plan=bool(meta.get("latest_plan")),
                selected_file_count=len(_planner_selected_file_ids(record)),
            )

            record = _update_planner_session_meta(
                session,
                record,
                planner_status="planning",
                model_override=normalize_runtime_model_override(state.get("model_override")),
                confirmed_plan_id=None,
                confirmed_plan=None,
            )
            _create_planner_message(
                session,
                record=record,
                role="user",
                content=feedback,
            )
            turns = _list_planner_turns(session, session_id=record.id, course_id=course_id, user_id=user_id)
            message_history = _build_planner_message_history(turns)
            latest_plan = _planner_plan(record)
            selected_file_ids = _planner_selected_file_ids(record)
            raw_files = list_raw_files_by_ids(session, course_id, selected_file_ids)
            workflow_files = _select_planner_workflow_files(raw_files)
            workflow_file_ids = [require_id(item.id, "RawFile.id") for item in workflow_files]
            if selected_file_ids and not workflow_file_ids:
                raise PlannerMaterialsNotReadyError(course_id)
            selected_file_ids = _file_ids(raw_files)
            logger.info(
                "planner_prepare_run_history_ready",
                course_id=course_id,
                planner_session_id=record.id,
                stored_turn_count=len(turns),
                prompt_message_count=len(message_history),
                history_turn_limit=_planner_history_turns(),
                latest_plan_chapter_count=len(list(latest_plan.get("chapters") or [])),
            )
            return {
                "file_ids": workflow_file_ids,
                "selected_file_ids": selected_file_ids,
                "user_prompt": str(meta.get("user_prompt") or ""),
                "digest_mode": str(meta.get("digest_mode") or ""),
                "message_history": message_history,
                "latest_plan": latest_plan,
                "planner_context_stats": _build_planner_context_stats(
                    turns=turns,
                    message_history=message_history,
                    latest_plan=latest_plan,
                    feedback_message=feedback,
                    user_prompt=str(meta.get("user_prompt") or ""),
                ),
                "planner_record": _record_snapshot(record),
                "planner_turns": [_turn_snapshot(turn) for turn in turns],
            }

    raise ValueError(f"Unsupported planner operation: {operation}")


def save_planner_result(
    state: Mapping[str, Any],
    *,
    plan: dict[str, Any],
    material_context: Any,
) -> dict[str, Any]:
    """Persist final planner output from the normal finalize node."""

    if _operation(state) == "generate_only":
        logger.info("planner_save_skipped_for_generate_only", planner_session_id=state.get("planner_session_id"))
        return {}

    # graph 已经生成稳定 plan 合同；这里只负责写持久化状态，并返回 API 需要的快照。
    course_id = str(state["course_id"])
    user_id = str(state.get("user_id") or "local")
    with managed_session() as session:
        record = _get_planner_session(
            session,
            course_id=course_id,
            session_id=str(state["planner_session_id"]),
            user_id=user_id,
        )
        if record is None:
            raise BuildPlannerSessionNotFoundError(str(state["planner_session_id"]))
        meta = _planner_meta(record)

        logger.info(
            "planner_save_started",
            course_id=course_id,
            planner_session_id=record.id,
            input_chapter_count=len(list((plan or {}).get("chapters") or [])),
            has_previous_plan=bool(meta.get("latest_plan")),
        )
        persisted_plan = _normalize_persisted_plan(
            plan,
            course_id=course_id,
            user_prompt=str(meta.get("user_prompt") or ""),
            digest_mode=str(meta.get("digest_mode") or ""),
            material_context=material_context,
            latest_plan=_planner_plan(record),
        )
        generated_title = _apply_generated_course_identity(
            persisted_plan,
            generated_name=str(state.get("generated_course_name") or ""),
            generated_icon_key=str(state.get("generated_course_icon_key") or ""),
        )
        course_description = _build_course_description_from_plan(
            persisted_plan,
            material_context=material_context,
        )
        course_user_intent = _build_course_user_intent_from_state(state)
        _maybe_update_course_from_planner(
            session,
            course_id=course_id,
            user_id=user_id,
            generated_name=generated_title,
            generated_icon_key=str(state.get("generated_course_icon_key") or ""),
            description=course_description,
            user_intent=course_user_intent,
        )
        record = _update_planner_session_meta(
            session,
            record,
            latest_plan=persisted_plan,
            latest_summary=str(persisted_plan.get("plan") or ""),
            digest_mode=str(persisted_plan.get("digest_mode") or meta.get("digest_mode") or ""),
            model_override=normalize_runtime_model_override(state.get("model_override")),
            planner_status="draft",
            confirmed_plan_id=None,
            confirmed_plan=None,
        )
        if generated_title and str(record.title or "").strip() != generated_title:
            record.title = generated_title
            record.updated_at = utcnow()
            session.add(record)
            session.commit()
            session.refresh(record)
        _create_planner_message(
            session,
            record=record,
            role="assistant",
            content=_render_final_plan_markdown(persisted_plan),
            plan=persisted_plan,
        )
        turns = _list_planner_turns(session, session_id=record.id, course_id=course_id, user_id=user_id)
        selected_file_ids = _planner_selected_file_ids(record)
        logger.info(
            "planner_save_finished",
            course_id=course_id,
            planner_session_id=record.id,
            persisted_chapter_count=len(list(persisted_plan.get("chapters") or [])),
            turn_count=len(turns),
        )
        return {
            "plan": persisted_plan,
            "digest_mode": str(persisted_plan.get("digest_mode") or state.get("digest_mode") or ""),
            "model_override": _planner_model_override(record),
            "selected_file_ids": selected_file_ids,
            "planner_record": _record_snapshot(record),
            "planner_turns": [_turn_snapshot(turn) for turn in turns],
        }


def _normalized_plan_payload(
    plan: dict[str, Any],
    *,
    planner_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    build_constraints = dict(plan.get("build_constraints") or {})
    chapters = _ensure_chapter_count_payload(
        list(plan.get("chapters") or []),
        min_chapters=int(build_constraints.get("min_chapters", 0) or 0),
        max_chapters=int(build_constraints.get("max_chapters", 0) or 0),
        digest_mode=str(plan.get("digest_mode") or ""),
        user_prompt=str(plan.get("user_prompt") or ""),
        plan=plan,
    )
    payload = {
        "course_name": str(plan.get("course_name") or ""),
        "course_icon": str(plan.get("course_icon") or ""),
        "user_prompt": str(plan.get("user_prompt") or ""),
        "digest_mode": str(plan.get("digest_mode") or ""),
        "intent": str(plan.get("intent") or ""),
        "summary": str(plan.get("summary") or ""),
        "suggestion": str(plan.get("suggestion") or ""),
        "plan": str(plan.get("plan") or ""),
        "chapters": chapters,
        "build_constraints": build_constraints,
        "model_override": normalize_runtime_model_override(plan.get("model_override")) or "",
    }
    context_payload = dict(planner_context or plan.get("planner_context") or {})
    if context_payload:
        payload["planner_context"] = context_payload
        payload["docgen_history_brief"] = str(context_payload.get("docgen_history_brief") or "")
    return payload


def _dedupe_payload_texts(items: list[object], *, limit: int = 10) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = " ".join(str(item or "").strip().split())
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _reindex_chapter_payload(chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reindexed: list[dict[str, Any]] = []
    for index, chapter in enumerate(chapters, start=1):
        item = dict(chapter)
        item["chapter_index"] = index
        reindexed.append(item)
    return reindexed


def _merge_chapter_payload_into(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    title = " ".join(str(extra.get("title") or "").strip().split())
    required = list(merged.get("required_elements") or [])
    if title:
        required.append(f"超出章节预算后合并覆盖：{title}")
    required.extend(list(extra.get("required_elements") or [])[:3])
    merged["required_elements"] = _dedupe_payload_texts(required, limit=10)
    objective = " ".join(str(merged.get("objective") or "").strip().split())
    if title:
        suffix = f"同时吸收《{title}》中的相邻内容。"
        merged["objective"] = "；".join(_dedupe_payload_texts([objective, suffix], limit=2))
    writing = " ".join(str(merged.get("writing_instructions") or "").strip().split())
    if title:
        guard = f"同时处理《{title}》的相邻内容，保持边界清楚，避免重复展开。"
        merged["writing_instructions"] = " ".join(_dedupe_payload_texts([writing, guard], limit=2))
    return merged


def _cap_chapter_payload(
    chapters: list[dict[str, Any]],
    *,
    max_chapters: int,
) -> list[dict[str, Any]]:
    if max_chapters <= 0 or len(chapters) <= max_chapters:
        return _reindex_chapter_payload(chapters)
    kept = [dict(item) for item in chapters[:max_chapters]]
    for extra in chapters[max_chapters:]:
        kept[-1] = _merge_chapter_payload_into(kept[-1], dict(extra))
    return _reindex_chapter_payload(kept)


def _ensure_chapter_count_payload(
    chapters: list[Any],
    *,
    min_chapters: int,
    max_chapters: int = 0,
    digest_mode: str,
    user_prompt: str,
    plan: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    normalized = [dict(item) for item in chapters if isinstance(item, dict)]
    effective_max = max(max_chapters, min_chapters) if max_chapters > 0 else 0
    return _cap_chapter_payload(normalized, max_chapters=effective_max)


def mark_planner_session_failed(*, course_id: str, user_id: str, session_id: str) -> None:
    with managed_session() as session:
        record = _get_planner_session(session, course_id=course_id, session_id=session_id, user_id=user_id)
        if record is None:
            return
        _update_planner_session_meta(session, record, planner_status="failed")


def mark_planner_session_cancelled(*, course_id: str, user_id: str, session_id: str) -> None:
    with managed_session() as session:
        record = _get_planner_session(session, course_id=course_id, session_id=session_id, user_id=user_id)
        if record is None:
            return
        _update_planner_session_meta(session, record, planner_status="cancelled")


def mark_planner_session_draft(*, course_id: str, user_id: str, session_id: str) -> None:
    with managed_session() as session:
        record = _get_planner_session(session, course_id=course_id, session_id=session_id, user_id=user_id)
        if record is None:
            return
        _update_planner_session_meta(session, record, planner_status="draft")


def confirm_planner_session(
    session: Session,
    *,
    course: Course,
    user_id: str,
    session_id: str,
) -> BuildPlannerConfirmResponse:
    """确认当前 Planner 草稿，并冻结成 DocGen 可执行的 confirmed plan。"""

    record = _get_planner_session(session, course_id=course.id, session_id=session_id, user_id=user_id)
    if record is None:
        raise BuildPlannerSessionNotFoundError(session_id)
    meta = _planner_meta(record)
    latest_plan = _planner_plan(record)
    if not latest_plan:
        raise BuildPlannerEmptyPlanError(session_id)

    turns = _list_planner_turns(session, session_id=record.id, course_id=course.id, user_id=user_id)
    planner_context = _build_planner_context_payload(
        record,
        turns=turns,
        plan=latest_plan,
    )
    model_override = _planner_model_override(record)
    plan_payload = _normalized_plan_payload(
        latest_plan,
        planner_context=planner_context,
    )
    plan_payload["model_override"] = model_override or ""
    current_confirmed = None
    if meta.get("confirmed_plan_id"):
        current_confirmed = get_confirmed_plan(
            session,
            course_id=course.id,
            plan_id=str(meta.get("confirmed_plan_id")),
            user_id=user_id,
        )
    if (
        current_confirmed is not None
        and _normalized_plan_payload(dict(current_confirmed.plan_json or {})) == plan_payload
    ):
        confirmed = current_confirmed
    else:
        version_no = next_confirmed_plan_version_no(session, course_id=course.id, user_id=user_id)
        confirmed = create_confirmed_plan(
            session,
            ConfirmedBuildPlan(
                id=uuid.uuid4().hex,
                version_no=version_no,
                course_id=course.id,
                planner_session_id=session_id,
                user_id=user_id,
                status="confirmed",
                user_prompt=str(meta.get("user_prompt") or ""),
                digest_mode=str(plan_payload.get("digest_mode") or meta.get("digest_mode") or ""),
                selected_file_ids=_planner_selected_file_ids(record),
                chapters=list(plan_payload.get("chapters") or []),
                build_constraints=dict(plan_payload.get("build_constraints") or {}),
                plan=str(plan_payload.get("plan") or meta.get("latest_summary") or ""),
                plan_json=plan_payload,
            ),
        )

    record = _update_planner_session_meta(
        session,
        record,
        latest_plan=plan_payload,
        latest_summary=str(plan_payload.get("plan") or ""),
        confirmed_plan_id=confirmed.id,
        model_override=model_override,
        planner_status="confirmed",
    )
    selected_file_ids = _planner_selected_file_ids(record)
    return BuildPlannerConfirmResponse(
        planner_session_id=record.id,
        confirmed_plan_id=confirmed.id,
        version_no=int(confirmed.version_no or 1),
        course_id=course.id,
        status=_planner_status(record),
        digest_mode=confirmed.digest_mode,
        model_override=model_override,
        selected_file_ids=list(confirmed.selected_file_ids),
        user_prompt=confirmed.user_prompt,
        course_name=str(plan_payload.get("course_name") or ""),
        course_icon=str(plan_payload.get("course_icon") or ""),
        intent=str(plan_payload.get("intent") or ""),
        summary=str(plan_payload.get("summary") or ""),
        suggestion=str(plan_payload.get("suggestion") or ""),
        plan=str(plan_payload.get("plan") or confirmed.plan or ""),
        chapters=list(plan_payload.get("chapters") or []),
        build_constraints=dict(plan_payload.get("build_constraints") or {}),
        plan_json=plan_payload,
        status_history=[confirmed.status, _planner_status(record)],
        created_at=confirmed.created_at,
        updated_at=confirmed.updated_at,
    )


def get_latest_planner_session(
    session: Session,
    *,
    course: Course,
    user_id: str,
) -> BuildPlannerSessionResponse | None:
    record = _get_latest_planner_session(session, course_id=course.id, user_id=user_id)
    if record is None:
        logger.info("planner_latest_none", course_id=course.id, user_id=user_id)
        return None
    turns = _list_planner_turns(session, session_id=record.id, course_id=course.id, user_id=user_id)
    plan_payload = _planner_plan(record)
    logger.info(
        "planner_latest_found",
        course_id=course.id,
        user_id=user_id,
        planner_session_id=record.id,
        turn_count=len(turns),
        has_latest_plan=bool(plan_payload),
        chapter_count=len(list(plan_payload.get("chapters") or [])),
    )
    return _planner_session_response(
        record,
        course_id=course.id,
        selected_file_ids=_planner_selected_file_ids(record),
        plan=plan_payload,
        turns=turns,
    )


def get_planner_adjust_click_context(
    session: Session,
    *,
    course: Course,
    user_id: str,
    session_id: str,
) -> dict[str, Any]:
    """Return sparse session context for tracing the UI adjust entrypoint."""

    record = _get_planner_session(session, course_id=course.id, session_id=session_id, user_id=user_id)
    if record is None:
        raise BuildPlannerSessionNotFoundError(session_id)

    meta = _planner_meta(record)
    turns = _list_planner_turns(session, session_id=record.id, course_id=course.id, user_id=user_id)
    latest_plan = _planner_plan(record)
    selected_file_ids = _planner_selected_file_ids(record)
    context = {
        "course_id": course.id,
        "user_id": user_id,
        "planner_session_id": record.id,
        "status": _planner_status(record),
        "digest_mode": str(meta.get("digest_mode") or ""),
        "turn_count": len(turns),
        "selected_file_count": len(selected_file_ids),
        "has_latest_plan": bool(latest_plan),
        "latest_plan_chapter_count": len(list(latest_plan.get("chapters") or [])),
        "confirmed_plan_id": meta.get("confirmed_plan_id"),
    }
    logger.info(
        "planner_adjust_click_context_loaded",
        course_id=course.id,
        user_id=user_id,
        planner_session_id=record.id,
        status=context["status"],
        turn_count=context["turn_count"],
        has_latest_plan=context["has_latest_plan"],
    )
    return context


def get_confirmed_plan_or_raise(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    plan_id: str,
) -> ConfirmedBuildPlan:
    plan = get_confirmed_plan(session, course_id=course_id, plan_id=plan_id, user_id=user_id)
    if plan is None:
        raise ConfirmedBuildPlanNotFoundError(plan_id)
    return plan


def mark_confirmed_plan_status(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    plan_id: str,
    status: str,
) -> None:
    plan = get_confirmed_plan(session, course_id=course_id, plan_id=plan_id, user_id=user_id)
    if plan is None:
        return
    plan.status = status
    plan.updated_at = utcnow()
    update_confirmed_plan(session, plan)
    if plan.planner_session_id:
        planner_session = _get_planner_session(
            session,
            course_id=course_id,
            session_id=plan.planner_session_id,
            user_id=user_id,
        )
        if planner_session is not None and _planner_meta(planner_session).get("confirmed_plan_id") == plan.id:
            _update_planner_session_meta(session, planner_session, planner_status=status)


__all__ = [
    "confirm_planner_session",
    "get_confirmed_plan_or_raise",
    "get_planner_adjust_click_context",
    "get_latest_planner_session",
    "mark_confirmed_plan_status",
    "mark_planner_session_cancelled",
    "mark_planner_session_draft",
    "mark_planner_session_failed",
    "prepare_planner_run",
    "planner_session_response_from_state",
    "save_planner_result",
]
