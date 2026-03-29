"""应用配置。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.exceptions import MissingLLMApiKeyError

_EMBEDDING_DIM_MAP: dict[str, int] = {
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

_DEFAULT_EMBEDDING_DIM = 1536


class Settings(BaseSettings):
    """从环境变量加载应用配置。"""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),  # 优先根目录 .env，兼容子目录 .env
        env_file_encoding="utf-8",
        extra="ignore",  # 忽略未定义的变量（如前端的 VITE_* 变量）
    )

    llm_api_key: str | None = None
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-plus"
    ocr_model: str | None = None
    ocr_api_key: str | None = None
    ocr_base_url: str | None = None
    embedding_model: str = "text-embedding-v3"
    data_dir: str = "./data"
    max_upload_size_mb: int = 50
    ingest_parse_concurrency: int = 5
    ingest_parser_timeout_s: int = 90
    rag_top_k: int = 5
    rag_similarity_threshold: float = 0.3
    chat_history_turns: int = 10
    app_mode: str = "local"
    auth_enabled: bool = False
    app_version: str = "0.2.0"

    # ── AI 基础设施配置 ──
    model_overrides: dict[str, str] = {}
    llm_observability_enabled: bool = True
    tracing_enabled: bool = True
    guardrails_enabled: bool = True
    llm_cache_enabled: bool = False
    llm_cache_ttl_s: int = 3600
    llm_cache_max_entries: int = 1000
    llm_concurrency_limit: int = 20
    embedding_batch_size: int = 10
    embedding_batch_delay_s: float = 0.1
    default_token_budget: int = 4000
    docgen_max_parallel_chapters: int = 20
    docgen_io_parallelism: int = 20
    docgen_outline_fast_path_max_chunks: int = 1
    docgen_skip_llm_cleanse_for_clean_markdown: bool = True
    docgen_skip_llm_review_for_single_chapter: bool = True
    docgen_review_fast_path_max_chapters: int = 1
    docgen_review_retry_mode: str = "targeted"
    docgen_metadata_fallback_llm: bool = True

    # ── RAG 重排序配置 ──
    rag_rerank_model: str | None = None
    rag_rerank_api_key: str | None = None
    rag_rerank_base_url: str | None = None
    rag_rerank_top_k: int = 3

    # ── Digest 模型分级配置 ──
    llm_model_light: str | None = None  # 轻量任务（大纲、审阅、元数据）
    llm_model_extract: str | None = None  # 抽取任务（KG 实体/关系）

    # ── Digest 构建加速配置 ──
    digest_chapter_priors_timeout_ms: int = 0
    kg_extract_max_parallelism: int = 20

    @property
    def embedding_dim(self) -> int:
        """根据 embedding 模型推导维度。"""

        return _EMBEDDING_DIM_MAP.get(self.embedding_model, _DEFAULT_EMBEDDING_DIM)

    @property
    def is_cloud_mode(self) -> bool:
        """是否为云端模式。"""

        return self.app_mode.lower() == "cloud"

    @property
    def is_local_mode(self) -> bool:
        """是否为本地模式。"""

        return not self.is_cloud_mode

    @property
    def auth_ready(self) -> bool:
        """鉴权能力是否就绪。"""

        return False

    def require_llm_api_key(self) -> str:
        """读取并校验 LLM API Key。"""

        if not self.llm_api_key:
            raise MissingLLMApiKeyError()
        return self.llm_api_key

    def get_ocr_config(self) -> tuple[str, str, str]:
        """获取 OCR 配置（model, api_key, base_url）。

        如果未单独配置 OCR，则回退到 LLM 配置。
        """
        ocr_model = self.ocr_model or self.llm_model
        ocr_api_key = self.ocr_api_key or self.llm_api_key
        ocr_base_url = self.ocr_base_url or self.llm_base_url

        if not ocr_api_key:
            raise MissingLLMApiKeyError()

        return ocr_model, ocr_api_key, ocr_base_url

    @property
    def has_vision_ocr_model(self) -> bool:
        """检测是否配置了真正的视觉模型用于 OCR。

        如果 OCR_MODEL 未显式配置（回退到 LLM_MODEL），则认为没有视觉模型，
        因为大部分 LLM_MODEL（如 qwen-plus）不支持图片输入。
        只有显式设置了 OCR_MODEL 才启用 OCR。

        已知的视觉模型名称模式：qwen-vl-*, gpt-4o*, claude-3*, gemini-*
        """
        if not self.ocr_model:
            return False  # 未显式配置 OCR_MODEL → 不启用 OCR
        return True


@lru_cache
def get_settings() -> Settings:
    """返回缓存后的配置对象。"""

    return Settings()
