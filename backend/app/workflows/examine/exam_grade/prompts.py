"""Prompt builders for the exam grading workflow."""

from __future__ import annotations

from typing import Any

from app.schemas.llm import ChatMessage
from app.workflows.common.prompt_tracing import trace_prompt_build

_LATEX_FEEDBACK_RULE = (
    "如果输出内容包含数学公式，必须使用有效 LaTeX，并用 `$...$` 或 `$$...$$` 包裹；"
    "不要输出未被 `$` 包裹的 TeX 命令，也不要使用 `\\(...\\)` 或 `\\[...\\]`。"
)


def build_subjective_grade_messages(
    *,
    course_name: str,
    question_type: str,
    stem: str,
    correct_answer: str,
    reference_explanation: str,
    user_answer: str,
) -> list[ChatMessage]:
    user_answer_block = user_answer.strip() or "未作答"
    messages: list[ChatMessage] = [
        {
            "role": "system",
            "content": (
                "你是一名擅长数学与理科问答判分的阅卷老师。"
                "请特别注意：在线作答时，数学公式、步骤和等价表达可能写法不同，"
                "不能只做字符串匹配。你需要根据语义、公式等价性、关键结论和推理是否成立来判断。"
                f"{_LATEX_FEEDBACK_RULE}"
                "若用户答案为空，则应判错。输出必须是结构化 JSON。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"课程：{course_name}\n"
                f"题型：{question_type}\n"
                f"题目：{stem}\n"
                f"参考答案：{correct_answer}\n"
                f"参考解析：{reference_explanation}\n"
                f"用户答案：{user_answer_block}\n\n"
                "请返回：\n"
                "1. `is_correct`：用户答案是否应判为正确。\n"
                "2. `score_obtained`：0 到 1 的分值；完全正确给 1，明显错误给 0，若基本正确但表达略有缺失可给 0.5-0.9。\n"
                "3. `feedback_text`：80-260字，面向学生解释本次判分原因，并指出关键思路或缺漏。\n"
                "4. `error_cause_label`：若未完全正确，可从 `knowledge_gap`、`careless_mistake`、`expression_issue`、`unknown` 中选一个；若完全正确则返回 null。\n"
                "5. 如果 `feedback_text` 含数学公式，必须使用 LaTeX，并用 `$...$` 或 `$$...$$` 包裹。\n"
                "不要输出 Markdown 代码块。"
            ),
        },
    ]
    return trace_prompt_build(
        "examine_subjective_grade",
        inputs={
            "question_type": question_type,
            "stem_chars": len(stem),
            "correct_answer_chars": len(correct_answer),
            "reference_explanation_chars": len(reference_explanation),
            "user_answer_chars": len(user_answer),
        },
        output=messages,
    )


def build_study_guide_messages(
    *,
    course_name: str,
    exam_title: str,
    score_summary: str,
    wrong_question_summaries: list[dict[str, str]],
    knowledge_unit_performance: list[dict[str, Any]],
    pending_reviews: list[dict[str, str]],
) -> list[ChatMessage]:
    messages: list[ChatMessage] = [
        {
            "role": "system",
            "content": (
                "你是一名擅长考试复盘与查漏补缺规划的学习教练。"
                "请根据本次考卷表现、本卷知识点统计、累计画像上下文和待复习任务，生成一份务实、可执行的学习指南。"
                "不要空泛鼓励，不要把同一结论换一种说法重复到多个部分。"
                "要把重点放在下一步该学什么、先补哪里、怎么练，并且所有判断都必须能由输入信息支持。"
                "不得向学生展示 repeated_wrong、newly_learned、forgetting_due、prereq_gap 等内部状态码或字段名。"
                f"{_LATEX_FEEDBACK_RULE}"
                "输出必须是结构化 JSON。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"课程：{course_name}\n"
                f"考卷标题：{exam_title}\n"
                f"本次成绩概览：{score_summary}\n"
                f"错题/未作答摘要：{wrong_question_summaries}\n"
                f"本卷知识点表现（含仅供个性化判断的累计画像上下文）：{knowledge_unit_performance}\n"
                f"待复习任务（请整合进 action_steps）：{pending_reviews}\n\n"
                "本卷知识点表现是本指南的主要证据。累计画像只用于判断问题是偶发还是持续、调整建议优先级；"
                "不要直接复述累计掌握度百分比、累计次数或输入字段名。\n"
                "请严格按以下字段顺序返回，确保流式内容能从上到下依次出现：\n"
                "1. `overall_summary`：70-140字。先给出整体判断，再指出首要复习方向；不要重复得分和正确率。\n"
                "2. `strengths`：0-2条。只写有正确作答或稳定表现支撑的具体优势；证据不足时返回空数组，不要勉强表扬。\n"
                "3. `focus_units`：0-3个重点知识点对象，每个对象包含 `knowledge_unit_id`、`knowledge_unit_name` 与 `reason`。"
                "只使用输入中的真实知识点和编号；`reason`只概括本卷关联题目的作答、得分与暴露的问题。"
                "知识点指标最终由后端按本卷数据校准；没有可靠知识点时返回空数组，不要编造编号。\n"
                "4. `priority_gaps`：0-3条。描述错题暴露出的概念、方法或审题缺口，每条说明表现证据与纠正要点；"
                "没有可靠缺口时返回空数组，"
                "不要只是重复 `focus_units` 的知识点名称。\n"
                "5. `action_steps`：2-3条。只保留最高优先级的学习动作，按先后顺序给出动作与可核验的完成标准；"
                "把待复习任务融入这些步骤，不要罗列多个专项清单，也不要重复前文分析；"
                "不要另行输出 `review_tasks`。\n"
                "各部分内容必须互补、简洁、可执行；不要输出 Markdown 代码块。"
            ),
        },
    ]
    return trace_prompt_build(
        "examine_study_guide",
        inputs={
            "wrong_question_count": len(wrong_question_summaries),
            "knowledge_unit_count": len(knowledge_unit_performance),
            "pending_review_count": len(pending_reviews),
            "score_summary_chars": len(score_summary),
        },
        output=messages,
    )
