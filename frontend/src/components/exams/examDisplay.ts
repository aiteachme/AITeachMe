import type { ExamHistoryItem, ExamNodeLinkResponse, ExamPaperDetailResponse, ExamPaperItemResponse } from "../../api/generated/model";

export const EXAM_MODES = [
  { value: "web_practice", label: "专项练习", description: "适合快速刷题，聚焦薄弱知识点。" },
  { value: "paper_exam", label: "整卷测试", description: "模拟完整考试节奏，适合阶段检验。" },
] as const;

export const DIFFICULTIES = [
  { value: "easy", label: "基础" },
  { value: "medium", label: "标准" },
  { value: "hard", label: "挑战" },
] as const;

export function formatDateTime(value?: string | null) {
  if (!value) return "暂无记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatModeLabel(mode?: string | null) {
  return EXAM_MODES.find((item) => item.value === mode)?.label ?? "智能试卷";
}

export function formatDifficultyLabel(value: string) {
  return DIFFICULTIES.find((item) => item.value === value)?.label ?? value;
}

export function getOptionLabel(index: number) {
  return String.fromCharCode(65 + index);
}

export function splitMultiChoiceAnswer(value?: string | null) {
  return new Set(
    String(value ?? "")
      .replace(/[，、；;\s]+/g, ",")
      .split(",")
      .map((item) => item.trim().replace(/[.)、．]$/g, "").toUpperCase())
      .filter(Boolean),
  );
}

export function buildExamTitle(item: Pick<ExamHistoryItem, "exam_mode" | "created_at">) {
  return `${formatModeLabel(item.exam_mode)} · ${formatDateTime(item.created_at)}`;
}

function getOptionalString(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function getStringCandidate(source: Record<string, unknown>, keys: string[]) {
  return keys.map((key) => getOptionalString(source[key])).find(Boolean);
}

export function getExamPaperDisplayTitle(paper: ExamPaperDetailResponse) {
  const dynamicPaper = paper as ExamPaperDetailResponse & Record<string, unknown>;
  const directTitle = getStringCandidate(dynamicPaper, ["title", "name", "exam_title", "paper_title"]);
  if (directTitle) return directTitle;

  const context = (paper.selection_context ?? {}) as Record<string, unknown>;
  const contextTitle = getStringCandidate(context, ["title", "name", "exam_title", "paper_title"]);
  if (contextTitle) return contextTitle;

  return buildExamTitle(paper);
}

export function buildKnowledgeLabel(item: ExamPaperItemResponse) {
  return (
    item.knowledge_unit_links
      ?.map((link: ExamNodeLinkResponse) => link.knowledge_unit_name)
      .filter(Boolean)
      .join(" · ") || "未标注知识点"
  );
}

export function hasAnsweredQuestion(item: ExamPaperItemResponse, answers: Record<number, string>) {
  const value = answers[item.id] ?? "";
  return value.trim().length > 0;
}

export function getQuestionMaxScore(item: ExamPaperItemResponse) {
  const score = Number(item.score_max);
  return Number.isFinite(score) && score > 0 ? score : 0;
}

export function getExamTotalScore(paper: ExamPaperDetailResponse) {
  const score = Number(paper.total_score);
  if (Number.isFinite(score) && score > 0) return score;
  return (paper.items ?? []).reduce((total, item) => total + getQuestionMaxScore(item), 0);
}

export function getEstimatedExamMinutes(paper: ExamPaperDetailResponse) {
  const itemCount = Math.max(1, paper.total_items || paper.items?.length || 1);
  const minutesPerItem = paper.exam_mode === "paper_exam" ? 2.2 : 1.5;
  return Math.max(8, Math.ceil(itemCount * minutesPerItem));
}

export function getAnsweredCount(paper: ExamPaperDetailResponse, answers: Record<number, string>) {
  return (paper.items ?? []).filter((item) => hasAnsweredQuestion(item, answers)).length;
}
