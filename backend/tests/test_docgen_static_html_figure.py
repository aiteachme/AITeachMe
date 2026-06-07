from app.shared.infra.tools.builtin.markdown_processing import validate_single_file_html
from app.workflows.digest.docgen.lib.figure_spec import (
    FigureElement,
    FigureSpec,
    normalize_figure_spec,
    render_figure_spec_html,
)
from app.workflows.digest.docgen.lib.static_html_figure import _score_static_figure_signal


def test_static_figure_scoring_prefers_problem_diagram_for_mechanics_context() -> None:
    score, goal, figure_type = _score_static_figure_signal(
        "平面汇交力系的合成",
        "如图所示，将力 F2 平移到力 F1 的端点，首尾相接后，从起点到终点的向量即为合力 FR。",
    )

    assert score >= 6
    assert figure_type == "problem_diagram"
    assert "题图" in goal or "变量" in goal


def test_static_figure_scoring_is_not_mechanics_only() -> None:
    score, goal, figure_type = _score_static_figure_signal(
        "辛亥革命的历史进程",
        "第一阶段是思想传播，第二阶段是组织动员，第三阶段是武昌起义，最后推动政治制度转型。",
    )

    assert score >= 6
    assert figure_type == "process_steps"
    assert "步骤" in goal or "过程" in goal


def test_static_figure_scoring_supports_general_comparison_tables() -> None:
    score, _goal, figure_type = _score_static_figure_signal(
        "细胞有丝分裂与减数分裂比较",
        "比较两类分裂的发生位置、染色体行为、子细胞数量和遗传物质变化，注意同源染色体联会这一易错点。",
    )

    assert score >= 6
    assert figure_type == "comparison_table"


def test_rendered_figure_is_single_file_static_html() -> None:
    spec = FigureSpec(
        type="problem_diagram",
        title="力的三角形法则",
        summary="把力 F2 平移到力 F1 的端点。",
        elements=[
            FigureElement(kind="point", id="O", label="O", x=18, y=72),
            FigureElement(kind="point", id="A", label="A", x=46, y=72),
            FigureElement(kind="point", id="B", label="B", x=72, y=42),
            FigureElement(kind="vector", from_id="O", to_id="A", label="F1"),
            FigureElement(kind="vector", from_id="A", to_id="B", label="F2"),
            FigureElement(kind="vector", from_id="O", to_id="B", label="FR"),
        ],
        annotations=["力三角形法则"],
        emphasis=["首尾相接找合力"],
        source_refs=["把力 F2 平移到力 F1 的端点"],
    )

    html = render_figure_spec_html(spec, title="力的三角形法则")

    assert "<!DOCTYPE html>" in html
    assert "<svg" in html
    assert "<script" not in html.lower()
    assert validate_single_file_html(html) == []


def test_normalize_figure_spec_replaces_untraceable_source_refs() -> None:
    context = "平面汇交力系：所有力都汇交于一点。力的三角形法则用于求合力。"
    spec = FigureSpec(
        type="concept_map",
        title="平面汇交力系",
        source_refs=["这句话不在正文中"],
        elements=[FigureElement(kind="step", text="所有力都汇交于一点")],
    )

    normalized, report = normalize_figure_spec(
        spec,
        fallback_title="平面汇交力系图示",
        context=context,
    )

    assert normalized.source_refs
    assert normalized.source_refs[0] in context
    assert report["source_ref_replacements"] == 1
