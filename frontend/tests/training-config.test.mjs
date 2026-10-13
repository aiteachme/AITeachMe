import assert from "node:assert/strict";
import test from "node:test";

import {
  getDefaultCreateExamConfigForMode,
  loadCreateExamConfig,
  normalizeCreateExamConfig,
  saveCreateExamConfig,
  toExamGenerateRequest,
} from "../src/components/exams/examConfig.ts";
import {
  loadMasteryDrillConfig,
  saveMasteryDrillConfig,
  toggleMasteryDrillQuestionType,
} from "../src/components/exams/masteryDrillConfig.ts";
import { isTrainingDetailPath } from "../src/lib/courseNavigation.ts";

class MemoryStorage {
  values = new Map();

  getItem(key) {
    return this.values.get(key) ?? null;
  }

  setItem(key, value) {
    this.values.set(key, String(value));
  }
}

test("stores practice and paper configurations independently per course", () => {
  const storage = new MemoryStorage();
  saveCreateExamConfig(
    "course-1",
    {
      ...getDefaultCreateExamConfigForMode("web_practice"),
      numQuestions: 12,
      questionTypes: ["single_choice", "true_false"],
      difficulty: "easy",
    },
    storage,
  );
  saveCreateExamConfig(
    "course-1",
    {
      ...getDefaultCreateExamConfigForMode("paper_exam"),
      numQuestions: 36,
      questionTypes: ["fill_blank", "short_answer"],
      difficulty: "hard",
    },
    storage,
  );

  const practice = loadCreateExamConfig("course-1", "web_practice", storage);
  const paper = loadCreateExamConfig("course-1", "paper_exam", storage);

  assert.equal(practice.numQuestions, 12);
  assert.deepEqual(practice.questionTypes, ["single_choice", "true_false"]);
  assert.equal(practice.difficulty, "easy");
  assert.equal(paper.numQuestions, 36);
  assert.deepEqual(paper.questionTypes, ["fill_blank", "short_answer"]);
  assert.equal(paper.difficulty, "hard");
});

test("migrates the legacy configuration only into its matching mode", () => {
  const storage = new MemoryStorage();
  storage.setItem(
    "aiteachme.exam.createConfig.v1.course-2",
    JSON.stringify({
      examMode: "web_practice",
      numQuestions: 18,
      focusPrompt: "重点考查函数",
      paperLayoutMode: "auto",
    }),
  );

  const practice = loadCreateExamConfig("course-2", "web_practice", storage);
  const paper = loadCreateExamConfig("course-2", "paper_exam", storage);

  assert.equal(practice.numQuestions, 18);
  assert.equal(practice.userPrompt, "重点考查函数");
  assert.equal(paper.numQuestions, 24);
  assert.equal(paper.userPrompt, "");
});

test("builds the generation request from structured type and difficulty settings", () => {
  const request = toExamGenerateRequest({
    ...getDefaultCreateExamConfigForMode("paper_exam"),
    numQuestions: 30,
    questionTypes: ["single_choice", "short_answer"],
    difficulty: "hard",
    userPrompt: "重点考查综合应用。",
    paperLayoutMode: "gaokao_six_page",
  });

  assert.equal(request.exam_mode, "paper_exam");
  assert.equal(request.num_questions, 30);
  assert.deepEqual(request.question_types, ["single_choice", "short_answer"]);
  assert.equal(request.difficulty, "hard");
  assert.equal(request.paper_layout_mode, "gaokao_six_page");
  assert.match(request.user_prompt, /题型仅限：单选题、简答题/);
  assert.match(request.user_prompt, /整体难度以挑战为主/);
  assert.match(request.user_prompt, /重点考查综合应用/);
});

test("normalizes invalid create config values and omits paper layout for practice", () => {
  const normalized = normalizeCreateExamConfig(
    {
      examMode: "web_practice",
      numQuestions: 999,
      questionTypes: ["single_choice", "unsupported", "single_choice"],
      difficulty: "invalid",
      paperLayoutMode: "invalid",
    },
    "web_practice",
  );
  const request = toExamGenerateRequest(normalized);

  assert.equal(normalized.numQuestions, 80);
  assert.deepEqual(normalized.questionTypes, ["single_choice"]);
  assert.equal(normalized.difficulty, "auto");
  assert.equal(request.paper_layout_mode, undefined);
});

test("reads the latest saved mastery drill selection", () => {
  const storage = new MemoryStorage();
  saveMasteryDrillConfig(
    "course-3",
    { numQuestions: 16, questionTypes: ["true_false", "single_choice"] },
    storage,
  );
  assert.deepEqual(loadMasteryDrillConfig("course-3", storage), {
    numQuestions: 16,
    questionTypes: ["true_false", "single_choice"],
  });

  saveMasteryDrillConfig(
    "course-3",
    { numQuestions: 8, questionTypes: ["multiple_choice"] },
    storage,
  );
  assert.deepEqual(loadMasteryDrillConfig("course-3", storage), {
    numQuestions: 8,
    questionTypes: ["multiple_choice"],
  });
});

test("allows the last specified mastery question type to be deselected", () => {
  const availableTypes = ["single_choice", "multiple_choice", "true_false"];

  assert.deepEqual(
    toggleMasteryDrillQuestionType(["single_choice"], "single_choice", availableTypes),
    [],
  );
  assert.deepEqual(
    toggleMasteryDrillQuestionType([], "multiple_choice", availableTypes),
    ["multiple_choice"],
  );
});

test("treats training child routes as immersive detail pages", () => {
  assert.equal(isTrainingDetailPath("/courses/math/exams"), false);
  assert.equal(isTrainingDetailPath("/courses/math/exams/question-templates"), true);
  assert.equal(isTrainingDetailPath("/courses/math/exams/question-types"), true);
  assert.equal(isTrainingDetailPath("/courses/math/exams/mastery-drill"), true);
  assert.equal(isTrainingDetailPath("/courses/math/exams/42"), true);
  assert.equal(isTrainingDetailPath("/course/math/exams/question-types"), true);
  assert.equal(isTrainingDetailPath("/courses/math/profile"), false);
});
