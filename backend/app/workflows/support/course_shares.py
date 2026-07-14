"""课程分享快照用例。"""

from __future__ import annotations

import hashlib
import hmac
import json
import posixpath
import re
import secrets
import tempfile
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from threading import Condition
from time import monotonic
from typing import Any, Callable
from urllib.parse import unquote

import structlog
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.models import Course, CourseShare, CourseShareImport
from app.schemas.course_share import (
    CourseShareData,
    CourseShareDocumentContent,
    CourseShareDocumentPreview,
    CourseSharePreviewData,
)
from app.schemas.export_import import ExportOptions, ImportOptions, ImportResultData
from app.shared.infra.exceptions import AITeachMeError, CourseRegistryNotFoundError
from app.shared.infra.storage import get_content_store, run_store_sync
from app.utils.time import ensure_utc_datetime, utcnow
from app.workflows.support.course_mutation_lock import course_mutation_lock
from app.workflows.support.courses.icons import COURSE_ICON_SETTINGS_KEY, get_course_icon_key
from app.workflows.support.export_import import (
    cleanup_imported_course_artifacts,
    extract_referenced_asset_paths,
    export_course,
    import_course,
)

DEFAULT_SHARE_EXPIRES_IN_DAYS = 30
MAX_SHARE_EXPIRES_IN_DAYS = 365
SHARE_STORAGE_PREFIX = "shared/course_snapshots"
SHARE_ASSET_ROOT = "share_assets"
SHARE_PUBLIC_EXCERPT_CHARS = 900
SHARE_SNAPSHOT_SCHEMA = "aiteachme.course-share.v1"
SHARE_SNAPSHOT_COURSE_ID = "shared_course"
SHARE_SNAPSHOT_USER_ID = "shared_owner"

MAX_SHARE_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_SHARE_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_SHARE_ARCHIVE_MEMBERS = 2000
MAX_SHARE_MEMBER_BYTES = 16 * 1024 * 1024
MAX_SHARE_COMPRESSION_RATIO = 100
SHARE_SNAPSHOT_CACHE_TTL_SECONDS = 60.0
SHARE_SNAPSHOT_CACHE_MAX_ENTRIES = 4
SHARE_SNAPSHOT_CACHE_MAX_BYTES = MAX_SHARE_PACKAGE_BYTES

SAFE_SHARE_ASSET_MEDIA_TYPES = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

SHARE_TABLE_FIELDS: dict[str, frozenset[str]] = {
    "knowledge_document": frozenset(
        {
            "id",
            "course_id",
            "root_document_id",
            "parent_document_id",
            "chapter_index",
            "order_index",
            "title",
            "summary",
            "markdown_content",
            "content_markdown",
            "tags",
            "word_count",
            "version",
            "version_no",
            "document_role",
            "digest_mode",
            "build_kind",
            "is_current",
            "status",
            "published_at",
            "created_at",
            "updated_at",
        }
    ),
    "knowledge_unit": frozenset(
        {
            "id",
            "course_id",
            "knowledge_unit_type",
            "canonical_name",
            "normalized_name",
            "summary",
            "body",
            "body_markdown",
            "aliases_json",
            "status",
            "confidence",
            "type_confidence",
            "type_source",
            "build_revision_no",
            "merged_into_knowledge_unit_id",
            "created_at",
            "updated_at",
        }
    ),
    "knowledge_edge": frozenset(
        {
            "id",
            "course_id",
            "source_node_id",
            "target_node_id",
            "edge_type",
            "description",
            "weight",
            "confidence",
            "status",
            "build_revision_no",
            "created_at",
            "updated_at",
        }
    ),
}

DEFAULT_SHARE_EXPORT_OPTIONS = ExportOptions(
    include_raw_files=False,
    include_raw_markdowns=False,
    include_knowledge_docs=True,
    include_chat_history=False,
    include_exam_history=False,
    include_profile=False,
)

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class _VerifiedSnapshotCacheEntry:
    data: bytes
    created_at: float


class _VerifiedSnapshotCache:
    """Small byte-bounded cache for immutable, already-validated snapshots."""

    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_entries: int,
        max_bytes: int,
    ) -> None:
        self._ttl_seconds = max(1.0, float(ttl_seconds))
        self._max_entries = max(1, int(max_entries))
        self._max_bytes = max(1, int(max_bytes))
        self._entries: OrderedDict[tuple[str, str, int, str], _VerifiedSnapshotCacheEntry] = OrderedDict()
        self._loading: set[tuple[str, str, int, str]] = set()
        self._total_bytes = 0
        self._condition = Condition()

    def get_or_load(
        self,
        key: tuple[str, str, int, str],
        loader: Callable[[], bytes],
    ) -> bytes:
        with self._condition:
            while True:
                self._evict_expired(monotonic())
                entry = self._entries.get(key)
                if entry is not None:
                    self._entries.move_to_end(key)
                    return entry.data
                if key not in self._loading:
                    self._loading.add(key)
                    break
                self._condition.wait(timeout=self._ttl_seconds)

        try:
            data = loader()
        except BaseException:
            with self._condition:
                self._loading.discard(key)
                self._condition.notify_all()
            raise

        with self._condition:
            self._loading.discard(key)
            if len(data) <= self._max_bytes:
                previous = self._entries.pop(key, None)
                if previous is not None:
                    self._total_bytes -= len(previous.data)
                while self._entries and (
                    len(self._entries) >= self._max_entries
                    or self._total_bytes + len(data) > self._max_bytes
                ):
                    self._evict_oldest()
                if (
                    len(self._entries) < self._max_entries
                    and self._total_bytes + len(data) <= self._max_bytes
                ):
                    self._entries[key] = _VerifiedSnapshotCacheEntry(
                        data=data,
                        created_at=monotonic(),
                    )
                    self._total_bytes += len(data)
            self._condition.notify_all()
        return data

    def discard_share(self, share_id: str) -> None:
        with self._condition:
            for key in [key for key in self._entries if key[0] == share_id]:
                entry = self._entries.pop(key)
                self._total_bytes -= len(entry.data)

    def clear(self) -> None:
        with self._condition:
            self._entries.clear()
            self._loading.clear()
            self._total_bytes = 0
            self._condition.notify_all()

    def _evict_expired(self, now: float) -> None:
        for key, entry in list(self._entries.items()):
            if now - entry.created_at > self._ttl_seconds:
                self._entries.pop(key, None)
                self._total_bytes -= len(entry.data)

    def _evict_oldest(self) -> None:
        _key, entry = self._entries.popitem(last=False)
        self._total_bytes -= len(entry.data)


_VERIFIED_SNAPSHOT_CACHE = _VerifiedSnapshotCache(
    ttl_seconds=SHARE_SNAPSHOT_CACHE_TTL_SECONDS,
    max_entries=SHARE_SNAPSHOT_CACHE_MAX_ENTRIES,
    max_bytes=SHARE_SNAPSHOT_CACHE_MAX_BYTES,
)


class CourseShareNotFoundError(AITeachMeError):
    error_code = "COURSE_SHARE_NOT_FOUND"
    status_code = 404

    def __init__(self) -> None:
        super().__init__("分享链接不存在或已失效。")


class CourseShareUnavailableError(AITeachMeError):
    error_code = "COURSE_SHARE_UNAVAILABLE"
    status_code = 410

    def __init__(self, reason: str = "分享链接已失效。") -> None:
        super().__init__(reason)


def create_course_share(
    session: Session,
    *,
    course: Course,
    owner_user_id: str,
    export_options: ExportOptions | None = None,
    expires_in_days: int = DEFAULT_SHARE_EXPIRES_IN_DAYS,
) -> CourseShareData:
    """创建或更新一个静态课程分享快照。"""

    options = _secure_share_export_options(export_options)
    normalized_days = max(
        1,
        min(
            MAX_SHARE_EXPIRES_IN_DAYS,
            int(expires_in_days or DEFAULT_SHARE_EXPIRES_IN_DAYS),
        ),
    )

    with course_mutation_lock(course.id):
        return _create_course_share_locked(
            session,
            course_id=course.id,
            owner_user_id=owner_user_id,
            options=options,
            expires_in_days=normalized_days,
        )


def _create_course_share_locked(
    session: Session,
    *,
    course_id: str,
    owner_user_id: str,
    options: ExportOptions,
    expires_in_days: int,
) -> CourseShareData:
    course = session.exec(
        select(Course)
        .where(Course.id == course_id)
        .where(Course.user_id == owner_user_id)
        .with_for_update()
    ).first()
    if course is None:
        raise CourseRegistryNotFoundError(course_id)

    active_share = session.exec(
        select(CourseShare)
        .where(CourseShare.source_course_id == course_id)
        .where(CourseShare.status == "active")
        .with_for_update()
    ).first()
    if active_share is not None and active_share.owner_user_id != owner_user_id:
        raise AITeachMeError(
            "该课程已有无法由当前账号更新的分享链接。",
            status_code=409,
            error_code="COURSE_SHARE_CONFLICT",
        )

    source_path = export_course(session, course_id=course_id, options=options)
    snapshot_path: Path | None = None
    try:
        snapshot_path, stats = _build_share_snapshot(source_path, course=course, options=options)
        file_size = snapshot_path.stat().st_size
        content_sha256 = _sha256_file(snapshot_path)

        active_was_reusable = active_share is not None and _share_status(active_share) == "active"
        snapshot_storage_id = active_share.id if active_was_reusable else _new_share_id(session)
        storage_key = f"{SHARE_STORAGE_PREFIX}/{snapshot_storage_id}/{secrets.token_hex(8)}.atmx"
        previous_storage_key = active_share.storage_key if active_share is not None else None

        store = get_content_store()
        try:
            run_store_sync(store.write_file, storage_key, snapshot_path)
            stored_bytes = run_store_sync(store.read_bytes, storage_key)
            _validate_snapshot_bytes(
                stored_bytes,
                expected_size=file_size,
                expected_sha256=content_sha256,
            )
        except Exception:
            _delete_snapshot_best_effort(storage_key)
            raise

    finally:
        source_path.unlink(missing_ok=True)
        if snapshot_path is not None:
            snapshot_path.unlink(missing_ok=True)

    now = utcnow()
    reusable_share = active_share if active_share is not None and _share_status(active_share) == "active" else None
    expired_share = active_share if active_share is not None and reusable_share is None else None
    if reusable_share is not None:
        share_id = reusable_share.id
    elif active_was_reusable:
        share_id = _new_share_id(session)
    else:
        share_id = snapshot_storage_id
    token = reusable_share.token if reusable_share is not None else _new_share_token(session)

    share = reusable_share or CourseShare(
        id=share_id,
        owner_user_id=owner_user_id,
        source_course_id=course_id,
        token=token,
        token_hash=_hash_token(token),
        storage_key=storage_key,
        course_name=course.name,
        course_description=course.description,
        expires_at=now + timedelta(days=expires_in_days),
        created_at=now,
    )
    share.storage_key = storage_key
    share.course_name = course.name
    share.course_description = course.description
    share.course_icon_key = get_course_icon_key(course)
    share.file_size_bytes = file_size
    share.content_sha256 = content_sha256
    share.options_json = options.model_dump(mode="json")
    share.stats_json = stats
    share.status = "active"
    share.revoked_at = None
    share.updated_at = now
    share.expires_at = now + timedelta(days=expires_in_days)
    response_data = _to_share_data(share, token=token)
    try:
        if expired_share is not None:
            expired_share.status = "expired"
            expired_share.updated_at = now
            session.add(expired_share)
            session.flush([expired_share])
        session.add(share)
        session.flush()
    except IntegrityError:
        session.rollback()
        _delete_snapshot_best_effort(storage_key)
        winner = session.exec(
            select(CourseShare)
            .where(CourseShare.source_course_id == course_id)
            .where(CourseShare.status == "active")
        ).first()
        if (
            winner is not None
            and winner.owner_user_id == owner_user_id
            and _share_status(winner) == "active"
        ):
            return _to_share_data(winner)
        raise
    except Exception:
        session.rollback()
        _delete_snapshot_best_effort(storage_key)
        raise

    bind = session.get_bind()
    try:
        session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception as rollback_exc:
            logger.warning(
                "course_share_create_rollback_failed",
                share_id=share_id,
                storage_key=storage_key,
                error=str(rollback_exc),
            )
        verified, committed_share = _verify_share_commit_outcome(
            bind,
            share_id=share_id,
            owner_user_id=owner_user_id,
            storage_key=storage_key,
            content_sha256=content_sha256,
            expected_status="active",
        )
        if committed_share is not None:
            if previous_storage_key and previous_storage_key != storage_key:
                _delete_snapshot_best_effort(previous_storage_key)
            return _to_share_data(committed_share, token=token)
        if verified:
            _delete_snapshot_best_effort(storage_key)
        else:
            logger.warning(
                "course_share_snapshot_retained_after_uncertain_commit",
                share_id=share_id,
                storage_key=storage_key,
            )
        raise

    if previous_storage_key and previous_storage_key != storage_key:
        _delete_snapshot_best_effort(previous_storage_key)
    return response_data


def list_course_shares(
    session: Session,
    *,
    owner_user_id: str,
    course_id: str,
) -> list[CourseShareData]:
    """列出某课程由当前用户创建的分享。"""

    shares = session.exec(
        select(CourseShare)
        .where(CourseShare.owner_user_id == owner_user_id)
        .where(CourseShare.source_course_id == course_id)
        .order_by(col(CourseShare.created_at).desc())
    ).all()
    return [_to_share_data(item) for item in shares]


def revoke_course_share(
    session: Session,
    *,
    owner_user_id: str,
    course_id: str,
    share_id: str,
) -> CourseShareData:
    """撤销自己创建的分享链接。"""

    with course_mutation_lock(course_id):
        share = session.exec(
            select(CourseShare)
            .where(CourseShare.id == share_id)
            .with_for_update()
        ).first()
        if share is None or share.owner_user_id != owner_user_id or share.source_course_id != course_id:
            raise CourseShareNotFoundError()
        storage_key = share.storage_key
        response_data = _to_share_data(share)
        if share.revoked_at is None:
            now = utcnow()
            share.status = "revoked"
            share.revoked_at = now
            share.updated_at = now
            session.add(share)
            response_data = _to_share_data(share)
            bind = session.get_bind()
            try:
                session.commit()
            except Exception:
                try:
                    session.rollback()
                except Exception as rollback_exc:
                    logger.warning(
                        "course_share_revoke_rollback_failed",
                        share_id=share_id,
                        storage_key=storage_key,
                        error=str(rollback_exc),
                    )
                verified, committed_share = _verify_share_commit_outcome(
                    bind,
                    share_id=share_id,
                    owner_user_id=owner_user_id,
                    storage_key=storage_key,
                    content_sha256=None,
                    expected_status="revoked",
                )
                if committed_share is None:
                    if not verified:
                        logger.warning(
                            "course_share_snapshot_retained_after_uncertain_revoke",
                            share_id=share_id,
                            storage_key=storage_key,
                        )
                    raise
                response_data = _to_share_data(committed_share)
    _VERIFIED_SNAPSHOT_CACHE.discard_share(share.id)
    _delete_snapshot_best_effort(storage_key)
    return response_data


def preview_course_share(session: Session, *, token: str) -> CourseSharePreviewData:
    """公开预览分享链接。"""

    share = _active_share_for_public_operation(session, token)
    return CourseSharePreviewData(
        token=token,
        course_name=share.course_name,
        course_description=share.course_description,
        course_icon_key=share.course_icon_key,
        status="active",
        can_import=True,
        created_at=share.created_at,
        expires_at=share.expires_at,
        file_size_bytes=share.file_size_bytes,
        stats=_stats_from_share(share),
        documents=_preview_documents_from_snapshot(share),
    )


def read_course_share_document(
    session: Session,
    *,
    token: str,
    doc_id: str,
) -> CourseShareDocumentContent:
    """读取分享快照中的单篇知识文档正文。"""

    share = _active_share_for_public_operation(session, token)

    normalized_doc_id = str(doc_id or "").strip()
    for preview, content in _share_documents_from_snapshot(share):
        if preview.doc_id == normalized_doc_id:
            return CourseShareDocumentContent(**preview.model_dump(), content_markdown=content)
    raise CourseShareNotFoundError()


def read_course_share_asset(
    session: Session,
    *,
    token: str,
    asset_path: str,
) -> tuple[bytes, str]:
    """读取分享快照中 token 作用域内的公开资产。"""

    share = _active_share_for_public_operation(session, token)

    normalized_asset_path = _normalize_share_asset_path(asset_path)
    package_bytes = _load_and_verify_snapshot(share)
    archive_path = f"{SHARE_ASSET_ROOT}/{normalized_asset_path}"
    try:
        with zipfile.ZipFile(BytesIO(package_bytes), "r") as archive:
            if archive_path not in set(archive.namelist()):
                raise CourseShareNotFoundError()
            data = archive.read(archive_path)
    except CourseShareNotFoundError:
        raise
    except Exception as exc:
        raise CourseShareUnavailableError("分享课程包已不可用，请让创建者重新生成链接。") from exc

    media_type = _safe_share_asset_media_type(normalized_asset_path, data)
    return data, media_type


def import_course_share(
    session: Session,
    *,
    token: str,
    user_id: str,
    new_course_name: str | None = None,
) -> ImportResultData:
    """将分享快照导入当前用户空间。"""

    course_id = _share_course_id_for_token(session, token)
    with course_mutation_lock(course_id):
        return _import_course_share_locked(
            session,
            token=token,
            user_id=user_id,
            new_course_name=new_course_name,
        )


def _import_course_share_locked(
    session: Session,
    *,
    token: str,
    user_id: str,
    new_course_name: str | None,
) -> ImportResultData:
    share = _resolve_active_share_locked(session, token, detach=False)
    share_id = share.id
    existing_result = _existing_share_import_result(
        session,
        share_id=share_id,
        user_id=user_id,
    )
    if existing_result is not None:
        return existing_result

    package_bytes = _load_and_verify_snapshot(share)
    now = utcnow()
    receipt = CourseShareImport(
        id=f"share_import_{secrets.token_hex(12)}",
        share_id=share_id,
        user_id=user_id,
        imported_course_id="",
        result_json={},
        created_at=now,
        updated_at=now,
    )
    session.add(receipt)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        concurrent_result = _existing_share_import_result(
            session,
            share_id=share_id,
            user_id=user_id,
        )
        if concurrent_result is not None:
            return concurrent_result
        raise

    result: ImportResultData | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="atm_share_import_") as tmpdir:
            package_path = Path(tmpdir) / "course-share.atmx"
            package_path.write_bytes(package_bytes)
            result = import_course(
                session,
                file_path=package_path,
                options=ImportOptions(new_course_name=new_course_name, rebuild_embeddings=False),
                user_id=user_id,
                commit=False,
            )

        receipt.imported_course_id = result.course_id
        receipt.result_json = result.model_dump(mode="json")
        receipt.updated_at = utcnow()
        share.import_count += 1
        share.last_imported_at = receipt.updated_at
        share.updated_at = receipt.updated_at
        session.add(receipt)
        session.add(share)
        session.flush()
    except IntegrityError:
        session.rollback()
        if result is not None:
            cleanup_imported_course_artifacts(result.course_id, user_id=user_id)
        concurrent_result = _existing_share_import_result(
            session,
            share_id=share_id,
            user_id=user_id,
        )
        if concurrent_result is not None:
            return concurrent_result
        raise
    except Exception:
        session.rollback()
        if result is not None:
            cleanup_imported_course_artifacts(result.course_id, user_id=user_id)
        raise
    assert result is not None

    bind = session.get_bind()
    try:
        session.commit()
    except Exception as commit_exc:
        try:
            session.rollback()
        except Exception as rollback_exc:
            logger.warning(
                "course_share_import_rollback_failed",
                share_id=share_id,
                imported_course_id=result.course_id,
                error=str(rollback_exc),
            )
        verified, committed_result = _verify_share_import_commit_outcome(
            bind,
            share_id=share_id,
            user_id=user_id,
            imported_course_id=result.course_id,
        )
        if committed_result is not None:
            return committed_result
        if verified:
            cleanup_imported_course_artifacts(result.course_id, user_id=user_id)
        else:
            logger.warning(
                "course_share_import_artifacts_retained_after_uncertain_commit",
                share_id=share_id,
                imported_course_id=result.course_id,
            )
        if isinstance(commit_exc, IntegrityError):
            concurrent_result = _existing_share_import_result(
                session,
                share_id=share_id,
                user_id=user_id,
            )
            if concurrent_result is not None:
                return concurrent_result
        raise
    return result


def _secure_share_export_options(export_options: ExportOptions | None = None) -> ExportOptions:
    """Return the server-enforced public share policy, ignoring client-sensitive flags."""

    del export_options
    return ExportOptions(
        include_raw_files=False,
        include_raw_markdowns=False,
        include_knowledge_docs=True,
        include_chat_history=False,
        include_exam_history=False,
        include_profile=False,
    )


def _build_share_snapshot(
    source_path: Path,
    *,
    course: Course,
    options: ExportOptions,
) -> tuple[Path, dict[str, int]]:
    """Project a generic course export into the public ShareSnapshotV1 contract."""

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".atmx")
    snapshot_path = Path(tmp.name)
    tmp.close()
    try:
        with zipfile.ZipFile(source_path, "r") as source:
            documents = _project_knowledge_documents(
                _read_table_records_from_archive(source, "knowledge_document")
            )
            units = _project_knowledge_units(
                _read_table_records_from_archive(source, "knowledge_unit")
            )
            edges = _project_knowledge_edges(
                _read_table_records_from_archive(source, "knowledge_edge"),
                unit_ids={_stable_record_id(item.get("id")) for item in units},
            )
            tables = {
                "course": [_public_course_record(course)],
                "knowledge_document": documents,
                "knowledge_unit": units,
                "knowledge_edge": edges,
            }
            stats = {
                "raw_file_count": 0,
                "knowledge_document_count": len(documents),
                "knowledge_unit_count": len(units),
                "knowledge_edge_count": len(edges),
                "knowledge_graph_sync_run_count": 0,
                "knowledge_graph_source_ref_count": 0,
                "confirmed_build_plan_count": 0,
                "question_type_registry_count": 0,
                "question_template_count": 0,
                "exam_paper_count": 0,
                "chat_session_count": 0,
                "user_knowledge_state_count": 0,
                "total_file_size_bytes": 0,
            }
            manifest = _share_snapshot_manifest(
                course=course,
                options=options,
                tables=tables,
                stats=stats,
            )

            with zipfile.ZipFile(snapshot_path, "w", zipfile.ZIP_DEFLATED) as target:
                _write_snapshot_json(target, "manifest.json", manifest)
                for table_name, records in tables.items():
                    _write_snapshot_json(
                        target,
                        f"db/{table_name}.json",
                        {
                            "table": table_name,
                            "count": len(records),
                            "records": records,
                        },
                    )
                allowed_share_assets = {
                    f"{SHARE_ASSET_ROOT}/{asset_path}"
                    for asset_path in extract_referenced_asset_paths(
                        documents,
                        local_only=True,
                    )
                }
                _copy_safe_share_assets(
                    source,
                    target,
                    allowed_share_assets=allowed_share_assets,
                )

        snapshot_bytes = snapshot_path.read_bytes()
        _validate_snapshot_bytes(snapshot_bytes)
        return snapshot_path, stats
    except AITeachMeError:
        snapshot_path.unlink(missing_ok=True)
        raise
    except ValueError as exc:
        snapshot_path.unlink(missing_ok=True)
        detail = str(exc).lower()
        if any(
            marker in detail
            for marker in (
                "size limit",
                "too many members",
                "uncompressed size",
                "compression ratio",
                "exceeds package",
            )
        ):
            raise AITeachMeError(
                "课程公开快照超过安全资源上限，请精简课程内容后重试。",
                status_code=413,
                error_code="COURSE_SHARE_SNAPSHOT_TOO_LARGE",
            ) from exc
        raise AITeachMeError(
            "课程内容无法生成安全的公开快照，请检查课程文档后重试。",
            status_code=422,
            error_code="COURSE_SHARE_SNAPSHOT_INVALID",
        ) from exc
    except Exception as exc:
        snapshot_path.unlink(missing_ok=True)
        raise AITeachMeError(
            "课程内容无法生成安全的公开快照，请检查课程文档后重试。",
            status_code=422,
            error_code="COURSE_SHARE_SNAPSHOT_INVALID",
        ) from exc


def _public_course_record(course: Course) -> dict[str, Any]:
    icon_key = get_course_icon_key(course)
    return {
        "id": SHARE_SNAPSHOT_COURSE_ID,
        "user_id": SHARE_SNAPSHOT_USER_ID,
        "name": course.name,
        "description": course.description,
        "user_intent": "",
        "profile_json": "{}",
        "settings_json": json.dumps(
            {COURSE_ICON_SETTINGS_KEY: icon_key},
            ensure_ascii=False,
        ),
        "learning_intent_text": "",
        "course_intro_text": "",
        "document_summary_json": {},
        "llm_context_text": "",
        "status": "active",
    }


def _project_knowledge_documents(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for record in records:
        if record.get("is_current") is not True:
            continue
        status = str(record.get("status") or "").strip().lower()
        if status != "published":
            continue
        title = str(record.get("title") or "").strip()
        if record.get("id") is None or not title:
            continue
        item = _allowlisted_record(record, SHARE_TABLE_FIELDS["knowledge_document"])
        item["course_id"] = SHARE_SNAPSHOT_COURSE_ID
        item["title"] = title
        item["source_file_ids"] = "[]"
        projected.append(item)

    included_ids = {_stable_record_id(item.get("id")) for item in projected}
    for item in projected:
        for field_name in ("root_document_id", "parent_document_id"):
            if _stable_record_id(item.get(field_name)) not in included_ids:
                item[field_name] = None
    return projected


def _project_knowledge_units(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for record in records:
        status = str(record.get("status") or "").strip().lower()
        if status in {"deprecated", "merged"}:
            continue
        if (
            record.get("id") is None
            or not str(record.get("knowledge_unit_type") or "").strip()
            or not str(record.get("canonical_name") or "").strip()
            or not str(record.get("normalized_name") or "").strip()
        ):
            continue
        item = _allowlisted_record(record, SHARE_TABLE_FIELDS["knowledge_unit"])
        item["course_id"] = SHARE_SNAPSHOT_COURSE_ID
        item["evidence_refs_json"] = "[]"
        projected.append(item)

    included_ids = {_stable_record_id(item.get("id")) for item in projected}
    for item in projected:
        if _stable_record_id(item.get("merged_into_knowledge_unit_id")) not in included_ids:
            item["merged_into_knowledge_unit_id"] = None
    return projected


def _project_knowledge_edges(
    records: list[dict[str, Any]],
    *,
    unit_ids: set[str],
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for record in records:
        if str(record.get("status") or "").strip().lower() == "deprecated":
            continue
        source_id = _stable_record_id(record.get("source_node_id"))
        target_id = _stable_record_id(record.get("target_node_id"))
        if (
            record.get("id") is None
            or source_id not in unit_ids
            or target_id not in unit_ids
            or not str(record.get("edge_type") or "").strip()
        ):
            continue
        item = _allowlisted_record(record, SHARE_TABLE_FIELDS["knowledge_edge"])
        item["course_id"] = SHARE_SNAPSHOT_COURSE_ID
        item["evidence_refs_json"] = "[]"
        projected.append(item)
    return projected


def _allowlisted_record(
    record: dict[str, Any],
    allowed_fields: frozenset[str],
) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if key in allowed_fields
    }


def _stable_record_id(value: Any) -> str:
    return "" if value is None else str(value)


def _share_snapshot_manifest(
    *,
    course: Course,
    options: ExportOptions,
    tables: dict[str, list[dict[str, Any]]],
    stats: dict[str, int],
) -> dict[str, Any]:
    table_meta = []
    for table_name, records in tables.items():
        table_meta.append(
            {
                "name": table_name,
                "count": len(records),
                "optional_group": "knowledge_docs" if table_name == "knowledge_document" else None,
                "id_type": "auto",
                "course_field": "id" if table_name == "course" else "course_id",
            }
        )
    return {
        "format_version": "1.0",
        "exported_at": utcnow().isoformat(),
        "exporter": "AITeachMe",
        "package": {
            "package_id": f"share_snapshot_{secrets.token_hex(12)}",
            "kind": "course_export",
            "manifest_schema": "aiteachme.atmx.manifest",
            "content_roots": ["db", "knowledge", SHARE_ASSET_ROOT],
            "capabilities": ["course_metadata", "knowledge_docs", "knowledge_graph"],
            "min_reader_format_version": "1.0",
        },
        "course": {
            "course_id": SHARE_SNAPSHOT_COURSE_ID,
            "name": course.name,
            "description": course.description,
            "user_intent": "",
            "icon_key": get_course_icon_key(course),
        },
        "stats": stats,
        "options": options.model_dump(mode="json"),
        "tables": table_meta,
        "extensions": {"share_snapshot_schema": SHARE_SNAPSHOT_SCHEMA},
    }


def _read_table_records_from_archive(
    archive: zipfile.ZipFile,
    table_name: str,
) -> list[dict[str, Any]]:
    member_name = f"db/{table_name}.json"
    try:
        payload = json.loads(archive.read(member_name).decode("utf-8"))
    except KeyError:
        return []
    if not isinstance(payload, dict):
        raise ValueError(f"{member_name} must be an object")
    records = payload.get("records")
    if records is None:
        return []
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise ValueError(f"{member_name} contains invalid records")
    return list(records)


def _write_snapshot_json(
    archive: zipfile.ZipFile,
    member_name: str,
    payload: dict[str, Any],
) -> None:
    archive.writestr(
        member_name,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
    )


def _copy_safe_share_assets(
    source: zipfile.ZipFile,
    target: zipfile.ZipFile,
    *,
    allowed_share_assets: set[str],
) -> None:
    for member in source.infolist():
        if member.is_dir():
            continue
        member_name = member.filename
        is_share_asset = member_name.startswith(f"{SHARE_ASSET_ROOT}/")
        is_cover = member_name.startswith("knowledge/cover.")
        if not is_share_asset and not is_cover:
            continue
        if is_share_asset and member_name not in allowed_share_assets:
            continue
        file_size = int(member.file_size or 0)
        compressed_size = int(member.compress_size or 0)
        if file_size > MAX_SHARE_MEMBER_BYTES:
            raise ValueError("share image asset exceeds size limit")
        if file_size and (
            compressed_size <= 0
            or file_size / compressed_size > MAX_SHARE_COMPRESSION_RATIO
        ):
            raise ValueError("share image asset compression ratio exceeds limit")
        data = source.read(member)
        if _detect_safe_share_asset_media_type(member_name, data) is None:
            continue
        target.writestr(member_name, data)


def _verify_share_commit_outcome(
    bind: Any,
    *,
    share_id: str,
    owner_user_id: str,
    storage_key: str,
    content_sha256: str | None,
    expected_status: str,
) -> tuple[bool, CourseShare | None]:
    try:
        with Session(bind, expire_on_commit=False) as verification_session:
            share = verification_session.get(CourseShare, share_id)
            if (
                share is not None
                and share.owner_user_id == owner_user_id
                and share.storage_key == storage_key
                and (
                    content_sha256 is None
                    or hmac.compare_digest(share.content_sha256, content_sha256)
                )
                and _share_status(share) == expected_status
            ):
                return True, share
            return True, None
    except Exception as exc:
        logger.warning(
            "course_share_commit_outcome_verification_failed",
            share_id=share_id,
            storage_key=storage_key,
            error=str(exc),
        )
        return False, None


def _verify_share_import_commit_outcome(
    bind: Any,
    *,
    share_id: str,
    user_id: str,
    imported_course_id: str,
) -> tuple[bool, ImportResultData | None]:
    try:
        with Session(bind, expire_on_commit=False) as verification_session:
            receipt = verification_session.exec(
                select(CourseShareImport)
                .where(CourseShareImport.share_id == share_id)
                .where(CourseShareImport.user_id == user_id)
                .where(CourseShareImport.imported_course_id == imported_course_id)
            ).first()
            imported_course = verification_session.get(Course, imported_course_id)
            if (
                receipt is None
                or imported_course is None
                or imported_course.user_id != user_id
            ):
                return True, None
            committed_result = ImportResultData.model_validate(receipt.result_json)
            if committed_result.course_id != imported_course_id:
                return True, None
            return True, committed_result
    except Exception as exc:
        logger.warning(
            "course_share_import_commit_outcome_verification_failed",
            share_id=share_id,
            imported_course_id=imported_course_id,
            error=str(exc),
        )
        return False, None


def _new_share_id(session: Session) -> str:
    while True:
        share_id = f"share_{secrets.token_hex(10)}"
        if session.get(CourseShare, share_id) is None:
            return share_id


def _new_share_token(session: Session) -> str:
    while True:
        token = f"cshr_{secrets.token_urlsafe(24)}"
        if session.exec(select(CourseShare).where(CourseShare.token_hash == _hash_token(token))).first() is None:
            return token


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _get_share_by_token(
    session: Session,
    token: str,
    *,
    for_update: bool = False,
) -> CourseShare:
    normalized = (token or "").strip()
    if not normalized.startswith("cshr_") or len(normalized) > 128:
        raise CourseShareNotFoundError()
    statement = select(CourseShare).where(CourseShare.token_hash == _hash_token(normalized))
    if for_update:
        statement = statement.with_for_update()
    share = session.exec(statement).first()
    if share is None:
        raise CourseShareNotFoundError()
    return share


def _share_course_id_for_token(session: Session, token: str) -> str:
    share = _get_share_by_token(session, token)
    course_id = share.source_course_id
    session.rollback()
    return course_id


def _active_share_for_public_operation(session: Session, token: str) -> CourseShare:
    course_id = _share_course_id_for_token(session, token)
    with course_mutation_lock(course_id):
        try:
            return _resolve_active_share_locked(session, token, detach=True)
        except Exception:
            session.rollback()
            raise


def _resolve_active_share_locked(
    session: Session,
    token: str,
    *,
    detach: bool,
) -> CourseShare:
    share = _get_share_by_token(session, token, for_update=True)
    status = _share_status(share)
    if status != "active":
        reason = _unavailable_reason_for_status(status)
        share_id = share.id
        storage_key = share.storage_key
        if status == "expired" and share.status == "active":
            now = utcnow()
            share.status = "expired"
            share.updated_at = now
            session.add(share)
            session.commit()
        else:
            session.rollback()
        if status in {"expired", "revoked"}:
            _VERIFIED_SNAPSHOT_CACHE.discard_share(share_id)
            _delete_snapshot_best_effort(storage_key)
        raise CourseShareUnavailableError(reason)

    if detach:
        session.expunge(share)
        session.rollback()
    return share


def _existing_share_import_result(
    session: Session,
    *,
    share_id: str,
    user_id: str,
) -> ImportResultData | None:
    receipt = session.exec(
        select(CourseShareImport)
        .where(CourseShareImport.share_id == share_id)
        .where(CourseShareImport.user_id == user_id)
    ).first()
    if receipt is None:
        return None

    imported_course = session.get(Course, receipt.imported_course_id)
    if imported_course is None or imported_course.user_id != user_id:
        session.delete(receipt)
        session.flush()
        return None
    try:
        return ImportResultData.model_validate(receipt.result_json)
    except Exception:
        session.delete(receipt)
        session.flush()
        return None


def _to_share_data(share: CourseShare, *, token: str | None = None) -> CourseShareData:
    return CourseShareData(
        share_id=share.id,
        token=token or share.token,
        share_path=f"/share/courses/{token or share.token}" if (token or share.token) else None,
        source_course_id=share.source_course_id,
        course_name=share.course_name,
        course_description=share.course_description,
        course_icon_key=share.course_icon_key,
        status=_share_status(share),
        can_import=_can_import_share(share),
        created_at=share.created_at,
        expires_at=share.expires_at,
        revoked_at=share.revoked_at,
        file_size_bytes=share.file_size_bytes,
        import_count=share.import_count,
        stats=_stats_from_share(share),
        export_options=ExportOptions.model_validate(share.options_json or {}),
    )


def _stats_dict(value: Any) -> dict[str, int]:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        try:
            result[str(key)] = max(0, int(item))
        except (TypeError, ValueError):
            continue
    return result


def _stats_from_share(share: CourseShare) -> dict[str, int]:
    return _stats_dict(share.stats_json or {})


def _preview_documents_from_snapshot(share: CourseShare) -> list[CourseShareDocumentPreview]:
    """从已分享的静态课程包中读取可公开展示的文档片段。"""

    return [preview for preview, _content in _share_documents_from_snapshot(share)]


def _share_documents_from_snapshot(share: CourseShare) -> list[tuple[CourseShareDocumentPreview, str]]:
    records = _load_document_records_from_snapshot(share)
    docs: list[tuple[CourseShareDocumentPreview, str]] = []
    for record in records:
        if record.get("is_current") is False:
            continue
        status = str(record.get("status") or "").strip().lower()
        if status and status not in {"published", "current", "ready"}:
            continue
        doc_id = str(record.get("id") or "").strip()
        title = str(record.get("title") or "").strip()
        if not doc_id or not title:
            continue
        content = str(record.get("content_markdown") or record.get("markdown_content") or "").strip()
        summary = str(record.get("summary") or "").strip()
        preview = CourseShareDocumentPreview(
            doc_id=doc_id,
            title=title,
            summary=_compact_text(summary, limit=180),
            excerpt=_compact_text(content or summary, limit=SHARE_PUBLIC_EXCERPT_CHARS),
            chapter_index=_safe_int(record.get("chapter_index")),
            order_index=_safe_int(record.get("order_index")),
        )
        docs.append((preview, content))

    docs.sort(key=lambda item: (item[0].chapter_index, item[0].order_index, item[0].title))
    return docs


def _load_document_records_from_snapshot(share: CourseShare) -> list[dict[str, Any]]:
    payload = _load_snapshot_json(share, "knowledge_document")
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _load_and_verify_snapshot(share: CourseShare) -> bytes:
    cache_key = (
        share.id,
        share.storage_key,
        int(share.file_size_bytes or 0),
        str(share.content_sha256 or ""),
    )

    def load() -> bytes:
        package_bytes = run_store_sync(get_content_store().read_bytes, share.storage_key)
        _validate_snapshot_bytes(
            package_bytes,
            expected_size=share.file_size_bytes,
            expected_sha256=share.content_sha256,
        )
        return package_bytes

    try:
        return _VERIFIED_SNAPSHOT_CACHE.get_or_load(cache_key, load)
    except Exception as exc:
        raise CourseShareUnavailableError("分享课程包已不可用，请让创建者重新生成链接。") from exc


def _load_snapshot_json(share: CourseShare, table_name: str) -> dict[str, Any]:
    safe_table_name = re.sub(r"[^a-z0-9_]", "", str(table_name or "").lower())
    if not safe_table_name or safe_table_name != str(table_name or "").lower():
        raise CourseShareUnavailableError("分享课程包格式异常，请让创建者重新生成链接。")
    package_bytes = _load_and_verify_snapshot(share)
    try:
        with zipfile.ZipFile(BytesIO(package_bytes), "r") as archive:
            payload = json.loads(archive.read(f"db/{safe_table_name}.json").decode("utf-8"))
    except Exception as exc:
        raise CourseShareUnavailableError("分享课程包格式异常，请让创建者重新生成链接。") from exc
    return payload if isinstance(payload, dict) else {}


def _validate_snapshot_bytes(
    package_bytes: bytes,
    *,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> None:
    if len(package_bytes) > MAX_SHARE_PACKAGE_BYTES:
        raise ValueError("share snapshot exceeds package size limit")
    if expected_size is not None and len(package_bytes) != int(expected_size):
        raise ValueError("share snapshot size mismatch")
    if expected_sha256:
        actual_sha256 = hashlib.sha256(package_bytes).hexdigest()
        if not hmac.compare_digest(actual_sha256, str(expected_sha256).lower()):
            raise ValueError("share snapshot checksum mismatch")

    try:
        with zipfile.ZipFile(BytesIO(package_bytes), "r") as archive:
            _validate_archive_members(archive)
            names = {
                member.filename
                for member in archive.infolist()
                if not member.is_dir()
            }
            required_names = {
                "manifest.json",
                "db/course.json",
                "db/knowledge_document.json",
                "db/knowledge_unit.json",
                "db/knowledge_edge.json",
            }
            if not required_names.issubset(names):
                raise ValueError("share snapshot is missing required members")

            allowed_fixed = set(required_names)
            for member in archive.infolist():
                if member.is_dir() or member.filename in allowed_fixed:
                    continue
                if member.filename.startswith(f"{SHARE_ASSET_ROOT}/") or member.filename.startswith(
                    "knowledge/cover."
                ):
                    with archive.open(member, "r") as stream:
                        signature = stream.read(16)
                    if _detect_safe_share_asset_media_type(member.filename, signature) is None:
                        raise ValueError("share snapshot contains an unsafe asset")
                    continue
                raise ValueError(f"share snapshot contains unexpected member: {member.filename}")

            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise ValueError("invalid share snapshot archive") from exc

    if not isinstance(manifest, dict):
        raise ValueError("share snapshot manifest must be an object")
    extensions = manifest.get("extensions")
    if not isinstance(extensions, dict) or extensions.get("share_snapshot_schema") != SHARE_SNAPSHOT_SCHEMA:
        raise ValueError("unsupported share snapshot schema")


def _validate_archive_members(archive: zipfile.ZipFile) -> None:
    members = archive.infolist()
    if len(members) > MAX_SHARE_ARCHIVE_MEMBERS:
        raise ValueError("share snapshot contains too many members")

    total_size = 0
    normalized_names: set[str] = set()
    for member in members:
        name = member.filename
        normalized_name = _normalize_archive_member_name(name, is_dir=member.is_dir())
        dedupe_name = normalized_name.casefold()
        if dedupe_name in normalized_names:
            raise ValueError("share snapshot contains duplicate members")
        normalized_names.add(dedupe_name)

        if member.flag_bits & 0x1:
            raise ValueError("encrypted share snapshot members are not supported")
        file_type = (int(member.external_attr) >> 16) & 0o170000
        if file_type == 0o120000:
            raise ValueError("share snapshot contains a symbolic link")
        if member.is_dir():
            continue

        file_size = int(member.file_size or 0)
        compressed_size = int(member.compress_size or 0)
        if file_size > MAX_SHARE_MEMBER_BYTES:
            raise ValueError("share snapshot member exceeds size limit")
        total_size += file_size
        if total_size > MAX_SHARE_UNCOMPRESSED_BYTES:
            raise ValueError("share snapshot uncompressed size exceeds limit")
        if file_size and (
            compressed_size <= 0
            or file_size / compressed_size > MAX_SHARE_COMPRESSION_RATIO
        ):
            raise ValueError("share snapshot compression ratio exceeds limit")


def _normalize_archive_member_name(name: str, *, is_dir: bool) -> str:
    raw = str(name or "")
    candidate = raw[:-1] if is_dir and raw.endswith("/") else raw
    if (
        not candidate
        or "\\" in candidate
        or "\x00" in candidate
        or candidate.startswith("/")
        or any(part in {"", ".", ".."} or ":" in part for part in candidate.split("/"))
    ):
        raise ValueError("share snapshot contains an unsafe path")
    normalized = posixpath.normpath(candidate)
    if normalized != candidate or normalized.startswith("../"):
        raise ValueError("share snapshot contains an unsafe path")
    return normalized


def _detect_safe_share_asset_media_type(asset_path: str, data: bytes) -> str | None:
    extension = Path(asset_path).suffix.lower()
    media_type = SAFE_SHARE_ASSET_MEDIA_TYPES.get(extension)
    if media_type == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return media_type
    if media_type == "image/jpeg" and data.startswith(b"\xff\xd8\xff"):
        return media_type
    if media_type == "image/gif" and data.startswith((b"GIF87a", b"GIF89a")):
        return media_type
    if (
        media_type == "image/webp"
        and len(data) >= 12
        and data.startswith(b"RIFF")
        and data[8:12] == b"WEBP"
    ):
        return media_type
    return None


def _safe_share_asset_media_type(asset_path: str, data: bytes) -> str:
    media_type = _detect_safe_share_asset_media_type(asset_path, data)
    if media_type is None:
        raise CourseShareNotFoundError()
    return media_type


def _delete_snapshot_best_effort(storage_key: str) -> None:
    try:
        run_store_sync(get_content_store().delete, storage_key)
    except Exception as exc:
        logger.warning(
            "course_share_snapshot_cleanup_failed",
            storage_key=storage_key,
            error=str(exc),
        )


def _normalize_share_asset_path(asset_path: str) -> str:
    raw = unquote(str(asset_path or "")).replace("\\", "/").strip()
    raw = raw.split("#", 1)[0].split("?", 1)[0].lstrip("/")
    normalized = posixpath.normpath(raw)
    if (
        not normalized
        or normalized in {".", ".."}
        or normalized.startswith("../")
        or normalized.startswith("/")
        or "\x00" in normalized
    ):
        raise CourseShareNotFoundError()
    return normalized


def _compact_text(value: str, *, limit: int) -> str:
    text = value.strip()
    if not text:
        return ""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "- ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return f"{text[:limit].rstrip()}..." if len(text) > limit else text


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _share_status(share: CourseShare) -> str:
    if share.revoked_at is not None or share.status == "revoked":
        return "revoked"
    if share.status != "active":
        return "expired"
    expires_at = ensure_utc_datetime(share.expires_at)
    if expires_at is not None and expires_at <= utcnow():
        return "expired"
    return "active"


def _can_import_share(share: CourseShare) -> bool:
    return _share_status(share) == "active"


def _unavailable_reason(share: CourseShare) -> str:
    return _unavailable_reason_for_status(_share_status(share))


def _unavailable_reason_for_status(status: str) -> str:
    if status == "revoked":
        return "分享链接已被创建者撤销。"
    if status == "expired":
        return "分享链接已过期。"
    return "分享链接当前不可用。"
