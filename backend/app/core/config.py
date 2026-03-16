"""Application configuration and environment-backed settings."""

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
    """Application-wide settings loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    llm_api_key: str | None = None
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-plus"
    embedding_model: str = "text-embedding-v3"
    data_dir: str = "./data"
    max_upload_size_mb: int = 50
    rag_top_k: int = 5
    rag_similarity_threshold: float = 0.3
    chat_history_turns: int = 10
    app_mode: str = "local"
    auth_enabled: bool = False
    app_version: str = "0.2.0"

    @property
    def embedding_dim(self) -> int:
        return _EMBEDDING_DIM_MAP.get(self.embedding_model, _DEFAULT_EMBEDDING_DIM)

    @property
    def is_cloud_mode(self) -> bool:
        return self.app_mode.lower() == "cloud"

    @property
    def is_local_mode(self) -> bool:
        return not self.is_cloud_mode

    @property
    def auth_ready(self) -> bool:
        return False

    def require_llm_api_key(self) -> str:
        if not self.llm_api_key:
            raise MissingLLMApiKeyError()
        return self.llm_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
