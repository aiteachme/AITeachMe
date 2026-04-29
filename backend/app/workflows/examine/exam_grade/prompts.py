"""Prompt builders for the exam grading workflow."""

from __future__ import annotations

from app.schemas.llm import ChatMessage

_LATEX_FEEDBACK_RULE = (
    "如果输出内容包含数学公式，必须使用有效 LaTeX，并用 `$...$` 或 `$$...$$` 包裹；"
    "不要输出未被 `$` 包裹的 TeX 命令，也不要使用 `\\(...\\)` 或 `\\[...\\]`。"
)


def build_objective_feedback_messages(
    *,
    course_name: str,
    question_type: str,
    stem: str,
    options: list[str] | None,
    correct_answer: str,
    reference_explanation: str,
    user_answer: str,
    is_correct: bool,
) -> list[ChatMessage]:
    option_block = "\n".join(
        f"{index + 1}. {option}"
        for index, option in enumerate(options or [])
    ).strip() or "无选项"
    verdict = "正确" if is_correct else "错误或未作答"
    user_answer_block = user_answer.strip() or "未作答"
    return [
        {
            "role": "system",
            "content": (
                "你是一名严谨且友好的阅卷老师。"
                "用户已经完成了一道客观题的作答，正确性已由程序规则判定。"
                "你的任务不是重新判对错，而是基于用户的实际作答生成一段简洁、清晰、面向学生的解析。"
                f"{_LATEX_FEEDBACK_RULE}"
                "输出必须是结构化 JSON。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"课程：{course_name}\n"
                f"题型：{question_type}\n"
                f"题目：{stem}\n"
                f"选项：\n{option_block}\n"
                f"标准答案：{correct_answer}\n"
                f"参考解析：{reference_explanation}\n"
                f"用户答案：{user_answer_block}\n"
                f"程序判定结果：{verdict}\n\n"
                "请生成：\n"
                "1. `feedback_text`：80-220字，直接解释为什么本次作答正确/错误；若未作答，要明确指出遗漏并给出关键思路。\n"
                "2. `error_cause_label`：若答错或未作答，可从 `knowledge_gap`、`careless_mistake`、`expression_issue`、`unknown` 中选一个；若答对则返回 null。\n"
                "3. 如果 `feedback_text` 含数学公式，必须使用 LaTeX，并用 `$...$` 或 `$$...$$` 包裹。\n"
                "不要输出 Markdown 代码块。"
            ),
        },
    ]


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
    return [
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


def build_study_guide_messages(
    *,
    course_name: str,
    exam_title: str,
    score_summary: str,
    wrong_question_summaries: list[dict[str, str]],
    weak_points: list[dict[str, str]],
    pending_reviews: list[dict[str, str]],
) -> list[ChatMessage]:
    return [
        {
            "role": "system",
            "content": (
                "你是一名擅长考试复盘与查漏补缺规划的学习教练。"
                "请根据本次考卷表现、薄弱知识点和待复习任务，生成一份务实、可执行的学习指南。"
                "不要空泛鼓励，要把重点放在下一步该学什么、先补哪里、怎么练。"
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
                f"当前薄弱知识点：{weak_points}\n"
                f"待复习任务：{pending_reviews}\n\n"
                "请返回：\n"
                "1. `overall_summary`：100-220字，总结本次考试暴露出的整体情况。\n"
                "2. `strengths`：2-4条，本次相对做得不错的方面。\n"
                "3. `priority_gaps`：3-5条，当前最需要查漏补缺的方向。\n"
                "4. `action_steps`：3-6条，按先后顺序给出下一步学习动作。\n"
                "5. `review_tasks`：2-5条，适合立刻执行的复习任务。\n"
                "6. `focus_units`：2-5个重点知识点对象，每个对象包含 `knowledge_unit_id`、`knowledge_unit_name`、`mastery_score`、`reason`。\n"
                "不要输出 Markdown 代码块。"
            ),
        },
    ]
