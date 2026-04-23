"""Image generation helper built on top of LiteLLM."""

from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from app.shared.infra.exceptions import LLMCallError, LLMTimeoutError
from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.shared.infra.observability.trace import langsmith_trace
from app.shared.infra.settings.support import (
    is_openai_compatible_one_step_image_model,
    normalize_openai_compatible_image_model_name,
    resolve_runtime_llm_provider,
)

from .common import (
    build_litellm_provider_kwargs,
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

PREDICTION_DESCRIBE_MODELS = {"describe"}
PREDICTION_ONLY_INPUT_KEYS = frozenset(
    {
        "numberOfImages",
        "stream",
        "sequential_image_generation",
    }
)
OFFICIALLY_UNSUPPORTED_IMAGE_PROVIDERS = frozenset({"anthropic", "groq", "deepseek", "kimi", "mistral"})
ERROR_PREVIEW_CHARS = 240


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


def _is_prediction_model_name(value: str) -> bool:
    normalized = str(value or "").strip()
    return "/" in normalized


def _is_bare_model_name(value: str | None) -> bool:
    normalized = str(value or "").strip()
    return bool(normalized) and "/" not in normalized


def _is_describe_only_model(value: str | None) -> bool:
    normalized = str(value or "").strip()
    model_name = normalized.rsplit("/", 1)[-1]
    return model_name.casefold() in PREDICTION_DESCRIBE_MODELS


def _should_use_prediction_endpoint(
    *,
    model: str,
    endpoint_mode: str | None,
    prediction_input: Mapping[str, Any] | None,
) -> bool:
    normalized_mode = str(endpoint_mode or "").strip().lower()
    if normalized_mode == "prediction":
        return True
    if normalized_mode == "images":
        return False
    if _is_prediction_model_name(model):
        return True
    if any(key in dict(prediction_input or {}) for key in PREDICTION_ONLY_INPUT_KEYS):
        return True
    return False


def _item_get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _base_origin(api_base: str | None) -> str:
    normalized = str(api_base or "").strip()
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return normalized.rstrip("/")


def _data_url_to_image(value: str) -> GeneratedImage | None:
    normalized = str(value or "").strip()
    if not normalized.startswith("data:") or ";base64," not in normalized:
        return None
    header, b64_data = normalized.split(",", 1)
    mime_type = header[5:].split(";", 1)[0].strip() or "image/png"
    return GeneratedImage(b64_json=b64_data, mime_type=mime_type)


def _preview_text(value: Any, *, limit: int = ERROR_PREVIEW_CHARS) -> str:
    return str(value)[:limit]


async def _materialize_b64_images(
    images: list[GeneratedImage],
    *,
    timeout_s: int,
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


def _extract_qwen_native_images(payload: Mapping[str, Any]) -> list[GeneratedImage]:
    output = payload.get("output") or {}
    choices = output.get("choices") or []
    images: list[GeneratedImage] = []
    if not isinstance(choices, list):
        return images
    for choice in choices:
        if not isinstance(choice, Mapping):
            continue
        message = choice.get("message") or {}
        contents = message.get("content") or []
        if not isinstance(contents, list):
            continue
        for item in contents:
            if not isinstance(item, Mapping):
                continue
            image_url = str(item.get("image") or "")
            if image_url:
                images.append(GeneratedImage(url=image_url))
    return images


def _extract_siliconflow_images(payload: Mapping[str, Any]) -> list[GeneratedImage]:
    images: list[GeneratedImage] = []
    for item in list(payload.get("images") or []):
        if not isinstance(item, Mapping):
            continue
        image_url = str(item.get("url") or "")
        if image_url:
            images.append(GeneratedImage(url=image_url))
    return images


def _extract_minimax_images(payload: Mapping[str, Any]) -> list[GeneratedImage]:
    data = payload.get("data") or {}
    images: list[GeneratedImage] = []
    for url in list(data.get("image_urls") or []):
        normalized = str(url or "").strip()
        if normalized:
            images.append(GeneratedImage(url=normalized))
    for raw_b64 in list(data.get("image_base64") or []):
        normalized = str(raw_b64 or "").strip()
        if normalized:
            images.append(GeneratedImage(b64_json=normalized, mime_type="image/jpeg"))
    return images


def _extract_openrouter_images(payload: Mapping[str, Any]) -> list[GeneratedImage]:
    images: list[GeneratedImage] = []
    for choice in list(payload.get("choices") or []):
        if not isinstance(choice, Mapping):
            continue
        message = choice.get("message") or {}
        for item in list(message.get("images") or []):
            if not isinstance(item, Mapping):
                continue
            image_url = item.get("image_url") or {}
            data_url = str(image_url.get("url") or "")
            parsed = _data_url_to_image(data_url)
            if parsed is not None:
                images.append(parsed)
            elif data_url:
                images.append(GeneratedImage(url=data_url))
    return images


def _extract_gemini_images(payload: Mapping[str, Any]) -> list[GeneratedImage]:
    images: list[GeneratedImage] = []
    for candidate in list(payload.get("candidates") or []):
        if not isinstance(candidate, Mapping):
            continue
        content = candidate.get("content") or {}
        for part in list(content.get("parts") or []):
            if not isinstance(part, Mapping):
                continue
            inline_data = part.get("inlineData") or part.get("inline_data") or {}
            b64_data = str(inline_data.get("data") or "")
            mime_type = str(inline_data.get("mimeType") or inline_data.get("mime_type") or "image/png")
            if b64_data:
                images.append(GeneratedImage(b64_json=b64_data, mime_type=mime_type))
    return images


def _extract_imagen_native_images(payload: Mapping[str, Any]) -> list[GeneratedImage]:
    images: list[GeneratedImage] = []
    for item in list(payload.get("generatedImages") or payload.get("generated_images") or []):
        if not isinstance(item, Mapping):
            continue
        image = item.get("image") or {}
        b64_data = str(image.get("imageBytes") or image.get("image_bytes") or "")
        if b64_data:
            images.append(GeneratedImage(b64_json=b64_data, mime_type="image/png"))
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


def _build_prediction_image_input(*, prompt: str, size: str, n: int, response_format: str) -> dict[str, Any]:
    return {
        "prompt": prompt,
        "size": size,
        "n": max(1, int(n or 1)),
        "response_format": "base64_json" if response_format == "b64_json" else response_format,
    }


def _build_openai_compatible_image_payload(
    *,
    model: str,
    prompt: str,
    size: str,
    n: int,
    response_format: str,
    extra_body: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "n": max(1, int(n or 1)),
        "response_format": "b64_json" if response_format == "b64_json" else response_format,
    }
    for key, value in dict(extra_body or {}).items():
        if value is None:
            continue
        payload[key] = value
    return payload


async def _agenerate_prediction_image(
    *,
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    size: str,
    n: int,
    response_format: str,
    timeout_s: int,
    extra_input: Mapping[str, Any] | None = None,
) -> ImageGenerationResult:
    request_input = _build_prediction_image_input(
        prompt=prompt,
        size=size,
        n=n,
        response_format=response_format,
    )
    for key, value in dict(extra_input or {}).items():
        if value is None:
            continue
        request_input[key] = value
    endpoint = f"{api_base.rstrip('/')}/models/{model.strip('/')}/predictions"
    request_payload = {
        "input": request_input
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
                f"prediction image endpoint failed: {response.status_code} "
                f"{_preview_text(response.text)}"
            )
        )
    payload = response.json()
    images = _extract_prediction_images(payload)
    if not images:
        raise LLMCallError(reason=f"prediction image endpoint returned no image: {_preview_text(payload)}")
    return ImageGenerationResult(
        model=model,
        prompt=prompt,
        images=images,
        raw_metadata={
            "provider": "openai_compatible_prediction_http",
            "endpoint": endpoint,
            "response_keys": sorted(str(key) for key in payload.keys()),
        },
    )


async def _agenerate_openai_compatible_image(
    *,
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    size: str,
    n: int,
    response_format: str,
    timeout_s: int,
    extra_body: Mapping[str, Any] | None = None,
) -> ImageGenerationResult:
    endpoint = f"{api_base.rstrip('/')}/images/generations"
    request_payload = _build_openai_compatible_image_payload(
        model=model,
        prompt=prompt,
        size=size,
        n=n,
        response_format=response_format,
        extra_body=extra_body,
    )
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
                f"openai-compatible image endpoint failed: {response.status_code} "
                f"{_preview_text(response.text)}"
            )
        )
    payload = response.json()
    images = _extract_images(payload)
    if not images:
        raise LLMCallError(
            reason=f"openai-compatible image endpoint returned no image: {_preview_text(payload)}"
        )
    return ImageGenerationResult(
        model=model,
        prompt=prompt,
        images=images,
        raw_metadata={
            "provider": "openai_compatible_http",
            "endpoint": endpoint,
            "response_keys": sorted(str(key) for key in payload.keys()),
        },
    )


async def _agenerate_qwen_native_image(
    *,
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    size: str,
    n: int,
    timeout_s: int,
    parameters: Mapping[str, Any] | None = None,
) -> ImageGenerationResult:
    endpoint = f"{_base_origin(api_base)}/api/v1/services/aigc/multimodal-generation/generation"
    request_parameters = {
        "size": size,
        "n": max(1, int(n or 1)),
        **{key: value for key, value in dict(parameters or {}).items() if value is not None},
    }
    request_payload = {
        "model": model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ]
        },
        "parameters": request_parameters,
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
        raise LLMCallError(reason=f"qwen image endpoint failed: {response.status_code} {_preview_text(response.text)}")
    payload = response.json()
    images = _extract_qwen_native_images(payload)
    if not images:
        raise LLMCallError(reason=f"qwen image endpoint returned no image: {_preview_text(payload)}")
    return ImageGenerationResult(
        model=model,
        prompt=prompt,
        images=images,
        raw_metadata={
            "provider": "qwen_native_http",
            "endpoint": endpoint,
            "response_keys": sorted(str(key) for key in payload.keys()),
        },
    )


async def _agenerate_siliconflow_image(
    *,
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    timeout_s: int,
    payload: Mapping[str, Any],
) -> ImageGenerationResult:
    endpoint = f"{api_base.rstrip('/')}/images/generations"
    request_payload = {key: value for key, value in dict(payload).items() if value is not None}
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
        raise LLMCallError(reason=f"siliconflow image endpoint failed: {response.status_code} {_preview_text(response.text)}")
    payload_json = response.json()
    images = _extract_siliconflow_images(payload_json)
    if not images:
        raise LLMCallError(reason=f"siliconflow image endpoint returned no image: {_preview_text(payload_json)}")
    return ImageGenerationResult(
        model=model,
        prompt=prompt,
        images=images,
        raw_metadata={
            "provider": "siliconflow_http",
            "endpoint": endpoint,
            "response_keys": sorted(str(key) for key in payload_json.keys()),
        },
    )


async def _agenerate_minimax_image(
    *,
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    timeout_s: int,
    payload: Mapping[str, Any],
) -> ImageGenerationResult:
    endpoint = f"{_base_origin(api_base)}/v1/image_generation"
    request_payload = {key: value for key, value in dict(payload).items() if value is not None}
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
        raise LLMCallError(reason=f"minimax image endpoint failed: {response.status_code} {_preview_text(response.text)}")
    payload_json = response.json()
    images = _extract_minimax_images(payload_json)
    if not images:
        raise LLMCallError(reason=f"minimax image endpoint returned no image: {_preview_text(payload_json)}")
    return ImageGenerationResult(
        model=model,
        prompt=prompt,
        images=images,
        raw_metadata={
            "provider": "minimax_http",
            "endpoint": endpoint,
            "response_keys": sorted(str(key) for key in payload_json.keys()),
        },
    )


async def _agenerate_openrouter_chat_image(
    *,
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    timeout_s: int,
    modalities: list[str],
    extra_body: Mapping[str, Any] | None = None,
) -> ImageGenerationResult:
    endpoint = f"{api_base.rstrip('/')}/chat/completions"
    request_payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": modalities,
        "stream": False,
    }
    for key, value in dict(extra_body or {}).items():
        if value is None:
            continue
        request_payload[key] = value
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
        raise LLMCallError(reason=f"openrouter image endpoint failed: {response.status_code} {_preview_text(response.text)}")
    payload = response.json()
    images = _extract_openrouter_images(payload)
    if not images:
        raise LLMCallError(reason=f"openrouter image endpoint returned no image: {_preview_text(payload)}")
    return ImageGenerationResult(
        model=model,
        prompt=prompt,
        images=images,
        raw_metadata={
            "provider": "openrouter_chat_http",
            "endpoint": endpoint,
            "response_keys": sorted(str(key) for key in payload.keys()),
        },
    )


async def _agenerate_gemini_native_image(
    *,
    api_key: str,
    model: str,
    prompt: str,
    timeout_s: int,
    extra_body: Mapping[str, Any] | None = None,
) -> ImageGenerationResult:
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    request_payload: dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}],
    }
    if extra_body:
        request_payload.update({key: value for key, value in dict(extra_body).items() if value is not None})
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.post(
            endpoint,
            headers={
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
            },
            json=request_payload,
        )
    if response.status_code >= 400:
        raise LLMCallError(reason=f"gemini image endpoint failed: {response.status_code} {_preview_text(response.text)}")
    payload = response.json()
    images = _extract_gemini_images(payload)
    if not images:
        raise LLMCallError(reason=f"gemini image endpoint returned no image: {_preview_text(payload)}")
    return ImageGenerationResult(
        model=model,
        prompt=prompt,
        images=images,
        raw_metadata={
            "provider": "gemini_native_http",
            "endpoint": endpoint,
            "response_keys": sorted(str(key) for key in payload.keys()),
        },
    )


async def _agenerate_imagen_native_image(
    *,
    api_key: str,
    model: str,
    prompt: str,
    timeout_s: int,
    parameters: Mapping[str, Any] | None = None,
) -> ImageGenerationResult:
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predict"
    request_payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {key: value for key, value in dict(parameters or {}).items() if value is not None},
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.post(
            endpoint,
            headers={
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
            },
            json=request_payload,
        )
    if response.status_code >= 400:
        raise LLMCallError(reason=f"imagen image endpoint failed: {response.status_code} {_preview_text(response.text)}")
    payload = response.json()
    images = _extract_imagen_native_images(payload)
    if not images:
        raise LLMCallError(reason=f"imagen image endpoint returned no image: {_preview_text(payload)}")
    return ImageGenerationResult(
        model=model,
        prompt=prompt,
        images=images,
        raw_metadata={
            "provider": "imagen_native_http",
            "endpoint": endpoint,
            "response_keys": sorted(str(key) for key in payload.keys()),
        },
    )


def _extract_vertex_imagen_images(payload: Mapping[str, Any]) -> list[GeneratedImage]:
    images: list[GeneratedImage] = []
    for item in list(payload.get("predictions") or []):
        if not isinstance(item, Mapping):
            continue
        b64_data = str(item.get("bytesBase64Encoded") or "")
        mime_type = str(item.get("mimeType") or "image/png")
        if b64_data:
            images.append(GeneratedImage(b64_json=b64_data, mime_type=mime_type))
    return images


async def _agenerate_vertex_imagen_image(
    *,
    api_key: str,
    model: str,
    prompt: str,
    timeout_s: int,
    parameters: Mapping[str, Any] | None = None,
) -> ImageGenerationResult:
    from app.shared.infra.env_support import get_env

    project_id = (get_env("VERTEX_AI_PROJECT_ID") or get_env("GOOGLE_CLOUD_PROJECT") or "").strip()
    location = (get_env("VERTEX_AI_LOCATION") or get_env("GOOGLE_CLOUD_LOCATION") or "us-central1").strip()
    access_token = (
        get_env("VERTEX_AI_ACCESS_TOKEN")
        or get_env("GOOGLE_CLOUD_ACCESS_TOKEN")
        or ""
    ).strip()
    if not project_id or not access_token:
        raise LLMCallError(
            reason=(
                "vertex_ai image generation requires VERTEX_AI_PROJECT_ID (or GOOGLE_CLOUD_PROJECT) "
                "and VERTEX_AI_ACCESS_TOKEN (or GOOGLE_CLOUD_ACCESS_TOKEN)."
            )
        )
    endpoint = (
        f"https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/"
        f"{location}/publishers/google/models/{model}:predict"
    )
    request_payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {key: value for key, value in dict(parameters or {}).items() if value is not None},
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=request_payload,
        )
    if response.status_code >= 400:
        raise LLMCallError(reason=f"vertex_ai image endpoint failed: {response.status_code} {_preview_text(response.text)}")
    payload = response.json()
    images = _extract_vertex_imagen_images(payload)
    if not images:
        raise LLMCallError(reason=f"vertex_ai image endpoint returned no image: {_preview_text(payload)}")
    return ImageGenerationResult(
        model=model,
        prompt=prompt,
        images=images,
        raw_metadata={
            "provider": "vertex_imagen_http",
            "endpoint": endpoint,
            "response_keys": sorted(str(key) for key in payload.keys()),
        },
    )


def _extract_bedrock_nova_images(payload: Mapping[str, Any]) -> list[GeneratedImage]:
    images: list[GeneratedImage] = []
    for item in list(payload.get("images") or []):
        normalized = str(item or "").strip()
        if normalized:
            images.append(GeneratedImage(b64_json=normalized, mime_type="image/png"))
    return images


async def _agenerate_bedrock_image(
    *,
    model: str,
    prompt: str,
    size: str,
    n: int,
    timeout_s: int,
    image_generation_config: Mapping[str, Any] | None = None,
    text_to_image_params: Mapping[str, Any] | None = None,
) -> ImageGenerationResult:
    import asyncio
    import json

    import boto3

    width = 1024
    height = 1024
    if "x" in str(size):
        raw_width, raw_height = str(size).lower().split("x", 1)
        if raw_width.isdigit() and raw_height.isdigit():
            width = int(raw_width)
            height = int(raw_height)

    request_payload = {
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {
            "text": prompt,
            **{key: value for key, value in dict(text_to_image_params or {}).items() if value is not None},
        },
        "imageGenerationConfig": {
            "numberOfImages": max(1, int(n or 1)),
            "width": width,
            "height": height,
            **{key: value for key, value in dict(image_generation_config or {}).items() if value is not None},
        },
    }

    def _invoke() -> dict[str, Any]:
        client = boto3.client("bedrock-runtime")
        response = client.invoke_model(
            modelId=model,
            body=json.dumps(request_payload),
            contentType="application/json",
            accept="application/json",
        )
        return json.loads(response["body"].read().decode("utf-8"))

    payload = await asyncio.wait_for(asyncio.to_thread(_invoke), timeout=timeout_s)
    images = _extract_bedrock_nova_images(payload)
    if not images:
        raise LLMCallError(reason=f"bedrock image endpoint returned no image: {_preview_text(payload)}")
    return ImageGenerationResult(
        model=model,
        prompt=prompt,
        images=images,
        raw_metadata={
            "provider": "bedrock_nova_runtime",
            "response_keys": sorted(str(key) for key in payload.keys()),
        },
    )


def _resolve_openrouter_modalities(model: str, modalities: Any = None) -> list[str]:
    if isinstance(modalities, list) and modalities:
        return [str(item) for item in modalities if str(item).strip()]
    normalized_model = str(model or "").strip().lower()
    if normalized_model.startswith("google/"):
        return ["image", "text"]
    return ["image"]


def _parse_size_dimensions(size: str, *, default: tuple[int, int] = (1024, 1024)) -> tuple[int, int]:
    normalized = str(size or "").strip().lower()
    if "x" not in normalized:
        return default
    raw_width, raw_height = normalized.split("x", 1)
    if raw_width.isdigit() and raw_height.isdigit():
        return int(raw_width), int(raw_height)
    return default


def _build_provider_image_options(
    *,
    model: str,
    prompt: str,
    size: str,
    n: int,
    response_format: str,
    kwargs: Mapping[str, Any],
    explicit_prediction_input: Mapping[str, Any] | None,
) -> dict[str, Any]:
    passthrough_image_body = {
        key: kwargs.get(key)
        for key in ("quality", "style", "user", "background", "output_format")
        if kwargs.get(key) is not None
    }
    passthrough_prediction_input = {
        key: kwargs.get(key)
        for key in (
            "quality",
            "style",
            "background",
            "output_format",
            "watermark",
            "stream",
            "sequential_image_generation",
            "numberOfImages",
        )
        if kwargs.get(key) is not None
    }
    if isinstance(explicit_prediction_input, Mapping):
        for key, value in explicit_prediction_input.items():
            if value is not None:
                passthrough_prediction_input[str(key)] = value

    qwen_parameters = {
        key: kwargs.get(key)
        for key in ("negative_prompt", "prompt_extend", "watermark", "seed")
        if kwargs.get(key) is not None
    }

    width, height = _parse_size_dimensions(size)
    minimax_payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "response_format": "base64" if response_format == "b64_json" else response_format,
        "width": width,
        "height": height,
    }
    for key in ("aspect_ratio", "seed", "prompt_optimizer", "watermark"):
        if kwargs.get(key) is not None:
            minimax_payload[key] = kwargs.get(key)

    siliconflow_payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "image_size": kwargs.get("image_size") or size,
        "batch_size": kwargs.get("batch_size") or max(1, int(n or 1)),
    }
    for key in ("negative_prompt", "seed", "num_inference_steps", "guidance_scale", "cfg", "image"):
        if kwargs.get(key) is not None:
            siliconflow_payload[key] = kwargs.get(key)

    openrouter_extra_body = {
        key: kwargs.get(key)
        for key in ("n", "temperature", "top_p", "stream", "image_config")
        if kwargs.get(key) is not None
    }
    if "n" not in openrouter_extra_body and int(n or 1) > 1:
        openrouter_extra_body["n"] = int(n or 1)

    gemini_extra_body = {
        "generationConfig": {
            key: value
            for key, value in {
                "responseModalities": kwargs.get("response_modalities") or ["TEXT", "IMAGE"],
            }.items()
            if value is not None
        }
    }

    imagen_parameters = {
        key: kwargs.get(key)
        for key in ("numberOfImages", "sampleCount", "aspectRatio", "personGeneration", "safetyFilterLevel")
        if kwargs.get(key) is not None
    }
    imagen_parameters.setdefault("numberOfImages", max(1, int(n or 1)))

    vertex_imagen_parameters = {
        key: kwargs.get(key)
        for key in (
            "sampleCount",
            "addWatermark",
            "aspectRatio",
            "enhancePrompt",
            "includeRaiReason",
            "includeSafetyAttributes",
            "personGeneration",
            "safetySetting",
            "seed",
            "storageUri",
            "outputOptions",
        )
        if kwargs.get(key) is not None
    }
    vertex_imagen_parameters.setdefault("sampleCount", max(1, int(n or 1)))

    bedrock_image_generation_config = {
        key: kwargs.get(key)
        for key in ("seed", "cfgScale", "quality")
        if kwargs.get(key) is not None
    }
    bedrock_text_to_image_params = {
        key: kwargs.get(key)
        for key in ("negativeText", "style")
        if kwargs.get(key) is not None
    }

    return {
        "passthrough_image_body": passthrough_image_body,
        "passthrough_prediction_input": passthrough_prediction_input,
        "qwen_parameters": qwen_parameters,
        "minimax_payload": minimax_payload,
        "siliconflow_payload": siliconflow_payload,
        "openrouter_extra_body": openrouter_extra_body,
        "openrouter_modalities": _resolve_openrouter_modalities(model, kwargs.get("modalities")),
        "gemini_extra_body": gemini_extra_body,
        "imagen_parameters": imagen_parameters,
        "vertex_imagen_parameters": vertex_imagen_parameters,
        "bedrock_image_generation_config": bedrock_image_generation_config,
        "bedrock_text_to_image_params": bedrock_text_to_image_params,
    }


async def _dispatch_provider_image_request(
    *,
    runtime_provider: str,
    call_kwargs: Mapping[str, Any],
    prompt: str,
    size: str,
    response_format: str,
    timeout_s: int,
    endpoint_mode: str | None,
    options: Mapping[str, Any],
) -> ImageGenerationResult:
    model = str(call_kwargs["model"])
    api_base = str(call_kwargs["api_base"])
    api_key = str(call_kwargs["api_key"])
    n = int(call_kwargs["n"])

    if runtime_provider in OFFICIALLY_UNSUPPORTED_IMAGE_PROVIDERS:
        raise LLMCallError(
            reason=(
                f"provider `{runtime_provider}` has no official text-to-image API in this project "
                "compatibility layer. Please switch to a provider with image generation support."
            )
        )

    if runtime_provider == "qwen":
        return await _agenerate_qwen_native_image(
            api_base=api_base,
            api_key=api_key,
            model=model,
            prompt=prompt,
            size=size,
            n=n,
            timeout_s=timeout_s,
            parameters=options["qwen_parameters"],
        )
    if runtime_provider == "minimax":
        return await _agenerate_minimax_image(
            api_base=api_base,
            api_key=api_key,
            model=model,
            prompt=prompt,
            timeout_s=timeout_s,
            payload=options["minimax_payload"],
        )
    if runtime_provider == "siliconflow":
        return await _agenerate_siliconflow_image(
            api_base=api_base,
            api_key=api_key,
            model=model,
            prompt=prompt,
            timeout_s=timeout_s,
            payload=options["siliconflow_payload"],
        )
    if runtime_provider == "openrouter":
        return await _agenerate_openrouter_chat_image(
            api_base=api_base,
            api_key=api_key,
            model=model,
            prompt=prompt,
            timeout_s=timeout_s,
            modalities=options["openrouter_modalities"],
            extra_body=options["openrouter_extra_body"],
        )
    if runtime_provider == "gemini" and model.startswith("imagen-"):
        return await _agenerate_imagen_native_image(
            api_key=api_key,
            model=model,
            prompt=prompt,
            timeout_s=timeout_s,
            parameters=options["imagen_parameters"],
        )
    if runtime_provider == "gemini":
        return await _agenerate_gemini_native_image(
            api_key=api_key,
            model=model,
            prompt=prompt,
            timeout_s=timeout_s,
            extra_body=options["gemini_extra_body"],
        )
    if runtime_provider == "vertex_ai":
        return await _agenerate_vertex_imagen_image(
            api_key=api_key,
            model=model,
            prompt=prompt,
            timeout_s=timeout_s,
            parameters=options["vertex_imagen_parameters"],
        )
    if runtime_provider == "bedrock":
        return await _agenerate_bedrock_image(
            model=model,
            prompt=prompt,
            size=size,
            n=n,
            timeout_s=timeout_s,
            image_generation_config=options["bedrock_image_generation_config"],
            text_to_image_params=options["bedrock_text_to_image_params"],
        )
    if runtime_provider == "openai_compatible":
        if _should_use_prediction_endpoint(
            model=model,
            endpoint_mode=endpoint_mode,
            prediction_input=options["passthrough_prediction_input"],
        ):
            return await _agenerate_prediction_image(
                api_base=api_base,
                api_key=api_key,
                model=model,
                prompt=prompt,
                size=size,
                n=n,
                response_format=response_format,
                timeout_s=timeout_s,
                extra_input=options["passthrough_prediction_input"],
            )
        if _is_bare_model_name(model):
            if not is_openai_compatible_one_step_image_model(model):
                raise LLMCallError(
                    reason=(
                        "OpenAI-compatible image model routing is ambiguous. "
                        "Use a provider/model prediction path such as "
                        "`doubao/doubao-seedream-4-0`, `qianfan/qwen-image`, "
                        "`openai/gpt-image-1`, or a supported one-step "
                        "`/images/generations` model such as `FLUX.1-Kontext-pro`. "
                        f"Current model: {model}"
                    )
                )
            return await _agenerate_openai_compatible_image(
                api_base=api_base,
                api_key=api_key,
                model=model,
                prompt=prompt,
                size=size,
                n=n,
                response_format=response_format,
                timeout_s=timeout_s,
                extra_body=options["passthrough_image_body"],
            )
        raise LLMCallError(reason="unsupported openai-compatible image model configuration")
    if runtime_provider in {"openai", "azure", "doubao", "xai"}:
        return await _agenerate_openai_compatible_image(
            api_base=api_base,
            api_key=api_key,
            model=model,
            prompt=prompt,
            size=size,
            n=n,
            response_format=response_format,
            timeout_s=timeout_s,
            extra_body=options["passthrough_image_body"],
        )

    response = await asyncio.wait_for(
        litellm.aimage_generation(**dict(call_kwargs)),
        timeout=timeout_s,
    )
    return ImageGenerationResult(
        model=model,
        prompt=prompt,
        images=_extract_images(response),
        raw_metadata={
            "response_type": type(response).__name__,
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
                "model DESCRIBE is an image description endpoint "
                "(requires an image_file input), not a text-to-image generation model. "
                "Use a text-to-image model such as gpt-image-1, gpt-4o-image-vip, "
                "FLUX.1-Kontext-pro, or a prediction-style model path like qianfan/qwen-image."
            )
        )

    call_kwargs = {
        "model": context.model,
        "prompt": str(prompt).strip(),
        "api_base": kwargs.pop("api_base", None) or None,
        "api_key": kwargs.pop("api_key", None) or context.api_key,
        "timeout": kwargs.pop("timeout", context.profile.timeout_s),
        "n": max(1, int(n or 1)),
        "size": size,
        "response_format": response_format,
    }
    endpoint_mode = kwargs.pop("endpoint_mode", None)
    explicit_prediction_input = kwargs.pop("prediction_input", None)
    if call_kwargs["api_base"] is None:
        from app.shared.infra.env_support import get_env

        call_kwargs["api_base"] = get_env("LLM_BASE_URL")
    runtime_provider = resolve_runtime_llm_provider(base_url=str(call_kwargs["api_base"] or ""))
    normalized_model = normalize_openai_compatible_image_model_name(
        str(call_kwargs["model"]),
        runtime_provider=runtime_provider,
    )
    if normalized_model:
        call_kwargs["model"] = normalized_model
    call_kwargs.update(build_litellm_provider_kwargs(str(call_kwargs["model"])))
    provider_options = _build_provider_image_options(
        model=str(call_kwargs["model"]),
        prompt=str(prompt).strip(),
        size=size,
        n=int(call_kwargs["n"]),
        response_format=response_format,
        kwargs=kwargs,
        explicit_prediction_input=explicit_prediction_input,
    )
    call_kwargs.update(kwargs)

    last_error: Exception | None = None
    call_started_at = time.monotonic()
    tracked_model = str(call_kwargs["model"])
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
                    result = await _dispatch_provider_image_request(
                        runtime_provider=runtime_provider,
                        call_kwargs=call_kwargs,
                        prompt=str(prompt).strip(),
                        size=size,
                        response_format=response_format,
                        timeout_s=request_timeout_s(context.profile.timeout_s),
                        endpoint_mode=endpoint_mode,
                        options=provider_options,
                    )
                    if response_format == "b64_json" and any(not image.b64_json and image.url for image in result.images):
                        result = ImageGenerationResult(
                            model=result.model,
                            prompt=result.prompt,
                            images=await _materialize_b64_images(
                                result.images,
                                timeout_s=request_timeout_s(context.profile.timeout_s),
                            ),
                            raw_metadata=dict(result.raw_metadata),
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
