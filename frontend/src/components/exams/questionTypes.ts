export const SUPPORTED_QUESTION_TYPE_KEYS = [
  "single_choice",
  "multiple_choice",
  "true_false",
  "fill_blank",
  "short_answer",
] as const;

export type AnswerValue = string | Record<string, string>;
export type AnswerState = Record<number, AnswerValue>;

const supportedQuestionTypes = new Set<string>(SUPPORTED_QUESTION_TYPE_KEYS);

export function normalizeQuestionTypeKey(questionType?: string | null): string {
  const normalized = String(questionType ?? "").trim().toLowerCase();
  return normalized === "multi_choice" ? "multiple_choice" : normalized;
}

export function isSupportedQuestionType(questionType?: string | null): boolean {
  return supportedQuestionTypes.has(normalizeQuestionTypeKey(questionType));
}

export function isRenderableQuestionItem(item?: {
  question_type?: string | null;
  renderer_key?: string | null;
} | null): boolean {
  if (!item) return false;
  return isSupportedQuestionType(item.question_type) ||
    item.renderer_key === "long_text_v1" ||
    item.renderer_key === "structured_text_v1";
}

export function isCustomQuestionItem(item?: {
  question_type_version_id?: number | null;
  renderer_key?: string | null;
} | null): boolean {
  return Boolean(
    item?.question_type_version_id &&
    (item.renderer_key === "long_text_v1" || item.renderer_key === "structured_text_v1"),
  );
}

export function getCustomAnswerFieldKey(item?: {
  answer_schema?: unknown;
} | null): string {
  if (!item || typeof item.answer_schema !== "object" || item.answer_schema === null) {
    return "answer";
  }
  const fields = (item.answer_schema as { fields?: unknown }).fields;
  if (!Array.isArray(fields) || typeof fields[0] !== "object" || fields[0] === null) {
    return "answer";
  }
  const key = String((fields[0] as { key?: unknown }).key ?? "").trim();
  return key || "answer";
}

export type CustomAnswerFieldDefinition = {
  key: string;
  label: string;
  placeholder: string;
  minLength: number;
  maxLength: number;
  required: boolean;
  control: "short_text" | "long_text";
};

export function getCustomAnswerFields(item?: {
  answer_schema?: unknown;
} | null): CustomAnswerFieldDefinition[] {
  if (!item || typeof item.answer_schema !== "object" || item.answer_schema === null) return [];
  const fields = (item.answer_schema as { fields?: unknown }).fields;
  if (!Array.isArray(fields)) return [];
  return fields.flatMap((rawField) => {
    if (typeof rawField !== "object" || rawField === null) return [];
    const field = rawField as Record<string, unknown>;
    const key = String(field.key ?? "").trim();
    if (!key) return [];
    const rawMinLength = Number(field.min_length);
    const rawMaxLength = Number(field.max_length);
    const control = field.control === "short_text" ? "short_text" : "long_text";
    return [{
      key,
      label: String(field.label ?? "").trim() || "你的作答",
      placeholder: String(field.placeholder ?? "").trim() || "输入你的作答",
      minLength: Number.isFinite(rawMinLength) ? Math.max(0, Math.round(rawMinLength)) : 0,
      maxLength: Number.isFinite(rawMaxLength) ? Math.max(1, Math.round(rawMaxLength)) : 20_000,
      required: field.required !== false,
      control,
    }];
  });
}

export function getCustomAnswerField(item?: {
  answer_schema?: unknown;
} | null): CustomAnswerFieldDefinition | null {
  return getCustomAnswerFields(item)[0] ?? null;
}

export function getAnswerPayload(item: {
  answer_schema?: unknown;
} | null | undefined, value: AnswerValue | null | undefined): Record<string, string> {
  const fields = getCustomAnswerFields(item);
  if (!fields.length) return {};
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return Object.fromEntries(
      fields.map((field) => [
        field.key,
        Object.prototype.hasOwnProperty.call(value, field.key) ? String(value[field.key] ?? "") : "",
      ]),
    );
  }
  if (fields.length === 1) {
    return { [fields[0].key]: String(value ?? "") };
  }
  return Object.fromEntries(fields.map((field) => [field.key, ""]));
}

export function getAnswerText(
  item: { answer_schema?: unknown } | null | undefined,
  value: AnswerValue | null | undefined,
): string {
  if (typeof value === "string") return value;
  const fields = getCustomAnswerFields(item);
  if (!fields.length) return "";
  const payload = getAnswerPayload(item, value);
  if (!Object.values(payload).some((candidate) => candidate.trim())) return "";
  if (fields.length === 1) return payload[fields[0].key] ?? "";
  return fields
    .map((field) => `${field.label}：${payload[field.key] ?? ""}`)
    .join("\n\n");
}

export function hasAnswerValue(
  item: { answer_schema?: unknown } | null | undefined,
  value: AnswerValue | null | undefined,
): boolean {
  return Object.values(getAnswerPayload(item, value)).some((candidate) => candidate.trim().length > 0) ||
    (typeof value === "string" && value.trim().length > 0);
}

export function updateAnswerField(
  item: { answer_schema?: unknown } | null | undefined,
  value: AnswerValue | null | undefined,
  fieldKey: string,
  nextValue: string,
): AnswerValue {
  const fields = getCustomAnswerFields(item);
  if (!fields.length || fields.length === 1) return nextValue;
  return { ...getAnswerPayload(item, value), [fieldKey]: nextValue };
}

export function getAnswerValidationMessage(
  item: { answer_schema?: unknown } | null | undefined,
  value: AnswerValue | null | undefined,
): string | null {
  const fields = getCustomAnswerFields(item);
  if (!fields.length) return null;
  const payload = getAnswerPayload(item, value);
  for (const field of fields) {
    const fieldValue = payload[field.key] ?? "";
    if (fieldValue.length > field.maxLength) return `“${field.label}”不能超过 ${field.maxLength} 个字符。`;
    if (fieldValue.trim() && fieldValue.trim().length < field.minLength) {
      return `“${field.label}”至少需要 ${field.minLength} 个字符。`;
    }
  }
  return null;
}

export function requireSupportedQuestionType(questionType?: string | null): string {
  const normalized = normalizeQuestionTypeKey(questionType);
  if (!supportedQuestionTypes.has(normalized)) {
    throw new Error(`当前版本不支持题型「${normalized || "未指定"}」`);
  }
  return normalized;
}
