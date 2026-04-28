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
from app.models.subject import Subject
from app.repositories.confirmed_plan_repo import (
    create_confirmed_plan,
    get_confirmed_plan,
    update_confirmed_plan,
)
from app.repositories.chats_repo import (
    create_chat_message,
    create_chat_session,
    get_chat_session,
    touch_chat_session,
)
from app.repositories.files_repo import list_all_raw_files_by_subject, list_raw_files_by_ids, list_raw_files_by_uids
from app.shared.infra.database import managed_session
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
from app.utils.presenters import require_id, require_uid
from app.utils.time import utcnow
from app.workflows.digest.common.file_status import is_markdown_ready_for_digest
from app.workflows.digest.common.runtime_config import get_teaching_runtime_config
from app.workflows.digest.planner.lib.plans import normalize_planner_payload
from app.workflows.digest.planner.lib.steps import STEP_TIMING_FIELDS
from app.workflows.support.subjects.icons import normalize_subject_icon_key, set_subject_icon_key

logger = structlog.get_logger(__name__)
PLANNER_CHAT_SOURCE = "build_planner"
_AUTO_TITLE_PLACEHOLDERS = {"", "untitled subject", "新学科", "无标题", "未命名", "未命名学科"}


def _select_planner_files(
    session: Session,
    *,
    subject_id: str,
    file_uids: list[str] | None,
) -> list[RawFile]:
    available_files = [item for item in list_all_raw_files_by_subject(session, subject_id) if item.id is not None]
    if not file_uids:
        return available_files
    requested = list_raw_files_by_uids(session, subject_id, file_uids)
    found_uids = {require_uid(item.uid, "RawFile.uid") for item in requested}
    missing = [uid for uid in file_uids if uid not in found_uids]
    if missing:
        raise RawFileNotFoundError(missing[0])
    available_ids = {require_id(item.id, "RawFile.id") for item in available_files}
    return [item for item in requested if item.id is not None and require_id(item.id, "RawFile.id") in available_ids]


def _select_planner_workflow_files(raw_files: list[RawFile]) -> list[RawFile]:
    ready = [item for item in raw_files if is_markdown_ready_for_digest(item)]
    return ready or raw_files


def _file_ids(raw_files: list[RawFile]) -> list[int]:
    return [require_id(item.id, "RawFile.id") for item in raw_files if item.id is not None]


def _file_uids(raw_files: list[RawFile]) -> list[str]:
    return [require_uid(item.uid, "RawFile.uid") for item in raw_files if item.uid is not None]


def _file_uids_from_ids(session: Session, *, subject_id: str, file_ids: list[int]) -> list[str]:
    files = list_raw_files_by_ids(session, subject_id, file_ids)
    by_id = {
        require_id(item.id, "RawFile.id"): require_uid(item.uid, "RawFile.uid")
        for item in files
        if item.id is not None and item.uid is not None
    }
    return [by_id[file_id] for file_id in file_ids if file_id in by_id]


def _turn_response_from_snapshot(turn: Mapping[str, Any]) -> BuildPlannerTurnResponse:
    return BuildPlannerTurnResponse(
        id=turn.get("id"),
        role=str(turn.get("role") or ""),
        content=str(turn.get("content") or ""),
        created_at=turn["created_at"],
    )


def _planner_meta(session_item: ChatSession) -> dict[str, Any]:
    return dict(session_item.meta_json or {})


def _planner_status(session_item: ChatSession) -> str:
    return str(_planner_meta(session_item).get("planner_status") or "draft")


def _planner_plan(session_item: ChatSession) -> dict[str, Any]:
    return dict(_planner_meta(session_item).get("latest_plan") or {})


def _planner_selected_file_ids(session_item: ChatSession) -> list[int]:
    values = _planner_meta(session_item).get("selected_file_ids") or []
    result: list[int] = []
    for value in values:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _planner_session_meta(
    *,
    session_id: str,
    status: str,
    user_prompt: str,
    digest_mode: str,
    selected_file_ids: list[int],
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
        "latest_plan": dict(latest_plan or {}),
        "latest_summary": latest_summary,
        "confirmed_plan_id": confirmed_plan_id,
    }


def _needs_auto_subject_name(value: str | None) -> bool:
    return str(value or "").strip().casefold() in _AUTO_TITLE_PLACEHOLDERS


def _clean_subject_metadata_text(value: str | None, *, max_chars: int = 800) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()


def _build_subject_description_from_plan(
    plan_payload: Mapping[str, Any],
    *,
    material_context: Any,
) -> str:
    profile = getattr(material_context, "learning_domain_profile", None)
    profile_description = _clean_subject_metadata_text(
        getattr(profile, "subject_description", "") if profile is not None else "",
        max_chars=360,
    )
    discipline = _clean_subject_metadata_text(
        getattr(profile, "discipline", "") if profile is not None else "",
        max_chars=80,
    )
    sub_discipline = _clean_subject_metadata_text(
        getattr(profile, "sub_discipline", "") if profile is not None else "",
        max_chars=80,
    )
    topics = (
        [
            _clean_subject_metadata_text(str(item), max_chars=40)
            for item in list(getattr(profile, "key_topics", []) or [])[:6]
            if str(item or "").strip()
        ]
        if profile is not None
        else []
    )
    summary = _clean_subject_metadata_text(str(plan_payload.get("plan_summary") or ""), max_chars=420)

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
    if summary and summary not in parts:
        parts.append(summary)
    return _clean_subject_metadata_text(" ".join(parts), max_chars=800)


def _build_subject_user_intent_from_state(state: Mapping[str, Any]) -> str:
    raw_intent = state.get("plan_intent") or {}
    if isinstance(raw_intent, Mapping):
        intent = _clean_subject_metadata_text(str(raw_intent.get("plan_intent") or ""), max_chars=420)
        if intent:
            return intent
    return _clean_subject_metadata_text(str(state.get("user_prompt") or ""), max_chars=420)


def _maybe_update_subject_from_planner(
    session: Session,
    *,
    subject_id: str,
    user_id: str,
    generated_name: str,
    generated_icon_key: str | None = None,
    description: str = "",
    user_intent: str = "",
) -> None:
    title = " ".join(str(generated_name or "").strip().split())
    should_apply_title = bool(title) and title.casefold() not in _AUTO_TITLE_PLACEHOLDERS
    description = _clean_subject_metadata_text(description, max_chars=800)
    user_intent = _clean_subject_metadata_text(user_intent, max_chars=420)
    subject_row = session.exec(
        select(Subject).where(Subject.id == subject_id, Subject.user_id == user_id)
    ).first()
    if subject_row is None:
        return

    updated = False
    if should_apply_title and _needs_auto_subject_name(subject_row.name):
        subject_row.name = title
        icon_key = normalize_subject_icon_key(generated_icon_key)
        if icon_key:
            set_subject_icon_key(subject_row, icon_key)
        updated = True
    if description and subject_row.description != description:
        subject_row.description = description
        updated = True
    if user_intent and subject_row.user_intent != user_intent:
        subject_row.user_intent = user_intent
        updated = True
    if not updated:
        return

    subject_row.updated_at = utcnow()
    session.add(subject_row)
    session.commit()
    logger.info(
        "planner_subject_metadata_updated",
        subject_id=subject_id,
        generated_name=title or None,
        description_chars=len(description),
        user_intent_chars=len(user_intent),
    )


def _apply_generated_subject_name(plan_payload: dict[str, Any], generated_name: str) -> str:
    title = " ".join(str(generated_name or "").strip().split())
    if not title or title.casefold() in _AUTO_TITLE_PLACEHOLDERS:
        return ""
    plan_payload["subject"] = title
    return title


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
    subject_id: str,
    session_id: str,
    user_id: str,
) -> ChatSession | None:
    item = get_chat_session(session, subject_id=subject_id, session_id=session_id, user_id=user_id)
    if item is None or item.source != PLANNER_CHAT_SOURCE:
        return None
    return item


def _get_latest_planner_session(session: Session, *, subject_id: str, user_id: str) -> ChatSession | None:
    stmt = (
        select(ChatSession)
        .where(
            ChatSession.subject_id == subject_id,
            ChatSession.user_id == user_id,
            ChatSession.source == PLANNER_CHAT_SOURCE,
        )
        .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
        .limit(1)
    )
    return session.exec(stmt).first()


def _list_planner_turns(session: Session, *, session_id: str, subject_id: str, user_id: str) -> list[ChatMessage]:
    stmt = (
        select(ChatMessage)
        .where(
            ChatMessage.session_id == session_id,
            ChatMessage.subject_id == subject_id,
            ChatMessage.user_id == user_id,
            ChatMessage.source == PLANNER_CHAT_SOURCE,
        )
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
    )
    return list(session.exec(stmt).all())


def _plan_response(
    *,
    subject_id: str,
    selected_file_uids: list[str],
    session_id: str,
    confirmed_plan_id: str | None,
    status: str,
    plan: dict[str, Any],
) -> BuildPlannerPlanResponse:
    return BuildPlannerPlanResponse(
        subject_id=subject_id,
        selected_file_uids=selected_file_uids,
        user_prompt=str(plan.get("user_prompt") or ""),
        digest_mode=str(plan.get("digest_mode") or "systematic"),
        chapter_plan=list(plan.get("chapter_plan") or []),
        build_constraints=dict(plan.get("build_constraints") or {}),
        plan_summary=str(plan.get("plan_summary") or ""),
        status=status,
        planner_session_id=session_id,
        confirmed_plan_id=confirmed_plan_id,
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
    subject_id = str(record.get("subject_id") or final_state.get("subject_id") or "")
    session_id = str(record.get("id") or final_state.get("planner_session_id") or "")
    status = str(record.get("status") or "draft")
    logger.info(
        "planner_response_from_state",
        planner_session_id=session_id,
        has_state_plan=bool(final_state.get("plan")),
        has_record_latest_plan=bool(record.get("latest_plan_json")),
        state_error=final_state.get("error"),
        plan_chapter_count=len(list(plan.get("chapter_plan") or [])),
    )
    return BuildPlannerSessionResponse(
        session_id=session_id,
        subject_id=subject_id,
        title=str(record.get("title") or ""),
        status=status,
        revision=len(turns),
        latest_plan=_plan_response(
            subject_id=subject_id,
            selected_file_uids=list(final_state.get("selected_file_uids") or []),
            session_id=session_id,
            confirmed_plan_id=record.get("confirmed_plan_id"),
            status=status,
            plan=plan,
        ),
        turns=[_turn_response_from_snapshot(turn) for turn in turns],
        runtime_stats=_runtime_stats_response(final_state),
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def _planner_session_response(
    record: ChatSession,
    *,
    subject_id: str,
    selected_file_uids: list[str],
    plan: dict[str, Any],
    turns: list[ChatMessage],
) -> BuildPlannerSessionResponse:
    meta = _planner_meta(record)
    return BuildPlannerSessionResponse(
        session_id=record.id,
        subject_id=subject_id,
        title=record.title,
        status=_planner_status(record),
        revision=len(turns),
        latest_plan=_plan_response(
            subject_id=subject_id,
            selected_file_uids=selected_file_uids,
            session_id=record.id,
            confirmed_plan_id=meta.get("confirmed_plan_id"),
            status=_planner_status(record),
            plan=plan,
        ),
        turns=[_turn_response_from_snapshot(_turn_snapshot(turn)) for turn in turns],
        runtime_stats=None,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _workflow_files_or_raise(
    *,
    subject_id: str,
    planner_files: list[RawFile],
) -> list[RawFile]:
    workflow_files = _select_planner_workflow_files(planner_files)
    if planner_files and not workflow_files:
        raise PlannerMaterialsNotReadyError(subject_id)
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
        subject_id=record.subject_id,
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
            "plan_summary": str((plan or {}).get("plan_summary") or ""),
        },
    )
    touch_chat_session(
        session,
        subject_id=record.subject_id,
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
        "subject_id": record.subject_id,
        "user_id": record.user_id,
        "title": record.title,
        "status": _planner_status(record),
        "user_prompt": str(meta.get("user_prompt") or ""),
        "digest_mode": str(meta.get("digest_mode") or ""),
        "selected_file_ids_json": _planner_selected_file_ids(record),
        "latest_plan_json": _planner_plan(record),
        "latest_summary": str(meta.get("latest_summary") or ""),
        "confirmed_plan_id": meta.get("confirmed_plan_id"),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _render_final_plan_markdown(plan_payload: dict[str, Any]) -> str:
    summary = str(plan_payload.get("plan_summary") or "").strip()
    plan_steps = [str(item).strip() for item in list(plan_payload.get("plan_steps") or []) if str(item).strip()]
    chapters = [
        item
        for item in list(plan_payload.get("chapter_plan") or [])
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    ]
    lines = [
        "# 计划大纲",
        "",
        f"> 模式：{str(plan_payload.get('digest_mode') or 'systematic')}",
        f"> 一句话摘要：{summary or '已生成一份可确认的构建方案。'}",
    ]
    if plan_steps:
        lines.extend(["", "## 计划步骤"])
        lines.extend(f"{index}. {item}" for index, item in enumerate(plan_steps, start=1))
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
        "latest_plan_summary": str(plan.get("plan_summary") or meta.get("latest_summary") or ""),
        "planner_outline_markdown": str(latest_outline or "").strip(),
        "docgen_history_brief": _build_docgen_history_brief(turns),
    }


def _normalize_persisted_plan(
    plan: dict[str, Any] | None,
    *,
    subject_id: str,
    user_prompt: str,
    digest_mode: str,
    material_context: Any | None = None,
    latest_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return normalize_planner_payload(
        plan or {},
        subject_id=subject_id,
        user_prompt=user_prompt,
        requested_digest_mode=digest_mode,
        shared_inputs=material_context,
        latest_plan=latest_plan,
    )


def _operation(state: Mapping[str, Any]) -> str:
    return str(state.get("planner_operation") or "generate_only").strip().lower() or "generate_only"


def prepare_planner_run(state: Mapping[str, Any]) -> dict[str, Any]:
    """Prepare persisted planner run data before material loading.

    Called by the normal `load_planner_materials` node. This keeps session DB
    IO inside the real workflow path without adding a separate "session node".
    """

    operation = _operation(state)
    logger.info(
        "planner_prepare_run_started",
        operation=operation,
        subject_id=state.get("subject_id"),
        planner_session_id=state.get("planner_session_id"),
        requested_file_uid_count=len(state.get("requested_file_uids") or []),
    )
    if operation == "generate_only":
        logger.info("planner_prepare_run_skipped_for_generate_only")
        return {}

    subject_id = str(state["subject_id"])
    user_id = str(state.get("user_id") or "local")

    if operation == "create":
        # 第一轮规划：创建 DB session、绑定文件选择，只返回后续 graph 需要的字段。
        planner_defaults = get_teaching_runtime_config().planner
        user_prompt = str(state.get("user_prompt") or "").strip()
        digest_mode = (
            state.get("digest_mode") or planner_defaults.default_digest_mode
        ).strip() or planner_defaults.default_digest_mode

        with managed_session() as session:
            subject_row = session.query(Subject).filter(Subject.id == subject_id).first()
            latest = _get_latest_planner_session(session, subject_id=subject_id, user_id=user_id)
            if latest is not None and _planner_status(latest) == "planning":
                raise BuildPlannerSessionBusyError(latest.id)
            planner_files = _select_planner_files(
                session,
                subject_id=subject_id,
                file_uids=list(state.get("requested_file_uids") or []),
            )
            workflow_files = _workflow_files_or_raise(
                subject_id=subject_id,
                planner_files=planner_files,
            )
            selected_file_ids = _file_ids(planner_files)
            workflow_file_ids = _file_ids(workflow_files)
            selected_file_uids = _file_uids(planner_files)
            session_title = str(
                state.get("session_title")
                or user_prompt
                or getattr(subject_row, "name", "")
                or "学习规划"
            )
            record = create_chat_session(
                session,
                subject_id=subject_id,
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
                subject_id=subject_id,
                planner_session_id=record.id,
                selected_file_count=len(selected_file_ids),
                workflow_file_count=len(workflow_file_ids),
                selected_file_uids=selected_file_uids,
            )
            return {
                "file_ids": workflow_file_ids,
                "selected_file_ids": selected_file_ids,
                "selected_file_uids": selected_file_uids,
                "user_prompt": user_prompt,
                "digest_mode": digest_mode,
                "message_history": [user_prompt],
                "planner_record": _record_snapshot(record),
                "planner_turns": [_turn_snapshot(user_turn)],
            }

    if operation == "append":
        # 修订规划：读取已有 session，追加用户反馈，并补齐 latest_plan/message_history。
        feedback = str(state.get("feedback_message") or "").strip()
        with managed_session() as session:
            record = _get_planner_session(
                session,
                subject_id=subject_id,
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
                subject_id=subject_id,
                planner_session_id=record.id,
                has_latest_plan=bool(meta.get("latest_plan")),
                selected_file_count=len(_planner_selected_file_ids(record)),
            )

            record = _update_planner_session_meta(
                session,
                record,
                planner_status="planning",
                confirmed_plan_id=None,
                confirmed_plan=None,
            )
            _create_planner_message(
                session,
                record=record,
                role="user",
                content=feedback,
            )
            turns = _list_planner_turns(session, session_id=record.id, subject_id=subject_id, user_id=user_id)
            selected_file_ids = _planner_selected_file_ids(record)
            raw_files = list_raw_files_by_ids(session, subject_id, selected_file_ids)
            workflow_files = _select_planner_workflow_files(raw_files)
            workflow_file_ids = [require_id(item.id, "RawFile.id") for item in workflow_files]
            if selected_file_ids and not workflow_file_ids:
                raise PlannerMaterialsNotReadyError(subject_id)
            selected_file_uids = [
                require_uid(item.uid, "RawFile.uid")
                for item in raw_files
                if item.id is not None and item.uid is not None
            ]
            return {
                "file_ids": workflow_file_ids,
                "selected_file_ids": selected_file_ids,
                "selected_file_uids": selected_file_uids,
                "user_prompt": str(meta.get("user_prompt") or ""),
                "digest_mode": str(meta.get("digest_mode") or ""),
                "message_history": [turn.content for turn in turns if turn.content.strip()],
                "latest_plan": _planner_plan(record),
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
    subject_id = str(state["subject_id"])
    user_id = str(state.get("user_id") or "local")
    with managed_session() as session:
        record = _get_planner_session(
            session,
            subject_id=subject_id,
            session_id=str(state["planner_session_id"]),
            user_id=user_id,
        )
        if record is None:
            raise BuildPlannerSessionNotFoundError(str(state["planner_session_id"]))
        meta = _planner_meta(record)

        logger.info(
            "planner_save_started",
            subject_id=subject_id,
            planner_session_id=record.id,
            input_chapter_count=len(list((plan or {}).get("chapter_plan") or [])),
            has_previous_plan=bool(meta.get("latest_plan")),
        )
        persisted_plan = _normalize_persisted_plan(
            plan,
            subject_id=subject_id,
            user_prompt=str(meta.get("user_prompt") or ""),
            digest_mode=str(meta.get("digest_mode") or ""),
            material_context=material_context,
            latest_plan=_planner_plan(record),
        )
        generated_title = _apply_generated_subject_name(
            persisted_plan,
            str(state.get("generated_subject_name") or ""),
        )
        subject_description = _build_subject_description_from_plan(
            persisted_plan,
            material_context=material_context,
        )
        subject_user_intent = _build_subject_user_intent_from_state(state)
        _maybe_update_subject_from_planner(
            session,
            subject_id=subject_id,
            user_id=user_id,
            generated_name=generated_title,
            generated_icon_key=str(state.get("generated_subject_icon_key") or ""),
            description=subject_description,
            user_intent=subject_user_intent,
        )
        record = _update_planner_session_meta(
            session,
            record,
            latest_plan=persisted_plan,
            latest_summary=str(persisted_plan.get("plan_summary") or state.get("plan_summary") or ""),
            digest_mode=str(persisted_plan.get("digest_mode") or meta.get("digest_mode") or ""),
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
        turns = _list_planner_turns(session, session_id=record.id, subject_id=subject_id, user_id=user_id)
        selected_file_ids = _planner_selected_file_ids(record)
        logger.info(
            "planner_save_finished",
            subject_id=subject_id,
            planner_session_id=record.id,
            persisted_chapter_count=len(list(persisted_plan.get("chapter_plan") or [])),
            turn_count=len(turns),
        )
        return {
            "plan": persisted_plan,
            "plan_summary": str(persisted_plan.get("plan_summary") or ""),
            "digest_mode": str(persisted_plan.get("digest_mode") or state.get("digest_mode") or ""),
            "selected_file_ids": selected_file_ids,
            "selected_file_uids": _file_uids_from_ids(
                session,
                subject_id=subject_id,
                file_ids=selected_file_ids,
            ),
            "planner_record": _record_snapshot(record),
            "planner_turns": [_turn_snapshot(turn) for turn in turns],
        }


def _normalized_plan_payload(
    plan: dict[str, Any],
    *,
    planner_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    build_constraints = dict(plan.get("build_constraints") or {})
    chapter_plan = _ensure_min_chapter_payload(
        list(plan.get("chapter_plan") or []),
        min_chapters=int(build_constraints.get("min_chapters", 0) or 0),
        digest_mode=str(plan.get("digest_mode") or ""),
        user_prompt=str(plan.get("user_prompt") or ""),
    )
    payload = {
        "subject": str(plan.get("subject") or ""),
        "user_prompt": str(plan.get("user_prompt") or ""),
        "digest_mode": str(plan.get("digest_mode") or ""),
        "chapter_plan": chapter_plan,
        "build_constraints": build_constraints,
        "plan_summary": str(plan.get("plan_summary") or ""),
        "plan_steps": [str(item).strip() for item in list(plan.get("plan_steps") or []) if str(item).strip()],
    }
    context_payload = dict(planner_context or plan.get("planner_context") or {})
    if context_payload:
        payload["planner_context"] = context_payload
        payload["docgen_history_brief"] = str(context_payload.get("docgen_history_brief") or "")
    return payload


def _ensure_min_chapter_payload(
    chapters: list[Any],
    *,
    min_chapters: int,
    digest_mode: str,
    user_prompt: str,
) -> list[dict[str, Any]]:
    normalized = [dict(item) for item in chapters if isinstance(item, dict)]
    if min_chapters <= 0 or len(normalized) >= min_chapters:
        return normalized
    existing_titles = {
        str(item.get("title") or "").strip().casefold()
        for item in normalized
        if str(item.get("title") or "").strip()
    }
    supplements = ["核心概念总览", "关键结构与流程", "典型例题与应用", "易错点与复盘", "综合练习"]
    mode = str(digest_mode or "").strip().lower()
    while len(normalized) < min_chapters:
        index = len(normalized) + 1
        title = supplements[(index - 1) % len(supplements)]
        if title.casefold() in existing_titles:
            title = f"{title} {index}"
        existing_titles.add(title.casefold())
        if mode == "sprint":
            required = [f"{title} 的高频考点", f"{title} 的典型题型", f"{title} 的易错点"]
        else:
            required = [f"{title} 的核心概念", f"{title} 的关键结构", f"{title} 的例子与迁移"]
        if user_prompt:
            required.append(user_prompt)
        normalized.append(
            {
                "chapter_index": index,
                "title": title,
                "objective": "；".join(required[:3]),
                "required_elements": required[:6],
                "writing_instructions": "按用户确认的课程模式补齐本章讲解，保持和前文章节风格一致。",
            }
        )
    return normalized


def mark_planner_session_failed(*, subject_id: str, user_id: str, session_id: str) -> None:
    with managed_session() as session:
        record = _get_planner_session(session, subject_id=subject_id, session_id=session_id, user_id=user_id)
        if record is None:
            return
        _update_planner_session_meta(session, record, planner_status="failed")


def mark_planner_session_cancelled(*, subject_id: str, user_id: str, session_id: str) -> None:
    with managed_session() as session:
        record = _get_planner_session(session, subject_id=subject_id, session_id=session_id, user_id=user_id)
        if record is None:
            return
        _update_planner_session_meta(session, record, planner_status="cancelled")


def mark_planner_session_draft(*, subject_id: str, user_id: str, session_id: str) -> None:
    with managed_session() as session:
        record = _get_planner_session(session, subject_id=subject_id, session_id=session_id, user_id=user_id)
        if record is None:
            return
        _update_planner_session_meta(session, record, planner_status="draft")


def confirm_planner_session(
    session: Session,
    *,
    subject: Subject,
    user_id: str,
    session_id: str,
) -> BuildPlannerConfirmResponse:
    """确认当前 Planner 草稿，并冻结成 DocGen 可执行的 confirmed plan。"""

    record = _get_planner_session(session, subject_id=subject.id, session_id=session_id, user_id=user_id)
    if record is None:
        raise BuildPlannerSessionNotFoundError(session_id)
    meta = _planner_meta(record)
    latest_plan = _planner_plan(record)
    if not latest_plan:
        raise BuildPlannerEmptyPlanError(session_id)

    turns = _list_planner_turns(session, session_id=record.id, subject_id=subject.id, user_id=user_id)
    planner_context = _build_planner_context_payload(
        record,
        turns=turns,
        plan=latest_plan,
    )
    plan_payload = _normalized_plan_payload(
        latest_plan,
        planner_context=planner_context,
    )
    current_confirmed = None
    if meta.get("confirmed_plan_id"):
        current_confirmed = get_confirmed_plan(
            session,
            subject_id=subject.id,
            plan_id=str(meta.get("confirmed_plan_id")),
            user_id=user_id,
        )
    if (
        current_confirmed is not None
        and _normalized_plan_payload(dict(current_confirmed.plan_json or {})) == plan_payload
    ):
        confirmed = current_confirmed
    else:
        confirmed = create_confirmed_plan(
            session,
            ConfirmedBuildPlan(
                id=uuid.uuid4().hex,
                subject_id=subject.id,
                planner_session_id=session_id,
                user_id=user_id,
                status="confirmed",
                user_prompt=str(meta.get("user_prompt") or ""),
                digest_mode=str(plan_payload.get("digest_mode") or meta.get("digest_mode") or ""),
                selected_file_ids_json=_planner_selected_file_ids(record),
                chapter_plan_json=list(plan_payload.get("chapter_plan") or []),
                build_constraints_json=dict(plan_payload.get("build_constraints") or {}),
                plan_summary=str(plan_payload.get("plan_summary") or meta.get("latest_summary") or ""),
                plan_json=plan_payload,
            ),
        )

    record = _update_planner_session_meta(
        session,
        record,
        latest_plan=plan_payload,
        latest_summary=str(plan_payload.get("plan_summary") or ""),
        confirmed_plan_id=confirmed.id,
        planner_status="confirmed",
    )
    selected_file_ids = _planner_selected_file_ids(record)
    file_uids = _file_uids_from_ids(session, subject_id=subject.id, file_ids=selected_file_ids)
    return BuildPlannerConfirmResponse(
        planner_session_id=record.id,
        confirmed_plan_id=confirmed.id,
        subject_id=subject.id,
        status=_planner_status(record),
        digest_mode=confirmed.digest_mode,
        selected_file_uids=file_uids,
        selected_file_ids=list(confirmed.selected_file_ids_json),
        user_prompt=confirmed.user_prompt,
        plan_summary=confirmed.plan_summary,
        chapter_plan=list(plan_payload.get("chapter_plan") or []),
        build_constraints=dict(plan_payload.get("build_constraints") or {}),
        plan_json=plan_payload,
        status_history=[confirmed.status, _planner_status(record)],
        created_at=confirmed.created_at,
        updated_at=confirmed.updated_at,
    )


def get_latest_planner_session(
    session: Session,
    *,
    subject: Subject,
    user_id: str,
) -> BuildPlannerSessionResponse | None:
    record = _get_latest_planner_session(session, subject_id=subject.id, user_id=user_id)
    if record is None:
        logger.info("planner_latest_none", subject_id=subject.id, user_id=user_id)
        return None
    turns = _list_planner_turns(session, session_id=record.id, subject_id=subject.id, user_id=user_id)
    plan_payload = _planner_plan(record)
    logger.info(
        "planner_latest_found",
        subject_id=subject.id,
        user_id=user_id,
        planner_session_id=record.id,
        turn_count=len(turns),
        has_latest_plan=bool(plan_payload),
        chapter_count=len(list(plan_payload.get("chapter_plan") or [])),
    )
    return _planner_session_response(
        record,
        subject_id=subject.id,
        selected_file_uids=_file_uids_from_ids(
            session,
            subject_id=subject.id,
            file_ids=_planner_selected_file_ids(record),
        ),
        plan=plan_payload,
        turns=turns,
    )


def get_planner_adjust_click_context(
    session: Session,
    *,
    subject: Subject,
    user_id: str,
    session_id: str,
) -> dict[str, Any]:
    """Return sparse session context for tracing the UI adjust entrypoint."""

    record = _get_planner_session(session, subject_id=subject.id, session_id=session_id, user_id=user_id)
    if record is None:
        raise BuildPlannerSessionNotFoundError(session_id)

    meta = _planner_meta(record)
    turns = _list_planner_turns(session, session_id=record.id, subject_id=subject.id, user_id=user_id)
    latest_plan = _planner_plan(record)
    selected_file_ids = _planner_selected_file_ids(record)
    context = {
        "subject_id": subject.id,
        "user_id": user_id,
        "planner_session_id": record.id,
        "status": _planner_status(record),
        "digest_mode": str(meta.get("digest_mode") or ""),
        "turn_count": len(turns),
        "selected_file_count": len(selected_file_ids),
        "has_latest_plan": bool(latest_plan),
        "latest_plan_chapter_count": len(list(latest_plan.get("chapter_plan") or [])),
        "confirmed_plan_id": meta.get("confirmed_plan_id"),
    }
    logger.info(
        "planner_adjust_click_context_loaded",
        subject_id=subject.id,
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
    subject_id: str,
    user_id: str,
    plan_id: str,
) -> ConfirmedBuildPlan:
    plan = get_confirmed_plan(session, subject_id=subject_id, plan_id=plan_id, user_id=user_id)
    if plan is None:
        raise ConfirmedBuildPlanNotFoundError(plan_id)
    return plan


def mark_confirmed_plan_status(
    session: Session,
    *,
    subject_id: str,
    user_id: str,
    plan_id: str,
    status: str,
) -> None:
    plan = get_confirmed_plan(session, subject_id=subject_id, plan_id=plan_id, user_id=user_id)
    if plan is None:
        return
    plan.status = status
    plan.updated_at = utcnow()
    update_confirmed_plan(session, plan)
    if plan.planner_session_id:
        planner_session = _get_planner_session(
            session,
            subject_id=subject_id,
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
