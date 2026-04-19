from app.workflows.digest.common.markdown_knowledge_anchors import extract_markdown_knowledge_units


def test_extract_markdown_knowledge_units_keeps_section_body_and_images():
    markdown = """# 勾股定理 <!-- ATM_KU: ku_pythagorean-theorem -->

直角三角形两直角边平方和等于斜边平方。

![勾股图](../assets/demo/pythagorean.png)

[prerequisite: 三角形]

# 三角形 <!-- ATM_KU: ku_triangle -->

三角形是由三条线段首尾相接组成的平面图形。
"""

    units = extract_markdown_knowledge_units(markdown)

    assert len(units) == 2
    first = units[0]
    assert first.name == "勾股定理"
    assert "直角三角形两直角边平方和等于斜边平方。" in first.body_markdown
    assert "![勾股图](../assets/demo/pythagorean.png)" in first.body_markdown
    assert first.knowledge_images == ["![勾股图](../assets/demo/pythagorean.png)"]
    assert "勾股图" not in first.summary
