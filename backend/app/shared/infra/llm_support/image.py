"""Image generation helper built on top of LiteLLM."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.shared.infra.exceptions import LLMCallError, LLMTimeoutError
from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.shared.infra.observability.trace import langsmith_trace

from .common import (
    build_completion_context,
    get_semaphore,
    logger,
    raise_last_error,
    request_timeout_s,
    trace_log_fields,
    track_call,
)
from .litellm_loader import load_litellm
from .observability import _end_langsmith_trace, _sanitize_langsmith_value

litellm = load_litellm()

AIHUBMIX_DESCRIBE_MODELS = {"describe"}


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


def _completion_model(provider_model: str) -> str:
    return provider_model if "/" in provider_model else f"openai/{provider_model}"


def _is_aihubmix_base_url(value: str | None) -> bool:
    return "aihubmix.com" in str(value or "").casefold()


def _is_aihubmix_prediction_model(value: str) -> bool:
    normalized = str(value or "").strip()
    return "/" in normalized


def _is_describe_only_model(value: str | None) -> bool:
    return str(value or "").strip().casefold() in AIHUBMIX_DESCRIBE_MODELS


def _item_get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _extract_images(response: Any) -> list[GeneratedImage]:
    data = _item_get(response, "data", []) or []
    images: list[GeneratedImage] = []
    for item in data:
        url = str(_item_get(item, "url", "") or "")
        b64_json = str(_item_get(item, "b64_json", "") or "")
        revised_prompt = str(_item_get(item, "revised_prompt", "") or "")
        mime_type = str(_item_get(item, "mime_type", "") or "") or "image/png"
        provider_metadata = {}
        if isinstance(item, Mapping):
            provider_metadata = {
                key: value
                for key, value in item.items()
                if key not in {"url", "b64_json", "revised_prompt"}
            }
        if url or b64_json:
            images.append(
                GeneratedImage(
                    url=url,
                    b64_json=b64_json,
                    revised_prompt=revised_prompt,
                    mime_type=mime_type,
                    provider_metadata=provider_metadata,
                )
            )
    return images


def _extract_prediction_images(payload: Mapping[str, Any]) -> list[GeneratedImage]:
    candidates = payload.get("output") or payload.get("data") or payload.get("images") or []
    if isinstance(candidates, Mapping):
        candidates = [candidates]
    images: list[GeneratedImage] = []
    if isinstance(candidates, list):
        for item in candidates:
            if isinstance(item, str):
                images.append(GeneratedImage(url=item))
                continue
            if not isinstance(item, Mapping):
                continue
            url = str(item.get("url") or item.get("image_url") or item.get("uri") or "")
            b64_json = str(item.get("b64_json") or item.get("base64") or item.get("base64_json") or "")
            mime_type = str(item.get("mime_type") or item.get("content_type") or "") or "image/png"
            if url or b64_json:
                images.append(
                    GeneratedImage(
                        url=url,
                        b64_json=b64_json,
                        mime_type=mime_type,
                        provider_metadata={key: value for key, value in item.items() if key not in {"url", "image_url", "uri", "b64_json", "base64", "base64_json"}},
                    )
                )
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
                "revised_prompt": image.revised_prompt[:240],
            }
            for image in result.images
        ],
    }


def _build_aihubmix_prediction_input(*, prompt: str, size: str, n: int, response_format: str) -> dict[str, Any]:
    return {
        "prompt": prompt,
        "size": size,
        "n": max(1, int(n or 1)),
        "response_format": "base64_json" if response_format == "b64_json" else response_format,
        "watermark": False,
    }


async def _agenerate_aihubmix_prediction(
    *,
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    size: str,
    n: int,
    response_format: str,
    timeout_s: int,
) -> ImageGenerationResult:
    endpoint = f"{api_base.rstrip('/')}/models/{model.strip('/')}/predictions"
    request_payload = {
        "input": _build_aihubmix_prediction_input(
            prompt=prompt,
            size=size,
            n=n,
            response_format=response_format,
        )
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_payload,
        )
    if response.status_code >= 400:
        raise LLMCallError(
            reason=(
                f"aihubmix prediction endpoint failed: {response.status_code} "
                f"{response.text[:240]}"
            )
        )
    payload = response.json()
    images = _extract_prediction_images(payload)
    if not images:
        raise LLMCallError(reason=f"aihubmix prediction returned no image: {str(payload)[:240]}")
    return ImageGenerationResult(
        model=model,
        prompt=prompt,
        images=images,
        raw_metadata={
            "provider": "aihubmix",
            "endpoint": endpoint,
            "response_keys": sorted(str(key) for key in payload.keys()),
        },
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
    """Generate one or more images through the configured image model."""

    if not str(prompt or "").strip():
        raise LLMCallError(reason="image prompt is empty")
    context = build_completion_context(
        call_purpose=LLMCallPurpose.IMAGE_GENERATION,
        model=model or "image_generation",
    )
    if (model is None or model == "image_generation") and not context.settings.image_generation_enabled:
        raise LLMCallError(reason="models.image_generation is not configured")
    if _is_describe_only_model(context.model):
        raise LLMCallError(
            reason=(
                "model DESCRIBE is an AiHubMix image description endpoint "
                "(requires an image_file input), not a text-to-image generation model. "
                "Use a text-to-image model such as gpt-image-1, gpt-4o-image-vip, "
                "FLUX.1-Kontext-pro, or an AiHubMix prediction model path like qianfan/qwen-image."
            )
        )

    call_kwargs = {
        "model": _completion_model(context.model),
        "prompt": str(prompt).strip(),
        "api_base": kwargs.pop("api_base", None) or None,
        "api_key": kwargs.pop("api_key", None) or context.api_key,
        "timeout": kwargs.pop("timeout", context.profile.timeout_s),
        "n": max(1, int(n or 1)),
        "size": size,
        "response_format": response_format,
    }
    if call_kwargs["api_base"] is None:
        from app.shared.infra.env_support import get_env

        call_kwargs["api_base"] = get_env("LLM_BASE_URL")
    call_kwargs.update(kwargs)

    last_error: Exception | None = None
    call_started_at = time.monotonic()
    tracked_model = context.model
    async with get_semaphore():
        for attempt in range(1, context.profile.max_retries + 1):
            start = time.monotonic()
            logger.info(
                "llm_image_generation_started",
                attempt=attempt,
                model=tracked_model,
                size=size,
                n=call_kwargs["n"],
                timeout_s=context.profile.timeout_s,
                **trace_log_fields(),
            )
            try:
                with langsmith_trace(
                    name="LLM：文生图",
                    run_type="llm",
                    inputs={
                        "model": call_kwargs["model"],
                        "prompt": _sanitize_langsmith_value(prompt, capture_text=True, field_name="prompt"),
                        "size": size,
                        "n": call_kwargs["n"],
                    },
                    extra_metadata={
                        "call_purpose": LLMCallPurpose.IMAGE_GENERATION.value,
                        "task_type": LLMCallPurpose.IMAGE_GENERATION.value,
                        "mode": "image_generation",
                        "model": tracked_model,
                        **dict(extra_metadata or {}),
                    },
                ) as trace_run:
                    if _is_aihubmix_base_url(call_kwargs.get("api_base")) and _is_aihubmix_prediction_model(context.model):
                        result = await _agenerate_aihubmix_prediction(
                            api_base=str(call_kwargs["api_base"]),
                            api_key=str(call_kwargs["api_key"]),
                            model=context.model,
                            prompt=str(prompt).strip(),
                            size=size,
                            n=int(call_kwargs["n"]),
                            response_format=response_format,
                            timeout_s=request_timeout_s(context.profile.timeout_s),
                        )
                    else:
                        response = await asyncio.wait_for(
                            litellm.aimage_generation(**call_kwargs),
                            timeout=request_timeout_s(context.profile.timeout_s),
                        )
                        result = ImageGenerationResult(
                            model=tracked_model,
                            prompt=str(prompt).strip(),
                            images=_extract_images(response),
                            raw_metadata={
                                "response_type": type(response).__name__,
                            },
                        )
                    if not result.images:
                        raise LLMCallError(reason="image generation returned no image")
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
                    task_type=LLMCallPurpose.IMAGE_GENERATION,
                    model=tracked_model,
                    start=call_started_at,
                    success=True,
                )
                return result
            except asyncio.TimeoutError:
                last_error = LLMTimeoutError(timeout_s=context.profile.timeout_s)
                logger.warning(
                    "llm_image_generation_timeout",
                    attempt=attempt,
                    elapsed_s=round(time.monotonic() - start, 2),
                    model=tracked_model,
                    **trace_log_fields(),
                )
            except asyncio.CancelledError:
                track_call(
                    task_type=LLMCallPurpose.IMAGE_GENERATION,
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
            if attempt < context.profile.max_retries:
                await asyncio.sleep(attempt * 2)

    track_call(
        task_type=LLMCallPurpose.IMAGE_GENERATION,
        model=tracked_model,
        start=call_started_at,
        success=False,
        error=str(last_error),
    )
    raise_last_error(last_error)


__all__ = ["GeneratedImage", "ImageGenerationResult", "agenerate_image"]
