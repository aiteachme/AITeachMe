"""Subject package import workflows."""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import structlog
from sqlmodel import Session
from app.schemas.export_import import ImportOptions, ImportResultData
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
            zf.extractall(tmpdir)

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
            session.commit()
        except Exception:
            session.rollback()
            _cleanup_import_artifacts(new_slug, user_id=user_id)
            raise

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


__all__ = ["import_subject"]
