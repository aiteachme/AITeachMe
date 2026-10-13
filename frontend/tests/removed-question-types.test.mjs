import assert from "node:assert/strict";
import test from "node:test";
import { normalizeCreateExamConfig, toExamGenerateRequest } from "../src/components/exams/examConfig.ts";
import { normalizeMasteryDrillConfig } from "../src/components/exams/masteryDrillConfig.ts";

test("old saved custom selections cannot reappear in generation requests", () => {
  const config = normalizeCreateExamConfig({ examMode: "web_practice", numQuestions: 6, questionTypes: ["single_choice", "custom_unknown_one"], customQuestionTypes: [{ registryId: 2, typeKey: "custom_unknown_one" }] });
  const request = toExamGenerateRequest(config);
  assert.deepEqual(request.question_types, ["single_choice"]);
  assert.equal("question_type_selections" in request, false);
  assert.equal("question_type_registry_ids" in request, false);
  assert.equal(JSON.stringify(request).includes("custom_"), false);
});

test("old mastery selections retain builtins and drop retired package keys", () => {
  const config = normalizeMasteryDrillConfig({ numQuestions: 5, questionTypes: ["custom_test", "single_choice", "multi_choice", "registry:7"] });
  assert.deepEqual(config.questionTypes, ["single_choice", "multiple_choice"]);
});
