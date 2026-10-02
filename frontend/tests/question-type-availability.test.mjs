import assert from "node:assert/strict";
import test from "node:test";
import {
  countQuestionTypesForMode,
  getQuestionTypeStatusCategory,
  getQuestionTypeStatusDescription,
  getQuestionTypeStatusLabel,
  isCustomQuestionTypeAvailable,
  isCustomQuestionTypeReady,
} from "../src/components/exams/questionTypeAvailability.ts";

const modes = ["web_practice", "paper_exam", "mastery_drill"];
const custom = {
  scope: "course", source: "upload", is_system: false,
  status: "active", is_active: true, runtime_ready: true,
  current_version_id: 1, modes,
};
const builtins = Array.from({ length: 5 }, () => ({
  ...custom, scope: "global", source: "system", is_system: true, current_version_id: null,
}));

test("seven registered types include six selectable types when one installed package is inactive", () => {
  const inactive = { ...custom, status: "inactive", is_active: false };
  const catalog = [...builtins, inactive, custom];
  assert.equal(catalog.length, 7);
  assert.equal(isCustomQuestionTypeReady(inactive), true);
  assert.equal(isCustomQuestionTypeAvailable(inactive), false);
  assert.equal(getQuestionTypeStatusCategory(inactive), "inactive");
  assert.equal(getQuestionTypeStatusLabel(inactive), "已停用");
  assert.match(getQuestionTypeStatusDescription(inactive), /启用题型/);
  for (const mode of modes) assert.equal(countQuestionTypesForMode(catalog, mode), 6);
});

test("enabling an installed legacy or current package makes it available in every declared mode", () => {
  for (const version of ["1.0.0", "2.0.0"]) {
    const enabled = { ...custom, current_version: version };
    assert.equal(getQuestionTypeStatusCategory(enabled), "available");
    assert.equal(isCustomQuestionTypeAvailable(enabled), true);
    assert.match(getQuestionTypeStatusDescription(enabled), /已启用/);
    for (const mode of modes) assert.equal(countQuestionTypesForMode([...builtins, custom, enabled], mode), 7);
  }
});

test("archiving hides the type and restoring it leaves it inactive until explicitly enabled", () => {
  const archived = { ...custom, status: "archived", is_active: false };
  const restored = { ...archived, status: "inactive" };
  assert.equal(getQuestionTypeStatusCategory(archived), "archived");
  assert.equal(getQuestionTypeStatusCategory(restored), "inactive");
  for (const item of [archived, restored]) {
    assert.equal(isCustomQuestionTypeAvailable(item), false);
    for (const mode of modes) assert.equal(countQuestionTypesForMode([...builtins, item], mode), 5);
  }
});

test("unready packages cannot be enabled and retain the backend explanation", () => {
  const pending = { ...custom, runtime_ready: false, runtime_message: "当前版本尚不支持此作答方式。" };
  assert.equal(isCustomQuestionTypeReady(pending), false);
  assert.equal(isCustomQuestionTypeAvailable(pending), false);
  assert.equal(getQuestionTypeStatusCategory(pending), "pending");
  assert.equal(getQuestionTypeStatusDescription(pending), pending.runtime_message);
});

test("incomplete or inconsistent catalog records never appear as selectable custom types", () => {
  for (const changes of [
    { current_version_id: null }, { runtime_ready: undefined },
    { source: "scan" }, { scope: "global" },
    { status: "inactive", is_active: true }, { status: "active", is_active: false },
  ]) {
    const item = { ...custom, ...changes };
    assert.notEqual(getQuestionTypeStatusCategory(item), "available");
    assert.equal(isCustomQuestionTypeAvailable(item), false);
    for (const mode of modes) assert.equal(countQuestionTypesForMode([...builtins, item], mode), 5);
  }
});

test("mode counts respect package declarations independently of the catalog total", () => {
  const practiceOnly = { ...custom, modes: ["web_practice"] };
  const noModes = { ...custom, modes: undefined };
  assert.equal(countQuestionTypesForMode([...builtins, practiceOnly, noModes], "web_practice"), 6);
  assert.equal(countQuestionTypesForMode([...builtins, practiceOnly, noModes], "paper_exam"), 5);
  assert.equal(countQuestionTypesForMode([...builtins, practiceOnly, noModes], "mastery_drill"), 5);
});

test("legacy course definitions of a built-in type keep their supported runtime without adding duplicate choices", () => {
  const legacy = {
    ...custom, type_key: "single_choice", source: "manual", current_version_id: null,
  };
  assert.equal(getQuestionTypeStatusCategory(legacy), "available");
  assert.equal(isCustomQuestionTypeAvailable(legacy), false);
  for (const mode of modes) assert.equal(countQuestionTypesForMode([...builtins, legacy], mode), 5);
  assert.equal(getQuestionTypeStatusCategory({ ...legacy, status: "inactive", is_active: false }), "inactive");
});
