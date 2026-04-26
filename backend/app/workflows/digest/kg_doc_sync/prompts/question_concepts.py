"""Prompts for question-heavy fallback concept extraction."""

SYSTEM_PROMPT_CONCEPT_EXTRACT = """
你是一名知识点识别助手。请从以下题目内容中提取背后考查的核心知识点。

## 输出要求
- 每个知识点用一个简短名称表示（2-8个字）
- 标注类型：`concept`（概念）或 `method`（方法/技巧）
- 只提取学科通用知识点，不提取题目专属设定
- 最多返回 8 个知识点
""".strip()

USER_PROMPT_CONCEPT_EXTRACT = """
## 题目内容

{{ questions_text }}

请提取这些题目背后考查的核心知识点。
""".strip()

QUESTION_CONCEPT_PROMPTS = {
    "question_concepts_system": SYSTEM_PROMPT_CONCEPT_EXTRACT,
    "question_concepts_user": USER_PROMPT_CONCEPT_EXTRACT,
}

__all__ = [
    "QUESTION_CONCEPT_PROMPTS",
    "SYSTEM_PROMPT_CONCEPT_EXTRACT",
    "USER_PROMPT_CONCEPT_EXTRACT",
]
