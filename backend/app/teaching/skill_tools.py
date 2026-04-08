"""教学专属轻量 Skills。"""

from __future__ import annotations

from app.shared.infra.skills.base import skill


@skill("solve_step_by_step", "对题目进行分步讲解，强调思路与关键转折。", tags=["teaching", "problem_solving"])
async def solve_step_by_step(problem: str, subject: str = "通用学科") -> str:
    cleaned_problem = " ".join(str(problem or "").split()).strip() or "题目未提供"
    cleaned_subject = " ".join(str(subject or "").split()).strip() or "通用学科"
    return (
        f"学科：{cleaned_subject}\n"
        f"题目：{cleaned_problem}\n\n"
        "分步拆解：\n"
        "1. 先判断题目在考什么概念、公式或方法。\n"
        "2. 再把已知条件和目标结论一一对齐，找出中间缺的那一步。\n"
        "3. 如果要计算，就先写思路再落公式，避免直接硬算。\n"
        "4. 最后回头检查：条件是否用全、符号是否一致、结论是否回答了题目。\n"
    )


@skill(
    "generate_similar_problems",
    "根据一道题生成相似变式题，便于巩固迁移。",
    tags=["teaching", "practice"],
)
async def generate_similar_problems(problem: str, count: int = 3) -> str:
    cleaned_problem = " ".join(str(problem or "").split()).strip() or "原题未提供"
    total = max(1, min(int(count or 3), 5))
    lines = [f"原题：{cleaned_problem}", "", "建议练这几道变式题：", ""]
    for index in range(1, total + 1):
        lines.append(f"{index}. 保持核心考点不变，但替换条件或数据，检查你是否真的理解方法。")
    lines.extend(["", "复习提醒：做完后要比较“题干变了什么、方法为什么没变或为什么需要调整”。"])
    return "\n".join(lines)


@skill("explain_formula", "用教学化语言解释公式的含义、用途和易错点。", tags=["teaching", "formula"])
async def explain_formula(formula: str, level: str = "beginner") -> str:
    cleaned_formula = " ".join(str(formula or "").split()).strip() or "公式未提供"
    cleaned_level = " ".join(str(level or "").split()).strip() or "beginner"
    return (
        f"公式：{cleaned_formula}\n"
        f"讲解层级：{cleaned_level}\n\n"
        "理解这条公式时，至少要回答三件事：\n"
        "1. 这条公式在描述什么关系。\n"
        "2. 什么时候可以直接用，前提条件是什么。\n"
        "3. 最容易错在哪里，是符号、边界条件，还是概念混淆。\n"
    )


@skill("compare_concepts", "对比两个容易混淆的概念，帮助学生建立区分。", tags=["teaching", "comparison"])
async def compare_concepts(concept_a: str, concept_b: str) -> str:
    left = " ".join(str(concept_a or "").split()).strip() or "概念 A"
    right = " ".join(str(concept_b or "").split()).strip() or "概念 B"
    return (
        f"| 维度 | {left} | {right} |\n"
        "| --- | --- | --- |\n"
        "| 核心定义 | 请补出该概念最本质的定义。 | 请补出该概念最本质的定义。 |\n"
        "| 关注重点 | 它更强调什么关系或对象？ | 它更强调什么关系或对象？ |\n"
        "| 常见混淆 | 学生最容易把它和什么弄混？ | 学生最容易把它和什么弄混？ |\n"
        "| 快速判断 | 看到什么题目特征时优先想到它？ | 看到什么题目特征时优先想到它？ |\n"
    )


__all__ = [
    "compare_concepts",
    "explain_formula",
    "generate_similar_problems",
    "solve_step_by_step",
]
