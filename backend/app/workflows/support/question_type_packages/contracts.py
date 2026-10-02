"""Contracts for validating and compiling declarative question-type packages.

The support workflow and command-line tooling share these models. They describe
package metadata only; generation and grading execution stay in Examine lanes.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.shared.kernel.question_type_compatibility import (
    LEGACY_SCHEMA_ID,
    LEGACY_TEMPLATE_FIELDS,
    TEXT_FORM_SCHEMA_ID,
    TEXT_FORM_TEMPLATE_KEY,
)


ATQSKILL_SCHEMA_ID = LEGACY_SCHEMA_ID
ATQSKILL_SCHEMA_ID_V2 = TEXT_FORM_SCHEMA_ID
REFERENCE_CASES_SCHEMA_ID = "aiteachme.question-skill-cases/v1"
REFERENCE_CASES_SCHEMA_ID_V2 = "aiteachme.question-skill-cases/v2"
TOOL_BINDINGS_SCHEMA_ID = "aiteachme.question-skill-tools/v1"
ATQSKILL_SUFFIX = ".atqskill"

ALLOWED_TEMPLATE_KEYS = frozenset(LEGACY_TEMPLATE_FIELDS)
ALLOWED_V2_TEMPLATE_KEYS = frozenset({TEXT_FORM_TEMPLATE_KEY})
SUPPORTED_ATQSKILL_SCHEMA_IDS = frozenset({ATQSKILL_SCHEMA_ID, ATQSKILL_SCHEMA_ID_V2})
SUPPORTED_REFERENCE_CASES_SCHEMA_IDS = frozenset({
    REFERENCE_CASES_SCHEMA_ID,
    REFERENCE_CASES_SCHEMA_ID_V2,
})
ALLOWED_RUNTIME_KEYS = frozenset({"structured_subjective_v1"})
ALLOWED_RENDERER_KEYS = frozenset({"long_text_v1", "structured_text_v1"})
ALLOWED_GRADER_KEYS = frozenset({"rubric_llm_v1"})
ALLOWED_MODE_KEYS = frozenset(
    {"question_bank", "mastery_drill", "web_practice", "paper_exam", "pdf"}
)
ALLOWED_TOOL_IDS = frozenset(
    {
        "rubric_coverage_v1",
        "keyword_match_v1",
        "math_equivalence_v1",
        "json_schema_validate_v1",
    }
)
ALLOWED_PROMPT_VARIABLES = frozenset(
    {
        "course_name",
        "course_description",
        "knowledge_units",
        "difficulty",
        "answer_schema",
        "rubric",
        "reference_examples",
    }
)

MAX_PACKAGE_BYTES = 8 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 24 * 1024 * 1024
MAX_PACKAGE_FILES = 100
MAX_MEMBER_BYTES = 4 * 1024 * 1024
MAX_PATH_CHARS = 240
MAX_DIRECTORY_DEPTH = 5
MAX_COMPRESSION_RATIO = 100
MAX_SKILL_MARKDOWN_BYTES = 32 * 1024
MAX_PROMPT_BYTES = 32 * 1024
MAX_REFERENCE_BYTES = 256 * 1024
MAX_TOOL_BINDINGS_BYTES = 32 * 1024
MAX_TOTAL_ANSWER_CHARS = 20_000
MAX_IMAGE_EDGE_PIXELS = 4096
MAX_IMAGE_PIXELS = 16_000_000


class PackageValidationIssue(BaseModel):
    """Stable, user-facing validation issue."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    path: str
    message: str


class PackagePreview(BaseModel):
    """Safe metadata suitable for an eventual import preview UI."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    package_key: str
    type_key: str
    version: str
    name: str
    description: str
    template_key: str
    runtime_key: str
    renderer_key: str
    grader_key: str
    modes: list[str]
    answer_field_count: int = Field(ge=0)
    rubric_item_count: int = Field(ge=0)
    tool_ids: list[str] = Field(default_factory=list)
    asset_count: int = Field(default=0, ge=0)


class CompiledAnswerField(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    label: str
    control: Literal["short_text", "long_text"]
    required: bool
    min_length: int = Field(ge=0)
    max_length: int = Field(ge=1)
    placeholder: str = ""


class CompiledRubricItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    label: str
    weight: float = Field(gt=0.0, le=1.0)
    description: str


class CompiledToolBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    required: bool


class CompiledReferenceAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: Literal["strong", "partial", "wrong"]
    content: str | dict[str, str]
    expected_score_min: float = Field(ge=0.0, le=1.0)
    expected_score_max: float = Field(ge=0.0, le=1.0)
    expected_pass: bool


class CompiledReferenceCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    knowledge_unit: dict[str, str]
    question: dict[str, str | dict[str, str]]
    answers: list[CompiledReferenceAnswer]


class CompiledAsset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    role: Literal["cover", "example", "illustration"]
    media_type: str
    size_bytes: int = Field(ge=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    sha256: str


class CompiledQuestionTypeDefinition(BaseModel):
    """Version-frozen output consumed by later import/runtime phases."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    package_key: str
    type_key: str
    version: str
    display_name: str
    description: str
    template_key: str
    runtime_key: str
    renderer_key: str
    grader_key: str
    modes: list[str]
    hints: bool
    immediate_feedback: bool
    answer_fields: list[CompiledAnswerField]
    pass_score: float = Field(ge=0.0, le=1.0)
    rubric: list[CompiledRubricItem]
    prompts: dict[str, str]
    tool_bindings: list[CompiledToolBinding]
    reference_cases: list[CompiledReferenceCase]
    assets: list[CompiledAsset]
    documentation_markdown: str
    package_sha256: str
    file_sha256: dict[str, str]
    manifest: dict[str, Any]


class PackageValidationResult(BaseModel):
    """Validation result returned by the library and CLI."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    package_hash: str = ""
    errors: list[PackageValidationIssue] = Field(default_factory=list)
    warnings: list[PackageValidationIssue] = Field(default_factory=list)
    preview: PackagePreview | None = None
    compiled_definition: CompiledQuestionTypeDefinition | None = None


class AtqSkillPackageError(ValueError):
    """Internal fail-fast error converted into a stable validation result."""

    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(message)
        self.issue = PackageValidationIssue(code=code, path=path, message=message)


class AtqSkillValidationError(ValueError):
    """Raised by compile_atqskill when a package is not valid."""

    def __init__(self, result: PackageValidationResult) -> None:
        super().__init__(result.errors[0].message if result.errors else "题型包校验失败。")
        self.result = result


__all__ = [
    "ALLOWED_GRADER_KEYS",
    "ALLOWED_MODE_KEYS",
    "ALLOWED_PROMPT_VARIABLES",
    "ALLOWED_RENDERER_KEYS",
    "ALLOWED_RUNTIME_KEYS",
    "ALLOWED_TEMPLATE_KEYS",
    "ALLOWED_V2_TEMPLATE_KEYS",
    "ALLOWED_TOOL_IDS",
    "ATQSKILL_SCHEMA_ID",
    "ATQSKILL_SCHEMA_ID_V2",
    "ATQSKILL_SUFFIX",
    "AtqSkillPackageError",
    "AtqSkillValidationError",
    "CompiledAsset",
    "CompiledQuestionTypeDefinition",
    "MAX_COMPRESSION_RATIO",
    "MAX_DIRECTORY_DEPTH",
    "MAX_IMAGE_EDGE_PIXELS",
    "MAX_IMAGE_PIXELS",
    "MAX_MEMBER_BYTES",
    "MAX_PACKAGE_BYTES",
    "MAX_PACKAGE_FILES",
    "MAX_PROMPT_BYTES",
    "MAX_REFERENCE_BYTES",
    "MAX_SKILL_MARKDOWN_BYTES",
    "MAX_TOOL_BINDINGS_BYTES",
    "MAX_TOTAL_ANSWER_CHARS",
    "MAX_UNCOMPRESSED_BYTES",
    "MAX_PATH_CHARS",
    "PackagePreview",
    "PackageValidationIssue",
    "PackageValidationResult",
    "REFERENCE_CASES_SCHEMA_ID",
    "REFERENCE_CASES_SCHEMA_ID_V2",
    "SUPPORTED_ATQSKILL_SCHEMA_IDS",
    "SUPPORTED_REFERENCE_CASES_SCHEMA_IDS",
    "TOOL_BINDINGS_SCHEMA_ID",
]
