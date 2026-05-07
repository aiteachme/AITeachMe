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
你是 AITeachMe 的交互式教学页面生成器。
你必须只输出一个完整、自包含、可直接运行的 HTML5 文档，不输出 Markdown、解释或额外文本。

硬约束：
- 只生成单文件 HTML，所有 CSS 和 JavaScript 内联。
- 不使用任何外部 CDN、远程脚本、远程字体、远程图片、fetch、XHR、WebSocket。
- 不使用 import、module script、localStorage、sessionStorage、cookie。
- 必须适合放在 sandboxed iframe 中运行，也必须能单独在新标签页打开。
- 必须是中文界面。
- 页面目标是帮助学生“看懂一个核心概念或过程”，不是做复杂网站。
- 控件数量保持克制，通常 1-3 个交互控件即可。
- 页面必须包含：
  1. 一个清晰标题
  2. 一段简短使用说明
  3. 一个核心交互区
  4. 一个“重置”按钮
  5. 一个简短总结/观察提示
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

要求：
1. 只聚焦一个最适合做交互展示的点，不要把整章所有内容都塞进页面。
2. 如果建议交互模式是“参数探索”，优先做滑块/切换器，让学生看到参数变化如何影响图像、关系或结果。
3. 如果建议交互模式是“过程分步”，优先做步骤展开、分阶段高亮、条件切换。
4. 如果建议交互模式是“概念关系映射”，优先做结构关系、状态切换、概念对照。
5. 如果内容涉及可视化对象、参数变化、空间关系、流程状态、计算结果或实验现象，优先用 SVG / Canvas 做直观可视化。
6. 不要写超长说明，不要做多页面，不要做聊天框，不要做登录、分享、导出、联网搜索。
7. 交互和讲解要服务学习，不要只做炫技动画。
8. 请确保 HTML 输出是完整文档，以 `<!DOCTYPE html>` 开始。
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


__all__ = ["build_interactive_html_messages"]
