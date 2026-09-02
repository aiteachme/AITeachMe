import type { ExamPaperDetailResponse } from "../../api/generated/model";
import { parseBackendDateTime } from "./examDateTime.ts";

export type ExamPaperExportKind = "blank" | "graded";

export type ExamPaperExportAvailability = {
  available: boolean;
  kind: ExamPaperExportKind | null;
  label: string;
  description: string;
};

const BLANK_EXPORT_STATUSES = new Set(["ready", "in_progress"]);
const EXAM_EXPORT_TIME_FORMATTER = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

export function getExamPaperExportAvailability(
  status: string | null | undefined,
  examMode?: string | null,
): ExamPaperExportAvailability {
  if (examMode === "mastery_drill") {
    return {
      available: false,
      kind: null,
      label: "暂不可导出",
      description: "闯关训练不保存完整记录",
    };
  }
  if (status === "graded") {
    return {
      available: true,
      kind: "graded",
      label: "导出批改结果",
      description: "包含作答状态、正误评判、标准答案与解析",
    };
  }
  if (status && BLANK_EXPORT_STATUSES.has(status)) {
    return {
      available: true,
      kind: "blank",
      label: "导出空白卷",
      description: "仅包含题目与空白答题区域",
    };
  }
  return {
    available: false,
    kind: null,
    label: "暂不可导出",
    description: "题目尚未完整生成",
  };
}

export function sanitizeExamExportFilenameSegment(value: string): string {
  const normalized = value
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "-")
    .replace(/\s+/g, " ")
    .replace(/-+/g, "-")
    .trim()
    .replace(/^[. -]+|[. -]+$/g, "");
  return normalized.slice(0, 80) || "训练记录";
}

export function formatExamExportDate(value: string | null | undefined): string {
  const parsed = value ? parseBackendDateTime(value) : new Date();
  const date = Number.isNaN(parsed.getTime()) ? new Date() : parsed;
  const parts = Object.fromEntries(
    EXAM_EXPORT_TIME_FORMATTER
      .formatToParts(date)
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value]),
  );
  return `${parts.year}${parts.month}${parts.day}-${parts.hour}${parts.minute}`;
}

export function buildExamExportFilename(
  title: string,
  kind: ExamPaperExportKind,
  createdAt?: string | null,
): string {
  const suffix = kind === "graded" ? "批改结果" : "空白卷";
  return `${sanitizeExamExportFilenameSegment(title)}-${suffix}-${formatExamExportDate(createdAt)}.pdf`;
}

function waitForExamPrintImageLoad(image: HTMLImageElement, signal?: AbortSignal): Promise<void> {
  if (image.complete || signal?.aborted) return Promise.resolve();

  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      image.removeEventListener("load", finish);
      image.removeEventListener("error", finish);
      signal?.removeEventListener("abort", finish);
      resolve();
    };

    image.addEventListener("load", finish, { once: true });
    image.addEventListener("error", finish, { once: true });
    signal?.addEventListener("abort", finish, { once: true });
    if (image.complete) finish();
  });
}

export async function waitForExamPrintImages(
  images: readonly HTMLImageElement[],
  signal?: AbortSignal,
): Promise<void> {
  await Promise.all(images.map(async (image) => {
    image.loading = "eager";
    await waitForExamPrintImageLoad(image, signal);
    if (signal?.aborted || typeof image.decode !== "function") return;
    try {
      await image.decode();
    } catch {
      // Broken images already reached a terminal state and must not block printing.
    }
  }));
}

export function buildExamPaperExportDetail(
  paper: ExamPaperDetailResponse,
  kind: ExamPaperExportKind,
): ExamPaperDetailResponse {
  if (kind === "graded") return paper;
  return {
    ...paper,
    score_obtained: null,
    submitted_at: null,
    graded_at: null,
    profile_sync: null,
    items: (paper.items ?? []).map((item) => ({
      ...item,
      user_answer: null,
      correct_answer: null,
      explanation: "",
      is_correct: null,
      score_obtained: null,
      error_cause_label: null,
    })),
  };
}
