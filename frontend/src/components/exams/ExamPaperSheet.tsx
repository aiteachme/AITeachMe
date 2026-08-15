import type { Dispatch, ReactNode, SetStateAction } from "react";
import { AlertTriangle, Bookmark, Lightbulb, MessageSquareText } from "lucide-react";

import type { ExamPaperDetailResponse, ExamPaperItemResponse, PaperPreviewRow } from "../../api/generated/model";
import { cn } from "../../lib/utils";
import {
  EXAM_ANSWER_TEXT_CLASS,
  EXAM_OPTION_BUTTON_TEXT_CLASS,
  EXAM_OPTION_MARKDOWN_CLASS,
  EXAM_QUESTION_TEXT_CLASS,
  EXAM_TEXTAREA_TEXT_CLASS,
  ExamMarkdown,
} from "./ExamMarkdown";
import { PaperExamCanvasSheet } from "./PaperExamCanvasSheet";
import { isSupportedQuestionType } from "./questionTypes";
import { buildExamQuestionAnchorId } from "../interaction";
import {
  formatAnswerDisplayValue,
  formatQuestionTypeLabel,
  formatTrueFalseOptionLabel,
  getAnsweredCount,
  getEstimatedExamMinutes,
  getExamPaperDisplayTitle,
  getExamTotalScore,
  getOptionLabel,
  isTrueFalseAnswerMatch,
  isTrueFalsePositive,
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
  isReviewAnalysisVisible?: boolean;
  footerContent?: ReactNode;
  onSelectQuestion?: (item: ExamPaperItemResponse) => void;
  onReviewAnalysisToggle?: (item: ExamPaperItemResponse) => void;
  onQuestionAi?: (item: ExamPaperItemResponse, isReviewStage: boolean, answerValue: string) => void;
  onQuestionMarkToggle?: (item: ExamPaperItemResponse, isMarked: boolean) => void;
  markingQuestionTemplateIds?: ReadonlySet<number>;
  activeAiAnchorId?: string | null;
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
      <div className="min-w-0 overflow-hidden">
        <div className="mb-4 flex items-center gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-sans text-lg font-bold text-slate-800 dark:text-slate-200">
              {row.order}.
            </span>
            {isFailed ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-rose-50 px-2 py-0.5 text-xs font-semibold text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">
                <AlertTriangle className="h-3.5 w-3.5" />
                生成失败
              </span>
            ) : (
              <span className="inline-flex items-center rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                {formatQuestionTypeLabel(row.type)}
              </span>
            )}
            <span className="text-slate-200 dark:text-slate-800 select-none">|</span>
            <div className="flex items-center gap-3 text-xs font-semibold text-slate-300">
              <span className="inline-flex items-center gap-1.5 px-2 py-1">
                <Bookmark className="h-4 w-4" />
                <span>标记</span>
              </span>
            </div>
          </div>
        </div>

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
  );
}

function getQuestionResultMarkJitter(item: ExamPaperItemResponse) {
  const seed = item.item_order * 37 + item.question_type.length * 11 + item.difficulty.length * 7;
  return {
    x: [-6, -4, -2, 0, 2, 4][seed % 6],
    y: [-8, -5, -2, 2, 5, 8][Math.floor(seed / 5) % 6],
    rotate: [-11, -7, -3, 4, 8, 12][Math.floor(seed / 11) % 6],
  };
}

function QuestionReviewResultMark({ item }: { item: ExamPaperItemResponse }) {
  const isCorrect = item.is_correct === true;
  const jitter = getQuestionResultMarkJitter(item);
  const style = {
    transform: `translate(${jitter.x}px, calc(-50% + ${jitter.y}px)) rotate(${jitter.rotate}deg)`,
  };

  return (
    <span
      className={cn(
        "pointer-events-none absolute -right-1 top-12 z-20 grid h-16 w-16 select-none place-items-center sm:right-1 lg:right-3",
        isCorrect ? "text-emerald-600/85" : "text-rose-600/85",
      )}
      style={style}
      aria-hidden="true"
    >
      <svg
        className="h-full w-full overflow-visible drop-shadow-[0_1px_0_rgba(255,255,255,0.5)]"
        viewBox="0 0 96 96"
        role="presentation"
      >
        {isCorrect ? (
          <g fill="currentColor">
            <path d="M12 53 C16 48 20 48 25 52 C31 57 35 62 40 66 C51 45 65 26 84 10 C89 6 92 8 88 14 C71 33 58 50 47 72 C44 77 40 79 36 75 C29 69 22 62 14 57 C11 55 10 55 12 53 Z" />
            <path
              d="M17 51 C23 54 31 61 38 68 C49 49 62 31 80 15"
              fill="none"
              stroke="rgba(255,255,255,0.34)"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="3"
            />
            <path
              d="M23 58 C29 62 34 68 39 72"
              fill="none"
              stroke="currentColor"
              strokeLinecap="round"
              strokeWidth="2.2"
              opacity="0.38"
            />
          </g>
        ) : (
          <g fill="currentColor">
            <path d="M18 17 C20 13 24 13 29 18 C42 30 55 44 76 68 C81 74 78 80 72 76 C53 61 38 45 20 26 C16 22 15 19 18 17 Z" />
            <path d="M73 15 C78 12 82 16 78 22 C64 41 47 58 23 78 C18 82 14 78 18 73 C31 55 50 36 73 15 Z" />
            <path
              d="M26 23 C39 36 52 50 70 70"
              fill="none"
              stroke="rgba(255,255,255,0.28)"
              strokeLinecap="round"
              strokeWidth="3"
            />
            <path
              d="M72 21 C56 39 39 56 22 74"
              fill="none"
              stroke="rgba(255,255,255,0.24)"
              strokeLinecap="round"
              strokeWidth="2.8"
            />
          </g>
        )}
      </svg>
    </span>
  );
}

function isQuestionMarked(item: ExamPaperItemResponse) {
  return (item as ExamPaperItemResponse & { is_marked?: boolean | null }).is_marked === true;
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
  isReviewAnalysisVisible = true,
  footerContent,
  onSelectQuestion,
  onReviewAnalysisToggle,
  onQuestionAi,
  onQuestionMarkToggle,
  markingQuestionTemplateIds,
  activeAiAnchorId,
}: ExamPaperSheetProps) {
  const items = paper.items ?? [];
  const itemsByOrder = new Map(items.map((item: ExamPaperItemResponse) => [item.item_order, item]));
  const questionEntries = buildQuestionEntries(paper, itemsByOrder);

  if (paper.exam_mode === "paper_exam") {
    return (
      <PaperExamCanvasSheet
        paper={paper}
        answers={answers}
        activeStage={activeStage}
        questionEntries={questionEntries}
        highlightedQuestionOrder={highlightedQuestionOrder}
        setAnswers={setAnswers}
        selectedItemId={selectedItemId}
        showInlineReviewDetails={showInlineReviewDetails}
        isReviewAnalysisVisible={isReviewAnalysisVisible}
        footerContent={footerContent}
        onSelectQuestion={onSelectQuestion}
        onReviewAnalysisToggle={onReviewAnalysisToggle ? () => {} : undefined}
        onQuestionAi={onQuestionAi}
        onQuestionMarkToggle={onQuestionMarkToggle}
        markingQuestionTemplateIds={markingQuestionTemplateIds}
        activeAiAnchorId={activeAiAnchorId}
      />
    );
  }

  return (
                <div
                  className="relative mx-auto w-full max-w-[1040px] pb-12"
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
                  <article className="relative min-h-[1470px] overflow-hidden border border-slate-200 bg-white shadow-[0_26px_70px_rgba(15,23,42,0.15)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_28px_76px_-34px_rgba(0,0,0,0.9)]">
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
                      <div className="mt-8 border-y border-dashed border-slate-300 py-5 text-left font-serif text-sm leading-8 text-slate-700 dark:border-slate-700 dark:text-slate-300 sm:text-base">
                        <p className="font-bold text-slate-800 dark:text-slate-200">注意事项：</p>
                        <p>1. 请在作答区内选择或填写答案，系统会自动保存当前选择。</p>
                        <p>2. 可使用右侧工具调整页面与字体大小；提交前请检查题号导航状态。</p>
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
                    const isReadonly = isGraded || paper.status === "grading_failed";
                    const isCorrect = item.is_correct === true;
                    const isSelectedReviewItem = isReviewStage && selectedItemId === item.id;
                    const isQuestionHighlighted = highlightedQuestionOrder === item.item_order;
                    const isMarked = isQuestionMarked(item);
                    const isMarking = Boolean(
                      item.question_template_id && markingQuestionTemplateIds?.has(item.question_template_id),
                    );

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
                          "group relative scroll-mt-28 border-b border-slate-100 px-0 py-8 transition-[background-color,box-shadow] duration-300 last:border-b-0 dark:border-slate-900 sm:py-10",
                          (isReviewStage || isQuestionHighlighted) && "px-4 sm:px-5 lg:px-6",
                          isReviewStage && "cursor-pointer rounded-xl",
                          isSelectedReviewItem && "bg-slate-50/80 outline outline-1 outline-slate-200 dark:bg-slate-900/70 dark:outline-slate-700",
                          isQuestionHighlighted && "rounded-xl bg-slate-50/80 outline outline-1 outline-slate-200 dark:bg-slate-900/70 dark:outline-slate-700",
                        )}
                        aria-selected={isSelectedReviewItem || undefined}
                      >
                        {isReviewStage ? <QuestionReviewResultMark item={item} /> : null}
                        <div className="w-full">
                          <div className="min-w-0 overflow-hidden">
                            <div className="mb-4 flex items-center gap-4">
                              <div className="flex flex-wrap items-center gap-3">
                                <div className="font-sans text-lg font-bold text-slate-800 dark:text-slate-200">
                                  {item.item_order}.
                                </div>
                                <span className="inline-flex items-center gap-1.5 rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold leading-4 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                                  <span className={cn(
                                    "h-1.5 w-1.5 rounded-full",
                                    isSingleChoice
                                      ? "bg-indigo-500"
                                      : isMultipleChoice
                                        ? "bg-sky-500"
                                        : isTrueFalse
                                          ? "bg-teal-500"
                                          : "bg-slate-500"
                                  )} />
                                  {formatQuestionTypeLabel(item.question_type)}
                                </span>
                                <span className="text-slate-200 dark:text-slate-800 select-none">|</span>

                                <div className={cn(
                                  "flex items-center gap-1.5 text-xs font-semibold transition-opacity duration-300",
                                  (isMarked || (selectedItemId === item.id && isReviewAnalysisVisible))
                                    ? "opacity-100"
                                    : "opacity-40 group-hover:opacity-100 group-focus-within:opacity-100"
                                )}>
                                  {onQuestionAi && (
                                    <button
                                      type="button"
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        onQuestionAi(item, isReviewStage, answerValue);
                                      }}
                                      className={cn(
                                        "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md border transition focus:outline-none",
                                        (activeAiAnchorId === buildExamQuestionAnchorId(paper.id, item.item_order))
                                          ? "border-indigo-200 bg-indigo-50/60 text-indigo-700 hover:bg-indigo-100/60 dark:border-indigo-900/60 dark:bg-indigo-950/30 dark:text-indigo-400"
                                          : "border-transparent text-slate-500 hover:text-slate-800 hover:bg-slate-100 dark:text-slate-400 dark:hover:text-slate-200 dark:hover:bg-slate-900",
                                      )}
                                      title={`围绕第 ${item.item_order} 题问 AI`}
                                      aria-label={`围绕第 ${item.item_order} 题问 AI`}
                                    >
                                      <MessageSquareText className="h-3.5 w-3.5" />
                                      <span>问AI</span>
                                    </button>
                                  )}
                                  <button
                                    type="button"
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      onQuestionMarkToggle?.(item, !isMarked);
                                    }}
                                    disabled={!onQuestionMarkToggle || isMarking}
                                    className={cn(
                                      "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md border transition focus:outline-none",
                                      isMarked
                                        ? "border-amber-200 bg-amber-50/60 text-amber-700 hover:bg-amber-100/60 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-400 font-bold"
                                        : "border-transparent text-slate-500 hover:text-slate-800 hover:bg-slate-100 dark:text-slate-400 dark:hover:text-slate-200 dark:hover:bg-slate-900",
                                      (!onQuestionMarkToggle || isMarking) && "cursor-default opacity-70",
                                    )}
                                    title={isMarked ? `取消标记第 ${item.item_order} 题` : `标记第 ${item.item_order} 题`}
                                    aria-label={isMarked ? `取消标记第 ${item.item_order} 题` : `标记第 ${item.item_order} 题`}
                                    aria-pressed={isMarked}
                                  >
                                    <Bookmark className={cn("h-3.5 w-3.5", isMarked && "fill-current")} />
                                    <span>{isMarked ? "已标记" : "标记"}</span>
                                  </button>
                                  {isReviewStage && (
                                    <button
                                      type="button"
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        onReviewAnalysisToggle?.(item);
                                      }}
                                      className={cn(
                                        "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md border transition focus:outline-none",
                                        (selectedItemId === item.id && isReviewAnalysisVisible)
                                          ? "border-emerald-200 bg-emerald-50/60 text-emerald-700 hover:bg-emerald-100/60 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-400 font-bold"
                                          : "border-transparent text-slate-500 hover:text-slate-800 hover:bg-slate-100 dark:text-slate-400 dark:hover:text-slate-200 dark:hover:bg-slate-900",
                                      )}
                                      title={selectedItemId === item.id && isReviewAnalysisVisible ? "收起右侧解析" : "展开右侧解析"}
                                      aria-label={selectedItemId === item.id && isReviewAnalysisVisible ? "收起右侧解析" : "展开右侧解析"}
                                      aria-pressed={selectedItemId === item.id && isReviewAnalysisVisible}
                                    >
                                      <Lightbulb className="h-3.5 w-3.5" />
                                      <span>解析</span>
                                    </button>
                                  )}
                                </div>
                              </div>
                            </div>
                            <div className={EXAM_QUESTION_TEXT_CLASS}>
                              <ExamMarkdown content={item.stem} />
                            </div>
                          {!isSupportedQuestionType(item.question_type) ? (
                            <div className="mt-6 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200" role="alert">
                              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                              <span>当前版本不支持题型「{item.question_type || "未指定"}」，请重新生成试卷。</span>
                            </div>
                          ) : isChoice ? (
                            <div
                              className={cn(
                                "mt-6 grid gap-3 max-w-[720px]",
                                choiceOptions.every((opt: string) => opt.toString().length < 12)
                                  ? "grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3"
                                  : "grid-cols-1"
                              )}
                              role={isMultipleChoice ? "group" : "radiogroup"}
                              aria-label={`第 ${item.item_order} 题选项`}
                            >
                              {choiceOptions.map((option: string, optionIndex: number) => {
                                const optionLabel = isTrueFalse ? option : getOptionLabel(optionIndex);
                                const optionValue = isTrueFalse ? option : optionLabel;
                                const optionDisplay = isTrueFalse ? formatTrueFalseOptionLabel(option) : option;
                                const isSelected = isMultipleChoice
                                  ? selectedMultiChoice.has(optionValue)
                                  : answerValue === optionValue;
                                const isCorrectOption = isMultipleChoice
                                  ? correctMultiChoice.has(optionValue)
                                  : isTrueFalse
                                    ? isTrueFalseAnswerMatch(item.correct_answer, optionValue)
                                    : (item.correct_answer ?? "") === optionValue;
                                const isWrongSelectedOption = isReviewStage && isSelected && !isCorrectOption;
                                const isRightOption = isReviewStage && isCorrectOption;
                                const innerSymbol = isTrueFalse
                                  ? (isTrueFalsePositive(optionValue) ? "✓" : "✗")
                                  : optionLabel;
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
                                    className={`flex items-center gap-3 rounded-lg border px-4 py-2.5 text-left transition duration-200 sm:gap-4 sm:px-4 sm:py-3 ${EXAM_OPTION_BUTTON_TEXT_CLASS} ${
                                      isReviewStage
                                        ? isRightOption
                                           ? "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-100"
                                          : isWrongSelectedOption
                                             ? "border-rose-300 bg-rose-50 text-rose-900 dark:border-rose-500/40 dark:bg-rose-500/10 dark:text-rose-100"
                                             : "border-slate-200 bg-white text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400"
                                        : isReadonly
                                          ? isSelected
                                             ? "border-indigo-200 bg-indigo-50/50 text-indigo-900 dark:border-indigo-500/30 dark:bg-indigo-500/5 dark:text-indigo-100"
                                             : "border-slate-200 bg-white text-slate-700 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-300"
                                        : isSelected
                                            ? "border-indigo-200 bg-indigo-50/50 text-indigo-900 dark:border-indigo-500/30 dark:bg-indigo-500/5 dark:text-indigo-100"
                                           : "border-slate-100 bg-slate-50/20 text-slate-700 hover:border-slate-200 hover:bg-slate-50 hover:translate-x-0.5 dark:border-slate-800/80 dark:bg-slate-900/40 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:bg-slate-900"
                                    } ${isReadonly ? "cursor-default" : ""} disabled:cursor-not-allowed`}
                                  >
                                    <span
                                      className={cn(
                                        "flex h-6 w-6 shrink-0 items-center justify-center border-2 text-[11px] font-extrabold transition-all duration-200",
                                        isMultipleChoice ? "rounded-md" : "rounded-full",
                                        isReviewStage
                                          ? isRightOption
                                            ? "border-emerald-600 bg-emerald-600 text-white"
                                            : isWrongSelectedOption
                                              ? "border-rose-600 bg-rose-600 text-white"
                                              : "border-slate-300 bg-white text-slate-400 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-500"
                                          : isReadonly
                                            ? isSelected
                                              ? "border-indigo-600 bg-indigo-600 text-white"
                                              : "border-slate-400 bg-white text-slate-400 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-500"
                                            : isSelected
                                              ? "border-indigo-600 bg-indigo-600 text-white"
                                              : "border-slate-300 bg-slate-50 hover:border-slate-400 hover:bg-slate-100 text-slate-500 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-400"
                                      )}
                                    >
                                      {innerSymbol}
                                    </span>
                                    <div className={cn(
                                      EXAM_OPTION_MARKDOWN_CLASS,
                                      isReviewStage
                                        ? isRightOption
                                          ? "[&_p]:text-emerald-900 dark:[&_p]:text-emerald-100"
                                          : isWrongSelectedOption
                                            ? "[&_p]:text-rose-900 dark:[&_p]:text-rose-100"
                                            : "[&_p]:text-slate-500 dark:[&_p]:text-slate-400"
                                        : isReadonly
                                          ? isSelected
                                            ? "[&_p]:text-indigo-900 dark:[&_p]:text-indigo-100"
                                            : "[&_p]:text-slate-700 dark:[&_p]:text-slate-300"
                                          : isSelected
                                            ? "[&_p]:text-indigo-900 dark:[&_p]:text-indigo-100"
                                            : "[&_p]:text-slate-800 dark:[&_p]:text-slate-200",
                                    )}>
                                      <div className="min-w-0 flex-1">
                                        <ExamMarkdown content={optionDisplay} />
                                      </div>
                                    </div>
                                  </button>
                                );
                              })}
                            </div>
                          ) : (
                            <div className="mt-6 min-w-0">
                              <textarea
                                className={`min-h-32 w-full max-w-full rounded-lg border px-4 py-3 outline-none transition ${EXAM_TEXTAREA_TEXT_CLASS} ${
                                  isReviewStage
                                    ? isCorrect
                                      ? "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-100"
                                      : "border-rose-300 bg-rose-50 text-rose-900 dark:border-rose-500/40 dark:bg-rose-500/10 dark:text-rose-100"
                                    : isReadonly
                                      ? "border-slate-200 bg-slate-50 text-slate-900 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-300"
                                    : "border-slate-200 bg-white text-slate-900 focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-indigo-500/60 dark:focus:ring-indigo-500/20"
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
                          <div className="mt-6 border-t border-dashed border-slate-200 pt-5 text-sm leading-7 text-slate-600 dark:border-slate-800 dark:text-slate-300">
                            <div>
                              <p className="mb-2 font-sans text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">你的答案</p>
                              <div className={EXAM_ANSWER_TEXT_CLASS}>
                                <ExamMarkdown content={formatAnswerDisplayValue(item.question_type, item.user_answer)} />
                              </div>
                            </div>
                            <div className="mt-3">
                              <p className="mb-2 font-sans text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">正确答案</p>
                              <div className={EXAM_ANSWER_TEXT_CLASS}>
                                <ExamMarkdown content={formatAnswerDisplayValue(item.question_type, item.correct_answer, "无标准答案")} />
                              </div>
                            </div>
                            <div className="mt-3">
                              <p className="mb-2 font-sans text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">解析</p>
                              <div className={EXAM_ANSWER_TEXT_CLASS}>
                                <ExamMarkdown content={item.explanation || "暂无解析"} />
                              </div>
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
