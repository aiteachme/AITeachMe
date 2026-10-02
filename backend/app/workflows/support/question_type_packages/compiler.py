"""Compile already validated question-type package content.

The compiler produces one version-frozen, path-independent definition. It performs
no I/O and does not execute package prompts, tools or assets.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from app.workflows.support.question_type_packages.archive import AtqSkillArchive
from app.workflows.support.question_type_packages.contracts import (
    CompiledAnswerField,
    CompiledAsset,
    CompiledQuestionTypeDefinition,
    CompiledReferenceAnswer,
    CompiledReferenceCase,
    CompiledRubricItem,
    CompiledToolBinding,
)


def build_compiled_definition(
    *,
    archive: AtqSkillArchive,
    manifest: dict[str, Any],
    documentation_markdown: str,
    prompts: Mapping[str, str],
    reference_payload: dict[str, Any],
    tool_payload: dict[str, Any] | None,
    assets: list[CompiledAsset],
) -> CompiledQuestionTypeDefinition:
    """Build the stable definition persisted by a later installation phase."""

    answer_fields = [CompiledAnswerField.model_validate(item) for item in manifest["answer_schema"]["fields"]]
    rubric = [CompiledRubricItem.model_validate(item) for item in manifest["grading"]["rubric"]]
    tool_bindings = [
        CompiledToolBinding.model_validate(item)
        for item in list((tool_payload or {}).get("tools") or [])
    ]
    reference_cases: list[CompiledReferenceCase] = []
    for case in reference_payload["cases"]:
        answers = [
            CompiledReferenceAnswer(
                label=answer["label"],
                content=answer["content"],
                expected_score_min=float(answer["expected_score"]["min"]),
                expected_score_max=float(answer["expected_score"]["max"]),
                expected_pass=bool(answer["expected_pass"]),
            )
            for answer in case["answers"]
        ]
        reference_cases.append(
            CompiledReferenceCase(
                id=case["id"],
                knowledge_unit=dict(case["knowledge_unit"]),
                question=dict(case["question"]),
                answers=answers,
            )
        )

    capabilities = manifest["capabilities"]
    return CompiledQuestionTypeDefinition(
        schema_version=manifest["schema"],
        package_key=manifest["package_key"],
        type_key=f"custom_{manifest['package_key']}",
        version=manifest["version"],
        display_name=manifest["name"],
        description=manifest["description"],
        template_key=manifest["template_key"],
        runtime_key=manifest["runtime_key"],
        renderer_key=manifest["renderer_key"],
        grader_key=manifest["grader_key"],
        modes=list(capabilities["modes"]),
        hints=bool(capabilities["hints"]),
        immediate_feedback=bool(capabilities["immediate_feedback"]),
        answer_fields=answer_fields,
        pass_score=float(manifest["grading"]["pass_score"]),
        rubric=rubric,
        prompts=dict(prompts),
        tool_bindings=tool_bindings,
        reference_cases=reference_cases,
        assets=sorted(assets, key=lambda item: item.path),
        documentation_markdown=documentation_markdown,
        package_sha256=archive.package_sha256,
        file_sha256=dict(sorted(archive.file_sha256.items())),
        manifest=deepcopy(manifest),
    )


__all__ = ["build_compiled_definition"]
