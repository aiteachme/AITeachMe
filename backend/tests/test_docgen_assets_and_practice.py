from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.workflow.context import create_langgraph_dev_context
from app.workflows.digest.docgen.nodes.append_practice_node import build_append_practice_node
from app.workflows.digest.docgen.lib import DocGenAssetRuntime


def test_docgen_asset_runtime_processes_interactive_placeholder() -> None:
    markdown = "# 偏导数\n\n<!-- [INTERACTIVE: 偏导数公式推导展开器] -->"
    rendered = asyncio.run(
        DocGenAssetRuntime(TracedExecutionContext(subject="demo")).process_interactive_placeholders(
            markdown,
            digest_mode="systematic",
        )
    )

    assert "[INTERACTIVE:" not in rendered
    assert 'data-atm-kind="formula-expander"' in rendered
    assert "交互推导卡" in rendered


def test_append_practice_node_generates_mode_aware_practice_layers() -> None:
    node = build_append_practice_node(context=create_langgraph_dev_context("digest.docgen.practice_test"))
    base_state = {
        "subject": "demo",
        "requested_at": datetime.utcnow(),
        "document_context": {},
        "chapter_metadatas": [
            {
                "chapter_index": 1,
                "title": "偏导数直觉",
                "markdown": "# 偏导数直觉\n\n正文",
                "source_file_ids": [1],
            },
            {
                "chapter_index": 2,
                "title": "梯度与方向导数",
                "markdown": "# 梯度与方向导数\n\n正文",
                "source_file_ids": [1],
            },
        ],
    }

    with patch(
        "app.workflows.digest.docgen.nodes.append_practice_node.update_knowledge_build_status"
    ), patch(
        "app.workflows.digest.docgen.nodes.append_practice_node.append_knowledge_build_recent_event"
    ), patch(
        "app.workflows.digest.docgen.nodes.append_practice_node.publish_docgen_progress",
        new=AsyncMock(),
    ):
        sprint_result = asyncio.run(node({**base_state, "digest_mode": "sprint"}))
        systematic_result = asyncio.run(node({**base_state, "digest_mode": "systematic"}))

    sprint_markdown = sprint_result["chapter_metadatas"][-1]["markdown"]
    systematic_markdown = systematic_result["chapter_metadatas"][-1]["markdown"]

    assert "## 高频题型自检" in sprint_markdown
    assert "## 易错复盘" in sprint_markdown
    assert sprint_result["exam_questions"][0]["type"] == "pattern_check"
    assert sprint_result["practice_count"] >= 4

    assert "## 理解与推理题" in systematic_markdown
    assert "## 章节收束与迁移" in systematic_markdown
    assert systematic_result["exam_questions"][0]["type"] == "comprehension"
    assert systematic_result["practice_count"] >= 6
