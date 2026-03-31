"""Prompt templates for the examine workflow."""

SYSTEM_PROMPT_EXAM_GENERATE = """
You are building a structured exam blueprint for the subject: {{ subject }}.
Return JSON only.

Requirements:
- Generate {{ num_questions }} questions.
- Allowed question types: {{ question_types }}.
- Allowed difficulty values: {{ difficulties }}.
- The paper should align with the requested knowledge points, weak points, and recent mistakes.
- Every question must be answerable from the provided teaching context.
- Keep wording clear, exam-like, and specific.

Requested knowledge points:
{{ requested_knowledge_points }}

Available knowledge points:
{{ available_knowledge_points }}

Weak knowledge points:
{{ weak_knowledge_points }}

Recent mistakes:
{{ recent_mistake_stems }}
""".strip()

SYSTEM_PROMPT_EXAM_GENERATE_FROM_TEXT = """
You are generating high-quality exam questions from curated teaching context.
Return JSON only in the shape {"questions": [...]}.

Requirements:
- Generate exactly {{ num_questions }} questions.
- Allowed question types: {{ question_types }}.
- Allowed difficulty values: {{ difficulties }}.
- Use only the provided knowledge packet.
- Questions must feel like a real teacher-made paper, not flash cards.
- Prefer clear stems, unambiguous answers, and concise explanations.
- If the style profile mentions a sample paper, follow that tone and section style when reasonable.
- Each question item must include:
  - question_type
  - difficulty
  - stem
  - options (only for single_choice)
  - answer
  - explanation
  - knowledge_node_id (pick the best matching node when possible)

Knowledge packet:
{{ knowledge_packet }}
""".strip()

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
    "exam_generate": SYSTEM_PROMPT_EXAM_GENERATE,
    "exam_generate_from_text": SYSTEM_PROMPT_EXAM_GENERATE_FROM_TEXT,
    "short_answer_grade": SYSTEM_PROMPT_SHORT_ANSWER_GRADE,
    "error_cause_label": SYSTEM_PROMPT_ERROR_CAUSE_LABEL,
    "mistake_analysis": SYSTEM_PROMPT_MISTAKE_ANALYSIS,
}
