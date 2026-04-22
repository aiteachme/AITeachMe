"""Helpers for settings overrides, provider detection, and retriever profiles."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

EMBEDDING_DIM_BY_MODEL: dict[str, int] = {
    "text-embedding-v4": 1024,
    "text-embedding-v3": 1536,
    "text-embedding-v2": 1536,
    "text-embedding-ada-002": 1536,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "BAAI/bge-large-zh-v1.5": 1024,
    "BAAI/bge-m3": 1024,
    "qwen3-embedding-8b": 4096,
    "qwen3-embedding-0.6b": 1024,
}
DEFAULT_EMBEDDING_DIM = 1536
PROJECT_SETTINGS_ENV_NAME = "PROJECT_SETTINGS_PATH"
PROJECT_SETTINGS_SOURCE_LABEL = "code defaults only"
LLM_PROVIDER_ENV_NAME = "LLM_PROVIDER"
LLM_API_VERSION_ENV_NAME = "LLM_API_VERSION"
DEFAULT_RETRIEVER_FALLBACK = "duckduckgo"
LLM_PROVIDER_ALIASES: dict[str, str] = {
    "openai": "openai",
    "openai_compatible": "openai_compatible",
    "openai-compatible": "openai_compatible",
    "compatible": "openai_compatible",
    "vllm": "vllm",
    "vllm_openai": "vllm",
    "vllm-openai": "vllm",
    "qwen": "qwen",
    "dashscope": "qwen",
    "deepseek": "deepseek",
    "kimi": "kimi",
    "moonshot": "kimi",
    "moonshotai": "kimi",
    "glm": "glm",
    "zhipu": "glm",
    "zhipuai": "glm",
    "bigmodel": "glm",
    "azure": "azure",
    "azure_openai": "azure",
    "azure-openai": "azure",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "minimax": "minimax",
    "gemini": "gemini",
    "google": "gemini",
    "google_ai": "gemini",
    "google-ai": "gemini",
    "google_ai_studio": "gemini",
    "google-ai-studio": "gemini",
    "vertex": "vertex_ai",
    "vertexai": "vertex_ai",
    "vertex_ai": "vertex_ai",
    "openrouter": "openrouter",
    "ollama": "ollama",
    "siliconflow": "siliconflow",
    "doubao": "doubao",
    "ark": "doubao",
    "xai": "xai",
    "grok": "xai",
    "groq": "groq",
    "mistral": "mistral",
    "bedrock": "bedrock",
    "aws_bedrock": "bedrock",
    "aws-bedrock": "bedrock",
    "amazon_bedrock": "bedrock",
    "amazon-bedrock": "bedrock",
}
LLM_CANONICAL_PROVIDERS: frozenset[str] = frozenset(
    {
        "openai",
        "openai_compatible",
        "vllm",
        "qwen",
        "deepseek",
        "kimi",
        "glm",
        "azure",
        "anthropic",
        "minimax",
        "gemini",
        "vertex_ai",
        "openrouter",
        "ollama",
        "siliconflow",
        "doubao",
        "xai",
        "groq",
        "mistral",
        "bedrock",
    }
)
LLM_MODEL_PREFIX_PROVIDERS: frozenset[str] = frozenset(
    {
        "openai",
        "openai_compatible",
        "vllm",
        "azure",
        "anthropic",
        "gemini",
        "vertex_ai",
        "openrouter",
        "ollama",
        "xai",
        "groq",
        "mistral",
        "bedrock",
    }
)
LITELLM_PROVIDER_BY_RUNTIME_PROVIDER: dict[str, str] = {
    "openai": "openai",
    "openai_compatible": "openai",
    "vllm": "openai",
    "qwen": "openai",
    "deepseek": "openai",
    "kimi": "openai",
    "glm": "openai",
    "siliconflow": "openai",
    "doubao": "openai",
    "azure": "azure",
    "anthropic": "anthropic",
    "minimax": "anthropic",
    "gemini": "gemini",
    "vertex_ai": "gemini",
    "openrouter": "openrouter",
    "ollama": "ollama",
    "xai": "xai",
    "groq": "groq",
    "mistral": "mistral",
    "bedrock": "bedrock",
}
LLM_PROVIDER_MODEL_DEFAULTS: dict[str, dict[str, Any]] = {
    # These are only first-run defaults. Users can still override any
    # models.reason / primary / light / extract value from the settings UI.
    # We bias primary / light toward lower-latency models when a provider
    # offers a clear speed-first option.
    #
    # Default path for OpenAI-compatible gateways such as DashScope compatible
    # mode, LiteLLM Gateway, vLLM, LM Studio, Ollama OpenAI mode, etc.
    "openai_compatible": {
        "reason": "qwen-max",
        "primary": "qwen-flash",
        "light": "qwen-flash",
        "extract": None,
        "ocr": None,
        "embedding": "text-embedding-v3",
        "image_generation": None,
    },
    "vllm": {
        "reason": "Qwen/Qwen2.5-7B-Instruct",
        "primary": "Qwen/Qwen2.5-7B-Instruct",
        "light": "Qwen/Qwen2.5-7B-Instruct",
        "extract": None,
        "ocr": None,
        "embedding": None,
        "image_generation": None,
    },
    "ollama": {
        "reason": "qwen2.5",
        "primary": "qwen2.5",
        "light": "qwen2.5",
        "extract": None,
        "ocr": None,
        "embedding": None,
        "image_generation": None,
    },
    "qwen": {
        "reason": "qwen-max",
        "primary": "qwen-flash",
        "light": "qwen-flash",
        "extract": None,
        "ocr": None,
        "embedding": "text-embedding-v4",
        "image_generation": None,
    },
    "deepseek": {
        "reason": "deepseek-reasoner",
        "primary": "deepseek-chat",
        "light": "deepseek-chat",
        "extract": None,
        "ocr": None,
        "embedding": None,
        "image_generation": None,
    },
    "kimi": {
        "reason": "kimi-k2-thinking",
        "primary": "kimi-k2.5",
        "light": "kimi-k2-turbo-preview",
        "extract": None,
        "ocr": None,
        "embedding": None,
        "image_generation": None,
    },
    "glm": {
        "reason": "glm-5.1",
        "primary": "glm-4.7-flash",
        "light": "glm-4.7-flash",
        "extract": None,
        "ocr": None,
        "embedding": None,
        "image_generation": None,
    },
    "openai": {
        "reason": "gpt-4o",
        "primary": "gpt-4o-mini",
        "light": "gpt-4o-mini",
        "extract": None,
        "ocr": None,
        "embedding": "text-embedding-3-small",
        "image_generation": "gpt-image-1",
    },
    # Azure OpenAI usually requires deployment names in `models.*`. We still
    # provide OpenAI-style defaults as sane placeholders for first-run setup.
    "azure": {
        "reason": "gpt-4o",
        "primary": "gpt-4o-mini",
        "light": "gpt-4o-mini",
        "extract": None,
        "ocr": None,
        "embedding": "text-embedding-3-small",
        "image_generation": "gpt-image-1",
    },
    "anthropic": {
        "reason": "claude-sonnet-4-6",
        "primary": "claude-haiku-4-5",
        "light": "claude-haiku-4-5",
        "extract": None,
        "ocr": None,
        "embedding": None,
        "image_generation": None,
    },
    "minimax": {
        "reason": "MiniMax-M2.5",
        "primary": "MiniMax-M2.5-highspeed",
        "light": "MiniMax-M2.1-highspeed",
        "extract": None,
        "ocr": None,
        "embedding": None,
        "image_generation": None,
    },
    "gemini": {
        "reason": "gemini-2.5-flash",
        "primary": "gemini-2.5-flash",
        "light": "gemini-2.5-flash-lite",
        "extract": None,
        "ocr": None,
        "embedding": "text-embedding-004",
        "image_generation": None,
    },
    "vertex_ai": {
        "reason": "gemini-2.5-flash",
        "primary": "gemini-2.5-flash",
        "light": "gemini-2.5-flash-lite",
        "extract": None,
        "ocr": None,
        "embedding": "text-embedding-004",
        "image_generation": None,
    },
    "siliconflow": {
        "reason": "deepseek-ai/DeepSeek-R1",
        "primary": "deepseek-ai/DeepSeek-V3.2",
        "light": "Qwen/Qwen2.5-7B-Instruct",
        "extract": None,
        "ocr": None,
        "embedding": None,
        "image_generation": None,
    },
    "doubao": {
        "reason": "doubao-seed-2-0-pro-260215",
        "primary": "doubao-seed-2-0-pro-260215",
        "light": "doubao-seed-2-0-lite-260215",
        "extract": None,
        "ocr": None,
        "embedding": None,
        "image_generation": None,
    },
    "openrouter": {
        "reason": "openai/gpt-4o-mini",
        "primary": "openai/gpt-4o-mini",
        "light": "openai/gpt-4o-mini",
        "extract": None,
        "ocr": None,
        "embedding": None,
        "image_generation": None,
    },
    "xai": {
        "reason": "grok-4",
        "primary": "grok-3-mini",
        "light": "grok-3-mini",
        "extract": None,
        "ocr": None,
        "embedding": None,
        "image_generation": None,
    },
    "groq": {
        "reason": "llama-3.3-70b-versatile",
        "primary": "llama-3.1-8b-instant",
        "light": "llama-3.1-8b-instant",
        "extract": None,
        "ocr": None,
        "embedding": None,
        "image_generation": None,
    },
    "mistral": {
        "reason": "mistral-small-latest",
        "primary": "mistral-small-latest",
        "light": "mistral-small-latest",
        "extract": None,
        "ocr": None,
        "embedding": None,
        "image_generation": None,
    },
    "bedrock": {
        "reason": "anthropic.claude-sonnet-4-6",
        "primary": "anthropic.claude-haiku-4-5-20251001-v1:0",
        "light": "anthropic.claude-haiku-4-5-20251001-v1:0",
        "extract": None,
        "ocr": None,
        "embedding": None,
        "image_generation": None,
    },
}
RETRIEVER_ALIASES: dict[str, str] = {
    "ddg": "duckduckgo",
    "rag": "local_rag",
    "oiwiki": "oi_wiki",
    "oi-wiki": "oi_wiki",
    "jina": "jina_search",
    "baidu_ai": "baidu_ai_search",
    "baidu_search": "baidu_ai_search",
    "google": "google_cse",
    "google_custom_search": "google_cse",
    "mcp": "mcp_search",
    "mcp_research": "mcp_search",
    "openrouter": "openrouter_search",
    "google_serp": "serper",
    "google_scholar": "serper",
    "serper_scholar": "serper",
    "searx": "searxng",
    "wiki": "wikipedia",
    "zh_wiki": "zh_wikipedia",
    "wikipedia_zh": "zh_wikipedia",
    "zh_wikibook": "zh_wikibooks",
    "wikibooks_zh": "zh_wikibooks",
    "wikiversity_zh": "zh_wikiversity",
    "wiktionary_zh": "zh_wiktionary",
}
ZH_EDU_RETRIEVERS: list[str] = [
    "zh_wikibooks",
    "zh_wikiversity",
    "zh_wikipedia",
    "zh_wiktionary",
    "oi_wiki",
]
DEFAULT_RETRIEVERS: list[str] = [
    "local_rag",
    "searxng",
    "tavily",
    "jina_search",
    "google_cse",
    "searchapi",
    "serpapi",
    "bocha",
    "brave",
    "exa",
    "bing",
    "perplexity",
    "serper",
    "openrouter_search",
    "baidu_ai_search",
    "wikipedia",
    "baidu_baike",
    "zhihu",
    "arxiv",
    "semantic_scholar",
    "pubmed_central",
    "mcp_search",
    "duckduckgo",
]
DOCGEN_RETRIEVERS: list[str] = [
    "local_rag",
    *ZH_EDU_RETRIEVERS,
    *[name for name in DEFAULT_RETRIEVERS if name not in {"local_rag", *ZH_EDU_RETRIEVERS}],
]
ZH_MATH_RETRIEVERS: list[str] = [
    "local_rag",
    "zh_wikibooks",
    "zh_wikiversity",
    "zh_wikipedia",
    "oi_wiki",
    "zh_wiktionary",
    "arxiv",
    "semantic_scholar",
    "duckduckgo",
]
DEFAULT_RETRIEVER_PROFILES: dict[str, list[str]] = {
    "planner_fast": list(DEFAULT_RETRIEVERS),
    "planner_grounding": list(DOCGEN_RETRIEVERS),
    "docgen_balanced": list(DOCGEN_RETRIEVERS),
    "docgen_sprint": list(DOCGEN_RETRIEVERS),
    "docgen_academic": list(DOCGEN_RETRIEVERS),
    "docgen_systematic": list(DOCGEN_RETRIEVERS),
    "docgen_zh_edu": [
        "local_rag",
        *ZH_EDU_RETRIEVERS,
        "duckduckgo",
    ],
    "docgen_zh_math": list(ZH_MATH_RETRIEVERS),
}
RETRIEVER_PROFILES = DEFAULT_RETRIEVER_PROFILES


def normalize_llm_provider_name(name: str | None) -> str | None:
    normalized = (name or "").strip().lower()
    if not normalized:
        return None
    return LLM_PROVIDER_ALIASES.get(normalized, normalized)


def split_provider_model_name(model: str | None) -> tuple[str | None, str]:
    normalized = (model or "").strip()
    if not normalized or "/" not in normalized:
        return None, normalized
    provider_name, model_name = normalized.split("/", 1)
    normalized_provider = normalize_llm_provider_name(provider_name)
    if normalized_provider not in LLM_MODEL_PREFIX_PROVIDERS:
        return None, normalized
    return normalized_provider, model_name.strip()


def detect_llm_provider_from_base_url(base_url: str | None) -> str | None:
    normalized = (base_url or "").strip()
    if not normalized:
        return None
    try:
        parsed = urlparse(normalized)
    except Exception:
        parsed = None
    host = (parsed.hostname or "").lower() if parsed is not None else normalized.lower()
    path = (parsed.path or "").lower() if parsed is not None else ""
    text = f"{host}{path}"

    if any(marker in text for marker in ("anthropic.com",)):
        return "anthropic"
    if any(marker in text for marker in ("minimaxi.com", "minimax.io")):
        return "minimax"
    if any(marker in text for marker in ("generativelanguage.googleapis.com", "ai.google.dev")):
        return "gemini"
    if any(marker in text for marker in ("aiplatform.googleapis.com", "vertex.googleapis.com")):
        return "vertex_ai"
    if any(marker in text for marker in ("openai.azure.com", ".inference.ai.azure.com", "azure.com/openai")):
        return "azure"
    if "api.deepseek.com" in text:
        return "deepseek"
    if any(marker in text for marker in ("moonshot.cn", "moonshot.ai")):
        return "kimi"
    if any(marker in text for marker in ("bigmodel.cn", "api.z.ai")):
        return "glm"
    if "dashscope.aliyuncs.com" in text:
        return "qwen"
    if "siliconflow.cn" in text:
        return "siliconflow"
    if any(marker in text for marker in ("ark.cn-beijing.volces.com", "volces.com/api/v3")):
        return "doubao"
    if "vllm" in text:
        return "vllm"
    if "localhost:8000" in normalized.lower() or "127.0.0.1:8000" in normalized.lower():
        return "vllm"
    if "api.openai.com" in text:
        return "openai"
    if "openrouter.ai" in text:
        return "openrouter"
    if "api.x.ai" in text:
        return "xai"
    if "api.groq.com" in text:
        return "groq"
    if "api.mistral.ai" in text:
        return "mistral"
    if "bedrock-runtime." in text or "bedrock-runtime-" in text:
        return "bedrock"
    if "localhost:11434" in normalized.lower() or "127.0.0.1:11434" in normalized.lower():
        return "ollama"
    return "openai_compatible"


def resolve_runtime_llm_provider(
    *,
    explicit_provider: str | None = None,
    base_url: str | None = None,
) -> str:
    from app.shared.infra.env_support import get_env

    configured_provider = normalize_llm_provider_name(
        explicit_provider or get_env(LLM_PROVIDER_ENV_NAME)
    )
    if configured_provider:
        return configured_provider
    detected = detect_llm_provider_from_base_url(base_url or get_env("LLM_BASE_URL"))
    return detected or "openai_compatible"


def get_llm_provider_model_defaults(provider: str | None) -> dict[str, Any]:
    normalized = normalize_llm_provider_name(provider) or "openai_compatible"
    candidate = LLM_PROVIDER_MODEL_DEFAULTS.get(normalized)
    if candidate is None:
        candidate = LLM_PROVIDER_MODEL_DEFAULTS["openai_compatible"]
    return dict(candidate)


def get_llm_api_version() -> str | None:
    from app.shared.infra.env_support import get_env

    value = (get_env(LLM_API_VERSION_ENV_NAME) or get_env("AZURE_API_VERSION") or "").strip()
    return value or None


def resolve_litellm_provider_name(provider: str | None) -> str | None:
    normalized = normalize_llm_provider_name(provider)
    if not normalized:
        return None
    return LITELLM_PROVIDER_BY_RUNTIME_PROVIDER.get(normalized)


def is_local_llm_base_url(base_url: str | None) -> bool:
    normalized = (base_url or "").strip()
    if not normalized:
        return False
    try:
        parsed = urlparse(normalized)
    except Exception:
        parsed = None
    host = (parsed.hostname or "").lower() if parsed is not None else ""
    return host in {"localhost", "127.0.0.1", "::1"}


def llm_provider_requires_api_key(
    provider: str | None = None,
    *,
    base_url: str | None = None,
) -> bool:
    normalized_provider = normalize_llm_provider_name(provider) or detect_llm_provider_from_base_url(base_url)
    if normalized_provider in {"ollama", "vllm"}:
        return False
    if is_local_llm_base_url(base_url):
        return False
    return True


def split_csv_names(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item and item.strip()]


def normalize_retriever_name(name: str) -> str:
    normalized = (name or "").strip().lower()
    return RETRIEVER_ALIASES.get(normalized, normalized)


def normalize_profile_name(name: str) -> str:
    return (name or "").strip().lower()


def parse_yaml_scalar(value: str) -> Any:
    text = value.strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    if text == "{}":
        return {}
    if text == "[]":
        return []
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def parse_yaml_mapping(text: str) -> dict[str, Any]:
    """Parse a small project settings override mapping."""

    try:
        import yaml  # type: ignore

        parsed = yaml.safe_load(text) or {}
        return parsed if isinstance(parsed, dict) else {}
    except ImportError:
        pass

    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()

        current = stack[-1][1]
        key, sep, raw_value = stripped.partition(":")
        if not sep:
            continue

        normalized_key = key.strip().replace("-", "_")
        value = raw_value.strip()
        if not value:
            child: dict[str, Any] = {}
            current[normalized_key] = child
            stack.append((indent, child))
            continue
        current[normalized_key] = parse_yaml_scalar(value)

    return root


def load_project_settings_values(path: Path | None = None) -> dict[str, Any]:
    current_path = path
    if current_path is None:
        from app.shared.infra.env_support import resolve_project_settings_path

        current_path = resolve_project_settings_path()
    if current_path is None:
        return {}
    if not current_path.exists():
        return {}
    try:
        raw = parse_yaml_mapping(current_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _normalize_profile_entries(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_names = split_csv_names(value)
    elif isinstance(value, list):
        raw_names = [str(item).strip() for item in value if str(item).strip()]
    else:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_names:
        name = normalize_retriever_name(str(item))
        if not name or name in seen:
            continue
        seen.add(name)
        normalized.append(name)
    return normalized


def _iter_retriever_profile_override_blocks(raw: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    search_value = raw.get("search")
    if isinstance(search_value, dict):
        candidate = search_value.get("retriever_profiles")
        if isinstance(candidate, dict):
            blocks.append(candidate)
    return blocks


@lru_cache(maxsize=1)
def get_retriever_profiles(path: Path | None = None) -> dict[str, list[str]]:
    profiles = {
        normalize_profile_name(name): list(values)
        for name, values in DEFAULT_RETRIEVER_PROFILES.items()
    }
    raw = load_project_settings_values(path)
    for block in _iter_retriever_profile_override_blocks(raw):
        for name, value in block.items():
            profile_name = normalize_profile_name(str(name))
            if not profile_name:
                continue
            entries = _normalize_profile_entries(value)
            if entries:
                profiles[profile_name] = entries
    return profiles


__all__ = [
    "DEFAULT_EMBEDDING_DIM",
    "LLM_API_VERSION_ENV_NAME",
    "LLM_CANONICAL_PROVIDERS",
    "LLM_MODEL_PREFIX_PROVIDERS",
    "LLM_PROVIDER_ENV_NAME",
    "LLM_PROVIDER_MODEL_DEFAULTS",
    "LITELLM_PROVIDER_BY_RUNTIME_PROVIDER",
    "PROJECT_SETTINGS_ENV_NAME",
    "PROJECT_SETTINGS_SOURCE_LABEL",
    "DEFAULT_RETRIEVER_FALLBACK",
    "DEFAULT_RETRIEVER_PROFILES",
    "DEFAULT_RETRIEVERS",
    "DOCGEN_RETRIEVERS",
    "EMBEDDING_DIM_BY_MODEL",
    "RETRIEVER_PROFILES",
    "ZH_MATH_RETRIEVERS",
    "ZH_EDU_RETRIEVERS",
    "detect_llm_provider_from_base_url",
    "get_retriever_profiles",
    "get_llm_api_version",
    "get_llm_provider_model_defaults",
    "is_local_llm_base_url",
    "llm_provider_requires_api_key",
    "load_project_settings_values",
    "normalize_llm_provider_name",
    "normalize_profile_name",
    "normalize_retriever_name",
    "resolve_litellm_provider_name",
    "resolve_runtime_llm_provider",
    "split_provider_model_name",
    "split_csv_names",
]
