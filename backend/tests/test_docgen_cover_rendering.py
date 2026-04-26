from __future__ import annotations

import asyncio

from app.workflows.digest.docgen.lib import cover
from app.workflows.digest.docgen.lib.cover import _cover_size_candidates
from app.workflows.digest.docgen.lib.publish import build_merged_markdown


def test_merged_markdown_places_cover_first_and_toc_after_overview_h1() -> None:
    merged = build_merged_markdown(
        [
            {
                "chapter_index": 1,
                "title": "Chapter One",
                "markdown": "# Chapter One\n\n## Core Content\n\nBody",
            }
        ],
        document_context={"subject": "demo", "include_sources": False},
        cover_markdown="![](../assets/docgen/cover.png)",
    )

    assert merged.lstrip().startswith("![](../assets/docgen/cover.png)")
    assert "# 知识文档总览" in merged
    assert "## 目录" in merged
    assert merged.index("![](../assets/docgen/cover.png)") < merged.index("# 知识文档总览")
    assert merged.index("## 目录") > merged.index("# 知识文档总览")


def test_cover_size_candidates_use_square_fallback_for_openai_compatible_gateway_models() -> None:
    assert _cover_size_candidates(
        "doubao-seedream-4-0",
        api_base="https://gateway.example.com/v1",
    ) == ("1024x1024",)


def test_docgen_cover_cleanup_keeps_only_current_stable_cover(monkeypatch) -> None:
    class FakeContentStore:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        async def list_prefix(self, prefix: str) -> list[str]:
            assert prefix == "users/local/subjects/math/assets/docgen/"
            return [
                "users/local/subjects/math/assets/docgen/cover.png",
                "users/local/subjects/math/assets/docgen/docgen_cover_old.png",
                "users/local/subjects/math/assets/docgen/notes.txt",
            ]

        async def delete(self, key: str) -> None:
            self.deleted.append(key)

    fake = FakeContentStore()
    monkeypatch.setattr(cover, "get_content_store", lambda: fake)

    asyncio.run(
        cover._cleanup_stale_docgen_covers(
            namespace="users/local/subjects/math",
            keep_key="users/local/subjects/math/assets/docgen/cover.png",
        )
    )

    assert fake.deleted == ["users/local/subjects/math/assets/docgen/docgen_cover_old.png"]
