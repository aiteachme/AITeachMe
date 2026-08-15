import assert from "node:assert/strict";
import test from "node:test";

import {
  buildQuestionBankSearchText,
  countQuestionBankReviewStatuses,
  filterAndSortQuestionBankEntries,
  matchesQuestionBankReviewStatus,
  toggleQuestionBankFilterValue,
} from "../src/components/exams/questionBankFilters.ts";

function createEntry(overrides = {}) {
  const item = {
    id: 1,
    question_type: "single_choice",
    difficulty: "easy",
    status: "active",
    stem: "一次函数基础题",
    options: [],
    answer: "A",
    explanation: "解析",
    knowledge_unit_refs: [{ knowledge_unit_id: 12, knowledge_unit_name: "一次函数" }],
    is_marked: false,
    has_wrong_attempt: false,
    created_at: "2026-08-10T10:00:00Z",
    updated_at: "2026-08-10T10:00:00Z",
    ...overrides,
  };
  const questionTypeLabel = item.question_type === "single_choice" ? "单选题" : "多选题";
  const difficultyLabel = item.difficulty === "hard" ? "难" : "易";
  return {
    item,
    questionTypeLabel,
    searchText: buildQuestionBankSearchText(item, questionTypeLabel, difficultyLabel),
  };
}

test("再次点击唯一选中的题型会取消选择", () => {
  assert.deepEqual(toggleQuestionBankFilterValue(["single_choice"], "single_choice"), []);
  assert.deepEqual(toggleQuestionBankFilterValue([], "multiple_choice"), ["multiple_choice"]);
});

test("中文难度和知识点名称可以直接搜索", () => {
  const entry = createEntry({
    id: 9,
    difficulty: "hard",
    knowledge_unit_refs: [{ knowledge_unit_id: 99, knowledge_unit_name: "函数建模" }],
  });

  assert.match(entry.searchText, /难/);
  assert.match(entry.searchText, /困难/);
  assert.match(entry.searchText, /函数建模/);
  assert.match(entry.searchText, /#9/);
});

test("同一维度取并集，不同维度和复习状态取交集", () => {
  const entries = [
    createEntry({ id: 1, question_type: "single_choice", difficulty: "easy" }),
    createEntry({ id: 2, question_type: "multiple_choice", difficulty: "hard", has_wrong_attempt: true }),
    createEntry({ id: 3, question_type: "single_choice", difficulty: "hard", is_marked: true, has_wrong_attempt: true }),
  ];
  const filtered = filterAndSortQuestionBankEntries(entries, {
    query: "",
    questionTypes: ["single_choice", "multiple_choice"],
    difficulties: ["hard"],
    reviewStatus: "wrong",
    sortMode: "newest",
  });

  assert.deepEqual(filtered.map(({ item }) => item.id), [3, 2]);
});

test("复习状态是互斥单选，组合状态要求同时满足", () => {
  assert.equal(matchesQuestionBankReviewStatus({ is_marked: true, has_wrong_attempt: false }, "marked"), true);
  assert.equal(matchesQuestionBankReviewStatus({ is_marked: true, has_wrong_attempt: false }, "wrong_marked"), false);
  assert.equal(matchesQuestionBankReviewStatus({ is_marked: true, has_wrong_attempt: true }, "wrong_marked"), true);
});

test("复习状态数量分别统计错题、标记题和两者交集", () => {
  const counts = countQuestionBankReviewStatuses([
    { is_marked: false, has_wrong_attempt: true },
    { is_marked: true, has_wrong_attempt: false },
    { is_marked: true, has_wrong_attempt: true },
    { is_marked: false, has_wrong_attempt: false },
  ]);

  assert.deepEqual(counts, {
    wrong: 2,
    marked: 2,
    wrong_marked: 1,
  });
});
