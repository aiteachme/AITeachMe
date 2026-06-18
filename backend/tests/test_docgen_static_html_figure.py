import asyncio
from types import SimpleNamespace

from app.shared.infra.tools.builtin.markdown_processing import validate_single_file_html
from app.shared.infra.execution import TracedExecutionContext
from app.workflows.digest.docgen.lib import static_html_figure as static_figures
from app.workflows.digest.docgen.lib.figure_spec import (
    FigureElement,
    FigureSpec,
    assess_static_figure_layout,
    build_fallback_figure_spec,
    is_renderable_problem_diagram,
    is_renderable_static_figure,
    normalize_figure_spec,
    render_figure_spec_html,
)
from app.workflows.digest.docgen.lib.models import ChapterDraft
from app.workflows.digest.docgen.prompts.static_html_figure import build_static_html_figure_selection_messages


class _FakeContentStore:
    def __init__(self) -> None:
        self.text_writes: dict[str, str] = {}

    async def write_text(self, key: str, content: str) -> None:
        self.text_writes[key] = content


def _figure_selection(*indexes: int) -> object:
    return static_figures._StaticFigureSelection(
        selected=[
            static_figures._StaticFigureSelectionItem(
                index=index,
                figure_goal="用示意图讲清关键关系。",
                figure_type="problem_diagram",
                reason="模型判断这段有可视化增量。",
            )
            for index in indexes
        ]
    )


def test_static_figure_selection_prompt_makes_llm_decide_trigger() -> None:
    messages = build_static_html_figure_selection_messages(
        chapter_title="函数图像",
        digest_mode="systematic",
        max_assets=1,
        candidates=[
            {
                "index": 1,
                "title": "函数图像与斜率",
                "context": "斜率、截距和图像位置需要一起观察。",
            }
        ],
    )
    text = "\n".join(message["content"] for message in messages)

    assert "本阶段只判断" in text
    assert "一个都不选" in text
    assert "不要按学科关键词" in text
    assert '{"selected":[]}' in text


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


def test_formula_derivation_renders_basic_superscripts_and_subscripts() -> None:
    spec = FigureSpec(
        type="formula_derivation",
        title="平方公式",
        elements=[
            FigureElement(kind="formula", label="原式", text="(a+b)^2"),
            FigureElement(kind="formula", label="合并", text="x_i^2+2ab"),
        ],
    )

    html = render_figure_spec_html(spec, title="平方公式")

    assert 'baseline-shift="super"' in html
    assert 'baseline-shift="sub"' in html
    assert "(a+b)" in html
    assert validate_single_file_html(html) == []


def test_text_only_process_steps_are_not_publishable_even_if_renderer_can_draw_them() -> None:
    spec = FigureSpec(
        type="process_steps",
        title="三步审题法",
        elements=[
            FigureElement(kind="step", label="1", text="读题找条件"),
            FigureElement(kind="step", label="2", text="转化为目标"),
            FigureElement(kind="step", label="3", text="选择方法"),
        ],
        source_refs=["读题 -> 条件 -> 目标 -> 方法"],
    )

    html = render_figure_spec_html(spec, title="三步审题法")
    report = assess_static_figure_layout(spec)

    assert not is_renderable_static_figure(spec)
    assert report["ok"] is False
    assert "text_only_static_figure" in report["issues"]
    assert "<svg" in html
    assert "读题找条件" in html
    assert "<table" not in html.lower()
    assert validate_single_file_html(html) == []


def test_non_problem_visual_boxes_are_not_promoted_to_publishable_diagrams() -> None:
    spec = FigureSpec(
        type="formula_derivation",
        title="完全平方公式",
        elements=[
            FigureElement(kind="shape", id="start", shape_type="rectangle", label="原式"),
            FigureElement(kind="shape", id="expand", shape_type="rectangle", label="展开"),
            FigureElement(kind="shape", id="merge", shape_type="rectangle", label="合并"),
            FigureElement(kind="vector", from_id="start", to_id="expand", label="->"),
            FigureElement(kind="vector", from_id="expand", to_id="merge", label="->"),
        ],
        source_refs=["先展开，再合并同类项"],
    )

    normalized, report = normalize_figure_spec(
        spec,
        fallback_title="完全平方公式图示",
        context="先展开，再合并同类项。",
    )

    assert normalized.type == "formula_derivation"
    assert "visual_primitives_coerced_to_problem_diagram" not in report["warnings"]
    assert not is_renderable_static_figure(normalized)
    assert "text_only_static_figure" in assess_static_figure_layout(normalized)["issues"]


def test_problem_diagram_renderer_does_not_apply_semantic_blacklist() -> None:
    spec = FigureSpec(
        type="problem_diagram",
        title="完全平方公式",
        elements=[
            FigureElement(kind="shape", id="start", shape_type="rectangle", label="(a+b)^2"),
            FigureElement(kind="shape", id="a2", shape_type="rectangle", label="a²"),
            FigureElement(kind="shape", id="ab", shape_type="rectangle", label="ab"),
            FigureElement(kind="shape", id="ba", shape_type="rectangle", label="ba"),
            FigureElement(kind="shape", id="b2", shape_type="rectangle", label="b²"),
            FigureElement(kind="line", from_id="start", to_id="a2"),
            FigureElement(kind="line", from_id="start", to_id="ab"),
            FigureElement(kind="callout", label="ab+ba"),
        ],
        source_refs=["先展开成 a^2+ab+ba+b^2，再合并同类项"],
    )

    report = assess_static_figure_layout(spec)

    assert is_renderable_static_figure(spec)
    assert report["ok"] is True
    assert "text_only_relation_diagram" not in report["issues"]


def test_empty_concept_map_does_not_invent_default_nodes() -> None:
    spec = FigureSpec(type="concept_map", title="空概念图")

    html = render_figure_spec_html(spec, title="空概念图")
    report = assess_static_figure_layout(spec)

    assert not is_renderable_static_figure(spec)
    assert report["ok"] is False
    assert "text_only_static_figure" in report["issues"]
    assert "核心概念" not in html
    assert "条件" not in html
    assert "结论" not in html


def test_static_figure_layout_accepts_clear_vector_diagram() -> None:
    spec = FigureSpec(
        type="problem_diagram",
        title="力的三角形法则",
        elements=[
            FigureElement(kind="point", id="O", label="O", x=18, y=72),
            FigureElement(kind="point", id="A", label="A", x=46, y=72),
            FigureElement(kind="point", id="B", label="B", x=72, y=42),
            FigureElement(kind="vector", from_id="O", to_id="A", label="F1"),
            FigureElement(kind="vector", from_id="A", to_id="B", label="F2"),
            FigureElement(kind="vector", from_id="O", to_id="B", label="FR"),
        ],
        source_refs=["把力 F2 平移到力 F1 的端点"],
    )

    report = assess_static_figure_layout(spec)

    assert report["ok"] is True
    assert report["issues"] == []


def test_static_figure_layout_rejects_overlapped_label_cluster() -> None:
    spec = FigureSpec(
        type="problem_diagram",
        title="变量位置图示",
        elements=[
            FigureElement(kind="shape", shape_type="rectangle", label="p_a", x=50, y=50, rx=4, ry=4),
            FigureElement(kind="shape", shape_type="rectangle", label="p_b", x=51, y=50, rx=4, ry=4),
            FigureElement(kind="shape", shape_type="rectangle", label="sum", x=52, y=50, rx=4, ry=4),
            FigureElement(kind="label", text="执行顺序", x=50, y=54),
            FigureElement(kind="callout", text="语句顺序", x=51, y=54),
        ],
        source_refs=["变量在程序中的位置关系"],
    )

    report = assess_static_figure_layout(spec)

    assert report["ok"] is False
    assert "label_overlap" in report["issues"]


def test_static_figure_layout_rejects_decorative_node_piles() -> None:
    spec = FigureSpec(
        type="problem_diagram",
        title="孤立节点",
        elements=[
            FigureElement(kind="shape", shape_type="rectangle", label="输入", x=25, y=45, rx=8, ry=7),
            FigureElement(kind="shape", shape_type="rectangle", label="处理", x=50, y=45, rx=8, ry=7),
            FigureElement(kind="shape", shape_type="rectangle", label="输出", x=75, y=45, rx=8, ry=7),
        ],
        source_refs=["输入、处理、输出三个词被列出"],
    )

    report = assess_static_figure_layout(spec)

    assert report["ok"] is False
    assert "text_only_relation_diagram" in report["issues"]


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


def test_shape_labels_are_rendered_inside_visual_nodes() -> None:
    spec = FigureSpec(
        type="problem_diagram",
        title="状态更新",
        elements=[
            FigureElement(kind="shape", shape_type="rectangle", label="a=3", x=28, y=48, rx=8, ry=7),
            FigureElement(kind="shape", shape_type="rectangle", label="sum", x=72, y=48, rx=8, ry=7),
            FigureElement(kind="vector", label="赋值", x=38, y=48, x2=62, y2=48),
        ],
        source_refs=["执行 sum=a+b 后更新变量状态"],
    )

    html = render_figure_spec_html(spec, title="状态更新")

    assert '<text x="196.5" y="158.1" text-anchor="middle"' in html
    assert '<text x="423.5" y="158.1" text-anchor="middle"' in html


def test_rendered_figure_preserves_chinese_labels() -> None:
    spec = FigureSpec(
        type="problem_diagram",
        title="审题推导路径",
        elements=[
            FigureElement(kind="shape", id="read", shape_type="rectangle", label="读题"),
            FigureElement(kind="shape", id="known", shape_type="rectangle", label="条件"),
            FigureElement(kind="shape", id="goal", shape_type="rectangle", label="目标"),
            FigureElement(kind="vector", from_id="read", to_id="known", label="提取"),
            FigureElement(kind="vector", from_id="known", to_id="goal", label="转化"),
        ],
        source_refs=["先标出已知条件，再写出目标"],
    )

    html = render_figure_spec_html(spec, title="审题推导路径")

    assert "审题推导路径" in html
    assert "读题" in html
    assert "条件" in html
    assert "目标" in html
    assert "提取" in html
    assert "转化" in html
    assert "??" not in html


def test_problem_diagram_renders_relation_annotations_from_model() -> None:
    spec = FigureSpec(
        type="problem_diagram",
        title="指针关系",
        elements=[
            FigureElement(kind="shape", shape_type="rectangle", label="sum", x=36, y=48, rx=8, ry=7),
            FigureElement(kind="shape", shape_type="rectangle", label="p", x=70, y=48, rx=8, ry=7),
            FigureElement(kind="vector", label="&sum", x=48, y=48, x2=60, y2=48),
            FigureElement(kind="relation", label="*p=sum", x=56, y=64),
        ],
        source_refs=["p 保存 sum 的地址，*p 读到的是 sum 当前的值"],
    )

    report = assess_static_figure_layout(spec)
    html = render_figure_spec_html(spec, title="指针关系")

    assert report["ok"] is True
    assert "*p=sum" in html


def test_vectors_can_connect_shape_ids_without_zero_length_arrow() -> None:
    spec = FigureSpec(
        type="problem_diagram",
        title="形状连接",
        elements=[
            FigureElement(kind="shape", id="left", shape_type="rectangle", label="A", x=28, y=48, rx=8, ry=7),
            FigureElement(kind="shape", id="right", shape_type="rectangle", label="B", x=72, y=48, rx=8, ry=7),
            FigureElement(kind="vector", from_id="left", to_id="right", label="到达"),
        ],
        source_refs=["A 到达 B"],
    )

    html = render_figure_spec_html(spec, title="形状连接")

    assert 'x1="186.2" y1="157.0" x2="433.8" y2="157.0"' in html
    assert 'x1="310.0" y1="157.0" x2="310.0" y2="157.0"' not in html


def test_relation_graph_specs_are_auto_laid_out_from_shape_ids() -> None:
    spec = FigureSpec(
        type="problem_diagram",
        title="变量状态路径",
        elements=[
            FigureElement(kind="shape", id="a", shape_type="rectangle", label="a=3"),
            FigureElement(kind="shape", id="b", shape_type="rectangle", label="b=5"),
            FigureElement(kind="shape", id="sum", shape_type="rectangle", label="sum=8"),
            FigureElement(kind="vector", from_id="a", to_id="sum", label="+"),
            FigureElement(kind="vector", from_id="b", to_id="sum", label="+"),
        ],
        source_refs=["sum=a+b 后，sum 保存 a 与 b 的结果"],
    )

    normalized, report = normalize_figure_spec(
        spec,
        fallback_title="变量状态路径",
        context="sum=a+b 后，sum 保存 a 与 b 的结果。",
    )
    html = render_figure_spec_html(normalized, title="变量状态路径")

    assert "relation_graph_auto_layout" in report["warnings"]
    assert [item.x for item in normalized.elements[:3]] == [18.0, 18.0, 82.0]
    assert assess_static_figure_layout(normalized)["ok"] is True
    assert html.count("marker-end") == 2


def test_normalize_figure_spec_ignores_model_template_layout() -> None:
    spec = FigureSpec(
        type="problem_diagram",
        title="模型误用模板",
        layout={"template": "legacy_subject_template"},
        elements=[
            FigureElement(kind="shape", shape_type="rectangle", label="a", x=25, y=48, rx=8, ry=7),
            FigureElement(kind="shape", shape_type="rectangle", label="b", x=50, y=48, rx=8, ry=7),
            FigureElement(kind="shape", shape_type="rectangle", label="sum", x=75, y=48, rx=8, ry=7),
            FigureElement(kind="vector", label="a+b", x=56, y=64, x2=70, y2=64),
        ],
        source_refs=["变量区中的 a、b、sum 位置和赋值顺序需要区分"],
    )

    normalized, report = normalize_figure_spec(
        spec,
        fallback_title="模型误用模板",
        context="变量区中的 a、b、sum 位置和赋值顺序需要区分。",
    )
    html = render_figure_spec_html(normalized, title="模型误用模板")

    assert normalized.layout == {}
    assert "template_layout_ignored" in report["warnings"]
    assert "变量内存格" not in html
    assert "sum" in html


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


def test_fallback_problem_diagram_does_not_guess_subject_templates() -> None:
    contexts = [
        "一次函数 y=2x+1 的图像是一条直线，斜率决定上升或下降，截距是与 y 轴的交点。",
        "两条平行线被一条截线所截，同位角相等，内错角相等；若一个角是 35°，对应角也相等。",
        "C 语言中 int a=3, b=5, sum; 执行 sum=a+b 后，变量区中的 a、b、sum 位置和赋值顺序需要区分。",
        "表达式 !a && !b || !c 的求值顺序要按 !、&&、|| 的优先级形成表达式树。",
        "统计图表中，A组、B组、C组的频数分布不同，需要比较平均数、中位数和样本差异。",
    ]

    for context in contexts:
        spec = build_fallback_figure_spec(
            title="图示",
            figure_type="problem_diagram",
            context=context,
        )

        assert spec.layout == {}
        assert spec.elements == []
        assert not is_renderable_problem_diagram(spec)


def test_static_figure_generation_uses_llm_spec_for_program_context(monkeypatch) -> None:
    store = _FakeContentStore()
    calls = {"count": 0}

    async def fake_acompletion(*_args, **kwargs):
        if kwargs.get("response_model") is static_figures._StaticFigureSelection:
            return _figure_selection(1)
        calls["count"] += 1
        return FigureSpec(
            type="problem_diagram",
            title="变量内存图",
            summary="变量 a、b、sum 的状态关系。",
            source_refs=["int a=3, b=5, sum"],
            elements=[
                FigureElement(kind="shape", shape_type="rectangle", label="a", x=22, y=44, rx=7, ry=7),
                FigureElement(kind="shape", shape_type="rectangle", label="b", x=45, y=44, rx=7, ry=7),
                FigureElement(kind="shape", shape_type="rectangle", label="sum", x=70, y=44, rx=8, ry=7),
                FigureElement(kind="vector", label="a+b", x=51, y=62, x2=66, y2=62),
                FigureElement(kind="label", text="变量区", x=22, y=26),
            ],
        )

    monkeypatch.setattr(static_figures, "get_content_store", lambda: store)
    monkeypatch.setattr(
        static_figures,
        "resolve_course_storage_scope",
        lambda _course_id: SimpleNamespace(namespace="users/test/courses/course_abc123abc123"),
    )
    monkeypatch.setattr(static_figures, "acompletion_with_fallback", fake_acompletion)

    draft = ChapterDraft(
        chapter_index=1,
        title="C 语言变量",
        markdown=(
            "## 程序中的变量位置\n\n"
            "C 语言中 int a=3, b=5, sum; 执行 sum=a+b 后，"
            "变量区中的 a、b、sum 位置和赋值顺序需要区分。"
        ),
    )

    assets = asyncio.run(
        static_figures.generate_static_html_figure_assets(
            draft=draft,
            traced_context=TracedExecutionContext(course_id="course_abc123abc123", build_session_id="build_1"),
            digest_mode="systematic",
            markdown=draft.markdown,
            max_assets=1,
        )
    )

    assert calls["count"] == 1
    assert len(assets) == 1
    asset = assets[0]
    assert asset["figure_spec"]["layout"] == {}
    assert asset["validation_report"]["layout_quality"]["ok"] is True
    assert not any("deterministic_template" in warning for warning in asset["validation_report"].get("warnings", []))
    assert store.text_writes
    html = next(iter(store.text_writes.values()))
    assert "<svg" in html
    assert "sum" in html
    assert "变量内存格" not in html


def test_static_figure_generation_asks_llm_when_signal_is_not_keyword_matched(monkeypatch) -> None:
    store = _FakeContentStore()
    calls = {"count": 0}

    async def fake_acompletion(*_args, **kwargs):
        if kwargs.get("response_model") is static_figures._StaticFigureSelection:
            return _figure_selection(1)
        calls["count"] += 1
        return FigureSpec(
            type="problem_diagram",
            title="审题路径图",
            summary="把解题动作画成三步路径。",
            source_refs=["先标出已知条件，再写出目标，再选择方法"],
            elements=[
                FigureElement(kind="shape", shape_type="rectangle", label="读题", x=22, y=48, rx=8, ry=7),
                FigureElement(kind="shape", shape_type="rectangle", label="条件", x=48, y=48, rx=8, ry=7),
                FigureElement(kind="shape", shape_type="rectangle", label="目标", x=74, y=48, rx=8, ry=7),
                FigureElement(kind="vector", x=31, y=48, x2=39, y2=48),
                FigureElement(kind="vector", x=57, y=48, x2=65, y2=48),
            ],
        )

    monkeypatch.setattr(static_figures, "get_content_store", lambda: store)
    monkeypatch.setattr(
        static_figures,
        "resolve_course_storage_scope",
        lambda _course_id: SimpleNamespace(namespace="users/test/courses/course_abc123abc123"),
    )
    monkeypatch.setattr(static_figures, "acompletion_with_fallback", fake_acompletion)

    draft = ChapterDraft(
        chapter_index=2,
        title="审题策略",
        markdown=(
            "## 审题策略\n\n"
            "- 第一步，先用一句话复述题目要问什么，并圈出已知条件。\n"
            "- 第二步，把条件整理成可直接使用的符号、等式或限制。\n"
            "- 第三步，写出目标量和需要验证的中间量，再选择最短的解法。\n"
            "在例题中，先标出已知条件，再写出目标，再选择方法；"
            "如果中途发现条件没有用上，需要回到题干重新检查。"
        ),
    )

    assets = asyncio.run(
        static_figures.generate_static_html_figure_assets(
            draft=draft,
            traced_context=TracedExecutionContext(course_id="course_abc123abc123", build_session_id="build_2"),
            digest_mode="systematic",
            markdown=draft.markdown,
            max_assets=1,
        )
    )

    assert calls["count"] == 1
    assert len(assets) == 1
    assert assets[0]["figure_spec"]["layout"] == {}
    assert store.text_writes


def test_static_figure_generation_skips_when_llm_declines_trigger(monkeypatch) -> None:
    store = _FakeContentStore()
    calls = {"spec": 0}

    async def fake_acompletion(*_args, **kwargs):
        if kwargs.get("response_model") is static_figures._StaticFigureSelection:
            return static_figures._StaticFigureSelection(selected=[])
        calls["spec"] += 1
        return FigureSpec(
            type="problem_diagram",
            title="不应生成",
            elements=[FigureElement(kind="axis", x=12, y=72, x2=92, y2=72)],
        )

    monkeypatch.setattr(static_figures, "get_content_store", lambda: store)
    monkeypatch.setattr(
        static_figures,
        "resolve_course_storage_scope",
        lambda _course_id: SimpleNamespace(namespace="users/test/courses/course_abc123abc123"),
    )
    monkeypatch.setattr(static_figures, "acompletion_with_fallback", fake_acompletion)

    markdown = "## 普通说明\n\n这一段只是在复述学习目标和文字说明。"
    assets = asyncio.run(
        static_figures.generate_static_html_figure_assets(
            draft=ChapterDraft(chapter_index=8, title="普通说明", markdown=markdown),
            traced_context=TracedExecutionContext(course_id="course_abc123abc123", build_session_id="build_8"),
            digest_mode="systematic",
            markdown=markdown,
            max_assets=1,
        )
    )

    assert assets == []
    assert calls["spec"] == 0
    assert store.text_writes == {}


def test_static_figure_generation_skips_non_static_visual_intent(monkeypatch) -> None:
    store = _FakeContentStore()
    calls = {"spec": 0}

    async def fake_acompletion(*_args, **kwargs):
        if kwargs.get("response_model") is static_figures._StaticFigureSelection:
            return static_figures._StaticFigureSelection(
                selected=[
                    static_figures._StaticFigureSelectionItem(
                        index=1,
                        visual_kind="interactive_html",
                        figure_goal="让学生拖动参数观察状态变化。",
                        example_seed="可调参数实验",
                        reason="静态图无法体现变量连续变化。",
                    )
                ]
            )
        calls["spec"] += 1
        return FigureSpec(
            type="problem_diagram",
            title="不应生成",
            elements=[FigureElement(kind="axis", x=12, y=72, x2=92, y2=72)],
        )

    monkeypatch.setattr(static_figures, "get_content_store", lambda: store)
    monkeypatch.setattr(
        static_figures,
        "resolve_course_storage_scope",
        lambda _course_id: SimpleNamespace(namespace="users/test/courses/course_abc123abc123"),
    )
    monkeypatch.setattr(static_figures, "acompletion_with_fallback", fake_acompletion)

    markdown = "## 参数实验\n\n这段内容更适合拖动参数观察曲线连续变化。"
    assets = asyncio.run(
        static_figures.generate_static_html_figure_assets(
            draft=ChapterDraft(chapter_index=9, title="参数实验", markdown=markdown),
            traced_context=TracedExecutionContext(course_id="course_abc123abc123", build_session_id="build_9"),
            digest_mode="systematic",
            markdown=markdown,
            max_assets=1,
        )
    )

    assert assets == []
    assert calls["spec"] == 0
    assert store.text_writes == {}


def test_static_figure_generation_skips_text_only_process_step_specs(monkeypatch) -> None:
    store = _FakeContentStore()

    async def fake_acompletion(*_args, **kwargs):
        if kwargs.get("response_model") is static_figures._StaticFigureSelection:
            return _figure_selection(1)
        return FigureSpec(
            type="process_steps",
            title="审题路径",
            summary="把审题动作画成清晰路径。",
            source_refs=["读题 -> 条件 -> 目标 -> 方法"],
            elements=[
                FigureElement(kind="step", label="1", text="读题"),
                FigureElement(kind="step", label="2", text="找条件"),
                FigureElement(kind="step", label="3", text="定目标"),
                FigureElement(kind="step", label="4", text="选方法"),
            ],
        )

    monkeypatch.setattr(static_figures, "get_content_store", lambda: store)
    monkeypatch.setattr(
        static_figures,
        "resolve_course_storage_scope",
        lambda _course_id: SimpleNamespace(namespace="users/test/courses/course_abc123abc123"),
    )
    monkeypatch.setattr(static_figures, "acompletion_with_fallback", fake_acompletion)

    markdown = "## 审题路径\n\n这个流程可以看成“读题 -> 条件 -> 目标 -> 方法”的路径。"
    assets = asyncio.run(
        static_figures.generate_static_html_figure_assets(
            draft=ChapterDraft(chapter_index=6, title="审题路径", markdown=markdown),
            traced_context=TracedExecutionContext(course_id="course_abc123abc123", build_session_id="build_6"),
            digest_mode="systematic",
            markdown=markdown,
            max_assets=1,
        )
    )

    assert assets == []
    assert store.text_writes == {}


def test_static_figure_generation_skips_duplicate_visual_specs(monkeypatch) -> None:
    store = _FakeContentStore()
    calls = {"count": 0}

    async def fake_acompletion(*_args, **kwargs):
        if kwargs.get("response_model") is static_figures._StaticFigureSelection:
            return _figure_selection(1, 2)
        calls["count"] += 1
        return FigureSpec(
            type="problem_diagram",
            title="重复状态图",
            summary="同一张状态图不应重复插入。",
            source_refs=["A=1 经由 B=2 得到 C=3"],
            elements=[
                FigureElement(kind="shape", id="a", shape_type="rectangle", label="A=1"),
                FigureElement(kind="shape", id="b", shape_type="rectangle", label="B=2"),
                FigureElement(kind="shape", id="c", shape_type="rectangle", label="C=3"),
                FigureElement(kind="vector", from_id="a", to_id="b", label="+1"),
                FigureElement(kind="vector", from_id="b", to_id="c", label="+1"),
            ],
        )

    monkeypatch.setattr(static_figures, "get_content_store", lambda: store)
    monkeypatch.setattr(
        static_figures,
        "resolve_course_storage_scope",
        lambda _course_id: SimpleNamespace(namespace="users/test/courses/course_abc123abc123"),
    )
    monkeypatch.setattr(static_figures, "acompletion_with_fallback", fake_acompletion)

    markdown = (
        "## 条件推导路径\n\n"
        "第一步整理条件，第二步代入关系式，第三步化简得到结论。"
        "题目要求把 A -> B -> C 的推导路径画清楚，避免只背结果。"
        "这里补充说明：先确认已知量，再选择可代入的关系式，最后检查结论是否满足题意。"
        "如果每一步都只背答案，就看不到条件到结论之间的转换方向。"
        "课堂上还会要求学生把每个箭头旁边写出对应依据，避免跳步。\n\n"
        "## 结论检验路径\n\n"
        "第一步整理条件，第二步代入关系式，第三步化简得到结论。"
        "题目要求把 A -> B -> C 的推导路径画清楚，避免只背结果。"
        "这里补充说明：先确认已知量，再选择可代入的关系式，最后检查结论是否满足题意。"
        "如果每一步都只背答案，就看不到条件到结论之间的转换方向。"
        "课堂上还会要求学生把每个箭头旁边写出对应依据，避免跳步。"
    )
    draft = ChapterDraft(chapter_index=5, title="推导路径", markdown=markdown)

    assets = asyncio.run(
        static_figures.generate_static_html_figure_assets(
            draft=draft,
            traced_context=TracedExecutionContext(course_id="course_abc123abc123", build_session_id="build_5"),
            digest_mode="systematic",
            markdown=draft.markdown,
            max_assets=2,
        )
    )

    assert calls["count"] == 2
    assert len(assets) == 1
    assert len(store.text_writes) == 1


def test_static_figure_generation_reuses_visual_signatures_across_chapters(monkeypatch) -> None:
    store = _FakeContentStore()

    async def fake_acompletion(*_args, **kwargs):
        if kwargs.get("response_model") is static_figures._StaticFigureSelection:
            return _figure_selection(1)
        return FigureSpec(
            type="problem_diagram",
            title="通用状态图",
            summary="同构状态图只保留一次。",
            source_refs=["A=1 经由 B=2 得到 C=3"],
            elements=[
                FigureElement(kind="shape", id="a", shape_type="rectangle", label="A=1"),
                FigureElement(kind="shape", id="b", shape_type="rectangle", label="B=2"),
                FigureElement(kind="shape", id="c", shape_type="rectangle", label="C=3"),
                FigureElement(kind="vector", from_id="a", to_id="b", label="+1"),
                FigureElement(kind="vector", from_id="b", to_id="c", label="+1"),
            ],
        )

    monkeypatch.setattr(static_figures, "get_content_store", lambda: store)
    monkeypatch.setattr(
        static_figures,
        "resolve_course_storage_scope",
        lambda _course_id: SimpleNamespace(namespace="users/test/courses/course_abc123abc123"),
    )
    monkeypatch.setattr(static_figures, "acompletion_with_fallback", fake_acompletion)
    shared_signatures: set[str] = set()
    markdown = (
        "## 条件推导路径\n\n"
        "第一步整理条件，第二步代入关系式，第三步化简得到结论。"
        "题目要求把 A -> B -> C 的推导路径画清楚。"
    )

    first_assets = asyncio.run(
        static_figures.generate_static_html_figure_assets(
            draft=ChapterDraft(chapter_index=1, title="第一章", markdown=markdown),
            traced_context=TracedExecutionContext(course_id="course_abc123abc123", build_session_id="build_shared"),
            digest_mode="systematic",
            markdown=markdown,
            max_assets=1,
            used_visual_signatures=shared_signatures,
        )
    )
    second_assets = asyncio.run(
        static_figures.generate_static_html_figure_assets(
            draft=ChapterDraft(chapter_index=2, title="第二章", markdown=markdown),
            traced_context=TracedExecutionContext(course_id="course_abc123abc123", build_session_id="build_shared"),
            digest_mode="systematic",
            markdown=markdown,
            max_assets=1,
            used_visual_signatures=shared_signatures,
        )
    )

    assert len(first_assets) == 1
    assert second_assets == []
    assert len(shared_signatures) == 1
    assert len(store.text_writes) == 1


def test_static_figure_generation_skips_nonvisual_llm_spec(monkeypatch) -> None:
    store = _FakeContentStore()

    async def fake_acompletion(*_args, **kwargs):
        if kwargs.get("response_model") is static_figures._StaticFigureSelection:
            return _figure_selection(1)
        return FigureSpec(
            type="problem_diagram",
            title="空图",
            summary="只能用文字说明。",
            source_refs=["变量区中的 a、b、sum 位置和赋值顺序需要区分"],
            elements=[],
        )

    monkeypatch.setattr(static_figures, "get_content_store", lambda: store)
    monkeypatch.setattr(
        static_figures,
        "resolve_course_storage_scope",
        lambda _course_id: SimpleNamespace(namespace="users/test/courses/course_abc123abc123"),
    )
    monkeypatch.setattr(static_figures, "acompletion_with_fallback", fake_acompletion)

    draft = ChapterDraft(
        chapter_index=3,
        title="C 语言变量",
        markdown=(
            "## 程序中的变量位置\n\n"
            "C 语言中 int a=3, b=5, sum; 执行 sum=a+b 后，"
            "变量区中的 a、b、sum 位置和赋值顺序需要区分。"
        ),
    )

    assets = asyncio.run(
        static_figures.generate_static_html_figure_assets(
            draft=draft,
            traced_context=TracedExecutionContext(course_id="course_abc123abc123", build_session_id="build_3"),
            digest_mode="systematic",
            markdown=draft.markdown,
            max_assets=1,
        )
    )

    assert assets == []
    assert store.text_writes == {}


def test_static_figure_generation_does_not_fallback_after_model_error(monkeypatch) -> None:
    store = _FakeContentStore()

    async def failing_acompletion(*_args, **_kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(static_figures, "get_content_store", lambda: store)
    monkeypatch.setattr(
        static_figures,
        "resolve_course_storage_scope",
        lambda _course_id: SimpleNamespace(namespace="users/test/courses/course_abc123abc123"),
    )
    monkeypatch.setattr(static_figures, "acompletion_with_fallback", failing_acompletion)

    draft = ChapterDraft(
        chapter_index=4,
        title="C 语言变量",
        markdown=(
            "## 程序中的变量位置\n\n"
            "C 语言中 int a=3, b=5, sum; 执行 sum=a+b 后，"
            "变量区中的 a、b、sum 位置和赋值顺序需要区分。"
        ),
    )

    assets = asyncio.run(
        static_figures.generate_static_html_figure_assets(
            draft=draft,
            traced_context=TracedExecutionContext(course_id="course_abc123abc123", build_session_id="build_4"),
            digest_mode="systematic",
            markdown=draft.markdown,
            max_assets=1,
        )
    )

    assert assets == []
    assert store.text_writes == {}


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
