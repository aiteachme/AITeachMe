"""Keep separately requested chapter-end exercise and quiz groups in one total."""

from __future__ import annotations

import json
import re

import pytest

from app.workflows.digest.docgen.lib import chapter_execution_brief, chapter_planning
from app.workflows.digest.docgen.lib.models import (
    ChapterExecutionBrief,
    ChapterGenerationTask,
    ChapterGenerationTaskSeed,
    DocGenContext,
    DocGenIntentProfile,
    LockedChapterTitle,
)
from app.workflows.digest.docgen.lib.unit_test_generation import generate_chapter_unit_test_markdown
from app.workflows.digest.docgen.lib.unit_tests import (
    ChapterUnitTestItem,
    ChapterUnitTestSet,
    unit_test_structure_issues,
)
from app.workflows.digest.docgen.nodes.generate_chapters import _chapter_plan_for_writer
from app.workflows.digest.docgen.prompts.chapter_review import build_chapter_review_messages
from app.workflows.digest.docgen.prompts.document_review import build_document_review_messages


TITLE = "整数加法"


def _compile(brief: ChapterExecutionBrief) -> ChapterGenerationTask:
    task = chapter_planning.assemble_chapter_generation_plan(
        docgen_context=DocGenContext(course_name=TITLE, digest_mode="sprint"),
        confirmed_chapters=[{"chapter_index": 1, "title": TITLE}],
        locked_titles=[LockedChapterTitle(chapter_index=1, confirmed_title=TITLE, enhanced_title=TITLE)],
        intent_profile=DocGenIntentProfile(),
        file_summaries=[],
        task_seeds=[ChapterGenerationTaskSeed(chapter_index=1, confirmed_title=TITLE, required_elements=["整数相加"])],
        chapter_execution_briefs=[brief],
    ).chapters[0]
    return ChapterGenerationTask.model_validate(task.model_dump(mode="json"))


@pytest.mark.anyio
@pytest.mark.parametrize(("requirement", "inline_count", "chapter_end_count"), [
    ("章末4道练习和5道短测", 0, 9),
    ("章末共5题，其中2道练习", 0, 5),
    ("正文4道练习、章末5道短测", 4, 5),
])
async def test_quantity_group_interpretation_contract_survives_task_compilation(
    monkeypatch, requirement: str, inline_count: int, chapter_end_count: int,
) -> None:
    async def fake_brief(messages, **kwargs):
        prompt = messages[-1]["content"]
        assert requirement in prompt
        assert "章末4道练习和5道短测”应为 inline_practice_count=0、chapter_end_question_count=9" in prompt
        assert "章末共5题，其中2道练习”总数仍为5" in prompt
        assert "正文4道练习、章末5道短测”则为 inline_practice_count=4、chapter_end_question_count=5" in prompt
        return kwargs["response_model"](
            teaching_outline=["用加一任务区分题组"],
            writing_instructions=[requirement],
            quantity_constraints={"inline_practice_count": inline_count, "chapter_end_question_count": chapter_end_count},
            content_role_targets={"concept": ["整数相加"]},
            example_coverage_plan=[{"target": "整数相加"}],
            chapter_end_practice_plan=[{"target": f"章末任务{i}", "question_count": 1} for i in range(chapter_end_count)],
        )

    monkeypatch.setattr(chapter_execution_brief, "acompletion_with_fallback", fake_brief)
    brief = await chapter_execution_brief.build_chapter_execution_brief(
        course_name=TITLE, digest_mode="sprint", chapter={"chapter_index": 1}, locked_title=TITLE,
        intent_core={}, glossary_terms=[], claim_targets=[], confusion_targets=[], user_prompt=requirement,
    )
    task = _compile(brief)
    plan = _chapter_plan_for_writer(task, total_chapters=1)
    contract = plan["execution_contract"]
    assert task.quantity_constraints.inline_practice_count == inline_count
    assert task.quantity_constraints.chapter_end_question_count == chapter_end_count
    assert requirement in task.writing_rules
    assert requirement in plan["writing_instructions"]
    assert contract["practice_quota"]["practice_tasks"] == inline_count
    assert contract["practice_quota"]["chapter_end_min_tasks"] == chapter_end_count
    assert contract["practice_quota"]["chapter_end_max_tasks"] == chapter_end_count
    assert len(contract["chapter_end_practice_plan"]) == chapter_end_count


@pytest.mark.anyio
async def test_four_end_exercises_and_five_quiz_items_publish_all_nine_with_group_contract() -> None:
    requirement = "正文不安排练习；章末4道应用练习和5道填空短测。"
    task = _compile(ChapterExecutionBrief(
        writing_instructions=[requirement],
        quantity_constraints={"inline_practice_count": 0, "chapter_end_question_count": 9},
        example_coverage_plan=[{"target": "整数相加"}],
        chapter_end_practice_plan=[
            {"target": f"练习{i}", "example_type": "应用迁移"} for i in range(1, 5)
        ] + [{"target": f"短测{i}", "example_type": "填空题"} for i in range(1, 6)],
    ))
    writer_plan = _chapter_plan_for_writer(task, total_chapters=1)
    contract = writer_plan["execution_contract"]
    stages: list[str] = []

    async def fake_quiz(messages, **kwargs):
        prompt = messages[-1]["content"]
        assert "题量范围：9-9" in prompt
        assert "全部章末题目的合计数" in prompt
        contract_text = prompt.split("用户确认的需求与章节写作合同（固定题型、数量和主题边界优先）：\n", 1)[1].splitlines()[0]
        received_contract = json.loads(contract_text)
        assert requirement in received_contract["writing_instructions"]
        assert received_contract["quantity_constraints"] == {"inline_practice_count": 0, "chapter_end_question_count": 9}
        assert "练习4" in prompt and "短测5" in prompt
        stages.append(kwargs["extra_metadata"]["docgen_stage"])
        return ChapterUnitTestSet(items=[
            ChapterUnitTestItem(
                type="应用迁移" if i <= 4 else "填空题",
                target=f"练习{i}" if i <= 4 else f"短测{i - 4}",
                stem=f"计算 ${i}+1$。", answer=str(i + 1), basis=f"把{i}加1；得到{i + 1}。",
            ) for i in range(1, 10)
        ])

    markdown = await generate_chapter_unit_test_markdown(
        chapter_index=1, chapter_title=TITLE, digest_mode="sprint", required_elements=["整数相加"],
        chapter_end_practice_plan=contract["chapter_end_practice_plan"],
        body_markdown=f"# {TITLE}\n\n## 加一\n\n在原数上增加1。",
        min_items=contract["practice_quota"]["chapter_end_min_tasks"],
        max_items=contract["practice_quota"]["chapter_end_max_tasks"],
        writing_contract={
            "writing_instructions": writer_plan["writing_instructions"],
            "quantity_constraints": contract["quantity_constraints"],
        },
        llm_caller=fake_quiz,
    )
    assert stages == ["generate_chapter_unit_test", "review_chapter_unit_test"]
    assert markdown.count("> [!QUESTION]") == markdown.count("> [!ANSWER]") == 9
    assert markdown.count("｜应用迁移｜") == 4
    assert markdown.count("｜填空题｜") == 5
    assert unit_test_structure_issues(markdown, expected_question_count=9) == []


@pytest.mark.parametrize("count", [9, 12, 20, 25])
def test_reviewers_receive_every_exact_group_after_task_round_trip(count: int) -> None:
    task = _compile(ChapterExecutionBrief(
        quantity_constraints={"chapter_end_question_count": count},
        chapter_end_practice_plan=[
            {"target": f"独立考点{i}", "question_count": 1} for i in range(1, count + 1)
        ],
    ))
    payload = task.model_dump(mode="json")
    chapter_prompt = build_chapter_review_messages(
        chapter_title=TITLE, digest_mode="sprint", chapter_task=payload,
        markdown="正文", claim_ledger={}, claim_evidence_map={}, conflict_report={}, rule_review={},
    )[-1]["content"]
    document_prompt = build_document_review_messages(
        digest_mode="sprint", reviewed_chapters=[], rule_report={}, chapter_tasks=[payload],
    )[-1]["content"]
    for prompt in (chapter_prompt, document_prompt):
        for i in range(1, count + 1):
            assert f"独立考点{i}" in prompt
        assert prompt.count("'question_count': 1") == count


@pytest.mark.anyio
@pytest.mark.parametrize("group_counts", [(4, 5), (14, 6), (20,), (1,) * 25, (17, 16, 7)])
async def test_large_explicit_sets_are_batched_reviewed_and_published_in_full(group_counts) -> None:
    total = sum(group_counts)
    groups = [
        {"target": f"整数加法题组{index}", "question_count": count,
         "question_type": "应用迁移" if index % 2 == 0 else "填空题"}
        for index, count in enumerate(group_counts)
    ]
    task = _compile(ChapterExecutionBrief(
        quantity_constraints={"chapter_end_question_count": total}, chapter_end_practice_plan=groups,
    ))
    contract = _chapter_plan_for_writer(task, total_chapters=1)["execution_contract"]
    expected_types = [group["question_type"] for group in groups for _ in range(group["question_count"])]
    batch_sizes = [total] if total <= 12 else [
        min(12, count - start) for count in group_counts for start in range(0, count, 12)
    ]
    calls: list[tuple[int, str]] = []

    async def fake_quiz(messages, **kwargs):
        prompt = messages[-1]["content"]
        received = json.loads(prompt.split(
            "用户确认的需求与章节写作合同（固定题型、数量和主题边界优先）：\n", 1,
        )[1].splitlines()[0])
        batch = received.get("unit_test_batch") or {"batch_index": 1, "previous_questions": []}
        start = len(batch["previous_questions"])
        count = batch_sizes[batch["batch_index"] - 1]
        assert received.get("chapter_writing_contract", received)["quantity_constraints"]["chapter_end_question_count"] == total
        assert received["quantity_constraints"]["chapter_end_question_count"] == count
        assert f"题量范围：{count}-{count}" in prompt
        assert kwargs["max_tokens"] >= 600 * count
        schema = kwargs["response_model"].model_json_schema()["properties"]["items"]
        assert schema["minItems"] == schema["maxItems"] == count
        calls.append((batch["batch_index"], kwargs["extra_metadata"]["docgen_stage"]))
        return ChapterUnitTestSet(items=[
            ChapterUnitTestItem(
                type=expected_types[i], target=f"整数{i}加一",
                stem=f"计算 ${i}+1$。", answer=str(i + 1), basis=f"从{i}增加1，得到{i + 1}。",
            ) for i in reversed(range(start, start + count))
        ])

    markdown = await generate_chapter_unit_test_markdown(
        chapter_index=1, chapter_title=TITLE, digest_mode="sprint", required_elements=["整数加法"],
        chapter_end_practice_plan=contract["chapter_end_practice_plan"],
        body_markdown="# 整数加法\n\n## 加一\n\n在原数上增加1。",
        min_items=3, max_items=4,  # Stale mode defaults must not override the explicit contract.
        writing_contract={"quantity_constraints": contract["quantity_constraints"]}, llm_caller=fake_quiz,
    )
    assert calls == [
        (index, stage) for index in range(1, len(batch_sizes) + 1)
        for stage in ["generate_chapter_unit_test", "review_chapter_unit_test"]
    ]
    assert markdown.count("## 单元测试") == 1
    assert markdown.count("> [!QUESTION]") == markdown.count("> [!ANSWER]") == total
    for kind in set(expected_types):
        assert markdown.count(f"｜{kind}｜") == expected_types.count(kind)
    assert re.findall(r'\[!QUESTION\][^\n]*?｜([^｜]+)｜', markdown) == expected_types
    assert unit_test_structure_issues(markdown, expected_question_count=total) == []
