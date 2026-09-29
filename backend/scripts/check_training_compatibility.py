"""Check upgrade/disable behavior on the isolated acceptance paper fixture."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from run_training_acceptance import Acceptance, ROOT, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9031)
    parser.add_argument("--paper-id", type=int, required=True)
    args = parser.parse_args()
    data = args.data_dir.resolve()
    if not data.is_relative_to((BACKEND / "tmp").resolve()) or not (data / "manifest.json").is_file():
        parser.error("Use an isolated acceptance directory")
    os.environ.update(AITEACHME_DATA_DIR=str(data), APP_MODE="local", LANGSMITH_TRACING="false", POSTHOG_ENABLED="false")
    from app.workflows.support.question_type_packages import build_atqskill_archive

    runner = Acceptance(data, args.port)
    course = runner.state["runs"]["paper_exam"]["course_id"]
    base = f"/api/v1/courses/{course}"
    with sqlite3.connect(data / "aiteachme.db") as db:
        db.row_factory = sqlite3.Row
        paper = db.execute("SELECT * FROM exam_paper WHERE id=? AND course_id=?", (args.paper_id, course)).fetchone()
        assert paper and paper["status"] == "ready", "Use a fresh ready fixture"
        rows = db.execute("SELECT * FROM exam_paper_item WHERE exam_paper_id=? ORDER BY item_order", (args.paper_id,)).fetchall()
        snapshot_fields = ("answer_schema_snapshot_json", "reference_answer_snapshot_json", "grading_spec_snapshot_json", "runtime_snapshot_json")

        def fingerprint(items):
            return hashlib.sha256(json.dumps([[row[key] for key in snapshot_fields] for row in items]).encode()).hexdigest()

        before = fingerprint(rows)
        selected = next(row for row in rows if row["question_type"] == "custom_case_analysis")
        registry = selected["question_type_registry_id"]
        old_version = selected["question_type_version_id"]
        folder = data / "upgrade-case-analysis"
        shutil.copytree(ROOT / "examples/question-type-skills/case_analysis", folder, dirs_exist_ok=True)
        skill = folder / "SKILL.md"
        skill.write_text(skill.read_text("utf-8").replace("version: 2.0.0", "version: 2.0.1").replace("pass_score: 0.7", "pass_score: 0.75"), encoding="utf-8")
        package = build_atqskill_archive(folder, data / "packages/case-analysis-upgrade.atqskill")
        preview = runner.request("POST", f"{base}/question-types/imports", files={"file": (package.name, package.read_bytes(), "application/zip")})
        assert preview["valid"] and preview["conflict"] == "new_version"
        installed = runner.request("POST", f"{base}/question-types/imports/{preview['import_id']}/confirm", json={"set_current": True})
        assert installed["registry_id"] == registry and installed["version_id"] != old_version
        runner.request("PATCH", f"{base}/question-types/{registry}", json={"status": "inactive"})
        try:
            rejected = runner.client.post(f"{base}/exams/generate", json={"exam_mode": "web_practice", "num_questions": 1, "question_type_selections": [{"registry_id": registry}]})
            assert rejected.status_code == 409
            detail = runner.request("GET", f"{base}/exams/{args.paper_id}")
            assert next(i for i in detail["items"] if i["question_type"] == "custom_case_analysis")["question_type_version_id"] == old_version
            body = {"answers": [], "submission_key": "p4-compatibility-blank"}
            runner.request("POST", f"{base}/exams/{args.paper_id}/submit", json=body)
            graded = runner.wait_paper(f"{base}/exams", args.paper_id, "graded")
            assert graded["score_obtained"] == 0 and all(i["grading_status"] == "graded" for i in graded["items"])
            replay = runner.request("POST", f"{base}/exams/{args.paper_id}/submit", json=body)
            assert replay["status"] == "completed" and replay["score"] == 0
            after_rows = db.execute("SELECT * FROM exam_paper_item WHERE exam_paper_id=? ORDER BY item_order", (args.paper_id,)).fetchall()
            assert fingerprint(after_rows) == before
            # Same submission key with a different answer must still conflict.
            changed = {"submission_key": body["submission_key"], "answers": [{"item_order": 7, "answer": "A"}]}
            conflict = runner.client.post(f"{base}/exams/{args.paper_id}/submit", json=changed)
            assert conflict.status_code == 409
            save(data / "compatibility-result.json", {"paper_id": args.paper_id, "old_version": old_version, "new_version": installed["version_id"], "old_pass_score": json.loads(selected["grading_spec_snapshot_json"])["pass_score"], "new_pass_score": 0.75, "frozen_fingerprint_before": before, "frozen_fingerprint_after": fingerprint(after_rows), "disabled_new_generation_status": rejected.status_code, "old_paper_grades_while_disabled": True, "omitted_answers_score": graded["score_obtained"], "replay_status": replay["status"], "changed_submission_status": conflict.status_code})
            print("Upgrade, disable, frozen snapshots, omitted answers and submission idempotency passed.")
        finally:
            runner.request("PATCH", f"{base}/question-types/{registry}", json={"status": "active", "current_version_id": old_version})
            runner.client.close()


if __name__ == "__main__":
    main()
