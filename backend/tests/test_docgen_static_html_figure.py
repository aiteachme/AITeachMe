from app.shared.infra.tools.builtin.markdown_processing import validate_single_file_html
from app.workflows.digest.docgen.lib.figure_spec import (
    FigureElement,
    FigureSpec,
    build_fallback_figure_spec,
    is_renderable_problem_diagram,
    normalize_figure_spec,
    render_figure_spec_html,
)
from app.workflows.digest.docgen.lib.static_html_figure import _score_static_figure_signal


def test_static_figure_scoring_prefers_problem_diagram_for_mechanics_context() -> None:
    score, _goal, figure_type = _score_static_figure_signal(
        "平面汇交力系的合成",
        "如图所示，将力 F2 平移到力 F1 的端点，首尾相接后，从起点到终点的向量即为合力 FR。",
    )

    assert score >= 6
    assert figure_type == "problem_diagram"


def test_static_figure_scoring_is_not_mechanics_only() -> None:
    score, _goal, figure_type = _score_static_figure_signal(
        "辛亥革命的历史进程",
        "第一阶段是思想传播，第二阶段是组织动员，第三阶段是武昌起义，最后推动政治制度转型。",
    )

    assert score < 6
    assert figure_type == "problem_diagram"


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


def test_generic_shape_primitives_render_as_single_svg_figure() -> None:
    spec = FigureSpec(
        type="problem_diagram",
        title="通用题图",
        elements=[
            FigureElement(kind="axis", label="x", x=12, y=72, x2=92, y2=72),
            FigureElement(kind="shape", shape_type="ellipse", label="E", x=52, y=50, rx=24, ry=14),
            FigureElement(kind="shape", shape_type="region", points=[[30, 72], [52, 34], [74, 72]], style="highlight"),
            FigureElement(kind="shape", shape_type="angle", label="θ", x=52, y=72, r=12, start_angle=35, end_angle=76),
            FigureElement(kind="shape", shape_type="arc", label="s", x=52, y=50, r=18, start_angle=210, end_angle=330),
        ],
        source_refs=["题图中标出坐标轴、曲线区域和角度关系"],
    )

    html = render_figure_spec_html(spec, title="通用题图")

    assert "<svg" in html
    assert "<ellipse" in html
    assert "<polygon" in html
    assert " A" in html
    assert "<table" not in html.lower()
    assert validate_single_file_html(html) == []


def test_model_supplied_coordinate_primitives_render_without_subject_template() -> None:
    spec = FigureSpec(
        type="problem_diagram",
        title="模型规划的坐标题图",
        elements=[
            FigureElement(kind="axis", label="x", x=12, y=80, x2=92, y2=80),
            FigureElement(kind="axis", label="y", x=20, y=88, x2=20, y2=14),
            FigureElement(kind="curve", label="y=f(x)", x=22, y=76, x2=84, y2=24),
            FigureElement(kind="point", id="P", label="P", x=56, y=46),
            FigureElement(kind="line", label="切线", x=32, y=64, x2=82, y2=32),
        ],
        source_refs=["函数图像在一点处的切线斜率"],
    )

    normalized, report = normalize_figure_spec(
        spec,
        fallback_title="模型规划的坐标题图",
        context="函数图像在一点处的切线斜率。",
    )
    html = render_figure_spec_html(normalized, title="模型规划的坐标题图")

    assert report["warnings"] == []
    assert is_renderable_problem_diagram(normalized)
    assert "<path" in html
    assert "切线" in html
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


def test_static_figure_normalization_does_not_fallback_to_fake_diagram() -> None:
    normalized, report = normalize_figure_spec(
        FigureSpec(type="problem_diagram", title="空图"),
        fallback_title="空图",
        context="这一段没有足够图形条件。",
    )

    assert normalized.elements == []
    assert not is_renderable_problem_diagram(normalized)
    assert "fallback_elements_used" not in report["warnings"]


def test_fallback_problem_diagram_draws_coordinate_context() -> None:
    spec = build_fallback_figure_spec(
        title="一次函数图像图示",
        figure_type="problem_diagram",
        context="一次函数 y=2x+1 的图像是一条直线，斜率决定上升或下降，截距是与 y 轴的交点。",
    )

    assert is_renderable_problem_diagram(spec)
    assert {item.kind for item in spec.elements} >= {"axis", "line", "point"}


def test_fallback_problem_diagram_draws_parallel_line_angle_context() -> None:
    spec = build_fallback_figure_spec(
        title="平行线与角图示",
        figure_type="problem_diagram",
        context="两条平行线被一条截线所截，同位角相等，内错角相等；若一个角是 35°，对应角也相等。",
    )

    assert is_renderable_problem_diagram(spec)
    assert any(item.kind == "shape" and item.shape_type == "angle" for item in spec.elements)


def test_normalize_figure_spec_does_not_invent_diagram_from_table() -> None:
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

    assert normalized.type == "concept_map"
    assert "comparison_table_coerced_to_concept_map" in report["warnings"]
    assert not is_renderable_problem_diagram(normalized)
    assert "<svg" in html
    assert "<table" not in html.lower()
