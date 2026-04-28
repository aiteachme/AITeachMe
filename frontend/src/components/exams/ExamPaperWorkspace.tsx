import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ListChecks, ZoomIn, ZoomOut } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import {
  getExamDetailApiV1SubjectsSubjectIdExamsExamPaperIdGetQueryKey,
  getExamHistoryApiV1SubjectsSubjectIdExamsHistoryGetQueryKey,
  useExamDetailApiV1SubjectsSubjectIdExamsExamPaperIdGet,
  useSubmitExamApiV1SubjectsSubjectIdExamsExamPaperIdSubmitPost,
} from "../../api/generated/exams";
import type { ExamPaperDetailResponse, ExamPaperItemResponse } from "../../api/generated/model";
import { getMasteryOverviewApiV1SubjectsSubjectIdProfileMasteryGetQueryKey } from "../../api/generated/profile";
import { buildApiUrl, getApiErrorMessage, orvalApiClient } from "../../api/client";
import {
  AI_SOURCE_EXAM_QUESTION,
  EXAM_QUESTION_JUMP_EVENT,
  buildExamQuestionAnchorId,
  useAiInteraction,
  type ExamQuestionJumpDetail,
} from "../interaction";
import { Button } from "../ui/Button";
import { useToast } from "../ui/Toast";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { ExamPaperSheet } from "./ExamPaperSheet";
import { ExamQuestionAnalysisSheet } from "./ExamQuestionAnalysisSheet";
import { ExamStageHeader } from "./ExamStageHeader";
import { ExamStudyGuideView } from "./ExamStudyGuideView";
import {
  parseExamGenerationSnapshot,
  patchExamDetailQueryData,
  patchExamHistoryQueryData,
} from "./examGenerationStream";
import type { ExamStudyGuideResponse } from "./types";
import {
  buildQuestionAiDraft,
  buildQuestionSelectedText,
  buildQuestionSelectionContext,
  hasAnsweredQuestion,
} from "./examDisplay";

async function getExamStudyGuide(subjectId: string, paperId: number, signal?: AbortSignal) {
  return orvalApiClient<{ data?: { code?: number; message?: string; data?: ExamStudyGuideResponse } }>(
    `/api/v1/subjects/${subjectId}/exams/${paperId}/study-guide`,
    {
      method: "GET",
      signal,
    },
  );
}

interface ExamPaperWorkspaceProps {
  subjectId: string;
  paperId: number;
  backHref: string;
}

export function ExamPaperWorkspace({ subjectId, paperId, backHref }: ExamPaperWorkspaceProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const { openAiInteraction, isSidebarOpen } = useAiInteraction();
  const { toast } = useToast();
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [pageScale, setPageScale] = useState(1);
  const [activeStage, setActiveStage] = useState<1 | 2 | 3>(1);
  const [isQuestionNavOpen, setIsQuestionNavOpen] = useState(false);
  const [selectedReviewItemId, setSelectedReviewItemId] = useState<number | null>(null);
  const [highlightedQuestionOrder, setHighlightedQuestionOrder] = useState<number | null>(null);
  const handledJumpMarkerRef = useRef<number | string | null>(null);
  const answerStorageKey = useMemo(
    () => `aiteachme:exam-draft-answers:${subjectId}:${paperId}`,
    [paperId, subjectId],
  );

  useEffect(() => {
    if (!isSidebarOpen) {
      setHighlightedQuestionOrder(null);
    }
  }, [isSidebarOpen]);

  const examDetailQuery = useExamDetailApiV1SubjectsSubjectIdExamsExamPaperIdGet(subjectId, paperId, {
    query: {
      enabled: Boolean(subjectId && paperId),
    },
  });

  const paper = useMemo<ExamPaperDetailResponse | null>(
    () => unwrapOrvalResponse<ExamPaperDetailResponse>(examDetailQuery.data),
    [examDetailQuery.data],
  );
  const generationErrorMessage = useMemo(() => {
    const raw = paper?.selection_context?.error_message;
    return typeof raw === "string" ? raw.trim() : "";
  }, [paper?.selection_context]);
  const selectedReviewItem = useMemo(
    () =>
      (paper?.items ?? []).find((item: ExamPaperItemResponse) => item.id === selectedReviewItemId) ??
      (paper?.items ?? [])[0] ??
      null,
    [paper?.items, selectedReviewItemId],
  );
  const isReviewLayout = paper?.status === "graded" && activeStage === 2;

  useEffect(() => {
    if (!paper) return;
    if (paper.status === "graded") {
      setActiveStage((current) => (current === 1 ? 2 : current));
      return;
    }
    setActiveStage(1);
  }, [paper?.id, paper?.status]);

  useEffect(() => {
    if (paper?.status !== "graded") return;
    const items = paper.items ?? [];
    if (!items.length) return;
    setSelectedReviewItemId((current) =>
      items.some((item: ExamPaperItemResponse) => item.id === current) ? current : items[0].id,
    );
  }, [paper?.id, paper?.items, paper?.status]);

  useEffect(() => {
    if (!isReviewLayout || !paper?.items?.length) return;

    const itemByOrder = new Map(
      (paper.items ?? []).map((item: ExamPaperItemResponse) => [item.item_order, item]),
    );
    let frameId = 0;
    const questionSelector = "[data-question-anchor='true'][data-question-order]";
    const getQuestionNodes = () => Array.from(
      document.querySelectorAll<HTMLElement>(questionSelector),
    );

    const getScrollContainers = () => {
      const containers = new Set<EventTarget>([window]);
      const main = document.querySelector("main");
      if (main instanceof HTMLElement) {
        containers.add(main);
      }

      for (const node of getQuestionNodes()) {
        let parent = node.parentElement;
        while (parent && parent !== document.body) {
          const style = window.getComputedStyle(parent);
          const canScrollY = /(auto|scroll|overlay)/.test(style.overflowY);
          if (canScrollY && parent.scrollHeight > parent.clientHeight + 1) {
            containers.add(parent);
          }
          parent = parent.parentElement;
        }
      }
      return containers;
    };

    const updateSelectedFromViewport = () => {
      frameId = 0;
      const questionNodes = getQuestionNodes();
      const viewportTop = 96;
      const viewportBottom = window.innerHeight;
      const focusY = Math.max(viewportTop + 80, Math.min(window.innerHeight * 0.38, viewportBottom - 120));
      let bestMatch: { item: ExamPaperItemResponse; distance: number } | null = null;

      for (const node of questionNodes) {
        const order = Number(node.dataset.questionOrder);
        const item = itemByOrder.get(order);
        if (!item) continue;

        const rect = node.getBoundingClientRect();
        if (rect.bottom <= viewportTop || rect.top >= viewportBottom) continue;

        const distance = rect.top <= focusY && rect.bottom >= focusY
          ? 0
          : Math.min(Math.abs(rect.top - focusY), Math.abs(rect.bottom - focusY));
        if (!bestMatch || distance < bestMatch.distance) {
          bestMatch = { item, distance };
        }
      }

      if (!bestMatch) return;
      setSelectedReviewItemId((current) => (
        current === bestMatch.item.id ? current : bestMatch.item.id
      ));
    };

    const scheduleUpdate = () => {
      if (frameId) return;
      frameId = window.requestAnimationFrame(updateSelectedFromViewport);
    };

    scheduleUpdate();
    const scrollContainers = getScrollContainers();
    const scrollOptions: AddEventListenerOptions = { passive: true, capture: true };
    for (const container of scrollContainers) {
      container.addEventListener("scroll", scheduleUpdate, scrollOptions);
    }
    document.addEventListener("scroll", scheduleUpdate, scrollOptions);
    window.addEventListener("resize", scheduleUpdate);
    return () => {
      for (const container of scrollContainers) {
        container.removeEventListener("scroll", scheduleUpdate, scrollOptions);
      }
      document.removeEventListener("scroll", scheduleUpdate, scrollOptions);
      window.removeEventListener("resize", scheduleUpdate);
      if (frameId) {
        window.cancelAnimationFrame(frameId);
      }
    };
  }, [isReviewLayout, paper?.items]);

  const studyGuideQuery = useQuery({
    queryKey: ["exam-study-guide", subjectId, paperId],
    enabled: Boolean(subjectId && paperId && paper?.status === "graded" && activeStage === 3),
    queryFn: async ({ signal }) => {
      const response = await getExamStudyGuide(subjectId, paperId, signal);
      return unwrapOrvalResponse<ExamStudyGuideResponse>(response);
    },
  });

  useEffect(() => {
    if (!subjectId || !paperId || paper?.status !== "generating") return;
    const stream = new EventSource(
      buildApiUrl(`/api/v1/subjects/${encodeURIComponent(subjectId)}/exams/${paperId}/stream`),
      { withCredentials: true },
    );
    const historyQueryKey = getExamHistoryApiV1SubjectsSubjectIdExamsHistoryGetQueryKey(subjectId, { page: 1, size: 24 });
    const detailQueryKey = getExamDetailApiV1SubjectsSubjectIdExamsExamPaperIdGetQueryKey(subjectId, paperId);

    const refreshPaper = () => {
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: historyQueryKey }),
        queryClient.invalidateQueries({ queryKey: detailQueryKey }),
      ]);
    };

    const applySnapshotPayload = (message: MessageEvent<string>) => {
      const payload = parseExamGenerationSnapshot(message.data);
      if (!payload.exam_paper_id) {
        refreshPaper();
        return payload;
      }
      queryClient.setQueryData(detailQueryKey, (current: unknown) =>
        patchExamDetailQueryData(current, payload),
      );
      queryClient.setQueryData(historyQueryKey, (current: unknown) =>
        patchExamHistoryQueryData(current, payload),
      );
      return payload;
    };

    const handleDone = (event: Event) => {
      const message = event as MessageEvent<string>;
      const payload = applySnapshotPayload(message);
      refreshPaper();
      stream.close();
      if (payload.status === "failed") {
        toast({
          title: "试卷生成失败",
          description: payload.error_message || "请稍后重试。",
          variant: "error",
        });
        return;
      }
      toast({
        title: "试卷生成完成",
        description: "题目已生成，可以开始作答。",
        variant: "success",
      });
    };

    const handleSnapshot = (event: Event) => {
      applySnapshotPayload(event as MessageEvent<string>);
    };

    stream.addEventListener("done", handleDone);
    stream.addEventListener("snapshot", handleSnapshot);
    stream.onerror = () => {
      refreshPaper();
    };

    return () => {
      stream.removeEventListener("done", handleDone);
      stream.removeEventListener("snapshot", handleSnapshot);
      stream.close();
    };
  }, [paper?.status, paperId, queryClient, subjectId, toast]);

  useEffect(() => {
    if (!paper?.items) return;
    setAnswers((current) => {
      let stored: Record<number, string> = {};
      try {
        const parsed = JSON.parse(window.localStorage.getItem(answerStorageKey) || "{}");
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
          for (const [key, value] of Object.entries(parsed)) {
            const order = Number(key);
            if (Number.isFinite(order) && order > 0) {
              stored[order] = typeof value === "string" ? value : String(value ?? "");
            }
          }
        }
      } catch {
        stored = {};
      }

      const next: Record<number, string> = { ...stored };
      for (const item of paper.items ?? []) {
        const serverAnswer = item.user_answer ?? "";
        if (serverAnswer.trim()) {
          next[item.item_order] = serverAnswer;
        }
      }
      for (const [rawOrder, value] of Object.entries(current)) {
        const order = Number(rawOrder);
        if (Number.isFinite(order) && order > 0 && value.trim()) {
          next[order] = value;
        }
      }
      return next;
    });
  }, [answerStorageKey, paper?.id, paper?.items]);

  useEffect(() => {
    if (!paper || paper.status === "graded") return;
    try {
      const nonEmptyAnswers = Object.fromEntries(
        Object.entries(answers).filter(([, value]) => value.trim().length > 0),
      );
      window.localStorage.setItem(answerStorageKey, JSON.stringify(nonEmptyAnswers));
    } catch {
      // Best-effort local draft persistence.
    }
  }, [answerStorageKey, answers, paper]);

  const keepQuestionHighlight = useCallback((questionOrder: number) => {
    setHighlightedQuestionOrder(questionOrder);
  }, []);

  const revealQuestion = useCallback((questionOrder: number, behavior: ScrollBehavior = "smooth") => {
    if (!Number.isFinite(questionOrder) || questionOrder <= 0) {
      return;
    }
    const matchedItem = (paper?.items ?? []).find(
      (item: ExamPaperItemResponse) => item.item_order === questionOrder,
    );
    if (paper?.status === "graded" && matchedItem) {
      setSelectedReviewItemId(matchedItem.id);
    }
    setActiveStage(paper?.status === "graded" ? 2 : 1);
    window.setTimeout(() => {
      const target = document.getElementById(`exam-question-${questionOrder}`);
      if (!target) {
        return;
      }
      target.scrollIntoView({ behavior, block: "start" });
      keepQuestionHighlight(questionOrder);
    }, 80);
  }, [keepQuestionHighlight, paper?.items, paper?.status]);

  useEffect(() => {
    const handleExamQuestionJump = (event: Event) => {
      const detail = (event as CustomEvent<ExamQuestionJumpDetail>).detail;
      if (!detail || detail.subjectId !== subjectId || detail.paperId !== paperId) {
        return;
      }
      revealQuestion(detail.questionOrder);
    };

    window.addEventListener(EXAM_QUESTION_JUMP_EVENT, handleExamQuestionJump);
    return () => window.removeEventListener(EXAM_QUESTION_JUMP_EVENT, handleExamQuestionJump);
  }, [paperId, revealQuestion, subjectId]);

  useEffect(() => {
    if (!paper) {
      return;
    }
    const state = location.state as {
      examQuestionJump?: ExamQuestionJumpDetail | null;
      examQuestionJumpAt?: number | null;
    } | null;
    const detail = state?.examQuestionJump ?? null;
    if (!detail || detail.subjectId !== subjectId || detail.paperId !== paperId) {
      return;
    }
    const marker = state?.examQuestionJumpAt ?? `${detail.paperId}-${detail.questionOrder}`;
    if (handledJumpMarkerRef.current === marker) {
      return;
    }
    handledJumpMarkerRef.current = marker;
    revealQuestion(detail.questionOrder);
  }, [location.state, paper, paperId, revealQuestion, subjectId]);

  const openQuestionAi = useCallback((
    item: ExamPaperItemResponse,
    isReviewStage: boolean,
    answerValue: string,
  ) => {
    if (!paper) {
      return;
    }
    const anchorId = buildExamQuestionAnchorId(paper.id, item.item_order);
    const selectedText = buildQuestionSelectedText(item);
    keepQuestionHighlight(item.item_order);
    openAiInteraction({
      mode: "sidebar",
      scope: { type: "subject", subjectId },
      sessionId: null,
      draft: buildQuestionAiDraft(item, isReviewStage),
      source: AI_SOURCE_EXAM_QUESTION,
      anchorId,
      selectedText,
      selectionContext: buildQuestionSelectionContext(paper, item, answerValue, isReviewStage),
      clientThreadId: `${anchorId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      newSession: true,
      showSelectionContext: true,
    });
  }, [keepQuestionHighlight, openAiInteraction, paper, subjectId]);

  const submitExam = useSubmitExamApiV1SubjectsSubjectIdExamsExamPaperIdSubmitPost({
    mutation: {
      onSuccess: async (response) => {
        const graded = unwrapOrvalResponse(response);
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: getExamHistoryApiV1SubjectsSubjectIdExamsHistoryGetQueryKey(subjectId, { page: 1, size: 24 }),
          }),
          queryClient.invalidateQueries({
            queryKey: getExamDetailApiV1SubjectsSubjectIdExamsExamPaperIdGetQueryKey(subjectId, paperId),
          }),
          queryClient.invalidateQueries({
            queryKey: getMasteryOverviewApiV1SubjectsSubjectIdProfileMasteryGetQueryKey(subjectId),
          }),
        ]);
        toast({
          title: "交卷成功",
          description: `本次得分 ${graded?.score ?? 0}，掌握度已同步更新。`,
          variant: "success",
        });
        try {
          window.localStorage.removeItem(answerStorageKey);
        } catch {
          // Best-effort local draft cleanup.
        }
        setActiveStage(2);
        window.scrollTo({ top: 0, behavior: "smooth" });
      },
      onError: (error) => {
        toast({
          title: "交卷失败",
          description: getApiErrorMessage(error, "请稍后重试"),
          variant: "error",
        });
      },
    },
  });

  return (
    <div className="relative min-h-full">
      <div className="pointer-events-none fixed inset-0 -z-10 bg-[linear-gradient(180deg,#ffffff_0%,#f7f9fc_36%,#eef3f8_100%)]" />
      <ExamStageHeader
        currentStep={paper?.status === "graded" ? activeStage : 1}
        onBack={() => navigate(backHref)}
        onStepSelect={(step) => {
          if (step === 1) {
            setActiveStage(1);
            return;
          }
          if (paper?.status === "graded") {
            setActiveStage(step);
          }
        }}
        isStepEnabled={(step) => {
          if (step === 1) return true;
          return paper?.status === "graded";
        }}
      />

      <div className="px-4 py-6 sm:px-6 lg:px-8">
        <div
          className={`mx-auto space-y-6 ${
            isReviewLayout
              ? "max-w-none lg:mr-16 xl:mr-20 2xl:mr-24"
              : "max-w-7xl"
          }`}
        >
          {examDetailQuery.isLoading && (
            <div className="rounded-[28px] border border-slate-200 bg-white px-6 py-12 text-center text-sm text-slate-500">
              正在加载考卷内容...
            </div>
          )}

          {examDetailQuery.error && (
            <div className="rounded-[28px] border border-red-200 bg-red-50 px-6 py-4 text-sm text-red-700">
              {getApiErrorMessage(examDetailQuery.error, "加载考卷失败")}
            </div>
          )}

          {!examDetailQuery.isLoading && !paper && !examDetailQuery.error && (
            <div className="rounded-[28px] border border-slate-200 bg-white px-6 py-12 text-center text-sm text-slate-500">
              这份考卷不存在，或者已经无法访问。
            </div>
          )}

          {paper && (
            <>
              {paper.status === "generating" && (
                <div
                  className="transition-all duration-150"
                  style={{
                    zoom: pageScale,
                  }}
                >
                  <ExamPaperSheet
                    paper={paper}
                    answers={answers}
                    activeStage={activeStage}
                    pageScale={pageScale}
                    highlightedQuestionOrder={highlightedQuestionOrder}
                    setAnswers={setAnswers}
                  />
                </div>
              )}

              {paper.status === "failed" && (
                <div className="rounded-[28px] border border-rose-200 bg-rose-50 px-6 py-12 text-center text-sm text-rose-700">
                  <h2 className="text-lg font-semibold text-rose-950">试卷生成失败</h2>
                  <p className="mt-2">
                    {generationErrorMessage || "后台生成题目时出错，请返回列表后重新生成。"}
                  </p>
                </div>
              )}

              {paper.status !== "generating" && paper.status !== "failed" && activeStage !== 3 && (
                <>
              <aside className="hidden lg:block">
                <div className="fixed right-4 top-28 z-30 flex items-start gap-3 xl:right-6">
                  {isQuestionNavOpen && (
                    <div
                      id="exam-question-nav-panel"
                      className="max-h-[calc(100vh-9rem)] w-52 overflow-y-auto rounded-2xl border border-slate-200/80 bg-white/95 px-3 py-4 shadow-[0_18px_40px_rgba(15,23,42,0.1)] backdrop-blur 2xl:w-60"
                    >
                      <div className="mb-3 px-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                        题目导航
                      </div>
                      <div className="grid grid-cols-4 gap-2 2xl:grid-cols-5">
                        {(paper.items ?? []).map((item) => {
                          const isAnswered = hasAnsweredQuestion(item, answers);
                          const isSelectedReviewItem = isReviewLayout && selectedReviewItemId === item.id;
                          const navTone =
                            paper.status === "graded"
                              ? item.is_correct
                                ? "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200 hover:bg-emerald-100"
                                : "bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-200 hover:bg-rose-100"
                              : isAnswered
                                ? "bg-slate-900 text-white hover:bg-slate-800"
                                : "bg-slate-100 text-slate-600 hover:bg-slate-200";

                          return (
                            <button
                              key={item.id}
                              type="button"
                              onClick={() => {
                                if (isReviewLayout) {
                                  setSelectedReviewItemId(item.id);
                                }
                                revealQuestion(item.item_order);
                              }}
                              className={`grid aspect-square w-full place-items-center rounded-lg text-xs font-semibold transition ${navTone} ${
                                isSelectedReviewItem ? "ring-2 ring-slate-900 ring-offset-2 ring-offset-white" : ""
                              }`}
                              aria-label={`跳转到第 ${item.item_order} 题`}
                            >
                              {item.item_order}
                            </button>
                          );
                        })}
                      </div>

                      <div className="mt-4 space-y-2 px-2 text-xs text-slate-500">
                        <div className="flex items-center gap-2">
                          <span className={`h-2.5 w-2.5 rounded-full ${paper.status === "graded" ? "bg-emerald-500" : "bg-slate-900"}`} />
                          <span>{paper.status === "graded" ? "正确" : "已作答"}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className={`h-2.5 w-2.5 rounded-full ${paper.status === "graded" ? "bg-rose-500" : "bg-slate-400"}`} />
                          <span>{paper.status === "graded" ? "错误 / 未作答" : "未作答"}</span>
                        </div>
                      </div>
                    </div>
                  )}

                  <div className="flex flex-col gap-3">
                    <button
                      type="button"
                      onClick={() => setIsQuestionNavOpen((current) => !current)}
                      className={`grid h-10 w-10 place-items-center rounded-xl border shadow-[0_18px_40px_rgba(15,23,42,0.08)] backdrop-blur transition ${
                        isQuestionNavOpen
                          ? "border-violet-300 bg-violet-50 text-violet-700 hover:bg-violet-100"
                          : "border-slate-200/80 bg-white/92 text-slate-700 hover:bg-slate-100"
                      }`}
                      aria-label={isQuestionNavOpen ? "收起题目导航" : "展开题目导航"}
                      aria-expanded={isQuestionNavOpen}
                      aria-controls="exam-question-nav-panel"
                      title={isQuestionNavOpen ? "收起题目导航" : "展开题目导航"}
                    >
                      <ListChecks className="h-5.5 w-5.5" />
                    </button>

                    <button
                      type="button"
                      onClick={() => setPageScale((current) => Math.min(1.4, Number((current + 0.05).toFixed(2))))}
                      className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200/80 bg-white/92 text-slate-700 shadow-[0_18px_40px_rgba(15,23,42,0.08)] backdrop-blur transition hover:bg-slate-100"
                      aria-label="放大页面"
                      title="放大页面"
                    >
                      <ZoomIn className="h-5.5 w-5.5" />
                    </button>

                    <button
                      type="button"
                      onClick={() => setPageScale((current) => Math.max(0.7, Number((current - 0.05).toFixed(2))))}
                      className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200/80 bg-white/92 text-slate-700 shadow-[0_18px_40px_rgba(15,23,42,0.08)] backdrop-blur transition hover:bg-slate-100"
                      aria-label="缩小页面"
                      title="缩小页面"
                    >
                      <ZoomOut className="h-5.5 w-5.5" />
                    </button>
                  </div>
                </div>
              </aside>

              <div
                className="transition-all duration-150"
                style={{
                  zoom: pageScale,
                }}
              >
                {isReviewLayout ? (
                  <div className="pb-4">
                    <div className="grid w-full grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(420px,0.62fr)] 2xl:grid-cols-[minmax(820px,1fr)_minmax(520px,0.72fr)] 2xl:gap-8">
                    <ExamPaperSheet
                      paper={paper}
                      answers={answers}
                      activeStage={activeStage}
                      pageScale={1}
                      highlightedQuestionOrder={highlightedQuestionOrder}
                      setAnswers={setAnswers}
                      selectedItemId={selectedReviewItem?.id ?? null}
                      showInlineReviewDetails={false}
                      onSelectQuestion={(item) => {
                        setSelectedReviewItemId(item.id);
                        keepQuestionHighlight(item.item_order);
                      }}
                      onQuestionAi={openQuestionAi}
                    />
                    <ExamQuestionAnalysisSheet item={selectedReviewItem} />
                    </div>
                  </div>
                ) : (
                  <ExamPaperSheet
                    paper={paper}
                    answers={answers}
                    activeStage={activeStage}
                    pageScale={pageScale}
                    highlightedQuestionOrder={highlightedQuestionOrder}
                    setAnswers={setAnswers}
                    onQuestionAi={openQuestionAi}
                  />
                )}

                <section className="flex flex-col items-center justify-center gap-3 border-t border-slate-100 pt-4 pb-12 text-center sm:pb-16">
                  <Button
                    className={`h-14 rounded-full bg-black px-10 text-base font-semibold shadow-[0_18px_40px_rgba(15,23,42,0.18)] ${paper.status === "graded" ? "hidden" : ""}`}
                    onClick={() =>
                      submitExam.mutate({
                        subjectId,
                        examPaperId: paperId,
                        data: {
                          answers: (paper.items ?? []).map((item: ExamPaperItemResponse) => ({
                            exam_paper_item_id: item.id,
                            item_order: item.item_order,
                            answer: answers[item.item_order] ?? "",
                          })),
                        },
                      })
                    }
                    disabled={submitExam.isPending}
                  >
                    {paper.status === "graded"
                      ? "已完成批改"
                      : submitExam.isPending
                        ? "提交中..."
                        : "提交这份考卷"}
                  </Button>
                  {paper.status === "graded" && (
                    <>
                      <Button
                        className="h-14 rounded-full bg-black px-10 text-base font-semibold shadow-[0_18px_40px_rgba(15,23,42,0.18)]"
                        onClick={() => {
                          setActiveStage(3);
                          window.scrollTo({ top: 0, behavior: "smooth" });
                        }}
                      >
                        查看学习指南
                      </Button>
                      <p className="text-sm text-slate-500">进入第 3 步，根据本次结果继续查漏补缺。</p>
                    </>
                  )}
                  </section>
                </div>
                </>
              )}

              {paper.status !== "generating" && paper.status !== "failed" && activeStage === 3 && (
                <div className="mx-auto max-w-6xl">
                  {studyGuideQuery.isLoading && (
                    <div className="rounded-[28px] border border-slate-200 bg-white px-6 py-12 text-center text-sm text-slate-500">
                      正在生成学习指南...
                    </div>
                  )}

                  {studyGuideQuery.error && (
                    <div className="rounded-[28px] border border-red-200 bg-red-50 px-6 py-4 text-sm text-red-700">
                      {getApiErrorMessage(studyGuideQuery.error, "学习指南生成失败")}
                    </div>
                  )}

                  {studyGuideQuery.data && (
                    <ExamStudyGuideView
                      guide={studyGuideQuery.data}
                      paper={paper}
                      onBackToReview={() => setActiveStage(2)}
                    />
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
