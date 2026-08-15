import assert from "node:assert/strict";
import test from "node:test";

import { parseExamStudyGuideStreamPayload } from "../src/components/exams/examStudyGuideStream.ts";
import {
  getStudyGuideGenerationProgress,
  getNextStudyGuideSection,
  getStudyGuideProgressValue,
  getStudyGuideSectionVisibility,
  mergeStudyGuideActionItems,
} from "../src/components/exams/studyGuideDisplay.ts";

const guide = {
  schema_version: 2,
  exam_paper_id: 42,
  course_name: "线性代数",
  generated_at: "2026-08-14T10:00:00Z",
  overall_summary: "本次作答整体稳定，建议继续巩固矩阵秩与线性映射。",
  strengths: ["基础概念清晰"],
  priority_gaps: ["矩阵秩"],
  action_steps: ["复习定义"],
  review_tasks: ["完成两道变式题"],
  focus_units: [{
    knowledge_unit_id: 12,
    knowledge_unit_name: "矩阵秩",
    paper_attempts: 2,
    paper_correct_attempts: 1,
    paper_score_obtained: 1,
    paper_score_max: 2,
    paper_score_rate: 0.5,
    mastery_score: 0.8,
    reason: "本卷关联 2 题，按分值计 1/2 分。",
  }],
};

test("parses study-guide progress and terminal SSE payloads", () => {
  assert.deepEqual(
    parseExamStudyGuideStreamPayload(JSON.stringify({
      exam_paper_id: 42,
      status: "generating",
      detail: "正在整理薄弱点...",
    })),
    {
      exam_paper_id: 42,
      status: "generating",
      detail: "正在整理薄弱点...",
    },
  );

  const completed = parseExamStudyGuideStreamPayload(JSON.stringify({
    exam_paper_id: 42,
    status: "completed",
    guide,
  }));
  assert.deepEqual(completed?.guide, guide);
});

test("parses incremental study-guide content snapshots", () => {
  const draft = {
    ...guide,
    overall_summary: "本次作答整体稳定，建议优先回顾",
    strengths: [],
    priority_gaps: [],
    action_steps: [],
    review_tasks: [],
  };
  const content = parseExamStudyGuideStreamPayload(JSON.stringify({
    exam_paper_id: 42,
    status: "generating",
    sequence: 3,
    draft,
  }));

  assert.equal(content?.sequence, 3);
  assert.deepEqual(content?.draft, draft);
});

test("rejects malformed study-guide SSE data without throwing", () => {
  assert.equal(parseExamStudyGuideStreamPayload("not-json"), null);
  assert.equal(parseExamStudyGuideStreamPayload("[]"), null);

  const malformedGuide = parseExamStudyGuideStreamPayload(JSON.stringify({
    status: "completed",
    guide: { exam_paper_id: 42 },
  }));
  assert.equal(malformedGuide?.guide, undefined);

  const malformedDraft = parseExamStudyGuideStreamPayload(JSON.stringify({
    status: "generating",
    sequence: -1,
    draft: { exam_paper_id: 42 },
  }));
  assert.equal(malformedDraft?.sequence, undefined);
  assert.equal(malformedDraft?.draft, undefined);
});

test("does not let an empty optional section block later streamed sections", () => {
  assert.deepEqual(
    getStudyGuideSectionVisibility({
      strengths: false,
      focusUnits: true,
      priorityGaps: true,
      actionSteps: true,
    }),
    {
      strengths: false,
      focusUnits: true,
      priorityGaps: true,
      actionSteps: true,
    },
  );

  assert.deepEqual(
    getStudyGuideSectionVisibility({
      strengths: true,
      focusUnits: true,
      priorityGaps: false,
      actionSteps: false,
    }),
    {
      strengths: true,
      focusUnits: true,
      priorityGaps: false,
      actionSteps: false,
    },
  );
});

test("advances study-guide progress with the visible streamed sections", () => {
  assert.deepEqual(
    getStudyGuideGenerationProgress({
      hasSummary: true,
      strengths: true,
      focusUnits: true,
      priorityGaps: false,
      actionSteps: false,
    }),
    { label: "正在提炼优先补漏" },
  );
  assert.deepEqual(
    getStudyGuideGenerationProgress({
      hasSummary: true,
      strengths: false,
      focusUnits: true,
      priorityGaps: true,
      actionSteps: true,
    }),
    { label: "正在完善学习步骤" },
  );
});

test("keeps unknown-duration generation indeterminate until all content is visible", () => {
  assert.equal(
    getStudyGuideProgressValue({ isStreaming: true, hasPendingSection: false }),
    undefined,
  );
  assert.equal(
    getStudyGuideProgressValue({ isStreaming: false, hasPendingSection: true }),
    undefined,
  );
  assert.equal(
    getStudyGuideProgressValue({ isStreaming: false, hasPendingSection: false }),
    100,
  );
});

test("reveals priority gaps before action steps when both arrive together", () => {
  const availability = {
    strengths: false,
    focusUnits: true,
    priorityGaps: true,
    actionSteps: true,
  };
  assert.equal(
    getNextStudyGuideSection(availability, {
      strengths: false,
      focusUnits: true,
      priorityGaps: false,
      actionSteps: false,
    }),
    "priorityGaps",
  );
  assert.equal(
    getNextStudyGuideSection(availability, {
      strengths: false,
      focusUnits: true,
      priorityGaps: true,
      actionSteps: false,
    }),
    "actionSteps",
  );
});

test("merges legacy review tasks into next steps without a fifth section", () => {
  assert.deepEqual(
    mergeStudyGuideActionItems(
      ["复盘错题", "完成两道变式题"],
      ["完成两道变式题", "整理错因"],
    ),
    ["复盘错题", "完成两道变式题", "整理错因"],
  );
});

test("keeps only the three highest-priority next steps", () => {
  assert.deepEqual(
    mergeStudyGuideActionItems(
      ["步骤一", "步骤二", "步骤三", "步骤四"],
      ["旧复习任务"],
    ),
    ["步骤一", "步骤二", "步骤三"],
  );
});
