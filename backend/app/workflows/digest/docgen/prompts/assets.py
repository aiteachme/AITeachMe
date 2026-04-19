"""Prompt builders used by DocGen asset enrichment."""

from app.workflows.digest.docgen.prompts.common import build_docgen_mermaid_prompt


def build_docgen_image_prompt(*, topic: str, context: str = "") -> str:
    """Build a safe educational image prompt from a DocGen asset request."""

    context_hint = str(context or "").strip()
    if len(context_hint) > 1200:
        context_hint = context_hint[:1200].rstrip() + "\n...[已截断]"
    return f"""
生成一张用于中文学习讲义的教育配图。

主题：{str(topic or '').strip()}

上下文摘要：
{context_hint or '无'}

要求：
- 画面清晰、克制、适合学习资料。
- 不要生成真实人物肖像、品牌标志、考试真题截图或版权教材页面。
- 不要包含大段文字；如需文字，只使用少量中文标签。
- 优先表现概念关系、学习场景、结构示意或例题情境。
""".strip()


__all__ = ["build_docgen_image_prompt", "build_docgen_mermaid_prompt"]
