from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen import graph
from app.workflows.digest.docgen.lib import repair
from app.workflows.digest.docgen.lib.models import (
    ChapterReviewReport,
    LockedChapterTitle,
    ReviewAction,
    ReviewedChapterDraft,
)
from app.workflows.digest.docgen.nodes import lock_titles_for_chapters, review_content


@pytest.mark.anyio
async def test_lock_titles_uses_course_id_state_key(monkeypatch) -> None:
    captured_course_ids: list[str] = []

    async def fake_lock_title_for_chapter(**kwargs):
        chapter = kwargs["chapter"]
        return LockedChapterTitle(
            chapter_index=int(chapter["chapter_index"]),
            confirmed_title=str(chapter["title"]),
            enhanced_title=str(chapter["title"]),
            fallback_used=True,
        )

    def fake_append(course_id: str, **kwargs) -> None:
        captured_course_ids.append(course_id)

    def fake_upsert(course_id: str, **kwargs) -> None:
        captured_course_ids.append(course_id)

    monkeypatch.setattr(lock_titles_for_chapters, "lock_title_for_chapter", fake_lock_title_for_chapter)
    monkeypatch.setattr(lock_titles_for_chapters, "append_knowledge_build_recent_event", fake_append)
    monkeypatch.setattr(lock_titles_for_chapters, "upsert_knowledge_build_chapter_progress", fake_upsert)

    node = lock_titles_for_chapters.build_lock_titles_for_chapters_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course_state_contract")
    )
    result = await node(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "docgen_context": {
                "course_id": "course_state_contract",
                "course_name": "计算机基础",
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
    assert captured_course_ids == ["course_state_contract", "course_state_contract"]


def test_review_sends_only_single_chapter_payload() -> None:
    sends = graph.build_review_sends(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "build_session_id": "build_review_scope",
            "enhanced_chapter_drafts": [
                {"chapter_index": 1, "title": "第一章", "markdown": "# 第一章\n\n正文"},
                {"chapter_index": 2, "title": "第二章", "markdown": "# 第二章\n\n正文"},
            ],
            "chapter_tasks": [
                {"chapter_index": 1, "confirmed_title": "第一章", "required_elements": ["A"]},
                {"chapter_index": 2, "confirmed_title": "第二章", "required_elements": ["B"]},
            ],
            "claim_ledgers": [
                {"chapter_index": 1, "items": [{"claim_id": "c1", "claim_text": "A"}]},
                {"chapter_index": 2, "items": [{"claim_id": "c2", "claim_text": "B"}]},
            ],
            "claim_evidence_maps": [
                {"chapter_index": 1, "bindings": [{"claim_id": "c1", "support_level": 0.8}]},
                {"chapter_index": 2, "bindings": [{"claim_id": "c2", "support_level": 0.2}]},
            ],
            "conflict_reports": [
                {"chapter_index": 1, "items": []},
                {"chapter_index": 2, "items": [{"severity": "warning", "detail": "冲突"}]},
            ],
        }
    )

    assert sends != "fail"
    assert [item.arg["review_chapter_task"]["chapter_index"] for item in sends] == [1, 2]
    assert [item.arg["review_claim_ledger"]["chapter_index"] for item in sends] == [1, 2]
    assert "chapter_tasks" not in sends[0].arg
    assert "claim_ledgers" not in sends[0].arg
    assert "claim_evidence_maps" not in sends[0].arg
    assert "conflict_reports" not in sends[0].arg


@pytest.mark.anyio
async def test_review_node_outputs_overlay_without_markdown(monkeypatch) -> None:
    async def fake_review_chapter(**kwargs):
        reviewed = ReviewedChapterDraft(
            chapter_index=1,
            title="第一章",
            markdown="# 第一章\n\n正文",
            review_report_ref="ch01_review",
            warnings=["需要补例题"],
        )
        report = ChapterReviewReport(
            report_id="ch01_review",
            chapter_index=1,
            passed=False,
            warnings=["需要补例题"],
        )
        return reviewed, report, []

    monkeypatch.setattr(review_content, "review_chapter", fake_review_chapter)
    monkeypatch.setattr(review_content, "update_knowledge_build_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(review_content, "upsert_knowledge_build_chapter_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(review_content, "upsert_knowledge_build_chapter_preview", lambda *args, **kwargs: None)
    monkeypatch.setattr(review_content, "append_knowledge_build_recent_event", lambda *args, **kwargs: None)

    async def fake_publish(*args, **kwargs):
        return None

    monkeypatch.setattr(review_content, "publish_docgen_progress", fake_publish)
    node = review_content.build_review_chapter_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course_state_contract")
    )
    result = await node(
        {
            "course_id": "course_state_contract",
            "requested_at": datetime(2026, 4, 29, tzinfo=timezone.utc),
            "enhanced_chapter_draft": {"chapter_index": 1, "title": "第一章", "markdown": "# 第一章\n\n正文"},
            "review_chapter_task": {"chapter_index": 1, "confirmed_title": "第一章"},
            "review_claim_ledger": {"chapter_index": 1, "items": []},
            "review_claim_evidence_map": {"chapter_index": 1, "bindings": []},
            "review_conflict_report": {"chapter_index": 1, "items": []},
        }
    )

    assert "reviewed_chapter_draft_items" not in result
    assert result["reviewed_chapter_overlay_items"] == [
        {
            "chapter_index": 1,
            "review_report_ref": "ch01_review",
            "warnings": ["需要补例题"],
            "patched": False,
        }
    ]


@pytest.mark.anyio
async def test_repair_patch_applies_local_snippet(monkeypatch) -> None:
    async def fake_completion(*args, **kwargs):
        return repair._LocalMarkdownPatch(
            status="patch",
            patch_markdown="## 易错补充\n\n- 先看单位，再代入公式。",
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", fake_completion)
    chapter = ReviewedChapterDraft(
        chapter_index=1,
        title="面积",
        markdown="# 面积\n\n## 核心概念\n\n面积表示平面的大小。\n\n## 本章小结\n\n记住公式。\n",
    )
    action = ReviewAction(
        action_id="a1",
        action_type="section_patch",
        chapter_index=1,
        reason="缺少易错提醒",
        target_anchor="核心概念",
        instruction="补充单位易错点。",
    )

    repaired, updated_actions, unresolved, traces = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter],
        review_actions=[action],
    )

    assert unresolved == []
    assert updated_actions[0].status == "applied"
    assert traces[0].changed is True
    assert "## 易错补充" in repaired[0].markdown
    assert repaired[0].markdown.index("## 易错补充") < repaired[0].markdown.index("## 本章小结")
