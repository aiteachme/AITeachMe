import assert from "node:assert/strict";
import test from "node:test";

import { getMasteryDrillQuestionNumber } from "../src/components/exams/masteryDrillProgress.ts";
import {
  interleaveMasteryDrillCandidateIdsByType,
  loadLastMasteryDrillTemplateIds,
  saveLastMasteryDrillTemplateIds,
  selectMasteryDrillQuestionTypes,
  selectNextMasteryDrillCandidateIds,
} from "../src/components/exams/masteryDrillSelection.ts";

function createMemoryStorage() {
  const entries = new Map();
  return {
    getItem(key) {
      return entries.get(key) ?? null;
    },
    setItem(key, value) {
      entries.set(key, String(value));
    },
  };
}

test("numbers the current drill question from completed progress", () => {
  assert.equal(getMasteryDrillQuestionNumber(0, 10), 1);
  assert.equal(getMasteryDrillQuestionNumber(2, 10), 3);
  assert.equal(getMasteryDrillQuestionNumber(9, 10), 10);
});

test("keeps the question number stable while a failed question is requeued", () => {
  const completedBeforeFailure = 2;

  assert.equal(getMasteryDrillQuestionNumber(completedBeforeFailure, 10), 3);
  assert.equal(getMasteryDrillQuestionNumber(completedBeforeFailure, 10), 3);
});

test("clamps completed progress to the available question range", () => {
  assert.equal(getMasteryDrillQuestionNumber(10, 10), 10);
  assert.equal(getMasteryDrillQuestionNumber(99, 10), 10);
  assert.equal(getMasteryDrillQuestionNumber(-1, 10), 1);
  assert.equal(getMasteryDrillQuestionNumber(0, 0), 0);
});

test("draws a completely fresh set when enough unseen questions exist", () => {
  assert.deepEqual(
    selectNextMasteryDrillCandidateIds([1, 2, 3, 4, 5, 6], [1, 2, 3], 3),
    [4, 5, 6],
  );
});

test("minimizes overlap when the question bank cannot provide a fully fresh set", () => {
  assert.deepEqual(
    selectNextMasteryDrillCandidateIds([1, 4, 2, 5, 3], [1, 2, 3], 4),
    [4, 5, 1, 2],
  );
});

test("changes order when every available question must be reused", () => {
  assert.deepEqual(
    selectNextMasteryDrillCandidateIds([1, 2, 3], [1, 2, 3], 3),
    [2, 3, 1],
  );
  assert.deepEqual(
    selectNextMasteryDrillCandidateIds([1, 2, 3], [1, 2, 3, 4], 3),
    [2, 3, 1],
  );
  assert.deepEqual(selectNextMasteryDrillCandidateIds([1], [1], 1), [1]);
});

test("remembers only the last selected question ids in session-compatible storage", () => {
  const storage = createMemoryStorage();
  saveLastMasteryDrillTemplateIds("course-a", [3, 2, 2, -1, 1], storage);

  assert.deepEqual(loadLastMasteryDrillTemplateIds("course-a", storage), [3, 2, 1]);
  assert.deepEqual(loadLastMasteryDrillTemplateIds("course-b", storage), []);
});

test("smart mastery mode chooses between two and all available question types", () => {
  const uniqueTypes = [
    "single_choice",
    "multiple_choice",
    "true_false",
    "fill_blank",
    "short_answer",
  ];
  const availableTypes = uniqueTypes.flatMap((questionType) => Array(10).fill(questionType));
  const observedCounts = new Set();

  for (let seed = 1; seed <= 64; seed += 1) {
    const selectedTypes = selectMasteryDrillQuestionTypes(availableTypes, [], seed, 10);
    observedCounts.add(selectedTypes.length);
    assert.equal(new Set(selectedTypes).size, selectedTypes.length);
    assert.ok(selectedTypes.every((questionType) => uniqueTypes.includes(questionType)));
    assert.ok(selectedTypes.length >= 2 && selectedTypes.length <= uniqueTypes.length);
  }

  assert.ok(observedCounts.size > 1);
});

test("specified mastery mode uses exactly the selected available question types", () => {
  assert.deepEqual(
    selectMasteryDrillQuestionTypes(
      ["single_choice", "multiple_choice", "true_false"],
      ["true_false", "unsupported", "single_choice"],
      42,
      10,
    ),
    ["true_false", "single_choice"],
  );
});

test("smart mastery mode respects unavoidable one-question or one-type limits", () => {
  assert.equal(
    selectMasteryDrillQuestionTypes(["single_choice", "true_false"], [], 7, 1).length,
    1,
  );
  assert.deepEqual(
    selectMasteryDrillQuestionTypes(["single_choice", "single_choice"], [], 7, 10),
    ["single_choice"],
  );
});

test("interleaves mastery candidates so selected types appear across the round", () => {
  assert.deepEqual(
    interleaveMasteryDrillCandidateIdsByType([
      { id: 1, questionType: "single_choice" },
      { id: 2, questionType: "single_choice" },
      { id: 3, questionType: "true_false" },
      { id: 4, questionType: "short_answer" },
      { id: 5, questionType: "true_false" },
    ]),
    [1, 3, 4, 2, 5],
  );
});
