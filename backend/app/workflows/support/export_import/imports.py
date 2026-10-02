"""Course package import workflows."""

from __future__ import annotations

import asyncio
import base64
import hashlib
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

from app.models import (
    ChatSession,
    Course,
    ExamPaper,
    ExamPaperItem,
    KnowledgeDocument,
    QuestionTypePackageAsset,
    QuestionTypePackageVersion,
    QuestionTypeRegistry,
    QuestionTemplate,
    RawFile,
    RetrievalChunk,
)
from app.repositories.knowledge import knowledge_repo
from app.repositories import initial_exam_repo
from app.schemas.export_import import ImportOptions, ImportResultData
from app.shared.infra.embedding import aembed_texts
from app.shared.infra.course import (
    get_runtime_embedding_config,
    should_generate_course_embeddings,
)
from app.shared.infra.llm_support import get_llm_concurrency_limit
from app.shared.infra.observability.trace import langsmith_trace, llm_trace_scope
from app.shared.infra.storage import (
    CourseStorageScope,
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
from app.shared.kernel.question_types import (
    UnsupportedQuestionTypeError,
    require_supported_question_type_key,
)
from app.shared.kernel.question_type_runtime import assess_custom_question_type_runtime
from app.workflows.support.question_type_packages.contracts import (
    ALLOWED_GRADER_KEYS,
    ALLOWED_RENDERER_KEYS,
    ALLOWED_RUNTIME_KEYS,
    ALLOWED_TEMPLATE_KEYS,
    ALLOWED_V2_TEMPLATE_KEYS,
    ATQSKILL_SCHEMA_ID,
    ATQSKILL_SCHEMA_ID_V2,
    CompiledAsset,
    CompiledQuestionTypeDefinition,
)
from app.workflows.support.question_type_packages.installer import build_public_definition
from app.workflows.support.question_type_packages.validator import (
    validate_compiled_asset_content,
    validate_compiled_question_type_definition,
)
from app.workflows.digest.docgen.lib.published_manifest import ensure_published_knowledge_manifest
from app.shared.infra.llm_support.common import build_completion_contexts
from app.workflows.support.export_import.exports import (
    TABLE_REGISTRY,
    _DOCGEN_COVER_MARKDOWN_RE,
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
_SHARE_ASSET_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_SHARE_ASSET_ROOT = "share_assets"
MAX_IMPORTED_SHARE_ASSET_BYTES = 16 * 1024 * 1024
_IMPORT_EMBEDDING_BATCH_SIZE = 1
_IMPORT_EMBEDDING_MAX_CONCURRENCY = 1
_IMPORT_EMBEDDING_FOREGROUND_SLOT_RESERVE = 2
_IMPORT_EMBEDDING_GLOBAL_FRACTION_DIVISOR = 3


def _validate_imported_question_types(table_name: str, records: list[dict[str, Any]]) -> None:
    """Reject runtime records whose question type is not implemented."""

    if table_name == "question_type_package_version":
        _validate_imported_question_type_versions(records)
        return
    if table_name == "question_type_package_asset":
        _validate_imported_question_type_assets(records)
        return

    if table_name not in {"question_template", "exam_paper_item", "question_type_registry"}:
        return

    for record in records:
        field_name = "type_key" if table_name == "question_type_registry" else "question_type"
        question_type = str(record.get(field_name) or "").strip().lower()
        if question_type.startswith("custom_"):
            if table_name == "question_type_registry":
                if record.get("scope") != "course" or record.get("source") != "upload":
                    raise InvalidImportPackageError(
                        f"课程题型 `{record.get('id', 'unknown')}` 的来源或作用域无效。"
                    )
            elif not record.get("question_type_version_id"):
                raise InvalidImportPackageError(
                    f"数据表 `{table_name}` 的记录 `{record.get('id', 'unknown')}` 缺少题型版本。"
                )
            continue
        if table_name == "question_type_registry" and not bool(record.get("is_active", True)):
            continue
        try:
            record[field_name] = require_supported_question_type_key(record.get(field_name))
        except UnsupportedQuestionTypeError as exc:
            record_id = record.get("id", "unknown")
            question_type = exc.question_type or "<empty>"
            raise InvalidImportPackageError(
                f"数据表 `{table_name}` 的记录 `{record_id}` 包含不支持的题型 `{question_type}`。"
            ) from exc


def _validate_imported_question_type_versions(records: list[dict[str, Any]]) -> None:
    for record in records:
        record_id = record.get("id", "unknown")
        try:
            compiled = CompiledQuestionTypeDefinition.model_validate_json(
                str(record.get("compiled_definition_json") or "{}")
            )
        except Exception as exc:
            raise InvalidImportPackageError(
                f"题型包版本 `{record_id}` 的编译定义无效。"
            ) from exc
        if (
            compiled.schema_version not in {ATQSKILL_SCHEMA_ID, ATQSKILL_SCHEMA_ID_V2}
            or (
                compiled.template_key not in ALLOWED_TEMPLATE_KEYS
                and compiled.template_key not in ALLOWED_V2_TEMPLATE_KEYS
            )
            or compiled.runtime_key not in ALLOWED_RUNTIME_KEYS
            or compiled.renderer_key not in ALLOWED_RENDERER_KEYS
            or compiled.grader_key not in ALLOWED_GRADER_KEYS
        ):
            raise InvalidImportPackageError(
                f"题型包版本 `{record_id}` 使用了不支持的运行合同。"
            )
        semantic_issues = validate_compiled_question_type_definition(compiled)
        if semantic_issues:
            issue = semantic_issues[0]
            raise InvalidImportPackageError(
                f"题型包版本 `{record_id}` 未通过语义校验：{issue.message}"
            )
        expected = {
            "package_key": compiled.package_key,
            "type_key": compiled.type_key,
            "version": compiled.version,
            "package_hash": compiled.package_sha256,
        }
        if any(str(record.get(key) or "") != value for key, value in expected.items()):
            raise InvalidImportPackageError(
                f"题型包版本 `{record_id}` 的身份字段与编译定义不一致。"
            )
        try:
            public_preview = json.loads(str(record.get("public_preview_json") or "{}"))
        except json.JSONDecodeError as exc:
            raise InvalidImportPackageError(
                f"题型包版本 `{record_id}` 的公开预览不是有效 JSON。"
            ) from exc
        if public_preview != build_public_definition(compiled):
            raise InvalidImportPackageError(
                f"题型包版本 `{record_id}` 的公开预览与编译定义不一致。"
            )


def _validate_imported_question_type_assets(records: list[dict[str, Any]]) -> None:
    for record in records:
        record_id = record.get("id", "unknown")
        try:
            content = base64.b64decode(str(record.get("content_base64") or ""), validate=True)
            declared_size = int(record.get("size_bytes") or 0)
            compiled_asset = CompiledAsset(
                path=str(record.get("path") or ""),
                role=record.get("role"),
                media_type=str(record.get("media_type") or ""),
                sha256=str(record.get("sha256") or ""),
                size_bytes=declared_size,
                width=int(record.get("width") or 0),
                height=int(record.get("height") or 0),
            )
        except (ValueError, TypeError, ValidationError) as exc:
            raise InvalidImportPackageError(
                f"题型包资源 `{record_id}` 的内容编码无效。"
            ) from exc
        digest = hashlib.sha256(content).hexdigest()
        if len(content) != declared_size or digest != str(record.get("sha256") or ""):
            raise InvalidImportPackageError(
                f"题型包资源 `{record_id}` 的大小或哈希不一致。"
            )
        asset_issues = validate_compiled_asset_content(compiled_asset, content)
        if asset_issues:
            raise InvalidImportPackageError(
                f"题型包资源 `{record_id}` 未通过安全校验：{asset_issues[0].message}"
            )


def _strict_json_object(raw: str, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise InvalidImportPackageError(f"{label}不是有效 JSON。") from exc
    if not isinstance(value, dict):
        raise InvalidImportPackageError(f"{label}必须是 JSON 对象。")
    return value


def _validate_imported_custom_question_snapshot(
    record: QuestionTemplate | ExamPaperItem,
    *,
    version: QuestionTypePackageVersion,
    compiled: CompiledQuestionTypeDefinition,
) -> None:
    record_id = record.id or "unknown"
    table_name = "question_template" if isinstance(record, QuestionTemplate) else "exam_paper_item"
    prefix = f"数据表 `{table_name}` 的记录 `{record_id}`"
    if (
        record.question_type_registry_id != version.registry_id
        or record.question_type != version.type_key
        or bool(record.profile_eligible) != bool(version.profile_eligible)
    ):
        raise InvalidImportPackageError(f"{prefix}与冻结题型版本的身份信息不一致。")

    is_template = isinstance(record, QuestionTemplate)
    public_payload = _strict_json_object(
        record.public_payload_json if is_template else record.public_payload_snapshot_json,
        label=f"{prefix}的公开题目数据",
    )
    answer_schema = _strict_json_object(
        record.answer_schema_json if is_template else record.answer_schema_snapshot_json,
        label=f"{prefix}的作答结构",
    )
    reference_answer = _strict_json_object(
        record.reference_answer_json if is_template else record.reference_answer_snapshot_json,
        label=f"{prefix}的参考答案",
    )
    grading_spec = _strict_json_object(
        record.grading_spec_json if is_template else record.grading_spec_snapshot_json,
        label=f"{prefix}的评分规则",
    )
    runtime_snapshot = _strict_json_object(
        record.runtime_snapshot_json,
        label=f"{prefix}的运行时快照",
    )
    expected_public_payload = {
        "display_name": compiled.display_name,
        "description": compiled.description,
        "renderer_key": compiled.renderer_key,
        "hints": compiled.hints,
        "immediate_feedback": compiled.immediate_feedback,
    }
    expected_answer_schema = {
        "fields": [item.model_dump(mode="json") for item in compiled.answer_fields]
    }
    expected_grading_spec = {
        "grader_key": compiled.grader_key,
        "pass_score": compiled.pass_score,
        "rubric": [item.model_dump(mode="json") for item in compiled.rubric],
        "grade_prompt": compiled.prompts.get("grade", ""),
        "feedback_prompt": compiled.prompts.get("feedback", ""),
        "reference_cases": [item.model_dump(mode="json") for item in compiled.reference_cases],
        "tool_bindings": [item.model_dump(mode="json") for item in compiled.tool_bindings],
    }
    expected_runtime_snapshot = {
        "registry_id": version.registry_id,
        "version_id": version.id,
        "type_key": compiled.type_key,
        "version": compiled.version,
        "package_hash": compiled.package_sha256,
        "template_key": compiled.template_key,
        "runtime_key": compiled.runtime_key,
        "renderer_key": compiled.renderer_key,
        "grader_key": compiled.grader_key,
        "profile_eligible": bool(version.profile_eligible),
    }
    if public_payload != expected_public_payload or answer_schema != expected_answer_schema:
        raise InvalidImportPackageError(f"{prefix}的公开合同与冻结题型版本不一致。")
    if grading_spec != expected_grading_spec or runtime_snapshot != expected_runtime_snapshot:
        raise InvalidImportPackageError(f"{prefix}的评分或运行合同与冻结题型版本不一致。")

    answer_text = record.answer if is_template else record.answer_snapshot
    answer_keys = [item.key for item in compiled.answer_fields]
    if set(reference_answer) != set(answer_keys):
        raise InvalidImportPackageError(f"{prefix}的参考答案字段与冻结作答结构不一致。")
    if any(not isinstance(reference_answer[key], str) for key in answer_keys):
        raise InvalidImportPackageError(f"{prefix}的参考答案字段必须是文本。")
    if len(answer_keys) == 1 and reference_answer[answer_keys[0]] != answer_text:
        raise InvalidImportPackageError(f"{prefix}的参考答案与兼容文本不一致。")


def _validate_imported_question_type_package_relationships(
    session: Session,
    *,
    course_id: str,
) -> None:
    versions = list(
        session.exec(
            select(QuestionTypePackageVersion).where(
                QuestionTypePackageVersion.course_id == course_id
            )
        ).all()
    )
    assets = list(
        session.exec(
            select(QuestionTypePackageAsset).where(
                QuestionTypePackageAsset.course_id == course_id
            )
        ).all()
    )
    assets_by_version: dict[int, list[QuestionTypePackageAsset]] = {}
    for asset in assets:
        assets_by_version.setdefault(asset.package_version_id, []).append(asset)

    compiled_by_version_id: dict[int, CompiledQuestionTypeDefinition] = {}
    for version in versions:
        try:
            compiled = CompiledQuestionTypeDefinition.model_validate_json(
                version.compiled_definition_json
            )
        except Exception as exc:  # already checked before insertion
            raise InvalidImportPackageError(
                f"题型包版本 `{version.id}` 的编译定义无效。"
            ) from exc
        compiled_by_version_id[int(version.id or 0)] = compiled
        expected_assets = {
            item.path: (
                item.role,
                item.media_type,
                item.sha256,
                item.size_bytes,
                item.width,
                item.height,
            )
            for item in compiled.assets
        }
        imported_assets = {
            item.path: (
                item.role,
                item.media_type,
                item.sha256,
                item.size_bytes,
                item.width,
                item.height,
            )
            for item in assets_by_version.get(version.id or 0, [])
        }
        if imported_assets != expected_assets:
            raise InvalidImportPackageError(
                f"题型包版本 `{version.id}` 的资源清单不完整或已被修改。"
            )

    registries = list(
        session.exec(
            select(QuestionTypeRegistry).where(
                QuestionTypeRegistry.course_id == course_id,
                QuestionTypeRegistry.scope == "course",
                QuestionTypeRegistry.is_system == False,  # noqa: E712
            )
        ).all()
    )
    versions_by_registry: dict[int, list[QuestionTypePackageVersion]] = {}
    for version in versions:
        versions_by_registry.setdefault(version.registry_id, []).append(version)
    for registry in registries:
        if registry.source != "upload" and not registry.type_key.startswith("custom_"):
            continue
        registry_versions = versions_by_registry.get(registry.id or 0, [])
        if registry.source != "upload" or not registry_versions:
            raise InvalidImportPackageError(
                f"课程题型 `{registry.id}` 缺少可信的安装版本。"
            )
        if registry.status not in {"active", "inactive", "archived"}:
            raise InvalidImportPackageError(
                f"课程题型 `{registry.id}` 的状态无效。"
            )
        if bool(registry.is_active) != (registry.status == "active"):
            raise InvalidImportPackageError(f"课程题型 `{registry.id}` 的启用状态不一致。")
        if any(item.type_key != registry.type_key for item in registry_versions):
            raise InvalidImportPackageError(
                f"课程题型 `{registry.id}` 与安装版本的类型标识不一致。"
            )
        if sum(1 for item in registry_versions if item.is_current) != 1:
            raise InvalidImportPackageError(
                f"课程题型 `{registry.id}` 必须且只能有一个当前版本。"
            )
        current_version = next(item for item in registry_versions if item.is_current)
        current_definition = compiled_by_version_id[int(current_version.id or 0)]
        if registry.is_active and not assess_custom_question_type_runtime(
            current_definition.model_dump(mode="json")
        ).ready:
            raise InvalidImportPackageError(
                f"课程题型 `{registry.id}` 当前版本没有可用的运行能力。"
            )
        if any(item.profile_eligible for item in registry_versions):
            raise InvalidImportPackageError(
                f"课程题型 `{registry.id}` 在第一版不能写入长期掌握度。"
            )

    versions_by_id = {int(item.id or 0): item for item in versions}
    templates = list(
        session.exec(
            select(QuestionTemplate).where(
                QuestionTemplate.course_id == course_id,
            )
        ).all()
    )
    paper_items = list(
        session.exec(
            select(ExamPaperItem)
            .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
            .where(ExamPaper.course_id == course_id)
        ).all()
    )
    for record in [*templates, *paper_items]:
        # An unresolved import FK becomes None. Select records by course, not
        # by that FK, so broken custom questions cannot evade this validation.
        if record.question_type_version_id is None:
            if str(record.question_type or "").strip().lower().startswith("custom_"):
                raise InvalidImportPackageError(
                    f"自定义题目 `{record.id or 'unknown'}` 缺少有效的题型版本。"
                )
            continue
        version_id = int(record.question_type_version_id or 0)
        version = versions_by_id.get(version_id)
        compiled = compiled_by_version_id.get(version_id)
        if version is None or compiled is None:
            raise InvalidImportPackageError(
                f"自定义题目 `{record.id or 'unknown'}` 引用了当前课程之外的题型版本。"
            )
        _validate_imported_custom_question_snapshot(
            record,
            version=version,
            compiled=compiled,
        )


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
    commit: bool = True,
) -> ImportResultData:
    """Import one course from an ``.atmx`` archive.

    ``commit=False`` leaves the imported rows in the caller's transaction so
    an outer use case can atomically persist related records. The caller must
    clean the imported course storage if that outer transaction later fails.
    """

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
                if spec.name == "exam_paper":
                    records = [
                        record
                        for record in records
                        if str(record.get("exam_mode") or "") != "mastery_drill"
                    ]
                if not records:
                    continue
                _validate_imported_question_types(spec.name, records)
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

            _validate_imported_question_type_package_relationships(
                session,
                course_id=new_course_id,
            )

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
            initial_exam_repo.ensure_course_initial_exam_job(
                session,
                course_id=new_course_id,
                user_id=user_id,
                status="completed",
                last_error_code="imported_course_backfill",
                auto_commit=False,
            )
            if commit:
                session.commit()
            else:
                session.flush()
        except Exception:
            file_scope = get_content_store().user_file_scope(user_id=user_id)
            imported_file_prefixes = {
                file_scope.file_prefix(file_id=item.id, filename=item.filename)
                for item in [*session.identity_map.values(), *session.new]
                if isinstance(item, RawFile)
                and item.user_id == user_id
                and item.origin_course_id == new_course_id
                and item.id
            }
            session.rollback()
            cleanup_imported_course_artifacts(
                new_course_id,
                user_id=user_id,
            )
            content_store = get_content_store()
            for prefix in imported_file_prefixes:
                run_store_sync(content_store.delete_prefix, prefix, default=0)
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

    _restore_share_assets(
        extract_dir,
        course_scope=course_scope,
        content_store=cs,
    )

    src_knowledge = extract_dir / "knowledge"
    restored_cover_name = ""
    if src_knowledge.exists():
        # Published chapter markdown is imported from KnowledgeDocument rows; only
        # non-DB docgen assets need to be restored.
        for item in sorted(src_knowledge.iterdir()):
            if not item.is_file():
                continue
            if item.stem == "cover" and item.suffix.lower() in _DOCGEN_COVER_IMAGE_EXTENSIONS:
                key = f"{course_scope.namespace}/assets/docgen/{item.name}"
                run_store_sync(cs.write_bytes, key, item.read_bytes())
                restored_cover_name = item.name
                break

    if not restored_cover_name:
        return

    first_published_doc = session.exec(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.course_id == new_course_id,
            KnowledgeDocument.is_current.is_(True),
            KnowledgeDocument.status == "published",
        )
        .order_by(
            KnowledgeDocument.order_index,
            KnowledgeDocument.chapter_index,
            KnowledgeDocument.id,
        )
    ).first()
    if first_published_doc is None:
        return

    cover_markdown = f"![](../assets/docgen/{restored_cover_name})"

    def restore_cover_reference(markdown: str | None) -> str:
        body = str(markdown or "").strip()
        if _DOCGEN_COVER_MARKDOWN_RE.search(body):
            return _DOCGEN_COVER_MARKDOWN_RE.sub(cover_markdown, body)
        return f"{cover_markdown}\n\n{body}".strip()

    effective_markdown = (
        str(first_published_doc.markdown_content or "").strip()
        or str(first_published_doc.content_markdown or "").strip()
    )
    first_published_doc.markdown_content = restore_cover_reference(effective_markdown)
    session.add(first_published_doc)


def _restore_share_assets(
    extract_dir: Path,
    *,
    course_scope: CourseStorageScope,
    content_store: Any,
) -> None:
    """Restore only bounded, signature-verified passive image assets."""

    asset_root = (extract_dir / _SHARE_ASSET_ROOT).resolve()
    if not asset_root.exists():
        return

    for candidate in sorted(asset_root.rglob("*")):
        if not candidate.is_file():
            continue
        if candidate.is_symlink():
            raise InvalidImportPackageError("分享资产包含不安全的符号链接。")

        resolved = candidate.resolve()
        try:
            relative = resolved.relative_to(asset_root)
        except ValueError as exc:
            raise InvalidImportPackageError("分享资产路径超出允许目录。") from exc

        suffix = resolved.suffix.lower()
        if suffix not in _SHARE_ASSET_IMAGE_EXTENSIONS:
            continue
        if resolved.stat().st_size > MAX_IMPORTED_SHARE_ASSET_BYTES:
            raise InvalidImportPackageError("单个分享图片资产不能超过 16 MiB。")

        data = resolved.read_bytes()
        if not _share_asset_magic_matches(suffix, data):
            continue
        key = f"{course_scope.namespace}/assets/{relative.as_posix()}"
        run_store_sync(content_store.write_bytes, key, data)


def _share_asset_magic_matches(suffix: str, data: bytes) -> bool:
    if suffix == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if suffix == ".gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if suffix == ".webp":
        return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    return False


def cleanup_imported_course_artifacts(course_id: str, *, user_id: str) -> None:
    """Best-effort storage cleanup after an import transaction fails."""

    cs = get_content_store()
    try:
        run_store_sync(
            cs.delete_prefix,
            build_course_storage_scope(user_id=user_id, course_id=course_id).course_prefix(),
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
        embedding_dim = len(embeddings[0]) if embeddings else 0
        with langsmith_trace(
            name="导入课程：持久化向量索引",
            run_type="tool",
            inputs={
                "course_id": course_id,
                "chunk_count": len(chunk_rows),
                "embedding_dim": embedding_dim,
            },
            course_id=course_id,
            workflow="course_import_embeddings",
            lane="background",
            node="persist_vector_index",
            extra_metadata={"vector_persist_phase": "upsert_and_verify"},
            extra_tags=["phase:vector_persist"],
        ) as persist_trace:
            knowledge_repo.bulk_insert_embeddings(
                session,
                course_id=course_id,
                chunk_ids=[int(chunk.id) for chunk in chunk_rows],
                embeddings=embeddings,
                embedding_model=runtime.embedding_model,
            )
            if persist_trace is not None:
                persist_trace.end(
                    outputs={
                        "status": "verified",
                        "indexed_chunk_count": len(chunk_rows),
                        "embedding_dim": embedding_dim,
                    }
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
    "cleanup_imported_course_artifacts",
    "import_course",
    "rebuild_imported_embeddings_background",
    "spawn_imported_embedding_rebuild_background",
]
