import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, ZoomIn, ZoomOut } from "lucide-react";
import { useNavigate } from "react-router-dom";

import {
  getExamDetailApiV1SubjectsSubjectExamsExamPaperIdGetQueryKey,
  getExamHistoryApiV1SubjectsSubjectExamsHistoryGetQueryKey,
  useExamDetailApiV1SubjectsSubjectExamsExamPaperIdGet,
  useSubmitExamApiV1SubjectsSubjectExamsExamPaperIdSubmitPost,
} from "../../api/generated/exams";
import type { ExamPaperDetailResponse, ExamPaperItemResponse } from "../../api/generated/model";
import { getMasteryOverviewApiV1SubjectsSubjectProfileMasteryGetQueryKey } from "../../api/generated/profile";
import { buildApiUrl, getApiErrorMessage, orvalApiClient } from "../../api/client";
import { Button } from "../ui/Button";
import { useToast } from "../ui/Toast";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { ExamPaperSheet } from "./ExamPaperSheet";
import { ExamStageHeader } from "./ExamStageHeader";
import { ExamStudyGuideView } from "./ExamStudyGuideView";
import type { ExamStudyGuideResponse } from "./types";
import { hasAnsweredQuestion } from "./examDisplay";

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
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [pageScale, setPageScale] = useState(1);
  const [activeStage, setActiveStage] = useState<1 | 2 | 3>(1);

  const examDetailQuery = useExamDetailApiV1SubjectsSubjectExamsExamPaperIdGet(subjectId, paperId, {
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

  useEffect(() => {
    if (!paper) return;
    if (paper.status === "graded") {
      setActiveStage((current) => (current === 1 ? 2 : current));
      return;
    }
    setActiveStage(1);
  }, [paper?.id, paper?.status]);

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

    const refreshPaper = () => {
      void Promise.all([
        queryClient.invalidateQueries({
          queryKey: getExamHistoryApiV1SubjectsSubjectExamsHistoryGetQueryKey(subjectId, { page: 1, size: 24 }),
        }),
        queryClient.invalidateQueries({
          queryKey: getExamDetailApiV1SubjectsSubjectExamsExamPaperIdGetQueryKey(subjectId, paperId),
        }),
      ]);
    };

    const handleDone = (event: Event) => {
      const message = event as MessageEvent<string>;
      let payload: { status?: string; error_message?: string } = {};
      try {
        payload = JSON.parse(message.data || "{}");
      } catch {
        payload = {};
      }
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

    const handleSnapshot = () => {
      refreshPaper();
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
    setAnswers(
      Object.fromEntries(
        (paper.items ?? []).map((item: ExamPaperItemResponse) => [item.id, item.user_answer ?? ""]),
      ),
    );
  }, [paper?.id, paper?.items]);

  const submitExam = useSubmitExamApiV1SubjectsSubjectExamsExamPaperIdSubmitPost({
    mutation: {
      onSuccess: async (response) => {
        const graded = unwrapOrvalResponse(response);
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: getExamHistoryApiV1SubjectsSubjectExamsHistoryGetQueryKey(subjectId, { page: 1, size: 24 }),
          }),
          queryClient.invalidateQueries({
            queryKey: getExamDetailApiV1SubjectsSubjectExamsExamPaperIdGetQueryKey(subjectId, paperId),
          }),
          queryClient.invalidateQueries({
            queryKey: getMasteryOverviewApiV1SubjectsSubjectProfileMasteryGetQueryKey(subjectId),
          }),
        ]);
        toast({
          title: "交卷成功",
          description: `本次得分 ${graded?.score ?? 0}，掌握度已同步更新。`,
          variant: "success",
        });
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
        <div className="mx-auto max-w-7xl space-y-6">
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
                <div className="rounded-[28px] border border-violet-200 bg-violet-50 px-6 py-12 text-center text-sm text-violet-700">
                  <Loader2 className="mx-auto mb-4 h-8 w-8 animate-spin" />
                  <h2 className="text-lg font-semibold text-violet-950">试卷题目生成中</h2>
                  <p className="mt-2">基础信息已创建，题目生成完成后会自动刷新。</p>
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
                <div className="fixed left-2 top-28 z-20 w-[112px] rounded-[28px] border border-slate-200/80 bg-white/92 px-3 py-4 shadow-[0_18px_40px_rgba(15,23,42,0.08)] backdrop-blur xl:left-3 xl:w-[136px] 2xl:w-[184px]">
                  <div className="mb-3 px-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                    题目导航
                  </div>
                  <div
                    className="grid gap-2"
                    style={{ gridTemplateColumns: "repeat(auto-fit, minmax(2rem, 1fr))" }}
                  >
                    {(paper.items ?? []).map((item) => {
                      const isAnswered = hasAnsweredQuestion(item, answers);
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
                          onClick={() =>
                            document
                              .getElementById(`exam-question-${item.item_order}`)
                              ?.scrollIntoView({ behavior: "smooth", block: "start" })
                          }
                          className={`grid aspect-square w-full max-w-8 justify-self-center place-items-center rounded-lg text-xs font-semibold transition ${navTone}`}
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
              </aside>

              <aside className="hidden lg:block">
                <div className="fixed right-4 top-28 z-20 flex flex-col gap-3 xl:right-6">
                <button
                  type="button"
                    onClick={() => setPageScale((current) => Math.min(1.4, Number((current + 0.05).toFixed(2))))}
                    className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200/80 bg-white/92 text-slate-700 shadow-[0_18px_40px_rgba(15,23,42,0.08)] backdrop-blur transition hover:bg-slate-100"
                  aria-label="放大页面"
                >
                    <ZoomIn className="h-5.5 w-5.5" />
                </button>

                <button
                  type="button"
                    onClick={() => setPageScale((current) => Math.max(0.7, Number((current - 0.05).toFixed(2))))}
                    className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200/80 bg-white/92 text-slate-700 shadow-[0_18px_40px_rgba(15,23,42,0.08)] backdrop-blur transition hover:bg-slate-100"
                  aria-label="缩小页面"
                >
                    <ZoomOut className="h-5.5 w-5.5" />
                </button>
                </div>
              </aside>

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
                  setAnswers={setAnswers}
                />

                <section className="flex flex-col items-center justify-center gap-3 border-t border-slate-100 pt-4 pb-12 text-center sm:pb-16">
                  <Button
                    className={`h-14 rounded-full bg-black px-10 text-base font-semibold shadow-[0_18px_40px_rgba(15,23,42,0.18)] ${paper.status === "graded" ? "hidden" : ""}`}
                    onClick={() =>
                      submitExam.mutate({
                        subject: subjectId,
                        examPaperId: paperId,
                        data: {
                          answers: (paper.items ?? []).map((item: ExamPaperItemResponse) => ({
                            exam_paper_item_id: item.id,
                            item_order: item.item_order,
                            answer: answers[item.id] ?? "",
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
