"""Course-level export/import support commands.

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
    build_course_storage_scope,
    get_content_store,
    run_store_sync,
)
from app.models import (
    ChatMessage,
    ChatSession,
    ExamPaper,
    ExamPaperItem,
    KnowledgeDocument,
    KnowledgeEdge,
    KnowledgeGraphSourceRef,
    KnowledgeGraphSyncRun,
    KnowledgeUnit,
    QuestionKnowledgeUnitLink,
    QuestionTypeRegistry,
    QuestionTemplate,
    RawFile,
    RetrievalChunk,
    CourseFileLink,
    Course,
    UserKnowledgeState,
)
from app.repositories.files_repo import list_all_raw_files_by_course
from app.schemas.export_import import (
    ExportOptions,
    ExportPreviewData,
    ExportPreviewStats,
)
from app.utils.path_helpers import sanitize_doc_title
from app.utils.course import generate_course_id
from app.utils.time import utcnow
from app.workflows.support.courses.icons import (
    COURSE_ICON_SETTINGS_KEY,
    infer_course_icon_key,
    normalize_course_icon_key,
)

logger = structlog.get_logger()

SUPPORTED_FORMAT_VERSIONS = {"1.0"}
MANIFEST_SCHEMA = "aiteachme.atmx.manifest"
PACKAGE_KIND = "course_export"


# ---------------------------------------------------------------------------
# Manifest 内部模型（仅用于 .atmx 文件，不走 API）


class _ManifestCourse(BaseModel):
    model_config = ConfigDict(extra="allow")

    course_id: str
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
    knowledge_graph_sync_run_count: int = 0
    knowledge_graph_source_ref_count: int = 0
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
    course_field: str | None = None


class _ExportManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    format_version: str = "1.0"
    app_version: str = ""
    exported_at: datetime | None = None
    exporter: str = "AITeachMe"
    package: _ManifestPackage = Field(default_factory=lambda: _ManifestPackage(package_id="legacy"))
    course: _ManifestCourse
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
    # How to filter by course: field name | "id" (Course itself) | None (filter via parent table)
    course_field: str | None = "course_id"
    id_field: str = "id"
    # id 类型："auto" (自增) | "uuid" (字符串 UUID)
    id_type: str = "auto"
    # Foreign-key remapping: {field_name: referenced_table_name}
    fk_remap: dict[str, str] = dc_field(default_factory=dict)
    # Filter via parent table (for tables without a course field)
    parent_fk: str | None = None
    parent_table: str | None = None
    # Optional export group: "raw_file_metadata" | "raw_markdowns" |
    # "knowledge_docs" | "chat" | "exam" | "profile" | None (always export)
    optional_group: str | None = None


# Tables must be ordered by dependency: referenced tables come first.
TABLE_REGISTRY: list[_TableSpec] = [
    _TableSpec("course", Course, course_field="id"),
    _TableSpec("raw_file", RawFile, course_field=None, optional_group="raw_file_metadata"),
    _TableSpec(
        "course_file",
        CourseFileLink,
        fk_remap={"file_id": "raw_file"},
        optional_group="raw_file_metadata",
    ),
    _TableSpec(
        "retrieval_chunk",
        RetrievalChunk,
        fk_remap={"file_id": "raw_file"},
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
    _TableSpec("knowledge_graph_sync_run", KnowledgeGraphSyncRun),
    _TableSpec(
        "knowledge_graph_source_ref",
        KnowledgeGraphSourceRef,
        fk_remap={
            "sync_run_id": "knowledge_graph_sync_run",
            "knowledge_document_id": "knowledge_document",
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
        course_field=None,
        parent_fk="exam_paper_id",
        parent_table="exam_paper",
        fk_remap={
            "exam_paper_id": "exam_paper",
            "question_template_id": "question_template",
        },
        optional_group="exam",
    ),
    _TableSpec(
        "question_knowledge_unit_link",
        QuestionKnowledgeUnitLink,
        course_field=None,
        fk_remap={
            "question_template_id": "question_template",
            "exam_paper_item_id": "exam_paper_item",
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
    course_id: str,
    options: ExportOptions | None = None,
) -> ExportPreviewData:
    """Build an export preview for one course."""

    options = options or ExportOptions()
    course = _require_course(session, course_id)
    raw_files = list_all_raw_files_by_course(session, course_id)

    stats = ExportPreviewStats(
        raw_file_count=len(raw_files) if _exports_raw_file_metadata(options) else 0,
        total_raw_file_size_bytes=0,
        knowledge_document_count=_count(session, KnowledgeDocument, course_id)
        if options.include_knowledge_docs
        else 0,
        knowledge_unit_count=_count(session, KnowledgeUnit, course_id),
        knowledge_edge_count=_count(session, KnowledgeEdge, course_id),
        knowledge_graph_sync_run_count=_count(session, KnowledgeGraphSyncRun, course_id),
        knowledge_graph_source_ref_count=_count(session, KnowledgeGraphSourceRef, course_id),
        confirmed_build_plan_count=_count_embedded_confirmed_plans(session, course_id)
        if options.include_knowledge_docs
        else 0,
        question_type_registry_count=_count(session, QuestionTypeRegistry, course_id)
        if options.include_exam_history
        else 0,
        question_template_count=_count(session, QuestionTemplate, course_id)
        if options.include_exam_history
        else 0,
        exam_paper_count=_count(session, ExamPaper, course_id) if options.include_exam_history else 0,
        chat_session_count=_count(session, ChatSession, course_id)
        if options.include_chat_history
        else (
            _count_planner_sessions_with_embedded_plans(session, course_id)
            if options.include_knowledge_docs
            else 0
        ),
        user_knowledge_state_count=_count(session, UserKnowledgeState, course_id)
        if options.include_profile
        else 0,
    )
    return ExportPreviewData(
        course_id=course.id,
        course_name=course.name,
        stats=stats,
        estimated_size_bytes=0,
    )


def export_course(
    session: Session,
    *,
    course_id: str,
    options: ExportOptions | None = None,
) -> Path:
    """Package one course into a temporary .atmx archive."""

    options = options or ExportOptions()
    course = _require_course(session, course_id)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".atmx")
    tmp.close()
    tmp_path = Path(tmp.name)

    try:
        course_scope = build_course_storage_scope(user_id=course.user_id, course_id=course.id)
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            exported: dict[str, list[dict]] = {}

            for spec in TABLE_REGISTRY:
                if not _should_export(spec, options):
                    continue
                records = _query_table(session, spec, course_id, exported, options)
                exported[spec.name] = records
                zf.writestr(
                    f"db/{spec.name}.json",
                    json.dumps(
                        {"table": spec.name, "count": len(records), "records": records},
                        ensure_ascii=False, indent=2, default=str,
                    ),
                )

            raw_files = list_all_raw_files_by_course(session, course_id)
            _pack_files(zf, course_scope.namespace, options, raw_files=raw_files)

            manifest = _build_manifest(course, exported, options)
            zf.writestr("manifest.json", manifest.model_dump_json(indent=2))

        logger.info("course_exported", course_id=course_id, course_name=course.name, path=str(tmp_path))
        return tmp_path

    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def build_course_export_filename(course: Course) -> str:
    """Build a readable download filename anchored by course name and id."""

    name = sanitize_doc_title(course.name or "未命名课程")
    course_id_stem = sanitize_doc_title(course.id or str(course.id or "course"))
    return f"{name}-{course_id_stem}.atmx"
# ===================================================================
# Internal: DB helpers
# ===================================================================


def _require_course(session: Session, course_id: str) -> Course:
    from app.shared.infra.exceptions import CourseRegistryNotFoundError

    course = session.exec(select(Course).where(Course.id == course_id)).first()
    if course is None:
        raise CourseRegistryNotFoundError(course_id)
    return course


def _count(session: Session, model: type, course_id: str) -> int:
    return int(
        session.exec(
            select(func.count()).select_from(model).where(model.course_id == course_id)
        ).one()
    )


def _has_embedded_confirmed_plan(record: ChatSession | dict[str, Any]) -> bool:
    meta = record.get("meta_json") if isinstance(record, dict) else record.meta_json
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    return isinstance((meta or {}).get("confirmed_plan"), dict)


def _count_planner_sessions_with_embedded_plans(session: Session, course_id: str) -> int:
    rows = session.exec(
        select(ChatSession).where(
            ChatSession.course_id == course_id,
            ChatSession.source == "build_planner",
        )
    ).all()
    return sum(1 for row in rows if _has_embedded_confirmed_plan(row))


def _count_embedded_confirmed_plans(session: Session, course_id: str) -> int:
    return _count_planner_sessions_with_embedded_plans(session, course_id)


def _should_export(spec: _TableSpec, options: ExportOptions) -> bool:
    if spec.name == "chat_session" and options.include_knowledge_docs:
        return True
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
    course_id: str,
    exported: dict[str, list[dict]],
    options: ExportOptions,
) -> list[dict]:
    def _ordered(stmt):
        order_col = getattr(spec.model, spec.id_field, None)
        if order_col is None:
            return stmt
        return stmt.order_by(order_col)

    if spec.name == "raw_file":
        rows = list_all_raw_files_by_course(session, course_id)
    elif spec.name == "chat_session" and not options.include_chat_history:
        rows = session.exec(
            _ordered(
                select(ChatSession).where(
                    ChatSession.course_id == course_id,
                    ChatSession.source == "build_planner",
                )
            )
        ).all()
        rows = [row for row in rows if _has_embedded_confirmed_plan(row)]
    elif spec.course_field == "id":
        rows = session.exec(_ordered(select(spec.model).where(spec.model.id == course_id))).all()
    elif spec.course_field:
        col = getattr(spec.model, spec.course_field)
        rows = session.exec(_ordered(select(spec.model).where(col == course_id))).all()
    elif spec.name == "question_knowledge_unit_link":
        template_ids = {r["id"] for r in exported.get("question_template", [])}
        item_ids = {r["id"] for r in exported.get("exam_paper_item", [])}
        predicates = []
        if template_ids:
            predicates.append(QuestionKnowledgeUnitLink.question_template_id.in_(template_ids))
        if item_ids:
            predicates.append(QuestionKnowledgeUnitLink.exam_paper_item_id.in_(item_ids))
        if not predicates:
            return []
        stmt = select(QuestionKnowledgeUnitLink)
        if len(predicates) == 1:
            stmt = stmt.where(predicates[0])
        else:
            from sqlalchemy import or_

            stmt = stmt.where(or_(*predicates))
        rows = session.exec(_ordered(stmt)).all()
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


def _prepare_imported_course_settings(record_data: dict[str, Any], course_name: str) -> None:
    settings = _decode_settings_json(record_data.get("settings_json"))
    embedding = settings.get("embedding")
    if isinstance(embedding, dict) and embedding.get("mode") == "enabled":
        # The package does not include vector rows, so enabled bindings must be rebuilt.
        settings.pop("embedding", None)
    if normalize_course_icon_key(settings.get(COURSE_ICON_SETTINGS_KEY)) is None:
        settings[COURSE_ICON_SETTINGS_KEY] = infer_course_icon_key(course_name)
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


def _create_unique_course_id(session: Session) -> str:
    for _ in range(100):
        course_id = generate_course_id()
        if session.exec(select(Course).where(Course.id == course_id)).first() is None:
            return course_id
    raise RuntimeError("Cannot generate unique course id after 100 attempts")


def _find_existing_raw_file_for_import(
    session: Session,
    record_data: dict[str, Any],
    *,
    user_id: str,
) -> RawFile | None:
    """Return an existing user library file matching the imported raw file."""

    if str(record_data.get("status") or "").strip().lower() == "failed":
        return None

    content_hash = str(record_data.get("content_hash") or "").strip()
    filetype = str(record_data.get("filetype") or "").strip().lstrip(".").lower()
    parse_signature = str(record_data.get("parse_request_signature") or "default").strip() or "default"
    try:
        file_size = int(record_data.get("file_size_bytes"))
    except (TypeError, ValueError):
        return None

    if not content_hash or not filetype or file_size < 0:
        return None

    record_data["filetype"] = filetype
    record_data["parse_request_signature"] = parse_signature
    record_data["file_size_bytes"] = file_size

    return session.exec(
        select(RawFile)
        .where(
            RawFile.user_id == user_id,
            RawFile.content_hash == content_hash,
            RawFile.file_size_bytes == file_size,
            RawFile.filetype == filetype,
            RawFile.parse_request_signature == parse_signature,
            RawFile.status != "failed",
        )
        .order_by(RawFile.updated_at.desc())
    ).first()


def _import_table(
    session: Session,
    spec: _TableSpec,
    records: list[dict],
    *,
    id_map: dict[str, dict[Any, Any]],
    new_course_id: str,
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
        legacy_uid = record_data.get("uid") if spec.name == "raw_file" else None
        old_self_refs = {field: record_data.get(field) for field in self_fk_fields}

        # 新 ID
        if spec.id_type == "auto":
            record_data[spec.id_field] = None
        elif spec.id_type == "uuid":
            record_data[spec.id_field] = str(uuid.uuid4())

        # 更新 course
        if spec.name == "course":
            record_data["id"] = new_course_id
            record_data["name"] = new_name
            record_data["normalized_name"] = None
            record_data["created_at"] = imported_at
            record_data["updated_at"] = imported_at
            _prepare_imported_course_settings(record_data, new_name)
        elif spec.course_field and spec.course_field != "id":
            record_data[spec.course_field] = new_course_id

        # 更新 user_id
        if "user_id" in record_data:
            record_data["user_id"] = user_id

        if spec.name == "course_file":
            legacy_raw_file_id = record_data.pop("raw_file_id", None)
            if "file_id" not in record_data and legacy_raw_file_id is not None:
                record_data["file_id"] = legacy_raw_file_id
        if spec.name == "retrieval_chunk":
            legacy_document_id = record_data.pop("document_id", None)
            if "file_id" not in record_data and legacy_document_id is not None:
                record_data["file_id"] = legacy_document_id

        if spec.name == "raw_file":
            existing_raw_file = _find_existing_raw_file_for_import(
                session,
                record_data,
                user_id=user_id,
            )
            if existing_raw_file is not None:
                if old_id is not None:
                    table_id_map[old_id] = existing_raw_file.id
                if legacy_uid is not None:
                    table_id_map[legacy_uid] = existing_raw_file.id
                filename = str(record_data.get("filename") or existing_raw_file.filename or "同一份资料")
                warnings.append(f"资料库已存在 {filename}，本次导入已复用已有解析结果。")
                logger.info(
                    "course_import_raw_file_reused",
                    old_id=old_id,
                    file_id=existing_raw_file.id,
                    user_id=user_id,
                )
                continue

        # Remap foreign keys after the referenced tables have been imported.
        for fk_field, ref_table in spec.fk_remap.items():
            if fk_field in self_fk_fields:
                record_data[fk_field] = None
                continue
            _remap_fk(record_data, fk_field, ref_table, id_map, spec.name, warnings)

        if spec.name == "chat_session":
            _remap_planner_meta(record_data, new_course_id=new_course_id, user_id=user_id, id_map=id_map, warnings=warnings)
        elif spec.name == "knowledge_document":
            _remap_optional_json_id_list_text_field(
                record_data,
                "source_file_ids",
                "raw_file",
                id_map,
            )
        elif spec.name == "knowledge_graph_source_ref":
            _remap_graph_source_ref_entity(record_data, id_map, warnings)
            _remap_json_int_list_text_field(
                record_data,
                "source_file_ids_json",
                "raw_file",
                id_map,
                spec.name,
                warnings,
            )

        # Clear absolute-path fields so they can be rebuilt during import
        if spec.name == "raw_file":
            record_data.pop("uid", None)
        if spec.name == "raw_file":
            record_data["id"] = f"file_{uuid.uuid4().hex}"  # Prevent identity conflicts
            record_data["origin_course_id"] = new_course_id
            record_data["origin_course_name"] = new_name
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

        # Rebuild storage keys under the new course namespace.
        cs = get_content_store()
        if spec.name == "raw_file" and isinstance(new_id, str):
            file_scope = cs.user_file_scope(user_id=user_id)
            ext = instance.filetype if instance.filetype.startswith(".") else f".{instance.filetype}"
            instance.file_path = file_scope.raw_file_key(
                file_id=instance.id,
                filename=instance.filename,
                extension=ext,
            )
            instance.markdown_path = file_scope.raw_markdown_key(
                file_id=instance.id,
                filename=instance.filename,
            )
            instance.asset_dir = file_scope.asset_prefix(
                file_id=instance.id,
                filename=instance.filename,
            ).rstrip("/")
            instance.storage_backend = "s3" if is_cloud_mode() else "local"
        elif spec.name == "knowledge_document" and isinstance(new_id, int):
            instance.markdown_path = None

        if old_id is not None:
            table_id_map[old_id] = new_id
        if spec.name == "raw_file" and legacy_uid is not None:
            table_id_map[legacy_uid] = new_id

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


def _remap_json_int_list_text_field(
    record: dict,
    field_name: str,
    ref_table: str,
    id_map: dict[str, dict[Any, Any]],
    table_name: str,
    warnings: list[str],
) -> None:
    try:
        values = json.loads(str(record.get(field_name) or "[]"))
    except Exception:
        values = []
    if not isinstance(values, list):
        values = []

    ref_map = id_map.get(ref_table) or {}
    remapped: list[Any] = []
    for old_id in values:
        new_id = _lookup_mapped_id(old_id, ref_map)
        if new_id is None:
            warnings.append(f"{table_name}.{field_name}: ref {old_id} not found in {ref_table}")
            continue
        remapped.append(new_id)
    record[field_name] = json.dumps(remapped, ensure_ascii=False)


def _remap_optional_json_id_list_text_field(
    record: dict,
    field_name: str,
    ref_table: str,
    id_map: dict[str, dict[Any, Any]],
) -> None:
    """Remap optional source-id metadata without leaking ids from the source course."""

    if ref_table not in id_map:
        record[field_name] = "[]"
        return
    try:
        values = json.loads(str(record.get(field_name) or "[]"))
    except Exception:
        values = []
    if not isinstance(values, list):
        values = []

    ref_map = id_map.get(ref_table) or {}
    remapped = [
        new_id
        for old_id in values
        if (new_id := _lookup_mapped_id(old_id, ref_map)) is not None
    ]
    record[field_name] = json.dumps(remapped, ensure_ascii=False)


def _remap_planner_meta(
    record: dict,
    *,
    new_course_id: str,
    user_id: str,
    id_map: dict[str, dict[Any, Any]],
    warnings: list[str],
) -> None:
    raw_meta = record.get("meta_json") or {}
    if isinstance(raw_meta, str):
        try:
            raw_meta = json.loads(raw_meta)
        except Exception:
            raw_meta = {}
    meta = dict(raw_meta or {}) if isinstance(raw_meta, dict) else {}
    if not meta:
        return

    if "selected_file_ids" in meta:
        _remap_id_list_field(meta, "selected_file_ids", "raw_file", id_map, "chat_session.meta_json", warnings)

    plan_id_map: dict[str, str] = {}

    def remap_confirmed_plan(confirmed_plan: dict[str, Any]) -> dict[str, Any]:
        confirmed_plan = dict(confirmed_plan)
        old_plan_id = str(confirmed_plan.get("id") or uuid.uuid4().hex)
        confirmed_plan["id"] = plan_id_map.setdefault(old_plan_id, str(uuid.uuid4().hex))
        confirmed_plan["course_id"] = new_course_id
        confirmed_plan["course"] = new_course_id
        confirmed_plan["user_id"] = user_id
        confirmed_plan["planner_session_id"] = str(record.get("id") or "")
        _remap_id_list_field(
            confirmed_plan,
            "selected_file_ids_json",
            "raw_file",
            id_map,
            "chat_session.meta_json.confirmed_plan",
            warnings,
        )
        plan_json = confirmed_plan.get("plan_json")
        if isinstance(plan_json, dict):
            plan_json = dict(plan_json)
            plan_json["course_id"] = new_course_id
            plan_json["course"] = new_course_id
            plan_json["selected_file_ids"] = list(confirmed_plan.get("selected_file_ids_json") or [])
            plan_json["planner_session_id"] = confirmed_plan["planner_session_id"]
            plan_json["confirmed_plan_id"] = confirmed_plan["id"]
            confirmed_plan["plan_json"] = plan_json
        return confirmed_plan

    history = meta.get("confirmed_plan_history")
    if isinstance(history, list):
        remapped_history = [
            remap_confirmed_plan(item)
            for item in history
            if isinstance(item, dict)
        ]
        if remapped_history:
            meta["confirmed_plan_history"] = remapped_history

    confirmed_plan = meta.get("confirmed_plan")
    if not isinstance(confirmed_plan, dict):
        record["meta_json"] = meta
        return

    confirmed_plan = remap_confirmed_plan(confirmed_plan)
    meta["confirmed_plan_id"] = confirmed_plan["id"]
    meta["confirmed_plan"] = confirmed_plan
    if isinstance(meta.get("confirmed_plan_history"), list):
        history_ids = {
            str(item.get("id") or "")
            for item in meta["confirmed_plan_history"]
            if isinstance(item, dict)
        }
        if confirmed_plan["id"] not in history_ids:
            meta["confirmed_plan_history"].append(confirmed_plan)
    else:
        meta["confirmed_plan_history"] = [confirmed_plan]
    record["meta_json"] = meta


def _remap_graph_source_ref_entity(
    record: dict,
    id_map: dict[str, dict[Any, Any]],
    warnings: list[str],
) -> None:
    entity_type = str(record.get("entity_type") or "").strip()
    ref_table = "knowledge_unit" if entity_type == "unit" else "knowledge_edge" if entity_type == "edge" else ""
    if not ref_table:
        record["entity_id"] = 0
        warnings.append(f"knowledge_graph_source_ref.entity_id: unsupported entity_type {entity_type!r}")
        return
    _remap_fk(record, "entity_id", ref_table, id_map, "knowledge_graph_source_ref", warnings)


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
    course: Course,
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
        course=_ManifestCourse(
            course_id=course.id,
            name=course.name,
            description=course.description,
            user_intent=course.user_intent,
            icon_key=normalize_course_icon_key(
                _decode_settings_json(course.settings_json).get(COURSE_ICON_SETTINGS_KEY)
            ),
            created_at=course.created_at,
            updated_at=course.updated_at,
        ),
        stats=_ManifestStats(
            raw_file_count=len(exported.get("raw_file", [])),
            knowledge_document_count=len(exported.get("knowledge_document", [])),
            knowledge_unit_count=len(exported.get("knowledge_unit", [])),
            knowledge_edge_count=len(exported.get("knowledge_edge", [])),
            knowledge_graph_sync_run_count=len(exported.get("knowledge_graph_sync_run", [])),
            knowledge_graph_source_ref_count=len(exported.get("knowledge_graph_source_ref", [])),
            confirmed_build_plan_count=sum(
                1
                for record in exported.get("chat_session", [])
                if _has_embedded_confirmed_plan(record)
            ),
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
    capabilities = ["course_metadata", "knowledge_graph"]
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
                course_field=spec.course_field if spec else None,
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
