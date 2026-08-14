"""User-safe error presentation for the interact chat lane."""

from __future__ import annotations


_AUTH_ERROR_SNIPPETS = (
    "authenticationerror",
    "401 unauthorized",
    "failed to retrieve token",
    "incorrect api key",
    "invalid api key",
    "invalid_api_key",
    "apikey-error",
    "llm_api_key",
    "api key is not configured",
    "aihubmix_api_error",
)

_MODEL_PROVIDER_ERROR_SNIPPETS = (
    "upstream model call failed",
    "上游模型调用失败",
    "litellm.",
    "litellm_",
    "model call",
    "openaiexception",
)

_TECHNICAL_DETAIL_SNIPPETS = (
    "[sql:",
    "parameters:",
    "traceback",
    "bearer ",
    "authorization",
    "api_key",
    "api-key",
    "sk-",
    "password",
    "secret",
)


def sanitize_interact_error_detail(error: object) -> str:
    """Return a user-facing chat error without provider or secret details."""

    text = str(error or "").strip()
    if not text:
        return "AI 回复生成失败，请稍后重试。"

    lower_text = text.lower()
    if any(snippet in lower_text for snippet in _AUTH_ERROR_SNIPPETS):
        return "模型服务认证失败，当前无法生成回复。请检查模型服务密钥或稍后重试。"
    if any(snippet in lower_text for snippet in _MODEL_PROVIDER_ERROR_SNIPPETS):
        return "模型服务暂时不可用，当前无法生成回复。请稍后重试。"
    if len(text) > 240 or any(snippet in lower_text for snippet in _TECHNICAL_DETAIL_SNIPPETS):
        return "AI 回复生成失败，请稍后重试。"
    return text


__all__ = ["sanitize_interact_error_detail"]
