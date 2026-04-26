import type {
  ChatSelectionContext,
  ExamHistoryItem,
  ExamNodeLinkResponse,
  ExamPaperDetailResponse,
  ExamPaperItemResponse,
} from "../../api/generated/model";
import { buildExamQuestionAnchorId } from "../interaction/types";

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

export function normalizeQuestionContextText(value?: string | null): string {
  return String(value ?? "")
    .replace(/!\[[^\]]*]\([^)]+\)/g, "")
    .replace(/\[([^\]]+)]\([^)]+\)/g, "$1")
    .replace(/[`*_#>|~]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function clipQuestionContext(value: string, maxChars: number): { text: string; truncated: boolean } {
  if (value.length <= maxChars) {
    return { text: value, truncated: false };
  }
  return { text: `${value.slice(0, maxChars - 1).trimEnd()}...`, truncated: true };
}

export function buildQuestionSelectedText(item: ExamPaperItemResponse) {
  const stem = normalizeQuestionContextText(item.stem) || "题干内容暂不可预览";
  return clipQuestionContext(`第 ${item.item_order} 题：${stem}`, 360).text;
}

function buildQuestionOptionsContext(item: ExamPaperItemResponse): string[] {
  const options = item.question_type === "true_false" && !(item.options?.length)
    ? ["True", "False"]
    : item.options ?? [];

  return options
    .map((option, index) => {
      const normalizedOption = normalizeQuestionContextText(option);
      if (item.question_type === "true_false") {
        return normalizedOption;
      }
      return `${getOptionLabel(index)}. ${normalizedOption}`;
    })
    .filter((line) => line.trim().length > 0);
}

export function buildQuestionAiDraft(item: ExamPaperItemResponse, isReviewStage: boolean) {
  if (isReviewStage && item.is_correct === false) {
    return "我这道题为什么错？请结合我的答案讲解解题思路。";
  }
  if (isReviewStage) {
    return "请帮我总结这道题的关键知识点和解题方法。";
  }
  return "请给我这道题的解题提示，不要直接给出答案。";
}

export function buildQuestionSelectionContext(
  paper: ExamPaperDetailResponse,
  item: ExamPaperItemResponse,
  answerValue: string,
  isReviewStage: boolean,
): ChatSelectionContext {
  const anchorId = buildExamQuestionAnchorId(paper.id, item.item_order);
  const selectedText = buildQuestionSelectedText(item);
  const knowledgeLabel = buildKnowledgeLabel(item);
  const optionsContext = buildQuestionOptionsContext(item);
  const answerStatus = answerValue.trim() ? answerValue.trim() : "未作答";
  const contextLines = [
    `题号：第 ${item.item_order} 题`,
    `题型：${item.question_type}`,
    `难度：${formatDifficultyLabel(item.difficulty)}`,
    `知识点：${knowledgeLabel}`,
    "",
    "题干：",
    normalizeQuestionContextText(item.stem),
  ];

  if (optionsContext.length > 0) {
    contextLines.push("", "选项：", ...optionsContext);
  }

  contextLines.push("", `学生当前答案：${answerStatus}`);

  if (isReviewStage) {
    contextLines.push(
      `正确答案：${normalizeQuestionContextText(item.correct_answer) || "无标准答案"}`,
      `批改结果：${item.is_correct ? "正确" : "需要继续巩固"}`,
      "",
      "已有解析：",
      normalizeQuestionContextText(item.explanation) || "暂无解析",
    );
  } else {
    contextLines.push("状态：尚未批改，请优先给提示、拆解思路和检查方向，不要直接泄露标准答案。");
  }

  const excerpt = clipQuestionContext(contextLines.join("\n"), 3600);
  return {
    selected_text: selectedText,
    anchor_id: anchorId,
    anchor_title: `第 ${item.item_order} 题`,
    heading_path: [formatModeLabel(paper.exam_mode), `第 ${item.item_order} 题`],
    before_text: `题型：${item.question_type}；难度：${formatDifficultyLabel(item.difficulty)}；知识点：${knowledgeLabel}`,
    after_text: isReviewStage
      ? `学生答案：${answerStatus}；正确答案：${normalizeQuestionContextText(item.correct_answer) || "无标准答案"}`
      : `学生当前答案：${answerStatus}`,
    section_title: `第 ${item.item_order} 题`,
    section_excerpt: excerpt.text,
    section_truncated: excerpt.truncated,
    local_context_truncated: false,
  };
}
