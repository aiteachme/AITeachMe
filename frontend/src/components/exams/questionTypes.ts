export const SUPPORTED_QUESTION_TYPE_KEYS = [
  "single_choice",
  "multiple_choice",
  "true_false",
  "fill_blank",
  "short_answer",
] as const;

const supportedQuestionTypes = new Set<string>(SUPPORTED_QUESTION_TYPE_KEYS);

export function normalizeQuestionTypeKey(questionType?: string | null): string {
  const normalized = String(questionType ?? "").trim().toLowerCase();
  return normalized === "multi_choice" ? "multiple_choice" : normalized;
}

export function isSupportedQuestionType(questionType?: string | null): boolean {
  return supportedQuestionTypes.has(normalizeQuestionTypeKey(questionType));
}

export function requireSupportedQuestionType(questionType?: string | null): string {
  const normalized = normalizeQuestionTypeKey(questionType);
  if (!supportedQuestionTypes.has(normalized)) {
    throw new Error(`当前版本不支持题型「${normalized || "未指定"}」`);
  }
  return normalized;
}
