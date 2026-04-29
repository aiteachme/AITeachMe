"""Prompt templates for the profile pipeline."""

SYSTEM_PROMPT_REPORT_SUGGESTIONS = """
请根据下面的学习情况，给出 3 到 5 条简洁、可执行的复习建议。
要求：
1. 每条建议一行
2. 不要编号
3. 不要空话，要能直接执行

课程：
{{ course_name }}

整体掌握度：
{{ overall_mastery }}

薄弱知识点：
{{ weak_points }}
""".strip()


PROMPTS: dict[str, str] = {
    "report_suggestions": SYSTEM_PROMPT_REPORT_SUGGESTIONS,
}
