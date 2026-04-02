"""LEARNER.md — 用户学习者档案（人类可读 Markdown 文件）。

参考 OpenClaw 的 USER.md / SOUL.md 思路，为每位学习者维护一份
可读可编辑的 Markdown 档案文件。

文件位置：
- 单用户模式：``~/.atm/LEARNER.md``
- 多用户模式：``data/users/{user_id}/LEARNER.md``

对外使用::

    from app.infra.memory.learner_doc import (
        read_learner_doc,
        write_learner_doc,
        update_learner_section,
        get_learner_doc_path,
    )

    # 读取完整档案
    doc = await read_learner_doc("u1")
    print(doc)

    # 更新某个章节
    await update_learner_section("u1", "薄弱领域", "- 线性代数：特征值\\n- 概率论：贝叶斯")

    # 从 UserProfile 同步到文件
    from app.infra.memory.learner_doc import sync_profile_to_doc
    await sync_profile_to_doc("u1")
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()


# ── 默认模板 ──────────────────────────────────────────────────

_DEFAULT_TEMPLATE = """# 📚 学习者档案

> 这是你的个人学习档案，AITeachMe 会根据这里的信息为你提供个性化教学。
> 你可以随时手动编辑此文件，系统也会在学习过程中自动更新。

## 基本信息

- 身份：
- 专业/年级：
- 学习目标：

## 学习风格偏好

- 偏好的讲解方式：（如：类比解释 / 严格推导 / 图示 / 代码演示）
- 偏好的练习类型：（如：选择题 / 编程题 / 简答题）
- 学习节奏：（如：一次深入一个概念 / 快速过一遍再回顾）

## 擅长领域

（系统会根据你的学习表现自动记录）

## 薄弱领域

（系统会根据你的错题和提问自动记录）

## 学习笔记

（学习过程中的重要洞察和笔记）

## 最近学习主题

（系统自动记录你近期学习的主题）

## 教学备注

（系统对你学习模式的观察和建议）
"""


# ── 路径管理 ──────────────────────────────────────────────────


def get_learner_doc_path(user_id: str = "default") -> Path:
    """获取 LEARNER.md 文件路径。

    路径规则：
    - user_id == "default" → ``~/.atm/LEARNER.md``
    - 其他 → ``~/.atm/users/{user_id}/LEARNER.md``

    Args:
        user_id: 用户标识。

    Returns:
        LEARNER.md 文件路径。
    """
    base = Path.home() / ".atm"
    if user_id == "default":
        return base / "LEARNER.md"
    return base / "users" / user_id / "LEARNER.md"


# ── 读写 API ─────────────────────────────────────────────────


async def read_learner_doc(user_id: str = "default") -> str:
    """读取学习者档案。

    如果文件不存在，自动创建默认模板。

    Args:
        user_id: 用户标识。

    Returns:
        Markdown 文本内容。

    Example::

        doc = await read_learner_doc("u1")
        print(doc)
    """
    path = get_learner_doc_path(user_id)

    if not path.exists():
        # 首次访问，创建默认模板
        await write_learner_doc(user_id, _DEFAULT_TEMPLATE)
        logger.info("learner_doc_created", user_id=user_id, path=str(path))
        return _DEFAULT_TEMPLATE

    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("learner_doc_read_failed", path=str(path), error=str(exc))
        return _DEFAULT_TEMPLATE


async def write_learner_doc(user_id: str, content: str) -> None:
    """写入完整学习者档案。

    Args:
        user_id: 用户标识。
        content: 完整 Markdown 内容。

    Example::

        await write_learner_doc("u1", "# 学习者档案\\n\\n...")
    """
    path = get_learner_doc_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.debug("learner_doc_written", user_id=user_id, path=str(path))


async def update_learner_section(
    user_id: str,
    section_name: str,
    new_content: str,
) -> None:
    """更新档案中的某个章节内容。

    根据 ``## 章节名`` 匹配，替换该章节到下一个 ``##`` 之间的内容。

    Args:
        user_id: 用户标识。
        section_name: 章节标题（不含 ##）。
        new_content: 新的章节内容。

    Example::

        await update_learner_section("u1", "薄弱领域",
            "- 线性代数：特征值计算\\n- 概率论：贝叶斯公式")
    """
    doc = await read_learner_doc(user_id)

    pattern = rf"(## {re.escape(section_name)}\s*\n)(.*?)(?=\n## |\Z)"
    match = re.search(pattern, doc, re.DOTALL)

    if match:
        replacement = f"{match.group(1)}\n{new_content}\n"
        updated = doc[:match.start()] + replacement + doc[match.end():]
    else:
        # 章节不存在，追加
        updated = doc.rstrip() + f"\n\n## {section_name}\n\n{new_content}\n"

    await write_learner_doc(user_id, updated)
    logger.info("learner_section_updated",
                user_id=user_id, section=section_name)


async def read_learner_section(
    user_id: str,
    section_name: str,
) -> str:
    """读取档案中某个章节的内容。

    Args:
        user_id: 用户标识。
        section_name: 章节标题。

    Returns:
        章节内容（不含标题行），未找到则返回空字符串。

    Example::

        weaknesses = await read_learner_section("u1", "薄弱领域")
    """
    doc = await read_learner_doc(user_id)

    pattern = rf"## {re.escape(section_name)}\s*\n(.*?)(?=\n## |\Z)"
    match = re.search(pattern, doc, re.DOTALL)
    return match.group(1).strip() if match else ""


async def append_to_learner_section(
    user_id: str,
    section_name: str,
    line: str,
) -> None:
    """向某个章节末尾追加一行。

    Args:
        user_id: 用户标识。
        section_name: 章节标题。
        line: 要追加的行（如 ``"- 新内容"``）。

    Example::

        await append_to_learner_section("u1", "学习笔记", "- 特征值 = 矩阵拉伸的倍数")
    """
    current = await read_learner_section(user_id, section_name)
    lines = current.split("\n") if current else []

    # 去重
    if line.strip() in [l.strip() for l in lines]:
        return

    lines.append(line)
    # 过滤空行和模板占位
    lines = [l for l in lines if l.strip() and not l.strip().startswith("（")]
    await update_learner_section(user_id, section_name, "\n".join(lines))


# ── Profile 同步 ──────────────────────────────────────────────


async def sync_profile_to_doc(user_id: str = "default") -> None:
    """将内存中的 UserProfile 同步到 LEARNER.md。

    自动把 profile 的各维度更新到对应章节。

    Args:
        user_id: 用户标识。

    Example::

        await sync_profile_to_doc("u1")
    """
    from app.infra.memory import get_user_profile

    profile = await get_user_profile(user_id)

    if profile.background:
        await update_learner_section(user_id, "基本信息",
                                     f"- 背景：{profile.background}")

    if profile.learning_style or profile.preferences:
        lines = []
        if profile.learning_style:
            lines.append(f"- 偏好的讲解方式：{profile.learning_style}")
        for p in profile.preferences[:5]:
            lines.append(f"- {p}")
        await update_learner_section(user_id, "学习风格偏好", "\n".join(lines))

    if profile.strengths:
        await update_learner_section(user_id, "擅长领域",
                                     "\n".join(f"- {s}" for s in profile.strengths))

    if profile.weaknesses:
        await update_learner_section(user_id, "薄弱领域",
                                     "\n".join(f"- w" for w in profile.weaknesses))

    if profile.insights:
        await update_learner_section(user_id, "教学备注",
                                     "\n".join(f"- {i}" for i in profile.insights))

    if profile.recent_topics:
        await update_learner_section(user_id, "最近学习主题",
                                     "\n".join(f"- {t}" for t in profile.recent_topics[-10:]))

    logger.info("profile_synced_to_doc", user_id=user_id)


async def load_doc_to_context(user_id: str = "default") -> str:
    """将 LEARNER.md 内容加载为 LLM 可用的上下文文本。

    返回的内容可直接注入 system message。

    Args:
        user_id: 用户标识。

    Returns:
        格式化后的学习者信息，适合注入 LLM 上下文。

    Example::

        learner_context = await load_doc_to_context("u1")
        messages = [{"role": "system", "content": learner_context}] + messages
    """
    doc = await read_learner_doc(user_id)

    # 去掉文件头的说明注释
    lines = doc.split("\n")
    filtered = [l for l in lines if not l.strip().startswith(">")]
    return "\n".join(filtered).strip()
