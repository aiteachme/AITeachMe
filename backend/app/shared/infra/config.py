"""应用配置。"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.shared.infra.exceptions import MissingLLMApiKeyError

_EMBEDDING_DIM_MAP: dict[str, int] = {
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
    app_mode: str = "auto"
    auth_enabled: bool = True
    auth_token_secret: str = "aiteachme-dev-token-secret"
    auth_token_ttl_hours: int = 24 * 30
    guest_token_ttl_hours: int = 24 * 30
    guest_cookie_name: str = "atm_guest_token"
    guest_cookie_secure: bool | None = None
    guest_cookie_samesite: str = "auto"
    smtp_host: str | None = None
    smtp_port: int = 465
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_from_name: str = "AITeachMe"
    smtp_use_ssl: bool = True
    smtp_use_starttls: bool = False
    smtp_address_family: str = "ipv4"
    smtp_timeout_s: int = 15
    auth_email_code_ttl_s: int = 600
    auth_email_code_resend_interval_s: int = 60
    auth_email_code_max_attempts: int = 5
    app_version: str = "0.2.0"
    export_openapi_on_startup: bool = False
    cors_allowed_origins: str = ""  # 逗号分隔，留空使用默认白名单

    # ── 云端数据库 ──
    database_url: str | None = None  # PostgreSQL 连接串，cloud 模式必填

    # ── 对象存储 (S3 兼容) ──
    storage_backend: str = "local"  # "local" | "s3"
    s3_bucket: str | None = None
    s3_endpoint: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str | None = None
    s3_public_base_url: str | None = None  # 可选 CDN 域名
    s3_addressing_style: str = "auto"  # "auto" | "virtual" | "path"

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
    digest_timing_top_k: int = 5
    digest_token_summary_enabled: bool = True
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

        if not self.normalized_embedding_model:
            return 0
        return _EMBEDDING_DIM_MAP.get(self.normalized_embedding_model, _DEFAULT_EMBEDDING_DIM)

    @property
    def normalized_embedding_model(self) -> str | None:
        """返回去空白后的 embedding 模型名。"""

        value = (self.embedding_model or "").strip()
        return value or None

    @property
    def embedding_configured(self) -> bool:
        """当前是否配置了 embedding 模型。"""

        return self.normalized_embedding_model is not None

    @property
    def resolved_app_mode(self) -> str:
        """返回当前运行环境下的最终模式。"""

        normalized = (self.app_mode or "auto").strip().lower()
        if normalized in {"local", "cloud"}:
            return normalized
        if os.getenv("RENDER") or os.getenv("RENDER_EXTERNAL_URL"):
            return "cloud"
        return "local"

    @property
    def is_cloud_mode(self) -> bool:
        """是否为云端模式。"""

        return self.resolved_app_mode == "cloud"

    @property
    def is_local_mode(self) -> bool:
        """是否为本地模式。"""

        return not self.is_cloud_mode

    @property
    def storage_is_s3(self) -> bool:
        """是否使用 S3 兼容对象存储。"""

        return self.storage_backend.lower() == "s3"

    @property
    def resolved_s3_addressing_style(self) -> str:
        """返回当前 S3 客户端应使用的 bucket 寻址风格。"""

        normalized = (self.s3_addressing_style or "auto").strip().lower()
        if normalized in {"auto", "virtual", "path"}:
            return normalized
        return "auto"

    @property
    def resolved_guest_cookie_samesite(self) -> str:
        """返回当前部署环境下可工作的 SameSite 策略。"""

        normalized = (self.guest_cookie_samesite or "auto").strip().lower()
        if normalized in {"lax", "strict", "none"}:
            return normalized
        return "none" if self.is_cloud_mode else "lax"

    @property
    def resolved_guest_cookie_secure(self) -> bool:
        """返回当前 guest cookie 是否必须启用 Secure。"""

        if self.guest_cookie_secure is not None:
            return self.guest_cookie_secure
        return self.is_cloud_mode or self.resolved_guest_cookie_samesite == "none"

    @property
    def auth_ready(self) -> bool:
        """鉴权能力是否就绪。"""

        return True

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
