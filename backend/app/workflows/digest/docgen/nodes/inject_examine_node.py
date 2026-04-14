"""Inject examine node for the DocGen lane."""

from __future__ import annotations

from copy import deepcopy

from app.shared.infra.tools.builtin.markdown_processing import prepend_table_of_contents
from app.utils.docgen_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.nodes.common import (
    build_examine_markdown,
    get_effective_chapter_title,
    publish_docgen_progress,
)
from app.workflows.digest.docgen.publish import build_merged_markdown
from app.workflows.digest.docgen.state import DocGenState


def _build_practice_layer(chapter_metadatas: list[dict], *, digest_mode: str) -> tuple[list[dict], list[str]]:
    normalized_mode = str(digest_mode or "").strip().lower()
    chapter_titles = [
        get_effective_chapter_title(
            chapter,
            fallback_index=int(chapter.get("chapter_index", 0) or 0) or None,
        )
        for chapter in chapter_metadatas[:4]
        if get_effective_chapter_title(
            chapter,
            fallback_index=int(chapter.get("chapter_index", 0) or 0) or None,
        )
    ]
    if normalized_mode == "sprint":
        questions = []
        for index, title in enumerate(chapter_titles[:3], start=1):
            questions.append(
                {
                    "question_index": len(questions) + 1,
                    "type": "pattern_check",
                    "question": f"《{title}》里哪一种题型最能暴露你还没真正掌握？请写出识别题眼、选择方法和避免失分的三步判断。",
                }
            )
            questions.append(
                {
                    "question_index": len(questions) + 1,
                    "type": "self_check",
                    "question": f"不看原文，试着口头复盘《{title}》里最值得临考前再扫一遍的公式、条件和易错点。",
                }
            )
        review_prompts = [
            "把你最容易混淆的两个概念写成一组对照卡，确保自己能在 30 秒内说清区别。",
            "挑一题你会做但讲不清理由的题，把理由补全成可以复述的步骤。",
            "如果只剩 10 分钟复习，你会优先回看哪三个抓手？",
        ]
        return questions, review_prompts

    questions = []
    for title in chapter_titles[:3]:
        questions.extend(
            [
                {
                    "question_index": len(questions) + 1,
                    "type": "comprehension",
                    "question": f"请用自己的话概括《{title}》要解决的核心问题，并说明它在整份文档中的位置。",
                },
                {
                    "question_index": len(questions) + 1,
                    "type": "reasoning",
                    "question": f"围绕《{title}》挑一条最关键的推理链，解释每一步为什么成立、缺了哪一步会出问题。",
                },
                {
                    "question_index": len(questions) + 1,
                    "type": "transfer",
                    "question": f"把《{title}》里的一个方法迁移到一个新场景中，说明哪些条件没变，哪些条件需要重新判断。",
                },
            ]
        )
    review_prompts = [
        "从整份文档里找出一条你已经能稳定复述的知识主线，再找出一条还不够稳的主线。",
        "选择一个边界条件或反例，解释它为什么能帮助你真正理解概念的适用范围。",
        "如果要继续深入学习，这份文档里哪一章最适合作为下一步的起点？为什么？",
    ]
    return questions, review_prompts


def build_inject_examine_node(*, context: WorkflowContext):
    async def inject_examine_node(state: DocGenState) -> dict:
        chapter_metadatas = sorted(
            deepcopy(list(state.get("chapter_metadatas", []))),
            key=lambda item: item.get("chapter_index", 0),
        )
        if not chapter_metadatas:
            return {"error": "当前没有可用于注入练习内容的章节。"}

        digest_mode = str(state.get("digest_mode") or "")
        exam_questions, review_prompts = _build_practice_layer(chapter_metadatas, digest_mode=digest_mode)
        practice_markdown = build_examine_markdown(
            exam_questions=exam_questions,
            digest_mode=digest_mode,
            review_prompts=review_prompts,
        )
        practice_count = len(exam_questions)
        next_index = max(int(chapter.get("chapter_index", 0) or 0) for chapter in chapter_metadatas) + 1
        chapter_metadatas.append(
            {
                "chapter_index": next_index,
                "title": "练习与自检",
                "markdown": practice_markdown,
                "summary": "本章之后的练习提示、自检问题与章节收束任务。",
                "tags": ["practice", "self_check"],
                "digest_mode": digest_mode,
                "source_file_ids": sorted(
                    {
                        int(file_id)
                        for chapter in chapter_metadatas
                        for file_id in chapter.get("source_file_ids", [])
                    }
                ),
                "sources": [],
                "source_details": [],
                "practice_count": practice_count,
            }
        )
        merged_markdown = prepend_table_of_contents(
            build_merged_markdown(
                chapter_metadatas,
                document_context=dict(state.get("document_context") or {}),
            ),
            min_level=2,
            max_level=4,
        )
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="publishing",
            digest_mode=state.get("digest_mode") or None,
            staged_chapter_count=len(chapter_metadatas),
            current_stage_description="文档组装完成，开始发布知识文档。",
            draft_available=bool(merged_markdown.strip()),
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "examine_injected",
                "summary": f"练习与自检内容已注入，新增 {practice_count} 个练习任务。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="examine_injected",
            payload={
                "question_count": practice_count,
                "chapter_count": len(chapter_metadatas),
            },
        )
        return {
            "chapter_metadatas": chapter_metadatas,
            "exam_questions": exam_questions,
            "merged_markdown": merged_markdown,
            "enriched_markdown": merged_markdown,
            "practice_count": practice_count,
        }

    return inject_examine_node


__all__ = ["build_inject_examine_node"]
