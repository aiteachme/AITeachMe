"""Tiny persistence API for the planner workflow.

只有 ``__all__`` 里的函数给外部用。Planner 节点只调用一个很小的 store
函数，避免业务节点里直接铺满 SQL/repo 细节。
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

import structlog
from sqlmodel import Session

from app.models import IngestStatus, TaskStatus
from app.models.build_planner import BuildPlannerSession, BuildPlannerTurn, ConfirmedBuildPlan
from app.models.raw_file import RawFile
from app.models.subject import Subject
from app.repositories.build_planner_repo import (
    create_confirmed_plan,
    create_planner_session,
    create_planner_turn,
    get_confirmed_plan,
    get_latest_planner_session as repo_get_latest_planner_session,
    get_planner_session,
    list_planner_turns,
    update_confirmed_plan,
    update_planner_session,
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
from app.workflows.digest.common.runtime_config import get_teaching_runtime_config
from app.workflows.digest.planner.lib.plans import normalize_planner_payload
from app.workflows.digest.planner.lib.steps import STEP_TIMING_FIELDS

logger = structlog.get_logger(__name__)
PLANNER_CHAT_SOURCE = "build_planner"


def _markdown_ready(raw_file: RawFile) -> bool:
    return (
        raw_file.status == TaskStatus.COMPLETED.value
        and raw_file.ingest_status
        in {
            IngestStatus.FAST_PARSED.value,
            IngestStatus.ENHANCING.value,
            IngestStatus.READY_FOR_DIGEST.value,
            IngestStatus.ENHANCE_FAILED.value,
        }
        and bool((raw_file.parsed_markdown or "").strip())
    )


def _select_planner_files(
    session: Session,
    *,
    subject: str,
    file_uids: list[str] | None,
) -> list[RawFile]:
    available_files = [item for item in list_all_raw_files_by_subject(session, subject) if item.id is not None]
    if not file_uids:
        return available_files
    requested = list_raw_files_by_uids(session, subject, file_uids)
    found_uids = {require_uid(item.uid, "RawFile.uid") for item in requested}
    missing = [uid for uid in file_uids if uid not in found_uids]
    if missing:
        raise RawFileNotFoundError(missing[0])
    available_ids = {require_id(item.id, "RawFile.id") for item in available_files}
    return [item for item in requested if item.id is not None and require_id(item.id, "RawFile.id") in available_ids]


def _select_planner_workflow_files(raw_files: list[RawFile]) -> list[RawFile]:
    ready = [item for item in raw_files if _markdown_ready(item)]
    return ready or raw_files


def _file_ids(raw_files: list[RawFile]) -> list[int]:
    return [require_id(item.id, "RawFile.id") for item in raw_files if item.id is not None]


def _file_uids(raw_files: list[RawFile]) -> list[str]:
    return [require_uid(item.uid, "RawFile.uid") for item in raw_files if item.uid is not None]


def _file_uids_from_ids(session: Session, *, subject: str, file_ids: list[int]) -> list[str]:
    files = list_raw_files_by_ids(session, subject, file_ids)
    by_id = {
        require_id(item.id, "RawFile.id"): require_uid(item.uid, "RawFile.uid")
        for item in files
        if item.id is not None and item.uid is not None
    }
    return [by_id[file_id] for file_id in file_ids if file_id in by_id]


def _turn_response(turn: BuildPlannerTurn) -> BuildPlannerTurnResponse:
    return BuildPlannerTurnResponse(
        id=turn.id,
        role=turn.role,
        content=turn.content,
        created_at=turn.created_at,
    )


def _turn_response_from_snapshot(turn: Mapping[str, Any]) -> BuildPlannerTurnResponse:
    return BuildPlannerTurnResponse(
        id=turn.get("id"),
        role=str(turn.get("role") or ""),
        content=str(turn.get("content") or ""),
        created_at=turn["created_at"],
    )


def _plan_response(
    *,
    subject: str,
    selected_file_uids: list[str],
    session_id: str,
    confirmed_plan_id: str | None,
    status: str,
    plan: dict[str, Any],
) -> BuildPlannerPlanResponse:
    return BuildPlannerPlanResponse(
        subject=subject,
        selected_file_uids=selected_file_uids,
        user_goal=str(plan.get("user_goal") or ""),
        digest_mode=str(plan.get("digest_mode") or "systematic"),
        chapter_plan=list(plan.get("chapter_plan") or []),
        research_queries=list(plan.get("research_queries") or []),
        media_plan=dict(plan.get("media_plan") or {}),
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
    subject = str(record.get("subject") or final_state.get("subject") or "")
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
        subject=subject,
        title=str(record.get("title") or ""),
        status=status,
        revision=len(turns),
        latest_plan=_plan_response(
            subject=subject,
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
    record: BuildPlannerSession,
    *,
    subject: str,
    selected_file_uids: list[str],
    plan: dict[str, Any],
    turns: list[BuildPlannerTurn],
) -> BuildPlannerSessionResponse:
    return BuildPlannerSessionResponse(
        session_id=record.id,
        subject=subject,
        title=record.title,
        status=record.status,
        revision=len(turns),
        latest_plan=_plan_response(
            subject=subject,
            selected_file_uids=selected_file_uids,
            session_id=record.id,
            confirmed_plan_id=record.confirmed_plan_id,
            status=record.status,
            plan=plan,
        ),
        turns=[_turn_response(turn) for turn in turns],
        runtime_stats=None,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _workflow_files_or_raise(
    *,
    subject: str,
    planner_files: list[RawFile],
) -> list[RawFile]:
    workflow_files = _select_planner_workflow_files(planner_files)
    if planner_files and not workflow_files:
        raise PlannerMaterialsNotReadyError(subject)
    return workflow_files


def _turn_snapshot(turn: BuildPlannerTurn) -> dict[str, Any]:
    return {
        "id": turn.id,
        "role": turn.role,
        "content": turn.content,
        "created_at": turn.created_at,
        "plan_json": turn.plan_json,
    }


def _planner_chat_meta(record: BuildPlannerSession, *, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "source": PLANNER_CHAT_SOURCE,
        "planner_session_id": record.id,
        "planner_status": record.status,
        "confirmed_plan_id": record.confirmed_plan_id,
        "digest_mode": record.digest_mode,
        "selected_file_ids": list(record.selected_file_ids_json or []),
        "plan_summary": str((plan or record.latest_plan_json or {}).get("plan_summary") or record.latest_summary or ""),
    }


def _ensure_planner_chat_session(
    session: Session,
    record: BuildPlannerSession,
    *,
    plan: dict[str, Any] | None = None,
) -> None:
    meta = _planner_chat_meta(record, plan=plan)
    existing = get_chat_session(
        session,
        subject=record.subject,
        session_id=record.id,
        user_id=record.user_id,
    )
    if existing is None:
        create_chat_session(
            session,
            subject=record.subject,
            user_id=record.user_id,
            session_id=record.id,
            title=record.title,
            source=PLANNER_CHAT_SOURCE,
            meta_json=meta,
        )
        return

    existing.title = record.title
    existing.source = PLANNER_CHAT_SOURCE
    existing.meta_json = meta
    existing.updated_at = utcnow()
    session.add(existing)
    session.commit()
    session.refresh(existing)


def _planner_chat_turn_id(turn: BuildPlannerTurn) -> str:
    suffix = turn.id if turn.id is not None else uuid.uuid4().hex
    return f"planner:{turn.session_id}:{suffix}"


def _mirror_planner_turn_to_chat(
    session: Session,
    *,
    record: BuildPlannerSession,
    turn: BuildPlannerTurn,
    plan: dict[str, Any] | None = None,
) -> None:
    _ensure_planner_chat_session(session, record, plan=plan)
    create_chat_message(
        session,
        subject=record.subject,
        user_id=record.user_id,
        session_id=record.id,
        role=turn.role,
        content=turn.content,
        turn_id=_planner_chat_turn_id(turn),
        source=PLANNER_CHAT_SOURCE,
        anchor_id=record.id,
        meta_json={
            "source": PLANNER_CHAT_SOURCE,
            "message_kind": "planner_plan" if turn.role == "assistant" else "planner_user_request",
            "planner_session_id": record.id,
            "planner_turn_id": turn.id,
            "plan_json": plan if turn.role == "assistant" else None,
            "plan_summary": str((plan or {}).get("plan_summary") or ""),
        },
    )
    touch_chat_session(
        session,
        subject=record.subject,
        user_id=record.user_id,
        session_id=record.id,
        title=record.title,
        touched_at=turn.created_at,
    )


def _record_snapshot(record: BuildPlannerSession) -> dict[str, Any]:
    return {
        "id": record.id,
        "subject": record.subject,
        "user_id": record.user_id,
        "title": record.title,
        "status": record.status,
        "user_goal": record.user_goal,
        "digest_mode": record.digest_mode,
        "selected_file_ids_json": list(record.selected_file_ids_json or []),
        "latest_plan_json": dict(record.latest_plan_json or {}),
        "latest_summary": record.latest_summary,
        "confirmed_plan_id": record.confirmed_plan_id,
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
    lines.extend(
        [
            "",
            "## 章节安排",
            *[
                f"{index}. {str(chapter.get('title') or '').strip()}："
                f"{'；'.join(str(item).strip() for item in list(chapter.get('required_elements') or [])[:3] if str(item).strip())}"
                for index, chapter in enumerate(chapters, start=1)
            ],
        ]
    )
    return "\n".join(lines).strip()


def _compact_planner_text(value: Any, *, max_chars: int = 900) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _build_docgen_history_brief(turns: list[BuildPlannerTurn]) -> str:
    lines: list[str] = []
    for turn in turns[-10:]:
        role = "用户" if turn.role == "user" else "规划器"
        content = _compact_planner_text(
            turn.content,
            max_chars=520 if turn.role == "user" else 720,
        )
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _build_planner_context_payload(
    record: BuildPlannerSession,
    *,
    turns: list[BuildPlannerTurn],
    plan: dict[str, Any],
) -> dict[str, Any]:
    assistant_turns = [turn for turn in turns if turn.role == "assistant"]
    user_turns = [turn for turn in turns if turn.role == "user"]
    latest_outline = assistant_turns[-1].content if assistant_turns else _render_final_plan_markdown(plan)
    return {
        "planner_session_id": record.id,
        "planner_turn_count": len(turns),
        "user_revision_count": max(0, len(user_turns) - 1),
        "assistant_revision_count": len(assistant_turns),
        "latest_plan_summary": str(plan.get("plan_summary") or record.latest_summary or ""),
        "planner_outline_markdown": _compact_planner_text(latest_outline, max_chars=1800),
        "docgen_history_brief": _build_docgen_history_brief(turns),
    }


def _normalize_persisted_plan(
    plan: dict[str, Any] | None,
    *,
    subject: str,
    user_goal: str,
    digest_mode: str,
    material_context: Any | None = None,
    latest_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return normalize_planner_payload(
        plan or {},
        subject=subject,
        user_goal=user_goal,
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
        subject=state.get("subject"),
        planner_session_id=state.get("planner_session_id"),
        requested_file_uid_count=len(state.get("requested_file_uids") or []),
    )
    if operation == "generate_only":
        logger.info("planner_prepare_run_skipped_for_generate_only")
        return {}

    subject_slug = str(state["subject"])
    user_id = str(state.get("user_id") or "local")

    if operation == "create":
        # 第一轮规划：创建 DB session、绑定文件选择，只返回后续 graph 需要的字段。
        planner_defaults = get_teaching_runtime_config().planner
        user_goal = str(state.get("user_goal") or "").strip()
        digest_mode = (
            state.get("digest_mode") or planner_defaults.default_digest_mode
        ).strip() or planner_defaults.default_digest_mode

        with managed_session() as session:
            subject_row = session.query(Subject).filter(Subject.slug == subject_slug).first()
            latest = repo_get_latest_planner_session(session, subject=subject_slug, user_id=user_id)
            if latest is not None and latest.status == "planning":
                raise BuildPlannerSessionBusyError(latest.id)
            planner_files = _select_planner_files(
                session,
                subject=subject_slug,
                file_uids=list(state.get("requested_file_uids") or []),
            )
            workflow_files = _workflow_files_or_raise(
                subject=subject_slug,
                planner_files=planner_files,
            )
            selected_file_ids = _file_ids(planner_files)
            workflow_file_ids = _file_ids(workflow_files)
            selected_file_uids = _file_uids(planner_files)
            session_title = str(state.get("session_title") or user_goal or getattr(subject_row, "name", "") or subject_slug)
            record = create_planner_session(
                session,
                BuildPlannerSession(
                    id=str(state["planner_session_id"]),
                    subject=subject_slug,
                    user_id=user_id,
                    title=session_title,
                    status="planning",
                    user_goal=user_goal,
                    digest_mode=digest_mode,
                    selected_file_ids_json=selected_file_ids,
                ),
            )
            user_turn = create_planner_turn(
                session,
                BuildPlannerTurn(
                    subject=subject_slug,
                    user_id=user_id,
                    session_id=record.id,
                    role="user",
                    content=user_goal,
                ),
            )
            _mirror_planner_turn_to_chat(session, record=record, turn=user_turn)
            logger.info(
                "planner_prepare_run_created_session",
                subject=subject_slug,
                planner_session_id=record.id,
                selected_file_count=len(selected_file_ids),
                workflow_file_count=len(workflow_file_ids),
                selected_file_uids=selected_file_uids,
            )
            return {
                "file_ids": workflow_file_ids,
                "selected_file_ids": selected_file_ids,
                "selected_file_uids": selected_file_uids,
                "user_goal": user_goal,
                "digest_mode": digest_mode,
                "message_history": [user_goal],
                "planner_record": _record_snapshot(record),
                "planner_turns": [_turn_snapshot(user_turn)],
            }

    if operation == "append":
        # 修订规划：读取已有 session，追加用户反馈，并补齐 latest_plan/message_history。
        feedback = str(state.get("feedback_message") or "").strip()
        with managed_session() as session:
            record = get_planner_session(
                session,
                subject=subject_slug,
                session_id=str(state["planner_session_id"]),
                user_id=user_id,
            )
            if record is None:
                raise BuildPlannerSessionNotFoundError(str(state["planner_session_id"]))
            if record.status == "planning":
                raise BuildPlannerSessionBusyError(record.id)
            logger.info(
                "planner_prepare_run_loaded_session",
                subject=subject_slug,
                planner_session_id=record.id,
                has_latest_plan=bool(record.latest_plan_json),
                selected_file_count=len(record.selected_file_ids_json or []),
            )

            record.status = "planning"
            record.confirmed_plan_id = None
            record.updated_at = utcnow()
            update_planner_session(session, record)
            user_turn = create_planner_turn(
                session,
                BuildPlannerTurn(
                    subject=subject_slug,
                    user_id=user_id,
                    session_id=record.id,
                    role="user",
                    content=feedback,
                ),
            )
            _mirror_planner_turn_to_chat(session, record=record, turn=user_turn)
            turns = list_planner_turns(session, session_id=record.id)
            raw_files = list_raw_files_by_ids(session, subject_slug, list(record.selected_file_ids_json))
            workflow_files = _select_planner_workflow_files(raw_files)
            workflow_file_ids = [require_id(item.id, "RawFile.id") for item in workflow_files]
            if record.selected_file_ids_json and not workflow_file_ids:
                raise PlannerMaterialsNotReadyError(subject_slug)
            selected_file_uids = [
                require_uid(item.uid, "RawFile.uid")
                for item in raw_files
                if item.id is not None and item.uid is not None
            ]
            return {
                "file_ids": workflow_file_ids,
                "selected_file_ids": list(record.selected_file_ids_json),
                "selected_file_uids": selected_file_uids,
                "user_goal": record.user_goal,
                "digest_mode": record.digest_mode,
                "message_history": [turn.content for turn in turns if turn.content.strip()],
                "latest_plan": record.latest_plan_json,
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
    subject_slug = str(state["subject"])
    user_id = str(state.get("user_id") or "local")
    with managed_session() as session:
        record = get_planner_session(
            session,
            subject=subject_slug,
            session_id=str(state["planner_session_id"]),
            user_id=user_id,
        )
        if record is None:
            raise BuildPlannerSessionNotFoundError(str(state["planner_session_id"]))

        logger.info(
            "planner_save_started",
            subject=subject_slug,
            planner_session_id=record.id,
            input_chapter_count=len(list((plan or {}).get("chapter_plan") or [])),
            has_previous_plan=bool(record.latest_plan_json),
        )
        persisted_plan = _normalize_persisted_plan(
            plan,
            subject=subject_slug,
            user_goal=record.user_goal,
            digest_mode=record.digest_mode,
            material_context=material_context,
            latest_plan=record.latest_plan_json,
        )
        record.latest_plan_json = persisted_plan
        record.latest_summary = str(persisted_plan.get("plan_summary") or state.get("plan_summary") or "")
        record.digest_mode = str(persisted_plan.get("digest_mode") or record.digest_mode)
        record.status = "draft"
        record.confirmed_plan_id = None
        record.updated_at = utcnow()
        record = update_planner_session(session, record)
        assistant_turn = create_planner_turn(
            session,
            BuildPlannerTurn(
                subject=subject_slug,
                user_id=user_id,
                session_id=record.id,
                role="assistant",
                content=_render_final_plan_markdown(persisted_plan),
                plan_json=persisted_plan,
            ),
        )
        _mirror_planner_turn_to_chat(session, record=record, turn=assistant_turn, plan=persisted_plan)
        turns = list_planner_turns(session, session_id=record.id)
        logger.info(
            "planner_save_finished",
            subject=subject_slug,
            planner_session_id=record.id,
            persisted_chapter_count=len(list(persisted_plan.get("chapter_plan") or [])),
            turn_count=len(turns),
        )
        return {
            "plan": persisted_plan,
            "plan_summary": str(persisted_plan.get("plan_summary") or ""),
            "digest_mode": str(persisted_plan.get("digest_mode") or state.get("digest_mode") or ""),
            "selected_file_ids": list(record.selected_file_ids_json),
            "selected_file_uids": _file_uids_from_ids(
                session,
                subject=subject_slug,
                file_ids=list(record.selected_file_ids_json),
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
        user_goal=str(plan.get("user_goal") or ""),
    )
    payload = {
        "subject": str(plan.get("subject") or ""),
        "user_goal": str(plan.get("user_goal") or ""),
        "digest_mode": str(plan.get("digest_mode") or ""),
        "chapter_plan": chapter_plan,
        "research_queries": list(plan.get("research_queries") or []),
        "media_plan": dict(plan.get("media_plan") or {}),
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
    user_goal: str,
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
        if user_goal:
            required.append(user_goal)
        normalized.append(
            {
                "chapter_index": index,
                "title": title,
                "objective": "；".join(required[:3]),
                "required_elements": required[:6],
                "search_queries": [title, *required[:3]],
                "writing_instructions": "按用户确认的课程模式补齐本章讲解，保持和前文章节风格一致。",
                "media_hints": {"images": [], "mermaid": [f"{title} 的知识结构图"], "interactive": []},
            }
        )
    return normalized


def mark_planner_session_failed(*, subject: str, user_id: str, session_id: str) -> None:
    with managed_session() as session:
        record = get_planner_session(session, subject=subject, session_id=session_id, user_id=user_id)
        if record is None:
            return
        record.status = "failed"
        record.updated_at = utcnow()
        update_planner_session(session, record)


def mark_planner_session_draft(*, subject: str, user_id: str, session_id: str) -> None:
    with managed_session() as session:
        record = get_planner_session(session, subject=subject, session_id=session_id, user_id=user_id)
        if record is None:
            return
        record.status = "draft"
        record.updated_at = utcnow()
        update_planner_session(session, record)


def confirm_planner_session(
    session: Session,
    *,
    subject: Subject,
    user_id: str,
    session_id: str,
) -> BuildPlannerConfirmResponse:
    """确认当前 Planner 草稿，并冻结成 DocGen 可执行的 confirmed plan。"""

    record = get_planner_session(session, subject=subject.slug, session_id=session_id, user_id=user_id)
    if record is None:
        raise BuildPlannerSessionNotFoundError(session_id)
    if not record.latest_plan_json:
        raise BuildPlannerEmptyPlanError(session_id)

    turns = list_planner_turns(session, session_id=record.id)
    planner_context = _build_planner_context_payload(
        record,
        turns=turns,
        plan=dict(record.latest_plan_json),
    )
    plan_payload = _normalized_plan_payload(
        dict(record.latest_plan_json),
        planner_context=planner_context,
    )
    record.latest_plan_json = plan_payload
    current_confirmed = None
    if record.confirmed_plan_id:
        current_confirmed = get_confirmed_plan(
            session,
            subject=subject.slug,
            plan_id=record.confirmed_plan_id,
            user_id=user_id,
        )
    if current_confirmed is not None and _normalized_plan_payload(dict(current_confirmed.plan_json or {})) == plan_payload:
        confirmed = current_confirmed
    else:
        confirmed = create_confirmed_plan(
            session,
            ConfirmedBuildPlan(
                id=uuid.uuid4().hex,
                subject=subject.slug,
                planner_session_id=session_id,
                user_id=user_id,
                status="confirmed",
                user_goal=record.user_goal,
                digest_mode=str(plan_payload.get("digest_mode") or record.digest_mode),
                selected_file_ids_json=list(record.selected_file_ids_json),
                chapter_plan_json=list(plan_payload.get("chapter_plan") or []),
                research_queries_json=list(plan_payload.get("research_queries") or []),
                media_plan_json=dict(plan_payload.get("media_plan") or {}),
                build_constraints_json=dict(plan_payload.get("build_constraints") or {}),
                plan_summary=str(plan_payload.get("plan_summary") or record.latest_summary),
                plan_json=plan_payload,
            ),
        )

    record.confirmed_plan_id = confirmed.id
    record.status = "confirmed"
    record.updated_at = utcnow()
    record = update_planner_session(session, record)
    file_uids = _file_uids_from_ids(session, subject=subject.slug, file_ids=list(record.selected_file_ids_json))
    return BuildPlannerConfirmResponse(
        planner_session_id=record.id,
        confirmed_plan_id=confirmed.id,
        subject=subject.slug,
        status=record.status,
        digest_mode=confirmed.digest_mode,
        selected_file_uids=file_uids,
        selected_file_ids=list(confirmed.selected_file_ids_json),
        user_goal=confirmed.user_goal,
        plan_summary=confirmed.plan_summary,
        chapter_plan=list(plan_payload.get("chapter_plan") or []),
        research_queries=list(plan_payload.get("research_queries") or []),
        media_plan=dict(plan_payload.get("media_plan") or {}),
        build_constraints=dict(plan_payload.get("build_constraints") or {}),
        plan_json=plan_payload,
        status_history=[confirmed.status, record.status],
        created_at=confirmed.created_at,
        updated_at=confirmed.updated_at,
    )


def get_latest_planner_session(
    session: Session,
    *,
    subject: Subject,
    user_id: str,
) -> BuildPlannerSessionResponse | None:
    record = repo_get_latest_planner_session(session, subject=subject.slug, user_id=user_id)
    if record is None:
        logger.info("planner_latest_none", subject=subject.slug, user_id=user_id)
        return None
    turns = list_planner_turns(session, session_id=record.id)
    plan_payload = dict(record.latest_plan_json or {})
    logger.info(
        "planner_latest_found",
        subject=subject.slug,
        user_id=user_id,
        planner_session_id=record.id,
        turn_count=len(turns),
        has_latest_plan=bool(plan_payload),
        chapter_count=len(list(plan_payload.get("chapter_plan") or [])),
    )
    return _planner_session_response(
        record,
        subject=subject.slug,
        selected_file_uids=_file_uids_from_ids(session, subject=subject.slug, file_ids=list(record.selected_file_ids_json or [])),
        plan=plan_payload,
        turns=turns,
    )


def get_confirmed_plan_or_raise(
    session: Session,
    *,
    subject: str,
    user_id: str,
    plan_id: str,
) -> ConfirmedBuildPlan:
    plan = get_confirmed_plan(session, subject=subject, plan_id=plan_id, user_id=user_id)
    if plan is None:
        raise ConfirmedBuildPlanNotFoundError(plan_id)
    return plan


def mark_confirmed_plan_status(
    session: Session,
    *,
    subject: str,
    user_id: str,
    plan_id: str,
    status: str,
) -> None:
    plan = get_confirmed_plan(session, subject=subject, plan_id=plan_id, user_id=user_id)
    if plan is None:
        return
    plan.status = status
    plan.updated_at = utcnow()
    update_confirmed_plan(session, plan)
    if plan.planner_session_id:
        planner_session = get_planner_session(
            session,
            subject=subject,
            session_id=plan.planner_session_id,
            user_id=user_id,
        )
        if planner_session is not None and planner_session.confirmed_plan_id == plan.id:
            planner_session.status = status
            planner_session.updated_at = utcnow()
            update_planner_session(session, planner_session)


__all__ = [
    "confirm_planner_session",
    "get_confirmed_plan_or_raise",
    "get_latest_planner_session",
    "mark_confirmed_plan_status",
    "mark_planner_session_draft",
    "mark_planner_session_failed",
    "prepare_planner_run",
    "planner_session_response_from_state",
    "save_planner_result",
]
