from app.workflows.digest.common.markdown_knowledge_anchors import (
    extract_markdown_knowledge_units,
    extract_markdown_section_chunks,
)


def test_extract_markdown_knowledge_units_keeps_section_body_and_images():
    markdown = """# Pythagorean Theorem <!-- ATM_KU: ku_pythagorean-theorem -->

In a right triangle, the sum of the squares of the two legs equals the square of the hypotenuse.
![Pythagorean figure](../assets/demo/pythagorean.png)

[prerequisite: Triangle]

# Triangle <!-- ATM_KU: ku_triangle -->

A triangle is a polygon with three edges and three vertices.
"""

    units = extract_markdown_knowledge_units(markdown)

    assert len(units) == 2
    first = units[0]
    assert first.name == "Pythagorean Theorem"
    assert "sum of the squares" in first.body_markdown
    assert "![Pythagorean figure](../assets/demo/pythagorean.png)" in first.body_markdown
    assert first.knowledge_images == ["![Pythagorean figure](../assets/demo/pythagorean.png)"]
    assert "Pythagorean figure" not in first.summary


def test_extract_markdown_knowledge_units_skips_reading_guide_headings():
    markdown = """# How To Read This Document

Start with the roadmap, then move into the main concepts.

# Derivative

Derivative describes the instantaneous rate of change.

## Learning Goals

Understand the definition and geometric meaning.

## Geometric Meaning

Derivative can represent the slope of a tangent line.
"""

    units = extract_markdown_knowledge_units(markdown)

    assert [unit.name for unit in units] == ["Derivative", "Geometric Meaning"]


def test_extract_markdown_section_chunks_keeps_heading_path():
    markdown = """# Derivative

Derivative describes change rate.

## Geometric Meaning

Derivative can represent the slope of a tangent line.
"""

    chunks = extract_markdown_section_chunks(markdown)

    assert [chunk.title for chunk in chunks] == ["Derivative", "Geometric Meaning"]
    assert [chunk.header_path for chunk in chunks] == [
        "Derivative",
        "Derivative > Geometric Meaning",
    ]
