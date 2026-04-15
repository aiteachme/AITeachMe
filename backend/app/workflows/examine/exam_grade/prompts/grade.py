"""Exam-grade prompt templates."""

SYSTEM_PROMPT_SHORT_ANSWER_GRADE = """
Judge whether the user answer should receive full credit.
Return only `1` or `0`.

Rules:
- `1` means the answer is substantially correct.
- `0` means the answer misses a key idea, contains a wrong claim, or is too incomplete.
- Be strict but fair.
- Use the knowledge context if it is helpful.

Question:
{{ stem }}

Reference answer:
{{ answer }}

User answer:
{{ user_answer }}

Knowledge context:
{{ knowledge_context }}
""".strip()

SYSTEM_PROMPT_ERROR_CAUSE_LABEL = """
Pick the single best error cause label for the wrong answer.
Return only one of these labels:
concept_confusion
calculation_error
prerequisite_gap
careless_mistake
incomplete_understanding
method_misapplication
unknown

Question:
{{ stem }}

Reference answer:
{{ answer }}

User answer:
{{ user_answer }}

Knowledge context:
{{ knowledge_context }}
""".strip()

SYSTEM_PROMPT_MISTAKE_ANALYSIS = """
Write a concise mistake analysis in under 120 Chinese characters.
Focus on why the answer is wrong and what to review next.

Question:
{{ stem }}

Reference answer:
{{ answer }}

User answer:
{{ user_answer }}

Knowledge point:
{{ knowledge_point }}
""".strip()

PROMPTS: dict[str, str] = {
    "short_answer_grade": SYSTEM_PROMPT_SHORT_ANSWER_GRADE,
    "error_cause_label": SYSTEM_PROMPT_ERROR_CAUSE_LABEL,
    "mistake_analysis": SYSTEM_PROMPT_MISTAKE_ANALYSIS,
}

__all__ = [
    "PROMPTS",
    "SYSTEM_PROMPT_ERROR_CAUSE_LABEL",
    "SYSTEM_PROMPT_MISTAKE_ANALYSIS",
    "SYSTEM_PROMPT_SHORT_ANSWER_GRADE",
]
