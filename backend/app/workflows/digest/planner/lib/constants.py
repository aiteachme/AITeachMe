"""Planner-owned product constants.

These values describe the planner prompt contract and normalization budget.
They are not runtime knobs: changing them changes product behavior and should
go through code review with the planner prompts.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlannerModeContract:
    min_chapters: int
    max_chapters: int
    target_length: str


PLANNER_MODE_CONTRACTS: dict[str, PlannerModeContract] = {
    "sprint": PlannerModeContract(
        min_chapters=4,
        max_chapters=7,
        target_length="8000-30000字",
    ),
    "systematic": PlannerModeContract(
        min_chapters=5,
        max_chapters=12,
        target_length="30000-100000字",
    ),
}


def normalize_planner_mode(value: object, *, default: str = "systematic") -> str:
    mode = str(value or default).strip().lower()
    return "sprint" if mode == "sprint" else "systematic"


def get_planner_mode_contract(digest_mode: object) -> PlannerModeContract:
    return PLANNER_MODE_CONTRACTS[normalize_planner_mode(digest_mode)]


__all__ = [
    "PLANNER_MODE_CONTRACTS",
    "PlannerModeContract",
    "get_planner_mode_contract",
    "normalize_planner_mode",
]
