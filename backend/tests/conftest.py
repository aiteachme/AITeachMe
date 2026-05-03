"""Pytest defaults for local test isolation."""

from __future__ import annotations

import os


if os.getenv("AITEACHME_ENABLE_TEST_LANGSMITH_TRACING", "").strip().lower() not in {
    "1",
    "true",
    "yes",
    "on",
}:
    os.environ["LANGSMITH_TRACING"] = "false"

