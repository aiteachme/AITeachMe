"""Subject-level export/import support commands.

The table registry drives export/import order and foreign-key remapping.
"""

from __future__ import annotations

import json
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field
from sqlmodel import Session, SQLModel, func, select

from app.shared.infra.runtime import get_app_version, is_cloud_mode
from app.shared.infra.storage import (
    build_subject_storage_scope,
    get_content_store,
    run_store_sync,
)
from app.models import (
    ChatMessage,
    ChatSession,
    ConfirmedBuildPlan,
    ExamPaper,
    ExamPaperItem,
    KnowledgeDocument,
    KnowledgeEdge,
    KnowledgeUnit,
    QuestionTypeRegistry,
    QuestionTemplate,
    RawFile,
    RetrievalChunk,
    Subject,
    UserKnowledgeState,
)
from app.schemas.export_import import (
    ExportOptions,
    ExportPreviewData,
    ExportPreviewStats,
)
from app.utils.path_helpers import sanitize_doc_title
from app.utils.subject import generate_subject_id
from app.utils.time import utcnow
from app.workflows.support.subjects.icons import (
    SUBJECT_ICON_SETTINGS_KEY,
    infer_subject_icon_key,
    normalize_subject_icon_key,
)

logger = structlog.get_logger()

SUPPORTED_FORMAT_VERSIONS = {"1.0"}


# ---------------------------------------------------------------------------
# Manifest 内部模型（仅用于 .atmx 文件，不走 API）


class _ManifestSubject(BaseModel):
    slug: str
    name: str


class _ManifestStats(BaseModel):
    raw_file_count: int = 0
    knowledge_document_count: int = 0
    knowledge_unit_count: int = 0
    knowledge_edge_count: int = 0
    confirmed_build_plan_count: int = 0
    question_type_registry_count: int = 0
    question_template_count: int = 0
    exam_paper_count: int = 0
    chat_session_count: int = 0
    total_file_size_bytes: int = 0


class _ExportManifest(BaseModel):
    format_version: str = "1.0"
    app_version: str = ""
    exported_at: datetime | None = None
    exporter: str = "AITeachMe"
    subject: _ManifestSubject
    stats: _ManifestStats = Field(default_factory=_ManifestStats)
    options: ExportOptions = Field(default_factory=ExportOptions)


# ---------------------------------------------------------------------------
# Table Registry — 导入导出的唯一配置源


@dataclass
class _TableSpec:
    """Import/export rules for one business table."""

    name: str
    model: type[SQLModel]
    # How to filter by subject: field name | "slug" (Subject itself) | None (filter via parent table)
    subject_field: str | None = "subject"
    id_field: str = "id"
    # id 类型："auto" (自增) | "uuid" (字符串 UUID)
    id_type: str = "auto"
    # Foreign-key remapping: {field_name: referenced_table_name}
    fk_remap: dict[str, str] = dc_field(default_factory=dict)
    # Filter via parent table (for tables without a subject field)
    parent_fk: str | None = None
    parent_table: str | None = None
    # Optional export group: "chat" | "exam" | "profile" | None (always export)
    optional_group: str | None = None


# Tables must be ordered by dependency: referenced tables come first.
TABLE_REGISTRY: list[_TableSpec] = [
    _TableSpec("subject", Subject, subject_field="slug"),
    _TableSpec("raw_file", RawFile),
    _TableSpec(
        "retrieval_chunk",
        RetrievalChunk,
        fk_remap={"document_id": "raw_file"},
    ),
    _TableSpec(
        "knowledge_document",
        KnowledgeDocument,
        fk_remap={
            "root_document_id": "knowledge_document",
            "parent_document_id": "knowledge_document",
        },
    ),
    _TableSpec(
        "knowledge_unit",
        KnowledgeUnit,
        fk_remap={"merged_into_knowledge_unit_id": "knowledge_unit"},
    ),
    _TableSpec(
        "knowledge_edge",
        KnowledgeEdge,
        fk_remap={
            "source_node_id": "knowledge_unit",
            "target_node_id": "knowledge_unit",
        },
    ),
    _TableSpec(
        "question_type_registry",
        QuestionTypeRegistry,
        optional_group="exam",
    ),
    _TableSpec(
        "question_template",
        QuestionTemplate,
        fk_remap={
            "knowledge_unit_id": "knowledge_unit",
        },
        optional_group="exam",
    ),
    _TableSpec(
        "exam_paper",
        ExamPaper,
        optional_group="exam",
    ),
    _TableSpec(
        "exam_paper_item",
        ExamPaperItem,
        subject_field=None,
        parent_fk="exam_paper_id",
        parent_table="exam_paper",
        fk_remap={
            "exam_paper_id": "exam_paper",
            "question_template_id": "question_template",
            "knowledge_unit_id": "knowledge_unit",
        },
        optional_group="exam",
    ),
    _TableSpec(
        "user_knowledge_state",
        UserKnowledgeState,
        fk_remap={
            "knowledge_unit_id": "knowledge_unit",
            "source_exam_paper_id": "exam_paper",
        },
        optional_group="profile",
    ),
    _TableSpec(
        "chat_session",
        ChatSession,
        id_type="uuid",
        optional_group="chat",
    ),
    _TableSpec(
        "confirmed_build_plan",
        ConfirmedBuildPlan,
        id_type="uuid",
        fk_remap={"planner_session_id": "chat_session"},
    ),
    _TableSpec(
        "chat_message",
        ChatMessage,
        fk_remap={
            "session_id": "chat_session",
            "source_chunk_id": "retrieval_chunk",
        },
        optional_group="chat",
    ),
]


# ===================================================================
# Public API
# ===================================================================


def preview_export(session: Session, *, subject_slug: str) -> ExportPreviewData:
    """Build an export preview for one subject."""

    subject = _require_subject(session, subject_slug)
    raw_files = session.exec(select(RawFile).where(RawFile.subject == subject_slug)).all()
    total_size = sum(r.file_size_bytes or 0 for r in raw_files)

    stats = ExportPreviewStats(
        raw_file_count=len(raw_files),
        total_raw_file_size_bytes=total_size,
        knowledge_document_count=_count(session, KnowledgeDocument, subject_slug),
        knowledge_unit_count=_count(session, KnowledgeUnit, subject_slug),
        knowledge_edge_count=_count(session, KnowledgeEdge, subject_slug),
        confirmed_build_plan_count=_count(session, ConfirmedBuildPlan, subject_slug),
        question_type_registry_count=_count(session, QuestionTypeRegistry, subject_slug),
        question_template_count=_count(session, QuestionTemplate, subject_slug),
        exam_paper_count=_count(session, ExamPaper, subject_slug),
        chat_session_count=_count(session, ChatSession, subject_slug),
        user_knowledge_state_count=_count(session, UserKnowledgeState, subject_slug),
    )
    return ExportPreviewData(
        subject_id=subject.slug,
        subject_name=subject.name,
        stats=stats,
        estimated_size_bytes=total_size * 2,
    )


def export_subject(
    session: Session,
    *,
    subject_slug: str,
    options: ExportOptions | None = None,
) -> Path:
    """Package one subject into a temporary .atmx archive."""

    options = options or ExportOptions()
    subject = _require_subject(session, subject_slug)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".atmx")
    tmp.close()
    tmp_path = Path(tmp.name)

    try:
        subject_scope = build_subject_storage_scope(user_id=subject.user_id, subject=subject.slug)
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            exported: dict[str, list[dict]] = {}

            for spec in TABLE_REGISTRY:
                if not _should_export(spec, options):
                    continue
                records = _query_table(session, spec, subject_slug, exported)
                exported[spec.name] = records
                zf.writestr(
                    f"db/{spec.name}.json",
                    json.dumps(
                        {"table": spec.name, "count": len(records), "records": records},
                        ensure_ascii=False, indent=2, default=str,
                    ),
                )

            _pack_files(zf, subject_scope.namespace, options)

            manifest = _build_manifest(subject, exported, options)
            zf.writestr("manifest.json", manifest.model_dump_json(indent=2))

        logger.info("subject_exported", subject=subject_slug, path=str(tmp_path))
        return tmp_path

    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
# ===================================================================
# Internal: DB helpers
# ===================================================================


def _require_subject(session: Session, slug: str) -> Subject:
    from app.shared.infra.exceptions import SubjectRegistryNotFoundError

    subject = session.exec(select(Subject).where(Subject.slug == slug)).first()
    if subject is None:
        raise SubjectRegistryNotFoundError(slug)
    return subject


def _count(session: Session, model: type, subject_slug: str) -> int:
    return int(
        session.exec(
            select(func.count()).select_from(model).where(model.subject == subject_slug)
        ).one()
    )


def _should_export(spec: _TableSpec, options: ExportOptions) -> bool:
    if spec.optional_group is None:
        return True
    return {
        "chat": options.include_chat_history,
        "exam": options.include_exam_history,
        "profile": options.include_profile,
    }.get(spec.optional_group, True)


def _query_table(
    session: Session,
    spec: _TableSpec,
    subject_slug: str,
    exported: dict[str, list[dict]],
) -> list[dict]:
    def _ordered(stmt):
        order_col = getattr(spec.model, spec.id_field, None)
        if order_col is None:
            return stmt
        return stmt.order_by(order_col)

    if spec.subject_field == "slug":
        rows = session.exec(_ordered(select(spec.model).where(spec.model.slug == subject_slug))).all()
    elif spec.subject_field:
        col = getattr(spec.model, spec.subject_field)
        rows = session.exec(_ordered(select(spec.model).where(col == subject_slug))).all()
    elif spec.parent_fk and spec.parent_table:
        parent_ids = {r["id"] for r in exported.get(spec.parent_table, [])}
        if not parent_ids:
            return []
        col = getattr(spec.model, spec.parent_fk)
        rows = session.exec(_ordered(select(spec.model).where(col.in_(parent_ids)))).all()
    else:
        return []

    return [_record_to_dict(row) for row in rows]


def _record_to_dict(record: SQLModel) -> dict:
    data = {}
    for key, value in record.model_dump().items():
        if hasattr(value, "isoformat"):
            data[key] = value.isoformat()
        else:
            data[key] = value
    return data


def _ensure_subject_icon(record_data: dict[str, Any], subject_name: str) -> None:
    settings = _decode_settings_json(record_data.get("settings_json"))
    if normalize_subject_icon_key(settings.get(SUBJECT_ICON_SETTINGS_KEY)) is None:
        settings[SUBJECT_ICON_SETTINGS_KEY] = infer_subject_icon_key(subject_name)
    record_data["settings_json"] = json.dumps(settings, ensure_ascii=False)


def _decode_settings_json(raw_value: Any) -> dict[str, Any]:
    if isinstance(raw_value, dict):
        return dict(raw_value)
    try:
        decoded = json.loads(str(raw_value or "{}"))
    except Exception:
        return {}
    return decoded if isinstance(decoded, dict) else {}


# ===================================================================
# Internal: DB import
# ===================================================================


def _create_unique_slug(session: Session) -> str:
    for _ in range(100):
        slug = generate_subject_id()
        if session.exec(select(Subject).where(Subject.slug == slug)).first() is None:
            return slug
    raise RuntimeError("Cannot generate unique subject slug after 100 attempts")


def _import_table(
    session: Session,
    spec: _TableSpec,
    records: list[dict],
    *,
    id_map: dict[str, dict[Any, Any]],
    new_slug: str,
    new_name: str,
    user_id: str,
    warnings: list[str],
) -> int:
    table_id_map: dict[Any, Any] = {}
    id_map[spec.name] = table_id_map  # Register early to support self-referencing foreign keys
    self_fk_fields = {fk_field for fk_field, ref_table in spec.fk_remap.items() if ref_table == spec.name}
    pending_self_refs: list[tuple[SQLModel, dict[str, Any], Any]] = []

    for raw_record in records:
        record_data = dict(raw_record)
        old_id = record_data.get(spec.id_field)
        old_self_refs = {field: record_data.get(field) for field in self_fk_fields}

        # 新 ID
        if spec.id_type == "auto":
            record_data[spec.id_field] = None
        elif spec.id_type == "uuid":
            record_data[spec.id_field] = str(uuid.uuid4())

        # 更新 subject
        if spec.name == "subject":
            record_data["slug"] = new_slug
            record_data["name"] = new_name
            record_data["normalized_name"] = None
            _ensure_subject_icon(record_data, new_name)
        elif spec.subject_field and spec.subject_field != "slug":
            record_data[spec.subject_field] = new_slug

        # 更新 user_id
        if "user_id" in record_data:
            record_data["user_id"] = user_id

        # Remap foreign keys after the referenced tables have been imported.
        for fk_field, ref_table in spec.fk_remap.items():
            if fk_field in self_fk_fields:
                record_data[fk_field] = None
                continue
            _remap_fk(record_data, fk_field, ref_table, id_map, spec.name, warnings)

        if spec.name == "confirmed_build_plan":
            _remap_id_list_field(
                record_data,
                "selected_file_ids_json",
                "raw_file",
                id_map,
                spec.name,
                warnings,
            )

        # Clear absolute-path fields so they can be rebuilt during import
        if spec.name == "raw_file":
            record_data["uid"] = str(uuid.uuid4())  # Prevent unique-constraint conflicts
            record_data["markdown_path"] = None
            record_data["asset_dir"] = None
            record_data["storage_uri"] = None
            record_data["markdown_uri"] = None
        elif spec.name == "retrieval_chunk":
            record_data["embedding_model"] = None
            record_data["vector_ref"] = None
        elif spec.name == "knowledge_document":
            record_data["markdown_path"] = None
            record_data["markdown_uri"] = None

        # Create and flush the row to obtain its new primary key.
        try:
            instance = spec.model.model_validate(record_data)
            session.add(instance)
            session.flush()
        except Exception as exc:
            warnings.append(f"{spec.name}: skipped record (old_id={old_id}): {exc}")
            continue

        new_id = getattr(instance, spec.id_field)

        # Rebuild storage keys under the new subject namespace.
        cs = get_content_store()
        if spec.name == "raw_file" and isinstance(new_id, int):
            subject_scope = build_subject_storage_scope(user_id=user_id, subject=new_slug)
            ext = instance.filetype if instance.filetype.startswith(".") else f".{instance.filetype}"
            instance.file_path = subject_scope.raw_file_key(new_id, ext)
            instance.markdown_path = subject_scope.raw_markdown_key(new_id)
            instance.asset_dir = subject_scope.asset_prefix(new_id).rstrip("/")
            instance.storage_backend = "s3" if is_cloud_mode() else "local"
        elif spec.name == "knowledge_document" and isinstance(new_id, int):
            subject_scope = build_subject_storage_scope(user_id=user_id, subject=new_slug)
            chapter_index = max(1, int(instance.chapter_index or 1))
            safe_title = sanitize_doc_title(instance.title or f"chapter_{chapter_index}")
            instance.markdown_path = subject_scope.knowledge_doc_key(
                f"chapter_{chapter_index:02d}_{safe_title}.md"
            )

        if old_id is not None:
            table_id_map[old_id] = new_id

        if self_fk_fields:
            pending_self_refs.append((instance, old_self_refs, old_id))

    for instance, old_refs, old_id in pending_self_refs:
        for fk_field, old_fk in old_refs.items():
            if old_fk is None:
                continue
            new_fk = _lookup_mapped_id(old_fk, table_id_map)
            if new_fk is None:
                warnings.append(f"{spec.name}.{fk_field}: ref {old_fk} not found in {spec.name}")
                continue
            setattr(instance, fk_field, new_fk)
        session.add(instance)

    if pending_self_refs:
        session.flush()

    return len(table_id_map)


def _lookup_mapped_id(old_id: Any, ref_map: dict[Any, Any]) -> Any | None:
    new_id = ref_map.get(old_id)
    if new_id is None and isinstance(old_id, str) and old_id.isdigit():
        new_id = ref_map.get(int(old_id))
    if new_id is None and isinstance(old_id, int):
        new_id = ref_map.get(str(old_id))
    return new_id


def _remap_fk(
    record: dict,
    fk_field: str,
    ref_table: str,
    id_map: dict[str, dict[Any, Any]],
    table_name: str,
    warnings: list[str],
) -> None:
    old_fk = record.get(fk_field)
    if old_fk is None:
        return
    ref_map = id_map.get(ref_table)
    if ref_map is None:
        record[fk_field] = None
        return
    new_fk = _lookup_mapped_id(old_fk, ref_map)
    if new_fk is not None:
        record[fk_field] = new_fk
    else:
        record[fk_field] = None
        warnings.append(f"{table_name}.{fk_field}: ref {old_fk} not found in {ref_table}")


def _remap_id_list_field(
    record: dict,
    field_name: str,
    ref_table: str,
    id_map: dict[str, dict[Any, Any]],
    table_name: str,
    warnings: list[str],
) -> None:
    values = record.get(field_name)
    if not isinstance(values, list):
        record[field_name] = []
        return

    ref_map = id_map.get(ref_table) or {}
    remapped: list[Any] = []
    for old_id in values:
        new_id = _lookup_mapped_id(old_id, ref_map)
        if new_id is None:
            warnings.append(f"{table_name}.{field_name}: ref {old_id} not found in {ref_table}")
            continue
        remapped.append(new_id)
    record[field_name] = remapped


# ===================================================================
# Internal: file packing and unpacking
# ===================================================================


def _pack_files(zf: zipfile.ZipFile, namespace: str, options: ExportOptions) -> None:
    """Read files from ContentStore and pack them into the zip archive."""
    cs = get_content_store()
    skip_filenames = {
        ".build.lock",
        "build_status.json",
        "chunk_manifest.json",
        "manifest.json",
        "node_embedding_cache.json",
    }

    def _pack_prefix(prefix: str, arc_prefix: str) -> None:
        keys = run_store_sync(cs.list_prefix, prefix, default=[])
        for key in keys:
            relative = key[len(prefix):] if key.startswith(prefix) else key.rsplit("/", 1)[-1]
            data = run_store_sync(cs.read_bytes, key, default=None)
            if data is not None:
                zf.writestr(f"{arc_prefix}/{relative}", data)

    if options.include_raw_files:
        _pack_prefix(f"{namespace}/raw_files/", "files/raw_files")
        _pack_prefix(f"{namespace}/assets/", "files/assets")
    if options.include_raw_markdowns:
        _pack_prefix(f"{namespace}/raw_markdowns/", "files/raw_markdowns")

    # knowledge markdowns
    if options.include_knowledge_docs:
        keys = run_store_sync(cs.list_prefix, f"{namespace}/knowledge_markdowns/", default=[])
        for key in keys:
            prefix = f"{namespace}/knowledge_markdowns/"
            relative = key[len(prefix):] if key.startswith(prefix) else key.rsplit("/", 1)[-1]
            filename = relative.rsplit("/", 1)[-1]
            if (
                filename in skip_filenames
                or relative.startswith("_build/")
                or relative.startswith("versions/")
                or "/" in relative
            ):
                continue
            data = run_store_sync(cs.read_bytes, key, default=None)
            if data is not None:
                zf.writestr(f"knowledge/{filename}", data)
# ===================================================================
# Internal: Manifest
# ===================================================================


def _build_manifest(
    subject: Subject,
    exported: dict[str, list[dict]],
    options: ExportOptions,
) -> _ExportManifest:
    return _ExportManifest(
        app_version=get_app_version(),
        exported_at=utcnow(),
        subject=_ManifestSubject(
            slug=subject.slug,
            name=subject.name,
        ),
        stats=_ManifestStats(
            raw_file_count=len(exported.get("raw_file", [])),
            knowledge_document_count=len(exported.get("knowledge_document", [])),
            knowledge_unit_count=len(exported.get("knowledge_unit", [])),
            knowledge_edge_count=len(exported.get("knowledge_edge", [])),
            confirmed_build_plan_count=len(exported.get("confirmed_build_plan", [])),
            question_type_registry_count=len(exported.get("question_type_registry", [])),
            question_template_count=len(exported.get("question_template", [])),
            exam_paper_count=len(exported.get("exam_paper", [])),
            chat_session_count=len(exported.get("chat_session", [])),
        ),
        options=options,
    )


def _read_manifest(extract_dir: Path) -> _ExportManifest:
    manifest_path = extract_dir / "manifest.json"
    if not manifest_path.exists():
        raise ValueError("Invalid .atmx file: missing manifest.json")
    manifest = _ExportManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if manifest.format_version not in SUPPORTED_FORMAT_VERSIONS:
        raise ValueError(
            f"Unsupported format version: {manifest.format_version}. "
            f"Supported: {SUPPORTED_FORMAT_VERSIONS}"
        )
    return manifest
