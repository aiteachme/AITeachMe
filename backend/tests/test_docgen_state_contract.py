from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.lib.models import LockedChapterTitle
from app.workflows.digest.docgen.nodes import lock_titles_for_chapters


@pytest.mark.anyio
async def test_lock_titles_uses_subject_id_state_key(monkeypatch) -> None:
    captured_subject_ids: list[str] = []

    async def fake_lock_title_for_chapter(**kwargs):
        chapter = kwargs["chapter"]
        return LockedChapterTitle(
            chapter_index=int(chapter["chapter_index"]),
            confirmed_title=str(chapter["title"]),
            enhanced_title=str(chapter["title"]),
            fallback_used=True,
        )

    def fake_append(subject_id: str, **kwargs) -> None:
        captured_subject_ids.append(subject_id)

    def fake_upsert(subject_id: str, **kwargs) -> None:
        captured_subject_ids.append(subject_id)

    monkeypatch.setattr(lock_titles_for_chapters, "lock_title_for_chapter", fake_lock_title_for_chapter)
    monkeypatch.setattr(lock_titles_for_chapters, "append_knowledge_build_recent_event", fake_append)
    monkeypatch.setattr(lock_titles_for_chapters, "upsert_knowledge_build_chapter_progress", fake_upsert)

    node = lock_titles_for_chapters.build_lock_titles_for_chapters_node(
        context=WorkflowContext(workflow_name="digest.docgen", subject_id="subj_state_contract")
    )
    result = await node(
        {
            "subject_id": "subj_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "docgen_context": {
                "subject_id": "subj_state_contract",
                "subject_name": "计算机基础",
                "digest_mode": "sprint",
                "user_prompt": "学习计算机基础",
                "plan_summary": "按核心模块组织内容",
            },
            "chapter_assignments": [
                {
                    "chapter_index": 1,
                    "title": "计算机系统构成",
                }
            ],
        }
    )

    assert result["locked_titles"][0]["enhanced_title"] == "计算机系统构成"
    assert captured_subject_ids == ["subj_state_contract", "subj_state_contract"]
