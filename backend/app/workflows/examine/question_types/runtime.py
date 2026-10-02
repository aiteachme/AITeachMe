"""Resolve immutable installed package versions for generation and grading."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlmodel import Session, select

from app.models import QuestionTypePackageVersion, QuestionTypeRegistry
from app.shared.kernel.question_type_runtime import assess_custom_question_type_runtime
from app.workflows.support.question_type_packages.contracts import CompiledQuestionTypeDefinition


class QuestionTypeRuntimeError(ValueError):
    """Raised when a selected question type cannot execute in the requested context."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ResolvedQuestionTypeRuntime:
    registry_id: int
    version_id: int
    course_id: str
    type_key: str
    version: str
    package_hash: str
    profile_eligible: bool
    definition: CompiledQuestionTypeDefinition

    def workflow_payload(self) -> dict[str, object]:
        return {
            "registry_id": self.registry_id,
            "version_id": self.version_id,
            "course_id": self.course_id,
            "type_key": self.type_key,
            "version": self.version,
            "package_hash": self.package_hash,
            "profile_eligible": self.profile_eligible,
            "definition": self.definition.model_dump(mode="json"),
        }

    def snapshot_payload(self) -> dict[str, object]:
        return {
            "registry_id": self.registry_id,
            "version_id": self.version_id,
            "type_key": self.type_key,
            "version": self.version,
            "package_hash": self.package_hash,
            "template_key": self.definition.template_key,
            "runtime_key": self.definition.runtime_key,
            "renderer_key": self.definition.renderer_key,
            "grader_key": self.definition.grader_key,
            "profile_eligible": self.profile_eligible,
        }


def _compiled_definition(version: QuestionTypePackageVersion) -> CompiledQuestionTypeDefinition:
    try:
        return CompiledQuestionTypeDefinition.model_validate_json(version.compiled_definition_json)
    except Exception as exc:  # noqa: BLE001 - stored data must fail closed
        raise QuestionTypeRuntimeError(
            "QUESTION_TYPE_VERSION_CORRUPTED",
            "\u9898\u578b\u7248\u672c\u5185\u5bb9\u5df2\u635f\u574f\uff0c\u8bf7\u91cd\u65b0\u5bfc\u5165\u9898\u578b\u5305\u3002",
        ) from exc


def _resolved_runtime(
    registry: QuestionTypeRegistry,
    version: QuestionTypePackageVersion,
    *,
    mode: str | None,
) -> ResolvedQuestionTypeRuntime:
    definition = _compiled_definition(version)
    if (
        definition.type_key != registry.type_key
        or version.type_key != registry.type_key
        or definition.version != version.version
        or definition.package_sha256 != version.package_hash
    ):
        raise QuestionTypeRuntimeError(
            "QUESTION_TYPE_VERSION_MISMATCH",
            "\u9898\u578b\u6ce8\u518c\u4fe1\u606f\u4e0e\u7248\u672c\u5185\u5bb9\u4e0d\u4e00\u81f4\uff0c\u8bf7\u91cd\u65b0\u5bfc\u5165\u9898\u578b\u5305\u3002",
        )
    availability = assess_custom_question_type_runtime(definition.model_dump(mode="json"), mode=mode)
    if not availability.ready:
        raise QuestionTypeRuntimeError(
            "QUESTION_TYPE_RUNTIME_UNAVAILABLE",
            availability.message
            or "\u8be5\u9898\u578b\u7684\u51fa\u9898\u6216\u5224\u5206\u80fd\u529b\u5c1a\u672a\u53d1\u5e03\u3002",
        )
    return ResolvedQuestionTypeRuntime(
        registry_id=int(registry.id or 0),
        version_id=int(version.id or 0),
        course_id=version.course_id,
        type_key=version.type_key,
        version=version.version,
        package_hash=version.package_hash,
        profile_eligible=bool(version.profile_eligible),
        definition=definition,
    )


def resolve_course_question_type_runtimes(
    session: Session,
    *,
    course_id: str,
    registry_ids: list[int],
    mode: str,
    require_active: bool = True,
) -> list[ResolvedQuestionTypeRuntime]:
    normalized_ids = list(dict.fromkeys(int(item) for item in registry_ids if int(item or 0) > 0))
    if not normalized_ids:
        return []
    registries = list(
        session.exec(
            select(QuestionTypeRegistry).where(
                QuestionTypeRegistry.id.in_(normalized_ids),
                QuestionTypeRegistry.scope == "course",
                QuestionTypeRegistry.course_id == course_id,
                QuestionTypeRegistry.source == "upload",
            )
        ).all()
    )
    by_id = {int(item.id or 0): item for item in registries}
    if set(by_id) != set(normalized_ids):
        raise QuestionTypeRuntimeError(
            "QUESTION_TYPE_NOT_FOUND",
            "\u6240\u9009\u81ea\u5b9a\u4e49\u9898\u578b\u4e0d\u5b58\u5728\u6216\u4e0d\u5c5e\u4e8e\u5f53\u524d\u8bfe\u7a0b\u3002",
        )

    resolved: list[ResolvedQuestionTypeRuntime] = []
    for registry_id in normalized_ids:
        registry = by_id[registry_id]
        if require_active and (registry.status != "active" or not registry.is_active):
            raise QuestionTypeRuntimeError(
                "QUESTION_TYPE_NOT_ACTIVE",
                f"\u9898\u578b\u201c{registry.display_name}\u201d\u5c1a\u672a\u542f\u7528\u3002",
            )
        version = session.exec(
            select(QuestionTypePackageVersion).where(
                QuestionTypePackageVersion.registry_id == registry_id,
                QuestionTypePackageVersion.course_id == course_id,
                QuestionTypePackageVersion.is_current == True,  # noqa: E712
            )
        ).first()
        if version is None:
            raise QuestionTypeRuntimeError(
                "QUESTION_TYPE_VERSION_NOT_FOUND",
                f"\u9898\u578b\u201c{registry.display_name}\u201d\u6ca1\u6709\u53ef\u7528\u7248\u672c\u3002",
            )
        resolved.append(_resolved_runtime(registry, version, mode=mode))
    return resolved


def resolve_question_type_version(
    session: Session,
    *,
    course_id: str,
    version_id: int,
    mode: str | None = None,
) -> ResolvedQuestionTypeRuntime:
    version = session.exec(
        select(QuestionTypePackageVersion).where(
            QuestionTypePackageVersion.id == version_id,
            QuestionTypePackageVersion.course_id == course_id,
        )
    ).first()
    if version is None:
        raise QuestionTypeRuntimeError(
            "QUESTION_TYPE_VERSION_NOT_FOUND",
            "\u9898\u76ee\u5f15\u7528\u7684\u9898\u578b\u7248\u672c\u4e0d\u5b58\u5728\u3002",
        )
    registry = session.get(QuestionTypeRegistry, version.registry_id)
    if registry is None or registry.course_id != course_id:
        raise QuestionTypeRuntimeError(
            "QUESTION_TYPE_NOT_FOUND",
            "\u9898\u76ee\u5f15\u7528\u7684\u9898\u578b\u6ce8\u518c\u4fe1\u606f\u4e0d\u5b58\u5728\u3002",
        )
    return _resolved_runtime(registry, version, mode=mode)


def runtime_payload_from_json(raw: str) -> dict[str, object]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


__all__ = [
    "QuestionTypeRuntimeError",
    "ResolvedQuestionTypeRuntime",
    "resolve_course_question_type_runtimes",
    "resolve_question_type_version",
    "runtime_payload_from_json",
]
