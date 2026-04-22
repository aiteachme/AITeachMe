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
        label="模型接入",
        description="统一模型网关、提供商识别与必要授权。",
        entries=(
            env(
                "llm.api_key",
                "模型网关密钥",
                "LLM_API_KEY",
                description="模型访问密钥，只显示是否已配置。Ollama、LM Studio、本地 vLLM 等无鉴权场景可留空。",
                secret=True,
                restart_required=False,
                ui_group="统一模型接入",
                ui_order=5,
            ),
            env(
                "llm.base_url",
                "模型网关地址",
                "LLM_BASE_URL",
                description="统一模型接入地址。OpenAI-compatible、Anthropic、Gemini、Azure、vLLM、Ollama 等上游都从这里接入。",
                restart_required=False,
                ui_group="统一模型接入",
                ui_order=10,
            ),
            env(
                "llm.provider",
                "提供商覆盖",
                "LLM_PROVIDER",
                description="仅在自动识别错误时填写；通常留空即可按模型地址自动识别。",
                value_path="llm_provider",
                restart_required=False,
                ui_group="统一模型接入",
                ui_order=15,
            ),
            env(
                "llm.api_version",
                "API 版本（Azure 等）",
                "LLM_API_VERSION",
                description="主要给 Azure 等需要 API Version 的上游使用；普通 OpenAI-compatible 场景可留空。",
                value_path="llm_api_version",
                restart_required=False,
                ui_group="统一模型接入",
                ui_order=20,
            ),
        ),
    ),
    SettingsCatalogSection(
        id="models",
        label="模型路由",
        description="文本生成、视觉理解、文档解析与检索能力模型。默认只预填文本生成与 embedding，其他能力按需启用。",
        entries=(
            setting(
                "models.primary",
                "主文本模型",
                description="主要生成、对话与批改任务使用。Azure 场景下通常填写 deployment 名称。",
                ui_group="文本生成",
                ui_order=10,
            ),
            setting(
                "models.reason",
                "推理模型",
                description="深度推理与规划使用；留空时回退到主模型。",
                ui_group="文本生成",
                ui_order=20,
            ),
            setting(
                "models.light",
                "轻量模型",
                description="分类、摘要和批量轻任务使用；留空时回退到主模型。",
                ui_group="文本生成",
                ui_order=30,
            ),
            setting(
                "models.vision",
                "视觉理解模型",
                description="处理图片、截图、图表和示意图等视觉理解任务；未配置时不处理直接上传的图片输入。",
                ui_group="视觉理解",
                ui_order=40,
            ),
            setting(
                "models.ocr",
                "文档 OCR 模型",
                description="处理扫描 PDF、教材截图、板书照片等高文本密度文档解析；未配置时跳过文档 OCR 增强。",
                ui_group="文档解析",
                ui_order=50,
            ),
            setting(
                "models.embedding",
                "Embedding 模型",
                description="向量检索使用；不提供 embedding 的上游可留空。",
                ui_group="检索与排序",
                ui_order=60,
            ),
            setting(
                "models.embedding_dim",
                "Embedding 维度覆盖",
                description="未知 embedding 模型可在这里显式填写维度；已知模型通常可留空自动推导。",
                ui_group="检索与排序",
                ui_order=70,
            ),
            setting(
                "models.rerank",
                "重排序模型",
                description="RAG 重排使用，复用统一模型网关与凭证，不需要单独的 Rerank 服务。",
                ui_group="检索与排序",
                ui_order=80,
            ),
            setting(
                "models.image_generation",
                "文生图模型",
                description="留空表示未启用服务端图片生成能力。",
                ui_group="多媒体生成",
                ui_order=90,
            ),
            setting(
                "models.speech_to_text",
                "音转文模型",
                description="语音转文本能力预留位；留空表示未启用。",
                ui_group="多媒体生成",
                ui_order=100,
            ),
            setting(
                "models.text_to_speech",
                "文转音模型",
                description="文本转语音能力预留位；留空表示未启用。",
                ui_group="多媒体生成",
                ui_order=110,
            ),
            setting(
                "models.video_generation",
                "视频生成模型",
                description="视频生成能力预留位；留空表示未启用。",
                ui_group="多媒体生成",
                ui_order=120,
            ),
            runtime(
                "runtime.embedding_dim_resolved",
                "Embedding 维度",
                value_path="settings.embedding_dim",
                ui_group="运行推导",
                ui_order=130,
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
                "MinerU API Token",
                "MINERU_API_TOKEN",
                description="服务端 MinerU Token，只显示是否已配置。",
                secret=True,
                ui_group="解析服务授权",
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
        description="本地 RAG 策略与外部联网检索授权。",
        entries=(
            setting(
                "rag.top_k",
                "RAG 返回条数",
                ui_group="本地资料检索",
                ui_order=10,
            ),
            setting(
                "rag.similarity_threshold",
                "相似度阈值",
                ui_group="本地资料检索",
                ui_order=20,
            ),
            setting(
                "models.rerank",
                "Rerank 模型",
                description="可选。配置后会对本地检索结果再做一次重排序，提高相关性。",
                ui_group="本地资料检索",
                ui_order=30,
            ),
            setting(
                "rag.rerank_top_k",
                "Rerank 保留条数",
                description="启用重排序模型后，最终保留的候选条数。",
                ui_group="本地资料检索",
                ui_order=40,
            ),
            setting(
                "local_rag.priority",
                "本地资料优先",
                ui_group="本地资料检索",
                ui_order=50,
            ),
            setting(
                "local_rag.min_results",
                "本地命中阈值",
                ui_group="本地资料检索",
                ui_order=60,
            ),
        ),
    ),
    SettingsCatalogSection(
        id="observability",
        label="观测与集成",
        description="观测开关与 LangSmith 接入状态。",
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
            env("langsmith.tracing", "LangSmith 上报", "LANGSMITH_TRACING", ui_group="LangSmith 授权", ui_order=40),
            env("langsmith.api_key", "LangSmith 密钥", "LANGSMITH_API_KEY", secret=True, ui_group="LangSmith 授权", ui_order=50),
            env("langsmith.project", "LangSmith 项目名", "LANGSMITH_PROJECT", ui_group="LangSmith 授权", ui_order=60),
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
        "APP_MODE、DATABASE_URL、对象存储等部署级变量不再出现在设置页里，请通过 .env、本地样例文件或部署平台环境变量管理。",
        "多供应商场景下，后端会优先按 LLM_PROVIDER 或 LLM_BASE_URL 推断默认模型；如果手动覆盖 models.*，仍以手动覆盖为准。",
        "视觉理解模型用于图片、图表和截图语义理解；文档 OCR 模型用于扫描 PDF、教材页和板书照片的文本/版面提取，两者可以配置为同一个模型，但能力语义保持分开。",
        "RAG 重排序直接复用统一模型网关与凭证；只需要填写 models.rerank，不需要再单独配置一套 Rerank 服务。",
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
