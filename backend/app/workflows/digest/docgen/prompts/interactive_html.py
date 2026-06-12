"""Prompts for DocGen interactive HTML sidecar generation."""

from __future__ import annotations

from collections.abc import Sequence

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.lib.mode_profiles import get_docgen_mode_profile


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
输出一个完整、自包含、可直接运行的 HTML5 微实验；只输出 HTML。
边界：单文件，CSS/JS 内联；无外部资源、联网、存储、import；可在 sandbox iframe 和新标签页运行。
质量：围绕一个关键点设计可操作变量或状态；SVG、Canvas 或真实 DOM 产生可见变化；形成“操作 -> 视觉反馈 -> 观察提示”闭环。
控件 1-3 个，带中文 label、当前值和重置；移动端 320px 不溢出、不重叠。
界面形态贴合知识内容，可用坐标画布、实验台、步骤轨道、双栏对照、仪表盘、时间轴、关系地图或题目场景。
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
1. 先确定“学习目标 -> 学生操作 -> 可见变化 -> 观察提示”的闭环，设计过程不输出。
2. 自主选择仿真、图形对比、关系图、步骤演示、场景实验或小游戏式练习。
3. 控件变化必须改变学生正在观察的对象；动画只作辅助。
4. 输出完整 HTML 文档，以 `<!DOCTYPE html>` 开始，并以一个 `</html>` 结束。{retry_section}
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
把划选文本转化为一个可嵌入文档的单文件 HTML 微实验；只输出完整 HTML。
边界：CSS/JS 内联；无外部资源、联网、存储、import；可在 sandbox iframe 和新标签页运行。
质量：围绕划选文本设计一个可操作状态，状态变化带来可见变化和观察提示。
优先使用 SVG、Canvas 或真实 DOM 可视化；控件有中文 label、当前值、重置逻辑。
320px 宽度下不横向滚动，控制区、图形和文本不重叠；界面形态跟内容匹配。
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
1. 选择一个最有教学价值的交互点：变量调节、步骤回放、关系辨析、案例推演或即时判断。
2. 使用贴合内容的界面和可视反馈。
3. 输出完整 HTML 文档，以 `<!DOCTYPE html>` 开始，并以一个 `</html>` 结束。{retry_section}
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
