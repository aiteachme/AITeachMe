import pytest

from app.api.files import _restore_static_docgen_figure_asset
from app.workflows.digest.docgen.lib.figure_spec import FigureElement, FigureSpec


class _FakeContentStore:
    def __init__(self, manifest: dict) -> None:
        self.manifest = manifest
        self.written: dict[str, str] = {}

    async def read_json_raw(self, key: str) -> dict:
        assert key == "users/u1/courses/course_demo/knowledge_markdowns/docgen_manifest.json"
        return self.manifest

    async def write_text(self, key: str, content: str) -> None:
        self.written[key] = content


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_restore_static_docgen_figure_asset_from_manifest() -> None:
    spec = FigureSpec(
        type="problem_diagram",
        title="导数切线图示",
        elements=[
            FigureElement(kind="axis", label="x", x=12, y=78, x2=92, y2=78),
            FigureElement(kind="axis", label="y", x=18, y=88, x2=18, y2=16),
            FigureElement(kind="curve", label="y=f(x)", x=22, y=76, x2=84, y2=28),
            FigureElement(kind="point", id="P", label="P", x=56, y=46),
            FigureElement(kind="line", label="切线", x=34, y=64, x2=82, y2=34),
        ],
        source_refs=["导数表示函数图像在一点处的切线斜率"],
    )
    manifest = {
        "asset_manifest": {
            "assets": [
                {
                    "kind": "static_html_figure",
                    "asset_path": "docgen/figures/missing.html",
                    "title": "导数切线图示",
                    "figure_spec": spec.model_dump(mode="json"),
                }
            ]
        }
    }
    store = _FakeContentStore(manifest)

    restored = await _restore_static_docgen_figure_asset(
        content_store=store,
        manifest_key="users/u1/courses/course_demo/knowledge_markdowns/docgen_manifest.json",
        storage_key="users/u1/courses/course_demo/assets/docgen/figures/missing.html",
        normalized_asset_path="docgen/figures/missing.html",
    )

    assert restored is not None
    assert b"<!DOCTYPE html>" in restored
    assert "users/u1/courses/course_demo/assets/docgen/figures/missing.html" in store.written
    assert "<script" not in store.written["users/u1/courses/course_demo/assets/docgen/figures/missing.html"].lower()
