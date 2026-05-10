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
    concept_targets: Sequence[str],
    formula_targets: Sequence[str],
    claim_targets: Sequence[str],
    chapter_context: str,
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
- 先选定一个“可操作变量”或“可切换状态”，让学生通过操作看到概念变化。
- 核心可视化必须由 SVG、Canvas 或真实 DOM 状态驱动，不能只是静态说明卡片。
- 每次交互都要形成“操作 -> 视觉反馈 -> 观察提示”的闭环。
- 页面只讲一个关键点；宁可做透一个微场景，也不要把整章内容堆成资料页。
- 控件保持 1-3 个为宜，每个控件都要有中文 label、当前值反馈，并能用键盘/触摸操作。
- 必须提供重置按钮，并恢复所有变量、动画状态、选中项和结果显示。
- 移动端必须可用：320px 宽度下不能横向滚动，文本和控件不能溢出或重叠。

页面组成：
- 标题：直接说明这个微实验要看懂什么。
- 导语：用一两句话告诉学生怎么操作。
- 控制区：承载滑块、选择器、按钮或步骤控制。
- 可视化区：展示随操作变化的图形、关系、过程或结果。
- 观察提示：根据当前状态给出一句面向学习的反馈。
""".strip()

    prompt = f"""
请围绕下面这一章生成一个交互式教学页面。

章节标题：{chapter_title}
章节目标：{chapter_objective or "帮助学生直观理解本章核心概念。"}
文档模式：{mode_label}
建议交互模式：{interaction_label}
核心概念：{"、".join(concept_targets) or "未提供"}
关键公式：{"、".join(formula_targets) or "未提供"}
核心主张：{"、".join(claim_targets) or "未提供"}

章节材料摘要：
{chapter_context}

生成策略：
1. 先找出本章最适合“动手看见”的一个知识点，其他内容只作为必要背景。
2. 参数探索：用滑块、切换器或数字输入展示参数改变如何影响图像、关系或结果。
3. 过程分步：用步骤推进、阶段高亮和状态说明展示推导、计算或操作路径。
4. 概念关系映射：用节点、连线、分组或状态切换展示概念之间的区别与联系。
5. 如果内容涉及函数、几何、比例、流程、机制、计算结果或实验现象，优先使用 SVG / Canvas。
6. 布局采用“控制区 + 可视化区 + 观察提示”的清晰结构；窄屏自动上下排列。
7. 不要写长篇讲义，不要做多页面，不要做聊天、登录、分享、导出或联网搜索。
8. 动画可以辅助理解，但不能替代可操作的学习反馈。
9. 请确保 HTML 输出是完整文档，以 `<!DOCTYPE html>` 开始，并以一个 `</html>` 结束。
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
            "concept_count": len(list(concept_targets)),
            "formula_count": len(list(formula_targets)),
            "claim_count": len(list(claim_targets)),
            "context_chars": len(chapter_context),
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
- 必须有一个学生能主动改变的状态：参数、步骤、选项、案例或判断。
- 状态变化必须带来可见变化，优先使用 SVG、Canvas 或真实 DOM 可视化。
- 每个控件都要有中文 label、当前值反馈和可恢复的重置逻辑。
- 观察提示要随状态更新，指出“现在应该看什么”。
- 320px 宽度下不能横向滚动，控制区、图形和文本不能重叠。
""".strip()

    prompt = f"""
请把用户在知识文档中划选的内容，改造成一个小型互动演示页面。

当前章节路径：{heading_label}
章节标题：{anchor_title or "未提供"}

用户划选内容：
{selected_text}

用户补充要求：
{user_prompt or "未提供，请自行选择最有教学价值的交互形式。"}

章节附近上下文：
{section_excerpt or "未提供"}

设计步骤：
1. 先判断划选内容最适合哪种互动形态：变量调节、步骤回放、关系辨析、案例推演或即时判断。
2. 只选择一个最有教学价值的交互点，避免把选中文本拆成多个松散模块。
3. 如果内容包含数值、公式、比例、变化、函数或几何对象，优先做可调参数和图形反馈。
4. 如果内容包含流程、方法、推导或解题步骤，优先做分步推进和阶段高亮。
5. 如果内容包含概念对照、分类、结构或因果关系，优先做关系图、切换对照或点选映射。
6. 使用简洁、稳定、现代的界面；不要做登录、联网、下载、分享、聊天框或多页面。
7. 输出必须是完整 HTML 文档，以 `<!DOCTYPE html>` 开始，并以一个 `</html>` 结束。
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
        },
        output=messages,
    )


__all__ = ["build_interactive_html_messages", "build_selection_interactive_html_messages"]
