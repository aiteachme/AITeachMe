export interface QuestionTemplateKnowledgeRefView {
  key: string;
  knowledgeUnitId: string | null;
  name: string;
  nameMarkdown: string;
  typeKey: string | null;
  typeLabel: string | null;
  isTopic: boolean;
  weight: number | null;
  weightLabel: string | null;
  hasResolvedName: boolean;
}

interface QuestionTemplateHistorySummaryItem {
  is_correct?: boolean | null;
}

export interface QuestionTemplateHistorySummary {
  attemptCount: number;
  gradedCount: number;
  correctCount: number;
  wrongCount: number;
  pendingCount: number;
  accuracy: number | null;
}

const QUESTION_TEMPLATE_STATUS_LABELS: Record<string, string> = {
  active: "可用",
  draft: "草稿",
  inactive: "已停用",
  disabled: "已停用",
  archived: "已归档",
  deprecated: "已停用",
  failed: "生成失败",
  generation_failed: "生成失败",
};

const QUESTION_TEMPLATE_MODE_LABELS: Record<string, string> = {
  web_practice: "测验",
  paper_exam: "考卷",
  mastery_drill: "闯关",
  practice: "练习",
  diagnostic: "诊断测验",
  weakpoint_boost: "弱点强化",
  review: "复习",
  mock_final: "模拟考试",
};

const QUESTION_TEMPLATE_ERROR_CAUSE_LABELS: Record<string, string> = {
  knowledge_gap: "知识点掌握不足",
  concept_gap: "概念掌握不足",
  concept_confusion: "概念混淆",
  answer_not_precise: "答案不够准确",
  calculation_error: "计算错误",
  careless_mistake: "审题或书写疏漏",
  expression_issue: "表达不够规范",
  incomplete_understanding: "理解不完整",
  method_misapplication: "方法使用不当",
  prerequisite_gap: "前置知识存在缺口",
  reasoning_error: "推理过程有误",
  no_answer: "未作答",
  blank_answer: "未作答",
  unknown: "暂未归因",
};

const KNOWLEDGE_UNIT_TYPE_LABELS: Record<string, string> = {
  topic: "主题模块",
  concept: "概念术语",
  principle: "原理性质",
  formula_model: "公式模型",
  procedure: "方法步骤",
  skill: "解题技能",
  misconception: "易错辨析",
  application_case: "应用案例",
  resource: "学习资源",
};

function nonEmptyString(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function containsChinese(value: string) {
  return /[\u3400-\u9fff]/.test(value);
}

function normalizedCode(value: unknown) {
  return String(value ?? "").trim().toLowerCase();
}

function parseKnowledgeWeight(value: unknown) {
  const weight = Number(value);
  if (!Number.isFinite(weight)) return null;
  return Math.max(0, Math.min(weight, 1));
}

function getKnowledgeUnitName(ref: Record<string, unknown>) {
  const candidate =
    nonEmptyString(ref.knowledge_unit_name) ??
    nonEmptyString(ref.canonical_name) ??
    nonEmptyString(ref.unit_name) ??
    nonEmptyString(ref.name) ??
    nonEmptyString(ref.title);
  if (!candidate || /^KU[-_ ]?\d+$/i.test(candidate)) return null;
  return candidate;
}

function getKnowledgeUnitTypeLabel(ref: Record<string, unknown>) {
  const explicitLabel = nonEmptyString(ref.knowledge_unit_type_label) ?? nonEmptyString(ref.type_label);
  if (explicitLabel) return explicitLabel;
  const rawType = normalizedCode(ref.knowledge_unit_type ?? ref.unit_type);
  return KNOWLEDGE_UNIT_TYPE_LABELS[rawType] ?? null;
}

export function formatQuestionTemplateKnowledgeNameMarkdown(value: unknown) {
  const text = String(value ?? "").trim();
  if (!text || /(?:\$|\\\(|\\\[)/.test(text)) return text;

  const match = text.match(
    /^([\s\S]*?)([A-Za-z][A-Za-z0-9]*\s*(?:=|\\(?:neq|ne|frac|sqrt|le|ge))[A-Za-z0-9\s{}\\=<>+\-*/^(),.]*)$/,
  );
  if (!match) return text;
  const prefix = match[1].trimEnd();
  const expression = match[2].trim();
  if (!expression || /[\u3400-\u9fff]/.test(expression)) return text;
  return `${prefix}${prefix ? " " : ""}$${expression}$`;
}

function cleanKnowledgeSummaryFragment(value: string) {
  return value
    .replace(/^\s*#{1,6}\s+/, "")
    .replace(/!\[[^\]]*]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)]\([^)]*\)/g, "$1")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/~~([^~]+)~~/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

export function formatQuestionTemplateKnowledgeSummaryMarkdown(value: unknown, maxChars = 360) {
  const raw = String(value ?? "").replace(/\r\n?/g, "\n").trim();
  if (!raw) return "";

  const sectionBreak = raw.search(/(?:^|\s)#{2,6}\s+/);
  const primarySection = sectionBreak > 0 ? raw.slice(0, sectionBreak).trim() : raw;
  const fragments = primarySection.includes("|")
    ? primarySection
        .split("|")
        .map(cleanKnowledgeSummaryFragment)
        .filter((fragment) => fragment && !/^:?-{3,}:?$/.test(fragment))
    : primarySection
        .split("\n")
        .map(cleanKnowledgeSummaryFragment)
        .filter(Boolean);
  const summary = fragments.join(" · ").replace(/(?:\s*·\s*){2,}/g, " · ").trim();
  if (summary.length <= maxChars) return summary;

  const clipped = summary.slice(0, Math.max(1, maxChars - 1)).trimEnd();
  const safeBoundary = Math.max(clipped.lastIndexOf("。"), clipped.lastIndexOf("；"), clipped.lastIndexOf(" · "));
  const bounded = safeBoundary >= Math.floor(maxChars * 0.55) ? clipped.slice(0, safeBoundary + 1) : clipped;
  return `${bounded.trimEnd()}…`;
}

export function formatQuestionTemplateStatus(value: unknown) {
  const raw = String(value ?? "").trim();
  if (!raw) return "状态未标注";
  if (containsChinese(raw)) return raw;
  return QUESTION_TEMPLATE_STATUS_LABELS[raw.toLowerCase()] ?? "状态未标注";
}

export function formatQuestionTemplateVersion(value: unknown) {
  const version = Number(value);
  return Number.isFinite(version) && version > 0 ? `第 ${Math.trunc(version)} 版` : "版本未标注";
}

export function formatQuestionTemplateHistoryMode(value: unknown) {
  const raw = String(value ?? "").trim();
  if (!raw) return "其他训练";
  if (containsChinese(raw)) return raw;
  return QUESTION_TEMPLATE_MODE_LABELS[raw.toLowerCase()] ?? "其他训练";
}

export function formatQuestionTemplateErrorCause(value: unknown) {
  const raw = String(value ?? "").trim();
  if (!raw) return null;
  if (containsChinese(raw)) return raw;
  return QUESTION_TEMPLATE_ERROR_CAUSE_LABELS[raw.toLowerCase()] ?? "需要进一步分析";
}

export function buildQuestionTemplateKnowledgeRefs(
  refs: ReadonlyArray<Record<string, unknown>>,
): QuestionTemplateKnowledgeRefView[] {
  const normalized = refs.map((ref, index) => {
    const rawId = ref.knowledge_unit_id ?? ref.unit_id;
    const knowledgeUnitId = rawId == null || String(rawId).trim() === "" ? null : String(rawId);
    const name = getKnowledgeUnitName(ref);
    const typeKey = normalizedCode(ref.knowledge_unit_type ?? ref.unit_type) || null;
    const weight = parseKnowledgeWeight(ref.coverage_weight ?? ref.weight);
    return {
      index,
      knowledgeUnitId,
      name,
      typeKey,
      typeLabel: getKnowledgeUnitTypeLabel(ref),
      weight,
    };
  });

  normalized.sort((left, right) => {
    if ((left.weight ?? -1) !== (right.weight ?? -1)) return (right.weight ?? -1) - (left.weight ?? -1);
    return left.index - right.index;
  });

  return normalized.map((item) => {
    const fallbackName = item.knowledgeUnitId ? `知识点 #${item.knowledgeUnitId}` : "未命名知识点";
    const displayName = item.name ?? fallbackName;
    return {
      key: `${item.knowledgeUnitId ?? "unknown"}-${item.typeKey ?? "unknown"}-${item.index}`,
      knowledgeUnitId: item.knowledgeUnitId,
      name: displayName,
      nameMarkdown: formatQuestionTemplateKnowledgeNameMarkdown(displayName),
      typeKey: item.typeKey,
      typeLabel: item.typeLabel,
      isTopic: item.typeKey === "topic",
      weight: item.weight,
      weightLabel: item.weight == null ? null : `本题覆盖 ${Math.round(item.weight * 100)}%`,
      hasResolvedName: item.name != null,
    };
  });
}

export function summarizeQuestionTemplateHistory(
  items: ReadonlyArray<QuestionTemplateHistorySummaryItem>,
): QuestionTemplateHistorySummary {
  let correctCount = 0;
  let wrongCount = 0;
  let pendingCount = 0;

  for (const item of items) {
    if (item.is_correct === true) correctCount += 1;
    else if (item.is_correct === false) wrongCount += 1;
    else pendingCount += 1;
  }

  const gradedCount = correctCount + wrongCount;
  return {
    attemptCount: items.length,
    gradedCount,
    correctCount,
    wrongCount,
    pendingCount,
    accuracy: gradedCount > 0 ? Math.round((correctCount / gradedCount) * 100) : null,
  };
}

function normalizeComparableText(value: unknown) {
  return String(value ?? "")
    .replace(/[`*_~>#]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

export function shouldShowQuestionTemplateFeedback(feedback: unknown, explanation: unknown) {
  const normalizedFeedback = normalizeComparableText(feedback);
  if (!normalizedFeedback) return false;
  const normalizedExplanation = normalizeComparableText(explanation);
  return !normalizedExplanation || normalizedFeedback !== normalizedExplanation;
}
