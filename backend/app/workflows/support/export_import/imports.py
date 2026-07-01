"""Course package import workflows."""

from __future__ import annotations

import asyncio
import json
import time
import tempfile
import uuid
import zipfile
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import structlog
from langsmith import tracing_context
from pydantic import ValidationError
from sqlmodel import Session, select

from app.models import ChatSession, RawFile, RetrievalChunk, Course
from app.repositories.knowledge import knowledge_repo
from app.schemas.export_import import ImportOptions, ImportResultData
from app.shared.infra.embedding import aembed_texts
from app.shared.infra.course import (
    get_runtime_embedding_config,
    should_generate_course_embeddings,
)
from app.shared.infra.llm_support import get_llm_concurrency_limit
from app.shared.infra.observability.trace import langsmith_trace, llm_trace_scope
from app.shared.infra.storage import (
    build_file_storage_segment,
    build_course_storage_scope,
    get_content_store,
    run_store_sync,
)
from app.shared.infra.exceptions import (
    ImportPackageTooLargeError,
    InvalidImportPackageError,
    LLMCallError,
    MissingLLMApiKeyError,
)
from app.workflows.digest.docgen.lib.published_manifest import ensure_published_knowledge_manifest
from app.shared.infra.llm_support.common import build_completion_contexts
from app.workflows.support.export_import.exports import (
    TABLE_REGISTRY,
    _create_unique_course_id,
    _import_table,
    _read_manifest,
)
from app.workflows.support.export_import.limits import (
    MAX_IMPORT_ARCHIVE_MEMBERS,
    MAX_IMPORT_PACKAGE_BYTES,
    MAX_IMPORT_PACKAGE_SIZE_MB,
)

logger = structlog.get_logger()

_DOCGEN_COVER_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_IMPORT_EMBEDDING_BATCH_SIZE = 1
_IMPORT_EMBEDDING_MAX_CONCURRENCY = 1
_IMPORT_EMBEDDING_FOREGROUND_SLOT_RESERVE = 2
_IMPORT_EMBEDDING_GLOBAL_FRACTION_DIVISOR = 3


def _import_embedding_rebuild_concurrency_limit(global_limit: int | None = None) -> int:
    """Keep imported-course embedding rebuild from occupying all LLM slots."""

    llm_limit = max(
        1,
        int(get_llm_concurrency_limit() if global_limit is None else global_limit or 1),
    )
    if llm_limit <= _IMPORT_EMBEDDING_FOREGROUND_SLOT_RESERVE:
        return 1
    return max(
        1,
        min(
            _IMPORT_EMBEDDING_MAX_CONCURRENCY,
            llm_limit - _IMPORT_EMBEDDING_FOREGROUND_SLOT_RESERVE,
            max(1, llm_limit // _IMPORT_EMBEDDING_GLOBAL_FRACTION_DIVISOR),
        ),
    )


def _import_embedding_rebuild_route_unavailable_reason() -> str | None:
    """Return a reason when imported-course embedding rebuild cannot be routed."""

    try:
        runtime = get_runtime_embedding_config()
        model = (runtime.embedding_model or "").strip()
        if not model:
            return "embedding_model_not_configured"
        build_completion_contexts(task_type="embedding", model=model)
    except (LLMCallError, MissingLLMApiKeyError) as exc:
        return str(exc)
    except Exception as exc:  # pragma: no cover - defensive config guard
        logger.warning("course_import_embedding_route_preflight_failed", error=str(exc))
        return str(exc)
    return None


def import_course(
    session: Session,
    *,
    file_path: Path,
    options: ImportOptions | None = None,
    user_id: str = "local",
) -> ImportResultData:
    """Import one course from an ``.atmx`` archive."""

    options = options or ImportOptions()

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)

        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                _safe_extract_archive(zf, tmpdir)
            manifest = _read_manifest(tmpdir)
        except InvalidImportPackageError:
            raise
        except ImportPackageTooLargeError:
            raise
        except zipfile.BadZipFile as exc:
            raise InvalidImportPackageError("请上传有效的 .atmx 文件。") from exc
        except (OSError, ValueError, ValidationError) as exc:
            raise InvalidImportPackageError(str(exc)) from exc

        new_course_id = _create_unique_course_id(session)
        new_name = (options.new_course_name or manifest.course.name or "导入课程").strip() or "导入课程"

        id_map: dict[str, dict[Any, Any]] = {}
        imported_counts: dict[str, int] = {}
        warnings: list[str] = []

        try:
            for spec in TABLE_REGISTRY:
                db_file = tmpdir / "db" / f"{spec.name}.json"
                if not db_file.exists():
                    continue
                records = _read_table_records(db_file, spec.name)
                if not records:
                    continue
                count = _import_table(
                    session,
                    spec,
                    records,
                    id_map=id_map,
                    new_course_id=new_course_id,
                    new_name=new_name,
                    user_id=user_id,
                    warnings=warnings,
                )
                imported_counts[spec.name] = count

            legacy_plan_count = _import_legacy_confirmed_build_plans(
                session,
                tmpdir=tmpdir,
                course_id=new_course_id,
                user_id=user_id,
                id_map=id_map,
                warnings=warnings,
            )
            if legacy_plan_count:
                imported_counts["confirmed_build_plan"] = legacy_plan_count

            _require_imported_course(
                session,
                course_id=new_course_id,
                imported_counts=imported_counts,
            )
            _unpack_files(
                session,
                tmpdir,
                new_course_id,
                user_id=user_id,
                file_id_map=id_map.get("raw_file", {}),
            )
            ensure_published_knowledge_manifest(
                session,
                course_id=new_course_id,
                course_scope=build_course_storage_scope(user_id=user_id, course_id=new_course_id),
            )
            _reconcile_imported_planner_metadata(
                session,
                course_id=new_course_id,
                id_map=id_map,
            )
            session.commit()
        except Exception:
            session.rollback()
            _cleanup_import_artifacts(new_course_id, user_id=user_id)
            raise

        if options.rebuild_embeddings:
            _rebuild_imported_embeddings(
                session,
                course_id=new_course_id,
                imported_counts=imported_counts,
                warnings=warnings,
            )

        logger.info(
            "course_imported",
            course_id=new_course_id,
            course_name=new_name,
            counts=imported_counts,
        )
        return ImportResultData(
            course_id=new_course_id,
            course_name=new_name,
            imported_counts=imported_counts,
            warnings=warnings,
        )


def _reconcile_imported_planner_metadata(
    session: Session,
    *,
    course_id: str,
    id_map: dict[str, dict[Any, Any]],
) -> None:
    """Remap planner chat-session metadata after all import ids are known."""

    file_id_map = id_map.get("raw_file") or {}
    plan_id_map = id_map.get("confirmed_build_plan") or {}
    if not file_id_map and not plan_id_map:
        return

    sessions = list(session.exec(select(ChatSession).where(ChatSession.course_id == course_id)).all())
    for item in sessions:
        raw_meta = item.meta_json or {}
        if isinstance(raw_meta, str):
            try:
                raw_meta = json.loads(raw_meta)
            except Exception:
                raw_meta = {}
        meta = dict(raw_meta or {}) if isinstance(raw_meta, dict) else {}
        selected_file_ids = meta.get("selected_file_ids")
        if isinstance(selected_file_ids, list):
            remapped_ids = []
            for old_id in selected_file_ids:
                new_id = _lookup_imported_or_existing_id(old_id, file_id_map)
                if new_id is not None:
                    remapped_ids.append(new_id)
            meta["selected_file_ids"] = remapped_ids

        def reconcile_confirmed_plan(confirmed_plan: dict[str, Any]) -> dict[str, Any]:
            confirmed_plan = dict(confirmed_plan)
            selected_file_ids = confirmed_plan.get("selected_file_ids")
            if isinstance(selected_file_ids, list) and file_id_map:
                confirmed_plan["selected_file_ids"] = [
                    new_id
                    for old_id in selected_file_ids
                    if (new_id := _lookup_imported_or_existing_id(old_id, file_id_map)) is not None
                ]
            plan_json = confirmed_plan.get("plan_json")
            if isinstance(plan_json, dict):
                plan_json = dict(plan_json)
                plan_json["selected_file_ids"] = list(confirmed_plan.get("selected_file_ids") or [])
                confirmed_plan["plan_json"] = plan_json
            return confirmed_plan

        confirmed_plan_id = meta.get("confirmed_plan_id")
        if confirmed_plan_id is not None and plan_id_map:
            meta["confirmed_plan_id"] = _lookup_imported_or_existing_id(confirmed_plan_id, plan_id_map)

        confirmed_plan = meta.get("confirmed_plan")
        if isinstance(confirmed_plan, dict):
            meta["confirmed_plan"] = reconcile_confirmed_plan(confirmed_plan)

        confirmed_plan_history = meta.get("confirmed_plan_history")
        if isinstance(confirmed_plan_history, list):
            meta["confirmed_plan_history"] = [
                reconcile_confirmed_plan(item)
                for item in confirmed_plan_history
                if isinstance(item, dict)
            ]

        item.meta_json = meta
        session.add(item)


def _import_legacy_confirmed_build_plans(
    session: Session,
    *,
    tmpdir: Path,
    course_id: str,
    user_id: str,
    id_map: dict[str, dict[Any, Any]],
    warnings: list[str],
) -> int:
    db_file = tmpdir / "db" / "confirmed_build_plan.json"
    if not db_file.exists():
        return 0

    records = _read_table_records(db_file, "confirmed_build_plan")
    if not records:
        return 0

    session_id_map = id_map.get("chat_session") or {}
    file_id_map = id_map.get("raw_file") or {}
    plan_id_map: dict[Any, Any] = {}
    id_map["confirmed_build_plan"] = plan_id_map
    imported_count = 0

    for record in records:
        old_session_id = record.get("planner_session_id")
        new_session_id = _lookup_imported_id(old_session_id, session_id_map)
        if not new_session_id:
            warnings.append(f"confirmed_build_plan: planner_session_id {old_session_id!r} not found in chat_session")
            continue
        session_item = session.get(ChatSession, str(new_session_id))
        if session_item is None:
            continue

        old_plan_id = record.get("id")
        new_plan_id = uuid.uuid4().hex
        plan_id_map[old_plan_id] = new_plan_id

        selected_file_ids = []
        for old_file_id in list(record.get("selected_file_ids_json") or []):
            new_file_id = _lookup_imported_id(old_file_id, file_id_map)
            if new_file_id is not None:
                selected_file_ids.append(new_file_id)

        plan_json = dict(record.get("plan_json") or {})
        plan_json["course_id"] = course_id
        plan_json["selected_file_ids"] = selected_file_ids
        plan_json["chapters"] = list(record.get("chapter_plan_json") or [])
        plan_json["build_constraints"] = dict(record.get("build_constraints_json") or {})
        plan_json["plan"] = record.get("plan_summary") or ""
        plan_json["planner_session_id"] = str(new_session_id)
        plan_json["confirmed_plan_id"] = new_plan_id

        raw_meta = session_item.meta_json or {}
        if isinstance(raw_meta, str):
            try:
                raw_meta = json.loads(raw_meta)
            except Exception:
                raw_meta = {}
        meta = dict(raw_meta or {}) if isinstance(raw_meta, dict) else {}
        meta["confirmed_plan_id"] = new_plan_id
        meta["confirmed_plan"] = {
            "id": new_plan_id,
            "version_no": int(record.get("version_no") or 1),
            "course_id": course_id,
            "planner_session_id": str(new_session_id),
            "user_id": user_id,
            "status": record.get("status") or "confirmed",
            "user_prompt": record.get("user_prompt") or "",
            "digest_mode": record.get("digest_mode") or "",
            "selected_file_ids": selected_file_ids,
            "chapters": list(record.get("chapter_plan_json") or []),
            "build_constraints": dict(record.get("build_constraints_json") or {}),
            "plan": record.get("plan_summary") or "",
            "plan_json": plan_json,
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
        }
        meta["confirmed_plan_history"] = [dict(meta["confirmed_plan"])]
        session_item.meta_json = meta
        session.add(session_item)
        imported_count += 1

    return imported_count


def _lookup_imported_id(old_id: Any, value_map: dict[Any, Any]) -> Any | None:
    new_id = value_map.get(old_id)
    if new_id is None and isinstance(old_id, str) and old_id.isdigit():
        new_id = value_map.get(int(old_id))
    if new_id is None and isinstance(old_id, int):
        new_id = value_map.get(str(old_id))
    return new_id


def _lookup_imported_or_existing_id(old_id: Any, value_map: dict[Any, Any]) -> Any | None:
    new_id = _lookup_imported_id(old_id, value_map)
    if new_id is not None:
        return new_id
    old_text = str(old_id)
    for mapped_id in value_map.values():
        if old_id == mapped_id or old_text == str(mapped_id):
            return old_id
    return None


def _safe_extract_archive(zf: zipfile.ZipFile, target_dir: Path) -> None:
    """Extract a course package after validating paths and archive size."""

    target_root = target_dir.resolve()
    members = zf.infolist()
    if len(members) > MAX_IMPORT_ARCHIVE_MEMBERS:
        raise InvalidImportPackageError(
            f"压缩包文件数超过 {MAX_IMPORT_ARCHIVE_MEMBERS} 个。"
        )

    total_size = 0
    for member in members:
        total_size += int(member.file_size or 0)
        if total_size > MAX_IMPORT_PACKAGE_BYTES:
            raise ImportPackageTooLargeError(MAX_IMPORT_PACKAGE_SIZE_MB)
        member_path = target_dir / member.filename
        resolved = member_path.resolve()
        try:
            resolved.relative_to(target_root)
        except ValueError as exc:
            raise InvalidImportPackageError(f"压缩包包含不安全路径 `{member.filename}`。") from exc
    zf.extractall(target_dir)


def _read_table_records(db_file: Path, table_name: str) -> list[dict[str, Any]]:
    """Read one exported table JSON file with strict shape checks."""

    try:
        data = json.loads(db_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InvalidImportPackageError(f"`db/{table_name}.json` 不是有效 JSON。") from exc

    if not isinstance(data, dict):
        raise InvalidImportPackageError(f"`db/{table_name}.json` 顶层必须是对象。")

    records = data.get("records", [])
    if not isinstance(records, list):
        raise InvalidImportPackageError(f"`db/{table_name}.json` 的 records 必须是数组。")

    normalized: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise InvalidImportPackageError(
                f"`db/{table_name}.json` 第 {index} 条记录必须是对象。"
            )
        normalized.append(record)
    return normalized


def _require_imported_course(
    session: Session,
    *,
    course_id: str,
    imported_counts: dict[str, int],
) -> None:
    """Fail malformed packages before returning a phantom import success."""

    if int(imported_counts.get("course", 0) or 0) != 1:
        raise InvalidImportPackageError("课程包缺少有效的 course 数据。")

    course = session.exec(select(Course).where(Course.id == course_id)).first()
    if course is None:
        raise InvalidImportPackageError("课程包未能生成有效课程。")


def _exported_raw_file_segments(extract_dir: Path) -> dict[Any, str]:
    db_file = extract_dir / "db" / "raw_file.json"
    if not db_file.exists():
        return {}

    data = json.loads(db_file.read_text(encoding="utf-8"))
    segments: dict[Any, str] = {}
    for record in data.get("records", []):
        old_id = record.get("id")
        file_id = record.get("uid") or record.get("id")
        if old_id is None or not file_id:
            continue
        segments[str(old_id)] = build_file_storage_segment(
            file_id=str(file_id),
            filename=record.get("filename"),
        )
        if record.get("uid") is not None:
            segments[str(record.get("uid"))] = build_file_storage_segment(
                file_id=str(file_id),
                filename=record.get("filename"),
            )
        segments[old_id] = build_file_storage_segment(
            file_id=str(file_id),
            filename=record.get("filename"),
        )
    return segments


def _unpack_files(
    session: Session,
    extract_dir: Path,
    new_course_id: str,
    *,
    user_id: str,
    file_id_map: dict[Any, Any],
) -> None:
    """Write packaged files into ContentStore using remapped file ids."""

    course_scope = build_course_storage_scope(user_id=user_id, course_id=new_course_id)
    cs = get_content_store()

    def _raw_file_for_old_id(old_id: Any) -> RawFile | None:
        new_id = _lookup_imported_id(old_id, file_id_map) or old_id
        return session.get(RawFile, str(new_id)) if new_id is not None else None

    file_segments = _exported_raw_file_segments(extract_dir)
    for old_id, file_segment in file_segments.items():
        raw_file = _raw_file_for_old_id(old_id)
        if raw_file is None:
            continue

        raw_dir = extract_dir / "files" / "raw_files" / file_segment
        if raw_file.file_path and raw_dir.exists():
            raw_candidates = sorted(item for item in raw_dir.iterdir() if item.is_file() and item.stem == "raw")
            if raw_candidates:
                run_store_sync(cs.write_bytes, raw_file.file_path, raw_candidates[0].read_bytes())

        markdown_path = extract_dir / "files" / "raw_markdowns" / file_segment / "markdown.md"
        if raw_file.markdown_path and markdown_path.exists():
            run_store_sync(cs.write_bytes, raw_file.markdown_path, markdown_path.read_bytes())

        asset_dir = extract_dir / "files" / "assets" / file_segment
        if raw_file.asset_dir and asset_dir.exists():
            asset_prefix = raw_file.asset_dir.rstrip("/") + "/"
            for asset_file in sorted(asset_dir.rglob("*")):
                if not asset_file.is_file():
                    continue
                relative = asset_file.relative_to(asset_dir).as_posix()
                run_store_sync(cs.write_bytes, f"{asset_prefix}{relative}", asset_file.read_bytes())

    src_knowledge = extract_dir / "knowledge"
    if src_knowledge.exists():
        # Published chapter markdown is imported from KnowledgeDocument rows; only
        # non-DB docgen assets need to be restored.
        for item in sorted(src_knowledge.iterdir()):
            if not item.is_file():
                continue
            if item.stem == "cover" and item.suffix.lower() in _DOCGEN_COVER_IMAGE_EXTENSIONS:
                key = f"{course_scope.namespace}/assets/docgen/{item.name}"
                run_store_sync(cs.write_bytes, key, item.read_bytes())


def _cleanup_import_artifacts(course_id: str, *, user_id: str) -> None:
    """Best-effort cleanup when import fails after files have been written."""

    cs = get_content_store()
    try:
        run_store_sync(
            cs.delete_prefix,
            build_course_storage_scope(user_id=user_id, course_id=course_id).course_prefix(),
            default=0,
        )
    except Exception as exc:  # pragma: no cover - best-effort cleanup
        logger.warning(
            "course_import_artifact_cleanup_failed",
            course_id=course_id,
            error=str(exc),
        )


def _rebuild_imported_embeddings(
    session: Session,
    *,
    course_id: str,
    imported_counts: dict[str, int],
    warnings: list[str],
) -> None:
    """Best-effort rebuild for imported retrieval chunk embeddings."""

    if int(imported_counts.get("retrieval_chunk", 0) or 0) <= 0:
        return

    course_record = session.exec(select(Course).where(Course.id == course_id)).first()
    if course_record is None:
        warnings.append("embedding_rebuild: imported course not found after commit")
        return

    if not should_generate_course_embeddings(session, course_id=course_id):
        logger.info(
            "course_import_embedding_skipped",
            course_id=course_id,
            reason="course_vectors_disabled_or_unavailable",
        )
        return
    runtime = get_runtime_embedding_config()

    chunks = list(
        session.exec(
            select(RetrievalChunk)
            .where(
                RetrievalChunk.course_id == course_id,
                RetrievalChunk.is_active.is_(True),
            )
            .order_by(RetrievalChunk.file_id, RetrievalChunk.chunk_index)
        ).all()
    )
    chunk_rows = [chunk for chunk in chunks if chunk.id is not None]
    if not chunk_rows:
        return

    payloads = [f"{chunk.title}\n{chunk.content}".strip() for chunk in chunk_rows]
    concurrency_limit = _import_embedding_rebuild_concurrency_limit()
    embeddings = _run_async(
        aembed_texts(
            payloads,
            batch_size=_IMPORT_EMBEDDING_BATCH_SIZE,
            soft_fail=True,
            model=runtime.embedding_model,
            max_concurrent=concurrency_limit,
        )
    )
    if not embeddings:
        logger.warning(
            "course_import_embedding_soft_failed",
            course_id=course_id,
            chunk_count=len(chunk_rows),
            concurrency_limit=concurrency_limit,
        )
        warnings.append("embedding_rebuild: skipped because embedding service is unavailable")
        return

    try:
        knowledge_repo.bulk_insert_embeddings(
            session,
            course_id=course_id,
            chunk_ids=[int(chunk.id) for chunk in chunk_rows],
            embeddings=embeddings,
            embedding_model=runtime.embedding_model,
        )
    except Exception as exc:
        logger.warning(
            "course_import_embedding_rebuild_failed",
            course_id=course_id,
            concurrency_limit=concurrency_limit,
            error=str(exc),
        )
        warnings.append(f"embedding_rebuild: failed: {exc}")


def _rebuild_imported_embeddings_with_new_session(
    *,
    course_id: str,
    imported_counts: dict[str, int],
    warnings: list[str],
) -> None:
    from app.shared.infra.database import managed_session

    with managed_session() as session:
        _rebuild_imported_embeddings(
            session,
            course_id=course_id,
            imported_counts=imported_counts,
            warnings=warnings,
        )


def _rebuild_imported_embeddings_with_trace(
    *,
    course_id: str,
    imported_counts: dict[str, int],
    warnings: list[str],
) -> None:
    workflow = "course_import_embeddings"
    lane = "background"
    node = "rebuild_retrieval_embeddings"
    chunk_count = int(imported_counts.get("retrieval_chunk", 0) or 0)
    concurrency_limit = _import_embedding_rebuild_concurrency_limit()
    started = time.monotonic()
    with llm_trace_scope(
        course_id=course_id,
        workflow=workflow,
        lane=lane,
        node=node,
    ):
        with langsmith_trace(
            name="导入课程：重建检索索引",
            run_type="chain",
            inputs={
                "course_id": course_id,
                "retrieval_chunk_count": chunk_count,
                "embedding_concurrency_limit": concurrency_limit,
            },
            course_id=course_id,
            workflow=workflow,
            lane=lane,
            node=node,
            extra_metadata={
                "background_sidecar": "course_import_embeddings",
                "retrieval_chunk_count": chunk_count,
                "embedding_concurrency_limit": concurrency_limit,
            },
            extra_tags=["background:course_import_embeddings"],
        ) as trace_run:
            with (
                tracing_context(parent=trace_run)
                if trace_run is not None
                else nullcontext()
            ):
                _rebuild_imported_embeddings_with_new_session(
                    course_id=course_id,
                    imported_counts=imported_counts,
                    warnings=warnings,
                )
            if trace_run is not None:
                trace_run.end(
                    outputs={
                        "status": "completed" if not warnings else "completed_with_warnings",
                        "elapsed_s": round(time.monotonic() - started, 2),
                        "retrieval_chunk_count": chunk_count,
                        "embedding_concurrency_limit": concurrency_limit,
                        "warning_count": len(warnings),
                    }
                )


async def rebuild_imported_embeddings_background(
    *,
    course_id: str,
    imported_counts: dict[str, int],
) -> None:
    """Rebuild imported course embeddings without holding up the import response."""

    warnings: list[str] = []
    await asyncio.to_thread(
        _rebuild_imported_embeddings_with_trace,
        course_id=course_id,
        imported_counts=dict(imported_counts),
        warnings=warnings,
    )
    if warnings:
        logger.warning(
            "course_import_embedding_background_warnings",
            course_id=course_id,
            warnings=warnings,
        )


def spawn_imported_embedding_rebuild_background(
    background_task_registry: Any | None,
    *,
    course_id: str,
    imported_counts: dict[str, int],
) -> bool:
    """Schedule imported-course embedding rebuild, returning whether it was queued."""

    if int(imported_counts.get("retrieval_chunk", 0) or 0) <= 0:
        return False
    if background_task_registry is None:
        logger.warning(
            "course_import_embedding_background_registry_missing",
            course_id=course_id,
        )
        return False
    route_unavailable_reason = _import_embedding_rebuild_route_unavailable_reason()
    if route_unavailable_reason:
        logger.info(
            "course_import_embedding_background_skipped",
            course_id=course_id,
            reason=route_unavailable_reason,
        )
        return False

    coroutine = rebuild_imported_embeddings_background(
        course_id=course_id,
        imported_counts=imported_counts,
    )
    try:
        background_task_registry.spawn(
            coroutine,
            kind="course.import.embeddings",
            course_id=course_id,
            name=f"course.import.embeddings:{course_id}",
        )
    except Exception:
        coroutine.close()
        raise
    return True


def _run_async(coro):
    """Run one coroutine safely from sync import flows."""

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


__all__ = [
    "import_course",
    "rebuild_imported_embeddings_background",
    "spawn_imported_embedding_rebuild_background",
]
