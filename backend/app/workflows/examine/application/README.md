# Examine Application

`workflows/examine/application/` is the canonical home for API-facing Examine use cases.

## Responsibilities

- Trigger question-template builds.
- Generate exam papers.
- Submit and grade answers.
- Query exam history, paper details, and question banks.

Graph internals remain in `question_build/` and `exam_grade/`; this package coordinates API-facing use cases and repository operations.
