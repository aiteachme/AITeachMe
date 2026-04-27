from __future__ import annotations

import json
import zipfile

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models import ChatSession, RawFile, Subject
from app.shared.infra.exceptions import ImportPackageTooLargeError, InvalidImportPackageError
from app.schemas.export_import import ExportOptions
from app.workflows.support.export_import import exports
from app.workflows.support.export_import import imports


class _FakeContentStore:
    def __init__(self) -> None:
        self._data = {
            "users/local/subjects/math/assets/docgen/docgen_cover_old.png": b"old",
            "users/local/subjects/math/assets/docgen/docgen_cover_new.png": b"new",
            "users/local/subjects/math/assets/docgen/cover.png": b"stable",
            "users/local/subjects/math/knowledge_markdowns/merged_knowledge_base.md": b"# Doc",
            "users/local/subjects/math/raw_files/file_1/source.pdf": b"%PDF",
            "users/local/subjects/math/raw_markdowns/file_1/markdown.md": b"# Parsed",
        }
        self.writes: dict[str, bytes] = {}

    async def list_prefix(self, prefix: str) -> list[str]:
        return sorted(key for key in self._data if key.startswith(prefix))

    async def read_bytes(self, key: str) -> bytes | None:
        return self._data.get(key)

    async def write_bytes(self, key: str, data: bytes) -> None:
        self.writes[key] = data


def test_export_packs_docgen_cover_but_not_derived_merged_markdown(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(exports, "get_content_store", lambda: _FakeContentStore())
    output = tmp_path / "subject.zip"

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        exports._pack_files(
            zf,
            "users/local/subjects/math",
            ExportOptions(include_raw_files=False, include_raw_markdowns=False),
            raw_files=[],
        )

    with zipfile.ZipFile(output, "r") as zf:
        names = set(zf.namelist())
        assert zf.read("knowledge/cover.png") == b"stable"
        assert "knowledge/merged_knowledge_base.md" not in names


def test_export_does_not_pack_raw_storage_files_even_if_requested(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(exports, "get_content_store", lambda: _FakeContentStore())
    output = tmp_path / "subject.zip"
    raw_file = RawFile(
        id=1,
        uid="file_1",
        subject="math",
        filename="source.pdf",
        filetype=".pdf",
        file_path="users/local/subjects/math/raw_files/file_1/source.pdf",
        markdown_path="users/local/subjects/math/raw_markdowns/file_1/markdown.md",
    )

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        exports._pack_files(
            zf,
            "users/local/subjects/math",
            ExportOptions(include_raw_files=True, include_raw_markdowns=True),
            raw_files=[raw_file],
        )

    with zipfile.ZipFile(output, "r") as zf:
        assert not any(name.startswith("files/raw_files/") for name in zf.namelist())
        assert not any(name.startswith("files/raw_markdowns/") for name in zf.namelist())


def test_export_options_skip_unselected_db_groups() -> None:
    options = ExportOptions(
        include_raw_files=False,
        include_raw_markdowns=False,
        include_knowledge_docs=False,
        include_chat_history=False,
        include_exam_history=False,
        include_profile=False,
    )
    specs = {spec.name: spec for spec in exports.TABLE_REGISTRY}

    assert exports._should_export(specs["subject"], options)
    assert exports._should_export(specs["knowledge_unit"], options)
    assert exports._should_export(specs["knowledge_edge"], options)
    assert not exports._should_export(specs["raw_file"], options)
    assert not exports._should_export(specs["subject_file"], options)
    assert not exports._should_export(specs["retrieval_chunk"], options)
    assert not exports._should_export(specs["knowledge_document"], options)
    assert not exports._should_export(specs["chat_session"], options)
    assert not exports._should_export(specs["exam_paper"], options)
    assert not exports._should_export(specs["user_knowledge_state"], options)


def test_knowledge_doc_export_includes_planner_sessions_for_confirmed_plans() -> None:
    options = ExportOptions(include_knowledge_docs=True, include_chat_history=False)
    specs = {spec.name: spec for spec in exports.TABLE_REGISTRY}

    assert exports._should_export(specs["chat_session"], options)


def test_reconcile_imported_planner_metadata_is_idempotent_for_remapped_ids() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine, tables=[ChatSession.__table__])

    with Session(engine) as session:
        session.add(
            ChatSession(
                id="new-session",
                subject="math-copy",
                user_id="local",
                source="build_planner",
                meta_json={
                    "selected_file_ids": [101],
                    "confirmed_plan_id": "new-plan",
                    "confirmed_plan": {
                        "id": "new-plan",
                        "selected_file_ids_json": [101],
                        "plan_json": {"selected_file_ids": [101]},
                    },
                },
            )
        )
        session.commit()

        imports._reconcile_imported_planner_metadata(
            session,
            subject_slug="math-copy",
            id_map={
                "raw_file": {1: 101},
                "confirmed_build_plan": {"old-plan": "new-plan"},
            },
        )
        session.commit()
        row = session.get(ChatSession, "new-session")

    assert row is not None
    assert row.meta_json["selected_file_ids"] == [101]
    assert row.meta_json["confirmed_plan_id"] == "new-plan"
    assert row.meta_json["confirmed_plan"]["selected_file_ids_json"] == [101]


def test_include_raw_files_flag_no_longer_exports_raw_metadata() -> None:
    options = ExportOptions(include_raw_files=True, include_raw_markdowns=False)
    specs = {spec.name: spec for spec in exports.TABLE_REGISTRY}

    assert not exports._should_export(specs["raw_file"], options)
    assert not exports._should_export(specs["subject_file"], options)


def test_default_export_options_include_parsed_source_metadata() -> None:
    options = ExportOptions()
    specs = {spec.name: spec for spec in exports.TABLE_REGISTRY}

    assert options.include_raw_markdowns
    assert exports._should_export(specs["raw_file"], options)
    assert exports._should_export(specs["retrieval_chunk"], options)


def test_export_filename_uses_subject_name_and_id() -> None:
    subject = Subject(slug="subj_abc123", name="线性/代数")

    assert exports.build_subject_export_filename(subject) == "线性_代数-subj_abc123.atmx"


def test_export_manifest_keeps_extension_fields_for_future_readers() -> None:
    subject = Subject(slug="subj_math", name="Math", description="demo", user_intent="learn")
    manifest = exports._build_manifest(
        subject,
        {
            "subject": [{"id": 1}],
            "knowledge_unit": [{"id": 1}, {"id": 2}],
            "knowledge_edge": [],
        },
        ExportOptions(include_chat_history=False, include_exam_history=False),
    )

    assert manifest.package.kind == exports.PACKAGE_KIND
    assert manifest.package.manifest_schema == exports.MANIFEST_SCHEMA
    assert "knowledge_graph" in manifest.package.capabilities
    assert manifest.subject.slug == "subj_math"
    assert manifest.subject.description == "demo"
    assert manifest.stats.knowledge_unit_count == 2
    assert {item.name: item.count for item in manifest.tables}["knowledge_unit"] == 2


def test_read_manifest_accepts_legacy_manifest_without_package_fields(tmp_path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "format_version": "1.0",
                "app_version": "0.1.0",
                "exporter": "AITeachMe",
                "subject": {"slug": "legacy", "name": "Legacy"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    manifest = exports._read_manifest(tmp_path)

    assert manifest.package.package_id == "legacy"
    assert manifest.tables == []


def test_import_restores_docgen_cover_to_asset_directory_only(tmp_path, monkeypatch) -> None:
    fake = _FakeContentStore()
    monkeypatch.setattr(imports, "get_content_store", lambda: fake)
    extract_dir = tmp_path / "extract"
    knowledge_dir = extract_dir / "knowledge"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "cover.png").write_bytes(b"cover")
    (knowledge_dir / "merged_knowledge_base.md").write_text("# Doc", encoding="utf-8")

    imports._unpack_files(
        None,
        extract_dir,
        "math-imported",
        user_id="user_a",
        file_id_map={},
    )

    assert fake.writes["users/user_a/subjects/math-imported/assets/docgen/cover.png"] == b"cover"
    assert "users/user_a/subjects/math-imported/knowledge_markdowns/merged_knowledge_base.md" not in fake.writes
    assert "users/user_a/subjects/math-imported/knowledge_markdowns/cover.png" not in fake.writes


def test_import_rejects_package_without_subject_table(tmp_path) -> None:
    package_path = tmp_path / "missing-subject.atmx"
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format_version": "1.0",
                    "app_version": "0.1.0",
                    "exporter": "AITeachMe",
                    "subject": {"slug": "legacy", "name": "Legacy"},
                },
                ensure_ascii=False,
            ),
        )

    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        with pytest.raises(InvalidImportPackageError):
            imports.import_subject(session, file_path=package_path, user_id="local")


def test_import_rejects_archive_path_traversal(tmp_path) -> None:
    package_path = tmp_path / "unsafe.atmx"
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("../evil.txt", "bad")

    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    with zipfile.ZipFile(package_path, "r") as zf:
        with pytest.raises(InvalidImportPackageError):
            imports._safe_extract_archive(zf, extract_dir)


def test_import_rejects_oversized_archive_payload(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(imports, "MAX_IMPORT_PACKAGE_BYTES", 4)
    monkeypatch.setattr(imports, "MAX_IMPORT_PACKAGE_SIZE_MB", 1)

    package_path = tmp_path / "too-large.atmx"
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", "12345")

    with zipfile.ZipFile(package_path, "r") as zf:
        with pytest.raises(ImportPackageTooLargeError):
            imports._safe_extract_archive(zf, tmp_path / "extract-large")
