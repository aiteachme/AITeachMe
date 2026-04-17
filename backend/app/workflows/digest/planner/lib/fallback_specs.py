"""Fallback chapter angle specs for planner normalization.

These specs are only used when the model output is missing, malformed, or too
generic. Normal planner output still comes from the LLM and uploaded material.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChapterAngleSpec(BaseModel):
    label: str
    required_elements: list[str] = Field(default_factory=list)
    query_suffixes: list[str] = Field(default_factory=list)
    writing_instruction: str = ""
    objective_template: str = ""


SPRINT_ANGLE_SPECS = [
    ChapterAngleSpec(
        label="核心概念",
        required_elements=["核心概念", "高频考点", "直觉理解"],
        query_suffixes=["核心概念", "通俗理解", "考点梳理"],
        writing_instruction="优先解释最少但最关键的概念，用大白话说明它为什么重要，并点明最常见的考法。",
        objective_template="围绕“{topic}”快速抓住核心概念与考点，先建立能直接拿来应试的理解抓手。",
    ),
    ChapterAngleSpec(
        label="公式方法",
        required_elements=["核心公式", "使用条件", "方法判断"],
        query_suffixes=["公式总结", "方法技巧", "使用条件"],
        writing_instruction="突出公式、方法和使用条件，每个要点都补一条快速判断规则，避免死记硬背。",
        objective_template="围绕“{topic}”整理最常用的公式与方法，帮助学生快速判断什么时候该用什么。",
    ),
    ChapterAngleSpec(
        label="题型突破",
        required_elements=["典型题型", "步骤拆解", "变式提醒"],
        query_suffixes=["典型题型", "例题解析", "真题变式"],
        writing_instruction="按题型展开，明确题眼、解题步骤和变式方向，让学生看到题就能找到入口。",
        objective_template="围绕“{topic}”拆解高频题型与解题路径，把会做一道题扩展成会做一类题。",
    ),
    ChapterAngleSpec(
        label="易错辨析",
        required_elements=["易错点", "混淆概念", "失分原因"],
        query_suffixes=["易错点总结", "常见陷阱", "对比辨析"],
        writing_instruction="集中讲清最容易混淆和失分的地方，明确为什么会错、如何快速自查。",
        objective_template="围绕“{topic}”集中处理最容易失分的误区，避免学生在考场上踩重复的坑。",
    ),
    ChapterAngleSpec(
        label="综合迁移",
        required_elements=["综合变式", "跨题型迁移", "得分策略"],
        query_suffixes=["综合变式", "迁移应用", "得分技巧"],
        writing_instruction="强调同一知识点在不同题型中的变形方式，补充综合场景下的得分策略。",
        objective_template="围绕“{topic}”补足综合变式和迁移能力，避免学生只会单一路径的套路题。",
    ),
    ChapterAngleSpec(
        label="考前速查",
        required_elements=["速查表", "最后回看", "记忆抓手"],
        query_suffixes=["速查表", "考前回看", "记忆口诀"],
        writing_instruction="压缩表达，形成适合最后回看的速查清单，确保一分钟能复盘关键抓手。",
        objective_template="围绕“{topic}”沉淀一页可快速回看的抓手，让学生在考前能高效完成最后复盘。",
    ),
]


SYSTEMATIC_ANGLE_SPECS = [
    ChapterAngleSpec(
        label="主题导入",
        required_elements=["学习目标", "前置关系", "核心问题"],
        query_suffixes=["学习路径", "知识框架", "前置知识"],
        writing_instruction="先交代这一章解决什么问题、与整套内容如何衔接，再进入细节展开。",
        objective_template="围绕“{topic}”建立学习入口，让学生先知道为什么学、先学什么、后学什么。",
    ),
    ChapterAngleSpec(
        label="概念定义",
        required_elements=["核心定义", "关键概念", "符号说明"],
        query_suffixes=["定义", "概念梳理", "符号说明"],
        writing_instruction="从概念、定义、符号和最小例子出发，搭好本章的理解底座。",
        objective_template="围绕“{topic}”建立准确的概念与定义理解，打牢后续推理和应用的基础。",
    ),
    ChapterAngleSpec(
        label="结构公式",
        required_elements=["关键结构", "核心公式", "成立条件"],
        query_suffixes=["关键结构", "核心公式", "成立条件"],
        writing_instruction="讲清结构、公式和它们的成立边界，不要只罗列结论，要补上使用前提。",
        objective_template="围绕“{topic}”梳理关键结构与公式，帮助学生建立可推演、可调用的知识骨架。",
    ),
    ChapterAngleSpec(
        label="方法推理",
        required_elements=["推理过程", "方法步骤", "判断依据"],
        query_suffixes=["推理思路", "方法步骤", "证明思路"],
        writing_instruction="强调方法链路、推理过程和判断依据，让学生知道为什么这样做而不是只记结果。",
        objective_template="围绕“{topic}”建立从原理到方法的推理链，形成更完整的系统理解。",
    ),
    ChapterAngleSpec(
        label="例题应用",
        required_elements=["典型例题", "应用场景", "变式扩展"],
        query_suffixes=["例题解析", "应用场景", "变式拓展"],
        writing_instruction="通过例题与应用场景把抽象知识落地，突出从概念到解题的转化过程。",
        objective_template="围绕“{topic}”把知识落到典型例题和应用场景中，提升理解到运用的转化能力。",
    ),
    ChapterAngleSpec(
        label="边界辨析",
        required_elements=["易混点", "边界条件", "反例提醒"],
        query_suffixes=["易混概念", "边界条件", "反例辨析"],
        writing_instruction="专门处理容易混淆的边界和反例，避免学生形成看似顺畅但不稳的理解。",
        objective_template="围绕“{topic}”处理最容易混淆的边界条件和反例，补齐系统学习中最容易漏掉的薄弱点。",
    ),
    ChapterAngleSpec(
        label="综合迁移",
        required_elements=["综合问题", "跨主题联系", "迁移能力"],
        query_suffixes=["综合问题", "知识联系", "迁移应用"],
        writing_instruction="把多个主题串起来，说明它们如何在综合问题中协同出现并互相支撑。",
        objective_template="围绕“{topic}”搭建跨主题联系，帮助学生把局部知识组织成可迁移的整体能力。",
    ),
    ChapterAngleSpec(
        label="总结延伸",
        required_elements=["本章回顾", "复习建议", "进阶方向"],
        query_suffixes=["总结回顾", "复习建议", "进阶学习"],
        writing_instruction="收束这一章的主线，指出后续延伸方向和推荐的复习顺序。",
        objective_template="围绕“{topic}”完成回收与延伸，帮助学生把本章内容沉淀成稳定的长期结构。",
    ),
]


SPRINT_TITLE_SUFFIXES: dict[str, str] = {
    "核心概念": "核心概念与高频考点",
    "公式方法": "公式与速判技巧",
    "题型突破": "高频题型突破",
    "易错辨析": "易错点辨析",
    "综合迁移": "综合变式与迁移",
    "考前速查": "考前速查清单",
}

SYSTEMATIC_TITLE_SUFFIXES: dict[str, str] = {
    "主题导入": "学习地图与主线",
    "概念定义": "核心概念与定义",
    "结构公式": "结构框架与关键公式",
    "方法推理": "方法推理与证明思路",
    "例题应用": "典型例题与应用",
    "边界辨析": "边界条件与易混辨析",
    "综合迁移": "跨主题综合迁移",
    "总结延伸": "章节总结与延伸",
}


def angle_specs_for_mode(digest_mode: str) -> list[ChapterAngleSpec]:
    return SPRINT_ANGLE_SPECS if str(digest_mode).strip().lower() == "sprint" else SYSTEMATIC_ANGLE_SPECS


def title_suffix_for_angle(*, digest_mode: str, angle: ChapterAngleSpec) -> str:
    mapping = SPRINT_TITLE_SUFFIXES if str(digest_mode).strip().lower() == "sprint" else SYSTEMATIC_TITLE_SUFFIXES
    return mapping.get(angle.label, angle.label)


__all__ = [
    "ChapterAngleSpec",
    "angle_specs_for_mode",
    "title_suffix_for_angle",
]
