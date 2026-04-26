from __future__ import annotations

import inspect

from app.workflows.digest.docgen import graph as docgen_graph


def test_docgen_graph_places_cover_generation_in_mainline() -> None:
    source = inspect.getsource(docgen_graph.build_docgen_graph)

    assert docgen_graph.NODE_GENERATE_COVER == "生成封面"
    assert "NODE_GENERATE_COVER" in source
