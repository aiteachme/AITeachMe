"""Legacy curriculum service shim.

Curriculum/theme-tree/prereq/unit endpoints are removed in the new docs+graph model.
Only taxonomy-anchor APIs remain as no-op placeholders for backward routing stability.
"""

from __future__ import annotations

from sqlmodel import Session

from app.schemas.knowledge import TaxonomyAnchorResponse


def manage_taxonomy_anchors(
    session: Session,
    *,
    subject: str,
    action: str,
    anchor_id: int | None = None,
    title: str | None = None,
    anchor_type: str | None = None,
    parent_anchor_id: int | None = None,
    order_index: int | None = None,
) -> list[TaxonomyAnchorResponse]:
    del session, subject, action, anchor_id, title, anchor_type, parent_anchor_id, order_index
    return []
