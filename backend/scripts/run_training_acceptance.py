"""Opt-in real-model training acceptance against an isolated local application.

Run setup, serve (in another terminal), generate, then submit. This script never
uses the user's course database for writes. Reference answers in smoke tests
check the transport/persistence contract, not independent grading quality.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
DEVICE = "p4-training-acceptance-device"
USER = "p4-training-acceptance"
MODES = ("web_practice", "paper_exam", "mastery_drill")
COURSES = {mode: f"course_p4{index:010d}" for index, mode in enumerate(MODES, 1)}
EXAMPLES = ("feynman_explanation", "oral_defense", "scenario_interview", "argument_debate", "experiment_design", "case_analysis")
UNITS = [
    ("随机分组与因果推断", "将个体随机分到实验组和对照组，减少分组前混杂。相关性不能单独证明因果。"),
    ("控制变量与对照实验", "每次只操纵目标自变量，测量因变量，两组保持其他条件一致。空白对照用于分离处理效果。"),
    ("重复测量与样本量", "增加独立样本可以减少随机误差，重复读同一样本不能等同于增加独立样本。"),
    ("均值与极端值", "均值等于总和除以样本数，易受极端值影响；偏态数据可结合中位数和原始数据解释。"),
    ("不确定性与结论边界", "小样本、测量误差和样本来源限制结论外推。未观察到差异不能证明两种方法完全相同。"),
    ("实验伦理与透明记录", "如实报告所有预先规定的结果，不选择性删除不支持假设的数据。先设定分析方法与排除标准。"),
]


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def setup(data: Path, settings_db: Path) -> None:
    target = data / "aiteachme.db"
    if target.exists():
        raise SystemExit("Use a new acceptance directory; setup will not overwrite an existing database.")
    from sqlmodel import Session, SQLModel
    import app.models  # noqa: F401
    from app.models import Course, KnowledgeUnit, SystemRuntimeSettings, User
    from app.shared.infra.database import get_engine, init_db

    SQLModel.metadata.create_all(get_engine())
    with sqlite3.connect(settings_db.resolve().as_uri() + "?mode=ro", uri=True) as source:
        row = source.execute("SELECT settings_json FROM system_runtime_settings WHERE id='runtime'").fetchone()
    with Session(get_engine()) as session:
        if row:
            session.add(SystemRuntimeSettings(id="runtime", settings_json=json.loads(row[0])))
            session.commit()
    init_db()
    with Session(get_engine()) as session:
        session.add(User(id=USER, username=USER, device_key=DEVICE))
        session.commit()
        for mode, course_id in COURSES.items():
            session.add(Course(id=course_id, user_id=USER, name=f"P4 科学实验方法 · {mode}",
                               description="隔离验收课程：科学实验设计、统计推理与证据评价。"))
            session.commit()
            for name, summary in UNITS:
                session.add(KnowledgeUnit(course_id=course_id, knowledge_unit_type="concept",
                                          canonical_name=name, normalized_name=name, summary=summary,
                                          body=summary, status="active"))
        session.commit()
    save(data / "manifest.json", {"courses": COURSES, "device_key": DEVICE, "models_source": "local runtime settings", "production_data_written": False})
    print("Isolated database and three synthetic courses created.", flush=True)


def serve(data: Path, port: int) -> None:
    import uvicorn
    from app.shared.infra.observability.llm_stats import get_tracker

    tracker = get_tracker()
    original = tracker.record

    def record_usage(record):
        original(record)
        payload = asdict(record)
        # Errors may include provider details. The acceptance ledger stores only
        # status and usage; normal application diagnostics stay in the local log.
        payload.pop("error", None)
        with (data / "usage.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    tracker.record = record_usage
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="warning")


class Acceptance:
    def __init__(self, data: Path, port: int):
        import httpx
        self.data = data
        self.client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=600,
                                   headers={"x-device-key": DEVICE})
        self.state_path = data / "results.json"
        self.state = json.loads(self.state_path.read_text("utf-8")) if self.state_path.exists() else {"runs": {}}

    def request(self, method: str, path: str, **kwargs):
        response = self.client.request(method, path, **kwargs)
        if response.status_code != 200:
            raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {response.text[:500]}")
        payload = response.json()
        assert payload["code"] == 0, payload
        return payload["data"]

    def checkpoint(self):
        save(self.state_path, self.state)

    def install(self, course: str):
        from app.workflows.support.question_type_packages import build_atqskill_archive
        installed = []
        for name in EXAMPLES:
            package = build_atqskill_archive(ROOT / "examples/question-type-skills" / name,
                                             self.data / "packages" / f"{name}.atqskill")
            base = f"/api/v1/courses/{course}/question-types"
            preview = self.request("POST", f"{base}/imports", files={"file": (package.name, package.read_bytes(), "application/zip")})
            assert preview["valid"] and preview["runtime_ready"], preview
            item = self.request("POST", f"{base}/imports/{preview['import_id']}/confirm", json={"set_current": True})
            assert item["status"] == "active"
            installed.append(item)
        return installed

    def wait_paper(self, base: str, paper_id: int, target: str, timeout: int = 600):
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            detail = self.request("GET", f"{base}/{paper_id}")
            if detail["status"] == target:
                return detail
            if detail["status"] in {"failed", "grading_failed"}:
                save(self.data / f"failed-paper-{paper_id}.json", detail)
                raise RuntimeError(f"Paper {paper_id}: {detail['status']}")
            time.sleep(2)
        raise TimeoutError(f"Paper {paper_id} still running; inspect server before retrying.")

    def generate(self):
        for mode, course in COURSES.items():
            run = self.state["runs"].setdefault(mode, {"course_id": course})
            if "ready" in run:
                continue
            if "installed" not in run:
                run["installed"] = self.install(course)
            installed = run["installed"]
            self.checkpoint()
            selections = [{"registry_id": item["registry_id"], "version_id": item["version_id"], "count": 1} for item in installed]
            # The two persisted papers also exercise built-in/custom mixing.
            if mode != "mastery_drill":
                selections.append({"question_type": "single_choice", "count": 1})
            base = f"/api/v1/courses/{course}/exams"
            started = time.monotonic()
            if mode == "mastery_drill":
                result = self.request("POST", f"{base}/mastery-drills/prepare", json={"num_questions": len(selections), "question_type_selections": selections})
                assert result["generated_count"] == 6 and len(result["templates"]) == 6
                items = result["templates"]
            else:
                if "paper_id" not in run:
                    response = self.request("POST", f"{base}/generate", json={"exam_mode": mode, "num_questions": len(selections), "question_type_selections": selections, "difficulty": "medium"})
                    run["paper_id"] = response["exam_paper_id"]
                    self.checkpoint()
                result = self.wait_paper(base, run["paper_id"], "ready")
                items = result["items"]
                assert all(not item.get("correct_answer") and not item.get("explanation") and not item.get("grading_detail") for item in items)
            expected = Counter({item["type_key"]: 1 for item in installed})
            if mode != "mastery_drill":
                expected["single_choice"] = 1
            assert Counter(item["question_type"] for item in items) == expected
            assert all(item["profile_eligible"] is False and item["answer_schema"]["fields"] for item in items if item["question_type"].startswith("custom_"))
            run.update(ready=result, generation_seconds=round(time.monotonic() - started, 3))
            self.checkpoint()
            print(f"{mode}: {len(items)} real questions ready in {run['generation_seconds']} s", flush=True)

    def submit(self):
        for mode, run in self.state["runs"].items():
            if "graded" in run:
                continue
            course = run["course_id"]
            base = f"/api/v1/courses/{course}/exams"
            started = time.monotonic()
            with sqlite3.connect(self.data / "aiteachme.db") as db:
                db.row_factory = sqlite3.Row
                if mode == "mastery_drill":
                    rows = db.execute("SELECT * FROM question_template WHERE course_id=? AND question_type_version_id IS NOT NULL", (course,)).fetchall()
                    graded = run.setdefault("drill_grades", [])
                    done_ids = {item["question_template_id"] for item in graded}
                    for row in rows:
                        if row["id"] in done_ids:
                            continue
                        result = self.request("POST", f"{base}/question-templates/{row['id']}/grade", json={"answer_payload": json.loads(row["reference_answer_json"]), "ephemeral": True})
                        assert result["grading_mode"] == "custom_rubric_llm" and result["grading_detail"]
                        graded.append(result)
                        self.checkpoint()
                    assert db.execute("SELECT COUNT(*) FROM exam_paper WHERE course_id=?", (course,)).fetchone()[0] == 0
                    assert db.execute("SELECT COUNT(*) FROM mastery_drill_session").fetchone()[0] == 0
                else:
                    rows = db.execute("SELECT * FROM exam_paper_item WHERE exam_paper_id=? ORDER BY item_order", (run["paper_id"],)).fetchall()
                    answers = [{"item_order": row["item_order"], **({"answer_payload": json.loads(row["reference_answer_snapshot_json"])} if row["question_type"].startswith("custom_") else {"answer": row["answer_snapshot"]})} for row in rows]
                    body = {"answers": answers, "submission_key": f"p4-{mode}-smoke"}
                    self.request("POST", f"{base}/{run['paper_id']}/submit", json=body)
                    graded = self.wait_paper(base, run["paper_id"], "graded")
                    retry = self.request("POST", f"{base}/{run['paper_id']}/submit", json=body)
                    assert retry["status"] == "completed"
                    assert abs(graded["score_obtained"] - sum(item["score_obtained"] for item in graded["items"])) < 0.001
                    for item, answer in zip(graded["items"], answers):
                        if "answer_payload" in answer:
                            assert item["user_answer_payload"] == answer["answer_payload"]
                            assert item["grading_status"] == "graded" and item["grading_detail"]
                            assert item["profile_eligible"] is False
            request_seconds = round(time.monotonic() - started, 3)
            # A resumed paper submission may just read an already completed
            # grade. Its request latency is not the original grading duration.
            grading_seconds = request_seconds if mode == "mastery_drill" else round(
                (datetime.fromisoformat(graded["graded_at"]) - datetime.fromisoformat(graded["submitted_at"])).total_seconds(), 3
            )
            run.update(graded=graded, grading_seconds=grading_seconds, submit_request_seconds=request_seconds)
            self.checkpoint()
            print(f"{mode}: grading {grading_seconds} s; this submit/read-back invocation {request_seconds} s", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["setup", "serve", "generate", "submit"])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9031)
    parser.add_argument("--settings-db", type=Path, default=BACKEND / "data/aiteachme.db")
    args = parser.parse_args()
    data = args.data_dir.resolve()
    # Hard guard against accidentally pointing an acceptance run at user data.
    if not data.is_relative_to((BACKEND / "tmp").resolve()) or data == (BACKEND / "tmp").resolve():
        parser.error("--data-dir must be a dedicated child of backend/tmp")
    data.mkdir(parents=True, exist_ok=True)
    os.environ.update(AITEACHME_DATA_DIR=str(data), APP_MODE="local", LANGSMITH_TRACING="false", POSTHOG_ENABLED="false", EXPORT_OPENAPI_ON_STARTUP="false")
    if args.phase == "setup":
        setup(data, args.settings_db)
    elif args.phase == "serve":
        if not (data / "manifest.json").is_file():
            parser.error("Run setup before serve")
        serve(data, args.port)
    else:
        runner = Acceptance(data, args.port)
        try:
            getattr(runner, args.phase)()
        finally:
            runner.client.close()


if __name__ == "__main__":
    main()
