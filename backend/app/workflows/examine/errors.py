"""Public training errors; detailed diagnostics stay in workflow state/logs."""

from __future__ import annotations


def public_exam_error_message(error: object) -> str:
    """Explain recoverable model failures without exposing provider internals."""

    text = str(error or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if "api key is disabled" in lowered:
        return "模型服务的 API Key 已停用。请启用或更换密钥，并在设置中测试模型连接后重试。"
    if any(marker in lowered for marker in (
        "authenticationerror", "401 unauthorized", "incorrect api key", "invalid api key",
        "invalid_api_key", "api key is not configured", "llm_api_key",
    )):
        return "模型服务认证失败。请检查设置中的模型网关和 API Key，测试连接通过后重试。"
    if any(marker in lowered for marker in ("timeout", "timed out")):
        return "模型服务响应超时，请稍后重试。"
    if any(marker in lowered for marker in ("ratelimiterror", "rate limit", "too many requests")):
        return "模型服务请求过于频繁，请稍后重试。"
    if any(marker in lowered for marker in ("litellm.", "openaiexception", "上游模型调用失败")):
        return "模型服务暂时不可用。请在设置中测试模型连接后重试。"
    if "knowledge-unit filtering failed" in lowered:
        return "知识点筛选失败，请稍后重试。"
    if len(text) > 240 or any(marker in lowered for marker in (
        "traceback", "[sql:", "parameters:", "bearer ", "authorization", "api_key",
        "api-key", "sk-", "password", "secret", "validation error", "input_value=",
    )):
        return "训练内容处理失败，请重试；若反复出现，请检查题型配置和模型连接。"
    return text


__all__ = ["public_exam_error_message"]
