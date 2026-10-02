"""Persistence use cases for validated course question-type packages.

This module intentionally stops at installation and catalog management. It does
not dispatch generation or grading; those runtime capabilities belong to P2.
"""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import uuid
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlmodel import Session, func, select

from app.models import (
    QuestionTypePackageAsset,
    QuestionTypePackageImport,
    QuestionTypePackageVersion,
    QuestionTypeRegistry,
)
from app.schemas.question_type_packages import (
    QuestionTypeAnswerFieldResponse,
    QuestionTypeCatalogItemResponse,
    QuestionTypePackageInstallData,
    QuestionTypePackageIssueResponse,
    QuestionTypePackagePreviewData,
    QuestionTypePackageVersionResponse,
    QuestionTypeRubricItemResponse,
)
from app.shared.infra.exceptions import AITeachMeError
from app.shared.kernel.question_type_runtime import assess_custom_question_type_runtime
from app.shared.kernel.question_types import is_supported_question_type
from app.utils.time import ensure_utc_datetime, utcnow
from app.workflows.support.question_type_packages.archive import read_atqskill_archive
from app.workflows.support.question_type_packages.contracts import (
    CompiledQuestionTypeDefinition,
    PackageValidationResult,
)


IMPORT_TTL = timedelta(hours=24)
MAX_PENDING_IMPORTS_PER_COURSE = 10
MAX_PENDING_IMPORTS_PER_USER = 20
MAX_UPLOADED_TYPES_PER_COURSE = 20
MAX_INSTALLED_VERSIONS_PER_TYPE = 10
MAX_INSTALLED_ASSET_BYTES_PER_COURSE = 100 * 1024 * 1024
PACKAGE_RUNTIME_UNAVAILABLE_MESSAGE = (
    "该题型的出题和判分能力尚未发布，暂不进入训练配置。"
)
BUILTIN_MODES = ["question_bank", "mastery_drill", "web_practice", "paper_exam", "pdf"]


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _json_value(raw: str, fallback: Any) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _runtime_availability(compiled: CompiledQuestionTypeDefinition):
    return assess_custom_question_type_runtime(compiled.model_dump(mode="json"))


def _stored_runtime_availability(version: QuestionTypePackageVersion | None):
    if version is None:
        return assess_custom_question_type_runtime({})
    try:
        compiled = CompiledQuestionTypeDefinition.model_validate_json(
            version.compiled_definition_json
        )
    except Exception:  # noqa: BLE001 - persisted package data must fail closed
        return assess_custom_question_type_runtime({})
    return _runtime_availability(compiled)


def _raise(
    detail: str,
    *,
    error_code: str,
    status_code: int,
    data: object | None = None,
) -> None:
    raise AITeachMeError(
        detail=detail,
        error_code=error_code,
        status_code=status_code,
        data=data,
    )


def build_public_definition(compiled: CompiledQuestionTypeDefinition) -> dict[str, Any]:
    """Return public metadata without prompts, reference answers, or private manifests."""

    return {
        "package_key": compiled.package_key,
        "type_key": compiled.type_key,
        "version": compiled.version,
        "name": compiled.display_name,
        "description": compiled.description,
        "template_key": compiled.template_key,
        "runtime_key": compiled.runtime_key,
        "renderer_key": compiled.renderer_key,
        "grader_key": compiled.grader_key,
        "modes": list(compiled.modes),
        "hints": compiled.hints,
        "immediate_feedback": compiled.immediate_feedback,
        "answer_fields": [item.model_dump(mode="json") for item in compiled.answer_fields],
        "pass_score": compiled.pass_score,
        "rubric": [item.model_dump(mode="json") for item in compiled.rubric],
        "tool_ids": [item.id for item in compiled.tool_bindings],
        "asset_count": len(compiled.assets),
        "documentation_markdown": compiled.documentation_markdown,
    }


def _issues(items: list[object]) -> list[QuestionTypePackageIssueResponse]:
    return [
        QuestionTypePackageIssueResponse.model_validate(
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
        )
        for item in items
    ]


def _find_version_conflict(
    session: Session,
    *,
    course_id: str,
    package_key: str,
    version: str,
    package_hash: str,
) -> tuple[str, int | None]:
    installed = session.exec(
        select(QuestionTypePackageVersion).where(
            QuestionTypePackageVersion.course_id == course_id,
            QuestionTypePackageVersion.package_key == package_key,
            QuestionTypePackageVersion.version == version,
        )
    ).first()
    if installed is not None:
        if installed.package_hash == package_hash:
            return "already_installed", installed.id
        return "version_conflict", installed.id
    any_version = session.exec(
        select(QuestionTypePackageVersion.id).where(
            QuestionTypePackageVersion.course_id == course_id,
            QuestionTypePackageVersion.package_key == package_key,
        )
    ).first()
    return ("new_version", None) if any_version is not None else ("none", None)


def build_validation_preview(
    session: Session,
    *,
    course_id: str,
    result: PackageValidationResult,
    import_record: QuestionTypePackageImport | None = None,
) -> QuestionTypePackagePreviewData:
    preview = result.preview
    compiled = result.compiled_definition
    conflict = "none"
    existing_version_id: int | None = None
    if preview is not None and result.package_hash:
        conflict, existing_version_id = _find_version_conflict(
            session,
            course_id=course_id,
            package_key=preview.package_key,
            version=preview.version,
            package_hash=result.package_hash,
        )
    return QuestionTypePackagePreviewData(
        import_id=import_record.id if import_record is not None else None,
        valid=result.valid,
        status="valid" if result.valid else "invalid",
        expires_at=import_record.expires_at if import_record is not None else None,
        package_hash=result.package_hash,
        package_key=preview.package_key if preview is not None else "",
        type_key=preview.type_key if preview is not None else "",
        version=preview.version if preview is not None else "",
        name=preview.name if preview is not None else "",
        description=preview.description if preview is not None else "",
        template_key=preview.template_key if preview is not None else "",
        runtime_key=preview.runtime_key if preview is not None else "",
        renderer_key=preview.renderer_key if preview is not None else "",
        grader_key=preview.grader_key if preview is not None else "",
        modes=list(preview.modes) if preview is not None else [],
        answer_fields=(
            [
                QuestionTypeAnswerFieldResponse.model_validate(item.model_dump(mode="json"))
                for item in compiled.answer_fields
            ]
            if compiled is not None
            else []
        ),
        rubric=(
            [
                QuestionTypeRubricItemResponse.model_validate(item.model_dump(mode="json"))
                for item in compiled.rubric
            ]
            if compiled is not None
            else []
        ),
        tool_ids=list(preview.tool_ids) if preview is not None else [],
        asset_count=preview.asset_count if preview is not None else 0,
        conflict=conflict,
        existing_version_id=existing_version_id,
        runtime_ready=bool(compiled and _runtime_availability(compiled).ready),
        runtime_message=(
            ""
            if compiled and _runtime_availability(compiled).ready
            else PACKAGE_RUNTIME_UNAVAILABLE_MESSAGE
        ),
        errors=_issues(result.errors),
        warnings=_issues(result.warnings),
    )


def create_pending_import(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    original_filename: str,
    archive_bytes: bytes,
    result: PackageValidationResult,
) -> tuple[QuestionTypePackageImport | None, QuestionTypePackagePreviewData]:
    """Persist a valid upload for a bounded period and return its safe preview."""

    if not result.valid or result.compiled_definition is None or result.preview is None:
        return None, build_validation_preview(session, course_id=course_id, result=result)

    now = utcnow()
    expired_ids = list(
        session.exec(
            select(QuestionTypePackageImport.id).where(
                QuestionTypePackageImport.user_id == user_id,
                QuestionTypePackageImport.expires_at <= now,
            )
        ).all()
    )
    if expired_ids:
        session.exec(
            sa.delete(QuestionTypePackageImport)
            .where(QuestionTypePackageImport.id.in_(expired_ids))
            .execution_options(synchronize_session=False)
        )

    pending_count = len(
        session.exec(
            select(QuestionTypePackageImport.id).where(
                QuestionTypePackageImport.course_id == course_id,
                QuestionTypePackageImport.user_id == user_id,
                QuestionTypePackageImport.status == "valid",
                QuestionTypePackageImport.expires_at > now,
            )
        ).all()
    )
    if pending_count >= MAX_PENDING_IMPORTS_PER_COURSE:
        _raise(
            "当前课程待确认的题型包过多，请先完成已有导入后再试。",
            error_code="QUESTION_TYPE_IMPORT_LIMIT_EXCEEDED",
            status_code=429,
        )
    pending_user_count = len(
        session.exec(
            select(QuestionTypePackageImport.id).where(
                QuestionTypePackageImport.user_id == user_id,
                QuestionTypePackageImport.status == "valid",
                QuestionTypePackageImport.expires_at > now,
            )
        ).all()
    )
    if pending_user_count >= MAX_PENDING_IMPORTS_PER_USER:
        _raise(
            "当前账号待确认的题型包过多，请先完成已有导入后再试。",
            error_code="QUESTION_TYPE_USER_IMPORT_LIMIT_EXCEEDED",
            status_code=429,
        )

    compiled = result.compiled_definition
    public_definition = build_public_definition(compiled)
    record = QuestionTypePackageImport(
        id=f"qti_{uuid.uuid4().hex}",
        course_id=course_id,
        user_id=user_id,
        original_filename=original_filename,
        status="valid",
        package_key=compiled.package_key,
        type_key=compiled.type_key,
        version=compiled.version,
        package_hash=compiled.package_sha256,
        public_preview_json=_json_dumps(public_definition),
        compiled_definition_json=compiled.model_dump_json(),
        archive_base64=base64.b64encode(archive_bytes).decode("ascii"),
        errors_json="[]",
        warnings_json=_json_dumps([item.model_dump(mode="json") for item in result.warnings]),
        expires_at=now + IMPORT_TTL,
        created_at=now,
        updated_at=now,
    )
    session.add(record)
    session.flush()
    return record, build_validation_preview(
        session,
        course_id=course_id,
        result=result,
        import_record=record,
    )


def _load_import_archive(record: QuestionTypePackageImport):
    try:
        archive_bytes = base64.b64decode(record.archive_base64, validate=True)
    except (ValueError, TypeError) as exc:
        _raise(
            "题型包暂存内容已损坏，请重新上传。",
            error_code="QUESTION_TYPE_IMPORT_CORRUPTED",
            status_code=409,
        )
        raise AssertionError("unreachable") from exc

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".atqskill") as temp_file:
            temp_file.write(archive_bytes)
            temp_path = Path(temp_file.name)
        return read_atqskill_archive(temp_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _answer_format(compiled: CompiledQuestionTypeDefinition) -> str:
    if compiled.renderer_key == "long_text_v1":
        return "长文本作答"
    return "结构化文本作答"


def _set_current_version(
    session: Session,
    *,
    registry: QuestionTypeRegistry,
    version: QuestionTypePackageVersion,
    public_definition: dict[str, Any],
) -> None:
    session.exec(
        sa.update(QuestionTypePackageVersion)
        .where(
            QuestionTypePackageVersion.registry_id == registry.id,
            QuestionTypePackageVersion.id != version.id,
        )
        .values(is_current=False)
        .execution_options(synchronize_session=False)
    )
    version.is_current = True
    if not _stored_runtime_availability(version).ready and registry.status == "active":
        registry.status = "inactive"
        registry.is_active = False
    registry.display_name = str(public_definition["name"])
    registry.description = str(public_definition["description"])
    registry.answer_format = _answer_format(
        CompiledQuestionTypeDefinition.model_validate_json(version.compiled_definition_json)
    )
    registry.grading_method = "llm"
    registry.option_schema_json = _json_dumps({"fields": public_definition["answer_fields"]})
    registry.rubric_json = _json_dumps(
        {
            "pass_score": public_definition["pass_score"],
            "items": public_definition["rubric"],
        }
    )
    registry.updated_at = utcnow()
    session.add(version)
    session.add(registry)


def install_pending_import(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    import_id: str,
    set_current: bool = True,
) -> QuestionTypePackageInstallData:
    record = session.exec(
        select(QuestionTypePackageImport).where(
            QuestionTypePackageImport.id == import_id,
            QuestionTypePackageImport.course_id == course_id,
            QuestionTypePackageImport.user_id == user_id,
        )
    ).first()
    if record is None:
        _raise(
            "题型包导入记录不存在。",
            error_code="QUESTION_TYPE_IMPORT_NOT_FOUND",
            status_code=404,
        )
    assert record is not None

    if record.status == "installed" and record.installed_version_id is not None:
        installed = session.get(QuestionTypePackageVersion, record.installed_version_id)
        if installed is not None and installed.course_id == course_id:
            registry = session.get(QuestionTypeRegistry, installed.registry_id)
            if registry is not None:
                runtime_ready = _stored_runtime_availability(installed).ready
                return QuestionTypePackageInstallData(
                    registry_id=registry.id or 0,
                    version_id=installed.id or 0,
                    type_key=installed.type_key,
                    version=installed.version,
                    status=registry.status,
                    runtime_ready=runtime_ready,
                    already_installed=True,
                )

    expires_at = ensure_utc_datetime(record.expires_at)
    if expires_at is None or expires_at <= utcnow():
        # Persist the security cleanup before returning 410; request-level
        # exception handling would otherwise roll this mutation back.
        session.delete(record)
        session.commit()
        _raise(
            "题型包导入预览已过期，请重新上传。",
            error_code="QUESTION_TYPE_IMPORT_EXPIRED",
            status_code=410,
        )
    if record.status != "valid":
        _raise(
            "该题型包当前不能安装，请重新上传并校验。",
            error_code="QUESTION_TYPE_IMPORT_NOT_INSTALLABLE",
            status_code=409,
        )

    try:
        compiled = CompiledQuestionTypeDefinition.model_validate_json(record.compiled_definition_json)
    except Exception as exc:
        _raise(
            "题型包编译结果已损坏，请重新上传。",
            error_code="QUESTION_TYPE_IMPORT_CORRUPTED",
            status_code=409,
        )
        raise AssertionError("unreachable") from exc
    if compiled.package_sha256 != record.package_hash:
        _raise(
            "题型包暂存内容完整性校验失败，请重新上传。",
            error_code="QUESTION_TYPE_IMPORT_CORRUPTED",
            status_code=409,
        )

    conflict, existing_version_id = _find_version_conflict(
        session,
        course_id=course_id,
        package_key=compiled.package_key,
        version=compiled.version,
        package_hash=compiled.package_sha256,
    )
    if conflict == "version_conflict":
        _raise(
            "相同版本已存在不同内容，请提升版本号后重新导入。",
            error_code="QUESTION_TYPE_VERSION_CONFLICT",
            status_code=409,
            data={"existing_version_id": existing_version_id},
        )

    registry = session.exec(
        select(QuestionTypeRegistry).where(
            QuestionTypeRegistry.scope == "course",
            QuestionTypeRegistry.course_id == course_id,
            QuestionTypeRegistry.type_key == compiled.type_key,
        )
    ).first()
    if registry is not None and (registry.is_system or registry.source != "upload"):
        _raise(
            "题型标识与现有非上传题型冲突，请修改 package_key 后重新导入。",
            error_code="QUESTION_TYPE_KEY_CONFLICT",
            status_code=409,
        )

    if conflict != "already_installed":
        version_count = int(
            session.exec(
                select(func.count())
                .select_from(QuestionTypePackageVersion)
                .where(
                    QuestionTypePackageVersion.course_id == course_id,
                    QuestionTypePackageVersion.package_key == compiled.package_key,
                )
            ).one()
        )
        if version_count >= MAX_INSTALLED_VERSIONS_PER_TYPE:
            _raise(
                "该题型安装版本数量已达上限，请使用新的 package_key。",
                error_code="QUESTION_TYPE_VERSION_LIMIT_EXCEEDED",
                status_code=409,
            )
        installed_asset_bytes = int(
            session.exec(
                select(func.coalesce(func.sum(QuestionTypePackageAsset.size_bytes), 0)).where(
                    QuestionTypePackageAsset.course_id == course_id
                )
            ).one()
        )
        incoming_asset_bytes = sum(item.size_bytes for item in compiled.assets)
        if installed_asset_bytes + incoming_asset_bytes > MAX_INSTALLED_ASSET_BYTES_PER_COURSE:
            _raise(
                "当前课程的题型资源已达到 100 MB 上限。",
                error_code="QUESTION_TYPE_ASSET_QUOTA_EXCEEDED",
                status_code=413,
            )
        if registry is None:
            uploaded_type_count = int(
                session.exec(
                    select(func.count())
                    .select_from(QuestionTypeRegistry)
                    .where(
                        QuestionTypeRegistry.course_id == course_id,
                        QuestionTypeRegistry.scope == "course",
                        QuestionTypeRegistry.source == "upload",
                    )
                ).one()
            )
            if uploaded_type_count >= MAX_UPLOADED_TYPES_PER_COURSE:
                _raise(
                    "当前课程安装的上传题型已达上限。",
                    error_code="QUESTION_TYPE_COURSE_LIMIT_EXCEEDED",
                    status_code=409,
                )

    if conflict == "already_installed" and existing_version_id is not None:
        existing = session.get(QuestionTypePackageVersion, existing_version_id)
        if existing is None or registry is None:
            _raise(
                "已安装题型版本引用不完整，请联系管理员检查数据。",
                error_code="QUESTION_TYPE_VERSION_CORRUPTED",
                status_code=409,
            )
        public_definition = _json_value(existing.public_preview_json, {})
        if set_current and not existing.is_current:
            _set_current_version(
                session,
                registry=registry,
                version=existing,
                public_definition=public_definition,
            )
        record.status = "installed"
        record.installed_version_id = existing.id
        record.archive_base64 = ""
        record.compiled_definition_json = "{}"
        record.updated_at = utcnow()
        session.add(record)
        runtime_ready = _stored_runtime_availability(existing).ready
        return QuestionTypePackageInstallData(
            registry_id=registry.id or 0,
            version_id=existing.id or 0,
            type_key=existing.type_key,
            version=existing.version,
            status=registry.status,
            runtime_ready=runtime_ready,
            already_installed=True,
        )

    archive = _load_import_archive(record)
    if archive.package_sha256 != compiled.package_sha256:
        _raise(
            "题型包暂存内容完整性校验失败，请重新上传。",
            error_code="QUESTION_TYPE_IMPORT_CORRUPTED",
            status_code=409,
        )

    now = utcnow()
    runtime_ready = _runtime_availability(compiled).ready
    if registry is None:
        registry = QuestionTypeRegistry(
            type_key=compiled.type_key,
            display_name=compiled.display_name,
            scope="course",
            course_id=course_id,
            description=compiled.description,
            answer_format=_answer_format(compiled),
            grading_method="llm",
            option_schema_json=_json_dumps(
                {"fields": [item.model_dump(mode="json") for item in compiled.answer_fields]}
            ),
            rubric_json=_json_dumps(
                {
                    "pass_score": compiled.pass_score,
                    "items": [item.model_dump(mode="json") for item in compiled.rubric],
                }
            ),
            source="upload",
            status="active" if runtime_ready else "inactive",
            confidence=1.0,
            is_system=False,
            is_active=runtime_ready,
            created_at=now,
            updated_at=now,
        )
        session.add(registry)
        session.flush()

    public_definition = build_public_definition(compiled)
    version = QuestionTypePackageVersion(
        registry_id=registry.id or 0,
        course_id=course_id,
        user_id=user_id,
        package_key=compiled.package_key,
        type_key=compiled.type_key,
        version=compiled.version,
        package_hash=compiled.package_sha256,
        source_filename=record.original_filename,
        compiled_definition_json=compiled.model_dump_json(),
        public_preview_json=_json_dumps(public_definition),
        profile_eligible=False,
        is_current=set_current or not bool(
            session.exec(
                select(QuestionTypePackageVersion.id).where(
                    QuestionTypePackageVersion.registry_id == registry.id,
                    QuestionTypePackageVersion.is_current == True,  # noqa: E712
                )
            ).first()
        ),
        created_at=now,
    )
    if version.is_current:
        session.exec(
            sa.update(QuestionTypePackageVersion)
            .where(QuestionTypePackageVersion.registry_id == registry.id)
            .values(is_current=False)
            .execution_options(synchronize_session=False)
        )
    session.add(version)
    session.flush()

    compiled_asset_by_path = {asset.path: asset for asset in compiled.assets}
    for asset_path, asset in compiled_asset_by_path.items():
        content = archive.files.get(asset_path)
        if content is None:
            _raise(
                f"题型资源 `{asset_path}` 缺失，请重新上传。",
                error_code="QUESTION_TYPE_IMPORT_CORRUPTED",
                status_code=409,
            )
        session.add(
            QuestionTypePackageAsset(
                package_version_id=version.id or 0,
                course_id=course_id,
                path=asset_path,
                role=asset.role,
                media_type=asset.media_type,
                sha256=asset.sha256,
                size_bytes=asset.size_bytes,
                width=asset.width,
                height=asset.height,
                content_base64=base64.b64encode(content).decode("ascii"),
                created_at=now,
            )
        )

    if version.is_current:
        _set_current_version(
            session,
            registry=registry,
            version=version,
            public_definition=public_definition,
        )
    record.status = "installed"
    record.installed_version_id = version.id
    record.archive_base64 = ""
    record.compiled_definition_json = "{}"
    record.updated_at = now
    session.add(record)
    session.flush()
    return QuestionTypePackageInstallData(
        registry_id=registry.id or 0,
        version_id=version.id or 0,
        type_key=version.type_key,
        version=version.version,
        status=registry.status,
        runtime_ready=runtime_ready,
        already_installed=False,
    )


def _version_response(version: QuestionTypePackageVersion) -> QuestionTypePackageVersionResponse:
    return QuestionTypePackageVersionResponse(
        id=version.id or 0,
        version=version.version,
        package_hash=version.package_hash,
        source_filename=version.source_filename,
        is_current=version.is_current,
        profile_eligible=version.profile_eligible,
        created_at=version.created_at,
    )


def list_question_type_catalog(
    session: Session,
    *,
    course_id: str,
) -> list[QuestionTypeCatalogItemResponse]:
    registries = list(
        session.exec(
            select(QuestionTypeRegistry)
            .where(
                sa.or_(
                    QuestionTypeRegistry.scope == "global",
                    QuestionTypeRegistry.course_id == course_id,
                )
            )
            .order_by(
                QuestionTypeRegistry.scope.asc(),
                QuestionTypeRegistry.course_id.asc(),
                QuestionTypeRegistry.type_key.asc(),
            )
        ).all()
    )
    versions = list(
        session.exec(
            select(QuestionTypePackageVersion)
            .where(QuestionTypePackageVersion.course_id == course_id)
            .order_by(QuestionTypePackageVersion.created_at.desc())
        ).all()
    )
    versions_by_registry: dict[int, list[QuestionTypePackageVersion]] = defaultdict(list)
    for version in versions:
        versions_by_registry[version.registry_id].append(version)

    catalog: list[QuestionTypeCatalogItemResponse] = []
    for registry in registries:
        registry_versions = versions_by_registry.get(registry.id or 0, [])
        current = next((item for item in registry_versions if item.is_current), None)
        public = _json_value(current.public_preview_json, {}) if current is not None else {}
        is_system = bool(registry.is_system)
        runtime_availability = _stored_runtime_availability(current)
        runtime_ready = (
            is_system
            or is_supported_question_type(registry.type_key)
            or runtime_availability.ready
        )
        catalog.append(
            QuestionTypeCatalogItemResponse(
                id=registry.id or 0,
                type_key=registry.type_key,
                display_name=registry.display_name,
                scope=registry.scope,
                course_id=registry.course_id,
                description=registry.description,
                answer_format=registry.answer_format,
                grading_method=registry.grading_method,
                option_schema=_json_value(registry.option_schema_json, {}),
                rubric=_json_value(registry.rubric_json, {}),
                source=registry.source,
                confidence=registry.confidence,
                is_system=is_system,
                is_active=bool(registry.is_active),
                status=getattr(registry, "status", "active") or "active",
                package_key=public.get("package_key"),
                current_version_id=current.id if current is not None else None,
                current_version=current.version if current is not None else None,
                template_key=public.get("template_key"),
                runtime_key=public.get("runtime_key"),
                renderer_key=public.get("renderer_key"),
                grader_key=public.get("grader_key"),
                modes=list(public.get("modes") or BUILTIN_MODES),
                runtime_ready=runtime_ready,
                runtime_message=(
                    ""
                    if runtime_ready
                    else runtime_availability.message
                    or PACKAGE_RUNTIME_UNAVAILABLE_MESSAGE
                ),
                answer_fields=[
                    QuestionTypeAnswerFieldResponse.model_validate(item)
                    for item in list(public.get("answer_fields") or [])
                ],
                versions=[_version_response(item) for item in registry_versions],
                created_at=registry.created_at,
                updated_at=registry.updated_at,
            )
        )
    return catalog


def get_question_type_catalog_item(
    session: Session,
    *,
    course_id: str,
    registry_id: int,
) -> QuestionTypeCatalogItemResponse:
    item = next(
        (
            item
            for item in list_question_type_catalog(session, course_id=course_id)
            if item.id == registry_id
        ),
        None,
    )
    if item is None:
        _raise(
            "课程题型不存在。",
            error_code="QUESTION_TYPE_NOT_FOUND",
            status_code=404,
        )
    return item


def update_question_type_catalog_item(
    session: Session,
    *,
    course_id: str,
    registry_id: int,
    status: str | None,
    current_version_id: int | None,
) -> QuestionTypeCatalogItemResponse:
    registry = session.exec(
        select(QuestionTypeRegistry).where(
            QuestionTypeRegistry.id == registry_id,
            QuestionTypeRegistry.course_id == course_id,
            QuestionTypeRegistry.scope == "course",
        )
    ).first()
    if registry is None:
        _raise(
            "课程上传题型不存在。",
            error_code="QUESTION_TYPE_NOT_FOUND",
            status_code=404,
        )
    assert registry is not None
    if registry.is_system or registry.source != "upload":
        _raise(
            "只有通过题型包安装的课程题型可以在这里修改。",
            error_code="QUESTION_TYPE_IMMUTABLE",
            status_code=409,
        )

    selected_version: QuestionTypePackageVersion | None = None
    if current_version_id is not None:
        selected_version = session.exec(
            select(QuestionTypePackageVersion).where(
                QuestionTypePackageVersion.id == current_version_id,
                QuestionTypePackageVersion.registry_id == registry.id,
                QuestionTypePackageVersion.course_id == course_id,
            )
        ).first()
        if selected_version is None:
            _raise(
                "题型版本不存在或不属于当前题型。",
                error_code="QUESTION_TYPE_VERSION_NOT_FOUND",
                status_code=404,
            )
        public = _json_value(selected_version.public_preview_json, {})
        _set_current_version(
            session,
            registry=registry,
            version=selected_version,
            public_definition=public,
        )

    if status == "active":
        if selected_version is None:
            selected_version = session.exec(
                select(QuestionTypePackageVersion).where(
                    QuestionTypePackageVersion.registry_id == registry.id,
                    QuestionTypePackageVersion.course_id == course_id,
                    QuestionTypePackageVersion.is_current == True,  # noqa: E712
                )
            ).first()
        availability = _stored_runtime_availability(selected_version)
        if not availability.ready:
            _raise(
                availability.message or PACKAGE_RUNTIME_UNAVAILABLE_MESSAGE,
                error_code="QUESTION_TYPE_RUNTIME_UNAVAILABLE",
                status_code=409,
            )

    if status is not None:
        registry.status = status
        registry.is_active = status == "active"
        registry.updated_at = utcnow()
        session.add(registry)
    session.flush()
    return get_question_type_catalog_item(
        session,
        course_id=course_id,
        registry_id=registry.id or 0,
    )


def get_question_type_asset(
    session: Session,
    *,
    course_id: str,
    asset_id: int,
) -> tuple[QuestionTypePackageAsset, bytes]:
    asset = session.exec(
        select(QuestionTypePackageAsset).where(
            QuestionTypePackageAsset.id == asset_id,
            QuestionTypePackageAsset.course_id == course_id,
        )
    ).first()
    if asset is None:
        _raise(
            "题型资源不存在。",
            error_code="QUESTION_TYPE_ASSET_NOT_FOUND",
            status_code=404,
        )
    assert asset is not None
    try:
        content = base64.b64decode(asset.content_base64, validate=True)
    except (TypeError, ValueError) as exc:
        _raise(
            "题型资源内容已损坏。",
            error_code="QUESTION_TYPE_ASSET_CORRUPTED",
            status_code=409,
        )
        raise AssertionError("unreachable") from exc
    if len(content) != asset.size_bytes or hashlib.sha256(content).hexdigest() != asset.sha256:
        _raise(
            "题型资源完整性校验失败。",
            error_code="QUESTION_TYPE_ASSET_CORRUPTED",
            status_code=409,
        )
    return asset, content


__all__ = [
    "PACKAGE_RUNTIME_UNAVAILABLE_MESSAGE",
    "build_public_definition",
    "build_validation_preview",
    "create_pending_import",
    "get_question_type_asset",
    "get_question_type_catalog_item",
    "install_pending_import",
    "list_question_type_catalog",
    "update_question_type_catalog_item",
]
