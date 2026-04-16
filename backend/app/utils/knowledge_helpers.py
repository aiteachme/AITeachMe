"""Knowledge graph utility helpers."""

from __future__ import annotations

import hashlib
import re
import unicodedata


def normalize_name(name: str) -> str:
    """Return a stable, idempotent normalized name."""

    text = unicodedata.normalize("NFKC", name.strip().lower())
    text = re.sub(r"[\s\-_]+", "", text)
    text = re.sub(r"[^\w\u4e00-\u9fff]", "", text)
    return text


def compute_member_signature(core_node_ids: list[int]) -> str:
    """Hash sorted core node ids for stable teaching-unit identity."""

    sorted_ids = sorted(core_node_ids)
    payload = ",".join(str(node_id) for node_id in sorted_ids)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
