"""System initialization queries."""

from __future__ import annotations

from typing import Any

from app.schemas.system import InitData, RuntimeUser, SettingEntry, SettingSection, SettingsOverviewData
from app.shared.infra.settings import DEFAULT_PROJECT_SETTINGS_FILENAME, get_settings
from app.shared.infra.env_support import get_env, get_env_bool, resolve_project_settings_path
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


def _settings_entry(
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
        source="settings",
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
    """Build a safe read-only overview of env/project settings effective settings."""

    settings = get_settings()
    mode = resolve_app_mode()
    settings_path = resolve_project_settings_path()

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
                _runtime_entry("settings.path", f"{DEFAULT_PROJECT_SETTINGS_FILENAME} 路径", str(settings_path)),
            ],
        ),
        SettingSection(
            id="models",
            label="模型与密钥",
            description=f"模型名来自 {DEFAULT_PROJECT_SETTINGS_FILENAME}，LLM 服务地址和密钥统一来自 LLM_API_KEY / LLM_BASE_URL。",
            entries=[
                _env_entry("llm.base_url", "LLM_BASE_URL", "LLM_BASE_URL", "OpenAI-compatible 上游地址。"),
                _env_entry("llm.api_key", "LLM_API_KEY", "LLM_API_KEY", "模型访问密钥，只显示是否配置。", secret=True),
                _settings_entry("models.primary", "Primary 模型", settings.models.primary, "主要生成、对话、批改任务。"),
                _settings_entry("models.reason", "Reason 模型", settings.models.reason, "深度推理与规划；空值时回退到 Primary。"),
                _settings_entry("models.light", "Light 模型", settings.models.light, "分类、摘要和批量轻任务；空值时回退到 Primary。"),
                _settings_entry("models.extract", "Extract 模型", settings.models.extract, "知识抽取专用；空值时回退到 Light/Primary。"),
                _settings_entry("models.embedding", "Embedding 模型", settings.models.embedding),
                _runtime_entry("models.embedding_dim", "Embedding 维度", settings.embedding_dim),
                _settings_entry("models.ocr", "Vision OCR 模型", settings.models.ocr, "空值时使用 Primary 模型；密钥和服务地址复用 LLM 接入配置。"),
                _settings_entry("models.mermaid", "Mermaid 模型", settings.models.mermaid_generation),
                _settings_entry("models.image_generation", "文生图模型", settings.models.image_generation),
            ],
        ),
        SettingSection(
            id="interact",
            label="伴读对话",
            description="Interact 伴读引擎的上下文与历史记录策略。",
            entries=[
                _settings_entry("interact.history_turns", "历史对话轮数", settings.interact.history_turns),
            ],
        ),
        SettingSection(
            id="ingest",
            label="资料解析",
            description="上传限制、解析并发、解析超时和外部解析服务状态。",
            entries=[
                _settings_entry("ingest.max_upload_size_mb", "最大上传大小", settings.ingest.max_upload_size_mb),
                _settings_entry("ingest.max_files_per_upload", "单次最大文件数", settings.ingest.max_files_per_upload),
                _settings_entry("ingest.parse_concurrency", "解析并发", settings.ingest.parse_concurrency),
                _settings_entry("ingest.parser_timeout_s", "解析超时", settings.ingest.parser_timeout_s),
                _env_entry("mineru.api_token", "MINERU_API_TOKEN", "MINERU_API_TOKEN", "服务端 MinerU Token，只显示是否配置。", secret=True),
            ],
        ),
        SettingSection(
            id="search",
            label="检索与联网",
            description="本地 RAG、外部搜索 provider、reader 与 rerank 配置。",
            entries=[
                _settings_entry("rag.top_k", "RAG Top-K", settings.rag.top_k),
                _settings_entry("rag.similarity_threshold", "相似度阈值", settings.rag.similarity_threshold),
                _settings_entry("rag.rerank_model", "Rerank 模型", settings.rag.rerank_model),
                _env_entry("rag.rerank_api_key", "RAG_RERANK_API_KEY", "RAG_RERANK_API_KEY", "Rerank 服务密钥。", secret=True),
                _settings_entry("local_rag.priority", "本地资料优先", settings.local_rag.priority),
                _settings_entry("local_rag.min_results", "本地命中阈值", settings.local_rag.min_results),
                _settings_entry("search.retriever_profile", "检索 Profile", settings.search.retriever_profile),
                _settings_entry("search.retrievers", "显式 Retrievers", settings.search.retrievers),
                _settings_entry("search.max_results_per_query", "单 query 最大结果数", settings.search.max_results_per_query),
                _settings_entry("search.provider_timeout_s", "Provider 超时", settings.search.provider_timeout_s),
                _settings_entry("search.total_timeout_s", "总检索预算", settings.search.total_timeout_s),
                _settings_entry("search.parallel_retrievers", "并发检索", settings.search.parallel_retrievers),
                _settings_entry("search.max_parallel_retrievers", "最大并发 Provider", settings.search.max_parallel_retrievers),
                _settings_entry("search.fusion_k", "融合参数 K", settings.search.fusion_k),
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
            description="LangSmith、LLM 统计、安全护栏与并发控制。",
            entries=[
                _settings_entry("observability.tracing_enabled", "Tracing 总开关", settings.observability.tracing_enabled),
                _settings_entry("observability.llm_token_summary_enabled", "LLM Token 摘要", settings.observability.llm_token_summary_enabled),
                _settings_entry("observability.timing_top_k", "慢步骤展示数量", settings.observability.timing_top_k),
                _env_entry("langsmith.tracing", "LANGSMITH_TRACING", "LANGSMITH_TRACING"),
                _env_entry("langsmith.api_key", "LANGSMITH_API_KEY", "LANGSMITH_API_KEY", secret=True),
                _env_entry("langsmith.project", "LANGSMITH_PROJECT", "LANGSMITH_PROJECT"),
                _env_entry("langsmith.endpoint", "LANGSMITH_ENDPOINT", "LANGSMITH_ENDPOINT"),
                _settings_entry(
                    "observability.langsmith_capture_inputs",
                    "Trace 输入预览",
                    settings.observability.langsmith_capture_inputs,
                    "空值表示按 APP_MODE 自动：local 开启，非本地关闭。",
                ),
                _settings_entry(
                    "observability.langsmith_capture_outputs",
                    "Trace 输出预览",
                    settings.observability.langsmith_capture_outputs,
                    "空值表示按 APP_MODE 自动：local 开启，非本地关闭。",
                ),
                _settings_entry(
                    "observability.langsmith_max_text_chars",
                    "Trace 文本预览上限",
                    settings.observability.langsmith_max_text_chars,
                ),
                _settings_entry("observability.llm_observability_enabled", "LLM 调用统计", settings.observability.llm_observability_enabled),
                _settings_entry("runtime.llm_concurrency_limit", "LLM 并发限制", settings.runtime.llm_concurrency_limit),
                _settings_entry("safety.guardrails_enabled", "Guardrails", settings.safety.guardrails_enabled),
                _settings_entry("search.runtime_cache_enabled", "检索运行时缓存", settings.search.runtime_cache_enabled),
            ],
        ),
    ]

    return SettingsOverviewData(
        settings_path=str(settings_path),
        mode=mode,
        sections=sections,
        notes=[
            f"页面只展示后端当前生效配置；环境变量和 {DEFAULT_PROJECT_SETTINGS_FILENAME} 需要在部署环境或文件中修改。",
            "敏感字段只显示是否已配置，不返回明文。",
            "浏览器本地偏好只影响当前设备，不会写回后端配置。",
        ],
    )
