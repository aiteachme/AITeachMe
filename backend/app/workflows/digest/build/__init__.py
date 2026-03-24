"""Unified digest build coordination layer.

Uses lazy imports to avoid circular dependency with kg/finalize_nodes.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.workflows.digest.build.artifacts import publish_artifact, try_read_artifact
    from app.workflows.digest.build.consistency import RepairBudget, bounded_repair, check_consistency
    from app.workflows.digest.build.events import (
        ChapterPriorsPublishedEvent,
        TopicAnchorSnapshotPublishedEvent,
        UnifiedBuildCompletedEvent,
        UnifiedBuildFailedEvent,
        UnifiedBuildStartedEvent,
    )
    from app.workflows.digest.build.models import (
        ChapterPrior,
        ChapterPriors,
        CoverageReport,
        TopicAnchor,
        TopicAnchorSnapshot,
    )
    from app.workflows.digest.build.runtime import run_unified_digest_build
    from app.workflows.digest.build.state import UnifiedBuildResult, UnifiedBuildState


def __getattr__(name: str):
    _lazy_map = {
        "publish_artifact": ("app.workflows.digest.build.artifacts", "publish_artifact"),
        "try_read_artifact": ("app.workflows.digest.build.artifacts", "try_read_artifact"),
        "RepairBudget": ("app.workflows.digest.build.consistency", "RepairBudget"),
        "bounded_repair": ("app.workflows.digest.build.consistency", "bounded_repair"),
        "check_consistency": ("app.workflows.digest.build.consistency", "check_consistency"),
        "ChapterPriorsPublishedEvent": ("app.workflows.digest.build.events", "ChapterPriorsPublishedEvent"),
        "TopicAnchorSnapshotPublishedEvent": ("app.workflows.digest.build.events", "TopicAnchorSnapshotPublishedEvent"),
        "UnifiedBuildCompletedEvent": ("app.workflows.digest.build.events", "UnifiedBuildCompletedEvent"),
        "UnifiedBuildFailedEvent": ("app.workflows.digest.build.events", "UnifiedBuildFailedEvent"),
        "UnifiedBuildStartedEvent": ("app.workflows.digest.build.events", "UnifiedBuildStartedEvent"),
        "ChapterPrior": ("app.workflows.digest.build.models", "ChapterPrior"),
        "ChapterPriors": ("app.workflows.digest.build.models", "ChapterPriors"),
        "CoverageReport": ("app.workflows.digest.build.models", "CoverageReport"),
        "TopicAnchor": ("app.workflows.digest.build.models", "TopicAnchor"),
        "TopicAnchorSnapshot": ("app.workflows.digest.build.models", "TopicAnchorSnapshot"),
        "run_unified_digest_build": ("app.workflows.digest.build.runtime", "run_unified_digest_build"),
        "UnifiedBuildResult": ("app.workflows.digest.build.state", "UnifiedBuildResult"),
        "UnifiedBuildState": ("app.workflows.digest.build.state", "UnifiedBuildState"),
    }
    if name in _lazy_map:
        module_path, attr = _lazy_map[name]
        from importlib import import_module
        mod = import_module(module_path)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ChapterPrior",
    "ChapterPriors",
    "ChapterPriorsPublishedEvent",
    "CoverageReport",
    "RepairBudget",
    "TopicAnchor",
    "TopicAnchorSnapshot",
    "TopicAnchorSnapshotPublishedEvent",
    "UnifiedBuildCompletedEvent",
    "UnifiedBuildFailedEvent",
    "UnifiedBuildResult",
    "UnifiedBuildStartedEvent",
    "UnifiedBuildState",
    "bounded_repair",
    "check_consistency",
    "publish_artifact",
    "run_unified_digest_build",
    "try_read_artifact",
]
