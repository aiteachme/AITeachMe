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
你是通用教学图示规划器。只输出 JSON FigureSpec，后端会把它渲染成单张 SVG。
type 固定为 problem_diagram；输出内容只包含 JSON 对象。
图必须来自章节片段，source_refs 摘录原文短语；图内只放必要短标签。
用同一套图元表达几何、坐标、受力、结构、路径、区域、网络等可视关系；不套固定学科模板。
片段不适合画图时，返回 elements: []。

可用图元：
- axis/curve/point/line/vector/shape/label/callout
- 坐标字段 x/y/x2/y2 均为 0-100
- shape_type: ellipse/circle/rectangle/triangle/polygon/angle/arc/region
- polygon/triangle/region 用 points: [[x,y],...]
- ellipse 用 rx/ry；angle/arc 用 start_angle/end_angle
""".strip()

    prompt = f"""
请为下面章节片段规划一张教学辅助图，只输出 JSON FigureSpec。

图示标题：{figure_title}
图示目标：{figure_goal or "把需要借助图形才能看清的关系画出来。"}
建议图类型：{figure_type}
文档模式：{mode_label}

章节片段：
{section_context}

生成要求：
1. 只画一个关键图，type 固定为 problem_diagram。
2. 用几何图元表达关系，图内只保留点名、轴名、变量、方向和短关系标签。
3. 标签短到能放进图里；讲解留给正文。
4. 画不出来就返回空 elements。
5. 输出为一个 JSON 对象。
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
