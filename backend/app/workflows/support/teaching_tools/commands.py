"""Teaching-focused callable tools."""

from __future__ import annotations

from app.shared.infra.tools.teaching_registry import teaching_function


@teaching_function(
    "solve_step_by_step",
    "按教学化步骤拆解一道题，输出思路、关键判断与自检提醒。",
    category="method",
    tags=["problem_solving"],
)
async def solve_step_by_step(problem: str, subject: str = "通用学科") -> str:
    cleaned_problem = " ".join(str(problem or "").split()).strip() or "请补充题目内容"
    cleaned_subject = " ".join(str(subject or "").split()).strip() or "通用学科"
    return (
        f"学科：{cleaned_subject}\n"
        f"题目：{cleaned_problem}\n\n"
        "建议拆解路径：\n"
        "1. 先读题并圈出已知条件、目标量和约束条件。\n"
        "2. 判断这道题对应的核心概念、公式或方法，不要一上来就机械套模板。\n"
        "3. 按“为什么这样做 -> 具体怎么做 -> 做完如何检查”的顺序推进解题。\n"
        "4. 最后回看最容易出错的地方，确认单位、符号、边界条件和结论是否一致。\n"
    )


@teaching_function(
    "generate_similar_problems",
    "围绕一道题生成若干变式练习，突出同类方法的迁移训练。",
    category="practice",
    tags=["practice"],
)
async def generate_similar_problems(problem: str, count: int = 3) -> str:
    cleaned_problem = " ".join(str(problem or "").split()).strip() or "请补充原题"
    total = max(1, min(int(count or 3), 5))
    lines = [f"原题：{cleaned_problem}", "", "建议生成这些同类练习：", ""]
    for index in range(1, total + 1):
        lines.append(f"{index}. 保持核心方法不变，但替换条件、数字或问法，观察解题入口是否仍然成立。")
    lines.extend(["", "使用建议：先独立完成，再回头比较每道变式的相同点、不同点和易错点。"])
    return "\n".join(lines)


@teaching_function(
    "explain_formula",
    "解释公式的含义、适用条件、使用场景与常见误区。",
    category="explain",
    tags=["formula"],
)
async def explain_formula(formula: str, level: str = "beginner") -> str:
    cleaned_formula = " ".join(str(formula or "").split()).strip() or "请补充公式"
    cleaned_level = " ".join(str(level or "").split()).strip() or "beginner"
    return (
        f"公式：{cleaned_formula}\n"
        f"讲解层级：{cleaned_level}\n\n"
        "建议从这三个角度解释：\n"
        "1. 这个公式在描述什么对象、关系或变化过程。\n"
        "2. 什么时候可以直接用，使用前需要先检查哪些条件。\n"
        "3. 学生最容易误用在哪里，以及如何用一个例子把它讲清楚。\n"
    )


@teaching_function(
    "compare_concepts",
    "对比两个概念的定义、关注重点、典型场景与常见混淆点。",
    category="explain",
    tags=["comparison"],
)
async def compare_concepts(concept_a: str, concept_b: str) -> str:
    left = " ".join(str(concept_a or "").split()).strip() or "概念 A"
    right = " ".join(str(concept_b or "").split()).strip() or "概念 B"
    return (
        f"| 维度 | {left} | {right} |\n"
        "| --- | --- | --- |\n"
        "| 核心定义 | 先说明这个概念本质上在刻画什么 | 先说明这个概念本质上在刻画什么 |\n"
        "| 关注重点 | 它最强调的对象、条件或关系是什么 | 它最强调的对象、条件或关系是什么 |\n"
        "| 典型场景 | 一般会在什么题型或知识场景中出现 | 一般会在什么题型或知识场景中出现 |\n"
        "| 常见混淆 | 最容易和哪个相近概念混在一起 | 最容易和哪个相近概念混在一起 |\n"
    )


__all__ = [
    "compare_concepts",
    "explain_formula",
    "generate_similar_problems",
    "solve_step_by_step",
]
