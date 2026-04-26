"""Built-in question type seed data."""

from __future__ import annotations


BUILTIN_QUESTION_TYPE_ROWS = (
    {
        "type_key": "single_choice",
        "display_name": "单选题",
        "description": "从多个选项中选择一个正确答案。",
        "answer_format": "correct_answer must exactly equal one option.",
        "grading_method": "objective",
        "option_schema_json": '{"required": true, "count": 4, "multiple": false}',
        "rubric_json": '{"score": "full score only when selected answer equals correct_answer"}',
    },
    {
        "type_key": "multiple_choice",
        "display_name": "不定项选择题",
        "description": "从多个选项中选择一个或多个正确答案。",
        "answer_format": "correct_answer must be comma-separated option labels, such as A,C.",
        "grading_method": "objective",
        "option_schema_json": '{"required": true, "count": 4, "multiple": true}',
        "rubric_json": '{"score": "full score only when selected option set equals correct_answer set"}',
    },
    {
        "type_key": "true_false",
        "display_name": "判断题",
        "description": "判断陈述是否正确。",
        "answer_format": "correct_answer must be True or False.",
        "grading_method": "objective",
        "option_schema_json": '{"required": false, "allowed": ["True", "False"]}',
        "rubric_json": '{"score": "full score only when normalized answer equals correct_answer"}',
    },
    {
        "type_key": "fill_blank",
        "display_name": "填空题",
        "description": "填写简短且唯一的答案。",
        "answer_format": "correct_answer should be concise and unique.",
        "grading_method": "llm",
        "option_schema_json": '{"required": false}',
        "rubric_json": '{"score": "grade semantic equivalence against the concise correct answer"}',
    },
    {
        "type_key": "short_answer",
        "display_name": "简答题",
        "description": "用文字说明关键步骤、理由或结论。",
        "answer_format": "answer should include key scoring points.",
        "grading_method": "llm",
        "option_schema_json": '{"required": false}',
        "rubric_json": '{"score": "grade according to key points in answer and explanation"}',
    },
)
