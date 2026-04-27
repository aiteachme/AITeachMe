import app.workflows.digest.kg_doc_sync.inputs as kg_doc_sync_inputs
from app.workflows.digest.kg_doc_sync.inputs import (
    build_knowledge_doc_sync_input_from_docgen_state,
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


def test_build_knowledge_doc_sync_input_from_docgen_state(monkeypatch):
    monkeypatch.setattr(
        kg_doc_sync_inputs,
        "_load_docgen_manifest",
        lambda subject: {"build_metadata": {"version_no": 4}, "document_backbone_snapshot": {}},
    )
    monkeypatch.setattr(
        kg_doc_sync_inputs,
        "_load_subject_document_summary",
        lambda subject: {"summary": "线性代数"},
    )

    sync_input = build_knowledge_doc_sync_input_from_docgen_state(
        "math",
        {
            "merged_markdown": "# 第一章\n\n矩阵与向量。",
            "doc_ids": [11],
            "chapter_metadatas": [
                {
                    "chapter_index": 1,
                    "title": "第一章",
                    "summary": "矩阵与向量",
                    "source_file_ids": [7],
                }
            ],
        },
    )

    assert sync_input is not None
    assert sync_input.source == "docgen_state"
    assert sync_input.markdown.startswith("# 第一章")
    assert sync_input.structured_context["doc_version_no"] == 4
    assert sync_input.structured_context["document_summary_json"] == {"summary": "线性代数"}
    assert sync_input.structured_context["chapters"] == [
        {
            "knowledge_document_id": 11,
            "chapter_index": 1,
            "title": "第一章",
            "summary": "矩阵与向量",
            "source_file_ids": [7],
            "source_scope": {},
            "manifest": {},
        }
    ]
