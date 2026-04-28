from app.workflows.digest.common.markdown_knowledge_anchors import extract_markdown_chapter_chunks
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import _build_extraction_tasks


def test_long_chapter_is_split_with_untruncated_body() -> None:
    markdown = "# Doc\n## Long chapter\n" + "\n".join(
        f"### S{index}\n" + ("x" * 1800)
        for index in range(1, 11)
    )

    chapters = extract_markdown_chapter_chunks(markdown, max_body_chars=None)
    tasks, metrics = _build_extraction_tasks(chapters, {})

    assert len(tasks) > 1
    assert len(tasks) <= metrics["planned_task_limit"]
    assert metrics["chapter_split_count"] == 1
    assert metrics["subsection_task_count"] == len(tasks)


def test_many_chapters_keep_chapter_tasks_and_limit_parallel_lanes() -> None:
    markdown = "\n".join(
        f"# C{index}\n" + ("x" * 1000)
        for index in range(1, 15)
    )

    chapters = extract_markdown_chapter_chunks(markdown, max_body_chars=None)
    tasks, metrics = _build_extraction_tasks(chapters, {})

    assert len(tasks) == len(chapters)
    assert metrics["planned_task_limit"] == 12
    assert metrics["chapter_split_count"] == 0
