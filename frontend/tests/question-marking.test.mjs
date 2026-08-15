import assert from "node:assert/strict";
import test from "node:test";

import {
  addPendingQuestionTemplateId,
  patchQuestionTemplateMarkInPaper,
  patchQuestionTemplateMarkInPrepareResult,
  patchQuestionTemplateMarkInTemplates,
  removePendingQuestionTemplateId,
  restoreQuestionTemplateMarkInPaper,
  restoreQuestionTemplateMarkInPrepareResult,
  restoreQuestionTemplateMarkInTemplates,
} from "../src/components/exams/questionMarking.ts";

test("serializes mark requests for the same question while allowing different questions", () => {
  const empty = new Set();
  const first = addPendingQuestionTemplateId(empty, 101);

  assert.ok(first);
  assert.equal(addPendingQuestionTemplateId(first, 101), null);
  const concurrentOtherQuestion = addPendingQuestionTemplateId(first, 102);
  assert.ok(concurrentOtherQuestion);
  assert.deepEqual([...concurrentOtherQuestion].sort(), [101, 102]);

  const finished = removePendingQuestionTemplateId(concurrentOtherQuestion, 101);
  assert.ok(addPendingQuestionTemplateId(finished, 101));
});

function createPaper() {
  return {
    id: 1,
    items: [
      { id: 11, question_template_id: 101, is_marked: false },
      { id: 12, question_template_id: 102, is_marked: false },
    ],
  };
}

test("patches the matching question without mutating the paper", () => {
  const paper = createPaper();
  const marked = patchQuestionTemplateMarkInPaper(paper, 101, true);

  assert.notStrictEqual(marked, paper);
  assert.notStrictEqual(marked.items, paper.items);
  assert.equal(marked.items[0].is_marked, true);
  assert.equal(marked.items[1], paper.items[1]);
  assert.equal(paper.items[0].is_marked, false);
});

test("supports unmarking and skips redundant updates", () => {
  const paper = createPaper();
  const marked = patchQuestionTemplateMarkInPaper(paper, 101, true);
  const unchanged = patchQuestionTemplateMarkInPaper(marked, 101, true);
  const unmarked = patchQuestionTemplateMarkInPaper(marked, 101, false);

  assert.equal(unchanged, marked);
  assert.equal(unmarked.items[0].is_marked, false);
});

test("keeps the original paper when the template is absent", () => {
  const paper = createPaper();

  assert.equal(patchQuestionTemplateMarkInPaper(paper, 999, true), paper);
});

test("patches the mastery drill prepare cache without mutating it", () => {
  const prepareResult = {
    requested_count: 2,
    available_count: 2,
    generated_count: 0,
    templates: [
      { id: 101, is_marked: false },
      { id: 102, is_marked: true },
    ],
  };

  const marked = patchQuestionTemplateMarkInPrepareResult(prepareResult, 101, true);

  assert.notStrictEqual(marked, prepareResult);
  assert.notStrictEqual(marked.templates, prepareResult.templates);
  assert.equal(marked.templates[0].is_marked, true);
  assert.equal(marked.templates[1], prepareResult.templates[1]);
  assert.equal(prepareResult.templates[0].is_marked, false);
});

test("keeps the mastery drill prepare cache when no patch is needed", () => {
  const prepareResult = {
    requested_count: 1,
    available_count: 1,
    generated_count: 0,
    templates: [{ id: 101, is_marked: true }],
  };

  assert.equal(
    patchQuestionTemplateMarkInPrepareResult(prepareResult, 101, true),
    prepareResult,
  );
  assert.equal(
    patchQuestionTemplateMarkInPrepareResult(prepareResult, 999, false),
    prepareResult,
  );
});

test("a failed mark restores only its question and preserves another successful update", () => {
  const templates = [
    { id: 101, is_marked: false },
    { id: 102, is_marked: false },
  ];
  const firstOptimistic = patchQuestionTemplateMarkInTemplates(templates, 101, true);
  const secondSucceeded = patchQuestionTemplateMarkInTemplates(firstOptimistic, 102, true);
  const restored = restoreQuestionTemplateMarkInTemplates(
    secondSucceeded,
    101,
    true,
    false,
  );

  assert.equal(restored[0].is_marked, false);
  assert.equal(restored[1].is_marked, true);
});

test("does not roll back a question whose optimistic value has since changed", () => {
  const templates = [{ id: 101, is_marked: false }];
  const firstOptimistic = patchQuestionTemplateMarkInTemplates(templates, 101, true);
  const newerUpdate = patchQuestionTemplateMarkInTemplates(firstOptimistic, 101, false);

  assert.equal(
    restoreQuestionTemplateMarkInTemplates(newerUpdate, 101, true, false),
    newerUpdate,
  );
});

test("restores only the failed question in mastery prepare and paper caches", () => {
  const prepareResult = {
    templates: [
      { id: 101, is_marked: true },
      { id: 102, is_marked: true },
    ],
  };
  const paper = {
    id: 1,
    items: [
      { id: 11, question_template_id: 101, is_marked: true },
      { id: 12, question_template_id: 102, is_marked: true },
    ],
  };

  const restoredPrepare = restoreQuestionTemplateMarkInPrepareResult(
    prepareResult,
    101,
    true,
    false,
  );
  const restoredPaper = restoreQuestionTemplateMarkInPaper(
    paper,
    101,
    true,
    false,
  );

  assert.equal(restoredPrepare.templates[0].is_marked, false);
  assert.equal(restoredPrepare.templates[1].is_marked, true);
  assert.equal(restoredPaper.items[0].is_marked, false);
  assert.equal(restoredPaper.items[1].is_marked, true);
});
