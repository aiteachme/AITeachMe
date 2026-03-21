"""检索类型定义。"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class RetrievalConfig:
    top_k: int = 5
    similarity_threshold: float = 0.3
    enable_keyword_search: bool = False
    enable_rerank: bool = False
    rerank_model: str | None = None

@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: int
    title: str
    header_path: str
    content: str
    score: float
    source: str = "vector"
