"""Shared OpenAPI helpers for API routes."""

from __future__ import annotations

from collections.abc import Iterable

from app.schemas.common import ErrorResponse


_DEFAULT_ERROR_DESCRIPTIONS: dict[int, str] = {
    400: "请求参数不合法。",
    404: "请求的资源不存在。",
    422: "请求通过了基础校验，但业务处理失败。",
    500: "服务内部出现未处理异常。",
    502: "上游 LLM 或外部依赖调用失败。",
    503: "依赖配置缺失或暂时不可用。",
}


def build_error_responses(status_codes: Iterable[int]) -> dict[int, dict[str, object]]:
    """Build a standard OpenAPI error response mapping for route decorators."""

    return {
        status_code: {
            "model": ErrorResponse,
            "description": _DEFAULT_ERROR_DESCRIPTIONS.get(status_code, "接口可能返回的错误响应。"),
        }
        for status_code in status_codes
    }
