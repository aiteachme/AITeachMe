import type { ReviewTaskResponse } from "../../api/generated/model";

const TOKEN_LABELS: Record<string, string> = {
  web_practice: "网页练习",
  paper_exam: "整卷测试",
  single_choice: "单选题",
  multiple_choice: "多选题",
  multi_choice: "多选题",
  true_false: "判断题",
  fill_blank: "填空题",
  short_answer: "简答题",
  easy: "基础",
  medium: "中等",
  hard: "困难",
  mixed: "混合",
  steady: "稳步推进",
  sprint: "重点强化",
  building: "建立中",
  balanced: "平衡讲解",
  concise: "简洁提示",
  detailed: "详细推导",
};

export function formatPercent(value?: number | null): string {
  return value != null && Number.isFinite(value) ? `${Math.round(value * 100)}%` : "--";
}

export function formatToken(value?: string | null, fallback = "--"): string {
  const text = String(value ?? "").trim();
  if (!text) return fallback;
  return TOKEN_LABELS[text] ?? text.replace(/_/g, " ");
}

export function formatDateTime(value?: string | null): string {
  if (!value) return "暂无记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "暂无记录";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function average(values: number[]): number | null {
  const valid = values.filter((value) => Number.isFinite(value));
  if (!valid.length) return null;
  return valid.reduce((sum, value) => sum + value, 0) / valid.length;
}

export function clamp01(value?: number | null): number {
  return Math.max(0, Math.min(1, Number.isFinite(value ?? NaN) ? Number(value) : 0));
}

export function buildNoteText(note: string): string {
  const weak = note.match(/^Weak KnowledgeUnits:\s*(\d+)/i);
  if (weak) return `薄弱知识点：${weak[1]} 个`;
  const due = note.match(/^Due reviews:\s*(\d+)/i);
  if (due) return `到期复习：${due[1]} 项`;
  const mode = note.match(/^Recommended exam mode:\s*(.+)$/i);
  if (mode) return `推荐练习模式：${formatToken(mode[1])}`;
  const types = note.match(/^Recommended question types:\s*(.+)$/i);
  if (types) return `推荐题型：${types[1].split(",").map((item) => formatToken(item.trim())).join("、")}`;
  const difficulty = note.match(/^Difficulty focus:\s*(.+)$/i);
  if (difficulty) return `推荐难度：${formatToken(difficulty[1])}`;
  return note;
}

export function isReviewDueSoon(task: ReviewTaskResponse): boolean {
  if (task.priority >= 0.72) return true;
  if (!task.scheduled_at) return false;
  const scheduledAt = new Date(task.scheduled_at).getTime();
  if (Number.isNaN(scheduledAt)) return false;
  return scheduledAt <= Date.now() + 1000 * 60 * 60 * 24;
}

export function masteryTone(score: number): { label: string; bar: string; text: string; bg: string } {
  if (score < 0.4) {
    return { label: "需要补强", bar: "bg-rose-500", text: "text-rose-700 dark:text-rose-300", bg: "bg-rose-50 dark:bg-rose-500/10" };
  }
  if (score < 0.7) {
    return { label: "正在建立", bar: "bg-amber-500", text: "text-amber-700 dark:text-amber-300", bg: "bg-amber-50 dark:bg-amber-500/10" };
  }
  return { label: "较稳定", bar: "bg-emerald-500", text: "text-emerald-700 dark:text-emerald-300", bg: "bg-emerald-50 dark:bg-emerald-500/10" };
}
