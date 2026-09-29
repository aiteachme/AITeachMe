"""Resolve a mixed selection to immutable runtimes and deterministic quotas."""

from __future__ import annotations

from sqlmodel import Session

from app.models import QuestionTypeRegistry
from app.schemas.exams import QuestionTypeSelection
from app.shared.kernel.question_types import require_supported_question_type_key
from app.workflows.examine.question_types.runtime import (
    QuestionTypeRuntimeError,
    ResolvedQuestionTypeRuntime,
    resolve_course_question_type_runtimes,
    resolve_question_type_version,
)


def allocate_type_counts(types: list[str], question_count: int) -> dict[str, int]:
    if not types:
        return {}
    if len(types) > question_count:
        raise QuestionTypeRuntimeError("QUESTION_TYPE_COUNT_EXCEEDS_QUESTIONS", "题量不能少于所选题型数量。")
    base, remainder = divmod(question_count, len(types))
    return {key: base + (index < remainder) for index, key in enumerate(types)}


def resolve_question_type_selection(
    session: Session,
    *,
    course_id: str,
    mode: str,
    question_count: int,
    selections: list[QuestionTypeSelection],
    legacy_types: list[str],
    legacy_registry_ids: list[int],
) -> tuple[list[str], list[ResolvedQuestionTypeRuntime], dict[str, int]]:
    if not selections:
        selections = [QuestionTypeSelection(question_type=key) for key in dict.fromkeys(legacy_types)] + [
            QuestionTypeSelection(registry_id=value) for value in dict.fromkeys(legacy_registry_ids)
        ]
    types: list[str] = []
    runtimes: list[ResolvedQuestionTypeRuntime] = []
    explicit_counts: dict[str, int] = {}
    for selection in selections:
        if selection.question_type:
            type_key = require_supported_question_type_key(selection.question_type)
        else:
            if selection.version_id is None:
                runtime = resolve_course_question_type_runtimes(
                    session, course_id=course_id, registry_ids=[int(selection.registry_id or 0)], mode=mode,
                )[0]
            else:
                runtime = resolve_question_type_version(
                    session, course_id=course_id, version_id=selection.version_id, mode=mode,
                )
                registry = session.get(QuestionTypeRegistry, selection.registry_id)
                if runtime.registry_id != selection.registry_id:
                    raise QuestionTypeRuntimeError("QUESTION_TYPE_VERSION_MISMATCH", "题型版本不属于所选注册项。")
                if registry is None or registry.source != "upload" or registry.scope != "course" or registry.status != "active" or not registry.is_active:
                    raise QuestionTypeRuntimeError("QUESTION_TYPE_NOT_ACTIVE", "所选题型已停用或归档。")
            type_key = runtime.type_key
            runtimes.append(runtime)
        if type_key in types:
            raise QuestionTypeRuntimeError("QUESTION_TYPE_DUPLICATE", "同一题型不能重复选择。")
        types.append(type_key)
        if selection.count is not None:
            explicit_counts[type_key] = selection.count
    balanced_counts = allocate_type_counts(types, question_count)
    if explicit_counts:
        if set(explicit_counts) != set(types) or sum(explicit_counts.values()) != question_count:
            raise QuestionTypeRuntimeError("QUESTION_TYPE_QUOTA_INVALID", "各题型数量之和必须等于总题量。")
        return types, runtimes, explicit_counts
    return types, runtimes, balanced_counts
