"""健康检查接口。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, HealthData, ok_response

router = APIRouter(prefix="/api", tags=["health"])


@router.get(
    "/health",
    response_model=ApiResponse[HealthData],
    summary="健康检查",
    description="返回后端服务的健康状态。",
    response_description="统一健康检查响应。",
    responses=build_error_responses([500]),
)
async def health_check() -> ApiResponse[HealthData]:
    """返回服务健康状态。"""

    return ok_response(HealthData(status="ok"))
