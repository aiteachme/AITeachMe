"""State contract for the independent multimodal DocGen graph."""

from __future__ import annotations

import operator
from typing import Annotated, Any

from app.workflows.digest.docgen.state import DocGenState


class MultimodalDocGenState(DocGenState, total=False):
    """Original DocGen state plus fields owned by the multimodal lane.

    Inheriting the canonical state preserves the exact reducer objects used by
    the currently shared downstream nodes. The original state is not modified.
    """

    # Only meaningful images enter downstream state. Decorative covers, logos,
    # unrelated UI, and other meaningless images remain cache decisions and
    # aggregate metrics, so later nodes cannot accidentally consume them.
    visual_evidence_items: list[dict[str, Any]]
    visual_evidence_failures: list[dict[str, Any]]
    visual_evidence_metrics: dict[str, Any]
    visual_model_name: str
    visual_evidence_ms: int
    visual_evidence_llm_calls: Annotated[int, operator.add]


__all__ = ["MultimodalDocGenState"]
