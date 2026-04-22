"""Declarative settings catalog for the system settings page."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CatalogEntryKind = Literal["setting", "env", "runtime"]


@dataclass(frozen=True)
class SettingsCatalogEntry:
    kind: CatalogEntryKind
    key: str
    label: str
    description: str = ""
    ui_group: str = ""
    ui_order: int = 0
    env_name: str | None = None
    secret: bool = False
    restart_required: bool = True
    editable_in_local: bool = True
    editable_in_cloud: bool = False
    value_path: str | None = None


@dataclass(frozen=True)
class SettingsCatalogSection:
    id: str
    label: str
    description: str
    entries: tuple[SettingsCatalogEntry, ...]


def setting(
    key: str,
    label: str,
    *,
    description: str = "",
    ui_group: str,
    ui_order: int,
    editable_in_local: bool = True,
    editable_in_cloud: bool = False,
) -> SettingsCatalogEntry:
    return SettingsCatalogEntry(
        kind="setting",
        key=key,
        label=label,
        description=description,
        ui_group=ui_group,
        ui_order=ui_order,
        editable_in_local=editable_in_local,
        editable_in_cloud=editable_in_cloud,
        restart_required=False,
    )


def env(
    key: str,
    label: str,
    env_name: str,
    *,
    description: str = "",
    ui_group: str,
    ui_order: int,
    secret: bool = False,
    restart_required: bool = True,
    value_path: str | None = None,
) -> SettingsCatalogEntry:
    return SettingsCatalogEntry(
        kind="env",
        key=key,
        label=label,
        env_name=env_name,
        description=description,
        ui_group=ui_group,
        ui_order=ui_order,
        secret=secret,
        restart_required=restart_required,
        value_path=value_path,
    )


def runtime(
    key: str,
    label: str,
    *,
    value_path: str,
    description: str = "",
    ui_group: str,
    ui_order: int,
) -> SettingsCatalogEntry:
    return SettingsCatalogEntry(
        kind="runtime",
        key=key,
        label=label,
        description=description,
        ui_group=ui_group,
        ui_order=ui_order,
        restart_required=False,
        value_path=value_path,
    )


SETTINGS_CATALOG: tuple[SettingsCatalogSection, ...] = (
    SettingsCatalogSection(
        id="connection",
        label="连接",
        description="模型服务连接与密钥状态。",
        entries=(
            env(
                "llm.provider",
                "模型提供商",
                "LLM_PROVIDER",
                description="可选。留空时会根据模型地址自动识别 Anthropic、Gemini、Azure、vLLM、Ollama 或 OpenAI-compatible。",
                value_path="llm_provider",
                restart_required=False,
                ui_group="服务端连接",
                ui_order=5,
            ),
            env(
                "llm.base_url",
                "模型服务地址",
                "LLM_BASE_URL",
                description="统一模型接入地址。OpenAI-compatible、Anthropic、Gemini、Azure、vLLM、Ollama 等上游都从这里接入。",
                restart_required=False,
                ui_group="服务端连接",
                ui_order=10,
            ),
            env(
                "llm.api_key",
                "模型服务密钥",
                "LLM_API_KEY",
                description="模型访问密钥，只显示是否已配置。Ollama、LM Studio、本地 vLLM 等无鉴权场景可留空。",
                secret=True,
                restart_required=False,
                ui_group="服务端连接",
                ui_order=20,
            ),
            env(
                "llm.api_version",
                "模型 API 版本",
                "LLM_API_VERSION",
                description="主要给 Azure 等需要 API Version 的上游使用；普通 OpenAI-compatible 场景可留空。",
                value_path="llm_api_version",
                restart_required=False,
                ui_group="服务端连接",
                ui_order=30,
            ),
        ),
    ),
    SettingsCatalogSection(
        id="models",
        label="模型路由",
        description="模型名默认来自代码默认值与可选项目 override；本地模式下页面修改会保存为系统级运行覆盖。",
        entries=(
            setting(
                "models.primary",
                "主模型",
                description="主要生成、对话与批改任务使用。Azure 场景下通常填写 deployment 名称。",
                ui_group="模型路由",
                ui_order=10,
            ),
            setting(
                "models.reason",
                "推理模型",
                description="深度推理与规划使用；留空时回退到主模型。",
                ui_group="模型路由",
                ui_order=20,
            ),
            setting(
                "models.light",
                "轻量模型",
                description="分类、摘要和批量轻任务使用；留空时回退到主模型。",
                ui_group="模型路由",
                ui_order=30,
            ),
            setting(
                "models.extract",
                "抽取模型",
                description="知识抽取专用；留空时回退到轻量模型或主模型。",
                ui_group="模型路由",
                ui_order=40,
            ),
            setting(
                "models.embedding",
                "向量模型",
                description="不提供 embedding 的上游可留空或接独立向量服务。",
                ui_group="模型路由",
                ui_order=50,
            ),
            setting(
                "models.embedding_dim",
                "向量维度覆盖",
                description="未知 embedding 模型可在这里显式填写维度；已知模型通常可留空自动推导。",
                ui_group="模型路由",
                ui_order=60,
            ),
            setting(
                "models.ocr",
                "视觉 OCR 模型",
                description="留空时使用主模型；密钥和服务地址复用统一模型接入配置。",
                ui_group="模型路由",
                ui_order=70,
            ),
            setting(
                "models.image_generation",
                "图片生成模型",
                description="留空表示未启用服务端图片生成能力。",
                ui_group="模型路由",
                ui_order=80,
            ),
            runtime(
                "runtime.embedding_dim_resolved",
                "向量维度",
                value_path="settings.embedding_dim",
                ui_group="运行推导",
                ui_order=90,
            ),
        ),
    ),
    SettingsCatalogSection(
        id="learning",
        label="学习引擎",
        description="上传限制、学习规划、知识文档策略与图谱联动开关。",
        entries=(
            setting(
                "ingest.max_upload_size_mb",
                "最大上传大小",
                ui_group="上传限制",
                ui_order=10,
            ),
            setting(
                "ingest.max_files_per_upload",
                "单次最大文件数",
                ui_group="上传限制",
                ui_order=20,
            ),
            env(
                "mineru.api_token",
                "MinerU 服务密钥",
                "MINERU_API_TOKEN",
                description="服务端 MinerU Token，只显示是否已配置。",
                secret=True,
                ui_group="解析服务",
                ui_order=30,
            ),
            setting(
                "planner.default_digest_mode",
                "默认 Digest 模式",
                ui_group="学习规划",
                ui_order=40,
            ),
            setting(
                "planner.sprint.min_chapters",
                "冲刺最少章节",
                ui_group="冲刺模式",
                ui_order=50,
            ),
            setting(
                "planner.sprint.max_chapters",
                "冲刺最多章节",
                ui_group="冲刺模式",
                ui_order=60,
            ),
            setting(
                "planner.sprint.target_length",
                "冲刺目标长度",
                ui_group="冲刺模式",
                ui_order=70,
            ),
            setting(
                "planner.systematic.min_chapters",
                "系统最少章节",
                ui_group="系统模式",
                ui_order=80,
            ),
            setting(
                "planner.systematic.max_chapters",
                "系统最多章节",
                ui_group="系统模式",
                ui_order=90,
            ),
            setting(
                "planner.systematic.target_length",
                "系统目标长度",
                ui_group="系统模式",
                ui_order=100,
            ),
            setting(
                "docgen.allow_external_search",
                "知识文档允许外部搜索",
                ui_group="知识文档",
                ui_order=110,
            ),
            setting(
                "docgen.generate_cover_image",
                "知识文档生成封面",
                description="启用后会为知识文档生成一张横向、抽象、无文字的艺术风景封面，并置于文档顶部。",
                ui_group="知识文档",
                ui_order=120,
            ),
            setting(
                "interact.history_turns",
                "伴读历史轮数",
                ui_group="伴读",
                ui_order=130,
            ),
            setting(
                "knowledge_graph.sync_after_docgen",
                "DocGen 后同步图谱",
                ui_group="图谱联动",
                ui_order=140,
            ),
        ),
    ),
    SettingsCatalogSection(
        id="search",
        label="检索与联网",
        description="本地 RAG、检索策略与外部 Provider 状态。",
        entries=(
            setting(
                "rag.top_k",
                "RAG 返回条数",
                ui_group="本地 RAG",
                ui_order=10,
            ),
            setting(
                "rag.similarity_threshold",
                "相似度阈值",
                ui_group="本地 RAG",
                ui_order=20,
            ),
            setting(
                "rag.rerank_model",
                "Rerank 模型",
                ui_group="本地 RAG",
                ui_order=30,
            ),
            setting(
                "rag.rerank_top_k",
                "Rerank 保留条数",
                ui_group="本地 RAG",
                ui_order=40,
            ),
            env(
                "rag.rerank_api_key",
                "重排服务密钥",
                "RAG_RERANK_API_KEY",
                description="Rerank 服务密钥。",
                secret=True,
                ui_group="重排服务",
                ui_order=50,
            ),
            setting(
                "local_rag.priority",
                "本地资料优先",
                ui_group="本地 RAG",
                ui_order=60,
            ),
            setting(
                "local_rag.min_results",
                "本地命中阈值",
                ui_group="本地 RAG",
                ui_order=70,
            ),
            setting(
                "search.retriever_profile",
                "检索策略预设",
                ui_group="检索策略",
                ui_order=80,
            ),
            env("search.tavily_key", "Tavily 密钥", "TAVILY_API_KEY", description="Tavily 搜索密钥。", secret=True, ui_group="检索 Provider", ui_order=90),
            env("search.brave_key", "Brave Search 密钥", "BRAVE_SEARCH_API_KEY", description="Brave Search 密钥。", secret=True, ui_group="检索 Provider", ui_order=100),
            env("search.exa_key", "Exa 搜索密钥", "EXA_API_KEY", description="Exa 语义搜索密钥。", secret=True, ui_group="检索 Provider", ui_order=110),
            env("search.bing_key", "Bing Search 密钥", "BING_API_KEY", description="Bing Search 密钥。", secret=True, ui_group="检索 Provider", ui_order=120),
            env("search.bocha_key", "Bocha 搜索密钥", "BOCHA_API_KEY", description="Bocha 搜索密钥。", secret=True, ui_group="检索 Provider", ui_order=130),
            env("search.jina_key", "Jina 搜索密钥", "JINA_API_KEY", description="Jina Search / Reader 共用密钥。", secret=True, ui_group="检索 Provider", ui_order=140),
            env("search.serper_key", "Serper 搜索密钥", "SERPER_API_KEY", description="Serper Google / Scholar 搜索密钥。", secret=True, ui_group="检索 Provider", ui_order=150),
            env("search.perplexity_key", "Perplexity 搜索密钥", "PERPLEXITY_API_KEY", description="Perplexity Sonar 搜索密钥。", secret=True, ui_group="检索 Provider", ui_order=160),
            env("search.openrouter_key", "OpenRouter 搜索密钥", "OPENROUTER_API_KEY", description="OpenRouter 搜索模型密钥。", secret=True, ui_group="检索 Provider", ui_order=170),
            env("search.baidu_ai_key", "百度千帆搜索密钥", "BAIDU_AI_SEARCH_API_KEY", description="百度千帆 AI Search 密钥。", secret=True, ui_group="检索 Provider", ui_order=180),
            env("search.google_key", "Google 搜索密钥", "GOOGLE_API_KEY", description="Google Custom Search API Key。", secret=True, ui_group="检索 Provider", ui_order=190),
            env("search.google_cx", "Google 搜索引擎 ID", "GOOGLE_CX_KEY", description="Google Custom Search Engine ID。", secret=True, ui_group="检索 Provider", ui_order=200),
            env("search.searchapi_key", "SearchApi 密钥", "SEARCHAPI_API_KEY", description="SearchApi.io 搜索密钥。", secret=True, ui_group="检索 Provider", ui_order=210),
            env("search.serpapi_key", "SerpApi 密钥", "SERPAPI_API_KEY", description="SerpApi 搜索密钥。", secret=True, ui_group="检索 Provider", ui_order=220),
            env("search.ncbi_key", "NCBI / PubMed 密钥", "NCBI_API_KEY", description="NCBI / PubMed API Key，可选。", secret=True, ui_group="检索 Provider", ui_order=230),
            env("search.mcp_tool", "MCP 搜索工具名", "MCP_SEARCH_TOOL", description="用于检索的 MCP 工具名。", ui_group="检索 Provider", ui_order=240),
            env("search.searxng_url", "SearXNG 地址", "SEARXNG_BASE_URL", description="自建或可信 SearXNG 地址。", ui_group="检索 Provider", ui_order=250),
            env("reader.jina_enabled", "是否启用 Jina Reader", "JINA_READER_ENABLED", description="是否启用 Jina Reader。", ui_group="阅读器", ui_order=260),
        ),
    ),
    SettingsCatalogSection(
        id="ops",
        label="部署状态",
        description="运行模式、鉴权、数据库与对象存储状态。",
        entries=(
            runtime(
                "runtime.mode",
                "运行模式",
                value_path="mode",
                description="由 APP_MODE 解析得到。",
                ui_group="运行状态",
                ui_order=10,
            ),
            env(
                "runtime.app_mode_raw",
                "应用运行模式原值",
                "APP_MODE",
                description="未设置时按本地优先策略解析。",
                ui_group="运行状态",
                ui_order=20,
            ),
            runtime(
                "runtime.version",
                "应用版本",
                value_path="app_version",
                ui_group="运行状态",
                ui_order=30,
            ),
            runtime(
                "settings.source",
                "项目设置来源",
                value_path="settings_source",
                ui_group="运行状态",
                ui_order=40,
            ),
            env(
                "auth.enabled_raw",
                "鉴权开关原值",
                "AUTH_ENABLED",
                description="为空时按 APP_MODE 自动推导。",
                ui_group="鉴权",
                ui_order=50,
            ),
            runtime(
                "runtime.auth_enabled_effective",
                "鉴权生效值",
                value_path="auth_enabled_effective",
                description="空值时按运行模式自动推导。",
                ui_group="鉴权",
                ui_order=60,
            ),
            env(
                "database.url",
                "数据库连接串",
                "DATABASE_URL",
                description="云端模式需要配置数据库连接串。",
                secret=True,
                ui_group="数据库与对象存储",
                ui_order=70,
            ),
            runtime(
                "storage.backend",
                "存储后端",
                value_path="storage_backend",
                ui_group="数据库与对象存储",
                ui_order=80,
            ),
            env("storage.s3_bucket", "S3 Bucket", "S3_BUCKET", ui_group="数据库与对象存储", ui_order=90),
            env("storage.s3_endpoint", "S3 Endpoint", "S3_ENDPOINT", ui_group="数据库与对象存储", ui_order=100),
            env("storage.s3_public_base_url", "S3 公共访问地址", "S3_PUBLIC_BASE_URL", ui_group="数据库与对象存储", ui_order=110),
            runtime(
                "storage.s3_addressing_style",
                "S3 地址风格",
                value_path="s3_addressing_style",
                ui_group="数据库与对象存储",
                ui_order=120,
            ),
            runtime(
                "storage.s3_credential_mode",
                "S3 凭证模式",
                value_path="s3_credential_mode",
                ui_group="数据库与对象存储",
                ui_order=130,
            ),
            env("storage.s3_access_key", "S3 访问密钥", "S3_ACCESS_KEY", secret=True, ui_group="数据库与对象存储", ui_order=140),
            env("storage.s3_secret_key", "S3 私钥", "S3_SECRET_KEY", secret=True, ui_group="数据库与对象存储", ui_order=150),
            env("storage.dogecloud_access_key", "DogeCloud 访问密钥", "DOGECLOUD_API_ACCESS_KEY", secret=True, ui_group="数据库与对象存储", ui_order=160),
            env("storage.dogecloud_space", "DogeCloud 空间名", "DOGECLOUD_SPACE_NAME", ui_group="数据库与对象存储", ui_order=170),
        ),
    ),
    SettingsCatalogSection(
        id="observability",
        label="观测调试",
        description="追踪、Token 摘要与 LangSmith 接入状态。",
        entries=(
            setting(
                "observability.tracing_enabled",
                "追踪总开关",
                ui_group="观测开关",
                ui_order=10,
            ),
            setting(
                "observability.llm_token_summary_enabled",
                "LLM Token 摘要",
                ui_group="观测开关",
                ui_order=20,
            ),
            setting(
                "observability.llm_observability_enabled",
                "LLM 调用统计",
                ui_group="观测开关",
                ui_order=30,
            ),
            env("langsmith.tracing", "LangSmith 追踪开关", "LANGSMITH_TRACING", ui_group="LangSmith", ui_order=40),
            env("langsmith.api_key", "LangSmith 密钥", "LANGSMITH_API_KEY", secret=True, ui_group="LangSmith", ui_order=50),
            env("langsmith.project", "LangSmith 项目名", "LANGSMITH_PROJECT", ui_group="LangSmith", ui_order=60),
            env("langsmith.endpoint", "LangSmith 地址", "LANGSMITH_ENDPOINT", ui_group="LangSmith", ui_order=70),
        ),
    ),
)

ENV_ENTRY_KEY_MAP: dict[str, str] = {
    entry.key: entry.env_name
    for section in SETTINGS_CATALOG
    for entry in section.entries
    if entry.kind == "env" and entry.env_name
}


def build_settings_notes(
    *,
    project_settings_env_name: str,
    project_settings_source_label: str,
) -> list[str]:
    return [
        f"{project_settings_source_label} 始终作为项目默认值保留；如需额外项目覆盖，可配置 {project_settings_env_name} 指向外部文件。",
        "本地模式下，服务端非敏感配置保存到 system_runtime_settings；环境变量写回本地 .env。",
        "云端模式下，普通用户只能查看状态，不能修改任何服务端配置。",
        "多供应商场景下，后端会优先按 LLM_PROVIDER 或 LLM_BASE_URL 推断默认模型；如果手动覆盖 models.*，仍以手动覆盖为准。",
        "Anthropic、DeepSeek、Kimi、GLM、MiniMax、Doubao、SiliconFlow 等上游的 embedding 能力并不统一；当未配置 embedding 时，系统仍可工作，但会跳过向量检索相关能力。",
        "Azure 场景通常还需要配置 API Version；本地 Ollama、vLLM、LM Studio 等无鉴权上游可以不填 API Key。",
    ]


__all__ = [
    "ENV_ENTRY_KEY_MAP",
    "SETTINGS_CATALOG",
    "SettingsCatalogEntry",
    "SettingsCatalogSection",
    "build_settings_notes",
]
