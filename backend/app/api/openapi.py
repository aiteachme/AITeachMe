"""OpenAPI 辅助函数。"""

from __future__ import annotations

from collections.abc import Iterable

from app.schemas.common import ErrorResponse

_DEFAULT_ERROR_DESCRIPTIONS: dict[int, str] = {
    400: "请求参数不合法。",
    404: "资源不存在。",
    409: "当前资源状态不允许执行该操作。",
    413: "上传文件超出大小限制。",
    422: "业务校验未通过。",
    500: "服务内部异常。",
    502: "上游模型调用失败。",
    503: "依赖服务当前不可用。",
}


def build_error_responses(status_codes: Iterable[int]) -> dict[int, dict[str, object]]:
    """构造统一错误响应描述。"""

    return {
        status_code: {
            "model": ErrorResponse,
            "description": _DEFAULT_ERROR_DESCRIPTIONS.get(status_code, "接口可能返回业务错误。"),
        }
        for status_code in status_codes
    }
