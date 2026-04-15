"""Digest-oriented projection of project runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.shared.infra.config import get_settings
from app.shared.infra.env_support import resolve_project_config_path


@dataclass(frozen=True, slots=True)
class PlannerModeRuntimeConfig:
    """Planner mode-specific defaults."""

    min_chapters: int
    max_chapters: int
    target_length: str


@dataclass(frozen=True, slots=True)
class PlannerRuntimeConfig:
    """Planner-facing teaching defaults."""

    default_tone: str
    default_digest_mode: str
    allow_external_search: bool
    sprint: PlannerModeRuntimeConfig
    systematic: PlannerModeRuntimeConfig


@dataclass(frozen=True, slots=True)
class TeachingRuntimeConfig:
    """Top-level teaching runtime configuration."""

    planner: PlannerRuntimeConfig
    source_path: str


def get_teaching_runtime_config_path() -> Path:
    """Return the resolved project config path for diagnostics/debugging."""

    return resolve_project_config_path()


@lru_cache
def get_teaching_runtime_config() -> TeachingRuntimeConfig:
    """Return the cached teaching runtime config."""

    settings = get_settings()
    return TeachingRuntimeConfig(
        planner=PlannerRuntimeConfig(
            default_tone=settings.planner_default_tone,
            default_digest_mode=settings.planner_default_digest_mode,
            allow_external_search=settings.planner_allow_external_search,
            sprint=PlannerModeRuntimeConfig(
                min_chapters=settings.planner_sprint_min_chapters,
                max_chapters=max(
                    settings.planner_sprint_min_chapters,
                    settings.planner_sprint_max_chapters,
                ),
                target_length=settings.planner_sprint_target_length,
            ),
            systematic=PlannerModeRuntimeConfig(
                min_chapters=settings.planner_systematic_min_chapters,
                max_chapters=max(
                    settings.planner_systematic_min_chapters,
                    settings.planner_systematic_max_chapters,
                ),
                target_length=settings.planner_systematic_target_length,
            ),
        ),
        source_path=str(resolve_project_config_path()),
    )


def get_planner_mode_runtime_config(digest_mode: str) -> PlannerModeRuntimeConfig:
    """Return planner defaults for the requested digest mode."""

    planner = get_teaching_runtime_config().planner
    return planner.sprint if str(digest_mode).strip().lower() == "sprint" else planner.systematic


__all__ = [
    "PlannerModeRuntimeConfig",
    "PlannerRuntimeConfig",
    "TeachingRuntimeConfig",
    "get_planner_mode_runtime_config",
    "get_teaching_runtime_config",
    "get_teaching_runtime_config_path",
]
