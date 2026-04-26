from app.workflows.digest.kg_doc_sync.inputs import (
    extract_doc_chapter_metadatas,
    resolve_graph_input_paths,
)


def test_extract_doc_chapter_metadatas_matches_sync_chapter_split():
    markdown = """# 初中数学总复习

这是一份总览，不应该单独当成图谱同步章节。

## 一元一次方程

移项、合并同类项和检验解是本章主线。

## 几何证明

辅助线和全等判定是本章主线。
"""

    chapters = extract_doc_chapter_metadatas(markdown)

    assert [item["title"] for item in chapters] == ["一元一次方程", "几何证明"]
    assert [item["chapter_index"] for item in chapters] == [1, 2]
    assert "移项" in str(chapters[0]["summary"])


def test_resolve_graph_input_paths_names_actual_sync_sources():
    assert resolve_graph_input_paths(file_ids=[], knowledge_doc_markdown="") == ["none"]
    assert resolve_graph_input_paths(file_ids=[1], knowledge_doc_markdown="") == ["source_files"]
    assert resolve_graph_input_paths(file_ids=[], knowledge_doc_markdown="# 文档") == ["knowledge_doc"]
    assert resolve_graph_input_paths(file_ids=[1], knowledge_doc_markdown="# 文档") == [
        "knowledge_doc",
        "source_files",
    ]
