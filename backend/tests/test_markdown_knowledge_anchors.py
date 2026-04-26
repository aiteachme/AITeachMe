from app.workflows.digest.common.markdown_knowledge_anchors import (
    ensure_markdown_knowledge_unit_anchors,
    extract_markdown_chapter_chunks,
    extract_markdown_knowledge_units,
)


def test_docs_sync_ignores_teaching_scaffold_headings():
    markdown = ensure_markdown_knowledge_unit_anchors(
        """
# 极限的定义

## 章节路线图

## 洛必达法则

### 本章要点

### 学习目标

### 本章自检

## 等价无穷小替换
""".strip()
    )

    units = extract_markdown_knowledge_units(markdown)
    names = [unit.name for unit in units]

    assert "极限的定义" in names
    assert "洛必达法则" in names
    assert "等价无穷小替换" in names
    assert "章节路线图" not in names
    assert "本章要点" not in names
    assert "学习目标" not in names
    assert "本章自检" not in names


def test_single_document_title_uses_h2_chapters_for_sync():
    markdown = """
# 初中数学复习讲义

## 一元一次方程
一元一次方程是只含有一个未知数的一次方程。

## 全等三角形判定
常见判定包括 SSS、SAS、ASA、AAS 和 HL。
""".strip()

    chunks = extract_markdown_chapter_chunks(markdown)

    assert [chunk.title for chunk in chunks] == ["一元一次方程", "全等三角形判定"]
