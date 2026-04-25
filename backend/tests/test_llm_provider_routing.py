from __future__ import annotations

from app.shared.infra.llm_support.common import (
    build_completion_context,
    build_litellm_provider_kwargs,
    capture_llm_runtime_snapshot,
    use_llm_runtime_snapshot,
)
from app.shared.infra.llm_support.image import (
    GeneratedImage,
    ImageGenerationResult,
    _build_litellm_image_kwargs,
    _extract_images,
    _is_openai_gpt_image_model,
    _metadata_without_image_payload,
    _resolve_litellm_image_model,
)
from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.shared.infra.settings import (
    clear_system_settings_override,
    reset_project_settings_cache,
    set_system_settings_override,
)
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


def test_llm_runtime_snapshot_freezes_model_and_connection(monkeypatch) -> None:
    clear_system_settings_override()
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://old-gateway.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "old-key")
    set_system_settings_override({"models": {"primary": "old-model"}})
    snapshot = capture_llm_runtime_snapshot()

    monkeypatch.setenv("LLM_BASE_URL", "https://new-gateway.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "new-key")
    set_system_settings_override({"models": {"primary": "new-model"}})

    try:
        with use_llm_runtime_snapshot(snapshot):
            context = build_completion_context(call_purpose=LLMCallPurpose.CHAT)

        assert context.model == "old-model"
        assert context.base_url == "https://old-gateway.example/v1"
        assert context.api_key == "old-key"
    finally:
        clear_system_settings_override()


def test_normalize_openai_compatible_image_model_name_uses_litellm_openai_route() -> None:
    assert normalize_openai_compatible_image_model_name(
        "doubao-seedream-4-0",
        runtime_provider="openai_compatible",
    ) == "openai/doubao-seedream-4-0"
    assert normalize_openai_compatible_image_model_name(
        "qwen-image",
        runtime_provider="openai_compatible",
    ) == "openai/qwen-image"
    assert normalize_openai_compatible_image_model_name(
        "FLUX.1-Kontext-pro",
        runtime_provider="openai_compatible",
    ) == "openai/FLUX.1-Kontext-pro"


def test_normalize_openai_compatible_image_model_name_keeps_prefixed_models() -> None:
    assert normalize_openai_compatible_image_model_name(
        "openrouter/google/gemini-2.5-flash-image",
        runtime_provider="openai_compatible",
    ) == "openrouter/google/gemini-2.5-flash-image"


def test_normalize_openai_compatible_image_model_name_skips_non_compatible_runtimes() -> None:
    assert normalize_openai_compatible_image_model_name(
        "doubao-seedream-4-0",
        runtime_provider="doubao",
    ) == "doubao-seedream-4-0"


def test_resolve_litellm_image_model_routes_by_runtime_provider() -> None:
    assert _resolve_litellm_image_model("gpt-image-1", runtime_provider="openai") == "gpt-image-1"
    assert _resolve_litellm_image_model("gpt-image-1", runtime_provider="openai_compatible") == "openai/gpt-image-1"
    assert (
        _resolve_litellm_image_model("google/gemini-2.5-flash-image", runtime_provider="openrouter")
        == "openrouter/google/gemini-2.5-flash-image"
    )
    assert (
        _resolve_litellm_image_model("openrouter/google/gemini-2.5-flash-image", runtime_provider="openai")
        == "openrouter/google/gemini-2.5-flash-image"
    )
    assert _resolve_litellm_image_model("fal-ai/flux/dev", runtime_provider="openai_compatible") == "fal-ai/flux/dev"
    assert _resolve_litellm_image_model("doubao/doubao-seedream-4-0", runtime_provider="openai_compatible") == "doubao/doubao-seedream-4-0"
    assert _resolve_litellm_image_model("imagegeneration@006", runtime_provider="vertex_ai") == "vertex_ai/imagegeneration@006"


def test_build_litellm_image_kwargs_drops_response_format_for_gpt_image_models() -> None:
    kwargs = _build_litellm_image_kwargs(
        model="gpt-image-1",
        prompt="demo",
        runtime_provider="openai_compatible",
        api_base="https://gateway.example.com/v1",
        api_key="sk-test",
        timeout_s=30,
        size="1024x1024",
        n=1,
        response_format="b64_json",
        extra_kwargs={"quality": "high"},
    )

    assert kwargs["model"] == "openai/gpt-image-1"
    assert kwargs["api_base"] == "https://gateway.example.com/v1"
    assert kwargs["api_key"] == "sk-test"
    assert kwargs["quality"] == "high"
    assert "response_format" not in kwargs
    assert _is_openai_gpt_image_model(kwargs["model"])


def test_build_litellm_image_kwargs_keeps_provider_specific_fields() -> None:
    kwargs = _build_litellm_image_kwargs(
        model="dall-e-3",
        prompt="demo",
        runtime_provider="openai",
        api_base=None,
        api_key=None,
        timeout_s=30,
        size="1024x1024",
        n=1,
        response_format="b64_json",
        extra_kwargs={"style": "vivid", "background": None},
    )

    assert kwargs["model"] == "dall-e-3"
    assert kwargs["response_format"] == "b64_json"
    assert kwargs["style"] == "vivid"
    assert "background" not in kwargs


def test_extract_images_reads_litellm_data_and_chat_image_payloads() -> None:
    images = _extract_images(
        {
            "data": [
                {
                    "b64_json": "T1BFTkFJ",
                    "revised_prompt": "clean prompt",
                    "mime_type": "image/png",
                }
            ],
            "choices": [
                {
                    "message": {
                        "images": [
                            {
                                "imageUrl": {
                                    "url": "data:image/png;base64,T1BFTlJPVVRFUg==",
                                }
                            }
                        ]
                    }
                }
            ],
        }
    )

    assert len(images) == 2
    assert images[0].b64_json == "T1BFTkFJ"
    assert images[0].revised_prompt == "clean prompt"
    assert images[1].b64_json == "T1BFTlJPVVRFUg=="
    assert images[1].mime_type == "image/png"


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
