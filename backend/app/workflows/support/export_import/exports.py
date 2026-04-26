"""Subject-level export/import support commands.

The table registry drives export/import order and foreign-key remapping.
"""

from __future__ import annotations

import json
import mimetypes
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field
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
    SubjectFileLink,
    Subject,
    UserKnowledgeState,
)
from app.repositories.files_repo import list_all_raw_files_by_subject
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
MANIFEST_SCHEMA = "aiteachme.atmx.manifest"
PACKAGE_KIND = "subject_export"


# ---------------------------------------------------------------------------
# Manifest 内部模型（仅用于 .atmx 文件，不走 API）


class _ManifestSubject(BaseModel):
    model_config = ConfigDict(extra="allow")

    slug: str
    name: str
    description: str = ""
    user_intent: str = ""
    icon_key: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class _ManifestStats(BaseModel):
    model_config = ConfigDict(extra="allow")

    raw_file_count: int = 0
    knowledge_document_count: int = 0
    knowledge_unit_count: int = 0
    knowledge_edge_count: int = 0
    confirmed_build_plan_count: int = 0
    question_type_registry_count: int = 0
    question_template_count: int = 0
    exam_paper_count: int = 0
    chat_session_count: int = 0
    user_knowledge_state_count: int = 0
    total_file_size_bytes: int = 0


class _ManifestPackage(BaseModel):
    model_config = ConfigDict(extra="allow")

    package_id: str
    kind: str = PACKAGE_KIND
    manifest_schema: str = MANIFEST_SCHEMA
    content_roots: list[str] = Field(default_factory=lambda: ["db", "files", "knowledge"])
    capabilities: list[str] = Field(default_factory=list)
    min_reader_format_version: str = "1.0"


class _ManifestTable(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    count: int = 0
    optional_group: str | None = None
    id_type: str = "auto"
    subject_field: str | None = None


class _ExportManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    format_version: str = "1.0"
    app_version: str = ""
    exported_at: datetime | None = None
    exporter: str = "AITeachMe"
    package: _ManifestPackage = Field(default_factory=lambda: _ManifestPackage(package_id="legacy"))
    subject: _ManifestSubject
    stats: _ManifestStats = Field(default_factory=_ManifestStats)
    options: ExportOptions = Field(default_factory=ExportOptions)
    tables: list[_ManifestTable] = Field(default_factory=list)
    extensions: dict[str, Any] = Field(default_factory=dict)


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
    # Optional export group: "raw_file_metadata" | "raw_markdowns" |
    # "knowledge_docs" | "chat" | "exam" | "profile" | None (always export)
    optional_group: str | None = None


# Tables must be ordered by dependency: referenced tables come first.
TABLE_REGISTRY: list[_TableSpec] = [
    _TableSpec("subject", Subject, subject_field="slug"),
    _TableSpec("raw_file", RawFile, optional_group="raw_file_metadata"),
    _TableSpec(
        "subject_file",
        SubjectFileLink,
        fk_remap={"raw_file_id": "raw_file"},
        optional_group="raw_file_metadata",
    ),
    _TableSpec(
        "retrieval_chunk",
        RetrievalChunk,
        fk_remap={"document_id": "raw_file"},
        optional_group="raw_markdowns",
    ),
    _TableSpec(
        "knowledge_document",
        KnowledgeDocument,
        fk_remap={
            "root_document_id": "knowledge_document",
            "parent_document_id": "knowledge_document",
        },
        optional_group="knowledge_docs",
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
        optional_group="knowledge_docs",
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


def preview_export(
    session: Session,
    *,
    subject_slug: str,
    options: ExportOptions | None = None,
) -> ExportPreviewData:
    """Build an export preview for one subject."""

    options = options or ExportOptions()
    subject = _require_subject(session, subject_slug)
    raw_files = list_all_raw_files_by_subject(session, subject_slug)

    stats = ExportPreviewStats(
        raw_file_count=len(raw_files) if _exports_raw_file_metadata(options) else 0,
        total_raw_file_size_bytes=0,
        knowledge_document_count=_count(session, KnowledgeDocument, subject_slug)
        if options.include_knowledge_docs
        else 0,
        knowledge_unit_count=_count(session, KnowledgeUnit, subject_slug),
        knowledge_edge_count=_count(session, KnowledgeEdge, subject_slug),
        confirmed_build_plan_count=_count(session, ConfirmedBuildPlan, subject_slug)
        if options.include_knowledge_docs
        else 0,
        question_type_registry_count=_count(session, QuestionTypeRegistry, subject_slug)
        if options.include_exam_history
        else 0,
        question_template_count=_count(session, QuestionTemplate, subject_slug)
        if options.include_exam_history
        else 0,
        exam_paper_count=_count(session, ExamPaper, subject_slug) if options.include_exam_history else 0,
        chat_session_count=_count(session, ChatSession, subject_slug) if options.include_chat_history else 0,
        user_knowledge_state_count=_count(session, UserKnowledgeState, subject_slug)
        if options.include_profile
        else 0,
    )
    return ExportPreviewData(
        subject_id=subject.slug,
        subject_name=subject.name,
        stats=stats,
        estimated_size_bytes=0,
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

            raw_files = list_all_raw_files_by_subject(session, subject_slug)
            _pack_files(zf, subject_scope.namespace, options, raw_files=raw_files)

            manifest = _build_manifest(subject, exported, options)
            zf.writestr("manifest.json", manifest.model_dump_json(indent=2))

        logger.info("subject_exported", subject=subject_slug, path=str(tmp_path))
        return tmp_path

    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def build_subject_export_filename(subject: Subject) -> str:
    """Build a readable download filename anchored by subject name and id."""

    name = sanitize_doc_title(subject.name or "未命名学科")
    subject_id = sanitize_doc_title(subject.slug or str(subject.id or "subject"))
    return f"{name}-{subject_id}.atmx"
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
        "raw_file_metadata": _exports_raw_file_metadata(options),
        "raw_markdowns": options.include_raw_markdowns,
        "knowledge_docs": options.include_knowledge_docs,
        "chat": options.include_chat_history,
        "exam": options.include_exam_history,
        "profile": options.include_profile,
    }.get(spec.optional_group, True)


def _exports_raw_file_metadata(options: ExportOptions) -> bool:
    return options.include_raw_markdowns


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

    if spec.name == "raw_file":
        rows = list_all_raw_files_by_subject(session, subject_slug)
    elif spec.subject_field == "slug":
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
    imported_at = utcnow()

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
            record_data["created_at"] = imported_at
            record_data["updated_at"] = imported_at
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
            record_data["uid"] = f"file_{uuid.uuid4().hex}"  # Prevent unique-constraint conflicts
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
            instance.file_path = subject_scope.raw_file_key(
                file_uid=instance.uid,
                filename=instance.filename,
                extension=ext,
            )
            instance.markdown_path = subject_scope.raw_markdown_key(
                file_uid=instance.uid,
                filename=instance.filename,
            )
            instance.asset_dir = subject_scope.asset_prefix(
                file_uid=instance.uid,
                filename=instance.filename,
            ).rstrip("/")
            instance.storage_backend = "s3" if is_cloud_mode() else "local"
        elif spec.name == "knowledge_document" and isinstance(new_id, int):
            instance.markdown_path = None

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


def _pack_files(
    zf: zipfile.ZipFile,
    namespace: str,
    options: ExportOptions,
    *,
    raw_files: list[RawFile],
) -> None:
    """Read files from ContentStore and pack them into the zip archive."""
    cs = get_content_store()

    def _pack_latest_docgen_cover() -> None:
        cover_keys = run_store_sync(cs.list_prefix, f"{namespace}/assets/docgen/", default=[]) or []
        latest_cover_key = next(
            (
                key
                for key in sorted(cover_keys)
                if key.rsplit("/", 1)[-1].startswith("cover.")
            ),
            "",
        )
        for key in sorted(cover_keys, reverse=True):
            if latest_cover_key:
                break
            filename = key.rsplit("/", 1)[-1]
            if filename.startswith("docgen_cover_"):
                latest_cover_key = key
                break
        if not latest_cover_key:
            return
        data = run_store_sync(cs.read_bytes, latest_cover_key, default=None)
        if data is None:
            return
        guessed_type, _ = mimetypes.guess_type(latest_cover_key)
        extension = mimetypes.guess_extension(guessed_type or "") or Path(latest_cover_key).suffix or ".png"
        zf.writestr(f"knowledge/cover{extension}", data)

    # KnowledgeDocument rows already carry the published markdown content. The package only
    # needs non-DB docgen assets such as the cover image.
    if options.include_knowledge_docs:
        _pack_latest_docgen_cover()
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
        package=_ManifestPackage(
            package_id=f"atmx_{uuid.uuid4().hex}",
            capabilities=_manifest_capabilities(options),
        ),
        subject=_ManifestSubject(
            slug=subject.slug,
            name=subject.name,
            description=subject.description,
            user_intent=subject.user_intent,
            icon_key=normalize_subject_icon_key(
                _decode_settings_json(subject.settings_json).get(SUBJECT_ICON_SETTINGS_KEY)
            ),
            created_at=subject.created_at,
            updated_at=subject.updated_at,
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
            user_knowledge_state_count=len(exported.get("user_knowledge_state", [])),
            total_file_size_bytes=0,
        ),
        options=options,
        tables=_build_manifest_tables(exported),
    )


def _manifest_capabilities(options: ExportOptions) -> list[str]:
    capabilities = ["subject_metadata", "knowledge_graph"]
    if _exports_raw_file_metadata(options):
        capabilities.append("raw_file_metadata")
    if options.include_raw_markdowns:
        capabilities.append("raw_markdowns")
    if options.include_knowledge_docs:
        capabilities.append("knowledge_docs")
    if options.include_chat_history:
        capabilities.append("chat_history")
    if options.include_exam_history:
        capabilities.append("exam_history")
    if options.include_profile:
        capabilities.append("profile")
    return capabilities


def _build_manifest_tables(exported: dict[str, list[dict]]) -> list[_ManifestTable]:
    spec_by_name = {spec.name: spec for spec in TABLE_REGISTRY}
    tables: list[_ManifestTable] = []
    for name, records in exported.items():
        spec = spec_by_name.get(name)
        tables.append(
            _ManifestTable(
                name=name,
                count=len(records),
                optional_group=spec.optional_group if spec else None,
                id_type=spec.id_type if spec else "auto",
                subject_field=spec.subject_field if spec else None,
            )
        )
    return tables


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
