"""Shared sizing policy for exam knowledge-unit candidate pools."""

from __future__ import annotations

EXAM_BLUEPRINT_CANDIDATE_MIN = 24
EXAM_BLUEPRINT_CANDIDATE_MAX = 60
EXAM_BLUEPRINT_CANDIDATE_PER_QUESTION = 4
DEFAULT_EXAM_READINESS_QUESTION_COUNT = 8


def exam_candidate_unit_limit(question_count: int) -> int:
    normalized_count = max(1, int(question_count or 1))
    scaled = normalized_count * EXAM_BLUEPRINT_CANDIDATE_PER_QUESTION
    return min(EXAM_BLUEPRINT_CANDIDATE_MAX, max(EXAM_BLUEPRINT_CANDIDATE_MIN, scaled))


def exam_readiness_question_count(chapter_count: int | None = None) -> int:
    normalized_chapters = max(0, int(chapter_count or 0))
    return max(DEFAULT_EXAM_READINESS_QUESTION_COUNT, normalized_chapters, 1)


def exam_readiness_candidate_target(chapter_count: int | None = None) -> int:
    return exam_candidate_unit_limit(exam_readiness_question_count(chapter_count))


def exam_ready_units_per_chapter_floor(chapter_count: int | None = None) -> int:
    normalized_chapters = max(0, int(chapter_count or 0))
    if normalized_chapters <= 0:
        return 0
    target = exam_readiness_candidate_target(normalized_chapters)
    return max(2, min(4, (target + normalized_chapters - 1) // normalized_chapters))


__all__ = [
    "DEFAULT_EXAM_READINESS_QUESTION_COUNT",
    "EXAM_BLUEPRINT_CANDIDATE_MAX",
    "EXAM_BLUEPRINT_CANDIDATE_MIN",
    "EXAM_BLUEPRINT_CANDIDATE_PER_QUESTION",
    "exam_candidate_unit_limit",
    "exam_readiness_candidate_target",
    "exam_readiness_question_count",
    "exam_ready_units_per_chapter_floor",
]
