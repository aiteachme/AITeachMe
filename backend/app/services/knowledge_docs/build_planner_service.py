"""Services for the persistent build planner flow."""

from __future__ import annotations

import uuid
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
    get_planner_session,
    list_planner_turns,
    update_confirmed_plan,
    update_planner_session,
)
from app.repositories.files_repo import (
    list_all_raw_files_by_subject,
    list_raw_files_by_ids,
    list_raw_files_by_uids,
)
from app.schemas.knowledge import (
    BuildPlannerConfirmResponse,
    BuildPlannerCreateRequest,
    BuildPlannerMessageRequest,
    BuildPlannerPlanResponse,
    BuildPlannerRuntimeStatsResponse,
    BuildPlannerSessionResponse,
    BuildPlannerStepStatsResponse,
    BuildPlannerTurnResponse,
)
from app.shared.infra.exceptions import (
    BuildPlannerEmptyPlanError,
    BuildPlannerSessionNotFoundError,
    ConfirmedBuildPlanNotFoundError,
    RawFileNotFoundError,
)
from app.teaching.runtime_config import get_teaching_runtime_config
from app.utils.presenters import require_id, require_uid
from app.utils.time import utcnow
from app.workflows.digest.planner.models import normalize_planner_payload
from app.workflows.digest.planner.runtime import run_build_planner_workflow

logger = structlog.get_logger(__name__)


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
        and bool(raw_file.parsed_markdown.strip())
    )


def _planner_file_available(raw_file: RawFile) -> bool:
    return raw_file.id is not None


def _select_planner_files(
    session: Session,
    *,
    subject: str,
    file_uids: list[str] | None,
) -> list[RawFile]:
    available_files = [item for item in list_all_raw_files_by_subject(session, subject) if _planner_file_available(item)]
    if not file_uids:
        return available_files
    requested = list_raw_files_by_uids(session, subject, file_uids)
    found_uids = {require_uid(item.uid, "RawFile.uid") for item in requested}
    missing = [uid for uid in file_uids if uid not in found_uids]
    if missing:
        raise RawFileNotFoundError(missing[0])
    available_ids = {require_id(item.id, "RawFile.id") for item in available_files}
    selected = [item for item in requested if item.id is not None and require_id(item.id, "RawFile.id") in available_ids]
    return selected


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
        tone=str(plan.get("tone") or "encouraging"),
        selected_skillpacks=list(plan.get("selected_skillpacks") or []),
        chapter_plan=list(plan.get("chapter_plan") or []),
        research_queries=list(plan.get("research_queries") or []),
        media_plan=dict(plan.get("media_plan") or {}),
        build_constraints=dict(plan.get("build_constraints") or {}),
        plan_summary=str(plan.get("plan_summary") or ""),
        status=status,
        planner_session_id=session_id,
        confirmed_plan_id=confirmed_plan_id,
    )


def _normalized_plan_payload(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject": str(plan.get("subject") or ""),
        "user_goal": str(plan.get("user_goal") or ""),
        "digest_mode": str(plan.get("digest_mode") or ""),
        "tone": str(plan.get("tone") or ""),
        "selected_skillpacks": list(plan.get("selected_skillpacks") or []),
        "chapter_plan": list(plan.get("chapter_plan") or []),
        "research_queries": list(plan.get("research_queries") or []),
        "media_plan": dict(plan.get("media_plan") or {}),
        "build_constraints": dict(plan.get("build_constraints") or {}),
        "plan_summary": str(plan.get("plan_summary") or ""),
    }


def _runtime_stats_response(final_state: dict[str, Any] | None) -> BuildPlannerRuntimeStatsResponse | None:
    if not isinstance(final_state, dict):
        return None

    steps: list[BuildPlannerStepStatsResponse] = []
    for item in list(final_state.get("runtime_steps") or []):
        if not isinstance(item, dict):
            continue
        steps.append(
            BuildPlannerStepStatsResponse(
                name=str(item.get("name") or ""),
                kind=str(item.get("kind") or "substep"),
                elapsed_ms=int(item.get("elapsed_ms", 0) or 0),
                status=str(item.get("status") or "ok"),
            )
        )

    return BuildPlannerRuntimeStatsResponse(
        elapsed_ms=int(final_state.get("workflow_elapsed_ms", 0) or 0),
        steps=steps,
        fallback_used=False,
        generation_mode=str(final_state.get("planner_generation_mode") or "").strip() or None,
    )


def _log_planner_runtime(
    *,
    subject: str,
    session_id: str,
    runtime_stats: BuildPlannerRuntimeStatsResponse | None,
) -> None:
    if runtime_stats is None:
        return
    logger.info(
        "planner_runtime_summary",
        subject=subject,
        planner_session_id=session_id,
        elapsed_ms=runtime_stats.elapsed_ms,
        steps=[step.model_dump(mode="json") for step in runtime_stats.steps],
        generation_mode=runtime_stats.generation_mode,
    )


def _normalize_persisted_plan(
    plan: dict[str, Any] | None,
    *,
    subject: str,
    user_goal: str,
    digest_mode: str,
    tone: str,
    selected_skillpacks: list[str] | None = None,
    shared_inputs: Any | None = None,
    latest_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return normalize_planner_payload(
        plan or {},
        subject=subject,
        user_goal=user_goal,
        requested_digest_mode=digest_mode,
        requested_tone=tone,
        selected_skillpacks=selected_skillpacks,
        shared_inputs=shared_inputs,
        latest_plan=latest_plan,
    )


async def create_build_planner_session_service(
    session: Session,
    *,
    subject: Subject,
    user_id: str,
    payload: BuildPlannerCreateRequest,
    progress_callback: object | None = None,
    token_callback: object | None = None,
) -> BuildPlannerSessionResponse:
    planner_defaults = get_teaching_runtime_config().planner
    planner_files = _select_planner_files(session, subject=subject.slug, file_uids=payload.file_uids)
    file_ids = [require_id(item.id, "RawFile.id") for item in planner_files]
    file_uids = [require_uid(item.uid, "RawFile.uid") for item in planner_files]
    session_id = uuid.uuid4().hex
    tone = (payload.tone or planner_defaults.default_tone).strip() or planner_defaults.default_tone
    digest_mode = (payload.digest_mode or planner_defaults.default_digest_mode).strip() or planner_defaults.default_digest_mode
    user_goal = payload.user_goal.strip()

    record = create_planner_session(
        session,
        BuildPlannerSession(
            id=session_id,
            subject=subject.slug,
            user_id=user_id,
            title=(payload.title or user_goal or subject.name)[:120],
            status="draft",
            user_goal=user_goal,
            digest_mode=digest_mode,
            tone=tone,
            selected_file_ids_json=file_ids,
        ),
    )
    user_turn = create_planner_turn(
        session,
        BuildPlannerTurn(
            subject=subject.slug,
            user_id=user_id,
            session_id=session_id,
            role="user",
            content=user_goal,
        ),
    )

    workflow_result = await run_build_planner_workflow(
        subject=subject.slug,
        file_ids=file_ids,
        user_goal=user_goal,
        planner_session_id=session_id,
        digest_mode=digest_mode,
        tone=tone,
        selected_skillpacks=list(payload.selected_skillpacks or []),
        message_history=[user_goal],
        progress_callback=progress_callback,
        token_callback=token_callback,
    )
    try:
        final_state = workflow_result.require_value()
    except Exception:
        record.status = "failed"
        record.updated_at = utcnow()
        update_planner_session(session, record)
        raise
    runtime_stats = _runtime_stats_response(final_state)
    plan = _normalize_persisted_plan(
        dict(final_state.get("plan") or {}),
        subject=subject.slug,
        user_goal=user_goal,
        digest_mode=digest_mode,
        tone=tone,
        selected_skillpacks=list(payload.selected_skillpacks or []),
        shared_inputs=final_state.get("shared_inputs"),
    )
    record.latest_plan_json = plan
    record.latest_summary = str(plan.get("plan_summary") or final_state.get("plan_summary") or "")
    record.digest_mode = str(plan.get("digest_mode") or digest_mode)
    record.tone = str(plan.get("tone") or tone)
    record.updated_at = utcnow()
    record = update_planner_session(session, record)

    assistant_turn = create_planner_turn(
        session,
        BuildPlannerTurn(
            subject=subject.slug,
            user_id=user_id,
            session_id=session_id,
            role="assistant",
            content=record.latest_summary,
            plan_json=plan,
        ),
    )
    response = BuildPlannerSessionResponse(
        session_id=record.id,
        title=record.title,
        status=record.status,
        plan=_plan_response(
            subject=subject.slug,
            selected_file_uids=file_uids,
            session_id=record.id,
            confirmed_plan_id=record.confirmed_plan_id,
            status=record.status,
            plan=plan,
        ),
        turns=[_turn_response(user_turn), _turn_response(assistant_turn)],
        runtime_stats=runtime_stats,
    )
    _log_planner_runtime(subject=subject.slug, session_id=record.id, runtime_stats=runtime_stats)
    return response


async def append_build_planner_message_service(
    session: Session,
    *,
    subject: Subject,
    user_id: str,
    session_id: str,
    payload: BuildPlannerMessageRequest,
    progress_callback: object | None = None,
    token_callback: object | None = None,
) -> BuildPlannerSessionResponse:
    record = get_planner_session(session, subject=subject.slug, session_id=session_id, user_id=user_id)
    if record is None:
        raise BuildPlannerSessionNotFoundError(session_id)

    feedback = payload.message.strip()
    user_turn = create_planner_turn(
        session,
        BuildPlannerTurn(
            subject=subject.slug,
            user_id=user_id,
            session_id=session_id,
            role="user",
            content=feedback,
        ),
    )
    turns = list_planner_turns(session, session_id=session_id)
    message_history = [turn.content for turn in turns if turn.content.strip()]
    selected_skillpacks = (
        list(payload.selected_skillpacks)
        if payload.selected_skillpacks is not None
        else list((record.latest_plan_json or {}).get("selected_skillpacks") or [])
    )
    workflow_result = await run_build_planner_workflow(
        subject=subject.slug,
        file_ids=list(record.selected_file_ids_json),
        user_goal=record.user_goal,
        planner_session_id=session_id,
        digest_mode=record.digest_mode,
        tone=record.tone,
        selected_skillpacks=selected_skillpacks,
        message_history=message_history,
        latest_plan=record.latest_plan_json,
        progress_callback=progress_callback,
        token_callback=token_callback,
    )
    try:
        final_state = workflow_result.require_value()
    except Exception:
        record.status = "failed"
        record.updated_at = utcnow()
        update_planner_session(session, record)
        raise
    runtime_stats = _runtime_stats_response(final_state)
    plan = _normalize_persisted_plan(
        dict(final_state.get("plan") or {}),
        subject=subject.slug,
        user_goal=record.user_goal,
        digest_mode=record.digest_mode,
        tone=record.tone,
        selected_skillpacks=selected_skillpacks,
        shared_inputs=final_state.get("shared_inputs"),
        latest_plan=record.latest_plan_json,
    )
    record.latest_plan_json = plan
    record.latest_summary = str(plan.get("plan_summary") or final_state.get("plan_summary") or "")
    record.digest_mode = str(plan.get("digest_mode") or record.digest_mode)
    record.tone = str(plan.get("tone") or record.tone)
    record.status = "draft"
    record.confirmed_plan_id = None
    record.updated_at = utcnow()
    record = update_planner_session(session, record)
    assistant_turn = create_planner_turn(
        session,
        BuildPlannerTurn(
            subject=subject.slug,
            user_id=user_id,
            session_id=session_id,
            role="assistant",
            content=record.latest_summary,
            plan_json=plan,
        ),
    )
    response_turns = [
        _turn_response(turn)
        for turn in list_planner_turns(session, session_id=session_id)
    ]
    file_uids = _file_uids_from_ids(session, subject=subject.slug, file_ids=list(record.selected_file_ids_json))
    response = BuildPlannerSessionResponse(
        session_id=record.id,
        title=record.title,
        status=record.status,
        plan=_plan_response(
            subject=subject.slug,
            selected_file_uids=file_uids,
            session_id=record.id,
            confirmed_plan_id=record.confirmed_plan_id,
            status=record.status,
            plan=plan,
        ),
        turns=response_turns,
        runtime_stats=runtime_stats,
    )
    _log_planner_runtime(subject=subject.slug, session_id=record.id, runtime_stats=runtime_stats)
    return response


def confirm_build_planner_session_service(
    session: Session,
    *,
    subject: Subject,
    user_id: str,
    session_id: str,
) -> BuildPlannerConfirmResponse:
    record = get_planner_session(session, subject=subject.slug, session_id=session_id, user_id=user_id)
    if record is None:
        raise BuildPlannerSessionNotFoundError(session_id)
    if not record.latest_plan_json:
        raise BuildPlannerEmptyPlanError(session_id)

    plan_payload = _normalized_plan_payload(dict(record.latest_plan_json))
    record.latest_plan_json = plan_payload
    current_confirmed = None
    if record.confirmed_plan_id:
        current_confirmed = get_confirmed_plan(
            session,
            subject=subject.slug,
            plan_id=record.confirmed_plan_id,
            user_id=user_id,
        )
    if current_confirmed is not None and _normalized_plan_payload(dict(current_confirmed.plan_json or {})) == _normalized_plan_payload(plan_payload):
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
                tone=str(plan_payload.get("tone") or record.tone),
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
        session_id=record.id,
        plan_id=confirmed.id,
        plan=_plan_response(
            subject=subject.slug,
            selected_file_uids=file_uids,
            session_id=record.id,
            confirmed_plan_id=confirmed.id,
            status=record.status,
            plan=plan_payload,
        ),
    )


def get_confirmed_build_plan_service(
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


def mark_confirmed_build_plan_status(
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


def get_latest_planner_session_service(
    session: Session,
    *,
    subject: Subject,
    user_id: str,
) -> BuildPlannerSessionResponse | None:
    """Return the most recent planner session with its turns for a subject.

    Returns None if no planner session exists (i.e. the user has never
    triggered a build plan for this subject).
    """
    from app.repositories.build_planner_repo import get_latest_planner_session

    record = get_latest_planner_session(session, subject=subject.slug, user_id=user_id)
    if record is None:
        return None

    turns = list_planner_turns(session, session_id=record.id)
    plan_payload = dict(record.latest_plan_json or {})
    file_uids = _file_uids_from_ids(
        session, subject=subject.slug, file_ids=list(record.selected_file_ids_json or [])
    )

    return BuildPlannerSessionResponse(
        session_id=record.id,
        title=record.title,
        status=record.status,
        plan=_plan_response(
            subject=subject.slug,
            selected_file_uids=file_uids,
            session_id=record.id,
            confirmed_plan_id=record.confirmed_plan_id,
            status=record.status,
            plan=plan_payload,
        ),
        turns=[_turn_response(turn) for turn in turns],
        runtime_stats=None,
    )


__all__ = [
    "append_build_planner_message_service",
    "confirm_build_planner_session_service",
    "create_build_planner_session_service",
    "get_confirmed_build_plan_service",
    "get_latest_planner_session_service",
    "mark_confirmed_build_plan_status",
]
