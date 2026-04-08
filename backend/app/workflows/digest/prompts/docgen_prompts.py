"""DocGen 主链路使用的中文提示词。"""

from __future__ import annotations


def _normalize_mode(digest_mode: str) -> str:
    return (digest_mode or "systematic").strip().lower()


def _tone_hint(tone: str) -> str:
    normalized_tone = (tone or "encouraging").strip().lower()
    if normalized_tone == "casual":
        return "表达可以更口语化，但仍要清楚、可信、适合学习。"
    if normalized_tone == "professional":
        return "表达要严谨专业，像高质量中文讲义。"
    if normalized_tone == "concise":
        return "表达要紧凑，尽量压缩废话，但不能省掉关键解释。"
    return "表达要温和、鼓励式、陪伴式，帮助学生建立理解信心。"


def _build_mode_contract(*, title: str, digest_mode: str) -> str:
    normalized_mode = _normalize_mode(digest_mode)
    if normalized_mode == "sprint":
        chapter_specific = ""
        if title == "概念破冰":
            chapter_specific = "本章必须先用生活化例子或考场场景破题，再建立概念直觉。"
        elif title == "公式武器库":
            chapter_specific = "本章必须整理公式、适用条件和大白话翻译，避免只堆公式。"
        elif title == "真题实战":
            chapter_specific = "本章必须至少包含 2 个步骤化例题，并突出变式提醒。"
        elif title == "防坑指南":
            chapter_specific = "本章必须总结常见错误、混淆点和考前检查清单。"
        return (
            "文档模式契约：这是冲刺型知识文档。"
            "必须写得抓重点、抓题型、抓易错点。"
            "必须显式出现这些二级标题：`## 本章导读`、`## 核心抓手`、`## 题型拆解`、"
            "`## 本章速记卡`、`## 易错提醒`、`## 快速回顾`。"
            "结尾不能空泛，必须便于考前快速复盘。"
            f"{chapter_specific}"
        )
    extra = ""
    if title == "全景导论":
        extra = "本章必须给出整体知识脉络，并插入 `<!-- [MERMAID: ...] -->` 占位符。"
    elif title == "总结与延展":
        extra = "本章必须回收全文主线，并给出进一步深入学习的建议。"
    return (
        "文档模式契约：这是系统型知识文档。"
        "必须重视定义、定理、推导、应用与章节之间的结构关系。"
        "必须显式出现这些二级标题：`## 本章导读`、`## 前置知识`、`## 动机引入`、"
        "`## 核心定义与定理`、`## 推理与应用`、`## 本章要点`。"
        "如果涉及公式或定理，不能只写结论，必须解释适用前提、推理过程和常见边界。"
        f"{extra}"
    )


def build_docgen_writer_messages(
    *,
    title: str,
    objective: str,
    tone: str,
    digest_mode: str,
    required_elements: list[str],
    writing_instructions: str,
    source_count: int,
    dense_context: str,
) -> list[dict[str, str]]:
    normalized_mode = _normalize_mode(digest_mode)
    required_text = "、".join(required_elements) if required_elements else "核心概念、推理过程、典型例子"
    tone_hint = _tone_hint(tone)
    system_prompt = (
        "你是 AITeachMe 的中文教学文档作者。"
        "你的任务是把研究材料写成可直接给学生阅读的高质量 Markdown 讲义。"
        "禁止输出英文标题、禁止输出英文段落、禁止把材料机械拼接。"
        "遇到公式要解释公式在说什么、什么时候能用、最容易错在哪里。"
        "如果材料不足，要坦诚用现有材料做稳健整理，不能编造事实或来源。"
    )
    user_prompt = f"""
请只输出本章的中文 Markdown 正文，不要输出解释，不要输出代码块外的多余说明。

章节标题：{title}
学习目标：{objective or "把本章最核心的知识主线讲清楚。"}
文档模式：{normalized_mode}
表达风格：{tone}
必须覆盖：{required_text}
可用来源数量：{source_count}
额外写作要求：{writing_instructions or "保持教学导向，强调理解路径与复习价值。"}

模式契约：
{_build_mode_contract(title=title, digest_mode=normalized_mode)}

风格提醒：
{tone_hint}

输出硬约束：
1. 只输出中文 Markdown。
2. 一级标题必须是 `# {title}`。
3. 二级标题必须服从模式契约，不能缺关键模块。
4. 如果需要图示，请使用 `<!-- [MERMAID: 描述] -->` 或 `<!-- [IMAGE: 描述] -->` 占位。
5. 如果需要公式，必须使用 `$...$` 或 `$$...$$`。
6. 不允许编造引用、文献、实验结果或材料中不存在的事实。
7. 不要把研究材料原样贴出来，要改写成适合学生学习的讲义。

研究材料：
{dense_context[:14000]}
""".strip()
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def build_docgen_research_purify_messages(
    *,
    dense_context: str,
    chapter_title: str,
    objective: str,
    required_elements: list[str],
    digest_mode: str,
) -> list[dict[str, str]]:
    must_cover = "、".join(required_elements) if required_elements else "与本章最相关的核心知识"
    normalized_mode = _normalize_mode(digest_mode)
    user_prompt = f"""
请把下面的研究素材提纯成“供章节写作直接使用”的中文研究笔记。

章节标题：{chapter_title or "未命名章节"}
章节目标：{objective or "为本章提供可教学、可解释、可举例的可靠材料。"}
文档模式：{normalized_mode}
必须覆盖：{must_cover}

输出要求：
1. 只保留和本章直接相关的信息。
2. 优先保留定义、公式、推理线索、典型例子、来源线索。
3. 删除空话、重复段落和无关背景。
4. 输出应是中文 Markdown 研究笔记，不是最终成稿。
5. 不能补充素材中没有出现的事实。
6. 如果是 `sprint`，优先保留高频考点、题型线索和易错点。
7. 如果是 `systematic`，优先保留定义、推导、适用条件和结构关系。

原始素材：
{dense_context[:12000]}
""".strip()
    return [
        {
            "role": "system",
            "content": "你是 AITeachMe 的研究整理助手，负责把杂乱素材提纯成适合教学写作的中文研究笔记。",
        },
        {"role": "user", "content": user_prompt},
    ]


def build_docgen_mermaid_prompt(*, topic: str, context: str) -> str:
    return f"""
请根据下面内容生成 Mermaid mindmap 语法。

要求：
1. 只返回 Mermaid 代码，不要解释，不要加 Markdown 代码块。
2. 根节点必须是主题本身。
3. 最多 3 层结构，保证清晰，不要过密。
4. 节点文字优先用中文，体现概念关系、步骤关系或结构关系。

主题：{topic}
上下文：{context[:3000]}
""".strip()


__all__ = [
    "build_docgen_mermaid_prompt",
    "build_docgen_research_purify_messages",
    "build_docgen_writer_messages",
]
