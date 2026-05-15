"""Prompts for DocGen interactive HTML sidecar generation."""

from __future__ import annotations

from collections.abc import Sequence

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile


_INTERACTION_MODE_LABELS = {
    "parameter_explorer": "参数探索",
    "process_stepper": "过程分步",
    "concept_mapper": "概念关系映射",
}


def build_interactive_html_messages(
    *,
    chapter_title: str,
    chapter_objective: str,
    digest_mode: str,
    interaction_mode: str,
    design_brief: str,
    concept_targets: Sequence[str],
    formula_targets: Sequence[str],
    claim_targets: Sequence[str],
    chapter_context: str,
    retry_feedback: Sequence[str] = (),
) -> list[dict[str, str]]:
    mode_label = get_docgen_mode_profile(digest_mode).prompt_label
    interaction_label = _INTERACTION_MODE_LABELS.get(interaction_mode, interaction_mode or "未指定")
    system_prompt = """
你是 AITeachMe 的教学微实验设计器。
你的输出不是网页模板，而是一段能让学生立刻操作、观察、修正理解的单文件 HTML 微实验。
你必须只输出一个完整、自包含、可直接运行的 HTML5 文档，不输出 Markdown、解释或额外文本。

生成边界：
- 只生成单文件 HTML；CSS 和 JavaScript 全部内联。
- 禁止外部资源和联网能力：CDN、远程脚本、远程字体、远程图片、fetch、XHR、WebSocket 都不能使用。
- 禁止 import、module script、localStorage、sessionStorage、cookie。
- 必须能在 sandboxed iframe 中运行，也能在新标签页单独打开。
- 只允许一个 `<!DOCTYPE html>`、一个 `<html>`、一个 `<head>` 和一个 `<body>`。

教学质量标准：
- 先理解设计 brief 中的学习目标，再选定一个“可操作变量”或“可切换状态”，让学生通过操作看到概念变化。
- 核心可视化必须由 SVG、Canvas 或真实 DOM 状态驱动，不能只是静态说明卡片。
- 每次交互都要形成“操作 -> 视觉反馈 -> 观察提示”的闭环。
- 页面只讲一个关键点；宁可做透一个微场景，也不要把整章内容堆成资料页。
- 控件保持 1-3 个为宜，每个控件都要有中文 label、当前值反馈，并能用键盘/触摸操作。
- 必须提供重置按钮，并恢复所有变量、动画状态、选中项和结果显示。
- 移动端必须可用：320px 宽度下不能横向滚动，文本和控件不能溢出或重叠。

版式自由度：
- 不要套固定模板，不要反复生成同一种居中白卡、蓝色按钮、灰色背景的页面。
- 根据知识类型自主选择结构：坐标画布、几何纸面、实验台、步骤轨道、双栏对照、仪表盘、时间轴、关系地图或题目场景都可以。
- 控件可以嵌在图形旁、图形内、底部工具条或分步区域里；只要操作路径清楚，不强制“控制区 + 可视化区 + 提示区”三段式。
- 视觉风格服务内容：数学可以像草稿纸/坐标板，物理可以像实验装置，流程可以像状态机，概念辨析可以像对照台。
- 保持克制和可读，但允许有主题化布局、色彩、形状和空间组织上的变化。

原创设计启发（只作思路，不是模板）：
- 局部近似观察：拖动变量靠近某个关键点，直接比较曲线、误差、比值或放大视图。
- 几何条件验证：拖动点、边或角，观察条件是否保持、结论何时失效。
- 单位/尺度映射：调节数量级或单位，观察现实含义和常见误判。
- 步骤误区诊断：切换不同做法，看到中间状态、错误来源和修正路径。
- 分类边界切换：改变案例特征，观察它落入哪个类别、为什么边界会改变。
""".strip()

    retry_section = ""
    if retry_feedback:
        retry_section = "\n\n上一次生成未达标，请针对这些问题重做，不要只是微调样式：\n" + "\n".join(
            f"- {item}" for item in retry_feedback if item
        )

    prompt = f"""
请围绕下面这一章生成一个交互式教学页面。

章节标题：{chapter_title}
章节目标：{chapter_objective or "帮助学生直观理解本章材料中最需要操作验证的一点。"}
文档模式：{mode_label}
建议交互模式：{interaction_label}
概念线索：{"、".join(concept_targets) or "未提供"}
关键公式：{"、".join(formula_targets) or "未提供"}
主张线索：{"、".join(claim_targets) or "未提供"}

微实验设计 brief：
{design_brief or "未提供，请自行判断最能帮助学生理解的互动方式。"}

章节材料摘要：
{chapter_context}

生成策略：
1. 先在心里完成“学习目标 -> 学生操作 -> 可见变化 -> 观察提示”的设计闭环，但不要把设计过程输出出来。
2. 根据 brief 和材料自主选择形态：仿真、图形对比、关系图、步骤演示、场景实验、小游戏式练习或其他更合适的形式都可以。
3. 如果图形能显著降低理解难度，就使用 SVG 或 Canvas；如果 DOM 状态更清楚，也可以使用真实 DOM 可视化。
4. 避免“标题 + 公式 + 滑块 + 灰色块”的通用样子；控件变化必须改变学生正在观察的对象。
5. 不要写长篇讲义，不要做多页面，不要做聊天、登录、分享、导出或联网搜索。
6. 动画可以辅助理解，但不能替代可操作的学习反馈。
7. 请确保 HTML 输出是完整文档，以 `<!DOCTYPE html>` 开始，并以一个 `</html>` 结束。{retry_section}
""".strip()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "docgen_interactive_html",
        inputs={
            "chapter_title": chapter_title,
            "digest_mode": digest_mode,
            "interaction_mode": interaction_mode,
            "design_brief_chars": len(design_brief),
            "concept_count": len(list(concept_targets)),
            "formula_count": len(list(formula_targets)),
            "claim_count": len(list(claim_targets)),
            "context_chars": len(chapter_context),
            "retry_issue_count": len(list(retry_feedback)),
        },
        output=messages,
    )


def build_selection_interactive_html_messages(
    *,
    anchor_title: str,
    heading_path: Sequence[str],
    selected_text: str,
    user_prompt: str,
    section_excerpt: str,
    design_brief: str,
    retry_feedback: Sequence[str] = (),
) -> list[dict[str, str]]:
    heading_label = " > ".join([item for item in heading_path if item]) or anchor_title or "当前章节"
    system_prompt = """
你是 AITeachMe 的划选知识微实验设计器。
用户已经在知识文档中选中了一小段文本，你要把这段文本转化为一个能嵌入文档的互动演示。
你必须只输出一个完整、自包含、可直接运行的 HTML5 文档，不输出 Markdown、解释或额外文本。

生成边界：
- 只生成单文件 HTML；CSS 和 JavaScript 全部内联。
- 禁止外部资源和联网能力：CDN、远程脚本、远程字体、远程图片、fetch、XHR、WebSocket 都不能使用。
- 禁止 import、module script、localStorage、sessionStorage、cookie。
- 必须能在 sandboxed iframe 中运行，也能在新标签页单独打开。
- 只允许一个 `<!DOCTYPE html>`、一个 `<html>`、一个 `<head>` 和一个 `<body>`。

微实验原则：
- 只围绕划选文本做一个可操作的理解场景，不能扩写成泛泛讲义。
- 先理解设计 brief 和用户补充要求，再选择一个学生能主动改变的状态：参数、步骤、选项、案例或判断。
- 状态变化必须带来可见变化，优先使用 SVG、Canvas 或真实 DOM 可视化。
- 每个控件都要有中文 label、当前值反馈和可恢复的重置逻辑。
- 观察提示要随状态更新，指出“现在应该看什么”。
- 320px 宽度下不能横向滚动，控制区、图形和文本不能重叠。
- 不要套同一个 UI 模板；根据选中文本自由选择画布、对照、步骤、场景或仪表等形态。
- 控件和反馈的位置可自由设计，只要学生能一眼知道如何操作、看哪里、为什么变了。

原创设计启发（只作思路，不是模板）：
- 局部近似观察：拖动变量靠近某个关键点，直接比较曲线、误差、比值或放大视图。
- 几何条件验证：拖动点、边或角，观察条件是否保持、结论何时失效。
- 单位/尺度映射：调节数量级或单位，观察现实含义和常见误判。
- 步骤误区诊断：切换不同做法，看到中间状态、错误来源和修正路径。
- 分类边界切换：改变案例特征，观察它落入哪个类别、为什么边界会改变。
""".strip()

    retry_section = ""
    if retry_feedback:
        retry_section = "\n\n上一次生成未达标，请针对这些问题重做，不要只是微调样式：\n" + "\n".join(
            f"- {item}" for item in retry_feedback if item
        )

    prompt = f"""
请把用户在知识文档中划选的内容，改造成一个小型互动演示页面。

当前章节路径：{heading_label}
章节标题：{anchor_title or "未提供"}

用户划选内容：
{selected_text}

用户补充要求：
{user_prompt or "未提供，请自行选择最有教学价值的交互形式。"}

微实验设计 brief：
{design_brief or "未提供，请自行判断最能帮助学生理解的互动方式。"}

章节附近上下文：
{section_excerpt or "未提供"}

设计步骤：
1. 先在心里判断划选内容最适合哪种互动形态：变量调节、步骤回放、关系辨析、案例推演、即时判断或其他更合适的形式。
2. 只选择一个最有教学价值的交互点，避免把选中文本拆成多个松散模块。
3. 如果图形能显著降低理解难度，就使用 SVG 或 Canvas；如果 DOM 状态更清楚，也可以使用真实 DOM 可视化。
4. 使用贴合内容的界面，不要固定成一种卡片模板；不要做登录、联网、下载、分享、聊天框或多页面。
5. 输出必须是完整 HTML 文档，以 `<!DOCTYPE html>` 开始，并以一个 `</html>` 结束。{retry_section}
""".strip()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "docgen_selection_interactive_html",
        inputs={
            "anchor_title": anchor_title,
            "heading_count": len(list(heading_path)),
            "selected_chars": len(selected_text),
            "prompt_chars": len(user_prompt),
            "context_chars": len(section_excerpt),
            "design_brief_chars": len(design_brief),
            "retry_issue_count": len(list(retry_feedback)),
        },
        output=messages,
    )


__all__ = ["build_interactive_html_messages", "build_selection_interactive_html_messages"]
