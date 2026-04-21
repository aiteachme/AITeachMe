"""System initialization queries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
import structlog
from sqlmodel import Session

from app.repositories.user_settings_repo import (
    clear_user_runtime_settings,
    get_user_runtime_settings_payload,
)
from app.repositories.system_settings_repo import (
    clear_system_runtime_settings,
    get_system_runtime_settings_payload,
    upsert_system_runtime_settings_payload,
)
from app.schemas.system import InitData, RuntimeUser, SettingEntry, SettingSection, SettingsOverviewData
from app.shared.infra.exceptions import AITeachMeError
from app.shared.infra.settings import (
    PROJECT_SETTINGS_ENV_NAME,
    PROJECT_SETTINGS_SOURCE_LABEL,
    Settings,
    get_project_settings,
    get_system_settings_override_payload,
    merge_settings_values,
    set_system_settings_override,
)
from app.shared.infra.env_support import (
    describe_project_settings_source,
    get_env,
    get_env_bool,
    resolve_writable_local_env_path,
    write_local_env_updates,
)
from app.shared.infra.runtime import get_app_version, is_local_mode, resolve_app_mode, resolve_auth_enabled
from app.shared.infra.storage.config import (
    get_storage_backend,
    resolve_s3_addressing_style,
    resolve_s3_credential_mode,
)

_MISSING = object()
logger = structlog.get_logger(__name__)
_ENV_ENTRY_KEYS: dict[str, str] = {}


def build_init_data(
    *,
    user_id: str,
    email: str | None,
    is_local: bool,
    device_key: str | None,
    is_authenticated: bool,
) -> InitData:
    """Build frontend runtime initialization data."""

    auth_enabled = resolve_auth_enabled()
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


def _diff_from_base(base_payload: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return only values in ``payload`` that differ from project defaults."""

    diff: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in base_payload:
            continue
        base_value = base_payload[key]
        if isinstance(value, Mapping) and isinstance(base_value, Mapping):
            child = _diff_from_base(base_value, value)
            if child:
                diff[key] = child
            continue
        if value != base_value:
            diff[key] = value
    return diff


def _project_known_settings_keys(
    schema_payload: Mapping[str, Any],
    raw_override: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep only user setting keys still recognized by the current schema.

    User settings are persisted in the database and may outlive config schema
    refactors. Unknown keys from older releases should not make the settings
    page fail to load after a deploy.
    """

    projected: dict[str, Any] = {}
    for key, raw_value in raw_override.items():
        if key not in schema_payload:
            continue
        schema_value = schema_payload[key]
        if isinstance(raw_value, Mapping) and isinstance(schema_value, Mapping):
            child = _project_known_settings_keys(schema_value, raw_value)
            if child:
                projected[key] = child
            continue
        projected[key] = raw_value
    return projected


def _normalize_user_settings_payload(raw_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and shrink a user settings override payload.

    The database should store only user-changed, non-secret settings. Defaults
    remain in code defaults / optional project override files; secrets remain in ``.env`` / process
    environment or browser-local draft fields.
    """

    base_payload = get_project_settings().model_dump(mode="json")
    known_payload = _project_known_settings_keys(base_payload, raw_payload)
    candidate_payload = merge_settings_values(base_payload, known_payload)
    try:
        effective = Settings.model_validate(candidate_payload)
    except ValidationError as exc:
        raise AITeachMeError(
            detail="用户 settings 配置格式不合法，请检查字段名和字段类型。",
            error_code="INVALID_USER_SETTINGS",
            status_code=422,
            data=exc.errors(),
        ) from exc
    projected_payload = _project_by_override_keys(effective.model_dump(mode="json"), known_payload)
    return _diff_from_base(base_payload, projected_payload)


def _safe_user_settings_payload(raw_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize persisted user settings without letting stale rows break reads."""

    try:
        return _normalize_user_settings_payload(raw_payload)
    except AITeachMeError as exc:
        logger.warning("invalid_user_settings_ignored", error=str(exc), error_code=exc.error_code)
        return {}


def _merge_system_settings(base_settings: Settings, system_payload: Mapping[str, Any]) -> Settings:
    if not system_payload:
        return base_settings
    normalized_payload = _safe_user_settings_payload(system_payload)
    merged_payload = merge_settings_values(
        base_settings.model_dump(mode="json"), normalized_payload
    )
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
    system_payload: Mapping[str, Any],
    user_payload: Mapping[str, Any],
    description: str = "",
    *,
    editable_in_local: bool = True,
    editable_in_cloud: bool = True,
) -> SettingEntry:
    has_system_value, system_value = _lookup_path(system_payload, key)
    has_user_value, user_value = _lookup_path(user_payload, key)
    if has_system_value:
        source = "system_settings"
    elif has_user_value:
        source = "user_settings"
    else:
        source = "settings"
    status = "configured" if has_system_value or has_user_value or value not in (None, "", [], {}) else "default"
    editable = editable_in_local if is_local_mode() else editable_in_cloud
    return SettingEntry(
        key=key,
        label=label,
        source=source,
        value=value,
        default_value=default_value,
        user_value=None if user_value is _MISSING else user_value,
        display_value=_display(value),
        status=status,
        editable=editable,
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
    _ENV_ENTRY_KEYS[key] = env_name
    configured = _has_env(env_name)
    local_mode = is_local_mode()
    actual_value = value if value is not None else get_env(env_name)
    safe_secret = bool(secret and not local_mode)
    safe_value = None if safe_secret else actual_value
    display_value = "已配置" if safe_secret and configured else ("未配置" if safe_secret else _display(safe_value))
    return SettingEntry(
        key=key,
        label=label,
        source="env",
        value=safe_value,
        display_value=display_value,
        status="configured" if configured else "missing",
        secret=safe_secret,
        editable=local_mode,
        restart_required=restart_required if local_mode else True,
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
        derived=True,
        restart_required=False,
        description=description,
    )


def build_settings_overview_data(
    *,
    session: Session | None = None,
    user_id: str | None = None,
) -> SettingsOverviewData:
    """Build a safe overview of env, project defaults, and user settings."""

    base_settings = get_project_settings()
    raw_system_payload = (
        get_system_runtime_settings_payload(session)
        if session is not None
        else get_system_settings_override_payload()
    )
    raw_user_payload = (
        get_user_runtime_settings_payload(session, user_id)
        if session is not None and user_id and is_local_mode()
        else {}
    )
    system_payload = _safe_user_settings_payload(raw_system_payload)
    user_payload = _safe_user_settings_payload(raw_user_payload)

    if is_local_mode() and session is not None and not system_payload and user_payload:
        upsert_system_runtime_settings_payload(session, payload=user_payload)
        set_system_settings_override(user_payload)
        system_payload = user_payload

    settings = _merge_system_settings(base_settings, system_payload)
    mode = resolve_app_mode()
    settings_source = describe_project_settings_source()

    def lse(key: str, label: str, value: Any, default_value: Any, description: str = "") -> SettingEntry:
        return _editable_settings_entry(
            key,
            label,
            value,
            default_value,
            system_payload,
            user_payload,
            description,
            editable_in_local=True,
            editable_in_cloud=False,
        )

    sections = [
        SettingSection(
            id="runtime",
            label="运行与部署",
            description="后端模式、鉴权、配置文件路径与运行版本。环境变量只读展示，密钥不返回明文。",
            entries=[
                _runtime_entry("runtime.mode", "运行模式", mode, "由 APP_MODE 解析得到。"),
                _env_entry("runtime.app_mode_raw", "应用运行模式", "APP_MODE", "未设置时按本地优先策略解析。"),
                _runtime_entry("runtime.version", "应用版本", get_app_version()),
                _env_entry("auth.enabled", "是否启用鉴权", "AUTH_ENABLED", "账号鉴权覆盖项；空值按 APP_MODE 自动：local 关闭，cloud/Render 开启。", value=resolve_auth_enabled()),
                _runtime_entry("settings.source", "项目设置来源", settings_source),
            ],
        ),
        SettingSection(
            id="models",
            label="模型路由",
            description="模型名默认来自代码默认值与可选项目 override；本地模式下页面修改会保存为系统级运行覆盖。",
            entries=[
                _env_entry("llm.base_url", "模型服务地址", "LLM_BASE_URL", "OpenAI 兼容上游地址。"),
                _env_entry("llm.api_key", "模型服务密钥", "LLM_API_KEY", "模型访问密钥，只显示是否配置。", secret=True),
                lse("models.primary", "主模型", settings.models.primary, base_settings.models.primary, "主要生成、对话、批改任务。"),
                lse("models.reason", "推理模型", settings.models.reason, base_settings.models.reason, "深度推理与规划；空值时回退到主模型。"),
                lse("models.light", "轻量模型", settings.models.light, base_settings.models.light, "分类、摘要和批量轻任务；空值时回退到主模型。"),
                lse("models.extract", "抽取模型", settings.models.extract, base_settings.models.extract, "知识抽取专用；空值时回退到轻量模型或主模型。"),
                lse("models.embedding", "向量模型", settings.models.embedding, base_settings.models.embedding),
                _runtime_entry("models.embedding_dim", "向量维度", settings.embedding_dim),
                lse("models.ocr", "视觉 OCR 模型", settings.models.ocr, base_settings.models.ocr, "空值时使用主模型；密钥和服务地址复用模型接入配置。"),
                lse("models.image_generation", "图片生成模型", settings.models.image_generation, base_settings.models.image_generation, "留空表示未启用服务端图片生成能力。"),
            ],
        ),
        SettingSection(
            id="learning_engines",
            label="学习引擎",
            description="Ingest / Digest / Interact / Profile 相关的非敏感运行策略。解析偏好会保存到数据库，并在上传时作为用户默认值下发。",
            entries=[
                lse("ingest.max_upload_size_mb", "最大上传大小", settings.ingest.max_upload_size_mb, base_settings.ingest.max_upload_size_mb),
                lse("ingest.max_files_per_upload", "单次最大文件数", settings.ingest.max_files_per_upload, base_settings.ingest.max_files_per_upload),
                lse("ingest.parse_concurrency", "解析并发", settings.ingest.parse_concurrency, base_settings.ingest.parse_concurrency),
                lse("ingest.parser_timeout_s", "解析超时", settings.ingest.parser_timeout_s, base_settings.ingest.parser_timeout_s),
                lse("ingest.default_parser_provider", "默认解析模式", settings.ingest.default_parser_provider, base_settings.ingest.default_parser_provider, "auto 表示走本地分类 + parse plan + parser chain；只有 markitdown / mineru 会显式指定 provider。"),
                lse("ingest.mineru_model_version", "MinerU 默认模型版本", settings.ingest.mineru_model_version, base_settings.ingest.mineru_model_version, "仅当默认解析引擎为 MinerU 时生效。"),
                lse("ingest.mineru_enable_formula", "MinerU 默认公式识别", settings.ingest.mineru_enable_formula, base_settings.ingest.mineru_enable_formula),
                lse("ingest.mineru_enable_table", "MinerU 默认表格识别", settings.ingest.mineru_enable_table, base_settings.ingest.mineru_enable_table),
                lse("ingest.mineru_is_ocr", "MinerU 默认 OCR", settings.ingest.mineru_is_ocr, base_settings.ingest.mineru_is_ocr),
                _env_entry("mineru.api_token", "MinerU 服务密钥", "MINERU_API_TOKEN", "服务端 MinerU Token，只显示是否配置。", secret=True),
                lse("planner.default_digest_mode", "默认 Digest 模式", settings.planner.default_digest_mode, base_settings.planner.default_digest_mode),
                lse("planner.sprint.min_chapters", "冲刺最少章节", settings.planner.sprint.min_chapters, base_settings.planner.sprint.min_chapters),
                lse("planner.sprint.max_chapters", "冲刺最多章节", settings.planner.sprint.max_chapters, base_settings.planner.sprint.max_chapters),
                lse("planner.sprint.target_length", "冲刺目标长度", settings.planner.sprint.target_length, base_settings.planner.sprint.target_length),
                lse("planner.systematic.min_chapters", "系统最少章节", settings.planner.systematic.min_chapters, base_settings.planner.systematic.min_chapters),
                lse("planner.systematic.max_chapters", "系统最多章节", settings.planner.systematic.max_chapters, base_settings.planner.systematic.max_chapters),
                lse("planner.systematic.target_length", "系统目标长度", settings.planner.systematic.target_length, base_settings.planner.systematic.target_length),
                lse("docgen.allow_external_search", "知识文档允许外部检索", settings.docgen.allow_external_search, base_settings.docgen.allow_external_search),
                lse("docgen.generate_cover_image", "知识文档生成封面", settings.docgen.generate_cover_image, base_settings.docgen.generate_cover_image, "启用后会为知识文档生成一张横向、抽象、无文字的艺术风景封面，并置于文档顶部。"),
                lse("docgen.max_parallel_chapters", "知识文档章节并发", settings.docgen.max_parallel_chapters, base_settings.docgen.max_parallel_chapters),
                lse("docgen.io_parallelism", "知识文档 I/O 并发", settings.docgen.io_parallelism, base_settings.docgen.io_parallelism),
                lse("docgen.max_research_queries", "每章研究查询数", settings.docgen.max_research_queries, base_settings.docgen.max_research_queries),
                lse("docgen.retrieval_timeout_s", "研究检索预算", settings.docgen.retrieval_timeout_s, base_settings.docgen.retrieval_timeout_s),
                lse("docgen.read_timeout_s", "网页读取超时", settings.docgen.read_timeout_s, base_settings.docgen.read_timeout_s),
                lse("interact.history_turns", "伴读历史轮数", settings.interact.history_turns, base_settings.interact.history_turns),
                lse("knowledge_graph.extract_max_parallelism", "图谱抽取并发", settings.knowledge_graph.extract_max_parallelism, base_settings.knowledge_graph.extract_max_parallelism),
                lse("knowledge_graph.sync_after_docgen", "DocGen 后同步图谱", settings.knowledge_graph.sync_after_docgen, base_settings.knowledge_graph.sync_after_docgen),
            ],
        ),
        SettingSection(
            id="search",
            label="检索与联网",
            description="本地 RAG、外部检索服务、阅读器与重排配置。",
            entries=[
                lse("rag.top_k", "RAG 返回条数", settings.rag.top_k, base_settings.rag.top_k),
                lse("rag.similarity_threshold", "相似度阈值", settings.rag.similarity_threshold, base_settings.rag.similarity_threshold),
                lse("rag.rerank_model", "Rerank 模型", settings.rag.rerank_model, base_settings.rag.rerank_model),
                lse("rag.rerank_top_k", "Rerank 保留条数", settings.rag.rerank_top_k, base_settings.rag.rerank_top_k),
                _env_entry("rag.rerank_api_key", "重排服务密钥", "RAG_RERANK_API_KEY", "Rerank 服务密钥。", secret=True),
                lse("local_rag.priority", "本地资料优先", settings.local_rag.priority, base_settings.local_rag.priority),
                lse("local_rag.min_results", "本地命中阈值", settings.local_rag.min_results, base_settings.local_rag.min_results),
                lse("search.retriever_profile", "检索策略预设", settings.search.retriever_profile, base_settings.search.retriever_profile),
                lse("search.retrievers", "显式检索服务", settings.search.retrievers, base_settings.search.retrievers),
                lse("search.max_results_per_query", "单次查询最大结果数", settings.search.max_results_per_query, base_settings.search.max_results_per_query),
                lse("search.scrape_timeout_s", "网页抓取超时", settings.search.scrape_timeout_s, base_settings.search.scrape_timeout_s),
                lse("search.provider_timeout_s", "检索服务超时", settings.search.provider_timeout_s, base_settings.search.provider_timeout_s),
                lse("search.total_timeout_s", "总检索预算", settings.search.total_timeout_s, base_settings.search.total_timeout_s),
                lse("search.read_timeout_s", "阅读器超时", settings.search.read_timeout_s, base_settings.search.read_timeout_s),
                lse("search.parallel_retrievers", "并发检索", settings.search.parallel_retrievers, base_settings.search.parallel_retrievers),
                lse("search.max_parallel_retrievers", "最大并发检索服务数", settings.search.max_parallel_retrievers, base_settings.search.max_parallel_retrievers),
                lse("search.fusion_k", "融合参数 K", settings.search.fusion_k, base_settings.search.fusion_k),
                lse("search.runtime_cache_enabled", "检索运行时缓存", settings.search.runtime_cache_enabled, base_settings.search.runtime_cache_enabled),
                lse("search.runtime_cache_ttl_s", "检索缓存 TTL", settings.search.runtime_cache_ttl_s, base_settings.search.runtime_cache_ttl_s),
                lse("search.runtime_cache_max_entries", "检索缓存容量", settings.search.runtime_cache_max_entries, base_settings.search.runtime_cache_max_entries),
                _env_entry("search.tavily_key", "Tavily 密钥", "TAVILY_API_KEY", "Tavily 检索密钥。", secret=True),
                _env_entry("search.brave_key", "Brave Search 密钥", "BRAVE_SEARCH_API_KEY", "Brave Search 密钥。", secret=True),
                _env_entry("search.exa_key", "Exa 检索密钥", "EXA_API_KEY", "Exa 语义搜索密钥。", secret=True),
                _env_entry("search.bing_key", "Bing Search 密钥", "BING_API_KEY", "Bing Search 密钥。", secret=True),
                _env_entry("search.bocha_key", "Bocha 检索密钥", "BOCHA_API_KEY", "Bocha 搜索密钥。", secret=True),
                _env_entry("search.jina_key", "Jina 检索密钥", "JINA_API_KEY", "Jina Search / Reader 共用密钥。", secret=True),
                _env_entry("search.serper_key", "Serper 检索密钥", "SERPER_API_KEY", "Serper Google / Scholar 检索密钥。", secret=True),
                _env_entry("search.perplexity_key", "Perplexity 检索密钥", "PERPLEXITY_API_KEY", "Perplexity Sonar 检索密钥。", secret=True),
                _env_entry("search.openrouter_key", "OpenRouter 检索密钥", "OPENROUTER_API_KEY", "OpenRouter 搜索模型密钥。", secret=True),
                _env_entry("search.baidu_ai_key", "百度千帆检索密钥", "BAIDU_AI_SEARCH_API_KEY", "百度千帆 AI Search 密钥。", secret=True),
                _env_entry("search.google_key", "Google 检索密钥", "GOOGLE_API_KEY", "Google Custom Search API Key。", secret=True),
                _env_entry("search.google_cx", "Google 检索引擎 ID", "GOOGLE_CX_KEY", "Google Custom Search Engine ID。", secret=True),
                _env_entry("search.searchapi_key", "SearchApi 密钥", "SEARCHAPI_API_KEY", "SearchApi.io 检索密钥。", secret=True),
                _env_entry("search.serpapi_key", "SerpApi 密钥", "SERPAPI_API_KEY", "SerpApi 检索密钥。", secret=True),
                _env_entry("search.ncbi_key", "NCBI / PubMed 密钥", "NCBI_API_KEY", "NCBI / PubMed API Key，可选。", secret=True),
                _env_entry("search.mcp_tool", "MCP 检索工具名", "MCP_SEARCH_TOOL", "用于检索的 MCP 工具名。"),
                _env_entry("search.searxng_url", "SearXNG 地址", "SEARXNG_BASE_URL", "自建/可信 SearXNG 地址。"),
                _env_entry("reader.jina_enabled", "是否启用 Jina Reader", "JINA_READER_ENABLED", "是否启用 Jina Reader。"),
                _runtime_entry("search.retriever_profiles", "检索策略覆盖表", settings.search.retriever_profiles, "当前仅从代码默认值与可选项目 override 读取，作为高级配置保留。"),
            ],
        ),
        SettingSection(
            id="storage",
            label="数据库与存储",
            description="SQLite/Postgres 与 Local/S3 存储当前状态。",
            entries=[
                _env_entry("database.url", "数据库连接串", "DATABASE_URL", "云端模式需要配置数据库连接串。", secret=True),
                _runtime_entry("storage.backend", "存储后端", get_storage_backend()),
                _env_entry("storage.s3_bucket", "S3 Bucket", "S3_BUCKET"),
                _env_entry("storage.s3_endpoint", "S3 Endpoint", "S3_ENDPOINT"),
                _env_entry("storage.s3_public_base_url", "S3 公共访问地址", "S3_PUBLIC_BASE_URL"),
                _runtime_entry("storage.s3_addressing_style", "S3 地址风格", resolve_s3_addressing_style()),
                _runtime_entry("storage.s3_credential_mode", "S3 凭证模式", resolve_s3_credential_mode()),
                _env_entry("storage.s3_access_key", "S3 访问密钥", "S3_ACCESS_KEY", secret=True),
                _env_entry("storage.s3_secret_key", "S3 私钥", "S3_SECRET_KEY", secret=True),
                _env_entry("storage.dogecloud_access_key", "DogeCloud 访问密钥", "DOGECLOUD_API_ACCESS_KEY", secret=True),
                _env_entry("storage.dogecloud_space", "DogeCloud 空间名", "DOGECLOUD_SPACE_NAME"),
            ],
        ),
        SettingSection(
            id="observability",
            label="观测与安全",
            description="LangSmith、LLM 统计、安全护栏与并发控制。",
            entries=[
                lse("observability.tracing_enabled", "追踪总开关", settings.observability.tracing_enabled, base_settings.observability.tracing_enabled),
                lse("observability.llm_token_summary_enabled", "LLM Token 摘要", settings.observability.llm_token_summary_enabled, base_settings.observability.llm_token_summary_enabled),
                lse("observability.timing_top_k", "慢步骤展示数量", settings.observability.timing_top_k, base_settings.observability.timing_top_k),
                _env_entry("langsmith.tracing", "LangSmith 追踪开关", "LANGSMITH_TRACING"),
                _env_entry("langsmith.api_key", "LangSmith 密钥", "LANGSMITH_API_KEY", secret=True),
                _env_entry("langsmith.project", "LangSmith 项目名", "LANGSMITH_PROJECT"),
                _env_entry("langsmith.endpoint", "LangSmith 地址", "LANGSMITH_ENDPOINT"),
                lse(
                    "observability.langsmith_capture_inputs",
                    "追踪输入预览",
                    settings.observability.langsmith_capture_inputs,
                    base_settings.observability.langsmith_capture_inputs,
                    "空值表示按 APP_MODE 自动：local 开启，非本地关闭。",
                ),
                lse(
                    "observability.langsmith_capture_outputs",
                    "追踪输出预览",
                    settings.observability.langsmith_capture_outputs,
                    base_settings.observability.langsmith_capture_outputs,
                    "空值表示按 APP_MODE 自动：local 开启，非本地关闭。",
                ),
                lse(
                    "observability.langsmith_max_text_chars",
                    "追踪文本预览上限",
                    settings.observability.langsmith_max_text_chars,
                    base_settings.observability.langsmith_max_text_chars,
                    "",
                ),
                lse("observability.llm_observability_enabled", "LLM 调用统计", settings.observability.llm_observability_enabled, base_settings.observability.llm_observability_enabled),
                lse("observability.llm_observability_max_records", "LLM 统计保留条数", settings.observability.llm_observability_max_records, base_settings.observability.llm_observability_max_records),
                lse("runtime.llm_concurrency_limit", "LLM 并发限制", settings.runtime.llm_concurrency_limit, base_settings.runtime.llm_concurrency_limit),
                lse("runtime.default_token_budget", "默认上下文预算", settings.runtime.default_token_budget, base_settings.runtime.default_token_budget),
                lse("embedding.batch_size", "向量批大小", settings.embedding.batch_size, base_settings.embedding.batch_size),
                lse("embedding.batch_delay_s", "向量批延迟", settings.embedding.batch_delay_s, base_settings.embedding.batch_delay_s),
            ],
        ),
    ]

    return SettingsOverviewData(
        settings_source=settings_source,
        mode=mode,
        sections=sections,
        notes=[
            f"{PROJECT_SETTINGS_SOURCE_LABEL} 始终作为项目默认值保留；如需额外项目覆盖，可配置 {PROJECT_SETTINGS_ENV_NAME} 指向外部文件。",
            "本地模式下，服务端非敏感配置保存到 system_runtime_settings；环境变量写回本地 .env。",
            "云端模式下，普通用户仅能查看状态，不能修改任何服务端配置。",
        ],
    )


def update_user_settings_overview_data(
    *,
    session: Session,
    user_id: str,
    settings_payload: Mapping[str, Any],
    env_payload: Mapping[str, str | None] | None = None,
    reset: bool = False,
) -> SettingsOverviewData:
    """Persist local system settings and return fresh overview.

    Cloud-mode ordinary users do not have writable server-side settings.
    """

    env_updates = {
        _ENV_ENTRY_KEYS[key]: value
        for key, value in dict(env_payload or {}).items()
        if key in _ENV_ENTRY_KEYS
    }

    has_settings_updates = bool(dict(settings_payload))
    if not is_local_mode() and (env_updates or has_settings_updates or reset):
        raise AITeachMeError(
            detail="云端模式下普通用户无服务端设置写权限。",
            error_code="SETTINGS_EDIT_FORBIDDEN",
            status_code=403,
        )

    if env_updates:
        write_local_env_updates(env_updates)
        logger.info(
            "local_env_updated_via_settings",
            env_path=str(resolve_writable_local_env_path()),
            updated_keys=sorted(env_updates),
        )

    if reset:
        clear_system_runtime_settings(session)
        clear_user_runtime_settings(session, user_id=user_id)
        set_system_settings_override({})
    else:
        normalized_payload = _normalize_user_settings_payload(settings_payload)
        upsert_system_runtime_settings_payload(session, payload=normalized_payload)
        set_system_settings_override(normalized_payload)
    return build_settings_overview_data(session=session, user_id=user_id)
