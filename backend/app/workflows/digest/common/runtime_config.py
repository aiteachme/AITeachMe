"""Digest-oriented projection of project runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.shared.infra.settings import get_settings
from app.shared.infra.env_support import describe_project_settings_source

if TYPE_CHECKING:
    from app.workflows.digest.planner.lib.constants import PlannerModeContract


@dataclass(frozen=True, slots=True)
class PlannerRuntimeConfig:
    """Planner-facing teaching defaults."""

    default_digest_mode: str
    history_turns: int


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
            history_turns=max(1, int(settings.planner.history_turns or 10)),
        ),
        settings_source=describe_project_settings_source(),
    )


def get_planner_mode_runtime_config(digest_mode: str) -> "PlannerModeContract":
    """Compatibility wrapper for planner mode prompt contracts."""

    from app.workflows.digest.planner.lib.constants import get_planner_mode_contract

    return get_planner_mode_contract(digest_mode)


__all__ = [
    "PlannerRuntimeConfig",
    "TeachingRuntimeConfig",
    "get_planner_mode_runtime_config",
    "get_teaching_runtime_config",
    "get_teaching_runtime_settings_source",
]
