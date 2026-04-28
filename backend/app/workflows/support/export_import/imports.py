"""Subject package import workflows."""

from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError
from sqlmodel import Session, select

from app.models import ChatSession, RawFile, RetrievalChunk, Subject
from app.repositories.knowledge import knowledge_repo
from app.schemas.export_import import ImportOptions, ImportResultData
from app.shared.infra.embedding import aembed_texts
from app.shared.infra.subject import (
    resolve_subject_build_vector_status,
    should_generate_subject_embeddings,
)
from app.shared.infra.storage import (
    build_file_storage_segment,
    build_subject_storage_scope,
    get_content_store,
    run_store_sync,
)
from app.shared.infra.exceptions import (
    ImportPackageTooLargeError,
    InvalidImportPackageError,
)
from app.workflows.support.export_import.exports import (
    TABLE_REGISTRY,
    _create_unique_slug,
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


def import_subject(
    session: Session,
    *,
    file_path: Path,
    options: ImportOptions | None = None,
    user_id: str = "local",
) -> ImportResultData:
    """Import one subject from an ``.atmx`` archive."""

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

        new_slug = _create_unique_slug(session)
        new_name = (options.new_subject_name or manifest.subject.name or "导入课程").strip() or "导入课程"

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
                    new_slug=new_slug,
                    new_name=new_name,
                    user_id=user_id,
                    warnings=warnings,
                )
                imported_counts[spec.name] = count

            legacy_plan_count = _import_legacy_confirmed_build_plans(
                session,
                tmpdir=tmpdir,
                subject_slug=new_slug,
                user_id=user_id,
                id_map=id_map,
                warnings=warnings,
            )
            if legacy_plan_count:
                imported_counts["confirmed_build_plan"] = legacy_plan_count

            _require_imported_subject(
                session,
                subject_slug=new_slug,
                imported_counts=imported_counts,
            )
            _unpack_files(
                session,
                tmpdir,
                new_slug,
                user_id=user_id,
                file_id_map=id_map.get("raw_file", {}),
            )
            _reconcile_imported_planner_metadata(
                session,
                subject_slug=new_slug,
                id_map=id_map,
            )
            session.commit()
        except Exception:
            session.rollback()
            _cleanup_import_artifacts(new_slug, user_id=user_id)
            raise

        _rebuild_imported_embeddings(
            session,
            subject_slug=new_slug,
            imported_counts=imported_counts,
            warnings=warnings,
        )

        logger.info(
            "subject_imported",
            subject=new_slug,
            name=new_name,
            counts=imported_counts,
        )
        return ImportResultData(
            subject_id=new_slug,
            subject_name=new_name,
            imported_counts=imported_counts,
            warnings=warnings,
        )


def _reconcile_imported_planner_metadata(
    session: Session,
    *,
    subject_slug: str,
    id_map: dict[str, dict[Any, Any]],
) -> None:
    """Remap planner chat-session metadata after all import ids are known."""

    file_id_map = id_map.get("raw_file") or {}
    plan_id_map = id_map.get("confirmed_build_plan") or {}
    if not file_id_map and not plan_id_map:
        return

    sessions = list(session.exec(select(ChatSession).where(ChatSession.subject == subject_slug)).all())
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

        confirmed_plan_id = meta.get("confirmed_plan_id")
        if confirmed_plan_id is not None and plan_id_map:
            meta["confirmed_plan_id"] = _lookup_imported_or_existing_id(confirmed_plan_id, plan_id_map)

        confirmed_plan = meta.get("confirmed_plan")
        if isinstance(confirmed_plan, dict) and file_id_map:
            selected_file_ids = confirmed_plan.get("selected_file_ids_json")
            if isinstance(selected_file_ids, list):
                confirmed_plan["selected_file_ids_json"] = [
                    new_id
                    for old_id in selected_file_ids
                    if (new_id := _lookup_imported_or_existing_id(old_id, file_id_map)) is not None
                ]
            plan_json = confirmed_plan.get("plan_json")
            if isinstance(plan_json, dict):
                plan_json["selected_file_ids"] = list(confirmed_plan.get("selected_file_ids_json") or [])
            meta["confirmed_plan"] = confirmed_plan

        item.meta_json = meta
        session.add(item)


def _import_legacy_confirmed_build_plans(
    session: Session,
    *,
    tmpdir: Path,
    subject_slug: str,
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
        plan_json["subject"] = subject_slug
        plan_json["selected_file_ids"] = selected_file_ids
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
            "subject": subject_slug,
            "planner_session_id": str(new_session_id),
            "user_id": user_id,
            "status": record.get("status") or "confirmed",
            "user_prompt": record.get("user_prompt") or "",
            "digest_mode": record.get("digest_mode") or "",
            "selected_file_ids_json": selected_file_ids,
            "chapter_plan_json": list(record.get("chapter_plan_json") or []),
            "build_constraints_json": dict(record.get("build_constraints_json") or {}),
            "plan_summary": record.get("plan_summary") or "",
            "plan_json": plan_json,
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
        }
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
    """Extract a subject package after validating paths and archive size."""

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


def _require_imported_subject(
    session: Session,
    *,
    subject_slug: str,
    imported_counts: dict[str, int],
) -> None:
    """Fail malformed packages before returning a phantom import success."""

    if int(imported_counts.get("subject", 0) or 0) != 1:
        raise InvalidImportPackageError("课程包缺少有效的 subject 数据。")

    subject = session.exec(select(Subject).where(Subject.slug == subject_slug)).first()
    if subject is None:
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
    new_slug: str,
    *,
    user_id: str,
    file_id_map: dict[Any, Any],
) -> None:
    """Write packaged files into ContentStore using remapped file ids."""

    subject_scope = build_subject_storage_scope(user_id=user_id, subject=new_slug)
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
                key = f"{subject_scope.namespace}/assets/docgen/{item.name}"
                run_store_sync(cs.write_bytes, key, item.read_bytes())


def _cleanup_import_artifacts(subject_slug: str, *, user_id: str) -> None:
    """Best-effort cleanup when import fails after files have been written."""

    cs = get_content_store()
    try:
        run_store_sync(
            cs.delete_prefix,
            build_subject_storage_scope(user_id=user_id, subject=subject_slug).subject_prefix(),
            default=0,
        )
    except Exception as exc:  # pragma: no cover - best-effort cleanup
        logger.warning(
            "subject_import_artifact_cleanup_failed",
            subject=subject_slug,
            error=str(exc),
        )


def _rebuild_imported_embeddings(
    session: Session,
    *,
    subject_slug: str,
    imported_counts: dict[str, int],
    warnings: list[str],
) -> None:
    """Best-effort rebuild for imported retrieval chunk embeddings."""

    if int(imported_counts.get("retrieval_chunk", 0) or 0) <= 0:
        return

    subject = session.exec(select(Subject).where(Subject.slug == subject_slug)).first()
    if subject is None:
        warnings.append("embedding_rebuild: imported subject not found after commit")
        return

    try:
        resolve_subject_build_vector_status(
            session,
            subject=subject,
            embedding_resolution=None,
        )
    except Exception as exc:
        logger.warning(
            "subject_import_embedding_precheck_failed",
            subject=subject_slug,
            error=str(exc),
        )
        warnings.append(f"embedding_rebuild: precheck failed: {exc}")
        return

    if not should_generate_subject_embeddings(session, subject_slug=subject_slug):
        logger.info(
            "subject_import_embedding_skipped",
            subject=subject_slug,
            reason="subject_vectors_disabled_or_unavailable",
        )
        return

    chunks = list(
        session.exec(
            select(RetrievalChunk)
            .where(
                RetrievalChunk.subject == subject_slug,
                RetrievalChunk.is_active.is_(True),
            )
            .order_by(RetrievalChunk.file_id, RetrievalChunk.chunk_index)
        ).all()
    )
    chunk_rows = [chunk for chunk in chunks if chunk.id is not None]
    if not chunk_rows:
        return

    payloads = [f"{chunk.title}\n{chunk.content}".strip() for chunk in chunk_rows]
    embeddings = _run_async(aembed_texts(payloads, soft_fail=True))
    if not embeddings:
        logger.warning(
            "subject_import_embedding_soft_failed",
            subject=subject_slug,
            chunk_count=len(chunk_rows),
        )
        warnings.append("embedding_rebuild: skipped because embedding service is unavailable")
        return

    try:
        knowledge_repo.bulk_insert_embeddings(
            session,
            subject=subject_slug,
            chunk_ids=[int(chunk.id) for chunk in chunk_rows],
            embeddings=embeddings,
        )
    except Exception as exc:
        logger.warning(
            "subject_import_embedding_rebuild_failed",
            subject=subject_slug,
            error=str(exc),
        )
        warnings.append(f"embedding_rebuild: failed: {exc}")


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


__all__ = ["import_subject"]
