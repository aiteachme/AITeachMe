import assert from "node:assert/strict";
import test from "node:test";
import {
  filterMasteryDrillCatalogTemplates,
  filterMasteryDrillSelectedTemplates,
} from "../src/components/exams/masteryDrillSelection.ts";
import { filterAvailableCustomTypeSelections } from "../src/components/exams/questionTypeSelection.ts";

const registry = {
  id: 6, type_key: "custom_debate", scope: "course", source: "upload",
  is_system: false, is_active: true, status: "active", runtime_ready: true,
  current_version_id: 12, modes: ["mastery_drill", "web_practice"],
};
const builtin = { id: 1, question_type: "single_choice" };
const current = { id: 2, question_type: "custom_debate", question_type_registry_id: 6, question_type_version_id: 12 };
const old = { ...current, id: 3, question_type_version_id: 11 };

test("upgrading and switching back changes reusable bank counts without rewriting historic templates", () => {
  const bank = [builtin, current, old];
  assert.deepEqual(filterMasteryDrillCatalogTemplates(bank, [registry]), [builtin, current]);
  assert.deepEqual(filterMasteryDrillCatalogTemplates(bank, [{ ...registry, current_version_id: 11 }]), [builtin, old]);
  assert.equal(bank.length, 3);
  assert.equal(current.question_type_version_id, 12);
});

test("inactive, archived, missing, unready and mode-incompatible packages add no reusable custom questions", () => {
  for (const changes of [
    { is_active: false, status: "inactive" }, { is_active: false, status: "archived" },
    { runtime_ready: false }, { modes: ["paper_exam"] }, { current_version_id: null },
  ]) {
    assert.deepEqual(filterMasteryDrillCatalogTemplates([builtin, current], [{ ...registry, ...changes }]), [builtin]);
  }
  assert.deepEqual(filterMasteryDrillCatalogTemplates([builtin, current], []), [builtin]);
});

test("matching a name or version alone cannot reuse a different registry's question", () => {
  const foreign = { ...current, question_type_registry_id: 7 };
  const renamed = { ...current, question_type: "custom_other" };
  assert.deepEqual(filterMasteryDrillCatalogTemplates([foreign, renamed], [registry]), []);
});

test("smart mix only counts built-in questions even when uploaded types have bank entries", () => {
  assert.deepEqual(filterMasteryDrillSelectedTemplates([builtin, current, old], []), [builtin]);
});

test("an explicit selection keeps its prepared frozen version without opting into another custom type", () => {
  const other = { ...current, id: 4, question_type_registry_id: 7, question_type: "custom_other" };
  const selected = [{ registryId: 6, typeKey: "custom_debate" }];
  assert.deepEqual(filterMasteryDrillSelectedTemplates([builtin, old, other], selected), [builtin, old]);
});

test("removing unavailable selections preserves supported choices and allows a replacement to be saved", () => {
  const inactive = { registryId: 6, typeKey: "custom_debate" };
  const supported = { registryId: 7, typeKey: "custom_other" };
  const original = [inactive, supported];
  assert.deepEqual(filterAvailableCustomTypeSelections(original, [7]), [supported]);
  assert.deepEqual(filterAvailableCustomTypeSelections([inactive], [7]), []);
  assert.deepEqual(original, [inactive, supported]);
});
