import { useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";
import {
  ArrowLeft,
  ArrowRight,
  AlertTriangle,
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
  isTrueFalseAnswerMatch,
  isTrueFalsePositive,
  splitMultiChoiceAnswer,
} from "./examDisplay";
import { isAiGradedQuestionType, type QuestionTemplateGradeResult } from "./questionTemplateGrading";
import { isSupportedQuestionType } from "./questionTypes";

export interface MasteryDrillCompletionSummary {
  totalAttemptCount: number;
  wrongAttemptCount: number;
  wrongQuestionTemplateIds: number[];
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
  onGradeAnswer: (item: ExamPaperItemResponse, answer: string) => Promise<QuestionTemplateGradeResult>;
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

const DRILL_QUESTION_TEXT_CLASS =
  "break-words font-serif text-base font-medium leading-7 text-slate-950 dark:text-slate-100 [&_p]:mb-0 [&_p]:text-base [&_p]:leading-7 [&_.katex-display]:my-3 [&_.katex]:text-inherit";

const DRILL_OPTION_BUTTON_TEXT_CLASS =
  "font-serif text-[15px] leading-7 sm:text-base";

const DRILL_OPTION_MARKDOWN_CLASS =
  "min-w-0 flex-1 [&_p]:mb-0 [&_p]:text-[15px] [&_p]:leading-7 sm:[&_p]:text-base sm:[&_p]:leading-7 [&_.katex-display]:my-2.5 [&_.katex]:text-inherit";

const DRILL_ANSWER_TEXT_CLASS =
  "font-serif text-[15px] leading-7 text-slate-700 dark:text-slate-300 sm:text-base [&_p]:mb-1 [&_p]:text-[15px] [&_p]:leading-7 sm:[&_p]:text-base sm:[&_p]:leading-7 [&_.katex-display]:my-2.5 [&_.katex]:text-inherit";

const DRILL_TEXTAREA_TEXT_CLASS =
  "font-serif text-[15px] leading-7 sm:text-base";

function normalizeTextAnswer(value?: string | null) {
  return String(value ?? "")
    .replace(/[，、；;]/g, ",")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function getChoiceOptions(item: ExamPaperItemResponse) {
  if (item.question_type === "true_false" && !(item.options?.length)) {
    return ["True", "False"];
  }
  return item.options ?? [];
}

function formatAnswerForDisplay(questionType: string, value?: string | null) {
  return formatAnswerDisplayValue(questionType, value);
}

function DrillAnswerBlock({ title, content }: { title: string; content: string }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 dark:border-slate-800 dark:bg-slate-950/80">
      <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">{title}</p>
      <div className={`mt-1.5 ${DRILL_ANSWER_TEXT_CLASS}`}>
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
  onGradeAnswer,
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
  const persistedAttempts = useMemo(
    () => (paper.mastery_drill?.attempts ?? []).filter((attempt) => attempt.status === "graded"),
    [paper.mastery_drill?.attempts],
  );
  const persistedAttemptSignature = persistedAttempts
    .map((attempt) => `${attempt.id}:${attempt.is_correct === true ? 1 : 0}`)
    .join(",");
  const buildPersistedState = () => {
    const stats: Record<number, AttemptStats> = {};
    persistedAttempts.forEach((attempt) => {
      const previous = stats[attempt.exam_paper_item_id] ?? { attempts: 0, wrong: 0, correct: false };
      stats[attempt.exam_paper_item_id] = {
        attempts: previous.attempts + 1,
        wrong: previous.wrong + (attempt.is_correct === true ? 0 : 1),
        correct: previous.correct || attempt.is_correct === true,
      };
    });
    const completed = new Set(
      orderedItems
        .filter((item) => item.is_correct === true || stats[item.id]?.correct === true)
        .map((item) => item.id),
    );
    return {
      stats,
      completed,
      queue: orderedItemIds.filter((itemId) => !completed.has(itemId)),
    };
  };
  const initialPersistedState = buildPersistedState();
  const [queue, setQueue] = useState<number[]>(initialPersistedState.queue);
  const [completedIds, setCompletedIds] = useState<Set<number>>(initialPersistedState.completed);
  const [attemptStats, setAttemptStats] = useState<Record<number, AttemptStats>>(initialPersistedState.stats);
  const [feedback, setFeedback] = useState<DrillFeedback | null>(null);
  const [checkingItemId, setCheckingItemId] = useState<number | null>(null);
  const completionNotifiedPaperIdRef = useRef<number | null>(null);

  useEffect(() => {
    const persisted = buildPersistedState();
    setQueue(persisted.queue);
    setCompletedIds(persisted.completed);
    setAttemptStats(persisted.stats);
    setFeedback(null);
    setCheckingItemId(null);
    completionNotifiedPaperIdRef.current = null;
  }, [paper.id, itemIdsKey, persistedAttemptSignature]);

  const currentItem = queue.length ? itemById.get(queue[0]) ?? null : null;
  const answerValue = currentItem ? answers[currentItem.item_order] ?? "" : "";
  const completedCount = completedIds.size;
  const wrongAttemptCount = Object.values(attemptStats).reduce((total, item) => total + item.wrong, 0);
  const isCurrentAnswered = answerValue.trim().length > 0;
  const isCurrentSupported = currentItem ? isSupportedQuestionType(currentItem.question_type) : false;
  const isCheckingAnswer = currentItem ? checkingItemId === currentItem.id : false;
  const checkingAnswerLabel = currentItem && isAiGradedQuestionType(currentItem.question_type)
    ? "AI 判题中"
    : "判题中";

  const setCurrentAnswer = (item: ExamPaperItemResponse, value: string) => {
    setAnswers((current) => ({ ...current, [item.item_order]: value }));
  };

  const handleCheckAnswer = async () => {
    if (!currentItem || !isCurrentSupported || feedback || !isCurrentAnswered || isCheckingAnswer) return;
    const submittedAnswer = answerValue.trim();
    setCheckingItemId(currentItem.id);
    let gradeResult: Partial<QuestionTemplateGradeResult> | null = null;
    try {
      gradeResult = await onGradeAnswer(currentItem, submittedAnswer);
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
        const wrongQuestionTemplateIds = Object.entries(finalAttemptStats)
          .filter(([, stats]) => stats.wrong > 0)
          .map(([itemId]) => itemById.get(Number(itemId))?.question_template_id)
          .filter((templateId): templateId is number => (
            typeof templateId === "number" && Number.isFinite(templateId) && templateId > 0
          ));
        completionNotifiedPaperIdRef.current = paper.id;
        onComplete(finalAnswers, {
          totalAttemptCount: Object.values(finalAttemptStats).reduce((total, item) => total + item.attempts, 0),
          wrongAttemptCount: Object.values(finalAttemptStats).reduce((total, item) => total + item.wrong, 0),
          wrongQuestionTemplateIds,
        });
      }
      return;
    }

    setAnswers((current) => ({ ...current, [currentItem.item_order]: "" }));
    setQueue([...remainingQueue, currentItem.id]);
    setFeedback(null);
  };

  useEffect(() => {
    if (
      orderedItems.length === 0 ||
      queue.length > 0 ||
      completedIds.size !== orderedItems.length ||
      completionNotifiedPaperIdRef.current === paper.id
    ) {
      return;
    }
    completionNotifiedPaperIdRef.current = paper.id;
    const wrongQuestionTemplateIds = Object.entries(attemptStats)
      .filter(([, stats]) => stats.wrong > 0)
      .map(([itemId]) => itemById.get(Number(itemId))?.question_template_id)
      .filter((templateId): templateId is number => (
        typeof templateId === "number" && Number.isFinite(templateId) && templateId > 0
      ));
    onComplete(answers, {
      totalAttemptCount: Object.values(attemptStats).reduce((total, item) => total + item.attempts, 0),
      wrongAttemptCount: Object.values(attemptStats).reduce((total, item) => total + item.wrong, 0),
      wrongQuestionTemplateIds,
    });
  }, [answers, attemptStats, completedIds, itemById, onComplete, orderedItems.length, paper.id, queue.length]);

  if (!orderedItems.length) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-12 text-center text-sm text-slate-500 shadow-sm dark:border-slate-800 dark:bg-slate-950/80 dark:text-slate-400">
        这份闯关训练还没有可作答题目。
      </div>
    );
  }

  if (!currentItem) {
    return (
      <div className="mx-auto w-full max-w-5xl rounded-2xl border border-emerald-200 bg-emerald-50 px-6 py-10 text-center text-emerald-900 shadow-sm dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-100">
        <Trophy className="mx-auto h-10 w-10" />
        <h2 className="mt-3 text-xl font-semibold">{orderedItems.length} 题全部答对</h2>
        <p className="mt-2 text-sm leading-6 text-emerald-800 dark:text-emerald-200">
          {isCompleting ? "正在保存本次训练记录..." : completionDescription}
        </p>
        {isCompleting ? <Loader2 className="mx-auto mt-4 h-5 w-5 animate-spin" /> : null}
        {!isCompleting && onRestart ? (
          <Button
            className="mt-5 h-10 rounded-full bg-emerald-950 px-5 text-sm font-semibold text-white hover:bg-emerald-900 dark:bg-emerald-100 dark:text-emerald-950 dark:hover:bg-white"
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

  const footerHint = useMemo(() => {
    if (activeFeedback) {
      return activeFeedback.isCorrect
        ? "回答正确！请阅读解析并点击“下一题”继续。"
        : "回答错误。点击“重新入队”可稍后再次挑战该题。";
    }
    if (!isCurrentSupported) {
      return `当前版本不支持题型「${currentItem.question_type || "未指定"}」，请返回训练中心重新选择题目。`;
    }
    if (!isCurrentAnswered) {
      if (isMultipleChoice) {
        return "多选题，请选择你的选项。";
      }
      if (isTrueFalse || currentItem.question_type === "single_choice") {
        return "请选择一个选项以作答。";
      }
      return "请在上方输入你的作答。";
    }
    return "已选定答案，点击“确认答案”提交。";
  }, [activeFeedback, isCurrentAnswered, isCurrentSupported, isMultipleChoice, isTrueFalse, currentItem]);

  return (
    <div className="mx-auto w-full max-w-5xl space-y-4">
      {onBack ? (
        <div className="flex items-center">
          <button
            type="button"
            onClick={onBack}
            className="group inline-flex h-9 items-center gap-2 rounded-full border border-slate-200/80 bg-white/80 pl-2.5 pr-4 text-sm font-semibold text-slate-600 shadow-sm backdrop-blur transition hover:border-slate-300 hover:bg-white hover:text-slate-950 dark:border-slate-700/80 dark:bg-slate-900/80 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:bg-slate-900 dark:hover:text-slate-50"
          >
            <span className="grid h-5 w-5 place-items-center rounded-full bg-slate-100 text-slate-500 transition group-hover:bg-slate-200 group-hover:text-slate-900 dark:bg-slate-800 dark:text-slate-400 dark:group-hover:bg-slate-700 dark:group-hover:text-slate-100">
              <ArrowLeft className="h-3 w-3 transition-transform group-hover:-translate-x-0.5" />
            </span>
            返回训练中心
          </button>
        </div>
      ) : null}

      <header className="rounded-2xl border border-slate-200 bg-white px-4 py-3.5 shadow-sm dark:border-slate-800 dark:bg-slate-950/88 sm:px-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">闯关训练</p>
            <h1 className="mt-1.5 text-xl font-semibold text-slate-950 dark:text-slate-100">
              已通过 {displayedCompletedCount} / {orderedItems.length}
            </h1>
          </div>
          <div className="grid w-full grid-cols-3 gap-2 text-center text-xs text-slate-500 dark:text-slate-400 sm:w-auto">
            <div className="min-w-16 rounded-lg bg-slate-50 px-2.5 py-1.5 dark:bg-slate-900">
              <div className="text-sm font-semibold text-slate-950 dark:text-slate-100">{displayedCompletedCount}</div>
              已通过
            </div>
            <div className="min-w-16 rounded-lg bg-slate-50 px-2.5 py-1.5 dark:bg-slate-900">
              <div className="text-sm font-semibold text-slate-950 dark:text-slate-100">{displayedRemainingCount}</div>
              待通过
            </div>
            <div className="min-w-16 rounded-lg bg-slate-50 px-2.5 py-1.5 dark:bg-slate-900">
              <div className="text-sm font-semibold text-rose-600 dark:text-rose-300">{wrongAttemptCount}</div>
              回炉
            </div>
          </div>
        </div>
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
          <div
            className="h-full rounded-full bg-slate-950 transition-all dark:bg-slate-100"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </header>

      <article className="overflow-hidden rounded-[22px] border border-slate-200 bg-white shadow-[0_16px_38px_rgba(15,23,42,0.08)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_24px_56px_-32px_rgba(0,0,0,0.9)]">
        <div className="grid gap-4 px-4 py-5 sm:px-5 sm:py-6">
          <div className="flex flex-wrap items-center gap-4 border-b border-slate-100 pb-3 dark:border-slate-800">
            <div className="flex flex-wrap items-center gap-3">
              <div className="font-sans text-lg font-bold text-slate-800 dark:text-slate-200">
                {currentItem.item_order}.
              </div>
              <span className="inline-flex items-center gap-1.5 rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold leading-4 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                <span className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  currentItem.question_type === "single_choice"
                    ? "bg-indigo-500"
                    : currentItem.question_type === "multiple_choice" || currentItem.question_type === "multi_choice"
                      ? "bg-sky-500"
                      : currentItem.question_type === "true_false"
                        ? "bg-teal-500"
                        : "bg-slate-500"
                )} />
                {formatQuestionTypeLabel(currentItem.question_type)}
              </span>
              <span className="text-slate-200 dark:text-slate-800 select-none">|</span>

              <div className={cn(
                "flex items-center gap-1.5 text-xs font-semibold transition-opacity duration-300",
                isMarked
                  ? "opacity-100"
                  : "opacity-40 hover:opacity-100 focus-within:opacity-100"
              )}>
                {onQuestionAi && (
                  <button
                    type="button"
                    onClick={() => onQuestionAi(currentItem, Boolean(hasFeedback), answerValue)}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition focus:outline-none dark:text-slate-400 dark:hover:text-slate-200 dark:hover:bg-slate-900"
                    title={`围绕第 ${currentItem.item_order} 题问 AI`}
                    aria-label={`围绕第 ${currentItem.item_order} 题问 AI`}
                  >
                    <MessageSquareText className="h-3.5 w-3.5" />
                    <span>问AI</span>
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => onQuestionMarkToggle?.(currentItem, !isMarked)}
                  disabled={!onQuestionMarkToggle || isMarking}
                  className={cn(
                    "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md transition focus:outline-none",
                    isMarked
                      ? "text-amber-600 bg-amber-50/50 hover:bg-amber-100/50 dark:text-amber-400 dark:bg-amber-500/10 dark:hover:bg-amber-500/20 font-bold"
                      : "text-slate-500 hover:text-slate-800 hover:bg-slate-100 dark:text-slate-400 dark:hover:text-slate-200 dark:hover:bg-slate-900",
                    (!onQuestionMarkToggle || isMarking) && "cursor-default opacity-70",
                  )}
                  title={isMarked ? `取消标记第 ${currentItem.item_order} 题` : `标记第 ${currentItem.item_order} 题`}
                  aria-label={isMarked ? `取消标记第 ${currentItem.item_order} 题` : `标记第 ${currentItem.item_order} 题`}
                  aria-pressed={isMarked}
                >
                  <Bookmark className={cn("h-3.5 w-3.5", isMarked && "fill-current")} />
                  <span>{isMarked ? "已标记" : "标记"}</span>
                </button>
              </div>
            </div>
          </div>

          <div className={DRILL_QUESTION_TEXT_CLASS}>
            <ExamMarkdown content={currentItem.stem} />
          </div>

          {!isCurrentSupported ? (
            <div className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200" role="alert">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>该题型尚未在当前客户端发布，已停止本题作答和判分。</span>
            </div>
          ) : choiceOptions.length > 0 ? (
            <div
              className={cn(
                "mt-6 grid gap-3 max-w-[720px]",
                choiceOptions.every((opt: string) => opt.toString().length < 12)
                  ? "grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3"
                  : "grid-cols-1"
              )}
              role={isMultipleChoice ? "group" : "radiogroup"}
              aria-label="闯关训练选项"
            >
              {choiceOptions.map((option, optionIndex) => {
                const optionLabel = isTrueFalse ? option : getOptionLabel(optionIndex);
                const optionValue = isTrueFalse ? option : optionLabel;
                const optionDisplay = isTrueFalse ? formatTrueFalseOptionLabel(option) : option;
                const isSelected = isMultipleChoice
                  ? selectedMultiChoice.has(optionValue)
                  : answerValue === optionValue;
                const isCorrectOption = isMultipleChoice
                  ? splitMultiChoiceAnswer(currentItem.correct_answer).has(optionValue)
                  : isTrueFalse
                    ? isTrueFalseAnswerMatch(currentItem.correct_answer, optionValue)
                    : normalizeTextAnswer(currentItem.correct_answer) === normalizeTextAnswer(optionValue);
                const showCorrect = hasFeedback && isCorrectOption;
                const showWrong = hasFeedback && isSelected && !isCorrectOption;
                const innerSymbol = isTrueFalse
                  ? (isTrueFalsePositive(optionValue) ? "✓" : "✗")
                  : optionLabel;

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
                      `flex items-center gap-3 rounded-lg border px-4 py-2.5 text-left transition duration-200 sm:gap-4 sm:px-4 sm:py-3 ${DRILL_OPTION_BUTTON_TEXT_CLASS}`,
                      showCorrect
                        ? "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-100"
                        : showWrong
                          ? "border-rose-300 bg-rose-50 text-rose-900 dark:border-rose-500/40 dark:bg-rose-500/10 dark:text-rose-100"
                          : isSelected
                            ? "border-transparent bg-indigo-50 text-indigo-900 dark:bg-indigo-500/10 dark:text-indigo-100"
                            : "border-slate-100 bg-slate-50/20 text-slate-700 hover:border-slate-200 hover:bg-slate-50 hover:translate-x-0.5 dark:border-slate-800/80 dark:bg-slate-900/40 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:bg-slate-900",
                      hasFeedback && "cursor-default",
                    )}
                  >
                    <span
                      className={cn(
                        "flex h-6 w-6 shrink-0 items-center justify-center border-2 text-[11px] font-extrabold transition-all duration-200",
                        isMultipleChoice ? "rounded-md" : "rounded-full",
                        showCorrect
                          ? "border-emerald-600 bg-emerald-600 text-white"
                          : showWrong
                            ? "border-rose-600 bg-rose-600 text-white"
                            : isSelected
                              ? "border-indigo-600 bg-indigo-600 text-white"
                              : "border-slate-300 bg-slate-50 hover:border-slate-400 hover:bg-slate-100 text-slate-500 dark:border-slate-600 dark:bg-slate-900/70 dark:text-slate-400"
                      )}
                    >
                      {innerSymbol}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className={cn(
                        DRILL_OPTION_MARKDOWN_CLASS,
                        showCorrect
                          ? "[&_p]:text-emerald-900 dark:[&_p]:text-emerald-100"
                          : showWrong
                            ? "[&_p]:text-rose-900 dark:[&_p]:text-rose-100"
                            : isSelected
                              ? "[&_p]:text-indigo-900 dark:[&_p]:text-indigo-100"
                              : "[&_p]:text-slate-800 dark:[&_p]:text-slate-200",
                      )}>
                        <ExamMarkdown content={optionDisplay} />
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          ) : (
            <textarea
              className={`min-h-28 w-full rounded-lg border border-slate-200 bg-white px-4 py-3 text-slate-900 outline-none transition focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-indigo-500/60 dark:focus:ring-indigo-500/20 dark:disabled:bg-slate-900/70 ${DRILL_TEXTAREA_TEXT_CLASS}`}
              placeholder="输入你的作答"
              value={answerValue}
              disabled={Boolean(hasFeedback) || isCompleting || isCheckingAnswer}
              onChange={(event) => setCurrentAnswer(currentItem, event.target.value)}
            />
          )}

          {activeFeedback ? (
            <section
              className={cn(
                "rounded-2xl border px-3.5 py-3.5",
                activeFeedback.isCorrect
                  ? "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-100"
                  : "border-rose-200 bg-rose-50 text-rose-900 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-100",
              )}
            >
              <div className="flex items-start gap-3">
                {activeFeedback.isCorrect ? (
                  <CheckCircle2 className="mt-0.5 h-[18px] w-[18px] shrink-0" />
                ) : (
                  <XCircle className="mt-0.5 h-[18px] w-[18px] shrink-0" />
                )}
                <div className="min-w-0 flex-1">
                  <h2 className="text-sm font-semibold">{activeFeedback.isCorrect ? "答对了" : "答错了，稍后再来一次"}</h2>
                  <p className="mt-0.5 text-xs leading-5 opacity-85">
                    {activeFeedback.isCorrect ? "这题已通过，会进入下一题。" : "这题会回到队列末尾，直到你答对为止。"}
                  </p>
                </div>
              </div>
              <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
                <DrillAnswerBlock title="你的答案" content={formatAnswerForDisplay(currentItem.question_type, activeFeedback.answer)} />
                <DrillAnswerBlock title="正确答案" content={formatAnswerForDisplay(currentItem.question_type, currentItem.correct_answer)} />
              </div>
              {activeFeedback.feedbackText ? (
                <div className="mt-2.5">
                  <DrillAnswerBlock title="判题反馈" content={activeFeedback.feedbackText} />
                </div>
              ) : null}
              <div className="mt-2.5">
                <DrillAnswerBlock title="解析" content={currentItem.explanation || "暂无解析"} />
              </div>
            </section>
          ) : null}
        </div>

        <footer className="flex flex-col gap-2.5 border-t border-slate-100 bg-slate-50/70 px-4 py-3.5 dark:border-slate-800 dark:bg-slate-900/35 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <p className="text-xs leading-5 text-slate-500 dark:text-slate-400 sm:text-sm">
            {footerHint}
          </p>
          {activeFeedback ? (
            <Button
              className="h-11 w-full rounded-full bg-black px-5 text-sm font-semibold dark:bg-slate-100 dark:text-slate-900 sm:w-auto"
              onClick={handleContinue}
              disabled={isCompleting}
            >
              {activeFeedback.isCorrect ? <ArrowRight className="h-4 w-4" /> : <RotateCcw className="h-4 w-4" />}
              {activeFeedback.isCorrect ? (queue.length === 1 ? "完成训练" : "下一题") : "重新入队"}
            </Button>
          ) : (
            <Button
              className="h-11 w-full rounded-full bg-black px-5 text-sm font-semibold dark:bg-slate-100 dark:text-slate-900 sm:w-auto"
              onClick={handleCheckAnswer}
              disabled={!isCurrentSupported || !isCurrentAnswered || isCompleting || isCheckingAnswer}
            >
              {isCheckingAnswer ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {isCheckingAnswer ? checkingAnswerLabel : "确认答案"}
            </Button>
          )}
        </footer>
      </article>
    </div>
  );
}
