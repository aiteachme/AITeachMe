"""Runtime configuration loaded from project `config.yaml` only."""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, ConfigDict

from .support import (
    DEFAULT_EMBEDDING_DIM,
    DEFAULT_RETRIEVER_FALLBACK,
    EMBEDDING_DIM_BY_MODEL,
    RETRIEVER_PROFILES,
    load_project_config_values,
    normalize_retriever_name,
    split_csv_names,
)


class Settings(BaseModel):
    """Project-level runtime configuration."""

    model_config = ConfigDict(extra="ignore")

    llm_model: str = "qwen-plus"
    ocr_model: str | None = None
    embedding_model: str = "text-embedding-v3"

    max_upload_size_mb: int = 50
    ingest_parse_concurrency: int = 5
    ingest_parser_timeout_s: int = 90
    rag_top_k: int = 5
    rag_similarity_threshold: float = 0.3
    chat_history_turns: int = 10

    model_overrides: dict[str, str] = {}
    llm_observability_enabled: bool = True
    tracing_enabled: bool = True
    langsmith_max_text_chars: int = 2000
    guardrails_enabled: bool = True
    llm_cache_enabled: bool = False
    llm_cache_ttl_s: int = 3600
    llm_cache_max_entries: int = 1000
    search_runtime_cache_enabled: bool = True
    search_runtime_cache_ttl_s: int = 900
    search_runtime_cache_max_entries: int = 256
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

    local_rag_priority: bool = True
    local_rag_min_results: int = 2
    search_max_results_per_query: int = 5
    search_scrape_timeout_s: int = 20

    planner_default_tone: str = "encouraging"
    planner_default_digest_mode: str = "sprint"
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
    rag_rerank_top_k: int = 3

    llm_model_light: str | None = None
    llm_model_extract: str | None = None
    kg_extract_max_parallelism: int = 20

    @property
    def embedding_dim(self) -> int:
        if not self.normalized_embedding_model:
            return 0
        return EMBEDDING_DIM_BY_MODEL.get(
            self.normalized_embedding_model,
            DEFAULT_EMBEDDING_DIM,
        )

    @property
    def normalized_embedding_model(self) -> str | None:
        value = (self.embedding_model or "").strip()
        return value or None

    @property
    def embedding_configured(self) -> bool:
        return self.normalized_embedding_model is not None

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
        resolved_profile = normalize_retriever_name(
            profile or self.web_search_retriever_profile
        )
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

        should_include_local_rag = (
            self.local_rag_priority
            if include_local_rag is None
            else include_local_rag
        )
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
    return Settings.model_validate(load_project_config_values())


__all__ = [
    "Settings",
    "get_settings",
]
