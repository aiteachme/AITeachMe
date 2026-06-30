"""Generate chapter-end unit tests after body-only chapter writing."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.knowledge.build_store import (
    append_knowledge_build_recent_event,
    update_knowledge_build_status,
    upsert_knowledge_build_chapter_preview,
    upsert_knowledge_build_chapter_progress,
)
from app.shared.infra.llm_support import run_llm_tasks
from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.shared.infra.workflow.context import WorkflowContext
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.models import ChapterDraft, ChapterGenerationTask
from app.workflows.digest.docgen.lib.unit_tests import (
    ChapterUnitTestGenerationError,
    append_unit_test_markdown,
    generate_chapter_unit_tests,
    render_unit_test_markdown,
)
from app.workflows.digest.docgen.nodes.common import extract_markdown_preview_headings, publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def _chapter_tasks_by_index(state: DocGenState) -> dict[int, ChapterGenerationTask]:
    tasks: dict[int, ChapterGenerationTask] = {}
    for raw in list(state.get("chapter_tasks") or []):
        try:
            task = ChapterGenerationTask.model_validate(raw)
        except Exception:
            continue
        tasks[task.chapter_index] = task
    return tasks


def _unit_test_bounds(task: ChapterGenerationTask | None, *, digest_mode: str) -> tuple[int, int]:
    policy = dict((task.practice_seed_policy if task is not None else {}) or {})
    density = dict(policy.get("example_density_policy") or {})
    is_sprint = str(digest_mode or "").lower() == "sprint"
    default_min = 3 if is_sprint else 5
    default_max = 4 if is_sprint else 7
    try:
        min_items = int(density.get("chapter_end_practice_min_tasks") or default_min)
    except (TypeError, ValueError):
        min_items = default_min
    try:
        max_items = int(density.get("chapter_end_practice_max_tasks") or default_max)
    except (TypeError, ValueError):
        max_items = default_max
    plan_count = len(list((task.chapter_end_practice_plan if task is not None else []) or []))
    required_count = len(list((task.required_elements if task is not None else []) or []))
    floor = 3 if is_sprint else 4
    cap = 5 if is_sprint else 12
    if plan_count >= 6 or required_count >= 8:
        min_items = max(min_items, 4 if is_sprint else 7)
        max_items = max(max_items, 5 if is_sprint else 8)
    min_items = max(floor, min(min_items, cap))
    max_items = max(min_items, min(max_items, cap))
    return min_items, max_items


def build_generate_unit_tests_node(*, context: WorkflowContext):
    """Build the node that appends a single final unit-test section per chapter."""

    async def generate_unit_tests_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        drafts = [
            ChapterDraft.model_validate(item)
            for item in sorted(
                list(state.get("chapter_drafts") or []),
                key=lambda raw: int((raw or {}).get("chapter_index", 0) or 0),
            )
        ]
        if not drafts:
            return {"error": "没有可生成单元测试的章节草稿。"}

        digest_mode = state.get("digest_mode") or "systematic"
        tasks_by_index = _chapter_tasks_by_index(state)
        update_knowledge_build_status(
            state["course_id"],
            requested_at=state["requested_at"],
            status="running",
            stage="generating_unit_tests",
            digest_mode=digest_mode,
            current_stage_description=f"章节正文已生成，正在并行生成 {len(drafts)} 个章末单元测试。",
        )

        async def _generate_one(draft: ChapterDraft) -> tuple[ChapterDraft, dict]:
            task = tasks_by_index.get(draft.chapter_index)
            min_items, max_items = _unit_test_bounds(task, digest_mode=digest_mode)
            upsert_knowledge_build_chapter_progress(
                state["course_id"],
                requested_at=state["requested_at"],
                chapter_progress={"chapter_index": draft.chapter_index, "title": draft.title, "status": "testing"},
            )
            try:
                result = await generate_chapter_unit_tests(
                    draft=draft,
                    task=task,
                    digest_mode=digest_mode,
                    min_items=min_items,
                    max_items=max_items,
                    trace_metadata={
                        **dict(context.metadata or {}),
                        "chapter_index": draft.chapter_index,
                        "docgen_stage": "generate_unit_tests",
                    },
                )
            except ChapterUnitTestGenerationError as exc:
                failure_summary = "章末单元测试生成失败，已跳过该章测试并继续发布正文；不会使用模板题目兜底。"
                upsert_knowledge_build_chapter_progress(
                    state["course_id"],
                    requested_at=state["requested_at"],
                    chapter_progress={
                        "chapter_index": draft.chapter_index,
                        "title": draft.title,
                        "status": "unit_test_skipped",
                        "warning": "unit_test_generation_failed",
                    },
                )
                upsert_knowledge_build_chapter_preview(
                    state["course_id"],
                    requested_at=state["requested_at"],
                    chapter_preview={
                        "chapter_index": draft.chapter_index,
                        "title": draft.title,
                        "status": "unit_test_skipped",
                        "excerpt": draft.markdown.strip(),
                        "latest_headings": extract_markdown_preview_headings(draft.markdown),
                        "word_count": count_words(draft.markdown),
                        "source_count": len(draft.source_details),
                    },
                )
                append_knowledge_build_recent_event(
                    state["course_id"],
                    requested_at=state["requested_at"],
                    event={
                        "stage": "chapter_unit_test_skipped",
                        "chapter_index": draft.chapter_index,
                        "title": draft.title,
                        "summary": failure_summary,
                        "detail": str(exc)[:240],
                        "created_at": utcnow(),
                    },
                )
                await publish_docgen_progress(
                    context,
                    state=state,
                    stage="chapter_unit_test_skipped",
                    payload={
                        "chapter_index": draft.chapter_index,
                        "title": draft.title,
                        "warning": "unit_test_generation_failed",
                        "message": str(exc)[:240],
                    },
                )
                return draft, {
                    "chapter_index": draft.chapter_index,
                    "items": [],
                    "skipped": True,
                    "error": str(exc)[:240],
                }
            targets = []
            if task is not None:
                targets = [
                    *task.content_points,
                    *task.concept_targets,
                    *task.definition_targets,
                    *task.formula_targets,
                    *task.example_targets,
                    *task.pitfall_targets,
                    *task.required_elements,
                ]
            unit_test_markdown = render_unit_test_markdown(
                result,
                title=draft.title,
                min_items=min_items,
                max_items=max_items,
                fallback_targets=targets,
            )
            markdown = append_unit_test_markdown(draft.markdown, unit_test_markdown)
            updated = draft.model_copy(update={"markdown": markdown})
            upsert_knowledge_build_chapter_preview(
                state["course_id"],
                requested_at=state["requested_at"],
                chapter_preview={
                    "chapter_index": updated.chapter_index,
                    "title": updated.title,
                    "status": "unit_test_ready",
                    "excerpt": updated.markdown.strip(),
                    "latest_headings": extract_markdown_preview_headings(updated.markdown),
                    "word_count": count_words(updated.markdown),
                    "source_count": len(updated.source_details),
                },
            )
            append_knowledge_build_recent_event(
                state["course_id"],
                requested_at=state["requested_at"],
                event={
                    "stage": "chapter_unit_test_ready",
                    "chapter_index": updated.chapter_index,
                    "title": updated.title,
                    "summary": f"{updated.title} 章末单元测试生成完成，共 {len(result.items)} 题。",
                    "created_at": utcnow(),
                },
            )
            return updated, result.model_dump(mode="json")

        results = await run_llm_tasks(drafts, _generate_one)
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        updated_drafts = [item[0] for item in results]
        unit_tests = [item[1] for item in results]
        await publish_docgen_progress(
            context,
            state=state,
            stage="unit_tests_ready",
            payload={
                "chapter_count": len(updated_drafts),
                "unit_test_count": sum(len(item.get("items") or []) for item in unit_tests),
                "unit_test_skipped_count": sum(1 for item in unit_tests if bool(item.get("skipped"))),
            },
        )
        return {
            "unit_test_chapter_drafts": [item.model_dump(mode="json") for item in updated_drafts],
            "unit_test_items": unit_tests,
            "unit_test_ms": elapsed_ms,
            "llm_calls_total": len(updated_drafts),
            "unit_test_skipped_count": sum(1 for item in unit_tests if bool(item.get("skipped"))),
        }

    return generate_unit_tests_node


__all__ = ["build_generate_unit_tests_node"]
