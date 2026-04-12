"""Settings model for the public `app.shared.infra.config` package."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from .support import (
    DEFAULT_EMBEDDING_DIM,
    DEFAULT_RETRIEVER_FALLBACK,
    EMBEDDING_DIM_BY_MODEL,
    RETRIEVER_PROFILES,
    build_settings_sources,
    normalize_retriever_name,
    split_csv_names,
)
from app.shared.infra.exceptions import MissingLLMApiKeyError


class Settings(BaseSettings):
    """Load application settings from `.env`, environment variables, and `config.yaml`."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return build_settings_sources(
            settings_cls,
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    llm_api_key: str | None = None
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-plus"
    ocr_model: str | None = None
    ocr_api_key: str | None = None
    ocr_base_url: str | None = None
    embedding_model: str = "text-embedding-v3"
    mineru_api_token: str | None = None

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
    app_version: str = "0.2.0"

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

    export_openapi_on_startup: bool = False
    cors_allowed_origins: str = ""
    project_config_path: str = "config.yaml"

    database_url: str | None = None

    storage_backend: str = "local"
    s3_bucket: str | None = None
    s3_endpoint: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_session_token: str | None = None
    s3_region: str | None = None
    s3_public_base_url: str | None = None
    s3_addressing_style: str = "virtual"
    s3_credential_mode: str = "auto"
    dogecloud_api_access_key: str | None = None
    dogecloud_api_secret_key: str | None = None
    dogecloud_api_base_url: str = "https://api.dogecloud.com"
    dogecloud_space_name: str | None = None
    dogecloud_tmp_token_path: str = "/auth/tmp_token.json"
    dogecloud_tmp_token_channel: str = "OSS_FULL"
    dogecloud_tmp_token_scope: str = "*"

    model_overrides: dict[str, str] = {}
    llm_observability_enabled: bool = True
    tracing_enabled: bool = True
    langsmith_tracing: bool = False
    langsmith_project: str = "AITeachMe"
    langsmith_capture_inputs: bool | None = None
    langsmith_capture_outputs: bool | None = None
    langsmith_max_text_chars: int = 2000
    guardrails_enabled: bool = True
    llm_cache_enabled: bool = False
    llm_cache_ttl_s: int = 3600
    llm_cache_max_entries: int = 1000
    llm_observability_max_records: int = 5000
    llm_concurrency_limit: int = 20
    default_token_budget: int = 4000

    embedding_batch_size: int = 10
    embedding_batch_delay_s: float = 0.1

    digest_timing_top_k: int = 5
    digest_token_summary_enabled: bool = True
    digest_chapter_priors_timeout_ms: int = 0

    docgen_max_parallel_chapters: int = 20
    docgen_io_parallelism: int = 20
    docgen_max_research_queries: int = 3

    web_search_retriever: str = "duckduckgo"
    web_search_retrievers: str = ""
    web_search_retriever_profile: str = ""
    searxng_base_url: str | None = None
    bing_api_key: str | None = None
    bocha_api_key: str | None = None
    semantic_scholar_api_key: str | None = None
    tavily_api_key: str | None = None

    local_rag_priority: bool = True
    local_rag_min_results: int = 2
    search_max_results_per_query: int = 5
    search_scrape_timeout_s: int = 20

    planner_default_tone: str = "encouraging"
    planner_default_digest_mode: str = "systematic"
    planner_min_chapters: int = 6
    planner_max_chapters: int = 10
    planner_allow_external_search: bool = True
    planner_sprint_min_chapters: int = 3
    planner_sprint_max_chapters: int = 6
    planner_sprint_target_length: str = "3000-5000字"
    planner_systematic_min_chapters: int = 5
    planner_systematic_max_chapters: int = 12
    planner_systematic_target_length: str = "10000-15000字"

    image_generation_model: str | None = None
    mermaid_generation_model: str | None = None
    enable_image_generation: bool = False
    enable_mermaid_generation: bool = True

    rag_rerank_model: str | None = None
    rag_rerank_api_key: str | None = None
    rag_rerank_base_url: str | None = None
    rag_rerank_top_k: int = 3

    llm_model_light: str | None = None
    llm_model_extract: str | None = None
    kg_extract_max_parallelism: int = 20

    @property
    def embedding_dim(self) -> int:
        if not self.normalized_embedding_model:
            return 0
        return EMBEDDING_DIM_BY_MODEL.get(self.normalized_embedding_model, DEFAULT_EMBEDDING_DIM)

    @property
    def normalized_embedding_model(self) -> str | None:
        value = (self.embedding_model or "").strip()
        return value or None

    @property
    def embedding_configured(self) -> bool:
        return self.normalized_embedding_model is not None

    @property
    def resolved_app_mode(self) -> str:
        normalized = (self.app_mode or "auto").strip().lower()
        if normalized in {"local", "cloud"}:
            return normalized
        if os.getenv("RENDER") or os.getenv("RENDER_EXTERNAL_URL"):
            return "cloud"
        return "local"

    @property
    def is_cloud_mode(self) -> bool:
        return self.resolved_app_mode == "cloud"

    @property
    def is_local_mode(self) -> bool:
        return not self.is_cloud_mode

    def _resolve_langsmith_capture_flag(self, *, configured: bool | None) -> bool:
        if configured is not None:
            return configured
        return self.is_local_mode

    @property
    def resolved_langsmith_capture_inputs(self) -> bool:
        return self._resolve_langsmith_capture_flag(configured=self.langsmith_capture_inputs)

    @property
    def resolved_langsmith_capture_outputs(self) -> bool:
        return self._resolve_langsmith_capture_flag(configured=self.langsmith_capture_outputs)

    @property
    def storage_is_s3(self) -> bool:
        return self.storage_backend.lower() == "s3"

    @property
    def resolved_s3_addressing_style(self) -> str:
        normalized = (self.s3_addressing_style or "virtual").strip().lower()
        if normalized in {"auto", "virtual", "path"}:
            return normalized
        return "virtual"

    @property
    def resolved_s3_credential_mode(self) -> str:
        normalized = (self.s3_credential_mode or "auto").strip().lower()
        if normalized in {"static", "dogecloud_tmp_token"}:
            return normalized
        if self.dogecloud_api_access_key and self.dogecloud_api_secret_key:
            return "dogecloud_tmp_token"
        return "static"

    @property
    def s3_uses_dogecloud_tmp_token(self) -> bool:
        return self.resolved_s3_credential_mode == "dogecloud_tmp_token"

    @property
    def resolved_dogecloud_api_access_key(self) -> str | None:
        if self.dogecloud_api_access_key:
            return self.dogecloud_api_access_key
        if self.s3_uses_dogecloud_tmp_token:
            return self.s3_access_key
        return None

    @property
    def resolved_dogecloud_api_secret_key(self) -> str | None:
        if self.dogecloud_api_secret_key:
            return self.dogecloud_api_secret_key
        if self.s3_uses_dogecloud_tmp_token:
            return self.s3_secret_key
        return None

    @property
    def resolved_dogecloud_space_name(self) -> str | None:
        if self.dogecloud_space_name:
            return self.dogecloud_space_name
        return self.s3_bucket

    @property
    def resolved_guest_cookie_samesite(self) -> str:
        normalized = (self.guest_cookie_samesite or "auto").strip().lower()
        if normalized in {"lax", "strict", "none"}:
            return normalized
        return "none" if self.is_cloud_mode else "lax"

    @property
    def resolved_guest_cookie_secure(self) -> bool:
        if self.guest_cookie_secure is not None:
            return self.guest_cookie_secure
        return self.is_cloud_mode or self.resolved_guest_cookie_samesite == "none"

    @property
    def auth_ready(self) -> bool:
        return True

    def require_llm_api_key(self) -> str:
        if not self.llm_api_key:
            raise MissingLLMApiKeyError()
        return self.llm_api_key

    def get_ocr_config(self) -> tuple[str, str, str]:
        ocr_model = self.ocr_model or self.llm_model
        ocr_api_key = self.ocr_api_key or self.llm_api_key
        ocr_base_url = self.ocr_base_url or self.llm_base_url
        if not ocr_api_key:
            raise MissingLLMApiKeyError()
        return ocr_model, ocr_api_key, ocr_base_url

    @property
    def has_vision_ocr_model(self) -> bool:
        return bool(self.ocr_model)

    @property
    def image_generation_enabled(self) -> bool:
        return bool((self.image_generation_model or "").strip()) or self.enable_image_generation

    @property
    def mermaid_generation_enabled(self) -> bool:
        return bool((self.mermaid_generation_model or "").strip()) or self.enable_mermaid_generation

    def parse_retrievers(
        self,
        *,
        profile: str | None = None,
        include_local_rag: bool | None = None,
        include_fallback: bool = True,
        fallback_retriever: str = DEFAULT_RETRIEVER_FALLBACK,
    ) -> list[str]:
        explicit_names = [
            normalize_retriever_name(item)
            for item in split_csv_names(self.web_search_retrievers)
        ]
        resolved_profile = normalize_retriever_name(profile or self.web_search_retriever_profile)
        profile_names = [
            normalize_retriever_name(item)
            for item in RETRIEVER_PROFILES.get(resolved_profile, [])
        ]
        legacy_names = [
            normalize_retriever_name(item)
            for item in split_csv_names(self.web_search_retriever)
        ]

        if explicit_names:
            candidate_names = explicit_names
        elif profile_names:
            candidate_names = profile_names
        elif legacy_names:
            candidate_names = legacy_names
        else:
            candidate_names = [DEFAULT_RETRIEVER_FALLBACK]

        should_include_local_rag = self.local_rag_priority if include_local_rag is None else include_local_rag
        normalized: list[str] = []
        seen: set[str] = set()

        def _append(name: str) -> None:
            if not name or name in seen:
                return
            seen.add(name)
            normalized.append(name)

        if should_include_local_rag:
            _append("local_rag")
        for item in candidate_names:
            if include_local_rag is False and item in {"local_rag", "rag"}:
                continue
            _append(item)

        fallback_name = normalize_retriever_name(fallback_retriever)
        if include_fallback and fallback_name and any(name != "local_rag" for name in normalized):
            _append(fallback_name)

        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings()


__all__ = [
    "Settings",
    "get_settings",
]
