import assert from "node:assert/strict";
import test from "node:test";

import { resolveExamSubmissionTerminalState } from "../src/components/exams/examSubmissionFlow.ts";

test("finalizes a locally submitted exam when grading completes before an intermediate status is observed", () => {
  assert.equal(resolveExamSubmissionTerminalState("graded", "ready", true), "graded");
});

test("finalizes an observed background grading transition", () => {
  assert.equal(resolveExamSubmissionTerminalState("graded", "submitted", false), "graded");
  assert.equal(resolveExamSubmissionTerminalState("graded", "grading", false), "graded");
});

test("does not treat an already graded paper as a new submission completion", () => {
  assert.equal(resolveExamSubmissionTerminalState("graded", null, false), null);
  assert.equal(resolveExamSubmissionTerminalState("graded", "graded", false), null);
});

test("closes a local submission flow when background grading reaches terminal failure", () => {
  assert.equal(resolveExamSubmissionTerminalState("grading_failed", "ready", true), "grading_failed");
});

test("keeps waiting while grading is still active", () => {
  assert.equal(resolveExamSubmissionTerminalState("submitted", "ready", true), null);
  assert.equal(resolveExamSubmissionTerminalState("grading", "submitted", true), null);
});
