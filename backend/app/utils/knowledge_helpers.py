"""Knowledge graph utility helpers."""

from __future__ import annotations

import hashlib
import re
import unicodedata


def _normalize_symbol_only_name(text: str) -> str:
    symbol_codepoints = [f"{ord(char):x}" for char in text if not char.isspace()]
    if not symbol_codepoints:
        return ""
    return "sym_" + "_".join(symbol_codepoints)


def normalize_name(name: str) -> str:
    """Return a stable, idempotent normalized name."""

    text = unicodedata.normalize("NFKC", name.strip().lower())
    compact = re.sub(r"[\s\-_]+", "", text)
    normalized = re.sub(r"[^\w\u4e00-\u9fff]", "", compact)
    if normalized:
        return normalized
    return _normalize_symbol_only_name(compact)


def compute_member_signature(core_node_ids: list[int]) -> str:
    """Hash sorted core node ids for stable teaching-unit identity."""

    sorted_ids = sorted(core_node_ids)
    payload = ",".join(str(node_id) for node_id in sorted_ids)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
