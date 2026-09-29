"""Question-bank identity shared by generation and course import."""

from __future__ import annotations

import hashlib
import json


def custom_question_identity_hash(*, stem: str, version_id: int) -> str:
    """Keep equal stems distinct across installed question-type versions."""
    payload = {
        "stem_hash": hashlib.sha1(stem.encode("utf-8")).hexdigest(),
        "question_type_version_id": version_id,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
