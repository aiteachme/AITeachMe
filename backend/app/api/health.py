"""Health-check route."""

from fastapi import APIRouter

from app.api.openapi import build_error_responses
from app.schemas.common import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="健康检查",
    description="返回后端服务的基础健康状态，用于前端或部署平台探活。",
    response_description="服务健康状态。",
    responses=build_error_responses([500]),
)
async def health_check() -> HealthResponse:
    """Return the current health status of the API service."""

    return HealthResponse(status="ok")
