"""Validate and compile declarative `.atqskill` question-type packages.

This is the stable support-layer use case for local tooling and the future
upload API. It never executes package code, prompts, tools or network calls.
"""

from __future__ import annotations

import hashlib
import json
import re
import warnings
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from PIL import Image, UnidentifiedImageError

from app.shared.kernel.question_type_runtime import RUBRIC_WEIGHT_SUM_TOLERANCE
from app.shared.kernel.question_type_compatibility import LEGACY_TEMPLATE_FIELDS, LEGACY_TEMPLATE_RENDERERS
from app.workflows.support.question_type_packages.archive import (
    AtqSkillArchive,
    read_atqskill_archive,
)
from app.workflows.support.question_type_packages.compiler import build_compiled_definition
from app.workflows.support.question_type_packages.contracts import (
    ALLOWED_MODE_KEYS,
    ALLOWED_PROMPT_VARIABLES,
    ALLOWED_TOOL_IDS,
    AtqSkillPackageError,
    AtqSkillValidationError,
    CompiledAsset,
    CompiledQuestionTypeDefinition,
    MAX_IMAGE_EDGE_PIXELS,
    MAX_IMAGE_PIXELS,
    MAX_PROMPT_BYTES,
    MAX_REFERENCE_BYTES,
    MAX_SKILL_MARKDOWN_BYTES,
    MAX_TOOL_BINDINGS_BYTES,
    MAX_TOTAL_ANSWER_CHARS,
    PackagePreview,
    PackageValidationIssue,
    PackageValidationResult,
    REFERENCE_CASES_SCHEMA_ID,
    REFERENCE_CASES_SCHEMA_ID_V2,
    ATQSKILL_SCHEMA_ID,
    ATQSKILL_SCHEMA_ID_V2,
    TOOL_BINDINGS_SCHEMA_ID,
)
from app.workflows.support.question_type_packages.parser import (
    decode_utf8,
    parse_json_document,
    parse_skill_markdown,
)

_SCHEMA_DIR = Path(__file__).with_name("schemas")
_PROMPT_VARIABLE_RE = re.compile(r"\$\{([^{}\r\n]*)\}")
_REQUIRED_PROMPT_VARIABLES = {
    "generate": frozenset({"knowledge_units", "answer_schema"}),
    "grade": frozenset({"rubric", "reference_examples"}),
    "feedback": frozenset(),
}
_IMAGE_FORMATS = {
    ".png": ("PNG", "image/png"),
    ".jpg": ("JPEG", "image/jpeg"),
    ".jpeg": ("JPEG", "image/jpeg"),
    ".webp": ("WEBP", "image/webp"),
}


def _schema_files_for_manifest(manifest: dict[str, Any]) -> tuple[str, str]:
    """Resolve the external manifest/reference schemas without weakening V1."""

    if str(manifest.get("schema") or "") == ATQSKILL_SCHEMA_ID_V2:
        return "atqskill-v2.schema.json", "reference-cases-v2.schema.json"
    return "atqskill-v1.schema.json", "reference-cases-v1.schema.json"


def _is_v2_manifest(manifest: dict[str, Any]) -> bool:
    return str(manifest.get("schema") or "") == ATQSKILL_SCHEMA_ID_V2


@lru_cache(maxsize=3)
def _schema(name: str) -> dict[str, Any]:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _json_path(parts: list[object], *, root: str) -> str:
    path = root
    for part in parts:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path


def _schema_issues(
    payload: dict[str, Any],
    *,
    schema_name: str,
    code: str,
    root: str,
) -> list[PackageValidationIssue]:
    validator = Draft202012Validator(_schema(schema_name))
    errors = sorted(
        validator.iter_errors(payload),
        key=lambda item: [str(part) for part in item.absolute_path],
    )
    return [
        PackageValidationIssue(
            code=code,
            path=_json_path(list(error.absolute_path), root=root),
            message=error.message,
        )
        for error in errors[:50]
    ]


def _required_file(archive: AtqSkillArchive, path: str, errors: list[PackageValidationIssue]) -> bytes | None:
    content = archive.files.get(path)
    if content is None:
        errors.append(PackageValidationIssue(code="FILE_REFERENCE_MISSING", path=path, message="清单引用的文件不存在。"))
    return content


def _issue(code: str, path: str, message: str) -> PackageValidationIssue:
    return PackageValidationIssue(code=code, path=path, message=message)


def _read_text_file(
    archive: AtqSkillArchive,
    path: str,
    *,
    max_bytes: int,
    errors: list[PackageValidationIssue],
) -> str | None:
    content = _required_file(archive, path, errors)
    if content is None:
        return None
    if len(content) > max_bytes:
        errors.append(PackageValidationIssue(code="PACKAGE_MEMBER_TOO_LARGE", path=path, message="文件超过该类别允许的大小。"))
        return None
    try:
        text = decode_utf8(content, path=path)
    except AtqSkillPackageError as exc:
        errors.append(exc.issue)
        return None
    if not text.strip():
        errors.append(PackageValidationIssue(code="TEXT_CONTENT_INVALID", path=path, message="文本文件不能为空。"))
        return None
    return text.strip()


def _validate_prompt(path: str, prompt: str, *, prompt_name: str) -> list[PackageValidationIssue]:
    issues: list[PackageValidationIssue] = []
    if "{{" in prompt or "{%" in prompt:
        issues.append(
            PackageValidationIssue(
                code="PROMPT_TEMPLATE_SYNTAX_INVALID",
                path=path,
                message="V1 只支持 `${name}` 占位符，不支持 Jinja 模板语法。",
            )
        )
    raw_variables = _PROMPT_VARIABLE_RE.findall(prompt)
    unknown = sorted(set(raw_variables) - ALLOWED_PROMPT_VARIABLES)
    malformed = prompt.count("${") != len(raw_variables)
    if unknown or malformed:
        detail = ", ".join(unknown) if unknown else "存在未闭合或嵌套占位符"
        issues.append(
            PackageValidationIssue(
                code="PROMPT_VARIABLE_INVALID",
                path=path,
                message=f"包含不允许的提示词变量：{detail}。",
            )
        )
    missing = sorted(_REQUIRED_PROMPT_VARIABLES[prompt_name] - set(raw_variables))
    if missing:
        issues.append(
            PackageValidationIssue(
                code="PROMPT_VARIABLE_REQUIRED",
                path=path,
                message=f"缺少必需的提示词变量：{', '.join(missing)}。",
            )
        )
    return issues


def _inspect_image_asset(
    *,
    path: str,
    content: bytes,
) -> tuple[tuple[str, int, int, str] | None, list[PackageValidationIssue], list[PackageValidationIssue]]:
    errors: list[PackageValidationIssue] = []
    package_warnings: list[PackageValidationIssue] = []
    image_contract = _IMAGE_FORMATS.get(Path(path).suffix.casefold())
    if image_contract is None:
        return None, [_issue("ASSET_FORMAT_UNSUPPORTED", path, "资源必须是受支持的静态图片。")], []
    expected_format, media_type = image_contract
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                actual_format = str(image.format or "").upper()
                width, height = image.size
                animated = bool(getattr(image, "is_animated", False))
                has_metadata = bool(image.info.get("exif") or image.info.get("icc_profile"))
                if (
                    width > MAX_IMAGE_EDGE_PIXELS
                    or height > MAX_IMAGE_EDGE_PIXELS
                    or width * height > MAX_IMAGE_PIXELS
                ):
                    return None, [_issue("ASSET_DIMENSIONS_INVALID", path, "图片尺寸超过 V1 限制。")], []
                if animated:
                    return None, [_issue("ASSET_ANIMATION_UNSUPPORTED", path, "V1 不支持动画图片。")], []
                image.verify()
    except (
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        return None, [_issue("ASSET_INVALID", path, "图片无法通过格式和完整性检查。")], []
    if actual_format != expected_format:
        errors.append(_issue("ASSET_FORMAT_MISMATCH", path, "图片实际格式与扩展名不一致。"))
    if has_metadata:
        package_warnings.append(
            _issue(
                "ASSET_METADATA_PRESENT",
                path,
                "图片包含 EXIF 或 ICC 元数据，安装阶段应剥离。",
            )
        )
    if errors:
        return None, errors, package_warnings
    return (
        (media_type, width, height, hashlib.sha256(content).hexdigest()),
        [],
        package_warnings,
    )


def _validate_asset(
    archive: AtqSkillArchive,
    asset: dict[str, Any],
) -> tuple[CompiledAsset | None, list[PackageValidationIssue], list[PackageValidationIssue]]:
    path = str(asset["path"])
    content = archive.files.get(path)
    if content is None:
        return None, [_issue("FILE_REFERENCE_MISSING", path, "清单引用的图片不存在。")], []
    inspected, errors, package_warnings = _inspect_image_asset(path=path, content=content)
    if inspected is None:
        return None, errors, package_warnings
    media_type, width, height, digest = inspected
    return (
        CompiledAsset(
            path=path,
            role=asset["role"],
            media_type=media_type,
            size_bytes=len(content),
            width=width,
            height=height,
            sha256=digest,
        ),
        [],
        package_warnings,
    )


def validate_compiled_asset_content(
    asset: CompiledAsset,
    content: bytes,
) -> list[PackageValidationIssue]:
    """Revalidate imported asset bytes against the immutable image contract."""

    inspected, errors, _warnings = _inspect_image_asset(path=asset.path, content=content)
    if inspected is None:
        return errors
    media_type, width, height, digest = inspected
    if (
        asset.media_type != media_type
        or asset.size_bytes != len(content)
        or asset.width != width
        or asset.height != height
        or asset.sha256 != digest
    ):
        return [
            _issue(
                "ASSET_METADATA_MISMATCH",
                asset.path,
                "资源内容与冻结的格式、尺寸或哈希信息不一致。",
            )
        ]
    return []


def _validate_manifest_semantics(manifest: dict[str, Any]) -> list[PackageValidationIssue]:
    issues: list[PackageValidationIssue] = []
    for key in ("name", "description"):
        if not str(manifest[key]).strip():
            issues.append(
                PackageValidationIssue(
                    code="TEXT_CONTENT_INVALID",
                    path=f"$manifest.{key}",
                    message="文本字段不能只包含空白字符。",
                )
            )
    modes = list(manifest["capabilities"]["modes"])
    if set(modes) != ALLOWED_MODE_KEYS:
        issues.append(
            PackageValidationIssue(
                code="CAPABILITY_INVALID",
                path="$manifest.capabilities.modes",
                message="V1 题型必须支持题库、闯关、网页测验、考卷和 PDF。",
            )
        )
    if "paper_exam" in modes and "pdf" not in modes:
        issues.append(
            _issue(
                "CAPABILITY_INVALID",
                "$manifest.capabilities.modes",
                "支持考卷时必须同时支持 PDF。",
            )
        )
    expected_renderer = LEGACY_TEMPLATE_RENDERERS[manifest["template_key"]]
    if manifest["renderer_key"] != expected_renderer:
        issues.append(
            _issue(
                "RENDERER_INCOMPATIBLE",
                "$manifest.renderer_key",
                "renderer 与固定模板不兼容。",
            )
        )

    fields = manifest["answer_schema"]["fields"]
    field_keys = [str(item["key"]) for item in fields]
    expected_field_keys = list(LEGACY_TEMPLATE_FIELDS[manifest["template_key"]])
    if field_keys != expected_field_keys:
        issues.append(
            PackageValidationIssue(
                code="ANSWER_SCHEMA_INVALID",
                path="$manifest.answer_schema.fields",
                message=f"固定模板必须按顺序声明字段：{', '.join(expected_field_keys)}。",
            )
        )
    if len(set(field_keys)) != len(field_keys):
        issues.append(
            _issue(
                "ANSWER_SCHEMA_INVALID",
                "$manifest.answer_schema.fields",
                "作答字段 key 不能重复。",
            )
        )
    for index, field in enumerate(fields):
        if not str(field["label"]).strip():
            issues.append(
                _issue(
                    "ANSWER_SCHEMA_INVALID",
                    f"$manifest.answer_schema.fields[{index}].label",
                    "作答字段名称不能为空。",
                )
            )
        if int(field["min_length"]) > int(field["max_length"]):
            issues.append(
                _issue(
                    "ANSWER_SCHEMA_INVALID",
                    f"$manifest.answer_schema.fields[{index}]",
                    "min_length 不能大于 max_length。",
                )
            )
    if sum(int(field["max_length"]) for field in fields) > MAX_TOTAL_ANSWER_CHARS:
        issues.append(
            PackageValidationIssue(
                code="ANSWER_SCHEMA_INVALID",
                path="$manifest.answer_schema.fields",
                message="所有作答字段的 max_length 合计不能超过 20000。",
            )
        )
    if manifest["renderer_key"] == "long_text_v1":
        if len(fields) != 1 or fields[0]["control"] != "long_text":
            issues.append(
                _issue(
                    "RENDERER_INCOMPATIBLE",
                    "$manifest.answer_schema.fields",
                    "long_text_v1 必须且只能声明一个 long_text 字段。",
                )
            )
    elif len(fields) < 2:
        issues.append(
            _issue(
                "RENDERER_INCOMPATIBLE",
                "$manifest.answer_schema.fields",
                "structured_text_v1 至少需要两个作答字段。",
            )
        )

    rubric = manifest["grading"]["rubric"]
    rubric_keys = [str(item["key"]) for item in rubric]
    if len(set(rubric_keys)) != len(rubric_keys):
        issues.append(
            _issue(
                "RUBRIC_KEY_DUPLICATE",
                "$manifest.grading.rubric",
                "评分维度 key 不能重复。",
            )
        )
    weight_total = sum(float(item["weight"]) for item in rubric)
    for index, item in enumerate(rubric):
        if not str(item["label"]).strip() or not str(item["description"]).strip():
            issues.append(
                _issue(
                    "RUBRIC_TEXT_INVALID",
                    f"$manifest.grading.rubric[{index}]",
                    "评分维度名称和说明不能为空。",
                )
            )
    if abs(weight_total - 1.0) > RUBRIC_WEIGHT_SUM_TOLERANCE:
        issues.append(
            _issue(
                "RUBRIC_WEIGHT_INVALID",
                "$manifest.grading.rubric",
                "评分维度权重合计必须为 1。",
            )
        )
    return issues


def _validate_v2_manifest_semantics(manifest: dict[str, Any]) -> list[PackageValidationIssue]:
    """Validate the first generic V2 capability without changing the V1 contract."""

    issues: list[PackageValidationIssue] = []
    for key in ("name", "description"):
        if not str(manifest[key]).strip():
            issues.append(
                _issue(
                    "TEXT_CONTENT_INVALID",
                    f"$manifest.{key}",
                    "文本字段不能只包含空白字符。",
                )
            )

    modes = list(manifest["capabilities"]["modes"])
    if set(modes) != ALLOWED_MODE_KEYS:
        issues.append(
            _issue(
                "CAPABILITY_INVALID",
                "$manifest.capabilities.modes",
                "V2 文本表单题型必须支持题库、闯关、网页测验、考卷和 PDF。",
            )
        )
    if "paper_exam" in modes and "pdf" not in modes:
        issues.append(
            _issue(
                "CAPABILITY_INVALID",
                "$manifest.capabilities.modes",
                "支持考卷时必须同时支持 PDF。",
            )
        )

    if manifest["template_key"] != "generic_text_form_v2":
        issues.append(
            _issue(
                "TEMPLATE_UNSUPPORTED",
                "$manifest.template_key",
                "V2 当前只支持 generic_text_form_v2。",
            )
        )
    if manifest["runtime_key"] != "structured_subjective_v1":
        issues.append(
            _issue(
                "RUNTIME_UNSUPPORTED",
                "$manifest.runtime_key",
                "V2 当前只支持 structured_subjective_v1。",
            )
        )
    if manifest["renderer_key"] != "structured_text_v1":
        issues.append(
            _issue(
                "RENDERER_INCOMPATIBLE",
                "$manifest.renderer_key",
                "V2 当前只支持 structured_text_v1。",
            )
        )
    if manifest["grader_key"] != "rubric_llm_v1":
        issues.append(
            _issue(
                "GRADER_UNSUPPORTED",
                "$manifest.grader_key",
                "V2 当前只支持 rubric_llm_v1。",
            )
        )

    fields = manifest["answer_schema"]["fields"]
    field_keys = [str(item["key"]) for item in fields]
    if len(set(field_keys)) != len(field_keys):
        issues.append(
            _issue(
                "ANSWER_SCHEMA_INVALID",
                "$manifest.answer_schema.fields",
                "作答字段 key 不能重复。",
            )
        )
    for index, field in enumerate(fields):
        if not str(field["label"]).strip():
            issues.append(
                _issue(
                    "ANSWER_SCHEMA_INVALID",
                    f"$manifest.answer_schema.fields[{index}].label",
                    "作答字段名称不能为空。",
                )
            )
        if int(field["min_length"]) > int(field["max_length"]):
            issues.append(
                _issue(
                    "ANSWER_SCHEMA_INVALID",
                    f"$manifest.answer_schema.fields[{index}]",
                    "min_length 不能大于 max_length。",
                )
            )
    if sum(int(field["max_length"]) for field in fields) > MAX_TOTAL_ANSWER_CHARS:
        issues.append(
            _issue(
                "ANSWER_SCHEMA_INVALID",
                "$manifest.answer_schema.fields",
                "所有作答字段的 max_length 合计不能超过 20000。",
            )
        )

    rubric = manifest["grading"]["rubric"]
    rubric_keys = [str(item["key"]) for item in rubric]
    if len(set(rubric_keys)) != len(rubric_keys):
        issues.append(
            _issue(
                "RUBRIC_KEY_DUPLICATE",
                "$manifest.grading.rubric",
                "评分维度 key 不能重复。",
            )
        )
    for index, item in enumerate(rubric):
        if not str(item["label"]).strip() or not str(item["description"]).strip():
            issues.append(
                _issue(
                    "RUBRIC_TEXT_INVALID",
                    f"$manifest.grading.rubric[{index}]",
                    "评分维度名称和说明不能为空。",
                )
            )
    if abs(sum(float(item["weight"]) for item in rubric) - 1.0) > RUBRIC_WEIGHT_SUM_TOLERANCE:
        issues.append(
            _issue(
                "RUBRIC_WEIGHT_INVALID",
                "$manifest.grading.rubric",
                "评分维度权重合计必须为 1。",
            )
        )
    return issues


def _validate_reference_semantics(
    payload: dict[str, Any],
    *,
    manifest: dict[str, Any],
    path: str,
) -> list[PackageValidationIssue]:
    issues: list[PackageValidationIssue] = []
    case_ids = [str(item["id"]) for item in payload["cases"]]
    if len(set(case_ids)) != len(case_ids):
        issues.append(_issue("REFERENCE_CASE_INVALID", f"{path}.cases", "参考案例 id 不能重复。"))
    field_keys = {str(item["key"]) for item in manifest["answer_schema"]["fields"]}
    required_keys = {str(item["key"]) for item in manifest["answer_schema"]["fields"] if item["required"]}
    structured = manifest["renderer_key"] == "structured_text_v1"
    pass_score = float(manifest["grading"]["pass_score"])
    for case_index, case in enumerate(payload["cases"]):
        if manifest["schema"] == ATQSKILL_SCHEMA_ID_V2:
            from app.workflows.examine.question_types.answers import AnswerPayloadError, normalize_custom_reference_answer
            reference = case["question"]["reference_answer"]
            for location, content in [("question.reference_answer", reference), *[(f"answers[{i}].content", answer["content"]) for i, answer in enumerate(case["answers"])]]:
                try:
                    normalize_custom_reference_answer(manifest["answer_schema"], answer=content if isinstance(content, str) else None, answer_payload=content if isinstance(content, dict) else None)
                except AnswerPayloadError as exc:
                    issues.append(_issue("REFERENCE_CASE_INVALID", f"{path}.cases[{case_index}].{location}", str(exc)))
        for section_name in ("knowledge_unit", "question"):
            for field_name, value in case[section_name].items():
                if not str(value).strip():
                    issues.append(
                        _issue(
                            "REFERENCE_CASE_INVALID",
                            f"{path}.cases[{case_index}].{section_name}.{field_name}",
                            "参考案例文本不能只包含空白字符。",
                        )
                    )
        labels = [str(answer["label"]) for answer in case["answers"]]
        if len(set(labels)) != len(labels) or set(labels) != {"strong", "partial", "wrong"}:
            issues.append(
                _issue(
                    "REFERENCE_CASE_INVALID",
                    f"{path}.cases[{case_index}].answers",
                    "每个案例必须且只能包含 strong、partial、wrong 三类答案。",
                )
            )
        answers_by_label = {str(answer["label"]): answer for answer in case["answers"]}
        if set(answers_by_label) == {"strong", "partial", "wrong"}:
            if not bool(answers_by_label["strong"]["expected_pass"]):
                issues.append(
                    _issue(
                        "REFERENCE_CASE_INVALID",
                        f"{path}.cases[{case_index}].answers",
                        "strong 案例必须标记为通过。",
                    )
                )
            if bool(answers_by_label["partial"]["expected_pass"]) or bool(answers_by_label["wrong"]["expected_pass"]):
                issues.append(
                    _issue(
                        "REFERENCE_CASE_INVALID",
                        f"{path}.cases[{case_index}].answers",
                        "partial 和 wrong 案例必须标记为未通过。",
                    )
                )
            strong_min = float(answers_by_label["strong"]["expected_score"]["min"])
            partial_min = float(answers_by_label["partial"]["expected_score"]["min"])
            partial_max = float(answers_by_label["partial"]["expected_score"]["max"])
            wrong_max = float(answers_by_label["wrong"]["expected_score"]["max"])
            if wrong_max >= partial_min or partial_max >= strong_min:
                issues.append(
                    _issue(
                        "REFERENCE_CASE_INVALID",
                        f"{path}.cases[{case_index}].answers",
                        "wrong、partial、strong 的期望分数区间必须依次分离。",
                    )
                )
        for answer_index, answer in enumerate(case["answers"]):
            score = answer["expected_score"]
            if float(score["min"]) > float(score["max"]):
                issues.append(
                    _issue(
                        "REFERENCE_CASE_INVALID",
                        f"{path}.cases[{case_index}].answers[{answer_index}].expected_score",
                        "期望分数下界不能大于上界。",
                    )
                )
            if bool(answer["expected_pass"]) and float(score["min"]) < pass_score:
                issues.append(
                    _issue(
                        "REFERENCE_CASE_INVALID",
                        f"{path}.cases[{case_index}].answers[{answer_index}]",
                        "标记为通过的案例分数下界不能低于及格线。",
                    )
                )
            if not bool(answer["expected_pass"]) and float(score["max"]) >= pass_score:
                issues.append(
                    _issue(
                        "REFERENCE_CASE_INVALID",
                        f"{path}.cases[{case_index}].answers[{answer_index}]",
                        "标记为未通过的案例分数上界必须低于及格线。",
                    )
                )
            content = answer["content"]
            content_values = content.values() if isinstance(content, dict) else [content]
            if any(not str(value).strip() for value in content_values):
                issues.append(
                    _issue(
                        "REFERENCE_CASE_INVALID",
                        f"{path}.cases[{case_index}].answers[{answer_index}].content",
                        "案例答案字段不能只包含空白字符。",
                    )
                )
            if structured:
                if not isinstance(content, dict):
                    issues.append(
                        _issue(
                            "REFERENCE_CASE_INVALID",
                            f"{path}.cases[{case_index}].answers[{answer_index}].content",
                            "结构化题型的案例答案必须是对象。",
                        )
                    )
                    continue
                content_keys = set(content)
                if not required_keys <= content_keys or not content_keys <= field_keys:
                    issues.append(
                        _issue(
                            "REFERENCE_CASE_INVALID",
                            f"{path}.cases[{case_index}].answers[{answer_index}].content",
                            "案例答案字段必须匹配 answer_schema。",
                        )
                    )
            elif not isinstance(content, str):
                issues.append(
                    _issue(
                        "REFERENCE_CASE_INVALID",
                        f"{path}.cases[{case_index}].answers[{answer_index}].content",
                        "长文本题型的案例答案必须是字符串。",
                    )
                )
    return issues


def validate_compiled_question_type_definition(
    compiled: CompiledQuestionTypeDefinition,
) -> list[PackageValidationIssue]:
    """Replay the original protocol contract for a restored frozen definition."""

    manifest = dict(compiled.manifest)
    manifest_schema_name, reference_schema_name = _schema_files_for_manifest(manifest)
    issues = _schema_issues(
        manifest,
        schema_name=manifest_schema_name,
        code="SCHEMA_INVALID",
        root="$manifest",
    )
    if issues:
        return issues
    issues.extend(
        _validate_v2_manifest_semantics(manifest)
        if _is_v2_manifest(manifest)
        else _validate_manifest_semantics(manifest)
    )

    manifest_fields = [
        {**dict(item), "placeholder": str(item.get("placeholder") or "")}
        for item in manifest["answer_schema"]["fields"]
    ]
    manifest_rubric = [dict(item) for item in manifest["grading"]["rubric"]]
    capabilities = manifest["capabilities"]
    identity_matches = (
        compiled.schema_version == manifest["schema"]
        and compiled.package_key == manifest["package_key"]
        and compiled.type_key == f"custom_{manifest['package_key']}"
        and compiled.version == manifest["version"]
        and compiled.display_name == manifest["name"]
        and compiled.description == manifest["description"]
        and compiled.template_key == manifest["template_key"]
        and compiled.runtime_key == manifest["runtime_key"]
        and compiled.renderer_key == manifest["renderer_key"]
        and compiled.grader_key == manifest["grader_key"]
        and compiled.modes == list(capabilities["modes"])
        and compiled.hints is bool(capabilities["hints"])
        and compiled.immediate_feedback is bool(capabilities["immediate_feedback"])
        and [item.model_dump(mode="json") for item in compiled.answer_fields] == manifest_fields
        and float(compiled.pass_score) == float(manifest["grading"]["pass_score"])
        and [item.model_dump(mode="json") for item in compiled.rubric] == manifest_rubric
    )
    if not identity_matches:
        issues.append(
            _issue(
                "COMPILED_DEFINITION_MISMATCH",
                "$compiled",
                "冻结定义与题型清单不一致。",
            )
        )

    files_config = manifest["files"]
    prompt_paths = {
        "generate": str(files_config["generate_prompt"]),
        "grade": str(files_config["grade_prompt"]),
    }
    if files_config.get("feedback_prompt"):
        prompt_paths["feedback"] = str(files_config["feedback_prompt"])
    if len(set(prompt_paths.values())) != len(prompt_paths):
        issues.append(
            _issue(
                "FILE_REFERENCE_DUPLICATE",
                "$manifest.files",
                "生成、判分和反馈提示词必须引用不同文件。",
            )
        )
    if set(compiled.prompts) != set(prompt_paths):
        issues.append(
            _issue(
                "COMPILED_PROMPTS_MISMATCH",
                "$compiled.prompts",
                "冻结提示词集合与题型清单不一致。",
            )
        )
    for prompt_name, path in prompt_paths.items():
        prompt = str(compiled.prompts.get(prompt_name) or "")
        if not prompt.strip() or len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
            issues.append(
                _issue(
                    "PROMPT_CONTENT_INVALID",
                    path,
                    "提示词不能为空或超过 32 KB。",
                )
            )
            continue
        issues.extend(_validate_prompt(path, prompt, prompt_name=prompt_name))

    reference_payload = {
        "schema": REFERENCE_CASES_SCHEMA_ID_V2 if _is_v2_manifest(manifest) else REFERENCE_CASES_SCHEMA_ID,
        "cases": [
            {
                "id": case.id,
                "knowledge_unit": dict(case.knowledge_unit),
                "question": dict(case.question),
                "answers": [
                    {
                        "label": answer.label,
                        "content": answer.content,
                        "expected_score": {
                            "min": answer.expected_score_min,
                            "max": answer.expected_score_max,
                        },
                        "expected_pass": answer.expected_pass,
                    }
                    for answer in case.answers
                ],
            }
            for case in compiled.reference_cases
        ],
    }
    reference_path = str(files_config["references"])
    reference_schema_issues = _schema_issues(
        reference_payload,
        schema_name=reference_schema_name,
        code="REFERENCE_CASE_INVALID",
        root=reference_path,
    )
    issues.extend(reference_schema_issues)
    if not reference_schema_issues:
        issues.extend(
            _validate_reference_semantics(
                reference_payload,
                manifest=manifest,
                path=reference_path,
            )
        )
    if len(json.dumps(reference_payload, ensure_ascii=False).encode("utf-8")) > MAX_REFERENCE_BYTES:
        issues.append(
            _issue(
                "PACKAGE_MEMBER_TOO_LARGE",
                reference_path,
                "参考案例文件不能超过 256 KB。",
            )
        )

    tool_path = str((manifest.get("tools") or {}).get("bindings") or "")
    tool_payload = {
        "schema": TOOL_BINDINGS_SCHEMA_ID,
        "tools": [item.model_dump(mode="json") for item in compiled.tool_bindings],
    }
    if not tool_path and compiled.tool_bindings:
        issues.append(
            _issue(
                "TOOL_BINDINGS_INVALID",
                "$compiled.tool_bindings",
                "冻结工具绑定与题型清单不一致。",
            )
        )
    if tool_path:
        tool_schema_issues = _schema_issues(
            tool_payload,
            schema_name="tool-bindings-v1.schema.json",
            code="TOOL_BINDINGS_INVALID",
            root=tool_path,
        )
        issues.extend(tool_schema_issues)
        tool_ids = [item.id for item in compiled.tool_bindings]
        if len(set(tool_ids)) != len(tool_ids):
            issues.append(_issue("TOOL_BINDINGS_INVALID", tool_path, "工具 ID 不能重复。"))
        for tool_id in sorted(set(tool_ids) - ALLOWED_TOOL_IDS):
            issues.append(_issue("UNSUPPORTED_TOOL", tool_path, f"不支持工具 `{tool_id}`。"))

    declared_assets = sorted(
        (str(item["path"]), str(item["role"]))
        for item in list(manifest.get("assets") or [])
    )
    compiled_assets = [(item.path, item.role) for item in compiled.assets]
    if compiled_assets != declared_assets:
        issues.append(
            _issue(
                "COMPILED_ASSETS_MISMATCH",
                "$compiled.assets",
                "冻结资源清单与题型清单不一致。",
            )
        )

    declared_paths = {
        "SKILL.md",
        *prompt_paths.values(),
        reference_path,
        *(path for path, _role in declared_assets),
    }
    if tool_path:
        declared_paths.add(tool_path)
    hash_pattern = re.compile(r"^[0-9a-f]{64}$")
    if set(compiled.file_sha256) != declared_paths or any(
        not hash_pattern.fullmatch(str(value))
        for value in compiled.file_sha256.values()
    ):
        issues.append(
            _issue(
                "COMPILED_FILE_HASHES_INVALID",
                "$compiled.file_sha256",
                "冻结文件哈希清单不完整或格式无效。",
            )
        )
    if not hash_pattern.fullmatch(compiled.package_sha256):
        issues.append(
            _issue(
                "COMPILED_PACKAGE_HASH_INVALID",
                "$compiled.package_sha256",
                "冻结题型包哈希格式无效。",
            )
        )
    for asset in compiled.assets:
        if compiled.file_sha256.get(asset.path) != asset.sha256:
            issues.append(
                _issue(
                    "COMPILED_ASSET_HASH_MISMATCH",
                    asset.path,
                    "冻结资源哈希与文件清单不一致。",
                )
            )
    if len(compiled.documentation_markdown.encode("utf-8")) > MAX_SKILL_MARKDOWN_BYTES:
        issues.append(
            _issue(
                "PACKAGE_MEMBER_TOO_LARGE",
                "SKILL.md",
                "题型说明不能超过 32 KB。",
            )
        )
    return issues


def validate_atqskill(package_path: str | Path) -> PackageValidationResult:
    """Validate a package and return a compiled definition when valid."""

    try:
        archive = read_atqskill_archive(package_path)
    except AtqSkillPackageError as exc:
        return PackageValidationResult(valid=False, errors=[exc.issue])

    errors: list[PackageValidationIssue] = []
    package_warnings: list[PackageValidationIssue] = []
    skill_content = archive.files["SKILL.md"]
    if len(skill_content) > MAX_SKILL_MARKDOWN_BYTES:
        return PackageValidationResult(
            valid=False,
            package_hash=archive.package_sha256,
            errors=[
                _issue(
                    "PACKAGE_MEMBER_TOO_LARGE",
                    "SKILL.md",
                    "`SKILL.md` 不能超过 32 KB。",
                )
            ],
        )
    try:
        manifest, documentation = parse_skill_markdown(skill_content)
    except AtqSkillPackageError as exc:
        return PackageValidationResult(valid=False, package_hash=archive.package_sha256, errors=[exc.issue])

    manifest_schema_name, reference_schema_name = _schema_files_for_manifest(manifest)
    errors.extend(
        _schema_issues(
            manifest,
            schema_name=manifest_schema_name,
            code="SCHEMA_INVALID",
            root="$manifest",
        )
    )
    if errors:
        return PackageValidationResult(valid=False, package_hash=archive.package_sha256, errors=errors)
    errors.extend(
        _validate_v2_manifest_semantics(manifest)
        if _is_v2_manifest(manifest)
        else _validate_manifest_semantics(manifest)
    )

    files_config = manifest["files"]
    prompt_paths = {
        "generate": files_config["generate_prompt"],
        "grade": files_config["grade_prompt"],
    }
    if files_config.get("feedback_prompt"):
        prompt_paths["feedback"] = files_config["feedback_prompt"]
    if len(set(prompt_paths.values())) != len(prompt_paths):
        errors.append(
            _issue(
                "FILE_REFERENCE_DUPLICATE",
                "$manifest.files",
                "生成、判分和反馈提示词必须引用不同文件。",
            )
        )

    prompts: dict[str, str] = {}
    for prompt_name, prompt_path in prompt_paths.items():
        prompt = _read_text_file(archive, prompt_path, max_bytes=MAX_PROMPT_BYTES, errors=errors)
        if prompt is not None:
            prompts[prompt_name] = prompt
            errors.extend(_validate_prompt(prompt_path, prompt, prompt_name=prompt_name))

    reference_path = files_config["references"]
    reference_payload: dict[str, Any] | None = None
    reference_content = _required_file(archive, reference_path, errors)
    if reference_content is not None:
        if len(reference_content) > MAX_REFERENCE_BYTES:
            errors.append(
                _issue(
                    "PACKAGE_MEMBER_TOO_LARGE",
                    reference_path,
                    "参考案例文件不能超过 256 KB。",
                )
            )
        else:
            try:
                reference_payload = parse_json_document(reference_content, path=reference_path)
            except AtqSkillPackageError as exc:
                errors.append(exc.issue)
            if reference_payload is not None:
                reference_schema_issues = _schema_issues(
                    reference_payload,
                    schema_name=reference_schema_name,
                    code="REFERENCE_CASE_INVALID",
                    root=reference_path,
                )
                errors.extend(reference_schema_issues)
                if not reference_schema_issues:
                    errors.extend(
                        _validate_reference_semantics(
                            reference_payload,
                            manifest=manifest,
                            path=reference_path,
                        )
                    )

    tool_payload: dict[str, Any] | None = None
    tool_path = str((manifest.get("tools") or {}).get("bindings") or "")
    if tool_path:
        tool_content = _required_file(archive, tool_path, errors)
        if tool_content is not None:
            if len(tool_content) > MAX_TOOL_BINDINGS_BYTES:
                errors.append(
                    _issue(
                        "PACKAGE_MEMBER_TOO_LARGE",
                        tool_path,
                        "工具绑定文件不能超过 32 KB。",
                    )
                )
            else:
                try:
                    tool_payload = parse_json_document(tool_content, path=tool_path)
                except AtqSkillPackageError as exc:
                    errors.append(exc.issue)
                if tool_payload is not None:
                    tool_schema_issues = _schema_issues(
                        tool_payload,
                        schema_name="tool-bindings-v1.schema.json",
                        code="TOOL_BINDINGS_INVALID",
                        root=tool_path,
                    )
                    errors.extend(tool_schema_issues)
                    if not tool_schema_issues:
                        tool_ids = [str(item["id"]) for item in tool_payload["tools"]]
                        if len(set(tool_ids)) != len(tool_ids):
                            errors.append(
                                _issue(
                                    "TOOL_BINDINGS_INVALID",
                                    f"{tool_path}.tools",
                                    "工具 ID 不能重复。",
                                )
                            )
                        for tool_id in sorted(set(tool_ids) - ALLOWED_TOOL_IDS):
                            errors.append(
                                _issue(
                                    "UNSUPPORTED_TOOL",
                                    tool_path,
                                    f"不支持工具 `{tool_id}`。",
                                )
                            )

    declared_assets = list(manifest.get("assets") or [])
    asset_paths = [str(item["path"]) for item in declared_assets]
    if len(set(asset_paths)) != len(asset_paths):
        errors.append(_issue("ASSET_PATH_DUPLICATE", "$manifest.assets", "资源路径不能重复。"))
    compiled_assets: list[CompiledAsset] = []
    for asset in declared_assets:
        compiled_asset, asset_errors, asset_warnings = _validate_asset(archive, asset)
        errors.extend(asset_errors)
        package_warnings.extend(asset_warnings)
        if compiled_asset is not None:
            compiled_assets.append(compiled_asset)

    declared_paths = {"SKILL.md", *prompt_paths.values(), reference_path, *asset_paths}
    if tool_path:
        declared_paths.add(tool_path)
    for archived_path in sorted(set(archive.files) - declared_paths):
        errors.append(
            _issue(
                "UNDECLARED_FILE",
                archived_path,
                "题型包包含未在 `SKILL.md` 中声明的文件。",
            )
        )

    tool_ids = [str(item["id"]) for item in list((tool_payload or {}).get("tools") or [])]
    preview = PackagePreview(
        package_key=manifest["package_key"],
        type_key=f"custom_{manifest['package_key']}",
        version=manifest["version"],
        name=manifest["name"],
        description=manifest["description"],
        template_key=manifest["template_key"],
        runtime_key=manifest["runtime_key"],
        renderer_key=manifest["renderer_key"],
        grader_key=manifest["grader_key"],
        modes=list(manifest["capabilities"]["modes"]),
        answer_field_count=len(manifest["answer_schema"]["fields"]),
        rubric_item_count=len(manifest["grading"]["rubric"]),
        tool_ids=tool_ids,
        asset_count=len(declared_assets),
    )
    if errors or reference_payload is None:
        return PackageValidationResult(
            valid=False,
            package_hash=archive.package_sha256,
            errors=errors,
            warnings=package_warnings,
            preview=preview,
        )

    compiled = build_compiled_definition(
        archive=archive,
        manifest=manifest,
        documentation_markdown=documentation,
        prompts=prompts,
        reference_payload=reference_payload,
        tool_payload=tool_payload,
        assets=compiled_assets,
    )
    compiled_errors = validate_compiled_question_type_definition(compiled)
    if compiled_errors:
        return PackageValidationResult(
            valid=False,
            package_hash=archive.package_sha256,
            errors=compiled_errors,
            warnings=package_warnings,
            preview=preview,
        )
    return PackageValidationResult(
        valid=True,
        package_hash=archive.package_sha256,
        warnings=package_warnings,
        preview=preview,
        compiled_definition=compiled,
    )


def compile_atqskill(package_path: str | Path) -> CompiledQuestionTypeDefinition:
    """Return a compiled definition or raise with the complete report."""

    result = validate_atqskill(package_path)
    if not result.valid or result.compiled_definition is None:
        raise AtqSkillValidationError(result)
    return result.compiled_definition


__all__ = [
    "compile_atqskill",
    "validate_atqskill",
    "validate_compiled_asset_content",
    "validate_compiled_question_type_definition",
]
