import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type MouseEvent } from "react";
import { AlertTriangle, Loader2, MoreVertical, Sparkles, Trash2 } from "lucide-react";

import type { ExamHistoryItem, PaperPreview, PaperPreviewRow } from "../../api/generated/model";
import { Button } from "../ui/Button";
import type { ExamResultDisplayMode } from "../../lib/examResultDisplayPreference";
import { buildExamTitle, formatDateTime, parseBackendDateTime } from "./examDisplay";

type PreviewShape = PaperPreviewRow["shape"];
type PreviewResultStatus = "ungraded" | "correct" | "incorrect";

interface ExamGenerationProgressView {
  completed_items?: number | null;
  generated_items?: number | null;
  failed_items?: number | null;
  total_items?: number | null;
}

type ExamHistoryItemWithGeneration = ExamHistoryItem & {
  updated_at?: string | null;
  generation_progress?: ExamGenerationProgressView | null;
};

const PREVIEW_ROW_LIMIT = 4;
const GRADING_PROGRESS_REFRESH_MS = 1000;
const GRADING_PROGRESS_MIN = 8;
const GRADING_PROGRESS_MAX = 95;
const GRADING_PROGRESS_FULL_SCALE_SECONDS = 120;

function buildFallbackPaperPreview(item: ExamHistoryItem): PaperPreview {
  const rowCount = Math.min(Math.max(item.total_items || 1, 1), PREVIEW_ROW_LIMIT);
  return {
    keywords: [],
    question_types: [],
    rows: Array.from({ length: rowCount }, (_, index) => ({
      order: index + 1,
      type: "text",
      shape: "text",
      difficulty: "medium",
      density: 2,
      result_status: "ungraded",
    })),
    overflow_count: Math.max(0, (item.total_items || 0) - PREVIEW_ROW_LIMIT),
  };
}

function getPaperPreview(item: ExamHistoryItem): PaperPreview {
  const preview = item.paper_preview;
  if (preview?.rows?.length || preview?.keywords?.length || preview?.question_types?.length) {
    return preview;
  }
  return buildFallbackPaperPreview(item);
}

function getExamScorePercent(item: ExamHistoryItem): number | null {
  if (item.status !== "graded" || item.score_obtained == null || item.total_score == null) {
    return null;
  }
  const score = Number(item.score_obtained);
  const total = Number(item.total_score);
  if (!Number.isFinite(score) || !Number.isFinite(total) || total <= 0) {
    return null;
  }
  return Math.max(0, Math.min(100, Math.round((score / total) * 100)));
}

function toSafeCount(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : 0;
}

function getExamGenerationProgress(item: ExamHistoryItemWithGeneration, preview: PaperPreview) {
  const raw = item.generation_progress;
  const previewRows = preview.rows ?? [];
  const totalFromPreview = previewRows.length + Math.max(0, Number(preview.overflow_count || 0));
  const total = Math.max(
    toSafeCount(raw?.total_items),
    toSafeCount(item.total_items),
    totalFromPreview,
  );
  const fallbackGenerated = previewRows.filter((row) => row.generation_status === "generated").length;
  const fallbackFailed = previewRows.filter((row) => row.generation_status === "failed").length;
  const generated = Math.min(total || Number.MAX_SAFE_INTEGER, toSafeCount(raw?.generated_items) || fallbackGenerated);
  const failed = Math.min(total || Number.MAX_SAFE_INTEGER, toSafeCount(raw?.failed_items) || fallbackFailed);
  const completed = Math.min(
    total || Number.MAX_SAFE_INTEGER,
    Math.max(toSafeCount(raw?.completed_items), generated + failed),
  );
  const percent = total > 0 ? Math.max(6, Math.min(100, Math.round((completed / total) * 100))) : 12;
  return { completed, failed, generated, percent, total };
}

function parseTimestampMs(value?: string | null): number | null {
  if (!value) return null;
  const parsed = parseBackendDateTime(value).getTime();
  return Number.isFinite(parsed) ? parsed : null;
}

function getPaperGradingProgress(startedAtMs: number, nowMs: number): number {
  const elapsedSeconds = Math.max(0, (nowMs - startedAtMs) / 1000);
  const normalized = Math.min(
    1,
    Math.log1p(elapsedSeconds) / Math.log1p(GRADING_PROGRESS_FULL_SCALE_SECONDS),
  );
  return Math.round(
    GRADING_PROGRESS_MIN + (GRADING_PROGRESS_MAX - GRADING_PROGRESS_MIN) * normalized,
  );
}

function ScoreDigit({ digit, x }: { digit: string; x: number }) {
  const pathsByDigit: Record<string, string[]> = {
    "0": ["M10 3 C5 4 3 11 4 18 C5 26 13 28 16 21 C19 12 16 2 10 3"],
    "1": ["M11 4 C9 6 7 8 6 11", "M10 5 C9 12 8 19 7 27"],
    "2": ["M4 9 C5 4 15 3 16 9 C17 14 9 17 5 25 C8 24 13 24 17 25"],
    "3": ["M5 6 C9 3 16 4 16 9 C16 12 12 14 9 15", "M9 15 C15 15 18 20 14 24 C11 28 5 26 3 23"],
    "4": ["M14 4 C11 10 8 16 4 21 C8 21 13 20 17 20", "M14 5 C13 12 12 20 12 27"],
    "5": ["M16 5 C12 5 8 5 5 6 C5 10 4 13 4 16", "M5 16 C10 13 17 16 17 21 C17 28 8 29 3 24"],
    "6": ["M16 6 C9 5 4 11 4 18 C4 25 10 29 15 24 C19 20 16 14 10 15 C7 15 5 17 4 20"],
    "7": ["M4 6 C8 5 13 5 17 6 C13 12 10 19 8 27"],
    "8": ["M11 3 C16 4 17 10 13 13 C10 15 5 13 5 9 C5 5 8 3 11 3", "M11 14 C17 15 18 22 14 25 C10 29 4 26 4 21 C4 16 8 14 11 14"],
    "9": ["M15 16 C12 19 6 17 5 12 C4 7 8 3 13 5 C19 8 17 19 10 27"],
  };

  return (
    <g transform={`translate(${x} 0)`}>
      {(pathsByDigit[digit] ?? pathsByDigit["0"]).map((path, index) => (
        <path key={`${digit}-${path}-${index}`} d={path} />
      ))}
    </g>
  );
}

function ExamPaperScoreMark({ score }: { score: number }) {
  const digits = String(score);
  const digitWidth = 18;
  const digitGap = 2;
  const contentWidth = digits.length * digitWidth + Math.max(0, digits.length - 1) * digitGap;
  const startX = (78 - contentWidth) / 2;
  const underlineStart = Math.max(16, startX + 2);
  const underlineEnd = Math.min(62, startX + contentWidth - 2);
  const underlineMid = (underlineStart + underlineEnd) / 2;

  return (
    <div className="pointer-events-none absolute right-16 top-[56%] z-20 -rotate-[12deg] select-none text-rose-600/90 dark:text-rose-400/85" aria-hidden="true">
      <svg className="h-16 w-[78px] overflow-visible text-current" viewBox="0 0 78 54" role="presentation" aria-hidden="true">
        <g
          fill="none"
          stroke="currentColor"
          strokeWidth="3.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          transform="skewX(-8)"
        >
          {digits.split("").map((digit, index) => (
            <ScoreDigit key={`${digit}-${index}`} digit={digit} x={startX + index * (digitWidth + digitGap)} />
          ))}
        </g>
        <g fill="none" stroke="currentColor" strokeWidth="3.4" strokeLinecap="round" strokeLinejoin="round">
          <path d={`M${underlineStart} 38 C${underlineStart + 9} 36.5 ${underlineMid - 8} 37.5 ${underlineMid} 36.8 S${underlineEnd - 9} 36.2 ${underlineEnd} 36.8`} />
          <path d={`M${underlineStart - 1} 46 C${underlineStart + 8} 44.8 ${underlineMid - 7} 45.6 ${underlineMid} 45 S${underlineEnd - 8} 44.5 ${underlineEnd + 1} 45`} />
        </g>
      </svg>
    </div>
  );
}

function ExamPaperPassMark() {
  return (
    <div
      className="pointer-events-none absolute right-12 top-[56%] z-20 -rotate-[13deg] select-none text-emerald-600/90 dark:text-emerald-400/85"
      aria-hidden="true"
    >
      <div className="relative rounded-[10px] border-[3px] border-current px-4 py-2 font-serif text-2xl font-black uppercase leading-none tracking-[0.22em] shadow-[0_0_0_2px_rgba(16,185,129,0.16)_inset]">
        PASS
        <span className="absolute inset-1 rounded-[6px] border border-current opacity-55" />
      </div>
    </div>
  );
}

function getPaperTags(preview: PaperPreview): string[] {
  const tags = preview.keywords?.length ? preview.keywords : preview.question_types;
  return (tags ?? []).map((tag) => tag.trim()).filter(Boolean).slice(0, 3);
}

function PaperTagLine({ preview }: { preview: PaperPreview }) {
  const tags = getPaperTags(preview);
  if (tags.length === 0) {
    return <span className="text-slate-400 dark:text-slate-500">智能试卷</span>;
  }
  return (
    <div className="flex min-w-0 items-center justify-center gap-1 overflow-hidden">
      {tags.map((tag) => (
        <span
          key={tag}
          title={tag}
          aria-label={tag}
          className="max-w-[4.8rem] truncate rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-semibold leading-4 text-slate-500 dark:border-slate-800 dark:bg-slate-800/80 dark:text-slate-400"
        >
          {tag}
        </span>
      ))}
    </div>
  );
}

const PREVIEW_LINE_WIDTH_REM: Record<string, number> = {
  "w-7": 1.75,
  "w-8": 2,
  "w-9": 2.25,
  "w-10": 2.5,
  "w-12": 3,
  "w-14": 3.5,
  "w-16": 4,
  "w-20": 5,
};

const PREVIEW_ROW_FLOW_STEP_REM = 1.5;
const PREVIEW_ROW_LINE_START_REM = 1.5;

function getPreviewLineWidthRem(width: string) {
  return PREVIEW_LINE_WIDTH_REM[width] ?? PREVIEW_LINE_WIDTH_REM["w-16"];
}

function PreviewLine({
  width = "w-16",
  flow = false,
  flowLeftRem = PREVIEW_ROW_LINE_START_REM,
  flowTopRem = 0,
}: {
  width?: string;
  flow?: boolean;
  flowLeftRem?: number;
  flowTopRem?: number;
}) {
  return (
    <span
      className={`block h-1 rounded-full ${
        flow ? "exam-preview-flow-line opacity-100" : "bg-current opacity-70"
      } ${width}`}
      style={
        flow
          ? ({
              "--exam-preview-line-x": `${flowLeftRem}rem`,
              "--exam-preview-line-y": `${-flowTopRem}rem`,
            } as CSSProperties)
          : undefined
      }
    />
  );
}

function ChoicePreviewShape({
  density,
  flow = false,
  rowTopRem = 0,
}: {
  density: number;
  flow?: boolean;
  rowTopRem?: number;
}) {
  const firstWidth = density > 1 ? "w-12" : "w-9";
  const secondWidth = density > 2 ? "w-10" : "w-7";
  const lineTopRem = rowTopRem + 0.5;
  const secondLeftRem = PREVIEW_ROW_LINE_START_REM + getPreviewLineWidthRem(firstWidth) + 0.375;

  return (
    <div className="flex h-5 min-w-0 flex-1 items-center gap-2">
      <div className="flex min-w-0 flex-1 items-center gap-1.5">
        <PreviewLine width={firstWidth} flow={flow} flowTopRem={lineTopRem} />
        <PreviewLine width={secondWidth} flow={flow} flowLeftRem={secondLeftRem} flowTopRem={lineTopRem} />
      </div>
      <div className="grid shrink-0 grid-cols-4 gap-1">
        {[0, 1, 2, 3].map((dot) => (
          <span
            key={dot}
            className={`h-1.5 w-1.5 rounded-full border border-current ${flow ? "opacity-0" : "opacity-80"}`}
          />
        ))}
      </div>
    </div>
  );
}

function BlankPreviewShape({
  density,
  flow = false,
  rowTopRem = 0,
}: {
  density: number;
  flow?: boolean;
  rowTopRem?: number;
}) {
  const firstWidth = density > 1 ? "w-10" : "w-7";
  const thirdWidth = density > 2 ? "w-12" : "w-8";
  const lineTopRem = rowTopRem + 0.5;
  const thirdLeftRem = PREVIEW_ROW_LINE_START_REM + getPreviewLineWidthRem(firstWidth) + 3.25;

  return (
    <div className="flex h-5 min-w-0 flex-1 items-center gap-1.5">
      <PreviewLine width={firstWidth} flow={flow} flowTopRem={lineTopRem} />
      <span className={`h-3 w-10 shrink-0 border-b border-current ${flow ? "opacity-0" : "opacity-80"}`} />
      <PreviewLine width={thirdWidth} flow={flow} flowLeftRem={thirdLeftRem} flowTopRem={lineTopRem} />
    </div>
  );
}

function TextPreviewShape({
  density,
  flow = false,
  rowTopRem = 0,
}: {
  density: number;
  flow?: boolean;
  rowTopRem?: number;
}) {
  const lines = density > 2 ? ["w-20", "w-16", "w-12"] : density > 1 ? ["w-20", "w-14"] : ["w-16"];
  const firstLineTopRem = density > 2 ? rowTopRem : rowTopRem + (density > 1 ? 0.25 : 0.5);
  return (
    <div className="flex h-5 min-w-0 flex-1 flex-col justify-center gap-1">
      {lines.map((width, index) => (
        <PreviewLine
          key={`${width}-${index}`}
          width={width}
          flow={flow}
          flowTopRem={firstLineTopRem + index * 0.5}
        />
      ))}
    </div>
  );
}

function JudgePreviewShape({
  density,
  flow = false,
  rowTopRem = 0,
}: {
  density: number;
  flow?: boolean;
  rowTopRem?: number;
}) {
  return (
    <div className="flex h-5 min-w-0 flex-1 items-center gap-2">
      <span
        className={`grid h-4 w-4 shrink-0 place-items-center rounded border border-current text-[9px] font-semibold ${
          flow ? "opacity-0" : "opacity-80"
        }`}
      >
        T
      </span>
      <PreviewLine
        width={density > 1 ? "w-20" : "w-14"}
        flow={flow}
        flowLeftRem={PREVIEW_ROW_LINE_START_REM + 1.5}
        flowTopRem={rowTopRem + 0.5}
      />
    </div>
  );
}

function ChartPreviewShape() {
  return (
    <svg className="h-5 min-w-0 flex-1 text-current opacity-80" viewBox="0 0 96 24" role="presentation" aria-hidden="true">
      <rect x="2" y="3" width="44" height="18" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M8 17h32M8 17V7" fill="none" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
      <path d="M9 15l8-5 7 4 8-8 7 6" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M56 8h28M56 15h20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function FormulaPreviewShape() {
  return (
    <div className="flex h-5 min-w-0 flex-1 items-center gap-2 text-[10px] font-semibold text-current">
      <span className="shrink-0 font-serif">f(x)</span>
      <svg className="h-5 min-w-0 flex-1 text-current opacity-80" viewBox="0 0 72 20" role="presentation" aria-hidden="true">
        <path d="M3 14c8-13 18-13 28 0s20 6 36-8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    </div>
  );
}

function CodePreviewShape({
  density,
  flow = false,
  rowTopRem = 0,
}: {
  density: number;
  flow?: boolean;
  rowTopRem?: number;
}) {
  const firstLineTopRem = rowTopRem + (density > 2 ? 0.25 : 0.5);
  const lineLeftRem = PREVIEW_ROW_LINE_START_REM + 1.35;

  return (
    <div className="flex h-5 min-w-0 flex-1 items-center gap-2 font-mono text-[11px] font-semibold text-current">
      <span className={`shrink-0 ${flow ? "opacity-0" : ""}`}>{"{}"}</span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <PreviewLine
          width={density > 1 ? "w-20" : "w-14"}
          flow={flow}
          flowLeftRem={lineLeftRem}
          flowTopRem={firstLineTopRem}
        />
        {density > 2 ? (
          <PreviewLine width="w-12" flow={flow} flowLeftRem={lineLeftRem} flowTopRem={firstLineTopRem + 0.5} />
        ) : null}
      </div>
    </div>
  );
}

function PaperPreviewShape({
  row,
  flow = false,
  flowRowIndex = 0,
}: {
  row: PaperPreviewRow;
  flow?: boolean;
  flowRowIndex?: number;
}) {
  const shape = (row.shape || "text") as PreviewShape;
  const density = row.density || 2;
  const rowTopRem = flowRowIndex * PREVIEW_ROW_FLOW_STEP_REM;
  if (shape === "choice") return <ChoicePreviewShape density={density} flow={flow} rowTopRem={rowTopRem} />;
  if (shape === "blank") return <BlankPreviewShape density={density} flow={flow} rowTopRem={rowTopRem} />;
  if (shape === "judge") return <JudgePreviewShape density={density} flow={flow} rowTopRem={rowTopRem} />;
  if (flow && (shape === "chart" || shape === "formula")) return <TextPreviewShape density={2} flow rowTopRem={rowTopRem} />;
  if (shape === "chart") return <ChartPreviewShape />;
  if (shape === "formula") return <FormulaPreviewShape />;
  if (shape === "code") return <CodePreviewShape density={density} flow={flow} rowTopRem={rowTopRem} />;
  return <TextPreviewShape density={density} flow={flow} rowTopRem={rowTopRem} />;
}

function PaperPreviewFlowOverlay({
  rows,
  loadingOrders,
}: {
  rows: PaperPreviewRow[];
  loadingOrders: Set<number>;
}) {
  return (
    <div className="exam-preview-flow-overlay" aria-hidden="true">
      {rows.map((row, index) => {
        const isLoading = loadingOrders.has(row.order);
        return (
          <div key={`flow-${row.order}-${row.type}`} className="flex h-5 items-center gap-2 text-transparent">
            {isLoading ? (
              <>
                <span className="w-4 shrink-0 text-right text-[10px] font-semibold tabular-nums opacity-0">
                  {row.order}
                </span>
                <div className="relative flex min-w-0 flex-1 pr-4">
                  <PaperPreviewShape row={row} flow flowRowIndex={index} />
                </div>
              </>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function getPreviewResultStatus(row: PaperPreviewRow): PreviewResultStatus {
  const status = (row as PaperPreviewRow & { result_status?: PreviewResultStatus }).result_status;
  if (status === "correct" || status === "incorrect") return status;
  return "ungraded";
}

function isPreviewRowLoading(row: PaperPreviewRow, isGenerating: boolean): boolean {
  if (!isGenerating) return false;
  if (row.generation_status === "failed") return false;
  return row.generation_status !== "generated";
}

function getResultMarkJitter(row: PaperPreviewRow) {
  const seed = row.order * 37 + row.type.length * 11 + row.difficulty.length * 7;
  return {
    x: [-6, -4, -2, 0, 2, 4][seed % 6],
    y: [-5, -3, -1, 1, 3, 5][Math.floor(seed / 5) % 6],
    rotate: [-11, -7, -3, 4, 8, 12][Math.floor(seed / 11) % 6],
  };
}

function PaperPreviewResultMark({ status, row }: { status: PreviewResultStatus; row: PaperPreviewRow }) {
  const jitter = getResultMarkJitter(row);
  const style = {
    transform: `translate(${jitter.x}px, calc(-50% + ${jitter.y}px)) rotate(${jitter.rotate}deg)`,
    fontFamily: '"Segoe Print", "Comic Sans MS", cursive',
  };
  if (status === "correct") {
    return (
      <span className="absolute right-2 top-1/2 grid h-4 w-4 place-items-center text-[18px] font-semibold leading-none text-emerald-500 dark:text-emerald-400" style={style}>
        ✓
      </span>
    );
  }
  if (status === "incorrect") {
    return (
      <span className="absolute right-2 top-1/2 grid h-4 w-4 place-items-center text-[18px] font-semibold leading-none text-rose-500 dark:text-rose-400" style={style}>
        ×
      </span>
    );
  }
  return null;
}

function PaperPreviewGenerationMark({ row }: { row: PaperPreviewRow }) {
  if (row.generation_status !== "failed") return null;
  const jitter = getResultMarkJitter(row);
  return (
    <span
      className="absolute right-2 top-1/2 grid h-4 w-4 place-items-center text-[16px] font-semibold leading-none text-rose-500 dark:text-rose-400"
      style={{
        transform: `translate(${jitter.x}px, calc(-50% + ${jitter.y}px)) rotate(${jitter.rotate}deg)`,
        fontFamily: '"Segoe Print", "Comic Sans MS", cursive',
      }}
      title="本题生成失败"
      aria-label="本题生成失败"
    >
      !
    </span>
  );
}

function PaperFingerprintPreview({
  preview,
  isGenerating = false,
  showResultMarks = false,
}: {
  preview: PaperPreview;
  isGenerating?: boolean;
  showResultMarks?: boolean;
}) {
  const allRows = preview.rows ?? [];
  const rows = allRows.slice(0, PREVIEW_ROW_LIMIT);
  const hiddenPreviewRows = Math.max(0, allRows.length - PREVIEW_ROW_LIMIT);
  const overflowCount = (preview.overflow_count || 0) + hiddenPreviewRows;
  const visibleLoadingOrders = new Set(
    rows.filter((row) => isPreviewRowLoading(row, isGenerating)).map((row) => row.order),
  );
  const hasLoadingRows = allRows.some((row) => isPreviewRowLoading(row, isGenerating));

  return (
    <div
      className={`relative z-10 mt-3 flex flex-1 flex-col overflow-hidden pt-1 ${
        hasLoadingRows ? "exam-preview-unified-flow" : ""
      }`}
      aria-busy={hasLoadingRows || undefined}
    >
      <div className="relative">
        <div className="space-y-1">
          {rows.map((row) => {
            const status = getPreviewResultStatus(row);
            return (
              <div
                key={`${row.order}-${row.type}`}
                className="flex h-5 items-center gap-2 text-slate-400 dark:text-slate-600"
              >
                <span className="w-4 shrink-0 text-right text-[10px] font-semibold tabular-nums opacity-80">
                  {row.order}
                </span>
                <div className="relative flex min-w-0 flex-1 pr-4">
                  <PaperPreviewShape row={row} />
                  <PaperPreviewGenerationMark row={row} />
                  {showResultMarks ? <PaperPreviewResultMark status={status} row={row} /> : null}
                </div>
              </div>
            );
          })}
        </div>
        {visibleLoadingOrders.size > 0 ? <PaperPreviewFlowOverlay rows={rows} loadingOrders={visibleLoadingOrders} /> : null}
      </div>

      {overflowCount > 0 ? (
        <div className="mt-1 flex h-4 items-center pl-6">
          <span
            className={`rounded-full border border-slate-200 bg-slate-50 px-2 text-[10px] font-semibold leading-4 text-slate-500 dark:border-slate-800 dark:bg-slate-800/80 dark:text-slate-400 ${
              hasLoadingRows ? "exam-preview-flow-tag exam-preview-flow-tag-loading" : ""
            }`}
          >
            +{overflowCount}
          </span>
        </div>
      ) : null}

    </div>
  );
}

function FailedPaperPreview() {
  return (
    <div
      className="relative z-10 mt-3 flex flex-1 flex-col items-center justify-center overflow-hidden rounded-md border border-rose-100 bg-rose-50/60 px-4 text-center text-rose-600 dark:border-rose-900/60 dark:bg-rose-950/20 dark:text-rose-300"
      aria-label="内容生成失败"
    >
      <div className="grid h-12 w-12 place-items-center rounded-full bg-white shadow-sm ring-1 ring-rose-100 dark:bg-rose-950/40 dark:ring-rose-900/70">
        <AlertTriangle className="h-6 w-6" />
      </div>
      <div className="mt-3 text-sm font-semibold">生成失败</div>
      <div className="mt-1 max-w-[9rem] text-[11px] leading-5 text-rose-500/80 dark:text-rose-300/75">
        这份内容没有生成完成
      </div>
      <div className="mt-4 h-px w-full bg-rose-100 dark:bg-rose-900/70" />
      <div className="mt-3 grid w-full gap-1.5 text-rose-300/80 dark:text-rose-700">
        <span className="mx-auto block h-1 w-24 rounded-full bg-current" />
        <span className="mx-auto block h-1 w-16 rounded-full bg-current" />
        <span className="mx-auto block h-1 w-20 rounded-full bg-current" />
      </div>
    </div>
  );
}

function PaperGradingPreview({ submittedAt }: { submittedAt?: string | null }) {
  const mountedAtRef = useRef(Date.now());
  const [nowMs, setNowMs] = useState(() => Date.now());
  const startedAtMs = parseTimestampMs(submittedAt) ?? mountedAtRef.current;
  const progress = getPaperGradingProgress(startedAtMs, nowMs);

  useEffect(() => {
    setNowMs(Date.now());
    const interval = window.setInterval(() => {
      setNowMs(Date.now());
    }, GRADING_PROGRESS_REFRESH_MS);
    return () => window.clearInterval(interval);
  }, [submittedAt]);

  return (
    <div
      className="relative z-10 mt-3 flex flex-1 flex-col items-center justify-center overflow-hidden rounded-xl border border-indigo-100/50 bg-indigo-50/10 px-4 py-4 text-center dark:border-indigo-900/40 dark:bg-indigo-950/10 animate-pulse"
      aria-label={`智能阅卷中，进度 ${progress}%`}
    >
      <div className="relative flex h-10 w-10 items-center justify-center rounded-full bg-white shadow-sm ring-1 ring-indigo-50 dark:bg-slate-900 dark:ring-indigo-950">
        <Loader2 className="h-5 w-5 animate-spin text-indigo-500" />
        <Sparkles className="absolute -right-1.5 -top-1.5 h-3.5 w-3.5 animate-pulse text-amber-500" />
      </div>
      <div className="mt-2 text-xs font-black text-slate-800 dark:text-slate-200">AI 智能阅卷中</div>
      <div className="mt-1 max-w-[11rem] text-[10px] leading-relaxed text-slate-500 dark:text-slate-400">
        正在深度解析作答并同步掌握度数据
      </div>
      <div className="mt-3.5 w-24 overflow-hidden rounded-full bg-slate-200/60 dark:bg-slate-800 h-1.5 relative">
        <div
          className="h-full rounded-full bg-indigo-500 transition-all duration-1000 ease-out"
          style={{ width: `${progress}%` }}
        />
      </div>
      <span className="mt-1 text-[9px] font-bold tabular-nums text-indigo-600/80 dark:text-indigo-400/80">
        {progress}%
      </span>
    </div>
  );
}

export function ExamPaperCard({
  item,
  resultDisplayMode,
  isDeleting,
  onOpen,
  onDelete,
}: {
  item: ExamHistoryItemWithGeneration;
  resultDisplayMode: ExamResultDisplayMode;
  isDeleting: boolean;
  onOpen: () => void;
  onDelete: (event: MouseEvent<HTMLButtonElement>) => void;
}) {
  const preview = getPaperPreview(item);
  const isGraded = item.status === "graded";
  const isGenerating = item.status === "generating";
  const isFailed = item.status === "failed";
  const isGrading = item.status === "submitted" || item.status === "grading";
  const showDetailedResult = isGraded && resultDisplayMode === "score";
  const showPassMark = isGraded && resultDisplayMode === "completed";
  const scorePercent = getExamScorePercent(item);
  const generationProgress = getExamGenerationProgress(item, preview);

  const handleCardKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onOpen();
  };

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={handleCardKeyDown}
      className="group w-full max-w-[300px] cursor-pointer rounded-[22px] bg-transparent p-1.5 text-left transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-2 hover:scale-[1.02] hover:rotate-[-0.5deg] focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2"
    >
      <div
        className={`relative mx-auto aspect-[300/230] w-full max-w-[300px] transition-all duration-300 ${
          isFailed
            ? "drop-shadow-[0_16px_24px_rgba(190,18,60,0.14)] group-hover:drop-shadow-[0_22px_34px_rgba(190,18,60,0.18)]"
            : "drop-shadow-[0_16px_24px_rgba(15,23,42,0.08)] group-hover:drop-shadow-[0_22px_34px_rgba(15,23,42,0.12)] dark:drop-shadow-[0_16px_24px_rgba(0,0,0,0.4)] dark:group-hover:drop-shadow-[0_24px_36px_rgba(0,0,0,0.55)]"
        }`}
      >
        <div
          className={`absolute inset-0 flex flex-col overflow-hidden rounded-[18px] border bg-white px-4 py-4 text-slate-950 dark:bg-slate-900 dark:text-slate-100 ${
            isFailed ? "border-rose-200 dark:border-rose-900/70" : "border-slate-200 dark:border-slate-800"
          }`}
          style={{ clipPath: "polygon(0 0, calc(100% - 48px) 0, 100% 48px, 100% 100%, 0 100%)" }}
        >

        <div className="relative z-10 px-3 pt-1 text-center">
          <h3 className="mx-auto line-clamp-1 max-w-[220px] text-base font-semibold leading-snug text-slate-950 dark:text-slate-100">
            {buildExamTitle(item)}
          </h3>
          {isGraded && item.submitted_at ? (
            <p className="mt-1 truncate text-[10px] font-semibold leading-4 text-slate-400 dark:text-slate-500">
              提交 {formatDateTime(item.submitted_at)}
            </p>
          ) : null}
          <div className="mx-auto mt-2 h-px w-16 bg-slate-200 dark:bg-slate-700" />
        </div>

        <div
          className={`relative z-10 mt-3 border-y px-1 py-1.5 text-center text-xs font-semibold ${
            isFailed
              ? "border-rose-100 text-rose-600 dark:border-rose-900/60 dark:text-rose-300"
              : isGrading
                ? "border-indigo-100 text-indigo-600 dark:border-indigo-900/50 dark:text-indigo-300"
                : "border-slate-100 text-slate-600 dark:border-slate-800 dark:text-slate-300"
          }`}
        >
          {isFailed ? (
            <span className="inline-flex items-center justify-center gap-1">
              <AlertTriangle className="h-3.5 w-3.5" />
               内容生成失败
            </span>
          ) : isGenerating ? (
            <div
              className="mx-auto w-full max-w-[11rem] space-y-1"
              aria-label={`题目生成中 ${generationProgress.completed}/${generationProgress.total || item.total_items || 0}`}
            >
              <span className="inline-flex items-center justify-center gap-1.5">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                生成中{generationProgress.total ? ` ${generationProgress.completed}/${generationProgress.total}` : ""}
              </span>
              <div className="h-1 overflow-hidden rounded-full bg-slate-200/80 dark:bg-slate-800">
                <div
                  className="h-full rounded-full bg-slate-500 transition-all duration-500 dark:bg-slate-300"
                  style={{ width: `${generationProgress.percent}%` }}
                />
              </div>
            </div>
          ) : isGrading ? (
            <span className="inline-flex items-center justify-center gap-1.5 text-indigo-600 dark:text-indigo-400 font-bold" aria-label="智能阅卷中">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              AI 智能阅卷中
            </span>
          ) : (
            <PaperTagLine preview={preview} />
          )}
        </div>

        {isFailed ? (
          <FailedPaperPreview />
        ) : isGrading ? (
          <PaperGradingPreview submittedAt={item.submitted_at} />
        ) : (
          <PaperFingerprintPreview
            preview={preview}
            isGenerating={isGenerating}
            showResultMarks={showDetailedResult}
          />
        )}

        {showDetailedResult && scorePercent !== null ? <ExamPaperScoreMark score={scorePercent} /> : null}
        {showPassMark ? <ExamPaperPassMark /> : null}

        <div className="absolute bottom-4 right-4 z-20 flex items-center gap-2 opacity-0 translate-y-1 group-hover:opacity-100 group-hover:translate-y-0 pointer-events-none group-hover:pointer-events-auto transition-all duration-300">
            <Button
              type="button"
              size="icon"
              variant="outline"
              className="!h-8 !w-8 shrink-0 rounded-full border-slate-200 bg-white text-slate-900 hover:border-red-200 hover:bg-red-50 hover:text-red-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:border-red-500/40 dark:hover:bg-red-950/30 dark:hover:text-red-300"
              aria-label={`删除记录 ${buildExamTitle(item)}`}
              title="删除记录"
              disabled={isDeleting}
              onClick={onDelete}
            >
              {isDeleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
            </Button>
            <button
              type="button"
              className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-slate-100 text-slate-600 transition hover:bg-slate-900 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700"
              aria-label={`展开记录操作 ${buildExamTitle(item)}`}
              title="更多操作"
              onClick={(event) => {
                event.stopPropagation();
              }}
            >
              <MoreVertical className="h-4 w-4" />
            </button>
        </div>
        </div>
        <style>{`
          .stop-fold-0-${item.id} { stop-color: #d2dbe7; }
          .stop-fold-1-${item.id} { stop-color: #e7edf5; }
          .stop-fold-2-${item.id} { stop-color: #f7f9fc; }
          .stop-fold-3-${item.id} { stop-color: #ffffff; }
          .dark .stop-fold-0-${item.id} { stop-color: #0f172a; }
          .dark .stop-fold-1-${item.id} { stop-color: #1e293b; }
          .dark .stop-fold-2-${item.id} { stop-color: #334155; }
          .dark .stop-fold-3-${item.id} { stop-color: #475569; }
        `}</style>
        <svg
          className="pointer-events-none absolute right-0 top-0 z-30 h-12 w-12 overflow-visible drop-shadow-[-6px_7px_10px_rgba(15,23,42,0.18)] dark:drop-shadow-[-6px_7px_10px_rgba(0,0,0,0.4)]"
          viewBox="0 0 48 48"
          role="presentation"
          aria-hidden="true"
        >
          <defs>
            <linearGradient id={`exam-paper-fold-${item.id}`} x1="48" y1="0" x2="0" y2="48" gradientUnits="userSpaceOnUse">
              <stop offset="0" className={`stop-fold-0-${item.id}`} />
              <stop offset="0.36" className={`stop-fold-1-${item.id}`} />
              <stop offset="0.72" className={`stop-fold-2-${item.id}`} />
              <stop offset="1" className={`stop-fold-3-${item.id}`} />
            </linearGradient>
          </defs>
          <path d="M0 0L48 48H7Q0 48 0 41Z" fill={`url(#exam-paper-fold-${item.id})`} className="stroke-slate-200 dark:stroke-slate-700" strokeWidth="1" strokeLinejoin="round" />
          <path d="M0 0L48 48" fill="none" className="stroke-slate-300 dark:stroke-slate-800" strokeWidth="1" strokeLinecap="round" />
          <path d="M1 2V40Q1 47 8 47H47" fill="none" className="stroke-slate-50 dark:stroke-slate-950/40" strokeWidth="0.75" strokeLinejoin="round" />
        </svg>
      </div>
    </article>
  );
}
