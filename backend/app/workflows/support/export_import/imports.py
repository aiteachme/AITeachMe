"""Subject package import workflows."""

from __future__ import annotations

import asyncio
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import structlog
from sqlmodel import Session, select

from app.models import ChatSession, RetrievalChunk, Subject
from app.repositories.knowledge import knowledge_repo
from app.schemas.export_import import ImportOptions, ImportResultData
from app.shared.infra.embedding import aembed_texts
from app.shared.infra.subject import (
    resolve_subject_build_vector_status,
    should_generate_subject_embeddings,
)
from app.shared.infra.storage import (
    build_subject_storage_scope,
    get_content_store,
    run_store_sync,
)
from app.workflows.support.export_import.exports import (
    TABLE_REGISTRY,
    _create_unique_slug,
    _import_table,
    _read_manifest,
)

logger = structlog.get_logger()


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

        with zipfile.ZipFile(file_path, "r") as zf:
            _safe_extract_archive(zf, tmpdir)

        manifest = _read_manifest(tmpdir)
        new_slug = _create_unique_slug(session)
        new_name = options.new_subject_name or manifest.subject.name

        id_map: dict[str, dict[Any, Any]] = {}
        imported_counts: dict[str, int] = {}
        warnings: list[str] = []

        try:
            for spec in TABLE_REGISTRY:
                db_file = tmpdir / "db" / f"{spec.name}.json"
                if not db_file.exists():
                    continue
                data = json.loads(db_file.read_text(encoding="utf-8"))
                records = data.get("records", [])
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

            _unpack_files(
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
        meta = dict(item.meta_json or {})
        selected_file_ids = meta.get("selected_file_ids")
        if isinstance(selected_file_ids, list):
            remapped_ids = []
            for old_id in selected_file_ids:
                new_id = _lookup_imported_id(old_id, file_id_map)
                if new_id is not None:
                    remapped_ids.append(new_id)
            meta["selected_file_ids"] = remapped_ids

        confirmed_plan_id = meta.get("confirmed_plan_id")
        if confirmed_plan_id is not None:
            meta["confirmed_plan_id"] = _lookup_imported_id(confirmed_plan_id, plan_id_map)

        item.meta_json = meta
        session.add(item)


def _lookup_imported_id(old_id: Any, value_map: dict[Any, Any]) -> Any | None:
    new_id = value_map.get(old_id)
    if new_id is None and isinstance(old_id, str) and old_id.isdigit():
        new_id = value_map.get(int(old_id))
    if new_id is None and isinstance(old_id, int):
        new_id = value_map.get(str(old_id))
    return new_id


def _safe_extract_archive(zf: zipfile.ZipFile, target_dir: Path) -> None:
    """Extract a subject package without allowing paths outside target_dir."""

    target_root = target_dir.resolve()
    for member in zf.infolist():
        member_path = target_dir / member.filename
        resolved = member_path.resolve()
        try:
            resolved.relative_to(target_root)
        except ValueError as exc:
            raise ValueError(f"Invalid .atmx file: unsafe archive path {member.filename!r}") from exc
    zf.extractall(target_dir)


def _unpack_files(
    extract_dir: Path,
    new_slug: str,
    *,
    user_id: str,
    file_id_map: dict[Any, Any],
) -> None:
    """Write packaged files into ContentStore using remapped file ids."""

    cs = get_content_store()
    subject_scope = build_subject_storage_scope(user_id=user_id, subject=new_slug)

    def _upload_remapped(src_dir: Path, prefix: str) -> None:
        if not src_dir.exists():
            return
        for item in sorted(src_dir.iterdir()):
            if not item.is_file():
                continue
            try:
                old_id = int(item.stem)
                new_id = file_id_map.get(old_id, old_id)
                key = f"{subject_scope.namespace}/{prefix}/{new_id}{item.suffix}"
            except ValueError:
                key = f"{subject_scope.namespace}/{prefix}/{item.name}"
            run_store_sync(cs.write_bytes, key, item.read_bytes())

    _upload_remapped(extract_dir / "files" / "raw_files", "raw_files")
    _upload_remapped(extract_dir / "files" / "raw_markdowns", "raw_markdowns")

    src_assets = extract_dir / "files" / "assets"
    if src_assets.exists():
        for old_dir in sorted(src_assets.iterdir()):
            if not old_dir.is_dir():
                continue
            try:
                old_id = int(old_dir.name)
            except ValueError:
                continue
            new_id = file_id_map.get(old_id, old_id)
            for asset_file in sorted(old_dir.rglob("*")):
                if not asset_file.is_file():
                    continue
                relative = asset_file.relative_to(old_dir).as_posix()
                key = f"{subject_scope.namespace}/assets/{new_id}/{relative}"
                run_store_sync(cs.write_bytes, key, asset_file.read_bytes())

    src_knowledge = extract_dir / "knowledge"
    if src_knowledge.exists():
        for item in sorted(src_knowledge.iterdir()):
            if not item.is_file():
                continue
            key = subject_scope.knowledge_doc_key(item.name)
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
            .order_by(RetrievalChunk.document_id, RetrievalChunk.chunk_index)
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
