"""System initialization queries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from sqlmodel import Session

from app.repositories.user_settings_repo import (
    clear_user_runtime_settings,
    get_user_runtime_settings_payload,
    upsert_user_runtime_settings_payload,
)
from app.schemas.system import InitData, RuntimeUser, SettingEntry, SettingSection, SettingsOverviewData
from app.shared.infra.exceptions import AITeachMeError
from app.shared.infra.settings import DEFAULT_PROJECT_SETTINGS_FILENAME, Settings, get_settings
from app.shared.infra.env_support import get_env, get_env_bool, resolve_project_settings_path
from app.shared.infra.runtime import get_app_version, resolve_app_mode
from app.shared.infra.storage.config import (
    get_storage_backend,
    resolve_s3_addressing_style,
    resolve_s3_credential_mode,
)

_MISSING = object()


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


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _project_by_override_keys(
    effective_payload: Mapping[str, Any],
    raw_override: Mapping[str, Any],
) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for key, raw_value in raw_override.items():
        if key not in effective_payload:
            continue
        effective_value = effective_payload[key]
        if isinstance(raw_value, Mapping) and isinstance(effective_value, Mapping):
            child = _project_by_override_keys(effective_value, raw_value)
            if child:
                projected[key] = child
            continue
        projected[key] = effective_value
    return projected


def _normalize_user_settings_payload(raw_payload: Mapping[str, Any]) -> dict[str, Any]:
    base_payload = get_settings().model_dump(mode="json")
    candidate_payload = _deep_merge(base_payload, raw_payload)
    try:
        effective = Settings.model_validate(candidate_payload)
    except ValidationError as exc:
        raise AITeachMeError(
            detail="用户 settings 配置格式不合法，请检查字段名和字段类型。",
            error_code="INVALID_USER_SETTINGS",
            status_code=422,
            data=exc.errors(),
        ) from exc
    return _project_by_override_keys(effective.model_dump(mode="json"), raw_payload)


def _merge_user_settings(base_settings: Settings, user_payload: Mapping[str, Any]) -> Settings:
    if not user_payload:
        return base_settings
    merged_payload = _deep_merge(base_settings.model_dump(mode="json"), user_payload)
    return Settings.model_validate(merged_payload)


def _lookup_path(payload: Mapping[str, Any], dotted_key: str) -> tuple[bool, Any]:
    current: Any = payload
    for part in dotted_key.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, _MISSING
        current = current[part]
    return True, current


def _editable_settings_entry(
    key: str,
    label: str,
    value: Any,
    default_value: Any,
    user_payload: Mapping[str, Any],
    description: str = "",
) -> SettingEntry:
    has_user_value, user_value = _lookup_path(user_payload, key)
    source = "user_settings" if has_user_value else "settings"
    status = "configured" if has_user_value or value not in (None, "", [], {}) else "default"
    return SettingEntry(
        key=key,
        label=label,
        source=source,
        value=value,
        default_value=default_value,
        user_value=None if user_value is _MISSING else user_value,
        display_value=_display(value),
        status=status,
        editable=True,
        restart_required=False,
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


def build_settings_overview_data(
    *,
    session: Session | None = None,
    user_id: str | None = None,
) -> SettingsOverviewData:
    """Build a safe overview of env, project defaults, and user settings."""

    base_settings = get_settings()
    user_payload = (
        get_user_runtime_settings_payload(session, user_id)
        if session is not None and user_id
        else {}
    )
    settings = _merge_user_settings(base_settings, user_payload)
    mode = resolve_app_mode()
    settings_path = resolve_project_settings_path()

    def se(key: str, label: str, value: Any, default_value: Any, description: str = "") -> SettingEntry:
        return _editable_settings_entry(
            key,
            label,
            value,
            default_value,
            user_payload,
            description,
        )

    sections = [
        SettingSection(
            id="runtime",
            label="运行与部署",
            description="后端模式、鉴权、配置文件路径与运行版本。环境变量只读展示，密钥不返回明文。",
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
            label="模型路由",
            description=f"模型名默认来自 {DEFAULT_PROJECT_SETTINGS_FILENAME}，页面修改会保存为当前用户的非敏感 settings 覆盖。",
            entries=[
                _env_entry("llm.base_url", "LLM_BASE_URL", "LLM_BASE_URL", "OpenAI-compatible 上游地址。"),
                _env_entry("llm.api_key", "LLM_API_KEY", "LLM_API_KEY", "模型访问密钥，只显示是否配置。", secret=True),
                se("models.primary", "Primary 模型", settings.models.primary, base_settings.models.primary, "主要生成、对话、批改任务。"),
                se("models.reason", "Reason 模型", settings.models.reason, base_settings.models.reason, "深度推理与规划；空值时回退到 Primary。"),
                se("models.light", "Light 模型", settings.models.light, base_settings.models.light, "分类、摘要和批量轻任务；空值时回退到 Primary。"),
                se("models.extract", "Extract 模型", settings.models.extract, base_settings.models.extract, "知识抽取专用；空值时回退到 Light/Primary。"),
                se("models.embedding", "Embedding 模型", settings.models.embedding, base_settings.models.embedding),
                _runtime_entry("models.embedding_dim", "Embedding 维度", settings.embedding_dim),
                se("models.ocr", "Vision OCR 模型", settings.models.ocr, base_settings.models.ocr, "空值时使用 Primary 模型；密钥和服务地址复用 LLM 接入配置。"),
                se("models.mermaid_generation", "Mermaid 模型", settings.models.mermaid_generation, base_settings.models.mermaid_generation),
                se("models.image_generation", "文生图模型", settings.models.image_generation, base_settings.models.image_generation),
            ],
        ),
        SettingSection(
            id="learning_engines",
            label="学习引擎",
            description="Ingest / Digest / Interact / Profile 相关的非敏感运行策略。",
            entries=[
                se("ingest.max_upload_size_mb", "最大上传大小", settings.ingest.max_upload_size_mb, base_settings.ingest.max_upload_size_mb),
                se("ingest.max_files_per_upload", "单次最大文件数", settings.ingest.max_files_per_upload, base_settings.ingest.max_files_per_upload),
                se("ingest.parse_concurrency", "解析并发", settings.ingest.parse_concurrency, base_settings.ingest.parse_concurrency),
                se("ingest.parser_timeout_s", "解析超时", settings.ingest.parser_timeout_s, base_settings.ingest.parser_timeout_s),
                _env_entry("mineru.api_token", "MINERU_API_TOKEN", "MINERU_API_TOKEN", "服务端 MinerU Token，只显示是否配置。", secret=True),
                se("planner.default_digest_mode", "默认 Digest 模式", settings.planner.default_digest_mode, base_settings.planner.default_digest_mode),
                se("planner.default_tone", "默认写作语气", settings.planner.default_tone, base_settings.planner.default_tone),
                se("planner.allow_external_search", "Planner 允许外部检索", settings.planner.allow_external_search, base_settings.planner.allow_external_search),
                se("planner.sprint.min_chapters", "冲刺最少章节", settings.planner.sprint.min_chapters, base_settings.planner.sprint.min_chapters),
                se("planner.sprint.max_chapters", "冲刺最多章节", settings.planner.sprint.max_chapters, base_settings.planner.sprint.max_chapters),
                se("planner.sprint.target_length", "冲刺目标长度", settings.planner.sprint.target_length, base_settings.planner.sprint.target_length),
                se("planner.systematic.min_chapters", "系统最少章节", settings.planner.systematic.min_chapters, base_settings.planner.systematic.min_chapters),
                se("planner.systematic.max_chapters", "系统最多章节", settings.planner.systematic.max_chapters, base_settings.planner.systematic.max_chapters),
                se("planner.systematic.target_length", "系统目标长度", settings.planner.systematic.target_length, base_settings.planner.systematic.target_length),
                se("docgen.max_parallel_chapters", "DocGen 章节并发", settings.docgen.max_parallel_chapters, base_settings.docgen.max_parallel_chapters),
                se("docgen.io_parallelism", "DocGen I/O 并发", settings.docgen.io_parallelism, base_settings.docgen.io_parallelism),
                se("docgen.max_research_queries", "每章研究 Query 数", settings.docgen.max_research_queries, base_settings.docgen.max_research_queries),
                se("docgen.retrieval_timeout_s", "研究检索预算", settings.docgen.retrieval_timeout_s, base_settings.docgen.retrieval_timeout_s),
                se("docgen.read_timeout_s", "网页读取超时", settings.docgen.read_timeout_s, base_settings.docgen.read_timeout_s),
                se("interact.history_turns", "伴读历史轮数", settings.interact.history_turns, base_settings.interact.history_turns),
                se("knowledge_graph.extract_max_parallelism", "图谱抽取并发", settings.knowledge_graph.extract_max_parallelism, base_settings.knowledge_graph.extract_max_parallelism),
                se("knowledge_graph.sync_after_docgen", "DocGen 后同步图谱", settings.knowledge_graph.sync_after_docgen, base_settings.knowledge_graph.sync_after_docgen),
            ],
        ),
        SettingSection(
            id="search",
            label="检索与联网",
            description="本地 RAG、外部搜索 provider、reader 与 rerank 配置。",
            entries=[
                se("rag.top_k", "RAG Top-K", settings.rag.top_k, base_settings.rag.top_k),
                se("rag.similarity_threshold", "相似度阈值", settings.rag.similarity_threshold, base_settings.rag.similarity_threshold),
                se("rag.rerank_model", "Rerank 模型", settings.rag.rerank_model, base_settings.rag.rerank_model),
                se("rag.rerank_top_k", "Rerank 保留条数", settings.rag.rerank_top_k, base_settings.rag.rerank_top_k),
                _env_entry("rag.rerank_api_key", "RAG_RERANK_API_KEY", "RAG_RERANK_API_KEY", "Rerank 服务密钥。", secret=True),
                se("local_rag.priority", "本地资料优先", settings.local_rag.priority, base_settings.local_rag.priority),
                se("local_rag.min_results", "本地命中阈值", settings.local_rag.min_results, base_settings.local_rag.min_results),
                se("search.retriever_profile", "检索 Profile", settings.search.retriever_profile, base_settings.search.retriever_profile),
                se("search.retrievers", "显式 Retrievers", settings.search.retrievers, base_settings.search.retrievers),
                se("search.max_results_per_query", "单 query 最大结果数", settings.search.max_results_per_query, base_settings.search.max_results_per_query),
                se("search.scrape_timeout_s", "网页抓取超时", settings.search.scrape_timeout_s, base_settings.search.scrape_timeout_s),
                se("search.provider_timeout_s", "Provider 超时", settings.search.provider_timeout_s, base_settings.search.provider_timeout_s),
                se("search.total_timeout_s", "总检索预算", settings.search.total_timeout_s, base_settings.search.total_timeout_s),
                se("search.read_timeout_s", "Reader 超时", settings.search.read_timeout_s, base_settings.search.read_timeout_s),
                se("search.parallel_retrievers", "并发检索", settings.search.parallel_retrievers, base_settings.search.parallel_retrievers),
                se("search.max_parallel_retrievers", "最大并发 Provider", settings.search.max_parallel_retrievers, base_settings.search.max_parallel_retrievers),
                se("search.fusion_k", "融合参数 K", settings.search.fusion_k, base_settings.search.fusion_k),
                se("search.runtime_cache_enabled", "检索运行时缓存", settings.search.runtime_cache_enabled, base_settings.search.runtime_cache_enabled),
                se("search.runtime_cache_ttl_s", "检索缓存 TTL", settings.search.runtime_cache_ttl_s, base_settings.search.runtime_cache_ttl_s),
                se("search.runtime_cache_max_entries", "检索缓存容量", settings.search.runtime_cache_max_entries, base_settings.search.runtime_cache_max_entries),
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
                se("observability.tracing_enabled", "Tracing 总开关", settings.observability.tracing_enabled, base_settings.observability.tracing_enabled),
                se("observability.llm_token_summary_enabled", "LLM Token 摘要", settings.observability.llm_token_summary_enabled, base_settings.observability.llm_token_summary_enabled),
                se("observability.timing_top_k", "慢步骤展示数量", settings.observability.timing_top_k, base_settings.observability.timing_top_k),
                _env_entry("langsmith.tracing", "LANGSMITH_TRACING", "LANGSMITH_TRACING"),
                _env_entry("langsmith.api_key", "LANGSMITH_API_KEY", "LANGSMITH_API_KEY", secret=True),
                _env_entry("langsmith.project", "LANGSMITH_PROJECT", "LANGSMITH_PROJECT"),
                _env_entry("langsmith.endpoint", "LANGSMITH_ENDPOINT", "LANGSMITH_ENDPOINT"),
                se(
                    "observability.langsmith_capture_inputs",
                    "Trace 输入预览",
                    settings.observability.langsmith_capture_inputs,
                    base_settings.observability.langsmith_capture_inputs,
                    "空值表示按 APP_MODE 自动：local 开启，非本地关闭。",
                ),
                se(
                    "observability.langsmith_capture_outputs",
                    "Trace 输出预览",
                    settings.observability.langsmith_capture_outputs,
                    base_settings.observability.langsmith_capture_outputs,
                    "空值表示按 APP_MODE 自动：local 开启，非本地关闭。",
                ),
                se(
                    "observability.langsmith_max_text_chars",
                    "Trace 文本预览上限",
                    settings.observability.langsmith_max_text_chars,
                    base_settings.observability.langsmith_max_text_chars,
                ),
                se("observability.llm_observability_enabled", "LLM 调用统计", settings.observability.llm_observability_enabled, base_settings.observability.llm_observability_enabled),
                se("observability.llm_observability_max_records", "LLM 统计保留条数", settings.observability.llm_observability_max_records, base_settings.observability.llm_observability_max_records),
                se("runtime.llm_concurrency_limit", "LLM 并发限制", settings.runtime.llm_concurrency_limit, base_settings.runtime.llm_concurrency_limit),
                se("runtime.default_token_budget", "默认上下文预算", settings.runtime.default_token_budget, base_settings.runtime.default_token_budget),
                se("embedding.batch_size", "Embedding 批大小", settings.embedding.batch_size, base_settings.embedding.batch_size),
                se("embedding.batch_delay_s", "Embedding 批延迟", settings.embedding.batch_delay_s, base_settings.embedding.batch_delay_s),
                se("safety.guardrails_enabled", "Guardrails", settings.safety.guardrails_enabled, base_settings.safety.guardrails_enabled),
            ],
        ),
    ]

    return SettingsOverviewData(
        settings_path=str(settings_path),
        mode=mode,
        sections=sections,
        notes=[
            f"{DEFAULT_PROJECT_SETTINGS_FILENAME} 作为项目默认值保留；页面保存的是当前用户的非敏感 settings 覆盖。",
            "环境变量与密钥只展示后端是否配置；前端填写的 .env.sample 类字段只保存在当前浏览器。",
            "敏感字段不返回后端明文，也不会写入用户 settings 数据库。",
        ],
    )


def update_user_settings_overview_data(
    *,
    session: Session,
    user_id: str,
    settings_payload: Mapping[str, Any],
    reset: bool = False,
) -> SettingsOverviewData:
    """Persist current user's non-secret settings and return fresh overview."""

    if reset:
        clear_user_runtime_settings(session, user_id=user_id)
    else:
        normalized_payload = _normalize_user_settings_payload(settings_payload)
        upsert_user_runtime_settings_payload(
            session,
            user_id=user_id,
            payload=normalized_payload,
        )
    return build_settings_overview_data(session=session, user_id=user_id)
