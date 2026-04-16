"""瀛︾绾ч」鐩鍏ュ鍑?support commands銆?
璁捐瑕佺偣锛?- TABLE_REGISTRY 椹卞姩锛氭柊澧?淇敼琛ㄦ椂鍙渶鏇存柊娉ㄥ唽琛紝瀵煎嚭瀵煎叆鑷姩閫傞厤
- model_dump() / model_validate() 搴忓垪鍖栵細瀛楁鍙樻洿鏃惰嚜鍔ㄥ吋瀹?- 澶栭敭閲嶆槧灏勫湪娉ㄥ唽琛ㄤ腑澹版槑锛氭柊澧炲閿彧闇€鍔犱竴琛岄厤缃?"""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field
from sqlmodel import Session, SQLModel, func, select

from app.shared.infra.env_support import get_env
from app.shared.infra.runtime import is_cloud_mode
from app.shared.infra.storage import get_content_store, run_store_sync
from app.models import (
    ChatMessage,
    ChatSession,
    ExamPaper,
    ExamPaperItem,
    KnowledgeDocument,
    KnowledgeEdge,
    KnowledgeUnit,
    QuestionTemplate,
    RawFile,
    RetrievalChunk,
    Subject,
    UserKnowledgeState,
)
from app.schemas.export_import import (
    CoursePackageItem,
    ExportOptions,
    ExportPreviewData,
    ExportPreviewStats,
    ImportOptions,
    ImportResultData,
)
from app.utils.path_helpers import (
    build_asset_dir,
    build_assets_dir,
    build_courses_dir,
    build_exam_dir,
    build_knowledge_markdown_dir,
    build_raw_dir,
    build_raw_file_path,
    build_raw_markdown_dir,
    build_raw_markdown_path,
    build_subject_dir,
)
from app.utils.subject import generate_subject_id
from app.utils.time import utcnow

logger = structlog.get_logger()

SUPPORTED_FORMAT_VERSIONS = {"1.0"}


# ---------------------------------------------------------------------------
# Manifest 鍐呴儴妯″瀷锛堜粎鐢ㄤ簬 .atmx 鏂囦欢锛屼笉璧?API锛?# ---------------------------------------------------------------------------


class _ManifestSubject(BaseModel):
    slug: str
    name: str


class _ManifestStats(BaseModel):
    raw_file_count: int = 0
    knowledge_document_count: int = 0
    knowledge_node_count: int = 0
    knowledge_edge_count: int = 0
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
# Table Registry 鈥?瀵煎叆瀵煎嚭鐨勫敮涓€閰嶇疆婧?# ---------------------------------------------------------------------------


@dataclass
class _TableSpec:
    """澹版槑涓€寮犱笟鍔¤〃鐨勫鍑哄鍏ヨ鍒欍€?
    鏂板琛ㄦ垨淇敼澶栭敭鏃讹紝鍙渶鏇存柊杩欎唤娉ㄥ唽琛ㄣ€?    """

    name: str
    model: type[SQLModel]
    # 濡備綍鎸?subject 杩囨护锛氬瓧娈靛悕 | "slug" (Subject 鏈韩) | None (閫氳繃鐖惰〃杩囨护)
    subject_field: str | None = "subject"
    id_field: str = "id"
    # id 绫诲瀷锛?auto" (鑷) | "uuid" (瀛楃涓?UUID)
    id_type: str = "auto"
    # 澶栭敭閲嶆槧灏? {瀛楁鍚? 寮曠敤鐨勮〃鍚峿
    fk_remap: dict[str, str] = dc_field(default_factory=dict)
    # 閫氳繃鐖惰〃杩囨护 (鐢ㄤ簬娌℃湁 subject 瀛楁鐨勮〃)
    parent_fk: str | None = None
    parent_table: str | None = None
    # 鍙€夊鍑哄垎缁? "chat" | "exam" | "profile" | None(蹇呴』瀵煎嚭)
    optional_group: str | None = None


# 椤哄簭涓ユ牸鎸変緷璧栧叧绯绘帓鍒?鈥斺€?琚紩鐢ㄧ殑琛ㄥ繀椤绘帓鍦ㄥ墠闈?TABLE_REGISTRY: list[_TableSpec] = [
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
        "knowledge_node",
        KnowledgeUnit,
        fk_remap={"merged_into_node_id": "knowledge_node"},
    ),
    _TableSpec(
        "knowledge_edge",
        KnowledgeEdge,
        fk_remap={
            "source_node_id": "knowledge_node",
            "target_node_id": "knowledge_node",
        },
    ),
    _TableSpec(
        "question_template",
        QuestionTemplate,
        fk_remap={
            "knowledge_node_id": "knowledge_node",
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
            "knowledge_node_id": "knowledge_node",
        },
        optional_group="exam",
    ),
    _TableSpec(
        "user_knowledge_state",
        UserKnowledgeState,
        fk_remap={
            "knowledge_node_id": "knowledge_node",
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


def preview_export(session: Session, *, subject_slug: str) -> ExportPreviewData:
    """瀵煎嚭棰勮锛氱粺璁″唴瀹规憳瑕併€?""

    subject = _require_subject(session, subject_slug)
    raw_files = session.exec(select(RawFile).where(RawFile.subject == subject_slug)).all()
    total_size = sum(r.file_size_bytes or 0 for r in raw_files)

    stats = ExportPreviewStats(
        raw_file_count=len(raw_files),
        total_raw_file_size_bytes=total_size,
        knowledge_document_count=_count(session, KnowledgeDocument, subject_slug),
        knowledge_node_count=_count(session, KnowledgeUnit, subject_slug),
        knowledge_edge_count=_count(session, KnowledgeEdge, subject_slug),
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
    """灏嗕竴涓绉戠殑鍏ㄩ儴浜х墿鎵撳寘涓?.atmx 鏂囦欢锛岃繑鍥炰复鏃舵枃浠惰矾寰勩€?""

    options = options or ExportOptions()
    subject = _require_subject(session, subject_slug)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".atmx")
    tmp.close()
    tmp_path = Path(tmp.name)

    try:
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

            _pack_files(zf, subject_slug, options)

            manifest = _build_manifest(subject, exported, options)
            zf.writestr("manifest.json", manifest.model_dump_json(indent=2))

        logger.info("subject_exported", subject=subject_slug, path=str(tmp_path))
        return tmp_path

    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def import_subject(
    session: Session,
    *,
    file_path: Path,
    options: ImportOptions | None = None,
    user_id: str = "local",
) -> ImportResultData:
    """浠?.atmx 鏂囦欢瀵煎叆瀛︾銆?""

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

        for spec in TABLE_REGISTRY:
            db_file = tmpdir / "db" / f"{spec.name}.json"
            if not db_file.exists():
                continue
            data = json.loads(db_file.read_text(encoding="utf-8"))
            records = data.get("records", [])
            if not records:
                continue
            count = _import_table(
                session, spec, records,
                id_map=id_map,
                new_slug=new_slug,
                new_name=new_name,
                user_id=user_id,
                warnings=warnings,
            )
            imported_counts[spec.name] = count

        session.commit()

        _unpack_files(tmpdir, new_slug, id_map.get("raw_file", {}))

        logger.info("subject_imported", subject=new_slug, name=new_name, counts=imported_counts)
        return ImportResultData(
            subject_id=new_slug,
            subject_name=new_name,
            imported_counts=imported_counts,
            warnings=warnings,
        )


def list_available_courses() -> list[CoursePackageItem]:
    """鎵弿鍏变韩璇剧▼鐩綍涓殑 .atmx 鏂囦欢锛岃鍙?manifest 杩斿洖姒傝鍒楄〃銆?""

    courses_dir = build_courses_dir()
    if not courses_dir.exists():
        courses_dir.mkdir(parents=True, exist_ok=True)
        return []

    items: list[CoursePackageItem] = []
    for path in sorted(courses_dir.glob("*.atmx")):
        if not path.is_file():
            continue
        try:
            with zipfile.ZipFile(path, "r") as zf:
                if "manifest.json" not in zf.namelist():
                    continue
                raw = zf.read("manifest.json")
                manifest = _ExportManifest.model_validate_json(raw)

            stats_dict = manifest.stats.model_dump()
            items.append(
                CoursePackageItem(
                    filename=path.name,
                    subject_name=manifest.subject.name,
                    file_size_bytes=path.stat().st_size,
                    exported_at=manifest.exported_at,
                    stats=stats_dict,
                )
            )
        except Exception as exc:
            logger.warning("course_package_scan_error", file=path.name, error=str(exc))
            continue

    return items


def get_courses_dir_path() -> Path:
    """杩斿洖鍏变韩璇剧▼鐩綍璺緞锛堝墠绔?API 浣跨敤锛夈€?""

    d = build_courses_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


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
    if spec.subject_field == "slug":
        rows = session.exec(select(spec.model).where(spec.model.slug == subject_slug)).all()
    elif spec.subject_field:
        col = getattr(spec.model, spec.subject_field)
        rows = session.exec(select(spec.model).where(col == subject_slug)).all()
    elif spec.parent_fk and spec.parent_table:
        parent_ids = {r["id"] for r in exported.get(spec.parent_table, [])}
        if not parent_ids:
            return []
        col = getattr(spec.model, spec.parent_fk)
        rows = session.exec(select(spec.model).where(col.in_(parent_ids))).all()
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
    id_map[spec.name] = table_id_map  # 鎻愬墠娉ㄥ唽锛屾敮鎸佽嚜寮曠敤澶栭敭

    for record_data in records:
        old_id = record_data.get(spec.id_field)

        # 鏂?ID
        if spec.id_type == "auto":
            record_data[spec.id_field] = None
        elif spec.id_type == "uuid":
            record_data[spec.id_field] = str(uuid.uuid4())

        # 鏇存柊 subject
        if spec.name == "subject":
            record_data["slug"] = new_slug
            record_data["name"] = new_name
            record_data["normalized_name"] = None
        elif spec.subject_field and spec.subject_field != "slug":
            record_data[spec.subject_field] = new_slug

        # 鏇存柊 user_id
        if "user_id" in record_data:
            record_data["user_id"] = user_id

        # 澶栭敭閲嶆槧灏?        for fk_field, ref_table in spec.fk_remap.items():
            _remap_fk(record_data, fk_field, ref_table, id_map, spec.name, warnings)

        # 娓呴櫎缁濆璺緞瀛楁锛堝鍏ュ悗閲嶅缓锛?        if spec.name == "raw_file":
            record_data["uid"] = str(uuid.uuid4())  # 闃叉鍞竴绾︽潫鍐茬獊
            record_data["file_path"] = "__importing__"
            record_data["markdown_path"] = None
            record_data["asset_dir"] = None
            record_data["storage_uri"] = None
            record_data["markdown_uri"] = None
        elif spec.name == "knowledge_document":
            record_data["markdown_path"] = None
            record_data["markdown_uri"] = None

        # 鍒涘缓瀹炰緥
        try:
            instance = spec.model.model_validate(record_data)
            session.add(instance)
            session.flush()
        except Exception as exc:
            warnings.append(f"{spec.name}: skipped record (old_id={old_id}): {exc}")
            continue

        new_id = getattr(instance, spec.id_field)

        # 璺緞閲嶅缓锛堢粺涓€璧?ContentStore key锛?        cs = get_content_store()
        if spec.name == "raw_file" and isinstance(new_id, int):
            ext = instance.filetype if instance.filetype.startswith(".") else f".{instance.filetype}"
            instance.file_path = f"{new_slug}/raw_files/{new_id}{ext}"
            instance.markdown_path = cs.raw_markdown_key(new_slug, new_id)
            instance.asset_dir = cs.asset_prefix(new_slug, new_id).rstrip("/")
            instance.storage_backend = "s3" if is_cloud_mode() else "local"
        elif spec.name == "knowledge_document" and isinstance(new_id, int):
            instance.markdown_path = cs.knowledge_doc_key(new_slug, f"chapter_{instance.chapter_index}.md")

        if old_id is not None:
            table_id_map[old_id] = new_id

    return len(table_id_map)


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
    new_fk = ref_map.get(old_fk)
    # 灏濊瘯 int/str 浜掕浆鏌ユ壘
    if new_fk is None and isinstance(old_fk, str) and old_fk.isdigit():
        new_fk = ref_map.get(int(old_fk))
    if new_fk is None and isinstance(old_fk, int):
        new_fk = ref_map.get(str(old_fk))
    if new_fk is not None:
        record[fk_field] = new_fk
    else:
        record[fk_field] = None
        warnings.append(f"{table_name}.{fk_field}: ref {old_fk} not found in {ref_table}")


# ===================================================================
# Internal: 鏂囦欢鎵撳寘涓庤В鍖?# ===================================================================


def _pack_files(zf: zipfile.ZipFile, subject_slug: str, options: ExportOptions) -> None:
    """缁熶竴浠?ContentStore 璇诲彇鏂囦欢鎵撳叆 zip銆?""
    cs = get_content_store()
    skip_filenames = {".build.lock", "build_status.json", "manifest.json"}

    def _pack_prefix(prefix: str, arc_prefix: str) -> None:
        keys = run_store_sync(cs.list_prefix, prefix, default=[])
        for key in keys:
            relative = key[len(prefix):] if key.startswith(prefix) else key.rsplit("/", 1)[-1]
            data = run_store_sync(cs.read_bytes, key, default=None)
            if data is not None:
                zf.writestr(f"{arc_prefix}/{relative}", data)

    if options.include_raw_files:
        _pack_prefix(f"{subject_slug}/raw_files/", "files/raw_files")
        _pack_prefix(f"{subject_slug}/assets/", "files/assets")
    if options.include_raw_markdowns:
        _pack_prefix(f"{subject_slug}/raw_markdowns/", "files/raw_markdowns")

    # knowledge markdowns
    if options.include_knowledge_docs:
        keys = run_store_sync(cs.list_prefix, f"{subject_slug}/knowledge_markdowns/", default=[])
        for key in keys:
            filename = key.rsplit("/", 1)[-1]
            if filename in skip_filenames or "/_build/" in key:
                continue
            data = run_store_sync(cs.read_bytes, key, default=None)
            if data is not None:
                zf.writestr(f"knowledge/{filename}", data)


def _pack_dir(zf: zipfile.ZipFile, src_dir: Path, arc_prefix: str) -> None:
    if not src_dir.exists():
        return
    for item in sorted(src_dir.rglob("*")):
        if item.is_file():
            zf.write(item, f"{arc_prefix}/{item.relative_to(src_dir).as_posix()}")


def _unpack_files(extract_dir: Path, new_slug: str, file_id_map: dict[Any, Any]) -> None:
    """缁熶竴閫氳繃 ContentStore 灏?zip 涓殑鏂囦欢鍐欏叆瀛樺偍銆?""
    cs = get_content_store()

    def _upload_remapped(src_dir: Path, prefix: str) -> None:
        if not src_dir.exists():
            return
        for item in src_dir.iterdir():
            if not item.is_file():
                continue
            try:
                old_id = int(item.stem)
                new_id = file_id_map.get(old_id, old_id)
                key = f"{new_slug}/{prefix}/{new_id}{item.suffix}"
            except ValueError:
                key = f"{new_slug}/{prefix}/{item.name}"
            run_store_sync(cs.write_bytes, key, item.read_bytes())

    _upload_remapped(extract_dir / "files/raw_files", "raw_files")
    _upload_remapped(extract_dir / "files/raw_markdowns", "raw_markdowns")

    # 璧勪骇鐩綍鎸?file_id 閲嶅懡鍚嶄笂浼?    src_assets = extract_dir / "files" / "assets"
    if src_assets.exists():
        for old_dir in src_assets.iterdir():
            if not old_dir.is_dir():
                continue
            try:
                old_id = int(old_dir.name)
            except ValueError:
                continue
            new_id = file_id_map.get(old_id, old_id)
            for asset_file in old_dir.rglob("*"):
                if asset_file.is_file():
                    relative = asset_file.relative_to(old_dir).as_posix()
                    key = f"{new_slug}/assets/{new_id}/{relative}"
                    run_store_sync(cs.write_bytes, key, asset_file.read_bytes())

    # 鐭ヨ瘑鏂囨。涓婁紶
    src_kd = extract_dir / "knowledge"
    if src_kd.exists():
        for item in src_kd.iterdir():
            if item.is_file():
                key = cs.knowledge_doc_key(new_slug, item.name)
                run_store_sync(cs.write_bytes, key, item.read_bytes())


def _copy_remapped(src_dir: Path, dst_dir: Path, id_map: dict[Any, Any]) -> None:
    if not src_dir.exists():
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    for item in src_dir.iterdir():
        if not item.is_file():
            continue
        try:
            old_id = int(item.stem)
            new_id = id_map.get(old_id, old_id)
            shutil.copy2(item, dst_dir / f"{new_id}{item.suffix}")
        except ValueError:
            shutil.copy2(item, dst_dir / item.name)


# ===================================================================
# Internal: Manifest
# ===================================================================


def _build_manifest(
    subject: Subject,
    exported: dict[str, list[dict]],
    options: ExportOptions,
) -> _ExportManifest:
    return _ExportManifest(
        app_version=get_env("APP_VERSION", "0.2.0") or "0.2.0",
        exported_at=utcnow(),
        subject=_ManifestSubject(
            slug=subject.slug,
            name=subject.name,
        ),
        stats=_ManifestStats(
            raw_file_count=len(exported.get("raw_file", [])),
            knowledge_document_count=len(exported.get("knowledge_document", [])),
            knowledge_node_count=len(exported.get("knowledge_node", [])),
            knowledge_edge_count=len(exported.get("knowledge_edge", [])),
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

