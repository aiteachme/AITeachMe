"""Knowledge API router aggregator.

This module keeps the historical import path ``app.api.knowledge`` stable while
splitting handlers into:
- docs/curriculum planner endpoints: ``app.api.knowledge_docs``
- graph query endpoints: ``app.api.knowledge_graph``
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.knowledge_docs import router as knowledge_docs_router
from app.api.knowledge_graph import router as knowledge_graph_router

router = APIRouter(prefix="/api/v1/subjects/{subject}/knowledge", tags=["knowledge"])
router.include_router(knowledge_docs_router)
router.include_router(knowledge_graph_router)

__all__ = ["router"]

