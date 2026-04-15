"""Digest observability package 鈥?re-exports for backward compatibility.

Submodules:
  models          鈥?Pydantic models (SlowItemTiming, DigestTokenSummary, 鈥?
  lane_summaries  鈥?Per-lane summary builders (docgen, kg)
  timing          鈥?build_token_summary, build_unified_timing_report
"""

from .models import (
    DigestModelUsageSummary,
    DigestTimingReport,
    DigestTokenSummary,
    SlowItemTiming,
)
from .lane_summaries import (
    add_slow_item,
    build_docgen_lane_summary,
    build_kg_lane_summary,
    build_slow_items,
    step_slow_items,
)
from .timing import (
    build_token_summary,
    build_unified_timing_report,
)

__all__ = [
    # Models
    "DigestModelUsageSummary",
    "DigestTimingReport",
    "DigestTokenSummary",
    "SlowItemTiming",
    # Slow items
    "add_slow_item",
    "build_slow_items",
    "step_slow_items",
    # Lane summaries
    "build_docgen_lane_summary",
    "build_kg_lane_summary",
    # Timing
    "build_token_summary",
    "build_unified_timing_report",
]

