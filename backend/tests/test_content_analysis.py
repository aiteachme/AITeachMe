from __future__ import annotations

from app.shared.infra.tools.builtin.content_analysis import (
    build_term_coverage,
    extract_key_terms,
    extract_term_excerpts,
    find_missing_terms,
)


def test_extract_key_terms_prefers_required_elements_and_detects_terms() -> None:
    markdown = """
    # 偏导数

    偏导数描述多元函数沿某一个坐标方向的变化率。
    梯度可以看成偏导数的有序组合，方向导数则刻画任意方向上的变化趋势。
    """

    terms = extract_key_terms(
        markdown,
        seed_terms=["偏导数", "梯度", "方向导数"],
        limit=6,
    )

    assert "偏导数" in terms
    assert "梯度" in terms
    assert "方向导数" in terms


def test_extract_term_excerpts_returns_short_supporting_sentences() -> None:
    markdown = """
    偏导数描述多元函数沿某一个坐标方向的变化率。
    梯度可以看成偏导数的有序组合。
    """

    excerpts = extract_term_excerpts(markdown, ["偏导数", "梯度"])

    assert "偏导数" in excerpts
    assert "变化率" in excerpts["偏导数"]
    assert "梯度" in excerpts


def test_build_term_coverage_and_missing_terms_detect_gaps() -> None:
    markdown = """
    本章介绍偏导数的定义，并用图像解释梯度的方向意义。
    """

    rows = build_term_coverage(markdown, ["偏导数", "梯度", "方向导数"])
    missing = find_missing_terms(markdown, ["偏导数", "梯度", "方向导数"])

    assert rows[0]["covered"] is True
    assert rows[1]["covered"] is True
    assert rows[2]["covered"] is False
    assert missing == ["方向导数"]
