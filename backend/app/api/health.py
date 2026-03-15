"""
健康检查端点 — GET /api/health

需求：12.4
"""

from fastapi import APIRouter

from app.schemas.common import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok")
