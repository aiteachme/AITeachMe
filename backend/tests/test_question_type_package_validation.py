"""Security and semantic validation tests for `.atqskill` packages."""

from __future__ import annotations

import json
import stat
import warnings
import zipfile
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.workflows.support.question_type_packages import validate_atqskill

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_ROOT = Path(__file__).parent / "fixtures" / "question_type_packages" / "v1"


def _source_files(package_key: str = "feynman_explanation") -> dict[str, bytes]:
    source = EXAMPLE_ROOT / package_key
    return {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }


def _write_package(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for member_path, content in sorted(files.items()):
            archive.writestr(member_path, content)
    return path


def _error_codes(path: Path) -> set[str]:
    return {item.code for item in validate_atqskill(path).errors}


def test_rejects_path_traversal_before_reading_package_content(tmp_path: Path) -> None:
    files = _source_files()
    files["../escape.md"] = b"unsafe"
    package = _write_package(tmp_path / "traversal.atqskill", files)

    assert "ARCHIVE_PATH_INVALID" in _error_codes(package)
    assert not (tmp_path.parent / "escape.md").exists()


def test_rejects_wrong_suffix_missing_manifest_and_non_utf8_prompt(tmp_path: Path) -> None:
    wrong_suffix = _write_package(tmp_path / "package.zip", _source_files())
    missing_manifest_files = _source_files()
    del missing_manifest_files["SKILL.md"]
    invalid_text_files = _source_files()
    invalid_text_files["prompts/generate.md"] = b"\xff\xfe"

    assert "UNSUPPORTED_FILE" in _error_codes(wrong_suffix)
    assert "MANIFEST_MISSING" in _error_codes(
        _write_package(tmp_path / "missing-manifest.atqskill", missing_manifest_files)
    )
    assert "TEXT_ENCODING_INVALID" in _error_codes(
        _write_package(tmp_path / "invalid-text.atqskill", invalid_text_files)
    )


def test_rejects_reserved_windows_path_and_extreme_compression_ratio(tmp_path: Path) -> None:
    reserved_files = _source_files()
    reserved_files["assets/con.png"] = b"x"
    compressed_files = _source_files()
    compressed_files["prompts/generate.md"] = b"A" * 4096

    assert "ARCHIVE_PATH_INVALID" in _error_codes(
        _write_package(tmp_path / "reserved.atqskill", reserved_files)
    )
    assert "ARCHIVE_COMPRESSION_RATIO_INVALID" in _error_codes(
        _write_package(tmp_path / "compression.atqskill", compressed_files)
    )


def test_rejects_executable_and_nested_archive_files(tmp_path: Path) -> None:
    executable_files = _source_files()
    executable_files["tools/check_answer.py"] = b"print('unsafe')"
    nested_files = _source_files()
    nested_files["assets/inner.zip"] = b"PK"

    assert "UNSUPPORTED_FILE" in _error_codes(_write_package(tmp_path / "python.atqskill", executable_files))
    assert "UNSUPPORTED_FILE" in _error_codes(_write_package(tmp_path / "nested.atqskill", nested_files))


def test_rejects_symbolic_link_member(tmp_path: Path) -> None:
    package = tmp_path / "link.atqskill"
    files = _source_files()
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for member_path, content in sorted(files.items()):
            archive.writestr(member_path, content)
        link = zipfile.ZipInfo("assets/link.png")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, b"target.png")

    assert "ARCHIVE_LINK_UNSUPPORTED" in _error_codes(package)


def test_rejects_symbolic_link_even_when_name_looks_like_directory(tmp_path: Path) -> None:
    package = tmp_path / "directory-link.atqskill"
    files = _source_files()
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for member_path, content in sorted(files.items()):
            archive.writestr(member_path, content)
        link = zipfile.ZipInfo("assets/link/")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, b"")

    assert "ARCHIVE_LINK_UNSUPPORTED" in _error_codes(package)


def test_rejects_duplicate_archive_member(tmp_path: Path) -> None:
    package = tmp_path / "duplicate.atqskill"
    files = _source_files()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
            for member_path, content in sorted(files.items()):
                archive.writestr(member_path, content)
            archive.writestr("prompts/generate.md", b"duplicate")

    assert "DUPLICATE_PACKAGE_PATH" in _error_codes(package)


def test_archive_member_limit_counts_directory_entries(tmp_path: Path) -> None:
    package = tmp_path / "many-directories.atqskill"
    files = _source_files()
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for member_path, content in sorted(files.items()):
            archive.writestr(member_path, content)
        for index in range(101):
            archive.writestr(f"assets/d{index:03d}/", b"")

    assert "PACKAGE_FILE_LIMIT_EXCEEDED" in _error_codes(package)


def test_rejects_yaml_alias_and_duplicate_key(tmp_path: Path) -> None:
    alias_files = _source_files()
    alias_files["SKILL.md"] = alias_files["SKILL.md"].replace(
        "description: 要求".encode(),
        "description: &shared 要求".encode(),
        1,
    )
    duplicate_files = _source_files()
    duplicate_files["SKILL.md"] = duplicate_files["SKILL.md"].replace(
        b"version: 1.0.1",
        b"version: 1.0.1\nversion: 1.0.2",
        1,
    )

    assert "FRONTMATTER_INVALID" in _error_codes(_write_package(tmp_path / "alias.atqskill", alias_files))
    assert "FRONTMATTER_INVALID" in _error_codes(_write_package(tmp_path / "duplicate-key.atqskill", duplicate_files))


def test_rejects_reserved_trust_fields(tmp_path: Path) -> None:
    files = _source_files()
    files["SKILL.md"] = files["SKILL.md"].replace(
        b"package_key: feynman_explanation",
        b"package_key: feynman_explanation\nsource: system\nis_system: true",
        1,
    )

    assert "SCHEMA_INVALID" in _error_codes(_write_package(tmp_path / "trust.atqskill", files))


def test_rejects_bad_rubric_weight_and_capability_pair(tmp_path: Path) -> None:
    weight_files = _source_files()
    weight_files["SKILL.md"] = weight_files["SKILL.md"].replace(b"weight: 0.4", b"weight: 0.5", 1)
    capability_files = _source_files()
    capability_files["SKILL.md"] = capability_files["SKILL.md"].replace(b"    - pdf\n", b"", 1)

    assert "RUBRIC_WEIGHT_INVALID" in _error_codes(_write_package(tmp_path / "weight.atqskill", weight_files))
    assert "CAPABILITY_INVALID" in _error_codes(_write_package(tmp_path / "capability.atqskill", capability_files))


def test_fixed_template_requires_its_canonical_answer_fields(tmp_path: Path) -> None:
    files = _source_files("oral_defense")
    files["SKILL.md"] = files["SKILL.md"].replace(b"- key: claim", b"- key: opinion", 1)

    assert "ANSWER_SCHEMA_INVALID" in _error_codes(_write_package(tmp_path / "fields.atqskill", files))


def test_rejects_answer_fields_whose_combined_limit_exceeds_runtime_budget(tmp_path: Path) -> None:
    files = _source_files("oral_defense")
    skill = files["SKILL.md"]
    skill = skill.replace(b"max_length: 500", b"max_length: 10000", 1)
    skill = skill.replace(b"max_length: 3000", b"max_length: 10000", 1)
    skill = skill.replace(b"max_length: 2000", b"max_length: 10000", 1)
    files["SKILL.md"] = skill

    assert "ANSWER_SCHEMA_INVALID" in _error_codes(
        _write_package(tmp_path / "answer-budget.atqskill", files)
    )


def test_rejects_unknown_prompt_variable_tool_and_undeclared_file(tmp_path: Path) -> None:
    variable_files = _source_files()
    variable_files["prompts/generate.md"] += b"\n${environment.name}"
    tool_files = _source_files()
    tool_payload = json.loads(tool_files["tools/bindings.json"])
    tool_payload["tools"][0]["id"] = "run_python_v1"
    tool_files["tools/bindings.json"] = json.dumps(tool_payload).encode()
    undeclared_files = _source_files()
    undeclared_files["prompts/extra.md"] = b"extra"
    missing_variable_files = _source_files()
    missing_variable_files["prompts/generate.md"] = missing_variable_files["prompts/generate.md"].replace(
        b"${answer_schema}",
        b"answer schema",
    )

    assert "PROMPT_VARIABLE_INVALID" in _error_codes(_write_package(tmp_path / "variable.atqskill", variable_files))
    assert "UNSUPPORTED_TOOL" in _error_codes(_write_package(tmp_path / "tool.atqskill", tool_files))
    assert "UNDECLARED_FILE" in _error_codes(_write_package(tmp_path / "undeclared.atqskill", undeclared_files))
    assert "PROMPT_VARIABLE_REQUIRED" in _error_codes(
        _write_package(tmp_path / "missing-variable.atqskill", missing_variable_files)
    )


def test_rejects_non_finite_numbers_and_inconsistent_pass_range(tmp_path: Path) -> None:
    yaml_files = _source_files()
    yaml_files["SKILL.md"] = yaml_files["SKILL.md"].replace(b"weight: 0.4", b"weight: .nan", 1)
    json_files = _source_files()
    json_payload = json.loads(json_files["references/cases.json"])
    json_payload["cases"][0]["answers"][0]["expected_score"]["min"] = float("nan")
    json_files["references/cases.json"] = json.dumps(json_payload).encode()
    range_files = _source_files()
    range_payload = json.loads(range_files["references/cases.json"])
    range_payload["cases"][0]["answers"][1]["expected_score"]["max"] = 0.8
    range_files["references/cases.json"] = json.dumps(range_payload, ensure_ascii=False).encode()
    duplicate_json_files = _source_files()
    duplicate_json_files["tools/bindings.json"] = duplicate_json_files["tools/bindings.json"].replace(
        b'"schema": "aiteachme.question-skill-tools/v1",',
        b'"schema": "aiteachme.question-skill-tools/v1",\n  "schema": "duplicate",',
        1,
    )

    assert "FRONTMATTER_INVALID" in _error_codes(_write_package(tmp_path / "yaml-nan.atqskill", yaml_files))
    assert "JSON_INVALID" in _error_codes(_write_package(tmp_path / "json-nan.atqskill", json_files))
    assert "REFERENCE_CASE_INVALID" in _error_codes(_write_package(tmp_path / "pass-range.atqskill", range_files))
    assert "JSON_INVALID" in _error_codes(_write_package(tmp_path / "duplicate-json.atqskill", duplicate_json_files))


def test_rejects_structured_reference_answer_with_missing_required_field(tmp_path: Path) -> None:
    files = _source_files("oral_defense")
    payload = json.loads(files["references/cases.json"])
    del payload["cases"][0]["answers"][0]["content"]["boundary"]
    files["references/cases.json"] = json.dumps(payload, ensure_ascii=False).encode()

    assert "REFERENCE_CASE_INVALID" in _error_codes(_write_package(tmp_path / "reference.atqskill", files))


def test_rejects_invalid_declared_image(tmp_path: Path) -> None:
    files = _source_files()
    files["SKILL.md"] = files["SKILL.md"].replace(
        b"tools:\n  bindings: tools/bindings.json",
        b"tools:\n  bindings: tools/bindings.json\nassets:\n  - path: assets/cover.png\n    role: cover",
        1,
    )
    files["assets/cover.png"] = b"not-an-image"

    assert "ASSET_INVALID" in _error_codes(_write_package(tmp_path / "asset.atqskill", files))


def test_accepts_declared_static_image_and_compiles_metadata(tmp_path: Path) -> None:
    files = _source_files()
    files["SKILL.md"] = files["SKILL.md"].replace(
        b"tools:\n  bindings: tools/bindings.json",
        b"tools:\n  bindings: tools/bindings.json\nassets:\n  - path: assets/cover.png\n    role: cover",
        1,
    )
    image_bytes = BytesIO()
    Image.new("RGB", (4, 3), color=(70, 90, 180)).save(image_bytes, format="PNG")
    files["assets/cover.png"] = image_bytes.getvalue()

    result = validate_atqskill(_write_package(tmp_path / "valid-asset.atqskill", files))

    assert result.valid is True
    assert result.compiled_definition is not None
    assert result.compiled_definition.assets[0].model_dump() == {
        "path": "assets/cover.png",
        "role": "cover",
        "media_type": "image/png",
        "size_bytes": len(files["assets/cover.png"]),
        "width": 4,
        "height": 3,
        "sha256": result.compiled_definition.file_sha256["assets/cover.png"],
    }


def test_rejects_image_dimensions_before_accepting_asset(tmp_path: Path) -> None:
    files = _source_files()
    files["SKILL.md"] = files["SKILL.md"].replace(
        b"tools:\n  bindings: tools/bindings.json",
        b"tools:\n  bindings: tools/bindings.json\nassets:\n  - path: assets/cover.png\n    role: cover",
        1,
    )
    image_bytes = BytesIO()
    pixels = bytes((index * 73) % 256 for index in range(4097 * 3))
    Image.frombytes("RGB", (4097, 1), pixels).save(image_bytes, format="PNG")
    files["assets/cover.png"] = image_bytes.getvalue()

    assert "ASSET_DIMENSIONS_INVALID" in _error_codes(_write_package(tmp_path / "large-image.atqskill", files))
