export type QuestionBankReviewStatus = "all" | "wrong" | "marked" | "wrong_marked";
export type QuestionBankReviewCounts = Record<Exclude<QuestionBankReviewStatus, "all">, number>;

export type QuestionBankSortMode = "newest" | "oldest" | "difficulty" | "question_type";

export interface QuestionBankFilterState {
  query: string;
  questionTypes: readonly string[];
  difficulties: readonly string[];
  reviewStatus: QuestionBankReviewStatus;
  sortMode: QuestionBankSortMode;
}

export interface QuestionBankFilterableItem {
  id: number;
  question_type: string;
  difficulty: string;
  status?: string;
  stem?: string;
  options?: readonly string[] | null;
  answer?: string;
  explanation?: string;
  knowledge_unit_refs?: ReadonlyArray<Record<string, unknown>>;
  is_marked?: boolean;
  has_wrong_attempt?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface QuestionBankIndexedEntry<T extends QuestionBankFilterableItem = QuestionBankFilterableItem> {
  item: T;
  questionTypeLabel: string;
  searchText: string;
}

const DIFFICULTY_ORDER: Record<string, number> = {
  easy: 0,
  medium: 1,
  hard: 2,
};

const DIFFICULTY_SEARCH_ALIASES: Record<string, string> = {
  easy: "易 容易 简单 基础 easy",
  medium: "中 中等 标准 medium",
  hard: "难 困难 挑战 hard",
};

function normalizeText(value: unknown) {
  return String(value ?? "").trim().toLocaleLowerCase("zh-CN");
}

function getTimestamp(item: QuestionBankFilterableItem) {
  const value = item.updated_at || item.created_at;
  const timestamp = value ? Date.parse(value) : Number.NaN;
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function getKnowledgeRefSearchParts(refs: QuestionBankFilterableItem["knowledge_unit_refs"]) {
  if (!Array.isArray(refs)) return [];
  return refs.flatMap((ref) =>
    Object.values(ref).filter(
      (value): value is string | number => typeof value === "string" || typeof value === "number",
    ),
  );
}

export function buildQuestionBankSearchText(
  item: QuestionBankFilterableItem,
  questionTypeLabel: string,
  difficultyLabel: string,
  content = "",
) {
  const difficultyKey = normalizeText(item.difficulty);
  return [
    item.id,
    `#${item.id}`,
    item.question_type,
    questionTypeLabel,
    item.difficulty,
    difficultyLabel,
    DIFFICULTY_SEARCH_ALIASES[difficultyKey],
    item.status,
    item.stem,
    ...(item.options ?? []),
    item.answer,
    item.explanation,
    ...getKnowledgeRefSearchParts(item.knowledge_unit_refs),
    content,
  ]
    .filter((value) => value !== undefined && value !== null && String(value).trim())
    .join(" ")
    .toLocaleLowerCase("zh-CN");
}

export function toggleQuestionBankFilterValue(values: readonly string[], value: string) {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

export function matchesQuestionBankReviewStatus(
  item: Pick<QuestionBankFilterableItem, "is_marked" | "has_wrong_attempt">,
  reviewStatus: QuestionBankReviewStatus,
) {
  if (reviewStatus === "wrong") return item.has_wrong_attempt === true;
  if (reviewStatus === "marked") return item.is_marked === true;
  if (reviewStatus === "wrong_marked") {
    return item.has_wrong_attempt === true && item.is_marked === true;
  }
  return true;
}

export function countQuestionBankReviewStatuses(
  items: ReadonlyArray<Pick<QuestionBankFilterableItem, "is_marked" | "has_wrong_attempt">>,
): QuestionBankReviewCounts {
  const counts: QuestionBankReviewCounts = {
    wrong: 0,
    marked: 0,
    wrong_marked: 0,
  };
  for (const item of items) {
    const isWrong = item.has_wrong_attempt === true;
    const isMarked = item.is_marked === true;
    if (isWrong) counts.wrong += 1;
    if (isMarked) counts.marked += 1;
    if (isWrong && isMarked) counts.wrong_marked += 1;
  }
  return counts;
}

export function filterQuestionBankEntriesByKnowledgeUnit<T extends QuestionBankIndexedEntry>(
  entries: readonly T[],
  knowledgeUnitId: number | null | undefined,
): T[] {
  if (!knowledgeUnitId || knowledgeUnitId <= 0) return [...entries];
  return entries.filter(({ item }) =>
    (item.knowledge_unit_refs ?? []).some((ref) => {
      const value = Number(ref.knowledge_unit_id ?? ref.unit_id ?? 0);
      return Number.isFinite(value) && value === knowledgeUnitId;
    }),
  );
}

export function filterAndSortQuestionBankEntries<T extends QuestionBankIndexedEntry>(
  entries: readonly T[],
  filters: QuestionBankFilterState,
) {
  const normalizedQuery = normalizeText(filters.query);
  const questionTypes = new Set(filters.questionTypes);
  const difficulties = new Set(filters.difficulties.map(normalizeText));
  const filtered = entries.filter(({ item, searchText }) => {
    if (questionTypes.size > 0 && !questionTypes.has(item.question_type)) return false;
    if (difficulties.size > 0 && !difficulties.has(normalizeText(item.difficulty))) return false;
    if (!matchesQuestionBankReviewStatus(item, filters.reviewStatus)) return false;
    return !normalizedQuery || searchText.includes(normalizedQuery);
  });

  return [...filtered].sort((left, right) => {
    if (filters.sortMode === "oldest") {
      return getTimestamp(left.item) - getTimestamp(right.item) || left.item.id - right.item.id;
    }
    if (filters.sortMode === "difficulty") {
      const leftRank = DIFFICULTY_ORDER[normalizeText(left.item.difficulty)] ?? 99;
      const rightRank = DIFFICULTY_ORDER[normalizeText(right.item.difficulty)] ?? 99;
      return leftRank - rightRank || right.item.id - left.item.id;
    }
    if (filters.sortMode === "question_type") {
      return (
        left.questionTypeLabel.localeCompare(right.questionTypeLabel, "zh-CN") ||
        right.item.id - left.item.id
      );
    }
    return getTimestamp(right.item) - getTimestamp(left.item) || right.item.id - left.item.id;
  });
}
