from __future__ import annotations

import pytest

from app.workflows.digest.docgen.lib.asset_rendering import MermaidSkipped, _sanitize_mermaid_body


def test_empty_mermaid_response_is_treated_as_skip() -> None:
    with pytest.raises(MermaidSkipped):
        _sanitize_mermaid_body("", topic="formula expansion")
