"""Compatibility wrapper exposing profile pipeline helpers."""

from app.workflows.profile.mastery_updater import (
    MasteryAttempt,
    MasteryUpdateResult,
    compute_confidence_score,
    compute_mastery_score,
    compute_stability_score,
    update_mastery_from_exam,
)
from app.workflows.profile.review_scheduler import compute_sm2_interval, schedule_reviews
from app.workflows.profile.runtime import generate_report_suggestions
from app.workflows.profile.weakness_analyzer import WeaknessItem, analyze_weakness

__all__ = [
    "MasteryAttempt",
    "MasteryUpdateResult",
    "WeaknessItem",
    "analyze_weakness",
    "compute_confidence_score",
    "compute_mastery_score",
    "compute_sm2_interval",
    "compute_stability_score",
    "generate_report_suggestions",
    "schedule_reviews",
    "update_mastery_from_exam",
]
