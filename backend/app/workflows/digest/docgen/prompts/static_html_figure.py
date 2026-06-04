"""Prompts for DocGen static HTML figure generation."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.lib.mode_profiles import get_docgen_mode_profile


def build_static_html_figure_messages(
    *,
    figure_title: str,
    figure_goal: str,
    digest_mode: str,
    section_context: str,
) -> list[dict[str, str]]:
    mode_label = get_docgen_mode_profile(digest_mode).prompt_label
    system_prompt = """
你是 AITeachMe 的静态教学图示设计器。
你要生成一个用于嵌入知识文档的单文件 HTML 图示，它的作用类似教材插图或题目附图，不是交互网页。
你必须只输出一个完整、自包含、可直接运行的 HTML5 文档，不输出 Markdown、解释或额外文本。

硬性边界：
- 只生成单文件 HTML；CSS 全部内联。
- 图形优先使用内联 SVG；必要时可用纯 HTML/CSS 布局。
- 禁止 JavaScript、表单控件、按钮、滑块、动画、计时器和任何用户交互。
- 禁止外部资源和联网能力：CDN、远程脚本、远程字体、远程图片、fetch、XHR、WebSocket 都不能使用。
- 禁止 import、module script、localStorage、sessionStorage、cookie。
- 必须能在 sandboxed iframe 中静态展示，也能在新标签页单独打开。
- 只允许一个 `<!DOCTYPE html>`、一个 `<html>`、一个 `<head>` 和一个 `<body>`。

教学质量标准：
- 只画一个关键图，不做资料页，不堆多个无关图。
- 图中必须有清晰中文标签、关键点/边/轴/量的标注，学生不看正文也能知道图在表达什么。
- 如果是函数图，要有坐标轴、刻度或关键点；如果是几何图，要有边角关系或辅助线；如果是波形/统计/单位图，要突出比较对象。
- 使用克制、清晰的视觉层级：线条、填充、标签、注释各司其职。
- 移动端 320px 宽度下不能横向滚动，文字不能溢出或重叠。

图形自由度：
- 不要套固定模板，不要总是生成居中白卡、蓝色标题、灰色背景的图。
- 根据内容自主选择图形语言：坐标纸、几何作图纸、测量尺、波形面板、题目草图、单位换算条、统计小图或概念剖面都可以。
- HTML 外壳只负责承载图，不要让装饰喧宾夺主；图形本身应该是第一视觉焦点。
- 可以使用不同构图、标注方式、配色和留白，只要图示清楚、稳定、像教材里的附图。
""".strip()

    prompt = f"""
请为下面章节片段生成一张静态 HTML 教学图示。

图示标题：{figure_title}
图示目标：{figure_goal or "把需要借助图形才能看清的关系画出来。"}
文档模式：{mode_label}

章节片段：
{section_context}

生成策略：
1. 先判断这段内容最需要哪一种图：函数/坐标、几何结构、数轴/单位换算、波形、流程中的静态状态图、统计分布或题目示意。
2. 只选择一种最贴合片段的图，不要把整段内容做成海报。
3. 使用内联 SVG 画出主体图形；标签用中文短语，避免大段说明，构图和风格要随题目变化。
4. 图下可放一行简短图注，说明图形如何服务本段知识点或题目条件。
5. 不要生成交互控件，不要写脚本，不要加动画。
6. 请确保 HTML 输出是完整文档，以 `<!DOCTYPE html>` 开始，并以一个 `</html>` 结束。
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
