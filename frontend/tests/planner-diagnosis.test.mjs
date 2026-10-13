import assert from "node:assert/strict";
import test from "node:test";

import {
  formatPlannerDiagnosticAnswer,
  normalizePlannerDiagnosticAnswer,
  normalizePlannerDiagnosticAnswers,
} from "../src/components/build-plan/plannerDiagnosis.ts";

const choice = "基础｜保留 `s = 'a  b'` 的完整示例";
const note = "严格保留 `s = 'a  b'`。\n```python\nif s:\n    print(len(s))\n```";

test("诊断补充说明逐字编辑时保留空格、换行与缩进", () => {
  let current = { choice, note: "" };
  for (const character of note) {
    current = normalizePlannerDiagnosticAnswer({ ...current, note: current.note + character });
  }
  assert.equal(current.choice, choice);
  assert.equal(current.note, note);
  assert.equal(normalizePlannerDiagnosticAnswer({ note: "代码\n    " }).note, "代码\n    ");
});

test("结构化答案持久化往返和提交保留代码内容", () => {
  const answers = { "如何讲解 `s = 'a  b'`？": { choice, note } };
  const restored = normalizePlannerDiagnosticAnswers(JSON.parse(JSON.stringify(answers)));
  assert.deepEqual(restored, answers);
  const serialized = formatPlannerDiagnosticAnswer(restored[Object.keys(answers)[0]]);
  assert.equal(serialized, `选择：${choice}；补充：${note}`);
  assert.deepEqual(normalizePlannerDiagnosticAnswer(serialized), { choice, note });
});

test("旧字符串答案保留内部空白和多行补充", () => {
  assert.deepEqual(normalizePlannerDiagnosticAnswer(` ${choice} `), { choice });
  assert.deepEqual(normalizePlannerDiagnosticAnswer(`补充：${note}`), { choice: "", note });
});

test("含代码分号的选项在旧格式回读时不被截断", () => {
  const semicolonChoice = "演示｜`s = 'a  b'; print(len(s))`";
  assert.deepEqual(
    normalizePlannerDiagnosticAnswer(formatPlannerDiagnosticAnswer({ choice: semicolonChoice, note })),
    { choice: semicolonChoice, note },
  );
  assert.deepEqual(normalizePlannerDiagnosticAnswer(`选择：${semicolonChoice}`), { choice: semicolonChoice, note: "" });
});

test("仅提交时清理补充边界并忽略全空白答案", () => {
  assert.equal(formatPlannerDiagnosticAnswer({ choice: ` ${choice} `, note: ` \n${note}\n ` }), `选择：${choice}；补充：${note}`);
  assert.equal(formatPlannerDiagnosticAnswer({ note: " \n\t " }), "");
  assert.deepEqual(normalizePlannerDiagnosticAnswers({ "问题": { note: " \n\t " } }), {});
  assert.deepEqual(normalizePlannerDiagnosticAnswer(null), {});
});
