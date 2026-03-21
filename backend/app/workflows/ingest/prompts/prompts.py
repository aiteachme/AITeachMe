"""Prompt templates used by ingest workflows."""

SYSTEM_PROMPT_IMAGE_PARSE = """
请把这张图片转换成结构清晰的 Markdown。
要求：
1. 如果有文字，请尽量完整提取。
2. 如果有图表，请描述图表结构、关键字段和结论。
3. 尽量保留标题、列表、表格等层级。
4. 不要输出无关寒暄。
""".strip()


PROMPTS: dict[str, str] = {
    "image_parse": SYSTEM_PROMPT_IMAGE_PARSE,
}
