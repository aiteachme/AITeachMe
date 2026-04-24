from __future__ import annotations

from pathlib import Path
import re

import yaml

from app.shared.infra.settings import (
    get_default_settings_values,
    get_project_settings,
    merge_default_settings,
    reset_project_settings_cache,
)
from app.shared.infra.settings.support import (
    detect_llm_provider_from_base_url,
    get_llm_provider_model_defaults,
    llm_provider_requires_api_key,
    resolve_runtime_llm_provider,
    split_provider_model_name,
    upgrade_legacy_settings_payload,
)
from app.shared.infra.settings.settings import Settings
from app.workflows.support.system.catalog import ENV_ENTRY_KEY_MAP, SETTINGS_CATALOG

SAMPLE_ENV_FILES = (
    ".env.sample",
    ".env.developer.sample",
)


def test_settings_model_uses_code_defaults_without_project_file(monkeypatch) -> None:
    monkeypatch.delenv("PROJECT_SETTINGS_PATH", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    reset_project_settings_cache()

    settings = get_project_settings()
    defaults = get_default_settings_values()

    assert settings.models.primary == defaults["models"]["primary"]
    assert settings.models.embedding == defaults["models"]["embedding"]
    assert settings.models.embedding_dim == defaults["models"]["embedding_dim"]
    assert settings.models.vision is defaults["models"]["vision"]
    assert settings.models.rerank is defaults["models"]["rerank"]
    assert settings.models.ocr is defaults["models"]["ocr"]
    assert settings.models.speech_to_text is defaults["models"]["speech_to_text"]
    assert settings.models.text_to_speech is defaults["models"]["text_to_speech"]
    assert settings.models.video_generation is defaults["models"]["video_generation"]
    assert settings.ingest.max_upload_size_mb == defaults["ingest"]["max_upload_size_mb"]
    assert settings.docgen.generate_cover_image == defaults["docgen"]["generate_cover_image"]
    assert "runtime" not in defaults
    assert "embedding" not in defaults


def test_detect_llm_provider_from_base_url_handles_major_providers() -> None:
    assert detect_llm_provider_from_base_url("https://api.openai.com/v1") == "openai"
    assert detect_llm_provider_from_base_url("https://api.anthropic.com") == "anthropic"
    assert detect_llm_provider_from_base_url("https://generativelanguage.googleapis.com") == "gemini"
    assert (
        detect_llm_provider_from_base_url("https://demo.openai.azure.com/openai/deployments/foo/chat/completions")
        == "azure"
    )
    assert detect_llm_provider_from_base_url("http://localhost:11434/v1") == "ollama"
    assert detect_llm_provider_from_base_url("http://localhost:9020/v1") == "vllm"
    assert detect_llm_provider_from_base_url("https://api.deepseek.com/v1") == "deepseek"
    assert detect_llm_provider_from_base_url("https://api.moonshot.cn/v1") == "kimi"
    assert detect_llm_provider_from_base_url("https://open.bigmodel.cn/api/paas/v4") == "glm"
    assert detect_llm_provider_from_base_url("https://api.minimaxi.com/anthropic/v1") == "minimax"
    assert detect_llm_provider_from_base_url("https://api.siliconflow.cn/v1") == "siliconflow"
    assert detect_llm_provider_from_base_url("https://ark.cn-beijing.volces.com/api/v3") == "doubao"
    assert (
        detect_llm_provider_from_base_url("https://bedrock-runtime.us-east-1.amazonaws.com")
        == "bedrock"
    )
    assert (
        detect_llm_provider_from_base_url("https://dashscope.aliyuncs.com/compatible-mode/v1")
        == "qwen"
    )


def test_resolve_runtime_llm_provider_prefers_explicit_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")

    assert resolve_runtime_llm_provider() == "anthropic"


def test_provider_defaults_switch_by_provider() -> None:
    anthropic_defaults = get_llm_provider_model_defaults("anthropic")
    gemini_defaults = get_llm_provider_model_defaults("gemini")
    azure_defaults = get_llm_provider_model_defaults("azure")
    vllm_defaults = get_llm_provider_model_defaults("vllm")
    ollama_defaults = get_llm_provider_model_defaults("ollama")
    deepseek_defaults = get_llm_provider_model_defaults("deepseek")
    minimax_defaults = get_llm_provider_model_defaults("minimax")
    bedrock_defaults = get_llm_provider_model_defaults("bedrock")

    assert anthropic_defaults["reason"] == "claude-sonnet-4-6"
    assert anthropic_defaults["primary"] == "claude-haiku-4-5"
    assert anthropic_defaults["embedding"] is None
    assert anthropic_defaults["rerank"] is None
    assert anthropic_defaults["image_generation"] is None
    assert gemini_defaults["primary"] == "gemini-2.5-flash"
    assert gemini_defaults["light"] == "gemini-2.5-flash-lite"
    assert gemini_defaults["embedding"] == "text-embedding-004"
    assert azure_defaults["primary"] == "gpt-4o-mini"
    assert vllm_defaults["primary"] == "Qwen/Qwen2.5-7B-Instruct"
    assert vllm_defaults["embedding"] is None
    assert ollama_defaults["primary"] == "qwen2.5"
    assert ollama_defaults["embedding"] is None
    assert deepseek_defaults["primary"] == "deepseek-chat"
    assert minimax_defaults["primary"] == "MiniMax-M2.5-highspeed"
    assert bedrock_defaults["reason"] == "anthropic.claude-sonnet-4-6"
    assert bedrock_defaults["primary"].startswith("anthropic.claude-haiku-4-5")


def test_provider_defaults_allow_optional_embedding_models(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    reset_project_settings_cache()

    settings = get_project_settings()

    assert settings.models.primary.startswith("claude-")
    assert settings.models.embedding is None


def test_split_provider_model_name_preserves_vendor_model_paths() -> None:
    assert split_provider_model_name("deepseek-ai/DeepSeek-V3.2") == (None, "deepseek-ai/DeepSeek-V3.2")
    assert split_provider_model_name("Qwen/Qwen2.5-7B-Instruct") == (None, "Qwen/Qwen2.5-7B-Instruct")
    assert split_provider_model_name("openai/gpt-4o-mini") == ("openai", "gpt-4o-mini")


def test_llm_provider_requires_api_key_handles_local_gateways() -> None:
    assert llm_provider_requires_api_key("anthropic", base_url="https://api.anthropic.com") is True
    assert llm_provider_requires_api_key("ollama", base_url="http://localhost:11434/v1") is False
    assert llm_provider_requires_api_key("vllm", base_url="http://127.0.0.1:9020/v1") is False
    assert llm_provider_requires_api_key("openai_compatible", base_url="http://localhost:1234/v1") is False


def test_settings_support_optional_external_override_file(
    monkeypatch, tmp_path: Path
) -> None:
    override_path = tmp_path / "settings.override.yaml"
    override_path.write_text(
        "\n".join(
            [
                "models:",
                "  primary: qwen-flash",
                "  embedding: text-embedding-v4",
                "  embedding_dim: 1024",
                "planner:",
                '  sprint:',
                '    target_length: "3000-10000字"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("PROJECT_SETTINGS_PATH", str(override_path))
    reset_project_settings_cache()

    settings = get_project_settings()

    assert settings.models.primary == "qwen-flash"
    assert settings.models.embedding == "text-embedding-v4"
    assert settings.models.embedding_dim == 1024
    assert settings.embedding_dim == 1024
    assert settings.planner.sprint.target_length == "3000-10000字"


def test_merge_default_settings_recursively_merges_nested_sections() -> None:
    payload = merge_default_settings(
        {"planner": {"sprint": {"target_length": "custom-length"}}}
    )

    assert payload["planner"]["sprint"]["target_length"] == "custom-length"
    assert payload["planner"]["sprint"]["min_chapters"] == 4
    assert payload["planner"]["systematic"]["max_chapters"] == 12


def test_settings_model_validate_accepts_partial_external_override() -> None:
    payload = yaml.safe_load(
        "\n".join(
            [
                "models:",
                "  primary: qwen-flash",
                "planner:",
                '  systematic:',
                '    target_length: "10000-30000字"',
            ]
        )
    ) or {}

    settings = Settings.model_validate(payload)
    defaults = get_default_settings_values()

    assert settings.models.primary == "qwen-flash"
    assert settings.models.embedding == defaults["models"]["embedding"]
    assert settings.planner.systematic.target_length == "10000-30000字"
    assert settings.planner.systematic.min_chapters == defaults["planner"]["systematic"]["min_chapters"]


def test_settings_embedding_dim_can_be_explicitly_overridden_for_unknown_model() -> None:
    settings = Settings.model_validate(
        {
            "models": {
                "embedding": "custom-embedding-model",
                "embedding_dim": 2048,
            }
        }
    )

    assert settings.models.embedding == "custom-embedding-model"
    assert settings.models.embedding_dim == 2048
    assert settings.embedding_dim == 2048


def test_settings_upgrade_legacy_extract_and_rerank_keys() -> None:
    upgraded = upgrade_legacy_settings_payload(
        {
            "models": {"extract": "legacy-extract-model"},
            "rag": {"rerank_model": "qwen3-reranker-4b"},
        }
    )

    assert upgraded["models"]["light"] == "legacy-extract-model"
    assert "extract" not in upgraded["models"]
    assert upgraded["models"]["rerank"] == "qwen3-reranker-4b"
    assert "rerank_model" not in upgraded["rag"]


def test_env_samples_cover_exposed_env_keys() -> None:
    exposed_env_names = set(ENV_ENTRY_KEY_MAP.values())
    project_root = Path(__file__).resolve().parents[2]

    sample_names: set[str] = set()
    for sample_name in SAMPLE_ENV_FILES:
        env_sample_text = project_root.joinpath(sample_name).read_text(encoding="utf-8")
        sample_names.update(
            re.findall(r"^(?:#\s*)?([A-Z][A-Z0-9_]+)=", env_sample_text, re.MULTILINE)
        )

    assert sorted(exposed_env_names - sample_names) == []


def test_user_env_sample_vars_are_all_exposed_in_settings_catalog() -> None:
    project_root = Path(__file__).resolve().parents[2]
    env_sample_text = project_root.joinpath(".env.sample").read_text(encoding="utf-8")
    sample_names = set(
        re.findall(r"^(?:#\s*)?([A-Z][A-Z0-9_]+)=", env_sample_text, re.MULTILINE)
    )

    assert sorted(sample_names - set(ENV_ENTRY_KEY_MAP.values())) == []


def test_settings_catalog_does_not_repeat_entry_keys() -> None:
    keys = [
        entry.key
        for section in SETTINGS_CATALOG
        for entry in section.entries
    ]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})

    assert duplicates == []


def test_minimal_env_sample_keeps_local_bootstrap_keys() -> None:
    env_sample_text = Path(__file__).resolve().parents[2].joinpath(".env.sample").read_text(
        encoding="utf-8"
    )

    assert "LLM_API_KEY=" in env_sample_text
    assert "LLM_BASE_URL=" in env_sample_text
