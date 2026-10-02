"""Six generic examples and byte-preserved V1 compatibility fixtures."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.workflows.support.question_type_packages import (
    build_atqskill_archive,
    compile_atqskill,
    validate_atqskill,
)
from app.workflows.support.question_type_packages.archive import read_atqskill_archive

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_ROOT = REPOSITORY_ROOT / "examples" / "question-type-skills"
SCHEMA_ROOT = (
    REPOSITORY_ROOT
    / "backend"
    / "app"
    / "workflows"
    / "support"
    / "question_type_packages"
    / "schemas"
)
BUNDLED_EXAMPLE_ROOT = (
    REPOSITORY_ROOT
    / "backend"
    / "app"
    / "workflows"
    / "support"
    / "question_type_packages"
    / "example_packages"
)

EXAMPLES = {
    "feynman_explanation": ("structured_text_v1", 1),
    "oral_defense": ("structured_text_v1", 3),
    "scenario_interview": ("structured_text_v1", 3),
    "argument_debate": ("structured_text_v1", 4),
    "experiment_design": ("structured_text_v1", 4),
    "case_analysis": ("structured_text_v1", 2),
}
LEGACY_VERSIONS = {
    "feynman_explanation": "1.0.1",
    "oral_defense": "1.0.0",
    "scenario_interview": "1.0.0",
    "argument_debate": "1.0.0",
}
LEGACY_ROOT = Path(__file__).parent / "fixtures" / "question_type_packages" / "v1"


@pytest.mark.parametrize(("package_key", "expected"), EXAMPLES.items())
def test_example_package_builds_valid_compiled_definition(
    tmp_path: Path,
    package_key: str,
    expected: tuple[str, int],
) -> None:
    renderer_key, answer_field_count = expected
    target = build_atqskill_archive(
        EXAMPLE_ROOT / package_key,
        tmp_path / f"{package_key}.atqskill",
    )

    result = validate_atqskill(target)

    assert result.valid is True
    assert result.errors == []
    assert result.preview is not None
    assert result.preview.package_key == package_key
    assert result.preview.renderer_key == renderer_key
    assert result.preview.answer_field_count == answer_field_count
    assert set(result.preview.modes) == {
        "question_bank",
        "mastery_drill",
        "web_practice",
        "paper_exam",
        "pdf",
    }
    compiled = compile_atqskill(target)
    assert compiled.schema_version == "aiteachme.question-skill/v2"
    assert compiled.template_key == "generic_text_form_v2"
    assert compiled.version == "2.0.0"
    for case in compiled.reference_cases:
        assert set(case.question["reference_answer"]) == {field.key for field in compiled.answer_fields}
        assert all(isinstance(answer.content, dict) for answer in case.answers)
    assert compiled.type_key == f"custom_{package_key}"
    assert compiled.package_sha256 == result.package_hash
    assert len(compiled.reference_cases) == 3
    assert sum(item.weight for item in compiled.rubric) == pytest.approx(1.0)


def test_example_builder_is_byte_for_byte_deterministic(tmp_path: Path) -> None:
    source = EXAMPLE_ROOT / "feynman_explanation"
    first = build_atqskill_archive(source, tmp_path / "first.atqskill")
    second = build_atqskill_archive(source, tmp_path / "second.atqskill")

    assert first.read_bytes() == second.read_bytes()
    assert read_atqskill_archive(first).package_sha256 == read_atqskill_archive(second).package_sha256


@pytest.mark.parametrize("package_key", EXAMPLES)
def test_bundled_example_matches_authoritative_source(
    tmp_path: Path,
    package_key: str,
) -> None:
    rebuilt = build_atqskill_archive(
        EXAMPLE_ROOT / package_key,
        tmp_path / f"{package_key}.atqskill",
    )
    bundled = BUNDLED_EXAMPLE_ROOT / (
        f"{package_key}-2.0.0.atqskill"
    )

    assert bundled.is_file()
    assert bundled.read_bytes() == rebuilt.read_bytes()


def test_feynman_example_uses_natural_numbered_question_stems(tmp_path: Path) -> None:
    package = build_atqskill_archive(
        EXAMPLE_ROOT / "feynman_explanation",
        tmp_path / "feynman.atqskill",
    )
    compiled = compile_atqskill(package)

    assert compiled.version == "2.0.0"
    assert compiled.manifest["generation_constraints"] == {"numbered_task_count": 4}
    assert "不得使用“请像向……讲解一样”等句式套叠" in compiled.prompts["generate"]
    assert "`(1)` 至 `(4)`" in compiled.prompts["generate"]
    for case in compiled.reference_cases:
        stem = str(case.question["stem"])
        assert "请像向" not in stem
        assert re.findall(r"(?:\A|\n\n)\((\d+)\)", stem) == ["1", "2", "3", "4"]


def test_package_hash_normalizes_text_line_endings(tmp_path: Path) -> None:
    source_package = build_atqskill_archive(
        EXAMPLE_ROOT / "feynman_explanation",
        tmp_path / "source.atqskill",
    )
    source_files: dict[str, bytes] = {}
    with zipfile.ZipFile(source_package, "r") as archive:
        for member in archive.infolist():
            source_files[member.filename] = archive.read(member)
    crlf_package = tmp_path / "crlf.atqskill"
    with zipfile.ZipFile(crlf_package, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in reversed(sorted(source_files.items())):
            if Path(path).suffix in {".md", ".json"}:
                content = content.replace(b"\n", b"\r\n")
            archive.writestr(path, content)

    assert read_atqskill_archive(source_package).package_sha256 == read_atqskill_archive(crlf_package).package_sha256


def test_published_json_schemas_are_valid_draft_2020_12() -> None:
    for path in sorted(SCHEMA_ROOT.glob("*.schema.json")):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_compiled_definition_does_not_accept_trust_origin_fields(tmp_path: Path) -> None:
    package = build_atqskill_archive(
        EXAMPLE_ROOT / "oral_defense",
        tmp_path / "oral.atqskill",
    )
    compiled = compile_atqskill(package)

    assert "source" not in compiled.manifest
    assert "is_system" not in compiled.manifest
    assert "owner_user_id" not in compiled.manifest
    assert "course_id" not in compiled.manifest


@pytest.mark.parametrize("package_key,version", LEGACY_VERSIONS.items())
def test_original_v1_sources_still_rebuild_identical_valid_packages(tmp_path, package_key, version):
    rebuilt = build_atqskill_archive(LEGACY_ROOT / package_key, tmp_path / "legacy.atqskill")
    assert rebuilt.read_bytes() == (LEGACY_ROOT / "archives" / f"{package_key}-{version}.atqskill").read_bytes()
    result = validate_atqskill(rebuilt)
    assert result.valid, result.errors
    assert result.compiled_definition.schema_version == "aiteachme.question-skill/v1"
