"""Opt-in real grading evaluation. No live provider calls in ordinary pytest.

Uses frozen example definitions and production grading with the shared scheduler.
Expected intervals are recorded before running; misses remain visible for review.
Held-out fixtures are agent-authored and use the production automatic grader.
No human approval is required; score-interval misses remain visible in results.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import time

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from run_training_acceptance import EXAMPLES, ROOT, save


async def evaluate(data: Path):
    from app.api.exams import _custom_runtime_persistence_payload
    from app.models import ExamPaperItem
    from app.shared.infra.database import init_db
    from app.shared.infra.llm_support import run_llm_tasks
    from app.shared.infra.observability.llm_stats import get_tracker
    from app.workflows.examine.exam_grade.lib.grader import _grade_custom_rubric_item
    from app.workflows.support.question_type_packages import validate_atqskill
    init_db()
    path = data / "quality-results.json"
    done = json.loads(path.read_text("utf-8")) if path.exists() else {"results": []}
    finished = {row["id"] for row in done["results"]}
    independent = json.loads((BACKEND / "tests/fixtures/training_quality_independent.json").read_text("utf-8"))
    tasks = []
    for name in EXAMPLES:
        result = validate_atqskill(data / "packages" / f"{name}.atqskill")
        assert result.valid
        definition = result.compiled_definition.model_dump(mode="json")
        runtime = {"registry_id": 1, "version_id": 1, "type_key": definition["type_key"], "version": definition["version"], "package_hash": result.package_hash, "profile_eligible": False, "definition": definition}
        # Evaluate the cases frozen in this installed archive. Working-tree
        # examples may have been upgraded since this acceptance run started.
        package_cases = [{
            "id": case["id"], "knowledge_unit": case["knowledge_unit"], "question": case["question"],
            "answers": [{
                "label": answer["label"], "content": answer["content"],
                "expected_score": {"min": answer["expected_score_min"], "max": answer["expected_score_max"]},
                "expected_pass": answer["expected_pass"],
            } for answer in case["answers"]],
        } for case in definition["reference_cases"]]
        cases = [("package", case) for case in package_cases]
        for case in independent["cases"]:
            if case["example"] == name:
                cases.append(("held_out_agent", {**case, "question": {"stem": case["stem"], "reference_answer": case.get("reference_answer") or case["answers"][0]["content"], "explanation": "评价推理的正确性、论据与结论边界。"}}))
        fields = [field["key"] for field in definition["answer_fields"]]
        for source, case in cases:
            reference = case["question"]["reference_answer"]
            # Historical V1 multi-field examples have a prose reference. Their
            # strong answer supplies the same reference in the declared fields.
            if isinstance(reference, str) and len(fields) > 1:
                reference = case["answers"][0]["content"]
            frozen = _custom_runtime_persistence_payload(runtime, answer=reference if isinstance(reference, str) else "", answer_payload=reference if isinstance(reference, dict) else None)
            samples = [*case["answers"], {"label": "blank", "content": {key: "" for key in fields}, "expected_score": {"min": 0, "max": 0}, "expected_pass": False}]
            for sample in samples:
                identity = f"{source}/{name}/{case['id']}/{sample['label']}"
                if identity in finished:
                    continue
                answer = sample["content"] if isinstance(sample["content"], dict) else {fields[0]: sample["content"]}
                item = ExamPaperItem(exam_paper_id=1, item_order=1, question_type=definition["type_key"], question_type_version_id=1, score=1, difficulty="medium", stem_snapshot=case["question"]["stem"], answer_snapshot=case["question"]["reference_answer"] if isinstance(case["question"]["reference_answer"], str) else json.dumps(reference, ensure_ascii=False), explanation_snapshot=case["question"]["explanation"], answer_schema_snapshot_json=json.dumps(frozen["answer_schema"]), reference_answer_snapshot_json=json.dumps(frozen["reference_answer"]), grading_spec_snapshot_json=json.dumps(frozen["grading_spec"]), runtime_snapshot_json=json.dumps(frozen["runtime_snapshot"]), answer_payload_json=json.dumps(answer), profile_eligible=False)
                tasks.append((identity, source, sample, item))

    async def worker(task):
        identity, source, sample, item = task
        started = time.monotonic()
        row = {"id": identity, "source": source, "label": sample["label"], "expected_score": sample["expected_score"], "expected_pass": sample["expected_pass"]}
        try:
            decision = await _grade_custom_rubric_item("课程评分验收", item)
            low, high = sample["expected_score"]["min"], sample["expected_score"]["max"]
            row.update(decision=asdict(decision), passed=low <= decision.score_obtained <= high and decision.is_correct == sample["expected_pass"])
        except Exception as exc:
            row.update(passed=False, error_type=type(exc).__name__)
        row["elapsed_seconds"] = round(time.monotonic() - started, 3)
        done["results"].append(row)
        save(path, done)
        print(f"{identity}: {'PASS' if row['passed'] else 'REVIEW'} score={row.get('decision',{}).get('score_obtained')} ({row['elapsed_seconds']} s)", flush=True)
        return row

    await run_llm_tasks(tasks, worker, max_concurrent=3)
    usage_path = data / "quality-usage.json"
    records = json.loads(usage_path.read_text("utf-8")) if usage_path.exists() else []
    recorded_calls = {row["call_id"] for row in records}
    for record in get_tracker()._records:
        row = asdict(record)
        row.pop("error", None)
        if row["call_id"] not in recorded_calls:
            records.append(row)
            recorded_calls.add(row["call_id"])
    # A resumed evaluation may have no remaining cases. Keep usage from earlier
    # invocations so a successful resume cannot erase the cost evidence.
    save(usage_path, records)
    done["summary"] = {"total": len(done["results"]), "passed": sum(row["passed"] for row in done["results"]), "review": [row["id"] for row in done["results"] if not row["passed"]], "sources": dict(Counter(row["source"] for row in done["results"])), "evaluation_mode": "automatic_llm", "human_review_required": False, "human_calibrated": False}
    save(path, done)
    print(json.dumps(done["summary"], ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    data = args.data_dir.resolve()
    if not data.is_relative_to((BACKEND / "tmp").resolve()) or not (data / "manifest.json").is_file():
        parser.error("Use an initialized isolated training acceptance directory")
    os.environ.update(AITEACHME_DATA_DIR=str(data), APP_MODE="local", LANGSMITH_TRACING="false", POSTHOG_ENABLED="false")
    asyncio.run(evaluate(data))


if __name__ == "__main__":
    main()
