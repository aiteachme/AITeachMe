"""Digest-oriented projection of project runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.infra.settings import get_settings
from app.shared.infra.env_support import describe_project_settings_source


@dataclass(frozen=True, slots=True)
class PlannerModeRuntimeConfig:
    """Planner mode-specific defaults."""

    min_chapters: int
    max_chapters: int
    target_length: str


@dataclass(frozen=True, slots=True)
class PlannerRuntimeConfig:
    """Planner-facing teaching defaults."""

    default_digest_mode: str
    sprint: PlannerModeRuntimeConfig
    systematic: PlannerModeRuntimeConfig


@dataclass(frozen=True, slots=True)
class TeachingRuntimeConfig:
    """Top-level teaching runtime configuration."""

    planner: PlannerRuntimeConfig
    settings_source: str


def get_teaching_runtime_settings_source() -> str:
    """Return a human-readable project settings source description."""

    return describe_project_settings_source()


def get_teaching_runtime_config() -> TeachingRuntimeConfig:
    """Return the current teaching runtime config."""

    settings = get_settings()
    return TeachingRuntimeConfig(
        planner=PlannerRuntimeConfig(
            default_digest_mode=settings.planner.default_digest_mode,
            sprint=PlannerModeRuntimeConfig(
                min_chapters=settings.planner.sprint.min_chapters,
                max_chapters=max(
                    settings.planner.sprint.min_chapters,
                    settings.planner.sprint.max_chapters,
                ),
                target_length=settings.planner.sprint.target_length,
            ),
            systematic=PlannerModeRuntimeConfig(
                min_chapters=settings.planner.systematic.min_chapters,
                max_chapters=max(
                    settings.planner.systematic.min_chapters,
                    settings.planner.systematic.max_chapters,
                ),
                target_length=settings.planner.systematic.target_length,
            ),
        ),
        settings_source=describe_project_settings_source(),
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
    "get_teaching_runtime_settings_source",
]
