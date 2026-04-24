from __future__ import annotations

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
        cover_markdown="![](assets/docgen/docgen_cover_demo.png)",
    )

    assert merged.lstrip().startswith("![](assets/docgen/docgen_cover_demo.png)")
    assert "# 知识文档总览" in merged
    assert "## 目录" in merged
    assert merged.index("![](assets/docgen/docgen_cover_demo.png)") < merged.index("# 知识文档总览")
    assert merged.index("## 目录") > merged.index("# 知识文档总览")


def test_cover_size_candidates_use_square_fallback_for_openai_compatible_gateway_models() -> None:
    assert _cover_size_candidates(
        "doubao-seedream-4-0",
        api_base="https://gateway.example.com/v1",
    ) == ("1024x1024",)
