"""Prompts for DocGen chapter critique and bounded rewrite."""

from __future__ import annotations

REWRITE_REQUIRED_POINT_BUDGET = 16
REWRITE_WARNING_BUDGET = 12
REWRITE_CONTEXT_BUDGET = 7000
REWRITE_MARKDOWN_BUDGET = 12000


def build_chapter_rewrite_messages(
    *,
    title: str,
    digest_mode: str,
    required_points: list[str],
    warnings: list[str],
    markdown: str,
    dense_context: str,
) -> list[dict[str, str]]:
    # 改写 prompt 只带审校所需摘要，完整章节和研究材料仍留在 workflow state。
    prompt = f"""
你是 AITeachMe 的章节审校改写器。请在不改变章节主题的前提下，修复下面章节的主要质量问题。

章节：{title}
模式：{digest_mode}
必须覆盖：{"、".join(required_points[:REWRITE_REQUIRED_POINT_BUDGET]) or "核心概念、方法、例子、易错点"}
发现的问题：{"；".join(warnings[:REWRITE_WARNING_BUDGET]) or "内容不够扎实"}

可用研究材料：
{dense_context[:REWRITE_CONTEXT_BUDGET]}

原章节：
{markdown[:REWRITE_MARKDOWN_BUDGET]}

输出要求：
1. 只输出改写后的 Markdown。
2. 保留学生可读的教学语气。
3. 不要虚构真题；如果是生成例题，要称为“自测例题”。
4. systematic 要讲清定义、结构和推理；sprint 要强化题型、速判和易错点。
""".strip()
    return [
        {"role": "system", "content": "你是严格的教学文档改写器，只输出 Markdown。"},
        {"role": "user", "content": prompt},
    ]


__all__ = ["build_chapter_rewrite_messages"]
