import type { Dispatch, SetStateAction } from "react";
import { AlertTriangle, Bookmark, Lightbulb, MessageSquareText } from "lucide-react";

import type { ExamPaperDetailResponse, ExamPaperItemResponse, PaperPreviewRow } from "../../api/generated/model";
import { cn } from "../../lib/utils";
import { ExamMarkdown } from "./ExamMarkdown";
import {
  getAnsweredCount,
  getEstimatedExamMinutes,
  getExamPaperDisplayTitle,
  getExamTotalScore,
  getOptionLabel,
  splitMultiChoiceAnswer,
} from "./examDisplay";

interface ExamPaperSheetProps {
  paper: ExamPaperDetailResponse;
  answers: Record<number, string>;
  activeStage: 1 | 2 | 3;
  pageScale: number;
  highlightedQuestionOrder?: number | null;
  setAnswers: Dispatch<SetStateAction<Record<number, string>>>;
  selectedItemId?: number | null;
  showInlineReviewDetails?: boolean;
  onSelectQuestion?: (item: ExamPaperItemResponse) => void;
  onQuestionAi?: (item: ExamPaperItemResponse, isReviewStage: boolean, answerValue: string) => void;
}

function buildGeneratingRows(paper: ExamPaperDetailResponse): PaperPreviewRow[] {
  const previewRows = [
    ...(paper.paper_preview?.rows ?? []),
    ...buildFailedRowsFromSelectionContext(paper),
  ];
  const previewByOrder = new Map(previewRows.map((row) => [row.order, row]));
  const maxPreviewOrder = Math.max(0, ...previewRows.map((row) => Number(row.order) || 0));
  const count = Math.max(Number(paper.total_items || 0), previewRows.length, maxPreviewOrder, 1);
  return Array.from({ length: count }, (_, index) => {
    const order = index + 1;
    return (
      previewByOrder.get(order) ?? {
        order,
        type: "pending",
        shape: "text",
        difficulty: "medium",
        density: 2,
        result_status: "ungraded",
      }
    );
  });
}

function buildFailedRowsFromSelectionContext(paper: ExamPaperDetailResponse): PaperPreviewRow[] {
  const failedQuestions = paper.selection_context?.failed_questions;
  if (!Array.isArray(failedQuestions)) return [];

  return failedQuestions.flatMap((item): PaperPreviewRow[] => {
    if (typeof item !== "object" || item === null) return [];
    const record = item as Record<string, unknown>;
    const order = Number(record.item_order);
    if (!Number.isFinite(order) || order <= 0) return [];
    return [{
      order: Math.trunc(order),
      type: typeof record.question_type === "string" && record.question_type.trim()
        ? record.question_type
        : "text",
      shape: "text",
      difficulty: typeof record.difficulty === "string" && record.difficulty.trim()
        ? record.difficulty
        : "medium",
      density: 2,
      result_status: "ungraded",
      generation_status: "failed",
    }];
  });
}

function buildQuestionEntries(
  paper: ExamPaperDetailResponse,
  itemsByOrder: Map<number, ExamPaperItemResponse>,
): Array<{
  item: ExamPaperItemResponse | null;
  row: PaperPreviewRow | null;
}> {
  if (paper.status === "generating") {
    return buildGeneratingRows(paper).map((row) => ({
      item: itemsByOrder.get(row.order) ?? null,
      row,
    }));
  }

  const previewRows = paper.paper_preview?.rows ?? [];
  const failedRowsByOrder = new Map(
    [...previewRows, ...buildFailedRowsFromSelectionContext(paper)]
      .filter((row) => row.generation_status === "failed")
      .map((row) => [row.order, row]),
  );
  const orders = new Set<number>([
    ...(paper.items ?? []).map((item: ExamPaperItemResponse) => item.item_order),
    ...failedRowsByOrder.keys(),
  ]);

  return Array.from(orders)
    .sort((left, right) => left - right)
    .map((order) => ({
      item: itemsByOrder.get(order) ?? null,
      row: failedRowsByOrder.get(order) ?? null,
    }));
}

function GeneratingQuestionPlaceholder({ row }: { row: PaperPreviewRow }) {
  const isFailed = row.generation_status === "failed";
  const isChoice =
    row.shape === "choice" ||
    row.shape === "judge" ||
    row.type === "single_choice" ||
    row.type === "multiple_choice" ||
    row.type === "true_false";
  const lineWidths = row.density && row.density > 2
    ? ["w-11/12", "w-8/12", "w-10/12", "w-6/12"]
    : ["w-11/12", "w-8/12", "w-10/12"];
  return (
    <div
      id={`exam-question-${row.order}`}
      data-question-anchor="true"
      data-question-order={row.order}
      className="exam-preview-unified-flow scroll-mt-28 border-b-[1.5px] border-dashed border-slate-200/90 px-0 py-7 last:border-b-0 dark:border-slate-800/90 sm:py-9"
    >
      <div className="grid min-w-0 gap-5 md:grid-cols-[72px_minmax(0,1fr)]">
        <aside className="flex items-start gap-4 border-b border-slate-100 pb-4 text-slate-500 dark:border-slate-800 dark:text-slate-400 md:flex-col md:items-center md:border-b-0 md:border-r md:pb-0 md:pr-4">
          <div className="font-serif text-2xl font-bold leading-none text-slate-950 dark:text-slate-100">{row.order}.</div>
          <div className="flex flex-wrap gap-2 text-xs font-semibold text-slate-400 md:flex-col md:gap-2">
            <span className="inline-flex flex-col items-center gap-1">
              <Bookmark className="h-4 w-4" />
              标记
            </span>
          </div>
        </aside>

        <div className="min-w-0 overflow-hidden">
          {isFailed ? (
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded-full bg-rose-50 px-2.5 py-1 text-xs font-semibold text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">
                <AlertTriangle className="h-3.5 w-3.5" />
                生成失败
              </span>
            </div>
          ) : null}

          {isFailed ? (
            <div className="rounded-xl border border-rose-200 bg-rose-50 px-5 py-6 text-sm leading-7 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300 sm:px-6">
              <div className="flex items-center gap-2 font-semibold text-rose-800 dark:text-rose-200">
                <AlertTriangle className="h-4 w-4" />
                本题生成失败
              </div>
              <p className="mt-2 text-rose-600">这道题已跳过，不会计入本次试卷题量和批改。</p>
            </div>
          ) : (
          <div className="exam-preview-skeleton-panel rounded-xl border border-slate-200 p-5 dark:border-slate-800 sm:p-6">
            <div className="space-y-3">
              {lineWidths.map((width, index) => (
                <span
                  key={`${row.order}-stem-${index}`}
                  className={`exam-preview-flow-line relative z-[1] block h-3 rounded-full ${width}`}
                />
              ))}
            </div>
          </div>
          )}

          {!isFailed && isChoice ? (
            <div className="mt-6 grid gap-3">
              {[0, 1, 2, 3].map((optionIndex) => (
                <div
                  key={optionIndex}
                  className="exam-preview-skeleton-panel flex items-center gap-3 rounded-lg border border-slate-200 px-3 py-3 dark:border-slate-800 sm:gap-4 sm:px-4 sm:py-3.5"
                >
                  <span className="relative z-[1] h-5 w-5 shrink-0 rounded-full border-2 border-slate-300 bg-white dark:border-slate-600 dark:bg-slate-900" />
                  <span
                    className={`exam-preview-flow-line relative z-[1] block h-2.5 rounded-full ${
                      optionIndex % 2 === 0 ? "w-8/12" : "w-6/12"
                    }`}
                  />
                </div>
              ))}
            </div>
          ) : !isFailed ? (
            <div className="exam-preview-skeleton-panel mt-6 min-h-32 rounded-lg border border-slate-200 p-4 dark:border-slate-800">
              <div className="relative z-[1] space-y-3">
                <span className="exam-preview-flow-line block h-3 w-7/12 rounded-full" />
                <span className="exam-preview-flow-line block h-3 w-10/12 rounded-full" />
                <span className="exam-preview-flow-line block h-3 w-5/12 rounded-full" />
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function ExamPaperSheet({
  paper,
  answers,
  activeStage,
  pageScale,
  highlightedQuestionOrder,
  setAnswers,
  selectedItemId,
  showInlineReviewDetails = true,
  onSelectQuestion,
  onQuestionAi,
}: ExamPaperSheetProps) {
  const items = paper.items ?? [];
  const itemsByOrder = new Map(items.map((item: ExamPaperItemResponse) => [item.item_order, item]));
  const questionEntries = buildQuestionEntries(paper, itemsByOrder);

  return (
                <div
                  className="relative mx-auto max-w-[1080px] pb-12"
                  style={
                    pageScale < 1
                      ? {
                          width: `${pageScale * 100}%`,
                          marginLeft: "auto",
                          marginRight: "auto",
                        }
                      : undefined
                  }
                >
                  <div className="absolute bottom-8 -right-5 top-5 hidden w-full border border-slate-200 bg-white shadow-[0_18px_36px_rgba(15,23,42,0.08)] dark:border-slate-800 dark:bg-slate-900/80 dark:shadow-[0_18px_36px_rgba(0,0,0,0.42)] lg:block" />
                  <div className="absolute bottom-4 -right-2 top-2 hidden w-full border border-slate-200 bg-white shadow-[0_14px_30px_rgba(15,23,42,0.06)] dark:border-slate-800 dark:bg-slate-900/90 dark:shadow-[0_14px_30px_rgba(0,0,0,0.36)] lg:block" />
                  <article className="relative overflow-hidden border border-slate-200 bg-white shadow-[0_26px_70px_rgba(15,23,42,0.15)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_28px_76px_-34px_rgba(0,0,0,0.9)]">
                    <header className="px-6 pb-6 pt-12 text-center sm:px-10 sm:pt-16 lg:px-16">
                      <h1 className="font-serif text-3xl font-bold tracking-[0.08em] text-slate-950 dark:text-slate-100 sm:text-4xl">
                        {getExamPaperDisplayTitle(paper)}
                      </h1>
                      <div className="mx-auto mt-5 flex max-w-md items-center justify-center gap-3 text-slate-400 dark:text-slate-600">
                        <span className="h-px flex-1 bg-slate-300 dark:bg-slate-700" />
                        <span className="h-2 w-2 rotate-45 bg-slate-800 dark:bg-slate-300" />
                        <span className="h-px flex-1 bg-slate-300 dark:bg-slate-700" />
                      </div>
                      <p className="mt-4 font-serif text-base font-semibold text-slate-600 dark:text-slate-400">
                        本试卷共 {paper.total_items} 题，满分 {getExamTotalScore(paper)} 分，预计用时 {getEstimatedExamMinutes(paper)} 分钟
                      </p>
                      <div className="mt-8 border-b border-dashed border-slate-300 pb-5 text-left font-serif text-sm leading-8 text-slate-700 dark:border-slate-700 dark:text-slate-300 sm:text-base">
                        <p className="font-bold text-slate-800 dark:text-slate-200">注意事项：</p>
                        <p>1. 请在作答区内选择或填写答案，系统会自动保存当前选择。</p>
                        <p>2. 可使用右侧工具调整页面与字体大小；提交前请检查左侧题号状态。</p>
                      </div>
                    </header>

                    <div className="px-4 pb-8 sm:px-8 lg:px-14">
                      {questionEntries.map((entry) => {
                    if (!entry.item) {
                      return entry.row ? <GeneratingQuestionPlaceholder key={entry.row.order} row={entry.row} /> : null;
                    }
                    const item = entry.item;
                    const answerValue = answers[item.item_order] ?? "";
                    const isSingleChoice = item.question_type === "single_choice";
                    const isMultipleChoice = item.question_type === "multiple_choice" || item.question_type === "multi_choice";
                    const isTrueFalse = item.question_type === "true_false";
                    const isChoice = isSingleChoice || isMultipleChoice || isTrueFalse;
                    const choiceOptions = isTrueFalse && !(item.options?.length)
                      ? ["True", "False"]
                      : (item.options ?? []);
                    const selectedMultiChoice = splitMultiChoiceAnswer(answerValue);
                    const correctMultiChoice = splitMultiChoiceAnswer(item.correct_answer);
                    const isGraded = paper.status === "graded";
                    const isReviewStage = isGraded && activeStage === 2;
                    const isReadonly = isGraded;
                    const isCorrect = item.is_correct === true;
                    const isSelectedReviewItem = isReviewStage && selectedItemId === item.id;
                    const isQuestionHighlighted = highlightedQuestionOrder === item.item_order;

                    return (
                      <div
                        key={item.id}
                        id={`exam-question-${item.item_order}`}
                        data-question-anchor="true"
                        data-question-order={item.item_order}
                        onClick={() => {
                          if (isReviewStage) {
                            onSelectQuestion?.(item);
                          }
                        }}
                        className={cn(
                          "scroll-mt-28 border-b-[1.5px] border-dashed border-slate-200/90 px-0 py-7 transition-[background-color,box-shadow] duration-300 last:border-b-0 dark:border-slate-800/90 sm:py-9",
                          (isReviewStage || isQuestionHighlighted) && "px-4 sm:px-5 lg:px-6",
                          isReviewStage && "cursor-pointer rounded-xl",
                          isSelectedReviewItem && "bg-slate-50/80 outline outline-1 outline-slate-200 dark:bg-slate-900/70 dark:outline-slate-700",
                          isQuestionHighlighted && "rounded-xl bg-slate-50/80 outline outline-1 outline-slate-200 dark:bg-slate-900/70 dark:outline-slate-700",
                        )}
                        aria-selected={isSelectedReviewItem || undefined}
                      >
                        <div className="grid min-w-0 gap-5 md:grid-cols-[72px_minmax(0,1fr)]">
                          <aside className="flex items-start gap-4 border-b border-slate-100 pb-4 text-slate-500 dark:border-slate-800 dark:text-slate-400 md:flex-col md:items-center md:border-b-0 md:border-r md:pb-0 md:pr-4">
                            <div className="font-serif text-2xl font-bold leading-none text-slate-950 dark:text-slate-100">
                              {item.item_order}.
                            </div>
                            <div className="flex flex-wrap gap-2 text-xs font-semibold text-slate-400 md:flex-col md:gap-2">
                              {onQuestionAi && (
                                <button
                                  type="button"
                                  onClick={() => onQuestionAi(item, isReviewStage, answerValue)}
                                  className="inline-flex min-h-10 min-w-10 flex-col items-center justify-center gap-1 rounded-xl border border-violet-200 bg-violet-50 px-2 text-[11px] font-semibold text-violet-700 shadow-sm transition hover:border-violet-300 hover:bg-violet-100 hover:text-violet-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-300 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:border-violet-500/30 dark:bg-violet-500/10 dark:text-violet-200 dark:hover:border-violet-400/50 dark:hover:bg-violet-500/15 dark:hover:text-violet-100 dark:focus-visible:ring-violet-400/40 dark:focus-visible:ring-offset-slate-950"
                                  title={`围绕第 ${item.item_order} 题问 AI`}
                                  aria-label={`围绕第 ${item.item_order} 题问 AI`}
                                >
                                  <MessageSquareText className="h-4 w-4" />
                                  问AI
                                </button>
                              )}
                              <span className="inline-flex flex-col items-center gap-1">
                                <Bookmark className="h-4 w-4" />
                                标记
                              </span>
                              {isReviewStage && (
                                <span className="inline-flex flex-col items-center gap-1">
                                  <Lightbulb className="h-4 w-4" />
                                  解析
                                </span>
                              )}
                            </div>
                          </aside>

                          <div className="min-w-0 overflow-hidden">
                            <div className="break-words font-serif text-base font-semibold leading-8 text-slate-950 dark:text-slate-100 sm:text-lg [&_p]:mb-0 [&_p]:leading-8 [&_.katex-display]:my-4 [&_.katex]:text-inherit">
                              <ExamMarkdown content={item.stem} />
                            </div>
                          {isChoice ? (
                            <div
                              className="mt-6 grid gap-3"
                              role={isMultipleChoice ? "group" : "radiogroup"}
                              aria-label={`第 ${item.item_order} 题选项`}
                            >
                              {choiceOptions.map((option: string, optionIndex: number) => {
                                const optionLabel = isTrueFalse ? option : getOptionLabel(optionIndex);
                                const optionValue = isTrueFalse ? option : optionLabel;
                                const isSelected = isMultipleChoice
                                  ? selectedMultiChoice.has(optionValue)
                                  : answerValue === optionValue;
                                const isCorrectOption = isMultipleChoice
                                  ? correctMultiChoice.has(optionValue)
                                  : (item.correct_answer ?? "") === optionValue;
                                const isWrongSelectedOption = isReviewStage && isSelected && !isCorrectOption;
                                const isRightOption = isReviewStage && isCorrectOption;
                                return (
                                  <button
                                    key={`${item.id}-${optionIndex}`}
                                    type="button"
                                    role={isMultipleChoice ? "checkbox" : "radio"}
                                    aria-checked={isSelected}
                                    disabled={isReadonly}
                                    onClick={() => {
                                      setAnswers((current) => {
                                        if (!isMultipleChoice) {
                                          return {
                                            ...current,
                                            [item.item_order]: isSelected ? "" : optionValue,
                                          };
                                        }
                                        const next = splitMultiChoiceAnswer(current[item.item_order]);
                                        if (next.has(optionValue)) {
                                          next.delete(optionValue);
                                        } else {
                                          next.add(optionValue);
                                        }
                                        return {
                                          ...current,
                                          [item.item_order]: Array.from(next).sort().join(","),
                                        };
                                      });
                                    }}
                                    className={`flex items-center gap-3 rounded-lg border px-3 py-3 text-left text-sm leading-7 transition sm:gap-4 sm:px-4 sm:py-3.5 sm:text-base ${
                                      isReviewStage
                                        ? isRightOption
                                           ? "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-100"
                                          : isWrongSelectedOption
                                             ? "border-rose-300 bg-rose-50 text-rose-900 dark:border-rose-500/40 dark:bg-rose-500/10 dark:text-rose-100"
                                             : "border-slate-200 bg-white text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400"
                                        : isReadonly
                                          ? isSelected
                                             ? "border-violet-300 bg-violet-50 text-violet-900 shadow-[0_0_0_2px_rgba(139,92,246,0.12)] dark:border-violet-500/45 dark:bg-violet-500/10 dark:text-violet-100 dark:shadow-[0_0_0_2px_rgba(167,139,250,0.16)]"
                                             : "border-slate-200 bg-white text-slate-700 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-300"
                                        : isSelected
                                           ? "border-violet-300 bg-violet-50 text-violet-900 shadow-[0_0_0_2px_rgba(139,92,246,0.12)] dark:border-violet-500/45 dark:bg-violet-500/10 dark:text-violet-100 dark:shadow-[0_0_0_2px_rgba(167,139,250,0.16)]"
                                           : "border-transparent bg-white text-slate-800 hover:border-slate-200 hover:bg-slate-50 dark:bg-slate-900/70 dark:text-slate-200 dark:hover:border-slate-700 dark:hover:bg-slate-900"
                                    } ${isReadonly ? "cursor-default" : ""} disabled:cursor-not-allowed`}
                                  >
                                    <span
                                      className={`grid h-5 w-5 shrink-0 place-items-center border-2 ${isMultipleChoice ? "rounded-[5px]" : "rounded-full"} ${
                                        isReviewStage
                                          ? isRightOption
                                            ? "border-emerald-600 bg-white dark:border-emerald-400 dark:bg-slate-950"
                                            : isWrongSelectedOption
                                              ? "border-rose-600 bg-white dark:border-rose-400 dark:bg-slate-950"
                                              : "border-slate-300 bg-white dark:border-slate-600 dark:bg-slate-950"
                                          : isReadonly
                                            ? isSelected
                                              ? "border-violet-600 bg-white dark:border-violet-400 dark:bg-slate-950"
                                              : "border-slate-400 bg-white dark:border-slate-600 dark:bg-slate-950"
                                          : isSelected
                                            ? "border-violet-600 bg-white dark:border-violet-400 dark:bg-slate-950"
                                            : "border-slate-300 bg-white dark:border-slate-600 dark:bg-slate-950"
                                      }`}
                                    >
                                      <span
                                        className={`${isMultipleChoice ? "h-2.5 w-2.5 rounded-[3px]" : "h-2.5 w-2.5 rounded-full"} ${
                                          isReviewStage
                                            ? isRightOption
                                              ? "bg-emerald-600"
                                              : isWrongSelectedOption
                                                ? "bg-rose-600"
                                                : "bg-transparent"
                                            : isReadonly
                                              ? isSelected
                                                ? "bg-violet-600"
                                                : "bg-transparent"
                                            : isSelected
                                              ? "bg-violet-600"
                                              : "bg-transparent"
                                        }`}
                                      />
                                    </span>
                                    <div className={`min-w-0 flex-1 [&_p]:mb-0 [&_p]:text-sm [&_p]:leading-7 sm:[&_p]:text-base sm:[&_p]:leading-7 [&_.katex-display]:my-3 [&_.katex]:text-inherit ${
                                      isReviewStage
                                        ? isRightOption
                                          ? "[&_p]:text-emerald-900 dark:[&_p]:text-emerald-100"
                                          : isWrongSelectedOption
                                            ? "[&_p]:text-rose-900 dark:[&_p]:text-rose-100"
                                            : "[&_p]:text-slate-500 dark:[&_p]:text-slate-400"
                                        : isReadonly
                                          ? isSelected
                                            ? "[&_p]:text-violet-900 dark:[&_p]:text-violet-100"
                                            : "[&_p]:text-slate-700 dark:[&_p]:text-slate-300"
                                        : isSelected
                                          ? "[&_p]:text-violet-900 dark:[&_p]:text-violet-100"
                                          : "[&_p]:text-slate-800 dark:[&_p]:text-slate-200"
                                    }`}>
                                      <div className="flex gap-3">
                                        {!isTrueFalse && (
                                          <span className="shrink-0 font-semibold">{optionLabel}.</span>
                                        )}
                                        <div className="min-w-0 flex-1">
                                          <ExamMarkdown content={option} />
                                        </div>
                                      </div>
                                    </div>
                                  </button>
                                );
                              })}
                            </div>
                          ) : (
                            <div className="mt-6 min-w-0">
                              <textarea
                                className={`min-h-32 w-full max-w-full rounded-lg border px-4 py-3 text-base leading-8 outline-none transition ${
                                  isReviewStage
                                    ? isCorrect
                                      ? "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-100"
                                      : "border-rose-300 bg-rose-50 text-rose-900 dark:border-rose-500/40 dark:bg-rose-500/10 dark:text-rose-100"
                                    : isReadonly
                                      ? "border-slate-200 bg-slate-50 text-slate-900 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-300"
                                    : "border-slate-200 bg-white text-slate-900 focus:border-violet-300 focus:ring-2 focus:ring-violet-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-violet-500/60 dark:focus:ring-violet-500/20"
                                }`}
                                placeholder={item.question_type === "fill_blank" ? "填写答案" : "输入你的作答"}
                                value={answerValue}
                                onChange={(event) =>
                                  setAnswers((current) => ({ ...current, [item.item_order]: event.target.value }))
                                }
                                disabled={isReadonly}
                              />
                            </div>
                          )}
                        </div>

                        {isReviewStage && showInlineReviewDetails && (
                          <div className="mt-6 border-t border-dashed border-slate-200 pt-5 text-sm leading-7 text-slate-600 dark:border-slate-800 dark:text-slate-300 md:col-start-2">
                            <div className="[&_p]:mb-2 [&_.katex-display]:my-3">
                              <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">你的答案</p>
                              <ExamMarkdown content={item.user_answer || "未作答"} />
                            </div>
                            <div className="mt-3 [&_p]:mb-2 [&_.katex-display]:my-3">
                              <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">正确答案</p>
                              <ExamMarkdown content={item.correct_answer || "无标准答案"} />
                            </div>
                            <div className="mt-3 [&_p]:mb-2 [&_.katex-display]:my-3">
                              <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">解析</p>
                              <ExamMarkdown content={item.explanation || "暂无解析"} />
                            </div>
                            <div className="mt-4 flex items-center gap-2 border-t border-slate-200 pt-4 dark:border-slate-800">
                              <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">结果</span>
                              <span className={item.is_correct ? "font-medium text-emerald-700 dark:text-emerald-300" : "font-medium text-rose-700 dark:text-rose-300"}>
                                {item.is_correct ? "正确" : "需要继续巩固"}
                              </span>
                            </div>
                          </div>
                        )}
                        </div>
                      </div>
                    );
                      })}
                    </div>
                    <div className="border-t border-slate-200 px-6 py-5 text-center font-serif text-base font-semibold text-slate-500 dark:border-slate-800 dark:text-slate-400">
                      第 1 / 1 页 · 已作答 {getAnsweredCount(paper, answers)} / {paper.total_items} 题
                    </div>
                  </article>
                </div>
  );
}
