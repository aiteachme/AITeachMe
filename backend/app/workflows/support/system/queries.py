"""System initialization queries."""

from __future__ import annotations

from typing import Any

from app.schemas.system import InitData, RuntimeUser, SettingEntry, SettingSection, SettingsOverviewData
from app.shared.infra.config import get_settings
from app.shared.infra.env_support import get_env, get_env_bool, resolve_project_config_path
from app.shared.infra.runtime import get_app_version, resolve_app_mode
from app.shared.infra.storage.config import (
    get_storage_backend,
    resolve_s3_addressing_style,
    resolve_s3_credential_mode,
)


def build_init_data(
    *,
    user_id: str,
    email: str | None,
    is_local: bool,
    device_key: str | None,
    is_authenticated: bool,
) -> InitData:
    """Build frontend runtime initialization data."""

    auth_enabled = get_env_bool("AUTH_ENABLED", True)
    return InitData(
        mode=resolve_app_mode(),
        auth_enabled=auth_enabled,
        auth_ready=True,
        current_user=RuntimeUser(
            user_id=user_id,
            email=email,
            is_local=is_local,
            device_key=device_key,
            is_authenticated=is_authenticated,
        ),
        feature_flags={
            "auth": auth_enabled,
            "files": True,
            "knowledge": True,
            "chat": True,
            "exam": True,
            "profile": True,
        },
        version=get_app_version(),
    )


def _has_env(name: str) -> bool:
    return bool((get_env(name) or "").strip())


def _display(value: Any) -> str:
    if value is None:
        return "未配置"
    if isinstance(value, bool):
        return "开启" if value else "关闭"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value if str(item).strip()) or "空"
    if isinstance(value, dict):
        return f"{len(value)} 项"
    text = str(value)
    return text if text.strip() else "空"


def _config_entry(
    key: str,
    label: str,
    value: Any,
    description: str = "",
    *,
    restart_required: bool = True,
) -> SettingEntry:
    status = "default" if value in (None, "", [], {}) else "configured"
    return SettingEntry(
        key=key,
        label=label,
        source="config",
        value=value,
        display_value=_display(value),
        status=status,
        restart_required=restart_required,
        description=description,
    )


def _env_entry(
    key: str,
    label: str,
    env_name: str,
    description: str = "",
    *,
    secret: bool = False,
    value: Any | None = None,
    restart_required: bool = True,
) -> SettingEntry:
    configured = _has_env(env_name)
    safe_value = None if secret else (value if value is not None else get_env(env_name))
    display_value = "已配置" if secret and configured else ("未配置" if secret else _display(safe_value))
    return SettingEntry(
        key=key,
        label=label,
        source="env",
        value=safe_value,
        display_value=display_value,
        status="configured" if configured else "missing",
        secret=secret,
        restart_required=restart_required,
        description=description,
    )


def _runtime_entry(
    key: str,
    label: str,
    value: Any,
    description: str = "",
) -> SettingEntry:
    return SettingEntry(
        key=key,
        label=label,
        source="runtime",
        value=value,
        display_value=_display(value),
        status="runtime",
        restart_required=False,
        description=description,
    )


def build_settings_overview_data() -> SettingsOverviewData:
    """Build a safe read-only overview of env/config.yaml effective settings."""

    settings = get_settings()
    mode = resolve_app_mode()
    config_path = resolve_project_config_path()

    sections = [
        SettingSection(
            id="runtime",
            label="运行与部署",
            description="后端模式、鉴权、配置文件路径与运行版本。",
            entries=[
                _runtime_entry("runtime.mode", "运行模式", mode, "由 APP_MODE 解析得到。"),
                _env_entry("runtime.app_mode_raw", "APP_MODE", "APP_MODE", "未设置时按本地优先策略解析。"),
                _runtime_entry("runtime.version", "应用版本", get_app_version()),
                _env_entry("auth.enabled", "AUTH_ENABLED", "AUTH_ENABLED", "控制账号鉴权能力。", value=get_env_bool("AUTH_ENABLED", True)),
                _runtime_entry("config.path", "config.yaml 路径", str(config_path)),
            ],
        ),
        SettingSection(
            id="models",
            label="模型与密钥",
            description="模型名来自 config.yaml，服务地址和密钥来自环境变量。",
            entries=[
                _env_entry("llm.base_url", "LLM_BASE_URL", "LLM_BASE_URL", "OpenAI-compatible 上游地址。"),
                _env_entry("llm.api_key", "LLM_API_KEY", "LLM_API_KEY", "模型访问密钥，只显示是否配置。", secret=True),
                _config_entry("models.primary", "Primary 模型", settings.llm_model, "主要生成、对话、批改任务。"),
                _config_entry("models.reason", "Reason 模型", settings.llm_model_reason, "深度推理与规划；空值时回退到 Primary。"),
                _config_entry("models.light", "Light 模型", settings.llm_model_light, "分类、摘要和批量轻任务；空值时回退到 Primary。"),
                _config_entry("models.extract", "Extract 模型", settings.llm_model_extract, "知识抽取专用；空值时回退到 Light/Primary。"),
                _config_entry("models.embedding", "Embedding 模型", settings.embedding_model),
                _runtime_entry("models.embedding_dim", "Embedding 维度", settings.embedding_dim),
                _config_entry("models.ocr", "OCR 模型", settings.ocr_model),
                _config_entry("models.mermaid", "Mermaid 模型", settings.mermaid_generation_model),
                _config_entry("models.image_generation", "文生图模型", settings.image_generation_model),
            ],
        ),
        SettingSection(
            id="ingest",
            label="资料解析",
            description="上传限制、解析并发、解析超时和外部解析服务状态。",
            entries=[
                _config_entry("files.max_upload_size_mb", "最大上传大小", settings.max_upload_size_mb),
                _config_entry("ingest.parse_concurrency", "解析并发", settings.ingest_parse_concurrency),
                _config_entry("ingest.parser_timeout_s", "解析超时", settings.ingest_parser_timeout_s),
                _env_entry("mineru.api_token", "MINERU_API_TOKEN", "MINERU_API_TOKEN", "服务端 MinerU Token，只显示是否配置。", secret=True),
                _env_entry("ocr.api_key", "OCR_API_KEY", "OCR_API_KEY", "外部 OCR 服务密钥，只显示是否配置。", secret=True),
                _env_entry("ocr.base_url", "OCR_BASE_URL", "OCR_BASE_URL", "外部 OCR 服务地址。"),
            ],
        ),
        SettingSection(
            id="search",
            label="检索与联网",
            description="本地 RAG、外部搜索 provider、reader 与 rerank 配置。",
            entries=[
                _config_entry("rag.top_k", "RAG Top-K", settings.rag_top_k),
                _config_entry("rag.similarity_threshold", "相似度阈值", settings.rag_similarity_threshold),
                _config_entry("rag.rerank_model", "Rerank 模型", settings.rag_rerank_model),
                _env_entry("rag.rerank_api_key", "RAG_RERANK_API_KEY", "RAG_RERANK_API_KEY", "Rerank 服务密钥。", secret=True),
                _config_entry("local_rag.priority", "本地资料优先", settings.local_rag_priority),
                _config_entry("local_rag.min_results", "本地命中阈值", settings.local_rag_min_results),
                _config_entry("web_search.retriever_profile", "检索 Profile", settings.web_search_retriever_profile),
                _config_entry("web_search.retrievers", "显式 Retrievers", settings.web_search_retrievers),
                _config_entry("search.max_results_per_query", "单 query 最大结果数", settings.search_max_results_per_query),
                _config_entry("search.provider_timeout_s", "Provider 超时", settings.search_provider_timeout_s),
                _config_entry("search.total_timeout_s", "总检索预算", settings.search_total_timeout_s),
                _config_entry("search.parallel_retrievers", "并发检索", settings.search_parallel_retrievers),
                _config_entry("search.max_parallel_retrievers", "最大并发 Provider", settings.search_max_parallel_retrievers),
                _config_entry("search.fusion_k", "融合参数 K", settings.search_fusion_k),
                _env_entry("search.tavily_key", "TAVILY_API_KEY", "TAVILY_API_KEY", "Tavily 检索密钥。", secret=True),
                _env_entry("search.brave_key", "BRAVE_SEARCH_API_KEY", "BRAVE_SEARCH_API_KEY", "Brave Search 密钥。", secret=True),
                _env_entry("search.exa_key", "EXA_API_KEY", "EXA_API_KEY", "Exa 语义搜索密钥。", secret=True),
                _env_entry("search.bing_key", "BING_API_KEY", "BING_API_KEY", "Bing Search 密钥。", secret=True),
                _env_entry("search.bocha_key", "BOCHA_API_KEY", "BOCHA_API_KEY", "Bocha 搜索密钥。", secret=True),
                _env_entry("search.searxng_url", "SEARXNG_BASE_URL", "SEARXNG_BASE_URL", "自建/可信 SearXNG 地址。"),
                _env_entry("reader.jina_enabled", "JINA_READER_ENABLED", "JINA_READER_ENABLED", "是否启用 Jina Reader。"),
                _env_entry("reader.jina_key", "JINA_API_KEY", "JINA_API_KEY", "Jina Reader 密钥。", secret=True),
            ],
        ),
        SettingSection(
            id="storage",
            label="数据库与存储",
            description="SQLite/Postgres 与 Local/S3 存储当前状态。",
            entries=[
                _env_entry("database.url", "DATABASE_URL", "DATABASE_URL", "云端模式需要配置数据库连接串。", secret=True),
                _runtime_entry("storage.backend", "存储后端", get_storage_backend()),
                _env_entry("storage.s3_bucket", "S3_BUCKET", "S3_BUCKET"),
                _env_entry("storage.s3_endpoint", "S3_ENDPOINT", "S3_ENDPOINT"),
                _env_entry("storage.s3_public_base_url", "S3_PUBLIC_BASE_URL", "S3_PUBLIC_BASE_URL"),
                _runtime_entry("storage.s3_addressing_style", "S3 地址风格", resolve_s3_addressing_style()),
                _runtime_entry("storage.s3_credential_mode", "S3 凭证模式", resolve_s3_credential_mode()),
                _env_entry("storage.s3_access_key", "S3_ACCESS_KEY", "S3_ACCESS_KEY", secret=True),
                _env_entry("storage.s3_secret_key", "S3_SECRET_KEY", "S3_SECRET_KEY", secret=True),
                _env_entry("storage.dogecloud_access_key", "DOGECLOUD_API_ACCESS_KEY", "DOGECLOUD_API_ACCESS_KEY", secret=True),
                _env_entry("storage.dogecloud_space", "DOGECLOUD_SPACE_NAME", "DOGECLOUD_SPACE_NAME"),
            ],
        ),
        SettingSection(
            id="observability",
            label="观测与安全",
            description="LangSmith、LLM 统计、缓存、安全护栏与并发控制。",
            entries=[
                _config_entry("observability.tracing_enabled", "Tracing 总开关", settings.tracing_enabled),
                _env_entry("langsmith.tracing", "LANGSMITH_TRACING", "LANGSMITH_TRACING"),
                _env_entry("langsmith.api_key", "LANGSMITH_API_KEY", "LANGSMITH_API_KEY", secret=True),
                _env_entry("langsmith.project", "LANGSMITH_PROJECT", "LANGSMITH_PROJECT"),
                _config_entry("observability.llm_observability_enabled", "LLM 调用统计", settings.llm_observability_enabled),
                _config_entry("runtime.llm_concurrency_limit", "LLM 并发限制", settings.llm_concurrency_limit),
                _config_entry("safety.guardrails_enabled", "Guardrails", settings.guardrails_enabled),
                _config_entry("cache.enabled", "LLM 缓存", settings.llm_cache_enabled),
                _config_entry("cache.ttl_s", "LLM 缓存 TTL", settings.llm_cache_ttl_s),
                _config_entry("search_runtime_cache.enabled", "检索运行时缓存", settings.search_runtime_cache_enabled),
            ],
        ),
    ]

    return SettingsOverviewData(
        config_path=str(config_path),
        mode=mode,
        sections=sections,
        notes=[
            "页面只展示后端当前生效配置；环境变量和 config.yaml 需要在部署环境或文件中修改。",
            "敏感字段只显示是否已配置，不返回明文。",
            "浏览器本地偏好只影响当前设备，不会写回后端配置。",
        ],
    )
