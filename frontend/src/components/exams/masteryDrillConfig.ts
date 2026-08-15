import type { ConfigStorage } from "./examConfig.ts";

export interface MasteryDrillConfig {
  numQuestions: number;
  questionTypes: string[];
}

export const DEFAULT_MASTERY_DRILL_CONFIG: MasteryDrillConfig = {
  numQuestions: 10,
  questionTypes: [],
};

export const MASTERY_DRILL_QUESTION_COUNT_PRESETS = [
  { label: "轻量", value: 10 },
  { label: "标准", value: 20 },
  { label: "强化", value: 30 },
] as const;

const MASTERY_DRILL_CONFIG_STORAGE_PREFIX = "aiteachme.exam.masteryDrillConfig.v1";

function normalizeQuestionTypes(values: readonly unknown[]): string[] {
  return Array.from(
    new Set(
      values
        .map((item) => String(item ?? "").trim())
        .filter(Boolean),
    ),
  );
}

function getBrowserStorage(): ConfigStorage | null {
  return typeof window === "undefined" ? null : window.localStorage;
}

function getMasteryDrillConfigStorageKey(courseId: string) {
  return `${MASTERY_DRILL_CONFIG_STORAGE_PREFIX}.${courseId}`;
}

export function normalizeMasteryDrillConfig(
  value: Partial<MasteryDrillConfig> | null | undefined,
): MasteryDrillConfig {
  const numQuestions = Number(value?.numQuestions);
  const questionTypes = Array.isArray(value?.questionTypes)
    ? normalizeQuestionTypes(value.questionTypes)
    : DEFAULT_MASTERY_DRILL_CONFIG.questionTypes;

  return {
    numQuestions: Math.min(
      80,
      Math.max(
        1,
        Number.isFinite(numQuestions) ? Math.round(numQuestions) : DEFAULT_MASTERY_DRILL_CONFIG.numQuestions,
      ),
    ),
    questionTypes,
  };
}

export function toggleMasteryDrillQuestionType(
  selectedQuestionTypes: readonly string[],
  questionType: string,
  availableQuestionTypes: readonly string[],
): string[] {
  const availableTypeSet = new Set(normalizeQuestionTypes(availableQuestionTypes));
  const normalizedSelection = normalizeQuestionTypes(selectedQuestionTypes)
    .filter((item) => availableTypeSet.has(item));
  const normalizedQuestionType = String(questionType ?? "").trim();
  if (!availableTypeSet.has(normalizedQuestionType)) {
    return normalizedSelection;
  }
  return normalizedSelection.includes(normalizedQuestionType)
    ? normalizedSelection.filter((item) => item !== normalizedQuestionType)
    : [...normalizedSelection, normalizedQuestionType];
}

export function loadMasteryDrillConfig(
  courseId: string,
  storage: ConfigStorage | null = getBrowserStorage(),
): MasteryDrillConfig {
  if (!storage) {
    return { ...DEFAULT_MASTERY_DRILL_CONFIG, questionTypes: [] };
  }

  try {
    const raw = storage.getItem(getMasteryDrillConfigStorageKey(courseId));
    return normalizeMasteryDrillConfig(raw ? JSON.parse(raw) : null);
  } catch {
    return { ...DEFAULT_MASTERY_DRILL_CONFIG, questionTypes: [] };
  }
}

export function saveMasteryDrillConfig(
  courseId: string,
  config: MasteryDrillConfig,
  storage: ConfigStorage | null = getBrowserStorage(),
) {
  if (!storage) {
    return;
  }
  storage.setItem(
    getMasteryDrillConfigStorageKey(courseId),
    JSON.stringify(normalizeMasteryDrillConfig(config)),
  );
}

export function getMasteryDrillConfigSelectionKey(config: MasteryDrillConfig) {
  const normalized = normalizeMasteryDrillConfig(config);
  return `${normalized.numQuestions}:${[...normalized.questionTypes].sort().join(",")}`;
}

export function formatMasteryDrillDurationRange(numQuestions: number) {
  const normalizedCount = normalizeMasteryDrillConfig({ numQuestions }).numQuestions;
  const minMinutes = Math.max(5, Math.round(normalizedCount));
  const maxMinutes = Math.max(minMinutes + 5, Math.round(normalizedCount * 2));
  return `预计${minMinutes}-${maxMinutes}分钟`;
}
