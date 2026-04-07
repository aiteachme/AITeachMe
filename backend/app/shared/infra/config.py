"""Application configuration."""

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
    """Load application settings from environment variables."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),  # Prefer the repo-root .env, with backend-local fallback.
        env_file_encoding="utf-8",
        extra="ignore",  # Ignore unrelated variables such as frontend VITE_* settings.
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
    cors_allowed_origins: str = ""  # Comma-separated allowed origins; empty uses the default allowlist.

    # Cloud database settings.
    database_url: str | None = None  # PostgreSQL connection string; required in cloud mode.

    # Object storage settings (S3-compatible).
    storage_backend: str = "local"  # "local" | "s3"
    s3_bucket: str | None = None
    s3_endpoint: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_session_token: str | None = None
    s3_region: str | None = None
    s3_public_base_url: str | None = None  # Optional public CDN base URL.
    s3_addressing_style: str = "virtual"  # "virtual" | "path" | "auto"
    s3_credential_mode: str = "auto"  # "auto" | "static" | "dogecloud_tmp_token"
    dogecloud_api_access_key: str | None = None
    dogecloud_api_secret_key: str | None = None
    dogecloud_api_base_url: str = "https://api.dogecloud.com"
    dogecloud_space_name: str | None = None
    dogecloud_tmp_token_path: str = "/auth/tmp_token.json"
    dogecloud_tmp_token_channel: str = "OSS_FULL"
    dogecloud_tmp_token_scope: str = "*"

    # AI infrastructure settings.
    model_overrides: dict[str, str] = {}
    llm_observability_enabled: bool = True
    tracing_enabled: bool = True
    langsmith_tracing: bool = False
    langsmith_project: str = "AITeachMe"
    langsmith_capture_inputs: bool = False
    langsmith_capture_outputs: bool = False
    langsmith_max_text_chars: int = 2000
    guardrails_enabled: bool = True
    llm_cache_enabled: bool = False
    llm_cache_ttl_s: int = 3600
    llm_cache_max_entries: int = 1000
    llm_observability_max_records: int = 5000
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

    # RAG reranking settings.
    rag_rerank_model: str | None = None
    rag_rerank_api_key: str | None = None
    rag_rerank_base_url: str | None = None
    rag_rerank_top_k: int = 3

    # Digest model tier settings.
    llm_model_light: str | None = None  # Lightweight model for low-complexity tasks.
    llm_model_extract: str | None = None  # Extraction model for KG entity and relation work.
    # Digest acceleration settings.
    digest_chapter_priors_timeout_ms: int = 0
    kg_extract_max_parallelism: int = 20

    @property
    def embedding_dim(self) -> int:
        """Infer the embedding dimension from the configured model."""

        if not self.normalized_embedding_model:
            return 0
        return _EMBEDDING_DIM_MAP.get(self.normalized_embedding_model, _DEFAULT_EMBEDDING_DIM)

    @property
    def normalized_embedding_model(self) -> str | None:
        """Return the normalized embedding model name."""

        value = (self.embedding_model or "").strip()
        return value or None

    @property
    def embedding_configured(self) -> bool:
        """Return whether an embedding model is configured."""

        return self.normalized_embedding_model is not None

    @property
    def resolved_app_mode(self) -> str:
        """Resolve the final runtime app mode."""

        normalized = (self.app_mode or "auto").strip().lower()
        if normalized in {"local", "cloud"}:
            return normalized
        if os.getenv("RENDER") or os.getenv("RENDER_EXTERNAL_URL"):
            return "cloud"
        return "local"

    @property
    def is_cloud_mode(self) -> bool:
        """Return whether the app is running in cloud mode."""

        return self.resolved_app_mode == "cloud"

    @property
    def is_local_mode(self) -> bool:
        """Return whether the app is running in local mode."""

        return not self.is_cloud_mode

    @property
    def storage_is_s3(self) -> bool:
        """Return whether object storage uses an S3-compatible backend."""

        return self.storage_backend.lower() == "s3"

    @property
    def resolved_s3_addressing_style(self) -> str:
        """Resolve the S3 bucket addressing style."""

        normalized = (self.s3_addressing_style or "virtual").strip().lower()
        if normalized in {"auto", "virtual", "path"}:
            return normalized
        return "virtual"

    @property
    def resolved_s3_credential_mode(self) -> str:
        """Resolve the credential mode used by the S3 client."""

        normalized = (self.s3_credential_mode or "auto").strip().lower()
        if normalized in {"static", "dogecloud_tmp_token"}:
            return normalized
        if self.dogecloud_api_access_key and self.dogecloud_api_secret_key:
            return "dogecloud_tmp_token"
        return "static"

    @property
    def s3_uses_dogecloud_tmp_token(self) -> bool:
        """Return whether S3 credentials come from DogeCloud tmp_token."""

        return self.resolved_s3_credential_mode == "dogecloud_tmp_token"

    @property
    def resolved_dogecloud_api_access_key(self) -> str | None:
        """Resolve the DogeCloud API access key."""

        if self.dogecloud_api_access_key:
            return self.dogecloud_api_access_key
        if self.s3_uses_dogecloud_tmp_token:
            return self.s3_access_key
        return None

    @property
    def resolved_dogecloud_api_secret_key(self) -> str | None:
        """Resolve the DogeCloud API secret key."""

        if self.dogecloud_api_secret_key:
            return self.dogecloud_api_secret_key
        if self.s3_uses_dogecloud_tmp_token:
            return self.s3_secret_key
        return None

    @property
    def resolved_dogecloud_space_name(self) -> str | None:
        """Resolve the DogeCloud space name used for tmp_token requests."""

        if self.dogecloud_space_name:
            return self.dogecloud_space_name
        return self.s3_bucket

    @property
    def resolved_guest_cookie_samesite(self) -> str:
        """Resolve the effective SameSite policy for the guest cookie."""

        normalized = (self.guest_cookie_samesite or "auto").strip().lower()
        if normalized in {"lax", "strict", "none"}:
            return normalized
        return "none" if self.is_cloud_mode else "lax"

    @property
    def resolved_guest_cookie_secure(self) -> bool:
        """Resolve whether the guest cookie must be marked Secure."""

        if self.guest_cookie_secure is not None:
            return self.guest_cookie_secure
        return self.is_cloud_mode or self.resolved_guest_cookie_samesite == "none"

    @property
    def auth_ready(self) -> bool:
        """Return whether auth prerequisites are ready."""

        return True

    def require_llm_api_key(self) -> str:
        """Return the configured LLM API key or raise an error."""

        if not self.llm_api_key:
            raise MissingLLMApiKeyError()
        return self.llm_api_key

    def get_ocr_config(self) -> tuple[str, str, str]:
        """Return the OCR configuration tuple: model, api_key, base_url."""

        ocr_model = self.ocr_model or self.llm_model
        ocr_api_key = self.ocr_api_key or self.llm_api_key
        ocr_base_url = self.ocr_base_url or self.llm_base_url

        if not ocr_api_key:
            raise MissingLLMApiKeyError()

        return ocr_model, ocr_api_key, ocr_base_url

    @property
    def has_vision_ocr_model(self) -> bool:
        """Return whether OCR has an explicitly configured vision-capable model."""
        if not self.ocr_model:
            return False  # OCR stays disabled unless OCR_MODEL is set explicitly.
        return True


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""

    return Settings()
