import assert from "node:assert/strict";
import test from "node:test";
import { getAnswerPayload, getAnswerText, getAnswerValidationMessage, hasAnswerValue, updateAnswerField } from "../src/components/exams/questionTypes.ts";
import { buildExamPaperExportDetail } from "../src/components/exams/examPaperExport.ts";
import { normalizeCreateExamConfig, toExamGenerateRequest } from "../src/components/exams/examConfig.ts";

const fields = [{ key: "result", label: "结果", required: true, min_length: 2, max_length: 10 }, { key: "reason", label: "理由", required: false, min_length: 3, max_length: 20 }];
const item = { answer_schema: { fields } };

test("field keys survive JSON drafts and reordered presentation", () => {
  const answer = updateAnswerField(item, { result: "成立", reason: "证据充分" }, "result", "不成立");
  const restored = JSON.parse(JSON.stringify(answer));
  const reordered = { answer_schema: { fields: [...fields].reverse() } };
  assert.deepEqual(getAnswerPayload(reordered, restored), { reason: "证据充分", result: "不成立" });
  assert.equal(getAnswerText(reordered, restored), "理由：证据充分\n\n结果：不成立");
});

test("empty fields are unanswered, and legacy single field strings retain their content", () => {
  assert.equal(hasAnswerValue(item, { result: "", reason: "  " }), false);
  assert.equal(getAnswerText(item, { result: "", reason: "" }), "");
  const single = { answer_schema: { fields: [fields[0]] } };
  assert.equal(getAnswerText(single, { result: "成立" }), "成立");
  assert.deepEqual(getAnswerPayload(single, "成立"), { result: "成立" });
  assert.match(getAnswerValidationMessage(item, { result: "是", reason: "" }), /结果/);
  assert.match(getAnswerValidationMessage(item, { result: "a".repeat(11) }), /不能超过/);
});

test("valid field keys never read inherited JavaScript object properties as answers", () => {
  const constructorItem = { answer_schema: { fields: [{ ...fields[0], key: "constructor" }, fields[1]] } };
  assert.deepEqual(getAnswerPayload(constructorItem, {}), { constructor: "", reason: "" });
  assert.equal(hasAnswerValue(constructorItem, {}), false);
  assert.equal(getAnswerText(constructorItem, {}), "");
  assert.deepEqual(getAnswerPayload(constructorItem, { constructor: "成立" }), { constructor: "成立", reason: "" });
});

test("blank exports remove object answers and rubric evidence", () => {
  const blank = buildExamPaperExportDetail({ items: [{ ...item, user_answer: "secret", user_answer_payload: { result: "secret" }, grading_detail: { evidence: ["secret"] }, correct_answer: "secret", explanation: "secret" }] }, "blank");
  assert.equal(JSON.stringify(blank).includes("secret"), false);
});

test("two unknown package names mix with builtins without changing question enums", () => {
  const config = normalizeCreateExamConfig({ examMode: "web_practice", numQuestions: 6, questionTypes: ["single_choice"], customQuestionTypes: [{ registryId: 2, typeKey: "custom_unknown_one" }, { registryId: 3, typeKey: "custom_unknown_two" }] });
  const request = toExamGenerateRequest(config);
  assert.deepEqual(request.question_type_selections, [{ question_type: "single_choice" }, { registry_id: 2 }, { registry_id: 3 }]);
  assert.deepEqual(request.question_types, []);
  assert.deepEqual(request.question_type_registry_ids, []);
  assert.equal(request.user_prompt?.includes("题型仅限"), undefined);
});
