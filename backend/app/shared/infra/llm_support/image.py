"""Image generation helper backed by LiteLLM."""

from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.shared.infra.env_support import get_env
from app.shared.infra.exceptions import LLMCallError, LLMTimeoutError
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.observability.trace import langsmith_trace
from app.shared.infra.settings.support import (
    get_llm_api_version,
    normalize_llm_provider_name,
    resolve_runtime_llm_provider,
)

from .common import (
    apply_provider_extra_headers,
    build_completion_context,
    context_request_timeout_s,
    effective_max_retries,
    get_llm_concurrency_limiter,
    logger,
    pop_overall_timeout_s,
    raise_last_error,
    should_enforce_request_timeout,
    trace_log_fields,
    track_call,
    wait_for_overall_timeout,
)
from .litellm_loader import load_litellm
from .observability import _end_langsmith_trace, _sanitize_langsmith_value

DESCRIBE_ONLY_IMAGE_MODELS = frozenset({"describe"})
ERROR_PREVIEW_CHARS = 240
LITELLM_IMAGE_PROVIDER_PREFIXES = frozenset(
    {
        "openai",
        "azure",
        "gemini",
        "vertex_ai",
        "bedrock",
        "openrouter",
        "black_forest_labs",
        "recraft",
        "xinference",
        "nscale",
    }
)
IMAGE_MODEL_PREFIX_BY_RUNTIME_PROVIDER: dict[str, str] = {
    "azure": "azure",
    "bedrock": "bedrock",
    "gemini": "gemini",
    "openrouter": "openrouter",
    "vertex_ai": "vertex_ai",
}
OPENAI_COMPATIBLE_IMAGE_RUNTIME_PROVIDERS = frozenset(
    {
        "openai_compatible",
        "vllm",
        "qwen",
        "deepseek",
        "kimi",
        "glm",
        "siliconflow",
        "doubao",
        "xai",
    }
)
OPENAI_GPT_IMAGE_MODEL_PREFIXES = ("gpt-image-", "gpt-4o-image")


class GeneratedImage(BaseModel):
    """One generated image returned by an upstream model."""

    url: str = ""
    b64_json: str = ""
    revised_prompt: str = ""
    mime_type: str = "image/png"
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class ImageGenerationResult(BaseModel):
    """Normalized image generation response."""

    model: str = ""
    prompt: str = ""
    images: list[GeneratedImage] = Field(default_factory=list)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


def _item_get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _preview_text(value: Any, *, limit: int = ERROR_PREVIEW_CHARS) -> str:
    return str(value)[:limit]


def _provider_prefix(value: str | None) -> str:
    normalized = str(value or "").strip()
    if "/" not in normalized:
        return ""
    provider, _model_name = normalized.split("/", 1)
    return provider.strip().lower()


def _model_name_without_provider(value: str | None) -> str:
    normalized = str(value or "").strip()
    provider = _provider_prefix(normalized)
    if provider in LITELLM_IMAGE_PROVIDER_PREFIXES:
        return normalized.split("/", 1)[1].strip()
    return normalized


def _has_litellm_image_provider_prefix(value: str | None) -> bool:
    return _provider_prefix(value) in LITELLM_IMAGE_PROVIDER_PREFIXES


def _is_describe_only_model(value: str | None) -> bool:
    return _model_name_without_provider(value).rsplit("/", 1)[-1].casefold() in DESCRIBE_ONLY_IMAGE_MODELS


def _is_openai_gpt_image_model(value: str | None) -> bool:
    model_name = _model_name_without_provider(value).casefold()
    return any(model_name.startswith(prefix) for prefix in OPENAI_GPT_IMAGE_MODEL_PREFIXES)


def _resolve_litellm_image_model(model: str | None, *, runtime_provider: str | None) -> str:
    normalized = str(model or "").strip()
    if not normalized:
        return normalized
    provider = normalize_llm_provider_name(runtime_provider)
    if _has_litellm_image_provider_prefix(normalized):
        return normalized
    if "/" in normalized:
        if provider == "openrouter":
            return f"openrouter/{normalized}"
        return normalized

    if provider in IMAGE_MODEL_PREFIX_BY_RUNTIME_PROVIDER:
        return f"{IMAGE_MODEL_PREFIX_BY_RUNTIME_PROVIDER[provider]}/{normalized}"
    if provider in OPENAI_COMPATIBLE_IMAGE_RUNTIME_PROVIDERS:
        return f"openai/{normalized}"
    return normalized


def _data_url_to_image(value: str) -> GeneratedImage | None:
    normalized = str(value or "").strip()
    if not normalized.startswith("data:") or ";base64," not in normalized:
        return None
    header, b64_data = normalized.split(",", 1)
    mime_type = header[5:].split(";", 1)[0].strip() or "image/png"
    return GeneratedImage(b64_json=b64_data, mime_type=mime_type)


def _image_url_value(item: Any) -> str:
    for key in ("url", "image_url", "imageUrl", "uri"):
        value = _item_get(item, key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, Mapping):
            nested = str(value.get("url") or "").strip()
            if nested:
                return nested
    return ""


def _base64_value(item: Any) -> str:
    for key in ("b64_json", "base64", "base64_json", "image_base64"):
        value = str(_item_get(item, key, "") or "").strip()
        if value:
            return value
    return ""


def _image_from_item(item: Any) -> GeneratedImage | None:
    data_url = _image_url_value(item)
    parsed = _data_url_to_image(data_url)
    if parsed is not None:
        return parsed

    b64_json = _base64_value(item)
    revised_prompt = str(_item_get(item, "revised_prompt", "") or "")
    mime_type = str(_item_get(item, "mime_type", None) or _item_get(item, "content_type", None) or "") or "image/png"
    provider_metadata = {}
    if isinstance(item, Mapping):
        image_payload_keys = {
            "url",
            "image_url",
            "imageUrl",
            "uri",
            "b64_json",
            "base64",
            "base64_json",
            "image_base64",
            "revised_prompt",
            "mime_type",
            "content_type",
        }
        provider_metadata = {
            str(key): value
            for key, value in item.items()
            if str(key) not in image_payload_keys
        }
    if data_url or b64_json:
        return GeneratedImage(
            url=data_url,
            b64_json=b64_json,
            revised_prompt=revised_prompt,
            mime_type=mime_type,
            provider_metadata=provider_metadata,
        )
    return None


def _extract_images(response: Any) -> list[GeneratedImage]:
    """Extract images from LiteLLM/OpenAI-shaped responses."""

    images: list[GeneratedImage] = []
    data = _item_get(response, "data", []) or []
    if isinstance(data, Mapping):
        data = [data]
    for item in list(data):
        image = _image_from_item(item)
        if image is not None:
            images.append(image)

    for choice in list(_item_get(response, "choices", []) or []):
        message = _item_get(choice, "message", {}) or {}
        for item in list(_item_get(message, "images", []) or []):
            image = _image_from_item(item)
            if image is not None:
                images.append(image)
    return images


def _metadata_without_image_payload(result: ImageGenerationResult) -> dict[str, Any]:
    return {
        "model": result.model,
        "prompt_chars": len(result.prompt),
        "image_count": len(result.images),
        "images": [
            {
                "has_url": bool(image.url),
                "has_b64_json": bool(image.b64_json),
                "mime_type": image.mime_type,
                "revised_prompt": image.revised_prompt,
            }
            for image in result.images
        ],
    }


def _response_metadata(response: Any) -> dict[str, Any]:
    metadata = {"response_type": type(response).__name__}
    if isinstance(response, Mapping):
        metadata["response_keys"] = sorted(str(key) for key in response.keys())
    return metadata


async def _materialize_b64_images(
    images: list[GeneratedImage],
    *,
    timeout_s: int | None,
) -> list[GeneratedImage]:
    materialized: list[GeneratedImage] = []
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        for image in images:
            if image.b64_json or not image.url:
                materialized.append(image)
                continue
            response = await client.get(image.url)
            response.raise_for_status()
            mime_type = response.headers.get("content-type", "").split(";", 1)[0].strip() or image.mime_type
            materialized.append(
                GeneratedImage(
                    url=image.url,
                    b64_json=base64.b64encode(response.content).decode("ascii"),
                    revised_prompt=image.revised_prompt,
                    mime_type=mime_type or "image/png",
                    provider_metadata=dict(image.provider_metadata),
                )
            )
    return materialized


def _build_litellm_image_kwargs(
    *,
    model: str,
    prompt: str,
    runtime_provider: str,
    api_base: str | None,
    api_key: str | None,
    timeout_s: int | None,
    size: str,
    n: int,
    response_format: str | None,
    extra_kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    call_kwargs: dict[str, Any] = {
        "model": _resolve_litellm_image_model(model, runtime_provider=runtime_provider),
        "prompt": prompt,
        "n": max(1, int(n or 1)),
        "size": size,
    }
    if timeout_s is not None:
        call_kwargs["timeout"] = timeout_s
    if api_base:
        call_kwargs["api_base"] = api_base
    if api_key:
        call_kwargs["api_key"] = api_key
    if response_format and not _is_openai_gpt_image_model(call_kwargs["model"]):
        call_kwargs["response_format"] = response_format

    normalized_provider = normalize_llm_provider_name(runtime_provider)
    if normalized_provider == "azure":
        api_version = str(extra_kwargs.get("api_version") or get_llm_api_version() or "").strip()
        if api_version:
            call_kwargs["api_version"] = api_version

    for key, value in dict(extra_kwargs).items():
        if value is None or key in {"api_base", "api_key", "timeout", "api_version", "max_retries"}:
            continue
        call_kwargs[str(key)] = value
    apply_provider_extra_headers(call_kwargs)
    return call_kwargs


async def _agenerate_litellm_image(
    *,
    call_kwargs: Mapping[str, Any],
    prompt: str,
    timeout_s: int | None,
) -> ImageGenerationResult:
    litellm = load_litellm()
    response = await asyncio.wait_for(
        litellm.aimage_generation(**dict(call_kwargs)),
        timeout=timeout_s,
    )
    images = _extract_images(response)
    if not images:
        raise LLMCallError(reason=f"LiteLLM image generation returned no image: {_preview_text(response)}")
    return ImageGenerationResult(
        model=str(call_kwargs.get("model") or ""),
        prompt=prompt,
        images=images,
        raw_metadata=_response_metadata(response),
    )


async def agenerate_image(
    prompt: str,
    *,
    model: str | None = None,
    size: str = "1024x1024",
    n: int = 1,
    response_format: str = "b64_json",
    extra_metadata: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> ImageGenerationResult:
    """Generate one or more images through the configured LiteLLM image model."""

    overall_timeout_s = pop_overall_timeout_s(kwargs)
    return await wait_for_overall_timeout(
        _agenerate_image_impl(
            prompt,
            model=model,
            size=size,
            n=n,
            response_format=response_format,
            extra_metadata=extra_metadata,
            kwargs=kwargs,
        ),
        overall_timeout_s,
    )


async def _agenerate_image_impl(
    prompt: str,
    *,
    model: str | None,
    size: str,
    n: int,
    response_format: str,
    extra_metadata: Mapping[str, Any] | None,
    kwargs: dict[str, Any],
) -> ImageGenerationResult:
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        raise LLMCallError(reason="image prompt is empty")
    context = build_completion_context(
        task_type=TaskType.IMAGE_GENERATION,
        model=model or "image_generation",
    )
    if (model is None or model == "image_generation") and not context.settings.image_generation_enabled:
        raise LLMCallError(reason="models.image_generation is not configured")
    if _is_describe_only_model(context.model):
        raise LLMCallError(
            reason=(
                "model DESCRIBE is an image description endpoint "
                "(requires an image_file input), not a text-to-image generation model. "
                "Use a LiteLLM image_generation model such as gpt-image-1, "
                "openrouter/google/gemini-2.5-flash-image, vertex_ai/imagegeneration@006, "
                "or openai/<model> for an OpenAI-compatible image gateway."
            )
        )

    api_base = kwargs.pop("api_base", None) or get_env("LLM_BASE_URL") or None
    api_key = kwargs.pop("api_key", None) or context.api_key
    raw_timeout_s = int(kwargs.pop("timeout", context.profile.timeout_s) or context.profile.timeout_s)
    max_retries = effective_max_retries(context, kwargs)
    timeout_s = raw_timeout_s if should_enforce_request_timeout(context) else None
    prediction_input = kwargs.pop("prediction_input", None)
    kwargs.pop("endpoint_mode", None)
    if isinstance(prediction_input, Mapping):
        merged_kwargs = dict(prediction_input)
        merged_kwargs.update(kwargs)
        kwargs = merged_kwargs

    runtime_provider = resolve_runtime_llm_provider(base_url=str(api_base or ""))
    call_kwargs = _build_litellm_image_kwargs(
        model=context.model,
        prompt=prompt_text,
        runtime_provider=runtime_provider,
        api_base=api_base,
        api_key=api_key,
        timeout_s=timeout_s,
        size=size,
        n=n,
        response_format=response_format,
        extra_kwargs=kwargs,
    )

    last_error: Exception | None = None
    call_started_at = time.monotonic()
    tracked_model = str(call_kwargs["model"])
    async with get_llm_concurrency_limiter().slot() as lease:
        for attempt in range(1, max_retries + 1):
            start = time.monotonic()
            logger.info(
                "llm_image_generation_started",
                attempt=attempt,
                model=tracked_model,
                size=size,
                n=call_kwargs["n"],
                timeout_s=timeout_s,
                **trace_log_fields(),
            )
            try:
                with langsmith_trace(
                    name="LLM：文生图",
                    run_type="llm",
                    inputs={
                        "model": tracked_model,
                        "prompt": _sanitize_langsmith_value(prompt_text, capture_text=True, field_name="prompt"),
                        "size": size,
                        "n": call_kwargs["n"],
                    },
                    extra_metadata={
                        "task_type": TaskType.IMAGE_GENERATION,
                        "mode": "image_generation",
                        "model": tracked_model,
                        "runtime_provider": runtime_provider,
                        **dict(extra_metadata or {}),
                    },
                ) as trace_run:
                    result = await _agenerate_litellm_image(
                        call_kwargs=call_kwargs,
                        prompt=prompt_text,
                        timeout_s=context_request_timeout_s(context, call_kwargs),
                    )
                    if response_format == "b64_json" and any(not image.b64_json and image.url for image in result.images):
                        result = ImageGenerationResult(
                            model=result.model,
                            prompt=result.prompt,
                            images=await _materialize_b64_images(
                                result.images,
                                timeout_s=context_request_timeout_s(context, call_kwargs),
                            ),
                            raw_metadata=dict(result.raw_metadata),
                        )
                    _end_langsmith_trace(trace_run, result=_metadata_without_image_payload(result))
                logger.info(
                    "llm_image_generation_complete",
                    attempt=attempt,
                    elapsed_s=round(time.monotonic() - start, 2),
                    model=tracked_model,
                    image_count=len(result.images),
                    **trace_log_fields(),
                )
                track_call(
                    task_type=TaskType.IMAGE_GENERATION,
                    model=tracked_model,
                    start=call_started_at,
                    success=True,
                )
                return result
            except asyncio.TimeoutError:
                last_error = LLMTimeoutError(timeout_s=raw_timeout_s)
                logger.warning(
                    "llm_image_generation_timeout",
                    attempt=attempt,
                    elapsed_s=round(time.monotonic() - start, 2),
                    model=tracked_model,
                    **trace_log_fields(),
                )
            except asyncio.CancelledError:
                track_call(
                    task_type=TaskType.IMAGE_GENERATION,
                    model=tracked_model,
                    start=call_started_at,
                    success=False,
                    error="cancelled",
                )
                raise
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "llm_image_generation_failed",
                    attempt=attempt,
                    elapsed_s=round(time.monotonic() - start, 2),
                    model=tracked_model,
                    error=str(exc),
                    **trace_log_fields(),
                )
            if attempt < max_retries:
                await lease.sleep_without_holding_slot(attempt * 2)

    track_call(
        task_type=TaskType.IMAGE_GENERATION,
        model=tracked_model,
        start=call_started_at,
        success=False,
        error=str(last_error),
    )
    raise_last_error(last_error)


__all__ = ["GeneratedImage", "ImageGenerationResult", "agenerate_image"]
