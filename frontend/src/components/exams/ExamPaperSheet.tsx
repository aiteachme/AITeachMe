import type { Dispatch, SetStateAction } from "react";
import { Bookmark, Lightbulb, MessageSquareText, Tags } from "lucide-react";

import type { ExamPaperDetailResponse, ExamPaperItemResponse, PaperPreviewRow } from "../../api/generated/model";
import { cn } from "../../lib/utils";
import { ExamMarkdown } from "./ExamMarkdown";
import {
  buildKnowledgeLabel,
  formatDifficultyLabel,
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
  const previewRows = paper.paper_preview?.rows ?? [];
  const previewByOrder = new Map(previewRows.map((row) => [row.order, row]));
  const count = Math.max(Number(paper.total_items || 0), previewRows.length, 1);
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

function formatQuestionType(type: string) {
  const normalized = String(type || "").trim();
  if (!normalized || normalized === "pending") return "题型生成中";
  const labels: Record<string, string> = {
    single_choice: "单选题",
    multiple_choice: "多选题",
    multi_choice: "多选题",
    fill_blank: "填空题",
    true_false: "判断题",
    short_answer: "简答题",
    essay: "问答题",
  };
  return labels[normalized] ?? normalized;
}

function GeneratingQuestionPlaceholder({ row }: { row: PaperPreviewRow }) {
  const isChoice = row.shape === "choice" || row.type === "single_choice" || row.type === "multiple_choice";
  return (
    <div
      id={`exam-question-${row.order}`}
      data-question-anchor="true"
      data-question-order={row.order}
      className="exam-preview-unified-flow scroll-mt-28 border-b-[1.5px] border-dashed border-slate-200/90 px-0 py-7 last:border-b-0 sm:py-9"
    >
      <div className="grid min-w-0 gap-5 md:grid-cols-[72px_minmax(0,1fr)]">
        <aside className="flex items-start gap-4 border-b border-slate-100 pb-4 text-slate-500 md:flex-col md:items-center md:border-b-0 md:border-r md:pb-0 md:pr-4">
          <div className="font-serif text-2xl font-bold leading-none text-slate-950">{row.order}.</div>
          <div className="flex flex-wrap gap-2 text-xs font-semibold text-slate-400 md:flex-col md:gap-2">
            <span className="inline-flex flex-col items-center gap-1">
              <Bookmark className="h-4 w-4" />
              标记
            </span>
          </div>
        </aside>

        <div className="min-w-0 overflow-hidden">
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <span className="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
              {formatQuestionType(row.type)}
            </span>
            <span className="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-500">
              {formatDifficultyLabel(row.difficulty)}
            </span>
          </div>

          <div className="relative overflow-hidden rounded-xl border border-slate-200 bg-slate-50/80 p-4">
            <div className="space-y-3">
              <span className="exam-preview-flow-line block h-3 w-11/12 rounded-full" />
              <span className="exam-preview-flow-line block h-3 w-8/12 rounded-full" />
              <span className="exam-preview-flow-line block h-3 w-10/12 rounded-full" />
            </div>
          </div>

          {isChoice ? (
            <div className="mt-6 grid gap-3">
              {[0, 1, 2, 3].map((optionIndex) => (
                <div
                  key={optionIndex}
                  className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-3 py-3 sm:gap-4 sm:px-4 sm:py-3.5"
                >
                  <span className="h-5 w-5 shrink-0 rounded-full border-2 border-slate-300 bg-white" />
                  <span className="exam-preview-flow-line block h-2.5 w-8/12 rounded-full" />
                </div>
              ))}
            </div>
          ) : (
            <div className="mt-6 min-h-32 rounded-lg border border-slate-200 bg-white p-4">
              <span className="exam-preview-flow-line block h-3 w-7/12 rounded-full" />
            </div>
          )}
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
  const showGeneratingPlaceholders = paper.status === "generating" && items.length === 0;
  const generatingRows = showGeneratingPlaceholders ? buildGeneratingRows(paper) : [];

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
                  <div className="absolute -right-5 top-5 bottom-8 hidden w-full border border-slate-200 bg-white shadow-[0_18px_36px_rgba(15,23,42,0.08)] lg:block" />
                  <div className="absolute -right-2 top-2 bottom-4 hidden w-full border border-slate-200 bg-white shadow-[0_14px_30px_rgba(15,23,42,0.06)] lg:block" />
                  <article className="relative overflow-hidden border border-slate-200 bg-white shadow-[0_26px_70px_rgba(15,23,42,0.15)]">
                    <header className="px-6 pb-6 pt-12 text-center sm:px-10 sm:pt-16 lg:px-16">
                      <h1 className="font-serif text-3xl font-bold tracking-[0.08em] text-slate-950 sm:text-4xl">
                        {getExamPaperDisplayTitle(paper)}
                      </h1>
                      <div className="mx-auto mt-5 flex max-w-md items-center justify-center gap-3 text-slate-400">
                        <span className="h-px flex-1 bg-slate-300" />
                        <span className="h-2 w-2 rotate-45 bg-slate-800" />
                        <span className="h-px flex-1 bg-slate-300" />
                      </div>
                      <p className="mt-4 font-serif text-base font-semibold text-slate-600">
                        本试卷共 {paper.total_items} 题，满分 {getExamTotalScore(paper)} 分，预计用时 {getEstimatedExamMinutes(paper)} 分钟
                      </p>
                      <div className="mt-8 border-b border-dashed border-slate-300 pb-5 text-left font-serif text-sm leading-8 text-slate-700 sm:text-base">
                        <p className="font-bold text-slate-800">注意事项：</p>
                        <p>1. 请在作答区内选择或填写答案，系统会自动保存当前选择。</p>
                        <p>2. 可使用右侧工具调整页面与字体大小；提交前请检查左侧题号状态。</p>
                      </div>
                    </header>

                    <div className="px-4 pb-8 sm:px-8 lg:px-14">
                      {showGeneratingPlaceholders
                        ? generatingRows.map((row) => <GeneratingQuestionPlaceholder key={row.order} row={row} />)
                        : items.map((item: ExamPaperItemResponse) => {
                    const answerValue = answers[item.id] ?? "";
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
                          "scroll-mt-28 border-b-[1.5px] border-dashed border-slate-200/90 px-0 py-7 transition-[background-color,box-shadow] duration-300 last:border-b-0 sm:py-9",
                          (isReviewStage || isQuestionHighlighted) && "px-4 sm:px-5 lg:px-6",
                          isReviewStage && "cursor-pointer rounded-xl",
                          isSelectedReviewItem && "bg-slate-50/80 outline outline-1 outline-slate-200",
                          isQuestionHighlighted && "rounded-xl bg-slate-50/80 outline outline-1 outline-slate-200",
                        )}
                        aria-selected={isSelectedReviewItem || undefined}
                      >
                        <div className="grid min-w-0 gap-5 md:grid-cols-[72px_minmax(0,1fr)]">
                          <aside className="flex items-start gap-4 border-b border-slate-100 pb-4 text-slate-500 md:flex-col md:items-center md:border-b-0 md:border-r md:pb-0 md:pr-4">
                            <div className="font-serif text-2xl font-bold leading-none text-slate-950">
                              {item.item_order}.
                            </div>
                            <div className="flex flex-wrap gap-2 text-xs font-semibold text-slate-400 md:flex-col md:gap-2">
                              {onQuestionAi && (
                                <button
                                  type="button"
                                  onClick={() => onQuestionAi(item, isReviewStage, answerValue)}
                                  className="inline-flex min-h-10 min-w-10 flex-col items-center justify-center gap-1 rounded-xl border border-violet-200 bg-violet-50 px-2 text-[11px] font-semibold text-violet-700 shadow-sm transition hover:border-violet-300 hover:bg-violet-100 hover:text-violet-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-300 focus-visible:ring-offset-2 focus-visible:ring-offset-white"
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
                            <div className="break-words font-serif text-base font-semibold leading-8 text-slate-950 sm:text-lg [&_p]:mb-0 [&_p]:leading-8 [&_.katex-display]:my-4 [&_.katex]:text-inherit">
                              <ExamMarkdown content={item.stem} />
                            </div>
                            {isReviewStage && (
                              <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
                                <span className="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-500">
                                  {formatDifficultyLabel(item.difficulty)}
                                </span>
                                <span className="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-500">
                                  {item.question_type}
                                </span>
                                <span className="mx-1 hidden h-4 w-px bg-slate-200 sm:inline-flex" />
                                <span className="inline-flex max-w-full items-start gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 font-semibold text-slate-500">
                                  <Tags className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                                  <span className="min-w-0 break-words">{buildKnowledgeLabel(item)}</span>
                                </span>
                              </div>
                            )}
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
                                            [item.id]: isSelected ? "" : optionValue,
                                          };
                                        }
                                        const next = splitMultiChoiceAnswer(current[item.id]);
                                        if (next.has(optionValue)) {
                                          next.delete(optionValue);
                                        } else {
                                          next.add(optionValue);
                                        }
                                        return {
                                          ...current,
                                          [item.id]: Array.from(next).sort().join(","),
                                        };
                                      });
                                    }}
                                    className={`flex items-center gap-3 rounded-lg border px-3 py-3 text-left text-sm leading-7 transition sm:gap-4 sm:px-4 sm:py-3.5 sm:text-base ${
                                      isReviewStage
                                        ? isRightOption
                                          ? "border-emerald-300 bg-emerald-50 text-emerald-900"
                                          : isWrongSelectedOption
                                            ? "border-rose-300 bg-rose-50 text-rose-900"
                                            : "border-slate-200 bg-white text-slate-500"
                                        : isReadonly
                                          ? isSelected
                                            ? "border-violet-300 bg-violet-50 text-violet-900 shadow-[0_0_0_2px_rgba(139,92,246,0.12)]"
                                            : "border-slate-200 bg-white text-slate-700"
                                        : isSelected
                                          ? "border-violet-300 bg-violet-50 text-violet-900 shadow-[0_0_0_2px_rgba(139,92,246,0.12)]"
                                          : "border-transparent bg-white text-slate-800 hover:border-slate-200 hover:bg-slate-50"
                                    } ${isReadonly ? "cursor-default" : ""} disabled:cursor-not-allowed`}
                                  >
                                    <span
                                      className={`grid h-5 w-5 shrink-0 place-items-center border-2 ${isMultipleChoice ? "rounded-[5px]" : "rounded-full"} ${
                                        isReviewStage
                                          ? isRightOption
                                            ? "border-emerald-600 bg-white"
                                            : isWrongSelectedOption
                                              ? "border-rose-600 bg-white"
                                              : "border-slate-300 bg-white"
                                          : isReadonly
                                            ? isSelected
                                              ? "border-violet-600 bg-white"
                                              : "border-slate-400 bg-white"
                                          : isSelected
                                            ? "border-violet-600 bg-white"
                                            : "border-slate-300 bg-white"
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
                                          ? "[&_p]:text-emerald-900"
                                          : isWrongSelectedOption
                                            ? "[&_p]:text-rose-900"
                                            : "[&_p]:text-slate-500"
                                        : isReadonly
                                          ? isSelected
                                            ? "[&_p]:text-violet-900"
                                            : "[&_p]:text-slate-700"
                                        : isSelected
                                          ? "[&_p]:text-violet-900"
                                          : "[&_p]:text-slate-800"
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
                                      ? "border-emerald-300 bg-emerald-50 text-emerald-900"
                                      : "border-rose-300 bg-rose-50 text-rose-900"
                                    : isReadonly
                                      ? "border-slate-200 bg-slate-50 text-slate-900"
                                    : "border-slate-200 bg-white text-slate-900 focus:border-violet-300 focus:ring-2 focus:ring-violet-100"
                                }`}
                                placeholder={item.question_type === "fill_blank" ? "填写答案" : "输入你的作答"}
                                value={answerValue}
                                onChange={(event) =>
                                  setAnswers((current) => ({ ...current, [item.id]: event.target.value }))
                                }
                                disabled={isReadonly}
                              />
                            </div>
                          )}
                        </div>

                        {isReviewStage && showInlineReviewDetails && (
                          <div className="mt-6 border-t border-dashed border-slate-200 pt-5 text-sm leading-7 text-slate-600 md:col-start-2">
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
                            <div className="mt-4 flex items-center gap-2 border-t border-slate-200 pt-4">
                              <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">结果</span>
                              <span className={item.is_correct ? "font-medium text-emerald-700" : "font-medium text-rose-700"}>
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
                    <div className="border-t border-slate-200 px-6 py-5 text-center font-serif text-base font-semibold text-slate-500">
                      第 1 / 1 页 · 已作答 {getAnsweredCount(paper, answers)} / {paper.total_items} 题
                    </div>
                  </article>
                </div>
  );
}
