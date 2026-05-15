"""Prompts for DocGen bounded chapter rewrite."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile


def build_chapter_rewrite_messages(
    *,
    title: str,
    digest_mode: str,
    required_points: list[str],
    warnings: list[str],
    markdown: str,
    dense_context: str,
) -> list[dict[str, str]]:
    mode_label = get_docgen_mode_profile(digest_mode).prompt_label
    system_prompt = """
你是 AITeachMe 的章节审校改写器。
你只能修复已有章节的主要质量问题，不能改变章节主题、章节顺序或已确认计划语义。
你只输出改写后的 Markdown，不输出解释。
标题保持语义清晰，必要时去掉旧稿里的草稿痕迹或内部流程口吻。
""".strip()
    prompt = f"""
请在不改变章节主题的前提下，修复下面章节的主要质量问题。

章节：{title}
模式：{mode_label}
必须覆盖：{"、".join(required_points) or "核心概念、方法、例子、易错点"}
发现的问题：{"；".join(warnings) or "内容不够扎实"}

可用研究材料：
{dense_context}

原章节：
{markdown}

输出要求：
1. 只输出改写后的 Markdown。
2. 保留学生可读的教学语气。
3. 不要把生成题伪装成来源真题；没有证据支撑的内容不要写成外部事实。
4. 系统学习要讲清定义、结构和推理；快速复习节奏要由模型根据本章材料判断章节角色：训练型章节多给真实任务分类、例题训练和易错点，概念型章节用短例子、反例和条件辨析增强直观性。
5. 标题必须像真实课程目录一样能单独看懂：按本章具体对象、真实任务、方法或场景命名，不要把“知识速查表”“综合训练”“快速自测”“常见任务整理”“补充讲解”这类泛标签当小节名。
6. 标题、列表和解析步骤保持标准 Markdown 结构。
7. 保留公式、命令、路径、配置项等字面内容的原始符号和语义。
8. 保留已有 `> [!TIP]`、`> [!IMPORTANT]`、`> [!WARNING]` 提示块；必要时把快速抓手、核心前提、易错提醒改成这种标准提示块，不要退化成普通引用。
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
