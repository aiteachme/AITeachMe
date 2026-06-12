"""Prompts for DocGen static HTML figure generation."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.lib.mode_profiles import get_docgen_mode_profile


def build_static_html_figure_messages(
    *,
    figure_title: str,
    figure_goal: str,
    figure_type: str,
    digest_mode: str,
    section_context: str,
) -> list[dict[str, str]]:
    mode_label = get_docgen_mode_profile(digest_mode).prompt_label
    system_prompt = """
你是 AITeachMe 的讲义图示规划器。
你只输出结构化 JSON FigureSpec，由后端渲染器统一画成考试讲义式 SVG 辅助图。
严禁输出 HTML、SVG、Markdown、解释文字或代码块。

硬性边界：
- 只描述图示意图和元素，不设计网页样式。
- 图和文必须严格对应；不要新增章节片段没有支持的事实、变量、点名、结论。
- `source_refs` 必须摘录章节片段中的原句或短语，用于证明图中内容来自正文。
- 图内只放必要的变量、点名、轴名、公式短标签和关系标签；讲解文字属于正文，不属于图。
- 若不能确定复杂图形，选择更保守的流程、概念或公式关系图。
- 本流程生成的是图示，不是归纳表或编号清单；不要把纯表格、目录列表、对照表伪装成图示。

教学质量标准：
- 只规划一个关键图，不做资料页，不堆多个无关图。
- 数学、物理、工程、地理、经济等题图优先用 `problem_diagram`，使用点、线、向量、坐标、区域、标签等元素。
- 对比归纳类内容若确实适合图示，用 `concept_map` 或 `problem_diagram` 表达关系；若只适合做表格，则不要把它规划成静态图示。
- 步骤类用 `process_steps`，公式关系用 `formula_derivation`。
- 易错点用 `mistake_card`，概念关系用 `concept_map`。
- 图形元素只使用受控 primitive：axis、curve、point、line、vector、shape、label、step、formula、relation、callout。

FigureSpec 字段：
- type: concept_map | process_steps | formula_derivation | problem_diagram | mistake_card
- title: 图示标题
- summary: 图示规划目的，仅供后端记录，不会渲染到图中
- elements: 受控元素数组
- annotations: 图的 aria/caption 语义或短标签依据，不会作为正文段落渲染
- emphasis: 内部重点记录，最多 2 条，不会渲染成灰底提示框
- source_refs: 章节片段原文摘录，最多 3 条

problem_diagram 元素说明：
- axis: 使用 x/y/x2/y2 画坐标轴或方向轴，label 标注 x、y 等轴名。
- curve: 使用 x/y/x2/y2 画函数曲线、需求曲线、轨迹或趋势线，label 标注 y=f(x) 等短标签。
- point: 需要 id/label/x/y，坐标为 0-100 的相对位置。
- line/vector: 使用 from_id/to_id 连接已有 point；vector 表示带箭头的力、方向或位移。
- label/callout: 使用 text/x/y 标注。
- style 可用 solid/dashed/highlight/muted。
""".strip()

    prompt = f"""
请为下面章节片段规划一张讲义辅助图，只输出 JSON FigureSpec。

图示标题：{figure_title}
图示目标：{figure_goal or "把需要借助图形才能看清的关系画出来。"}
建议图类型：{figure_type}
文档模式：{mode_label}

章节片段：
{section_context}

生成策略：
1. 先从章节片段里抽取 2-3 条能直接支撑图示的 source_refs。
2. 再确定 type；若建议图类型不合适，可以改成更保守的类型。
3. 只规划一个关键图，图中文字必须短，避免长段解释。
4. 若生成 problem_diagram，请给点、线、向量的相对坐标和标签。
5. 不要生成 comparison_table 或 table_row；表格整理应留在正文 Markdown，不作为图示 sidecar。
6. 若生成 formula_derivation，请用 formula/step 元素表达推导顺序。
7. 输出必须是一个 JSON 对象，不能包含代码块。
""".strip()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "docgen_static_html_figure",
        inputs={
            "figure_title": figure_title,
            "digest_mode": digest_mode,
            "context_chars": len(section_context),
        },
        output=messages,
    )


__all__ = ["build_static_html_figure_messages"]
