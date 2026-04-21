"""DocGen build lifecycle around the graph runtime.

这个模块负责 API 触发后的外围生命周期：文件选择、confirmed plan 读取、
构建锁、后台任务、状态查询和结果组装。真正的 LangGraph 定义与单次
运行入口在 `docgen/graph.py`。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

import structlog
from sqlmodel import Session

from app.models import IngestStatus, TaskStatus
from app.models.build_planner import ConfirmedBuildPlan
from app.models.raw_file import RawFile
from app.models.subject import Subject
from app.repositories.files_repo import list_all_raw_files_by_subject, list_raw_files_by_ids, list_raw_files_by_uids
from app.repositories.knowledge.knowledge_repo import clear_chunk_vector_metadata
from app.schemas.knowledge import (
    BuildPreviewChapterProgressResponse,
    BuildPreviewNodeResponse,
    BuildPreviewRecentEventResponse,
    DocGenBuildData,
    DocGenGetResponse,
    KnowledgeBuildMetricsResponse,
    KnowledgeBuildPreviewResponse,
    KnowledgeBuildStatusResponse,
)
from app.shared.infra.database import managed_session
from app.shared.infra.settings import get_settings
from app.workflows.digest.planner import (
    get_confirmed_build_plan,
    mark_confirmed_build_plan_status,
)
from app.shared.infra.database import managed_session
from app.shared.infra.exceptions import ConfirmedBuildPlanRequiredError, NoReadyFilesForDocGenError, RawFileNotFoundError, SubjectBuildLockConflictError
from app.shared.infra.subject import get_subject_vector_status_by_slug
from app.shared.infra.tools.builtin.markdown_processing import normalize_mermaid_blocks
from app.utils.docgen_store import KnowledgeBuildLock, acquire_knowledge_build_lock, clear_docgen_staging, read_knowledge_build_lock, read_knowledge_build_status, read_knowledge_manifest, update_knowledge_build_status
from app.utils.path_helpers import build_merged_knowledge_base_build_path, build_merged_knowledge_base_path
from app.utils.presenters import require_id, require_uid
from app.utils.time import utcnow
from app.workflows.digest.common.metrics import build_token_summary
from app.workflows.digest.common.contracts import normalize_digest_confirmed_plan_payload
from app.shared.infra.subject import inspect_subject_build_precheck, resolve_subject_build_vector_status

logger = structlog.get_logger()


def _markdown_ready(raw_file: RawFile) -> bool:
    return raw_file.status == TaskStatus.COMPLETED.value and raw_file.ingest_status in (IngestStatus.FAST_PARSED.value, IngestStatus.ENHANCING.value, IngestStatus.READY_FOR_DIGEST.value, IngestStatus.ENHANCE_FAILED.value) and bool((raw_file.parsed_markdown or "").strip())


def _clean_prompt(prompt: str | None) -> str | None:
    prompt = (prompt or "").strip()
    return prompt or None


def _sanitize_build_error_message(error_message: str | None) -> str | None:
    text = (error_message or "").strip()
    if not text:
        return None
    if text == "build_cancelled":
        return "知识构建已取消。"
    if text == "build_crashed":
        return "知识构建异常失败。"
    if text == "no_ready_digest_inputs":
        return "当前没有可用于构建的已解析资料。"
    if text == "confirmed_plan_required":
        return "知识文档构建必须基于已确认的构建方案执行，请先完成 planner 确认。"
    if "Dimension mismatch" in text or "sqlite3.OperationalError" in text or ("chunk_embeddings" in text and "embedding" in text):
        return "Embedding 配置已变化，请先重建向量后再继续。"
    if "[SQL:" in text or "parameters:" in text or "Traceback" in text or len(text) > 240:
        return "知识构建异常失败。"
    return text


def _resolve_requested_raw_files(session: Session, *, subject: str, file_uids: list[str] | None) -> list[RawFile]:
    if not file_uids:
        return []
    items = list_raw_files_by_uids(session, subject, file_uids)
    found_uids = {require_uid(item.uid, "RawFile.uid") for item in items}
    missing = [uid for uid in file_uids if uid not in found_uids]
    if missing:
        raise RawFileNotFoundError(missing[0])
    order = {uid: index for index, uid in enumerate(file_uids)}
    return sorted(items, key=lambda item: order[require_uid(item.uid, "RawFile.uid")])


def _select_ready_docgen_files(
    session: Session,
    *,
    subject: str,
    file_uids: list[str] | None,
    allow_empty: bool = False,
) -> tuple[list[RawFile], int]:
    all_files = list_all_raw_files_by_subject(session, subject)
    ready_files = [item for item in all_files if item.id is not None and _markdown_ready(item)]
    ready_file_count = len(ready_files)
    if file_uids:
        requested = _resolve_requested_raw_files(session, subject=subject, file_uids=file_uids)
        ready_ids = {require_id(item.id, "RawFile.id") for item in ready_files}
        accepted = [item for item in requested if item.id is not None and require_id(item.id, "RawFile.id") in ready_ids]
    else:
        accepted = ready_files
    if not accepted and not allow_empty:
        raise NoReadyFilesForDocGenError(subject)
    return accepted, ready_file_count


def _select_ready_docgen_files_by_ids(
    session: Session,
    *,
    subject: str,
    file_ids: list[int],
    allow_empty: bool = False,
) -> tuple[list[RawFile], int]:
    all_files = list_all_raw_files_by_subject(session, subject)
    ready_files = [item for item in all_files if item.id is not None and _markdown_ready(item)]
    ready_ids = {require_id(item.id, "RawFile.id") for item in ready_files}
    requested = {require_id(item.id, "RawFile.id"): item for item in list_raw_files_by_ids(session, subject, file_ids) if item.id is not None}
    accepted = [requested[file_id] for file_id in file_ids if file_id in requested and file_id in ready_ids]
    if not accepted and not allow_empty:
        raise NoReadyFilesForDocGenError(subject)
    return accepted, len(ready_files)


def _resolve_file_uids(raw_files: list[RawFile]) -> list[str]:
    return [require_uid(item.uid, "RawFile.uid") for item in raw_files]


def _resolve_file_ids(raw_files: list[RawFile]) -> list[int]:
    return [require_id(item.id, "RawFile.id") for item in raw_files]


def _resolve_file_uids_from_ids(session: Session, *, subject: str, file_ids: list[int]) -> list[str]:
    if not file_ids:
        return []
    raw_files = list_raw_files_by_ids(session, subject, file_ids)
    uid_by_id = {require_id(item.id, "RawFile.id"): require_uid(item.uid, "RawFile.uid") for item in raw_files if item.id is not None and item.uid is not None}
    return [uid_by_id[file_id] for file_id in file_ids if file_id in uid_by_id]


def _new_build_session_id() -> str:
    return uuid.uuid4().hex


def _clear_docgen_staging_safely(subject: str) -> None:
    try:
        clear_docgen_staging(subject)
    except Exception:
        logger.exception("knowledge_build_cleanup_failed", subject=subject)

def _write_build_status(subject: str, *, requested_at: datetime, status: str, stage: str, **extra: object) -> None:
    payload = {"requested_at": requested_at, "build_kind": "docgen", "status": status, "stage": stage, **extra}
    if "error_message" in payload:
        payload["error_message"] = _sanitize_build_error_message(payload.get("error_message"))
    update_knowledge_build_status(subject, **payload)

def _extract_markdown_excerpt(markdown: str, *, max_lines: int = 6, max_chars: int = 420) -> str:
    lines: list[str] = []
    chars = 0
    for raw_line in markdown.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped == "---":
            continue
        lines.append(stripped)
        chars += len(stripped)
        if len(lines) >= max_lines or chars >= max_chars:
            break
    excerpt = "\n".join(lines).strip()
    return excerpt if len(excerpt) <= max_chars else excerpt[: max_chars - 3].rstrip() + "..."


def _resolve_preview_chapter_titles(*, draft_markdown: str, manifest) -> list[str]:
    if manifest is not None and manifest.chapter_titles:
        return [str(title).strip() for title in manifest.chapter_titles[:4] if str(title).strip()]
    titles: list[str] = []
    for raw_line in draft_markdown.splitlines():
        stripped = raw_line.strip()
        if not stripped.startswith("#"):
            continue
        title = stripped.lstrip("#").strip()
        if title and title.lower() not in {"knowledge document overview", "知识文档总览"}:
            titles.append(title)
        if len(titles) >= 4:
            break
    return titles


def _build_initial_chapter_progress(plan: ConfirmedBuildPlan) -> list[dict[str, object]]:
    chapter_plan = list(plan.chapter_plan_json or [])
    progress: list[dict[str, object]] = []
    for index, chapter in enumerate(chapter_plan, start=1):
        chapter_index = int(chapter.get("chapter_index", index) or index)
        progress.append(
            {
                "chapter_index": chapter_index,
                "title": str(chapter.get("title") or f"第 {chapter_index} 章").strip() or f"第 {chapter_index} 章",
                "status": "planned",
                "source_count": 0,
                "local_hits": 0,
                "web_hits": 0,
                "query_count": 0,
                "word_count": 0,
                "fallback_used": False,
            }
        )
    return progress


def _build_runtime_preview(*, build_status, draft_markdown: str, manifest) -> KnowledgeBuildPreviewResponse | None:
    if build_status is None and not draft_markdown.strip() and manifest is None:
        return None
    sample_nodes = []
    sample_cards = []
    if build_status is not None:
        sample_nodes = [BuildPreviewNodeResponse(name=str(item.get("name", "")).strip(), knowledge_unit_type=str(item.get("type", "concept")).strip() or "concept") for item in build_status.sample_nodes if str(item.get("name", "")).strip()][:6]
        sample_cards = [{"title": str(item.get("title", "")).strip(), "card_type": str(item.get("card_type", "")).strip() or "topic", "summary": str(item.get("summary", "")).strip()} for item in build_status.sample_cards if str(item.get("title", "")).strip() and str(item.get("summary", "")).strip()]
    chapter_progress = [
        BuildPreviewChapterProgressResponse.model_validate(item)
        for item in list(build_status.chapter_progress or [])
    ] if build_status is not None else []
    recent_events = [
        BuildPreviewRecentEventResponse.model_validate(item)
        for item in list(build_status.recent_events or [])
    ] if build_status is not None else []
    return KnowledgeBuildPreviewResponse(current_stage_description=(build_status.current_stage_description if build_status is not None else None), digest_mode=(build_status.digest_mode if build_status is not None else None), mode_reason=(build_status.mode_reason if build_status is not None else None), processed_chunks=(build_status.processed_chunks if build_status is not None else 0), total_chunks=(build_status.total_chunks if build_status is not None else 0), discovered_node_count=(build_status.discovered_node_count if build_status is not None else 0), discovered_node_types=(dict(build_status.discovered_node_types) if build_status is not None else {}), sample_nodes=sample_nodes, sample_cards=sample_cards, plan_summary=(build_status.plan_summary if build_status is not None else None), chapter_progress=chapter_progress, recent_events=recent_events, latest_chapter_titles=_resolve_preview_chapter_titles(draft_markdown=draft_markdown, manifest=manifest), draft_excerpt=_extract_markdown_excerpt(draft_markdown))


def _build_runtime_metrics(*, build_status) -> KnowledgeBuildMetricsResponse | None:
    build_session_id = str(build_status.build_session_id).strip() if build_status is not None and build_status.build_session_id is not None else ""
    if not build_session_id:
        return None
    token_summary = build_token_summary(build_session_id=build_session_id)
    if token_summary.total_calls <= 0 and token_summary.failed_call_count <= 0:
        return None
    lane_counts = {lane: count for lane, count in token_summary.call_count_by_lane.items() if lane and lane != "(unknown_lane)" and count > 0}
    return KnowledgeBuildMetricsResponse(llm_total_calls=token_summary.total_calls, failed_llm_call_count=token_summary.failed_call_count, llm_avg_latency_ms=token_summary.avg_latency_ms, call_count_by_lane=lane_counts)


def _resolve_runtime_build_status(*, subject: str) -> KnowledgeBuildStatusResponse | None:
    build_lock = read_knowledge_build_lock(subject)
    build_status = read_knowledge_build_status(subject)
    effective = build_status
    if effective is None and build_lock is not None:
        effective = update_knowledge_build_status(subject, requested_at=build_lock.requested_at, build_kind="docgen", status="running", stage="build_accepted", source_file_ids=build_lock.source_file_ids, prompt=build_lock.prompt)
    if effective is None or effective.build_kind != "docgen":
        return None
    return KnowledgeBuildStatusResponse(status=effective.status, requested_at=effective.requested_at, stage=effective.stage, error_message=_sanitize_build_error_message(effective.error_message), draft_available=bool(effective.draft_available), progress_pct=effective.progress_pct, planner_session_id=effective.planner_session_id, confirmed_plan_id=effective.confirmed_plan_id, digest_mode=effective.digest_mode, mode_reason=effective.mode_reason, current_stage_description=effective.current_stage_description)


def _build_confirmed_plan_payload(plan: ConfirmedBuildPlan) -> dict[str, Any]:
    payload = dict(plan.plan_json or {})
    payload.setdefault("subject", plan.subject)
    payload.setdefault("user_prompt", plan.user_prompt)
    payload.setdefault("digest_mode", plan.digest_mode)
    payload.setdefault("chapter_plan", list(plan.chapter_plan_json))
    payload.setdefault("build_constraints", dict(plan.build_constraints_json))
    payload.setdefault("plan_summary", plan.plan_summary)
    payload["selected_file_ids"] = list(plan.selected_file_ids_json)
    payload["planner_session_id"] = plan.planner_session_id
    payload["confirmed_plan_id"] = plan.id
    return normalize_digest_confirmed_plan_payload(payload)


def _load_confirmed_plan_payload(*, subject: str, user_id: str, confirmed_plan_id: str) -> tuple[ConfirmedBuildPlan, dict[str, Any]]:
    with managed_session() as session:
        plan = get_confirmed_build_plan(session, subject=subject, user_id=user_id, plan_id=confirmed_plan_id)
    return plan, _build_confirmed_plan_payload(plan)


def _build_graph_seed_chapter_metadatas(confirmed_plan_payload: dict[str, Any] | None) -> list[dict[str, object]]:
    if not isinstance(confirmed_plan_payload, dict):
        return []

    normalized: list[dict[str, object]] = []
    for index, chapter in enumerate(list(confirmed_plan_payload.get("chapter_plan") or []), start=1):
        if not isinstance(chapter, dict):
            continue
        title = str(chapter.get("title") or "").strip()
        objective = str(chapter.get("objective") or "").strip()
        required_elements = [
            str(item).strip()
            for item in list(chapter.get("required_elements") or [])
            if str(item).strip()
        ]
        summary_parts = [objective]
        if required_elements:
            summary_parts.append("重点覆盖：" + "、".join(required_elements[:6]))
        summary = "\n".join(part for part in summary_parts if part).strip()
        if not title or not summary:
            continue
        normalized.append(
            {
                "chapter_index": int(chapter.get("chapter_index", index) or index),
                "title": title,
                "summary": summary,
                "research_summary": "",
                "tags": required_elements[:8],
                "source_file_ids": list(confirmed_plan_payload.get("selected_file_ids") or []),
            }
        )
    return normalized


def trigger_docgen_build(session: Session, *, subject: Subject, user_id: str, file_uids: list[str] | None, prompt: str | None, embedding_resolution: str | None, confirmed_plan_id: str | None, build_type: str = "docs") -> tuple[DocGenBuildData, list[int]]:
    """处理知识文档构建请求的同步前置阶段。

    这里还没有启动 LangGraph。它只负责确认 plan、选择可用文件、处理向量
    precheck、写 build lock / status，并把后台任务需要的 file_ids 和响应
    数据交给 API 层。
    """

    conflict = inspect_subject_build_precheck(session, subject=subject)
    vector_status = resolve_subject_build_vector_status(session, subject=subject, embedding_resolution=embedding_resolution)
    force_full_rebuild = bool(conflict is not None and conflict.requires_full_rebuild and vector_status.mode != "disabled")
    if force_full_rebuild:
        clear_chunk_vector_metadata(session, subject=subject.slug)
    planner_session_id = None
    digest_mode = None
    plan_summary = None
    chapter_progress: list[dict[str, object]] = []
    recent_events: list[dict[str, object]] = []
    cleaned_prompt = _clean_prompt(prompt)
    allow_search_only = build_type == "docs"
    if build_type != "graph" and not confirmed_plan_id:
        raise ConfirmedBuildPlanRequiredError(build_type)
    if confirmed_plan_id:
        plan = get_confirmed_build_plan(session, subject=subject.slug, user_id=user_id, plan_id=confirmed_plan_id)
        if plan.status == "building":
            raise SubjectBuildLockConflictError(subject.slug)
        planner_session_id = plan.planner_session_id
        digest_mode = plan.digest_mode
        plan_summary = plan.plan_summary
        chapter_progress = _build_initial_chapter_progress(plan)
        recent_events = [
            {
                "stage": "build_accepted",
                "chapter_index": None,
                "title": None,
                "summary": f"方案已确认，共 {len(chapter_progress)} 章，构建请求已受理。",
                "created_at": utcnow(),
            }
        ]
        accepted_files, ready_file_count = _select_ready_docgen_files_by_ids(
            session,
            subject=subject.slug,
            file_ids=list(plan.selected_file_ids_json),
            allow_empty=allow_search_only,
        )
        plan_prompt = _clean_prompt(plan.user_prompt) or _clean_prompt(plan.plan_summary)
        if file_uids:
            logger.warning(
                "knowledge_build_file_selection_ignored_for_confirmed_plan",
                subject=subject.slug,
                confirmed_plan_id=confirmed_plan_id,
                requested_file_uid_count=len(file_uids),
            )
        if cleaned_prompt and plan_prompt and cleaned_prompt != plan_prompt:
            logger.warning(
                "knowledge_build_prompt_ignored_for_confirmed_plan",
                subject=subject.slug,
                confirmed_plan_id=confirmed_plan_id,
            )
        cleaned_prompt = plan_prompt or cleaned_prompt
    else:
        accepted_files, ready_file_count = _select_ready_docgen_files(session, subject=subject.slug, file_uids=file_uids)
    accepted_file_ids = _resolve_file_ids(accepted_files)
    accepted_file_uids = _resolve_file_uids(accepted_files)
    search_only_mode = allow_search_only and not accepted_file_ids
    if search_only_mode:
        recent_events.append(
            {
                "stage": "search_only_mode",
                "chapter_index": None,
                "title": None,
                "summary": "当前没有已解析资料，本轮将以外部检索为主生成知识文档。",
                "created_at": utcnow(),
            }
        )
    requested_at = utcnow()
    if not acquire_knowledge_build_lock(subject.slug, KnowledgeBuildLock(requested_at=requested_at, source_file_ids=accepted_file_ids, prompt=cleaned_prompt)):
        raise SubjectBuildLockConflictError(subject.slug)
    clear_docgen_staging(subject.slug)
    _write_build_status(
        subject.slug,
        requested_at=requested_at,
        status="accepted",
        stage="build_accepted",
        error_message=None,
        draft_available=False,
        source_file_ids=accepted_file_ids,
        prompt=cleaned_prompt,
        staged_chapter_count=0,
        published_doc_count=0,
        planner_session_id=planner_session_id,
        confirmed_plan_id=confirmed_plan_id,
        digest_mode=digest_mode,
        plan_summary=plan_summary,
        chapter_progress=chapter_progress,
        recent_events=recent_events,
        current_stage_description=(
            "方案已确认，当前没有本地资料，将优先执行联网研究。"
            if search_only_mode
            else ("方案已确认，正在排队启动构建。" if confirmed_plan_id else None)
        ),
        build_kind="docgen" if (build_type or "docs") == "docs" else "graph",
    )
    logger.info(
        "knowledge_build_requested",
        subject=subject.slug,
        requested_at=requested_at.isoformat(),
        file_count=len(accepted_file_ids),
        force_full_rebuild=force_full_rebuild,
        vector_mode=vector_status.mode,
        planner_session_id=planner_session_id,
        confirmed_plan_id=confirmed_plan_id,
        search_only_mode=search_only_mode,
    )
    return DocGenBuildData(accepted_file_uids=accepted_file_uids, ready_file_count=ready_file_count, prompt=cleaned_prompt, requested_at=requested_at, vector_status=vector_status, planner_session_id=planner_session_id, confirmed_plan_id=confirmed_plan_id, digest_mode=digest_mode), accepted_file_ids

async def run_docgen_background(*, subject: str, file_ids: list[int], prompt: str | None, requested_at: datetime, planner_session_id: str | None = None, confirmed_plan_id: str | None = None, user_id: str | None = None) -> None:
    """后台执行 DocGen 构建生命周期。

    负责把 API 接受的构建请求转成一次真实 workflow run：加载 confirmed
    plan、可选并发触发 KG ingest、运行 `run_docgen_workflow`、同步文档到
    KG、更新状态并释放构建锁。异常处理也集中在这里，避免 API 层持有
    长任务细节。
    """

    from app.workflows.digest import run_docgen_workflow
    from app.utils.docgen_store import release_knowledge_build_lock
    from app.workflows.support.knowledge_graph import (
        run_graph_docs_sync_after_doc_build,
        run_graph_file_ingest_background,
    )
    build_session_id = _new_build_session_id()
    confirmed_plan_payload = None
    resolved_digest_mode = None
    kg_ingest_task: asyncio.Task[dict[str, int]] | None = None
    graph_seed_chapter_metadatas: list[dict[str, object]] = []
    sync_graph_after_docgen = bool(get_settings().knowledge_graph.sync_after_docgen)
    logger.info(
        "knowledge_build_background_started",
        subject=subject,
        requested_at=requested_at.isoformat(),
        file_count=len(file_ids),
        planner_session_id=planner_session_id,
        confirmed_plan_id=confirmed_plan_id,
        user_id=user_id,
    )
    if not confirmed_plan_id or not user_id:
        _write_build_status(subject, requested_at=requested_at, status="failed", stage="failed", build_session_id=build_session_id, planner_session_id=planner_session_id, confirmed_plan_id=confirmed_plan_id, digest_mode=resolved_digest_mode, error_message="confirmed_plan_required", draft_available=False)
        logger.error("knowledge_build_failed_missing_confirmed_plan", subject=subject)
        release_knowledge_build_lock(subject)
        return
    if confirmed_plan_id and user_id:
        plan, confirmed_plan_payload = _load_confirmed_plan_payload(subject=subject, user_id=user_id, confirmed_plan_id=confirmed_plan_id)
        planner_session_id = planner_session_id or plan.planner_session_id
        resolved_digest_mode = plan.digest_mode
        graph_seed_chapter_metadatas = _build_graph_seed_chapter_metadatas(confirmed_plan_payload)
        with managed_session() as session:
            mark_confirmed_build_plan_status(session, subject=subject, user_id=user_id, plan_id=confirmed_plan_id, status="building")
    try:
        _clear_docgen_staging_safely(subject)
        _write_build_status(subject, requested_at=requested_at, status="running", stage="prepare_shared", build_session_id=build_session_id, planner_session_id=planner_session_id, confirmed_plan_id=confirmed_plan_id, digest_mode=resolved_digest_mode, error_message=None, draft_available=False, source_file_ids=file_ids, prompt=prompt)
        if sync_graph_after_docgen and file_ids:
            kg_ingest_task = asyncio.create_task(
                run_graph_file_ingest_background(
                    subject=subject,
                    file_ids=file_ids,
                    prompt=prompt,
                    requested_at=requested_at,
                    build_session_id=build_session_id,
                    doc_chapter_metadatas=graph_seed_chapter_metadatas,
                    build_kind="docgen",
                )
            )
        result = await run_docgen_workflow(subject=subject, file_ids=file_ids, user_prompt=prompt, requested_at=requested_at, build_session_id=build_session_id, confirmed_plan=confirmed_plan_payload, planner_session_id=planner_session_id, confirmed_plan_id=confirmed_plan_id, digest_mode=resolved_digest_mode)
        if result.failed:
            if kg_ingest_task is not None and not kg_ingest_task.done():
                kg_ingest_task.cancel()
                try:
                    await kg_ingest_task
                except asyncio.CancelledError:
                    pass
            _clear_docgen_staging_safely(subject)
            _write_build_status(subject, requested_at=requested_at, status="failed", stage="failed", build_session_id=build_session_id, planner_session_id=planner_session_id, confirmed_plan_id=confirmed_plan_id, digest_mode=resolved_digest_mode, error_message=result.error.detail, draft_available=False)
            if confirmed_plan_id and user_id:
                with managed_session() as session:
                    mark_confirmed_build_plan_status(session, subject=subject, user_id=user_id, plan_id=confirmed_plan_id, status="failed")
            logger.error("knowledge_build_failed", subject=subject, error=result.error.detail)
            return
        ingest_metrics = {"processed_chunks": 0}
        if kg_ingest_task is not None:
            ingest_metrics = await kg_ingest_task
        doc_sync_metrics: dict[str, int | str] = {
            "knowledge_doc_source": "not_synced",
            "knowledge_doc_chapter_count": 0,
            "doc_sync_unit_changes": 0,
            "doc_sync_edge_changes": 0,
            "doc_sync_elapsed_ms": 0,
        }
        if sync_graph_after_docgen:
            doc_sync_metrics = run_graph_docs_sync_after_doc_build(
                subject=subject,
                requested_at=requested_at,
                build_session_id=build_session_id,
                file_ids=file_ids,
                prompt=prompt,
                build_kind="docgen",
            )
        _write_build_status(
            subject,
            requested_at=requested_at,
            status="completed",
            stage="completed",
            build_session_id=build_session_id,
            planner_session_id=planner_session_id,
            confirmed_plan_id=confirmed_plan_id,
            digest_mode=resolved_digest_mode,
            error_message=None,
            draft_available=False,
            processed_chunks=int(ingest_metrics.get("processed_chunks", 0) or 0),
            current_stage_description=(
                "知识文档与知识图谱已同步完成。"
                if sync_graph_after_docgen
                else "知识文档已发布完成。"
            ),
            **doc_sync_metrics,
        )
        if confirmed_plan_id and user_id:
            with managed_session() as session:
                mark_confirmed_build_plan_status(session, subject=subject, user_id=user_id, plan_id=confirmed_plan_id, status="completed")
    except asyncio.CancelledError:
        if kg_ingest_task is not None and not kg_ingest_task.done():
            kg_ingest_task.cancel()
            try:
                await kg_ingest_task
            except asyncio.CancelledError:
                pass
        _clear_docgen_staging_safely(subject)
        _write_build_status(subject, requested_at=requested_at, status="cancelled", stage="cancelled", build_session_id=build_session_id, planner_session_id=planner_session_id, confirmed_plan_id=confirmed_plan_id, digest_mode=resolved_digest_mode, error_message="build_cancelled", draft_available=False)
        if confirmed_plan_id and user_id:
            with managed_session() as session:
                mark_confirmed_build_plan_status(session, subject=subject, user_id=user_id, plan_id=confirmed_plan_id, status="cancelled")
        raise
    except Exception:
        if kg_ingest_task is not None and not kg_ingest_task.done():
            kg_ingest_task.cancel()
            try:
                await kg_ingest_task
            except asyncio.CancelledError:
                pass
        _clear_docgen_staging_safely(subject)
        _write_build_status(subject, requested_at=requested_at, status="failed", stage="failed", build_session_id=build_session_id, planner_session_id=planner_session_id, confirmed_plan_id=confirmed_plan_id, digest_mode=resolved_digest_mode, error_message="build_crashed", draft_available=False)
        if confirmed_plan_id and user_id:
            with managed_session() as session:
                mark_confirmed_build_plan_status(session, subject=subject, user_id=user_id, plan_id=confirmed_plan_id, status="failed")
        logger.exception("knowledge_build_failed", subject=subject)
        return
    finally:
        release_knowledge_build_lock(subject)


def get_docgen_result(session: Session, *, subject: str) -> DocGenGetResponse:
    """组装知识文档页面轮询所需的当前状态。

    读取已发布 Markdown、构建中草稿、manifest、build status、preview 和
    LLM 统计；该函数不触发构建，只服务 `/knowledge/docs` 轮询查询。
    """

    merged_path = build_merged_knowledge_base_path(subject)
    draft_path = build_merged_knowledge_base_build_path(subject)
    manifest = read_knowledge_manifest(subject)
    build_status = read_knowledge_build_status(subject)
    docgen_build_status = build_status if build_status is not None and build_status.build_kind == "docgen" else None
    markdown = normalize_mermaid_blocks(merged_path.read_text(encoding="utf-8")) if merged_path.exists() else ""
    draft_markdown = normalize_mermaid_blocks(draft_path.read_text(encoding="utf-8")) if draft_path.exists() else ""
    updated_at = manifest.updated_at if manifest is not None else (datetime.fromtimestamp(merged_path.stat().st_mtime) if merged_path.exists() else None)
    draft_updated_at = docgen_build_status.draft_updated_at if docgen_build_status is not None and docgen_build_status.draft_updated_at is not None else (datetime.fromtimestamp(draft_path.stat().st_mtime) if draft_path.exists() else None)
    source_file_uids = _resolve_file_uids_from_ids(session, subject=subject, file_ids=(manifest.source_file_ids if manifest is not None else [])) if manifest is not None else []
    build_response = _resolve_runtime_build_status(subject=subject)
    if build_response is not None:
        build_response.draft_available = bool(build_response.draft_available or draft_markdown.strip())
    build_preview = _build_runtime_preview(build_status=docgen_build_status, draft_markdown=draft_markdown, manifest=manifest)
    build_metrics = _build_runtime_metrics(build_status=docgen_build_status)
    return DocGenGetResponse(exists=bool(merged_path.exists() and markdown.strip()), markdown=markdown, updated_at=updated_at, source_file_uids=source_file_uids, prompt=(manifest.prompt if manifest is not None else None), draft_markdown=draft_markdown, draft_updated_at=draft_updated_at, build=build_response, build_preview=build_preview, build_metrics=build_metrics, vector_status=get_subject_vector_status_by_slug(session, subject), planner_session_id=(build_response.planner_session_id if build_response is not None else None), confirmed_plan_id=(build_response.confirmed_plan_id if build_response is not None else None), digest_mode=(build_response.digest_mode if build_response is not None else None))


__all__ = ["get_docgen_result", "run_docgen_background", "trigger_docgen_build"]
