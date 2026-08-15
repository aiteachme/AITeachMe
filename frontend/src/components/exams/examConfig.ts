export type CreateExamMode = "web_practice" | "paper_exam";

export type PaperLayoutMode =
  | "auto"
  | "standard_two_page"
  | "gaokao_four_page"
  | "gaokao_six_page"
  | "gaokao_eight_page";

export type ExamDifficultyPreference = "auto" | "easy" | "medium" | "hard";
export type CreateExamQuestionType =
  | "single_choice"
  | "multiple_choice"
  | "true_false"
  | "fill_blank"
  | "short_answer";

export interface CreateExamConfig {
  examMode: CreateExamMode;
  numQuestions: number;
  questionTypes: CreateExamQuestionType[];
  difficulty: ExamDifficultyPreference;
  userPrompt: string;
  paperLayoutMode: PaperLayoutMode;
}

export interface ConfigStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export const CREATE_EXAM_QUESTION_COUNT_PRESETS = [
  { label: "轻量", value: 10 },
  { label: "标准", value: 24 },
  { label: "冲刺", value: 40 },
] as const;

export const CREATE_EXAM_QUESTION_TYPE_OPTIONS = [
  { value: "single_choice", label: "单选题" },
  { value: "multiple_choice", label: "多选题" },
  { value: "true_false", label: "判断题" },
  { value: "fill_blank", label: "填空题" },
  { value: "short_answer", label: "简答题" },
] as const;

export const CREATE_EXAM_DIFFICULTY_OPTIONS = [
  { value: "auto", label: "智能", description: "按知识点和训练模式自动搭配" },
  { value: "easy", label: "基础", description: "以理解和基础应用为主" },
  { value: "medium", label: "标准", description: "兼顾理解、应用与分析" },
  { value: "hard", label: "挑战", description: "增加综合分析和迁移要求" },
] as const;

const DEFAULT_CONFIG_BY_MODE: Record<CreateExamMode, CreateExamConfig> = {
  web_practice: {
    examMode: "web_practice",
    numQuestions: 10,
    questionTypes: [],
    difficulty: "auto",
    userPrompt: "",
    paperLayoutMode: "auto",
  },
  paper_exam: {
    examMode: "paper_exam",
    numQuestions: 24,
    questionTypes: [],
    difficulty: "auto",
    userPrompt: "",
    paperLayoutMode: "auto",
  },
};

export const DEFAULT_CREATE_EXAM_CONFIG = DEFAULT_CONFIG_BY_MODE.paper_exam;

const CREATE_EXAM_CONFIG_STORAGE_PREFIX = "aiteachme.exam.createConfig.v2";
const LEGACY_CREATE_EXAM_CONFIG_STORAGE_PREFIX = "aiteachme.exam.createConfig.v1";
const EXAM_MODES = new Set<CreateExamMode>(["web_practice", "paper_exam"]);
const PAPER_LAYOUT_MODES = new Set<PaperLayoutMode>([
  "auto",
  "standard_two_page",
  "gaokao_four_page",
  "gaokao_six_page",
  "gaokao_eight_page",
]);
const DIFFICULTIES = new Set<ExamDifficultyPreference>(["auto", "easy", "medium", "hard"]);
const QUESTION_TYPES = new Set(CREATE_EXAM_QUESTION_TYPE_OPTIONS.map((item) => item.value));

function getBrowserStorage(): ConfigStorage | null {
  return typeof window === "undefined" ? null : window.localStorage;
}

function getCreateExamConfigStorageKey(courseId: string, examMode: CreateExamMode) {
  return `${CREATE_EXAM_CONFIG_STORAGE_PREFIX}.${courseId}.${examMode}`;
}

function getLegacyCreateExamConfigStorageKey(courseId: string) {
  return `${LEGACY_CREATE_EXAM_CONFIG_STORAGE_PREFIX}.${courseId}`;
}

function cloneDefaultCreateExamConfig(examMode: CreateExamMode): CreateExamConfig {
  const config = DEFAULT_CONFIG_BY_MODE[examMode];
  return { ...config, questionTypes: [...config.questionTypes] };
}

function normalizeExamMode(value: unknown, fallback: CreateExamMode): CreateExamMode {
  const normalized = String(value ?? "") as CreateExamMode;
  return EXAM_MODES.has(normalized) ? normalized : fallback;
}

export function normalizeCreateExamConfig(
  value: (Partial<CreateExamConfig> & { focusPrompt?: string }) | null | undefined,
  requestedMode?: CreateExamMode,
): CreateExamConfig {
  const examMode = normalizeExamMode(requestedMode ?? value?.examMode, "paper_exam");
  const defaults = cloneDefaultCreateExamConfig(examMode);
  const numQuestions = Number(value?.numQuestions);
  const rawQuestionTypes = Array.isArray(value?.questionTypes) ? value.questionTypes : [];
  const questionTypes = Array.from(
    new Set(
      rawQuestionTypes
        .map((item) => String(item ?? "").trim())
        .filter((item): item is CreateExamQuestionType => QUESTION_TYPES.has(item as CreateExamQuestionType)),
    ),
  );
  const rawDifficulty = String(value?.difficulty ?? "") as ExamDifficultyPreference;
  const rawLayoutMode = String(value?.paperLayoutMode ?? "") as PaperLayoutMode;

  return {
    examMode,
    numQuestions: Math.min(
      80,
      Math.max(1, Number.isFinite(numQuestions) ? Math.round(numQuestions) : defaults.numQuestions),
    ),
    questionTypes,
    difficulty: DIFFICULTIES.has(rawDifficulty) ? rawDifficulty : defaults.difficulty,
    userPrompt:
      typeof value?.userPrompt === "string"
        ? value.userPrompt
        : typeof value?.focusPrompt === "string"
          ? value.focusPrompt
          : defaults.userPrompt,
    paperLayoutMode: PAPER_LAYOUT_MODES.has(rawLayoutMode) ? rawLayoutMode : defaults.paperLayoutMode,
  };
}

export function getDefaultCreateExamConfigForMode(examMode: CreateExamMode): CreateExamConfig {
  return cloneDefaultCreateExamConfig(examMode);
}

export function applyExamModeToCreateConfig(
  config: CreateExamConfig,
  examMode: CreateExamMode,
): CreateExamConfig {
  return config.examMode === examMode
    ? normalizeCreateExamConfig(config, examMode)
    : getDefaultCreateExamConfigForMode(examMode);
}

export function loadCreateExamConfig(
  courseId: string,
  examMode: CreateExamMode = "paper_exam",
  storage: ConfigStorage | null = getBrowserStorage(),
): CreateExamConfig {
  if (!storage) {
    return getDefaultCreateExamConfigForMode(examMode);
  }

  try {
    const currentRaw = storage.getItem(getCreateExamConfigStorageKey(courseId, examMode));
    if (currentRaw) {
      return normalizeCreateExamConfig(JSON.parse(currentRaw), examMode);
    }

    const legacyRaw = storage.getItem(getLegacyCreateExamConfigStorageKey(courseId));
    if (legacyRaw) {
      const legacyValue = JSON.parse(legacyRaw) as Partial<CreateExamConfig>;
      if (normalizeExamMode(legacyValue.examMode, "paper_exam") === examMode) {
        const migrated = normalizeCreateExamConfig(legacyValue, examMode);
        storage.setItem(getCreateExamConfigStorageKey(courseId, examMode), JSON.stringify(migrated));
        return migrated;
      }
    }
  } catch {
    return getDefaultCreateExamConfigForMode(examMode);
  }

  return getDefaultCreateExamConfigForMode(examMode);
}

export function saveCreateExamConfig(
  courseId: string,
  config: CreateExamConfig,
  storage: ConfigStorage | null = getBrowserStorage(),
) {
  if (!storage) {
    return;
  }
  const normalized = normalizeCreateExamConfig(config, config.examMode);
  storage.setItem(
    getCreateExamConfigStorageKey(courseId, normalized.examMode),
    JSON.stringify(normalized),
  );
}

function getQuestionTypeLabel(value: string): string {
  return CREATE_EXAM_QUESTION_TYPE_OPTIONS.find((item) => item.value === value)?.label ?? value;
}

function getDifficultyRequirement(value: ExamDifficultyPreference): string {
  const labels: Record<Exclude<ExamDifficultyPreference, "auto">, string> = {
    easy: "基础",
    medium: "标准",
    hard: "挑战",
  };
  return value === "auto" ? "" : `整体难度以${labels[value]}为主。`;
}

export function buildExamConfigUserPrompt(config: CreateExamConfig): string {
  const normalized = normalizeCreateExamConfig(config, config.examMode);
  const requirements = [
    normalized.questionTypes.length
      ? `题型仅限：${normalized.questionTypes.map(getQuestionTypeLabel).join("、")}。请在整套题目中合理分配。`
      : "",
    getDifficultyRequirement(normalized.difficulty),
    normalized.userPrompt.trim(),
  ].filter(Boolean);
  return requirements.join("\n");
}

export function toExamGenerateRequest(config: CreateExamConfig) {
  const normalized = normalizeCreateExamConfig(config, config.examMode);
  const userPrompt = buildExamConfigUserPrompt(normalized);

  return {
    exam_mode: normalized.examMode,
    user_prompt: userPrompt || undefined,
    num_questions: normalized.numQuestions,
    question_types: normalized.questionTypes,
    difficulty: normalized.difficulty,
    paper_layout_mode: normalized.examMode === "paper_exam" ? normalized.paperLayoutMode : undefined,
  };
}

export function formatCreateExamQuestionTypeSummary(config: CreateExamConfig): string {
  const normalized = normalizeCreateExamConfig(config, config.examMode);
  return normalized.questionTypes.length
    ? `${normalized.questionTypes.length} 种题型`
    : "智能题型";
}

export function formatCreateExamDifficultySummary(config: CreateExamConfig): string {
  const normalized = normalizeCreateExamConfig(config, config.examMode);
  return CREATE_EXAM_DIFFICULTY_OPTIONS.find((item) => item.value === normalized.difficulty)?.label ?? "智能";
}
