"""Question-build prompt templates."""

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
  - knowledge_unit_id (pick the best matching node when possible)

Knowledge packet:
{{ knowledge_packet }}
""".strip()

PROMPTS: dict[str, str] = {
    "exam_generate": SYSTEM_PROMPT_EXAM_GENERATE,
    "exam_generate_from_text": SYSTEM_PROMPT_EXAM_GENERATE_FROM_TEXT,
}

__all__ = [
    "PROMPTS",
    "SYSTEM_PROMPT_EXAM_GENERATE",
    "SYSTEM_PROMPT_EXAM_GENERATE_FROM_TEXT",
]
