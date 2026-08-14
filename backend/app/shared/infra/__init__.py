"""Shared infrastructure primitives: LLM, tracing, tools, search, storage, and memory."""

import os

from app.shared.infra.env_support import load_local_dotenv

load_local_dotenv()

# Keep LangSmith tracing enabled while avoiding its memory-intensive zstd
# batch compressor. Process and dotenv configuration can explicitly opt in.
os.environ.setdefault("LANGSMITH_DISABLE_RUN_COMPRESSION", "true")
