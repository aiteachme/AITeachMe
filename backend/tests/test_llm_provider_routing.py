from __future__ import annotations

from app.shared.infra.llm_support.image import (
    _metadata_without_image_payload,
    _build_provider_image_options,
    _build_prediction_image_input,
    _extract_bedrock_nova_images,
    _extract_gemini_images,
    _extract_imagen_native_images,
    _extract_openrouter_images,
    _extract_qwen_native_images,
    _extract_vertex_imagen_images,
    GeneratedImage,
    ImageGenerationResult,
    _should_use_prediction_endpoint,
)
from app.shared.infra.llm_support.common import build_completion_context, build_litellm_provider_kwargs
from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.shared.infra.settings import reset_project_settings_cache
from app.shared.infra.settings.support import normalize_openai_compatible_image_model_name


def test_build_provider_kwargs_for_anthropic(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("LLM_API_VERSION", raising=False)

    kwargs = build_litellm_provider_kwargs("claude-3-5-sonnet-latest")

    assert kwargs == {"custom_llm_provider": "anthropic"}


def test_build_provider_kwargs_for_gemini(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("LLM_API_VERSION", raising=False)

    kwargs = build_litellm_provider_kwargs("gemini-2.5-flash")

    assert kwargs == {"custom_llm_provider": "gemini"}


def test_build_provider_kwargs_for_azure_includes_api_version(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "azure")
    monkeypatch.setenv("LLM_API_VERSION", "2024-10-21")

    kwargs = build_litellm_provider_kwargs("gpt-4o-mini")

    assert kwargs == {
        "custom_llm_provider": "azure",
        "api_version": "2024-10-21",
    }


def test_build_provider_kwargs_for_ollama(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("LLM_API_VERSION", raising=False)

    kwargs = build_litellm_provider_kwargs("qwen2.5:7b")

    assert kwargs == {"custom_llm_provider": "ollama"}


def test_build_provider_kwargs_for_minimax_routes_to_anthropic(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    monkeypatch.delenv("LLM_API_VERSION", raising=False)

    kwargs = build_litellm_provider_kwargs("MiniMax-M2.5-highspeed")

    assert kwargs == {"custom_llm_provider": "anthropic"}


def test_build_provider_kwargs_for_openai_compatible_vendor_routes(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("LLM_API_VERSION", raising=False)

    deepseek_kwargs = build_litellm_provider_kwargs("deepseek-chat")
    siliconflow_kwargs = build_litellm_provider_kwargs("deepseek-ai/DeepSeek-V3.2")

    assert deepseek_kwargs == {"custom_llm_provider": "openai"}
    assert siliconflow_kwargs == {"custom_llm_provider": "openai"}


def test_build_provider_kwargs_prefers_prefixed_model(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_VERSION", "2024-10-21")

    kwargs = build_litellm_provider_kwargs("azure/my-deployment")

    assert kwargs == {
        "custom_llm_provider": "azure",
        "api_version": "2024-10-21",
    }


def test_build_provider_kwargs_keeps_openrouter_route_for_prefixed_models(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("LLM_API_VERSION", raising=False)

    kwargs = build_litellm_provider_kwargs("openai/gpt-4o-mini")

    assert kwargs == {"custom_llm_provider": "openrouter"}


def test_build_completion_context_allows_local_provider_without_api_key(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_API_KEY", "")
    reset_project_settings_cache()

    context = build_completion_context(call_purpose=LLMCallPurpose.CHAT)

    assert context.api_key is None
    assert context.model == "qwen2.5"


def test_normalize_openai_compatible_image_model_name_for_prediction_models() -> None:
    assert normalize_openai_compatible_image_model_name(
        "doubao-seedream-4-0",
        runtime_provider="openai_compatible",
    ) == "doubao/doubao-seedream-4-0"
    assert normalize_openai_compatible_image_model_name(
        "qwen-image",
        runtime_provider="openai_compatible",
    ) == "qianfan/qwen-image"


def test_normalize_openai_compatible_image_model_name_keeps_one_step_models() -> None:
    assert normalize_openai_compatible_image_model_name(
        "FLUX.1-Kontext-pro",
        runtime_provider="openai_compatible",
    ) == "FLUX.1-Kontext-pro"


def test_normalize_openai_compatible_image_model_name_skips_non_compatible_runtimes() -> None:
    assert normalize_openai_compatible_image_model_name(
        "doubao-seedream-4-0",
        runtime_provider="doubao",
    ) == "doubao-seedream-4-0"


def test_build_prediction_image_input_uses_prediction_style_response_format() -> None:
    payload = _build_prediction_image_input(
        prompt="demo",
        size="2K",
        n=1,
        response_format="b64_json",
    )

    assert payload == {
        "prompt": "demo",
        "size": "2K",
        "n": 1,
        "response_format": "base64_json",
    }


def test_should_use_prediction_endpoint_for_bare_model_with_prediction_inputs() -> None:
    assert _should_use_prediction_endpoint(
        model="imagen-3.0-generate-002",
        endpoint_mode=None,
        prediction_input={"numberOfImages": 1},
    )


def test_should_use_prediction_endpoint_respects_explicit_endpoint_mode() -> None:
    assert _should_use_prediction_endpoint(
        model="imagen-3.0-generate-002",
        endpoint_mode="prediction",
        prediction_input={},
    )
    assert not _should_use_prediction_endpoint(
        model="FLUX.1-Kontext-pro",
        endpoint_mode="images",
        prediction_input={"numberOfImages": 1},
    )


def test_extract_openrouter_images_parses_data_urls() -> None:
    images = _extract_openrouter_images(
        {
            "choices": [
                {
                    "message": {
                        "images": [
                            {
                                "image_url": {
                                    "url": "data:image/png;base64,QUJD",
                                }
                            }
                        ]
                    }
                }
            ]
        }
    )

    assert len(images) == 1
    assert images[0].b64_json == "QUJD"
    assert images[0].mime_type == "image/png"


def test_extract_qwen_native_images_reads_message_content_images() -> None:
    images = _extract_qwen_native_images(
        {
            "output": {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"image": "https://example.com/qwen.png"},
                            ]
                        }
                    }
                ]
            }
        }
    )

    assert len(images) == 1
    assert images[0].url == "https://example.com/qwen.png"


def test_extract_gemini_and_imagen_images_read_native_payloads() -> None:
    gemini_images = _extract_gemini_images(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": "R0VNSU5J",
                                }
                            }
                        ]
                    }
                }
            ]
        }
    )
    imagen_images = _extract_imagen_native_images(
        {
            "generatedImages": [
                {
                    "image": {
                        "imageBytes": "SU1BR0VO",
                    }
                }
            ]
        }
    )

    assert gemini_images[0].b64_json == "R0VNSU5J"
    assert imagen_images[0].b64_json == "SU1BR0VO"


def test_extract_vertex_and_bedrock_images_read_native_payloads() -> None:
    vertex_images = _extract_vertex_imagen_images(
        {
            "predictions": [
                {
                    "bytesBase64Encoded": "VkVSVEVY",
                    "mimeType": "image/png",
                }
            ]
        }
    )
    bedrock_images = _extract_bedrock_nova_images(
        {
            "images": ["QkVEUk9DSw=="],
        }
    )

    assert vertex_images[0].b64_json == "VkVSVEVY"
    assert bedrock_images[0].b64_json == "QkVEUk9DSw=="


def test_build_provider_image_options_splits_bedrock_text_and_generation_fields() -> None:
    options = _build_provider_image_options(
        model="amazon.nova-canvas-v1:0",
        prompt="demo",
        size="1536x1024",
        n=2,
        response_format="b64_json",
        kwargs={
            "negativeText": "bad",
            "style": "photographic",
            "seed": 123,
            "cfgScale": 7.5,
            "quality": "premium",
        },
        explicit_prediction_input=None,
    )

    assert options["bedrock_text_to_image_params"] == {
        "negativeText": "bad",
        "style": "photographic",
    }
    assert options["bedrock_image_generation_config"] == {
        "seed": 123,
        "cfgScale": 7.5,
        "quality": "premium",
    }


def test_metadata_without_image_payload_keeps_full_revised_prompt() -> None:
    revised_prompt = "x" * 400
    payload = _metadata_without_image_payload(
        ImageGenerationResult(
            model="demo-model",
            prompt="hello",
            images=[GeneratedImage(revised_prompt=revised_prompt)],
        )
    )

    assert payload["images"][0]["revised_prompt"] == revised_prompt
