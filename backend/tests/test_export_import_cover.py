from __future__ import annotations

import zipfile

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
        }
        self.writes: dict[str, bytes] = {}

    async def list_prefix(self, prefix: str) -> list[str]:
        return sorted(key for key in self._data if key.startswith(prefix))

    async def read_bytes(self, key: str) -> bytes | None:
        return self._data.get(key)

    async def write_bytes(self, key: str, data: bytes) -> None:
        self.writes[key] = data


def test_export_packs_latest_docgen_cover_as_stable_cover_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(exports, "get_content_store", lambda: _FakeContentStore())
    output = tmp_path / "subject.zip"

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        exports._pack_files(
            zf,
            "users/local/subjects/math",
            ExportOptions(include_raw_files=False, include_raw_markdowns=False),
        )

    with zipfile.ZipFile(output, "r") as zf:
        assert zf.read("knowledge/cover.png") == b"stable"
        assert zf.read("knowledge/merged_knowledge_base.md") == b"# Doc"


def test_import_restores_docgen_cover_to_asset_directory(tmp_path, monkeypatch) -> None:
    fake = _FakeContentStore()
    monkeypatch.setattr(imports, "get_content_store", lambda: fake)
    extract_dir = tmp_path / "extract"
    knowledge_dir = extract_dir / "knowledge"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "cover.png").write_bytes(b"cover")
    (knowledge_dir / "merged_knowledge_base.md").write_text("# Doc", encoding="utf-8")

    imports._unpack_files(
        extract_dir,
        "math-imported",
        user_id="user_a",
        file_id_map={},
    )

    assert fake.writes["users/user_a/subjects/math-imported/assets/docgen/cover.png"] == b"cover"
    assert fake.writes["users/user_a/subjects/math-imported/knowledge_markdowns/merged_knowledge_base.md"] == b"# Doc"
    assert "users/user_a/subjects/math-imported/knowledge_markdowns/cover.png" not in fake.writes
