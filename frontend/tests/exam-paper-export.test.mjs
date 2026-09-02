import assert from "node:assert/strict";
import test from "node:test";

import {
  buildExamExportFilename,
  buildExamPaperExportDetail,
  formatExamExportDate,
  getExamPaperExportAvailability,
  waitForExamPrintImages,
} from "../src/components/exams/examPaperExport.ts";
import { buildHashRouterUrl } from "../src/lib/electronRuntime.ts";

test("仅完整题面和已完成记录允许导出", () => {
  assert.deepEqual(getExamPaperExportAvailability("ready"), {
    available: true,
    kind: "blank",
    label: "导出空白卷",
    description: "仅包含题目与空白答题区域",
  });
  assert.equal(getExamPaperExportAvailability("in_progress").kind, "blank");
  assert.equal(getExamPaperExportAvailability("graded").kind, "graded");
  assert.equal(getExamPaperExportAvailability("graded", "mastery_drill").available, false);

  for (const status of ["draft", "generating", "failed", "submitted", "grading", "grading_failed"]) {
    const availability = getExamPaperExportAvailability(status);
    assert.equal(availability.available, false, status);
    assert.equal(availability.description, "题目尚未完整生成", status);
  }
});

test("空白卷在显示层再次移除答案、评分和解析", () => {
  const paper = {
    id: 12,
    course_id: "course_123456789abc",
    user_id: "user",
    exam_mode: "web_practice",
    status: "ready",
    total_items: 1,
    score_obtained: 1,
    total_score: 1,
    submitted_at: "2026-09-02T00:00:00Z",
    graded_at: "2026-09-02T00:01:00Z",
    created_at: "2026-09-02T00:00:00Z",
    selection_context: {},
    profile_sync: { status: "completed" },
    mastery_drill: null,
    paper_preview: { keywords: [], question_types: [], rows: [], overflow_count: 0 },
    items: [{
      id: 1,
      item_order: 1,
      question_template_id: 2,
      question_type: "single_choice",
      difficulty: "easy",
      stem: "题干",
      options: ["选项 A", "选项 B"],
      correct_answer: "A",
      explanation: "解析",
      knowledge_unit_links: [],
      selection_context: {},
      user_answer: "B",
      is_correct: false,
      score_obtained: 0,
      score_max: 1,
      error_cause_label: "knowledge_gap",
      is_marked: false,
    }],
  };

  const exported = buildExamPaperExportDetail(paper, "blank");
  assert.equal(exported.items[0].stem, "题干");
  assert.equal(exported.items[0].user_answer, null);
  assert.equal(exported.items[0].correct_answer, null);
  assert.equal(exported.items[0].explanation, "");
  assert.equal(exported.items[0].is_correct, null);
  assert.equal(exported.items[0].score_obtained, null);
  assert.equal(exported.profile_sync, null);
});

test("批改结果保留权威详情对象，文件名移除系统非法字符", () => {
  const paper = { status: "graded", items: [{ user_answer: "A", correct_answer: "A" }] };
  assert.equal(buildExamPaperExportDetail(paper, "graded"), paper);
  assert.equal(
    buildExamExportFilename("高数/测验:*?", "graded", "2026-09-02T08:09:00"),
    "高数-测验-批改结果-20260902-1609.pdf",
  );
});

test("导出时间按后端 UTC 约定解析并固定显示为上海时区", () => {
  assert.equal(formatExamExportDate("2026-09-02T08:09:00"), "20260902-1609");
  assert.equal(formatExamExportDate("2026-09-02T08:09:00Z"), "20260902-1609");
  assert.equal(formatExamExportDate("2026-09-02T08:09:00+08:00"), "20260902-0809");
});

test("Electron 导出地址保留入口文件并把路由与查询参数写入 hash", () => {
  const route = "/courses/mock/exams/4/print?auto=1&mock=1";
  assert.equal(
    buildHashRouterUrl("http://127.0.0.1:5180/#/courses/mock/exams", route),
    "http://127.0.0.1:5180/#/courses/mock/exams/4/print?auto=1&mock=1",
  );
  assert.equal(
    buildHashRouterUrl("file:///D:/AITeachMe/dist/index.html#/courses/mock/exams", route),
    "file:///D:/AITeachMe/dist/index.html#/courses/mock/exams/4/print?auto=1&mock=1",
  );
});

test("自动打印会等待懒加载图片完成并执行 decode", async () => {
  let decodeCalls = 0;
  const image = new EventTarget();
  image.complete = false;
  image.loading = "lazy";
  image.decode = async () => {
    decodeCalls += 1;
  };

  const ready = waitForExamPrintImages([image]);
  await Promise.resolve();
  assert.equal(image.loading, "eager");
  assert.equal(decodeCalls, 0);

  image.complete = true;
  image.dispatchEvent(new Event("load"));
  await ready;
  assert.equal(decodeCalls, 1);

  await assert.doesNotReject(() => waitForExamPrintImages([{
    complete: true,
    loading: "lazy",
    decode: async () => {
      throw new Error("broken image");
    },
  }]));
});
