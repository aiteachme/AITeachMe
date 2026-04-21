"""Prompts for DocGen chapter critique and bounded rewrite."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build


def build_chapter_rewrite_messages(
    *,
    title: str,
    digest_mode: str,
    required_points: list[str],
    warnings: list[str],
    markdown: str,
    dense_context: str,
) -> list[dict[str, str]]:
    system_prompt = """
你是 AITeachMe 的章节审校改写器。
你只能修复已有章节的主要质量问题，不能改变章节主题、章节顺序或 confirmed plan 语义。
你只输出改写后的 Markdown，不输出解释。
""".strip()
    prompt = f"""
请在不改变章节主题的前提下，修复下面章节的主要质量问题。

章节：{title}
模式：{digest_mode}
必须覆盖：{"、".join(required_points) or "核心概念、方法、例子、易错点"}
发现的问题：{"；".join(warnings) or "内容不够扎实"}

可用研究材料：
{dense_context}

原章节：
{markdown}

输出要求：
1. 只输出改写后的 Markdown。
2. 保留学生可读的教学语气。
3. 不要虚构真题；如果是生成例题，要称为“自测例题”。
4. systematic 要讲清定义、结构和推理；sprint 要强化题型、速判和易错点。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "chapter_rewrite",
        inputs={
            "title": title,
            "digest_mode": digest_mode,
            "required_point_count": len(required_points),
            "warning_count": len(warnings),
            "markdown_chars": len(markdown),
            "dense_context_chars": len(dense_context),
        },
        output=messages,
    )


__all__ = ["build_chapter_rewrite_messages"]
