"""课程分享快照用例。"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import tempfile
import zipfile
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

from sqlmodel import Session, col, select

from app.models import Course, CourseShare
from app.schemas.course_share import (
    CourseShareData,
    CourseShareDocumentContent,
    CourseShareDocumentPreview,
    CourseSharePreviewData,
)
from app.schemas.export_import import ExportOptions, ImportOptions, ImportResultData
from app.shared.infra.exceptions import AITeachMeError
from app.shared.infra.storage import get_content_store, run_store_sync
from app.utils.time import ensure_utc_datetime, utcnow
from app.workflows.support.courses.icons import get_course_icon_key
from app.workflows.support.export_import import export_course, import_course, preview_export

DEFAULT_SHARE_EXPIRES_IN_DAYS = 30
MAX_SHARE_EXPIRES_IN_DAYS = 365
SHARE_STORAGE_PREFIX = "shared/course_snapshots"
SHARE_PUBLIC_EXCERPT_CHARS = 900

DEFAULT_SHARE_EXPORT_OPTIONS = ExportOptions(
    include_raw_files=False,
    include_raw_markdowns=True,
    include_knowledge_docs=True,
    include_chat_history=False,
    include_exam_history=False,
    include_profile=False,
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
    """创建一个静态课程分享快照。"""

    options = export_options or DEFAULT_SHARE_EXPORT_OPTIONS
    normalized_days = max(1, min(MAX_SHARE_EXPIRES_IN_DAYS, int(expires_in_days or DEFAULT_SHARE_EXPIRES_IN_DAYS)))
    token = _new_share_token(session)
    share_id = _new_share_id(session)
    storage_key = f"{SHARE_STORAGE_PREFIX}/{share_id}.atmx"
    tmp_path = export_course(session, course_id=course.id, options=options)
    try:
        file_size = tmp_path.stat().st_size
        content_sha256 = _sha256_file(tmp_path)
        run_store_sync(get_content_store().write_file, storage_key, tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    preview = preview_export(session, course_id=course.id, options=options)
    now = utcnow()
    share = CourseShare(
        id=share_id,
        owner_user_id=owner_user_id,
        source_course_id=course.id,
        token=token,
        token_hash=_hash_token(token),
        storage_key=storage_key,
        course_name=course.name,
        course_description=course.description,
        course_icon_key=get_course_icon_key(course),
        file_size_bytes=file_size,
        content_sha256=content_sha256,
        options_json=options.model_dump(mode="json"),
        stats_json=_stats_dict(preview.stats),
        status="active",
        import_count=0,
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(days=normalized_days),
    )
    session.add(share)
    session.commit()
    session.refresh(share)
    return _to_share_data(share, token=token)


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

    share = session.get(CourseShare, share_id)
    if share is None or share.owner_user_id != owner_user_id or share.source_course_id != course_id:
        raise CourseShareNotFoundError()
    if share.revoked_at is None:
        now = utcnow()
        share.status = "revoked"
        share.revoked_at = now
        share.updated_at = now
        session.add(share)
        session.commit()
        session.refresh(share)
    return _to_share_data(share)


def preview_course_share(session: Session, *, token: str) -> CourseSharePreviewData:
    """公开预览分享链接。"""

    share = _get_share_by_token(session, token)
    return CourseSharePreviewData(
        token=token,
        course_name=share.course_name,
        course_description=share.course_description,
        course_icon_key=share.course_icon_key,
        status=_share_status(share),
        can_import=_can_import_share(share),
        created_at=share.created_at,
        expires_at=share.expires_at,
        file_size_bytes=share.file_size_bytes,
        stats=_stats_from_share(share),
        documents=_preview_documents_from_snapshot(share) if _can_import_share(share) else [],
    )


def read_course_share_document(
    session: Session,
    *,
    token: str,
    doc_id: str,
) -> CourseShareDocumentContent:
    """读取分享快照中的单篇知识文档正文。"""

    share = _get_share_by_token(session, token)
    if not _can_import_share(share):
        raise CourseShareUnavailableError(_unavailable_reason(share))

    normalized_doc_id = str(doc_id or "").strip()
    for preview, content in _share_documents_from_snapshot(share):
        if preview.doc_id == normalized_doc_id:
            return CourseShareDocumentContent(**preview.model_dump(), content_markdown=content)
    raise CourseShareNotFoundError()


def import_course_share(
    session: Session,
    *,
    token: str,
    user_id: str,
    new_course_name: str | None = None,
) -> ImportResultData:
    """将分享快照导入当前用户空间。"""

    share = _get_share_by_token(session, token)
    if not _can_import_share(share):
        raise CourseShareUnavailableError(_unavailable_reason(share))

    with tempfile.TemporaryDirectory(prefix="atm_share_import_") as tmpdir:
        try:
            package_path = run_store_sync(get_content_store().materialize, share.storage_key, Path(tmpdir))
        except Exception as exc:
            raise CourseShareUnavailableError("分享课程包已不可用，请让创建者重新生成链接。") from exc
        result = import_course(
            session,
            file_path=package_path,
            options=ImportOptions(new_course_name=new_course_name, rebuild_embeddings=False),
            user_id=user_id,
        )

    now = utcnow()
    share.import_count += 1
    share.last_imported_at = now
    share.updated_at = now
    session.add(share)
    session.commit()
    return result


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


def _get_share_by_token(session: Session, token: str) -> CourseShare:
    normalized = (token or "").strip()
    if not normalized.startswith("cshr_") or len(normalized) > 128:
        raise CourseShareNotFoundError()
    share = session.exec(select(CourseShare).where(CourseShare.token_hash == _hash_token(normalized))).first()
    if share is None:
        raise CourseShareNotFoundError()
    return share


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
    try:
        package_bytes = run_store_sync(get_content_store().read_bytes, share.storage_key)
        with zipfile.ZipFile(BytesIO(package_bytes), "r") as archive:
            payload = json.loads(archive.read("db/knowledge_document.json").decode("utf-8"))
    except Exception:
        return []

    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


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
    expires_at = ensure_utc_datetime(share.expires_at)
    if expires_at is not None and expires_at <= utcnow():
        return "expired"
    return "active"


def _can_import_share(share: CourseShare) -> bool:
    return _share_status(share) == "active"


def _unavailable_reason(share: CourseShare) -> str:
    status = _share_status(share)
    if status == "revoked":
        return "分享链接已被创建者撤销。"
    if status == "expired":
        return "分享链接已过期。"
    return "分享链接当前不可用。"
