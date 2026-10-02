"""Published runtime capabilities for declarative question-type packages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.shared.kernel.question_type_compatibility import (
    LEGACY_TEMPLATE_FIELDS,
    TEXT_FORM_TEMPLATE_KEY,
    supports_text_form_definition,
)


RUBRIC_WEIGHT_SUM_TOLERANCE = 0.001


ENABLED_CUSTOM_TEMPLATE_KEYS = frozenset(LEGACY_TEMPLATE_FIELDS)
SUPPORTED_CUSTOM_TEMPLATE_KEYS = frozenset(
    {*ENABLED_CUSTOM_TEMPLATE_KEYS, TEXT_FORM_TEMPLATE_KEY}
)
AVAILABLE_CUSTOM_RUNTIME_KEYS = frozenset({"structured_subjective_v1"})
AVAILABLE_CUSTOM_RENDERER_KEYS = frozenset({"long_text_v1", "structured_text_v1"})
AVAILABLE_CUSTOM_GRADER_KEYS = frozenset({"rubric_llm_v1"})
AVAILABLE_CUSTOM_TOOL_IDS = frozenset({"rubric_coverage_v1"})


@dataclass(frozen=True)
class QuestionTypeRuntimeAvailability:
    ready: bool
    message: str = ""


def assess_custom_question_type_runtime(
    definition: Mapping[str, object],
    *,
    mode: str | None = None,
) -> QuestionTypeRuntimeAvailability:
    """Fail closed unless every declared required capability is published."""

    checks = (
        (supports_text_form_definition(definition), "题型模板尚未发布"),
        (str(definition.get("runtime_key") or "") in AVAILABLE_CUSTOM_RUNTIME_KEYS, "题型运行时尚未发布"),
        (str(definition.get("renderer_key") or "") in AVAILABLE_CUSTOM_RENDERER_KEYS, "题型作答组件尚未发布"),
        (str(definition.get("grader_key") or "") in AVAILABLE_CUSTOM_GRADER_KEYS, "题型判分器尚未发布"),
    )
    for passed, message in checks:
        if not passed:
            return QuestionTypeRuntimeAvailability(False, message)

    raw_bindings = definition.get("tool_bindings")
    bindings: Sequence[object] = raw_bindings if isinstance(raw_bindings, list | tuple) else ()
    missing_required_tools = sorted(
        str(binding.get("id") or "")
        for binding in bindings
        if isinstance(binding, Mapping)
        and bool(binding.get("required"))
        and str(binding.get("id") or "") not in AVAILABLE_CUSTOM_TOOL_IDS
    )
    if missing_required_tools:
        return QuestionTypeRuntimeAvailability(
            False,
            f"缺少必需的系统工具：{', '.join(missing_required_tools)}",
        )

    if mode:
        raw_modes = definition.get("modes")
        modes = {str(item) for item in raw_modes} if isinstance(raw_modes, list | tuple | set) else set()
        if mode not in modes:
            return QuestionTypeRuntimeAvailability(False, "该题型不支持当前训练模式")

    return QuestionTypeRuntimeAvailability(True, "")


__all__ = [
    "AVAILABLE_CUSTOM_GRADER_KEYS",
    "AVAILABLE_CUSTOM_RENDERER_KEYS",
    "AVAILABLE_CUSTOM_RUNTIME_KEYS",
    "AVAILABLE_CUSTOM_TOOL_IDS",
    "ENABLED_CUSTOM_TEMPLATE_KEYS",
    "SUPPORTED_CUSTOM_TEMPLATE_KEYS",
    "QuestionTypeRuntimeAvailability",
    "RUBRIC_WEIGHT_SUM_TOLERANCE",
    "assess_custom_question_type_runtime",
]
