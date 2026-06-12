from app.shared.infra.tools.builtin.markdown_processing import validate_single_file_html
from app.workflows.digest.docgen.lib.figure_spec import (
    FigureElement,
    FigureSpec,
    build_fallback_figure_spec,
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


def test_static_figure_scoring_keeps_function_tangent_as_problem_diagram() -> None:
    score, _goal, figure_type = _score_static_figure_signal(
        "导数、切线斜率与切线方程",
        "例题：求 y=x^2 在 x=1 处的切线方程。导数表示函数图像在一点处的切线斜率。",
    )

    assert score >= 6
    assert figure_type == "problem_diagram"


def test_static_figure_scoring_does_not_promote_plain_comparison_tables() -> None:
    score, _goal, figure_type = _score_static_figure_signal(
        "细胞有丝分裂与减数分裂比较",
        "比较两类分裂的发生位置、染色体行为、子细胞数量和遗传物质变化，注意同源染色体联会这一易错点。",
    )

    assert score < 6
    assert figure_type != "comparison_table"


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
    assert "把力 F2 平移到力 F1 的端点。" not in html
    assert "记忆：" not in html
    assert "对应正文" not in html
    assert "atm-caption" not in html
    assert validate_single_file_html(html) == []


def test_process_figure_renders_as_svg_not_table() -> None:
    spec = FigureSpec(
        type="process_steps",
        title="辛亥革命的历史进程",
        summary="把历史进程画成阶段推进关系。",
        elements=[
            FigureElement(kind="step", label="阶段一", text="思想传播"),
            FigureElement(kind="step", label="阶段二", text="组织动员"),
            FigureElement(kind="step", label="阶段三", text="武昌起义"),
        ],
        source_refs=["第一阶段是思想传播，第二阶段是组织动员"],
    )

    html = render_figure_spec_html(spec, title="辛亥革命的历史进程")

    assert "<svg" in html
    assert "<table" not in html.lower()
    assert validate_single_file_html(html) == []


def test_formula_figure_renders_as_svg_not_table() -> None:
    spec = FigureSpec(
        type="formula_derivation",
        title="导数定义到切线斜率",
        summary="把平均变化率到瞬时变化率的极限关系画出来。",
        elements=[
            FigureElement(kind="formula", label="平均变化率", text="Δy / Δx"),
            FigureElement(kind="formula", label="取极限", text="Δx -> 0"),
            FigureElement(kind="formula", label="导数", text="f'(x)"),
        ],
        source_refs=["导数表示函数在某点的瞬时变化率"],
    )

    html = render_figure_spec_html(spec, title="导数定义到切线斜率")

    assert "<svg" in html
    assert "<table" not in html.lower()
    assert validate_single_file_html(html) == []


def test_tangent_formula_context_is_rendered_as_coordinate_diagram() -> None:
    context = "例题：求 y=x^2 在 x=1 处的切线方程。导数表示函数图像在一点处的切线斜率。"
    spec = FigureSpec(
        type="formula_derivation",
        title="导数、切线斜率与切线方程",
        summary="把导数定义和切线斜率对应起来。",
        elements=[
            FigureElement(kind="formula", label="求导", text="f'(x)=2x"),
            FigureElement(kind="formula", label="代入", text="f'(1)=2"),
            FigureElement(kind="formula", label="切线", text="y-f(x0)=f'(x0)(x-x0)"),
        ],
        source_refs=["导数表示函数图像在一点处的切线斜率"],
    )

    normalized, report = normalize_figure_spec(
        spec,
        fallback_title="导数、切线斜率与切线方程图示",
        context=context,
    )
    html = render_figure_spec_html(normalized, title="导数、切线斜率与切线方程图示")

    assert normalized.type == "problem_diagram"
    assert "visual_context_forced_problem_diagram" in report["warnings"]
    assert "<path" in html
    assert "切线" in html
    assert "<table" not in html.lower()
    assert validate_single_file_html(html) == []


def test_function_mapping_fallback_renders_mapping_diagram() -> None:
    spec = build_fallback_figure_spec(
        title="函数概念与复合函数图示",
        figure_type="problem_diagram",
        context="函数是定义域到值域的对应关系；每个 x 只能对应唯一的 y，复合函数先内后外。",
        goal="画出函数的唯一对应关系。",
    )
    html = render_figure_spec_html(spec, title="函数概念与复合函数图示")

    assert spec.type == "problem_diagram"
    assert "定义域" in html
    assert "值域" in html
    assert "每个 x 只能对应一个 y" in html
    assert "<table" not in html.lower()
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


def test_normalize_figure_spec_coerces_derivative_table_to_diagram() -> None:
    context = "导数的几何意义是切线斜率，物理意义是瞬时速度。"
    spec = FigureSpec(
        type="comparison_table",
        title="导数意义图示",
        elements=[
            FigureElement(kind="table_row", cells=["几何意义", "切线斜率"]),
            FigureElement(kind="table_row", cells=["物理意义", "瞬时速度"]),
        ],
        source_refs=["导数的几何意义是切线斜率"],
    )

    normalized, report = normalize_figure_spec(
        spec,
        fallback_title="导数意义图示",
        context=context,
    )
    html = render_figure_spec_html(normalized, title="导数意义图示")

    assert normalized.type == "problem_diagram"
    assert "comparison_table_coerced_to_concept_map" in report["warnings"]
    assert "visual_context_forced_problem_diagram" in report["warnings"]
    assert "<svg" in html
    assert "<path" in html
    assert "<table" not in html.lower()
