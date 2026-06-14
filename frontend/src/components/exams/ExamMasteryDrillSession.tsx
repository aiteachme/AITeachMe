import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Bookmark,
  CheckCircle2,
  Loader2,
  MessageSquareText,
  RotateCcw,
  Trophy,
  XCircle,
} from "lucide-react";

import type { ExamPaperDetailResponse, ExamPaperItemResponse } from "../../api/generated/model";
import { cn } from "../../lib/utils";
import { Button } from "../ui/Button";
import { ExamMarkdown } from "./ExamMarkdown";
import {
  formatAnswerDisplayValue,
  formatQuestionTypeLabel,
  formatTrueFalseOptionLabel,
  getOptionLabel,
  splitMultiChoiceAnswer,
} from "./examDisplay";
import { isAiGradedQuestionType, type QuestionTemplateGradeResult } from "./questionTemplateGrading";

export interface MasteryDrillCompletionSummary {
  totalAttemptCount: number;
  wrongAttemptCount: number;
}

interface ExamMasteryDrillSessionProps {
  paper: ExamPaperDetailResponse;
  answers: Record<number, string>;
  setAnswers: Dispatch<SetStateAction<Record<number, string>>>;
  isCompleting: boolean;
  onComplete: (finalAnswers: Record<number, string>, summary: MasteryDrillCompletionSummary) => void;
  onBack?: () => void;
  onRestart?: () => void;
  completionDescription?: string;
  onGradeSubjectiveAnswer?: (item: ExamPaperItemResponse, answer: string) => Promise<QuestionTemplateGradeResult>;
  onQuestionAi?: (item: ExamPaperItemResponse, isReviewStage: boolean, answerValue: string) => void;
  onQuestionMarkToggle?: (item: ExamPaperItemResponse, isMarked: boolean) => void;
  markingQuestionTemplateId?: number | null;
}

interface DrillFeedback {
  itemId: number;
  answer: string;
  isCorrect: boolean;
  feedbackText?: string | null;
  scoreObtained?: number | null;
  scoreMax?: number | null;
  errorCauseLabel?: string | null;
  gradingMode?: string | null;
}

interface AttemptStats {
  attempts: number;
  wrong: number;
  correct: boolean;
}

function normalizeTextAnswer(value?: string | null) {
  return String(value ?? "")
    .replace(/[，、；;]/g, ",")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function normalizeTrueFalseAnswer(value?: string | null) {
  const normalized = normalizeTextAnswer(value);
  if (["true", "t", "yes", "y", "正确", "对", "是"].includes(normalized)) return "true";
  if (["false", "f", "no", "n", "错误", "错", "否"].includes(normalized)) return "false";
  return normalized;
}

function getChoiceOptions(item: ExamPaperItemResponse) {
  if (item.question_type === "true_false" && !(item.options?.length)) {
    return ["True", "False"];
  }
  return item.options ?? [];
}

function isAnswerCorrect(item: ExamPaperItemResponse, answer: string) {
  const questionType = item.question_type;
  if (questionType === "multiple_choice" || questionType === "multi_choice") {
    const expected = splitMultiChoiceAnswer(item.correct_answer);
    const actual = splitMultiChoiceAnswer(answer);
    if (!expected.size || expected.size !== actual.size) return false;
    return Array.from(expected).every((value) => actual.has(value));
  }
  if (questionType === "true_false") {
    return normalizeTrueFalseAnswer(item.correct_answer) === normalizeTrueFalseAnswer(answer);
  }
  return normalizeTextAnswer(item.correct_answer) === normalizeTextAnswer(answer);
}

function formatAnswerForDisplay(questionType: string, value?: string | null) {
  return formatAnswerDisplayValue(questionType, value);
}

function DrillAnswerBlock({ title, content }: { title: string; content: string }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-950/80">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">{title}</p>
      <div className="mt-2 font-serif text-base leading-8 text-slate-700 dark:text-slate-300 sm:text-lg [&_p]:mb-1 [&_p]:leading-8 [&_.katex-display]:my-3 [&_.katex]:text-inherit">
        <ExamMarkdown content={content} />
      </div>
    </section>
  );
}

export function ExamMasteryDrillSession({
  paper,
  answers,
  setAnswers,
  isCompleting,
  onComplete,
  onBack,
  onRestart,
  completionDescription = "本轮闯关已完成，训练记录会同步到历史记录。",
  onGradeSubjectiveAnswer,
  onQuestionAi,
  onQuestionMarkToggle,
  markingQuestionTemplateId,
}: ExamMasteryDrillSessionProps) {
  const orderedItems = useMemo(
    () => [...(paper.items ?? [])].sort((left, right) => left.item_order - right.item_order),
    [paper.items],
  );
  const orderedItemIds = useMemo(() => orderedItems.map((item) => item.id), [orderedItems]);
  const itemIdsKey = orderedItemIds.join(",");
  const itemById = useMemo(
    () => new Map(orderedItems.map((item) => [item.id, item])),
    [orderedItems],
  );
  const [queue, setQueue] = useState<number[]>(orderedItemIds);
  const [completedIds, setCompletedIds] = useState<Set<number>>(() => new Set());
  const [attemptStats, setAttemptStats] = useState<Record<number, AttemptStats>>({});
  const [feedback, setFeedback] = useState<DrillFeedback | null>(null);
  const [checkingItemId, setCheckingItemId] = useState<number | null>(null);

  useEffect(() => {
    setQueue(orderedItemIds);
    setCompletedIds(new Set());
    setAttemptStats({});
    setFeedback(null);
    setCheckingItemId(null);
  }, [paper.id, itemIdsKey]);

  const currentItem = queue.length ? itemById.get(queue[0]) ?? null : null;
  const answerValue = currentItem ? answers[currentItem.item_order] ?? "" : "";
  const completedCount = completedIds.size;
  const wrongAttemptCount = Object.values(attemptStats).reduce((total, item) => total + item.wrong, 0);
  const isCurrentAnswered = answerValue.trim().length > 0;
  const isCheckingAnswer = currentItem ? checkingItemId === currentItem.id : false;

  const setCurrentAnswer = (item: ExamPaperItemResponse, value: string) => {
    setAnswers((current) => ({ ...current, [item.item_order]: value }));
  };

  const handleCheckAnswer = async () => {
    if (!currentItem || feedback || !isCurrentAnswered || isCheckingAnswer) return;
    const submittedAnswer = answerValue.trim();
    setCheckingItemId(currentItem.id);
    let gradeResult: Partial<QuestionTemplateGradeResult> | null = null;
    try {
      gradeResult = isAiGradedQuestionType(currentItem.question_type) && onGradeSubjectiveAnswer
        ? await onGradeSubjectiveAnswer(currentItem, submittedAnswer)
        : { is_correct: isAnswerCorrect(currentItem, submittedAnswer) };
    } catch {
      return;
    } finally {
      setCheckingItemId((current) => (current === currentItem.id ? null : current));
    }
    const isCorrect = gradeResult.is_correct === true;
    setAttemptStats((current) => {
      const previous = current[currentItem.id] ?? { attempts: 0, wrong: 0, correct: false };
      return {
        ...current,
        [currentItem.id]: {
          attempts: previous.attempts + 1,
          wrong: previous.wrong + (isCorrect ? 0 : 1),
          correct: previous.correct || isCorrect,
        },
      };
    });
    setFeedback({
      itemId: currentItem.id,
      answer: submittedAnswer,
      isCorrect,
      feedbackText: gradeResult.feedback_text,
      scoreObtained: gradeResult.score_obtained,
      scoreMax: gradeResult.score_max,
      errorCauseLabel: gradeResult.error_cause_label,
      gradingMode: gradeResult.grading_mode,
    });
  };

  const handleContinue = () => {
    if (!currentItem || !feedback || feedback.itemId !== currentItem.id) return;
    const remainingQueue = queue.slice(1);
    if (feedback.isCorrect) {
      const finalAnswers = {
        ...answers,
        [currentItem.item_order]: feedback.answer,
      };
      const finalAttemptStats = {
        ...attemptStats,
        [currentItem.id]: {
          attempts: Math.max(1, attemptStats[currentItem.id]?.attempts ?? 0),
          wrong: attemptStats[currentItem.id]?.wrong ?? 0,
          correct: true,
        },
      };
      setCompletedIds((current) => new Set([...current, currentItem.id]));
      setQueue(remainingQueue);
      setFeedback(null);
      if (remainingQueue.length === 0) {
        onComplete(finalAnswers, {
          totalAttemptCount: Object.values(finalAttemptStats).reduce((total, item) => total + item.attempts, 0),
          wrongAttemptCount: Object.values(finalAttemptStats).reduce((total, item) => total + item.wrong, 0),
        });
      }
      return;
    }

    setAnswers((current) => ({ ...current, [currentItem.item_order]: "" }));
    setQueue([...remainingQueue, currentItem.id]);
    setFeedback(null);
  };

  if (!orderedItems.length) {
    return (
      <div className="rounded-[28px] border border-slate-200 bg-white px-6 py-12 text-center text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-950/80 dark:text-slate-400">
        这份闯关训练还没有可作答题目。
      </div>
    );
  }

  if (!currentItem) {
    return (
      <div className="mx-auto max-w-3xl rounded-[28px] border border-emerald-200 bg-emerald-50 px-6 py-12 text-center text-emerald-900 shadow-sm dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-100">
        <Trophy className="mx-auto h-12 w-12" />
        <h2 className="mt-4 text-2xl font-semibold">{orderedItems.length} 题全部答对</h2>
        <p className="mt-3 text-sm leading-7 text-emerald-800 dark:text-emerald-200">
          {isCompleting ? "正在保存本次训练记录..." : completionDescription}
        </p>
        {isCompleting ? <Loader2 className="mx-auto mt-5 h-5 w-5 animate-spin" /> : null}
        {!isCompleting && onRestart ? (
          <Button
            className="mt-6 h-11 rounded-full bg-emerald-950 px-5 text-sm font-semibold text-white hover:bg-emerald-900 dark:bg-emerald-100 dark:text-emerald-950 dark:hover:bg-white"
            onClick={onRestart}
          >
            <RotateCcw className="h-4 w-4" />
            再来一轮
          </Button>
        ) : null}
      </div>
    );
  }

  const isMultipleChoice = currentItem.question_type === "multiple_choice" || currentItem.question_type === "multi_choice";
  const isTrueFalse = currentItem.question_type === "true_false";
  const choiceOptions = getChoiceOptions(currentItem);
  const selectedMultiChoice = splitMultiChoiceAnswer(answerValue);
  const activeFeedback = feedback?.itemId === currentItem.id ? feedback : null;
  const hasFeedback = Boolean(activeFeedback);
  const displayedCompletedCount = Math.min(
    orderedItems.length,
    completedCount + (activeFeedback?.isCorrect ? 1 : 0),
  );
  const displayedRemainingCount = Math.max(0, orderedItems.length - displayedCompletedCount);
  const progressPercent = Math.round((displayedCompletedCount / orderedItems.length) * 100);
  const isMarked = currentItem.is_marked === true;
  const isMarking = markingQuestionTemplateId === currentItem.question_template_id;

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <header className="rounded-[24px] border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-950/88">
        {onBack ? (
          <button
            type="button"
            onClick={onBack}
            className="mb-4 inline-flex items-center gap-2 text-sm font-medium text-slate-500 transition hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
          >
            <ArrowLeft className="h-4 w-4" />
            返回训练中心
          </button>
        ) : null}
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">闯关训练</p>
            <h1 className="mt-2 text-2xl font-semibold text-slate-950 dark:text-slate-100">
              已通过 {displayedCompletedCount} / {orderedItems.length}
            </h1>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              当前第 {Math.min(completedCount + 1, orderedItems.length)} 题
            </p>
          </div>
          <div className="grid grid-cols-3 gap-2 text-center text-xs text-slate-500 dark:text-slate-400">
            <div className="rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-900">
              <div className="text-base font-semibold text-slate-950 dark:text-slate-100">{displayedCompletedCount}</div>
              已通过
            </div>
            <div className="rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-900">
              <div className="text-base font-semibold text-slate-950 dark:text-slate-100">{displayedRemainingCount}</div>
              待通过
            </div>
            <div className="rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-900">
              <div className="text-base font-semibold text-rose-600 dark:text-rose-300">{wrongAttemptCount}</div>
              回炉
            </div>
          </div>
        </div>
        <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
          <div
            className="h-full rounded-full bg-slate-950 transition-all dark:bg-slate-100"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </header>

      <article className="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-[0_24px_60px_rgba(15,23,42,0.1)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_28px_76px_-34px_rgba(0,0,0,0.9)]">
        <div className="grid gap-5 px-5 py-6 sm:px-7 sm:py-8">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-4 dark:border-slate-800">
            <div className="flex items-center gap-3">
              <span className="grid h-10 w-10 place-items-center rounded-xl bg-slate-950 text-base font-semibold text-white dark:bg-slate-100 dark:text-slate-950">
                {currentItem.item_order}
              </span>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                {formatQuestionTypeLabel(currentItem.question_type)}
              </span>
            </div>
            <div className="flex items-center gap-3">
              {onQuestionAi ? (
                <button
                  type="button"
                  onClick={() => onQuestionAi(currentItem, Boolean(hasFeedback), answerValue)}
                  className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-xs font-semibold text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-900 dark:hover:text-slate-100"
                >
                  <MessageSquareText className="h-4 w-4" />
                  问 AI
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => onQuestionMarkToggle?.(currentItem, !isMarked)}
                disabled={!onQuestionMarkToggle || isMarking}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-xs font-semibold transition",
                  isMarked
                    ? "bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100"
                    : "text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-900 dark:hover:text-slate-100",
                  (!onQuestionMarkToggle || isMarking) && "cursor-default opacity-70",
                )}
              >
                <Bookmark className={cn("h-4 w-4", isMarked && "fill-current")} />
                {isMarked ? "已标记" : "标记"}
              </button>
            </div>
          </div>

          <div className="break-words font-serif text-base font-semibold leading-8 text-slate-950 dark:text-slate-100 sm:text-lg [&_p]:mb-0 [&_p]:leading-8 [&_.katex-display]:my-4 [&_.katex]:text-inherit">
            <ExamMarkdown content={currentItem.stem} />
          </div>

          {choiceOptions.length > 0 ? (
            <div className="grid gap-3" role={isMultipleChoice ? "group" : "radiogroup"} aria-label="闯关训练选项">
              {choiceOptions.map((option, optionIndex) => {
                const optionLabel = isTrueFalse ? option : getOptionLabel(optionIndex);
                const optionValue = isTrueFalse ? option : optionLabel;
                const optionDisplay = isTrueFalse ? formatTrueFalseOptionLabel(option) : option;
                const isSelected = isMultipleChoice
                  ? selectedMultiChoice.has(optionValue)
                  : answerValue === optionValue;
                const isCorrectOption = isMultipleChoice
                  ? splitMultiChoiceAnswer(currentItem.correct_answer).has(optionValue)
                  : normalizeTextAnswer(currentItem.correct_answer) === normalizeTextAnswer(optionValue);
                const showCorrect = hasFeedback && isCorrectOption;
                const showWrong = hasFeedback && isSelected && !isCorrectOption;

                return (
                  <button
                    key={`${currentItem.id}-${optionIndex}`}
                    type="button"
                    role={isMultipleChoice ? "checkbox" : "radio"}
                    aria-checked={isSelected}
                    disabled={Boolean(hasFeedback) || isCompleting || isCheckingAnswer}
                    onClick={() => {
                      if (!isMultipleChoice) {
                        setCurrentAnswer(currentItem, isSelected ? "" : optionValue);
                        return;
                      }
                      const next = splitMultiChoiceAnswer(answerValue);
                      if (next.has(optionValue)) {
                        next.delete(optionValue);
                      } else {
                        next.add(optionValue);
                      }
                      setCurrentAnswer(currentItem, Array.from(next).sort().join(","));
                    }}
                    className={cn(
                      "flex items-center gap-3 rounded-lg border px-3 py-3 text-left font-serif text-base leading-8 transition sm:gap-4 sm:px-4 sm:py-3.5 sm:text-lg",
                      showCorrect
                        ? "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-100"
                        : showWrong
                          ? "border-rose-300 bg-rose-50 text-rose-900 dark:border-rose-500/40 dark:bg-rose-500/10 dark:text-rose-100"
                          : isSelected
                            ? "border-transparent bg-indigo-50 text-indigo-900 dark:bg-indigo-500/10 dark:text-indigo-100"
                            : "border-slate-200 bg-white text-slate-800 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-200 dark:hover:bg-slate-900",
                      hasFeedback && "cursor-default",
                    )}
                  >
                    <span
                      className={cn(
                        "relative h-5 w-5 shrink-0 border-2 bg-white dark:bg-slate-950",
                        isMultipleChoice ? "rounded-[5px]" : "rounded-full",
                        showCorrect
                          ? "border-emerald-600 dark:border-emerald-400"
                          : showWrong
                            ? "border-rose-600 dark:border-rose-400"
                            : isSelected
                              ? "border-indigo-600 dark:border-indigo-400"
                              : "border-slate-300 dark:border-slate-600",
                      )}
                    >
                      <span
                        className={cn(
                          "absolute left-1/2 top-1/2 block h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2",
                          isMultipleChoice ? "rounded-[3px]" : "rounded-full",
                          showCorrect
                            ? "bg-emerald-600"
                            : showWrong
                              ? "bg-rose-600"
                              : isSelected
                                ? "bg-indigo-600"
                                : "bg-transparent",
                        )}
                      />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex gap-3">
                        {!isTrueFalse ? <span className="shrink-0 font-semibold">{optionLabel}.</span> : null}
                        <div className="min-w-0 flex-1 [&_p]:mb-0 [&_p]:text-base [&_p]:leading-8 sm:[&_p]:text-lg sm:[&_p]:leading-8 [&_.katex]:text-inherit">
                          <ExamMarkdown content={optionDisplay} />
                        </div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          ) : (
            <textarea
              className="min-h-32 w-full rounded-lg border border-slate-200 bg-white px-4 py-3 font-serif text-base leading-8 text-slate-900 outline-none transition focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-indigo-500/60 dark:focus:ring-indigo-500/20 dark:disabled:bg-slate-900/70 sm:text-lg"
              placeholder="输入你的作答"
              value={answerValue}
              disabled={Boolean(hasFeedback) || isCompleting || isCheckingAnswer}
              onChange={(event) => setCurrentAnswer(currentItem, event.target.value)}
            />
          )}

          {activeFeedback ? (
            <section
              className={cn(
                "rounded-[18px] border px-4 py-4",
                activeFeedback.isCorrect
                  ? "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-100"
                  : "border-rose-200 bg-rose-50 text-rose-900 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-100",
              )}
            >
              <div className="flex items-start gap-3">
                {activeFeedback.isCorrect ? (
                  <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0" />
                ) : (
                  <XCircle className="mt-0.5 h-5 w-5 shrink-0" />
                )}
                <div className="min-w-0 flex-1">
                  <h2 className="font-semibold">{activeFeedback.isCorrect ? "答对了" : "答错了，稍后再来一次"}</h2>
                  <p className="mt-1 text-sm leading-6 opacity-85">
                    {activeFeedback.isCorrect ? "这题已通过，会进入下一题。" : "这题会回到队列末尾，直到你答对为止。"}
                  </p>
                </div>
              </div>
              <div className="mt-4 grid gap-3">
                <DrillAnswerBlock title="你的答案" content={formatAnswerForDisplay(currentItem.question_type, activeFeedback.answer)} />
                <DrillAnswerBlock title="正确答案" content={formatAnswerForDisplay(currentItem.question_type, currentItem.correct_answer)} />
                {activeFeedback.feedbackText ? (
                  <DrillAnswerBlock title="判题反馈" content={activeFeedback.feedbackText} />
                ) : null}
                <DrillAnswerBlock title="解析" content={currentItem.explanation || "暂无解析"} />
              </div>
            </section>
          ) : null}
        </div>

        <footer className="flex flex-col gap-3 border-t border-slate-100 px-5 py-5 dark:border-slate-800 sm:flex-row sm:items-center sm:justify-between sm:px-7">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {hasFeedback ? "看完解析后继续。" : isMultipleChoice ? "多选题选完所有答案后再检查。" : "选择答案后立即检查。"}
          </p>
          {activeFeedback ? (
            <Button
              className="h-12 rounded-full bg-black px-6 text-sm font-semibold dark:bg-slate-100 dark:text-slate-900"
              onClick={handleContinue}
              disabled={isCompleting}
            >
              {activeFeedback.isCorrect ? <ArrowRight className="h-4 w-4" /> : <RotateCcw className="h-4 w-4" />}
              {activeFeedback.isCorrect ? (queue.length === 1 ? "完成训练" : "下一题") : "重新入队"}
            </Button>
          ) : (
            <Button
              className="h-12 rounded-full bg-black px-6 text-sm font-semibold dark:bg-slate-100 dark:text-slate-900"
              onClick={handleCheckAnswer}
              disabled={!isCurrentAnswered || isCompleting || isCheckingAnswer}
            >
              {isCheckingAnswer ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {isCheckingAnswer ? "AI 判题中" : "检查答案"}
            </Button>
          )}
        </footer>
      </article>
    </div>
  );
}
