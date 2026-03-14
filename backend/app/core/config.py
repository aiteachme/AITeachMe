from functools import lru_cache
from pydantic_settings import BaseSettings


# 内置模型 → 向量维度映射表
_EMBEDDING_DIM_MAP: dict[str, int] = {
    "text-embedding-v3": 1536,          # 阿里云百炼
    "text-embedding-v2": 1536,          # 阿里云百炼
    "text-embedding-ada-002": 1536,     # OpenAI
    "text-embedding-3-small": 1536,     # OpenAI
    "text-embedding-3-large": 3072,     # OpenAI
    "BAAI/bge-large-zh-v1.5": 1024,    # 硅基流动
    "BAAI/bge-m3": 1024,               # 硅基流动
}

_DEFAULT_EMBEDDING_DIM = 1536


class Settings(BaseSettings):
    # 必填项（缺失时启动报错）
    llm_api_key: str

    # 可选项（含默认值）
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-plus"
    embedding_model: str = "text-embedding-v3"
    data_dir: str = "./data"
    max_upload_size_mb: int = 50
    rag_top_k: int = 5
    rag_similarity_threshold: float = 0.3
    chat_history_turns: int = 10

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def embedding_dim(self) -> int:
        """由 embedding_model 自动推导向量维度，不暴露为用户配置项。"""
        return _EMBEDDING_DIM_MAP.get(self.embedding_model, _DEFAULT_EMBEDDING_DIM)


@lru_cache
def get_settings() -> Settings:
    return Settings()
