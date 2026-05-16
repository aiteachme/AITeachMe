import { useEffect, useMemo, useState, type MouseEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  BookOpen,
  Bookmark,
  CheckCircle2,
  ChevronDown,
  CloudOff,
  FileText,
  ClipboardCheck,
  Layers3,
  Loader2,
  MoreVertical,
  Plus,
  Search,
  Sparkles,
  Tags,
  X,
  XCircle,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import {
  getExamHistoryApiV1CoursesCourseIdExamsHistoryGetQueryKey,
  useExamHistoryApiV1CoursesCourseIdExamsHistoryGet,
  useGenerateExamApiV1CoursesCourseIdExamsGeneratePost,
} from "../api/generated/exams";
import type { ExamHistoryItem } from "../api/generated/model";
import {
  buildApiUrl,
  getApiErrorMessage,
  orvalApiClient,
  registerBackendEventSource,
  reportBackendConnectionIssue,
} from "../api/client";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Modal";
import { useToast } from "../components/ui/Toast";
import {
  CreateExamModal,
  ExamMarkdown,
  ExamPaperCard,
  ExamPaperWorkspace,
  MASTERY_DRILL_EXAM_MODE,
  MASTERY_DRILL_QUESTION_COUNT,
  buildExamTitle,
  formatDifficultyLabel,
  loadCreateExamConfig,
  toExamGenerateRequest,
} from "../components/exams";
import {
  parseExamGenerationSnapshot,
  patchExamHistoryQueryData,
} from "../components/exams/examGenerationStream";
import { useExamResultDisplayPreference } from "../lib/examResultDisplayPreference";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { buildCoursePath, buildCourseSubPath } from "../lib/courseNavigation";
import { useCourseDisplayName } from "../hooks/useCourseDisplayName";
import { CoursePagePillTitle } from "../components/course/CoursePagePillTitle";


interface ExamPaperDeleteResponse {
  deleted: boolean;
  exam_paper_id: number;
}

interface QuestionTemplateItem {
  id: number;
  course: string;
  question_type: string;
  difficulty: string;
  stem: string;
  options?: string[] | null;
  answer: string;
  explanation: string;
  knowledge_unit_refs: Array<Record<string, unknown>>;
  selection_hints: Record<string, unknown>;
  template_version: number;
  status: string;
  is_marked?: boolean;
  has_wrong_attempt?: boolean;
  created_at: string;
  updated_at: string;
}

interface QuestionTemplateAnswerHistoryItem {
  exam_paper_id: number;
  exam_paper_item_id: number;
  item_order: number;
  exam_mode: string;
  exam_status: string;
  submitted_at?: string | null;
  graded_at?: string | null;
  answered_at?: string | null;
  user_answer: string;
  correct_answer: string;
  is_correct?: boolean | null;
  score_obtained?: number | null;
  score_max?: number | null;
  error_cause_label?: string | null;
  feedback_text?: string | null;
  created_at: string;
}

interface QuestionTypeRegistryItem {
  id: number;
  type_key: string;
  display_name: string;
  scope: string;
  course: string;
  description: string;
  answer_format: string;
  grading_method: string;
  option_schema: Record<string, unknown>;
  rubric: Record<string, unknown>;
  source: string;
  confidence: number;
  is_system: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

type ExamPrewarmStatusValue = "ready" | "preparing" | "missing" | "failed" | "stale";

interface ExamPrewarmStatusResponse {
  status: ExamPrewarmStatusValue;
  exam_mode: string;
  num_questions: number;
  prepared_at?: string | null;
  expires_at?: string | null;
  updated_at?: string | null;
  background_requested?: boolean;
  error_message?: string | null;
}

const EXAM_PAGE_SHELL_CLASS = "mx-auto min-h-full w-full max-w-[1500px] px-4 pb-24 sm:px-6 lg:px-8 xl:px-10";
const EXAM_ALERT_CLASS = "rounded-lg border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900 shadow-sm dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300";


async function deleteExamPaper(courseId: string, paperId: number) {
  return orvalApiClient<{ data?: { code?: number; message?: string; data?: ExamPaperDeleteResponse } }>(
    `/api/v1/courses/${courseId}/exams/${paperId}`,
    {
      method: "DELETE",
    },
  );
}

async function getQuestionTemplates(courseId: string, signal?: AbortSignal) {
  return orvalApiClient<{ data?: { code?: number; message?: string; data?: QuestionTemplateItem[] } }>(
    `/api/v1/courses/${courseId}/exams/question-templates`,
    {
      method: "GET",
      signal,
    },
  );
}

async function getQuestionTemplateAnswerHistory(courseId: string, templateId: number, signal?: AbortSignal) {
  return orvalApiClient<{ data?: { code?: number; message?: string; data?: QuestionTemplateAnswerHistoryItem[] } }>(
    `/api/v1/courses/${courseId}/exams/question-templates/${templateId}/answer-history`,
    {
      method: "GET",
      signal,
    },
  );
}

async function getQuestionTypes(courseId: string, signal?: AbortSignal) {
  return orvalApiClient<{ data?: { code?: number; message?: string; data?: QuestionTypeRegistryItem[] } }>(
    `/api/v1/courses/${courseId}/exams/question-types`,
    {
      method: "GET",
      signal,
    },
  );
}

async function getExamPrewarmStatus(
  courseId: string,
  config: ReturnType<typeof loadCreateExamConfig>,
  signal?: AbortSignal,
) {
  const params = new URLSearchParams();
  params.set("exam_mode", config.examMode);
  params.set("num_questions", String(config.numQuestions));
  if (config.examMode === "paper_exam") {
    params.set("paper_layout_mode", config.paperLayoutMode);
  }
  const userPrompt = config.userPrompt.trim();
  if (userPrompt) {
    params.set("user_prompt", userPrompt);
  }
  return orvalApiClient<{ data?: { code?: number; message?: string; data?: ExamPrewarmStatusResponse } }>(
    `/api/v1/courses/${encodeURIComponent(courseId)}/exams/prewarm-status?${params.toString()}`,
    {
      method: "GET",
      signal,
    },
  );
}

function ExamPrewarmStatusIcon({
  status,
  isFetching,
  hasError,
}: {
  status?: ExamPrewarmStatusResponse | null;
  isFetching: boolean;
  hasError: boolean;
}) {
  const effectiveStatus: ExamPrewarmStatusValue = hasError
    ? "failed"
    : status?.status ?? (isFetching ? "preparing" : "missing");
  const title =
    effectiveStatus === "ready"
      ? "后台已备好一次练习或测试"
      : effectiveStatus === "preparing"
        ? "后台正在准备练习或测试"
        : effectiveStatus === "stale"
          ? "后台预生成已过期，正在刷新"
          : effectiveStatus === "failed"
            ? "后台预生成暂不可用"
            : "后台尚未备好练习或测试";
  const toneClass =
    effectiveStatus === "ready"
      ? "border-emerald-200 bg-emerald-50 text-emerald-600 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300"
      : effectiveStatus === "preparing"
        ? "border-indigo-200 bg-indigo-50 text-indigo-600 dark:border-indigo-900/60 dark:bg-indigo-950/30 dark:text-indigo-300"
        : effectiveStatus === "failed" || effectiveStatus === "stale"
          ? "border-amber-200 bg-amber-50 text-amber-600 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300"
          : "border-slate-200 bg-slate-50 text-slate-400 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-500";

  return (
    <span
      className={`inline-grid h-6 w-6 shrink-0 place-items-center rounded-full border ${toneClass}`}
      title={title}
      aria-label={title}
      role="status"
    >
      {effectiveStatus === "ready" ? (
        <CheckCircle2 className="h-3.5 w-3.5" />
      ) : effectiveStatus === "preparing" ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <CloudOff className="h-3.5 w-3.5" />
      )}
    </span>
  );
}


export function ExamsPage() {
  const { courseId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { mode: examResultDisplayMode } = useExamResultDisplayPreference();
  const [isCreateConfigOpen, setIsCreateConfigOpen] = useState(false);
  const [createConfigRevision, setCreateConfigRevision] = useState(0);
  const [expandedGroups, setExpandedGroups] = useState({
    active: true,
    completed: true,
  });
  const { courseName } = useCourseDisplayName(courseId);

  const currentCreateConfig = useMemo(
    () => (courseId ? loadCreateExamConfig(courseId) : null),
    [createConfigRevision, courseId],
  );
  const prewarmStatusQuery = useQuery({
    queryKey: [
      "exam-prewarm-status",
      courseId,
      currentCreateConfig?.examMode,
      currentCreateConfig?.numQuestions,
      currentCreateConfig?.paperLayoutMode,
      currentCreateConfig?.userPrompt.trim(),
    ],
    enabled: Boolean(courseId && currentCreateConfig),
    queryFn: async ({ signal }) => {
      if (!courseId || !currentCreateConfig) return null;
      const response = await getExamPrewarmStatus(courseId, currentCreateConfig, signal);
      return unwrapOrvalResponse<ExamPrewarmStatusResponse>(response);
    },
    staleTime: 30_000,
    refetchInterval: (query) => (query.state.data?.status === "preparing" ? 8000 : false),
  });

  const historyQuery = useExamHistoryApiV1CoursesCourseIdExamsHistoryGet(courseId ?? "", { page: 1, size: 24 });
  const history = useMemo(
    () => unwrapOrvalResponse<{ items?: ExamHistoryItem[] }>(historyQuery.data),
    [historyQuery.data],
  );
  const historyItems = history?.items ?? [];
  const generatingPaperIds = useMemo(
    () =>
      historyItems
        .filter((item) => item.status === "generating")
        .map((item) => item.id)
        .filter((id): id is number => Number.isFinite(id)),
    [historyItems],
  );
  const generatingPaperIdsKey = generatingPaperIds.join(",");

  useEffect(() => {
    if (!courseId || !generatingPaperIds.length) return;

    const historyQueryKey = getExamHistoryApiV1CoursesCourseIdExamsHistoryGetQueryKey(courseId, {
      page: 1,
      size: 24,
    });
    const refreshHistory = () => {
      void queryClient.invalidateQueries({ queryKey: historyQueryKey });
    };
    const applySnapshot = (event: Event) => {
      const payload = parseExamGenerationSnapshot((event as MessageEvent<string>).data);
      if (!payload.exam_paper_id) {
        refreshHistory();
        return;
      }
      queryClient.setQueryData(historyQueryKey, (current: unknown) =>
        patchExamHistoryQueryData(current, payload),
      );
    };

    const streams = generatingPaperIds.map((paperId) => {
      const stream = new EventSource(
        buildApiUrl(`/api/v1/courses/${encodeURIComponent(courseId)}/exams/${paperId}/stream`),
        { withCredentials: true },
      );
      const unregisterEventSource = registerBackendEventSource(stream);
      const handleSnapshot = (event: Event) => {
        applySnapshot(event);
      };
      const handleDone = (event: Event) => {
        applySnapshot(event);
        refreshHistory();
        unregisterEventSource();
        stream.close();
      };

      stream.addEventListener("snapshot", handleSnapshot);
      stream.addEventListener("done", handleDone);
      stream.onerror = () => {
        reportBackendConnectionIssue("exam_stream_error");
        refreshHistory();
      };

      return { stream, handleSnapshot, handleDone, unregisterEventSource };
    });

    return () => {
      streams.forEach(({ stream, handleSnapshot, handleDone, unregisterEventSource }) => {
        unregisterEventSource();
        stream.removeEventListener("snapshot", handleSnapshot);
        stream.removeEventListener("done", handleDone);
        stream.close();
      });
    };
  }, [generatingPaperIdsKey, queryClient, courseId]);

  const activeHistoryItems = useMemo(
    () => historyItems.filter((item) => item.status !== "graded"),
    [historyItems],
  );
  const completedHistoryItems = useMemo(
    () => historyItems.filter((item) => item.status === "graded"),
    [historyItems],
  );

  const deleteExamMutation = useMutation({
    mutationFn: async (paperId: number) => {
      if (!courseId) {
        throw new Error("缺少课程标识，无法删除记录。");
      }
      return deleteExamPaper(courseId, paperId);
    },
    onSuccess: async (_response, paperId) => {
      await queryClient.invalidateQueries({
        queryKey: getExamHistoryApiV1CoursesCourseIdExamsHistoryGetQueryKey(courseId ?? "", { page: 1, size: 24 }),
      });
      toast({
        title: "记录已删除",
        description: `已删除记录 #${paperId}。`,
        variant: "success",
      });
    },
    onError: (error) => {
      toast({
        title: "删除失败",
        description: getApiErrorMessage(error, "请稍后重试"),
        variant: "error",
      });
    },
  });

  const generateExam = useGenerateExamApiV1CoursesCourseIdExamsGeneratePost({
    mutation: {
      onSuccess: async (response, variables) => {
        const created = unwrapOrvalResponse(response);
        if (!created?.exam_paper_id) return;
        const isMasteryDrill = variables.data.exam_mode === MASTERY_DRILL_EXAM_MODE;
        await queryClient.invalidateQueries({
          queryKey: getExamHistoryApiV1CoursesCourseIdExamsHistoryGetQueryKey(courseId ?? "", { page: 1, size: 24 }),
        });
        await queryClient.invalidateQueries({ queryKey: ["exam-prewarm-status", courseId ?? ""] });
        navigate(buildCourseSubPath(courseId ?? "", "exams", created.exam_paper_id));
        toast({
          title: isMasteryDrill ? "闯关训练已开始" : "内容已创建",
          description: isMasteryDrill
            ? `已准备 ${created.num_questions} 题，答错会重新回到队列。`
            : `已生成 ${created.num_questions} 题，马上开始。`,
          variant: "success",
        });
      },
      onError: (error) => {
        toast({
          title: "创建失败",
          description: getApiErrorMessage(error, "请稍后重试"),
          variant: "error",
        });
      },
    },
  });

  const handleCreateExam = () => {
    if (!courseId || generateExam.isPending) return;
    const config = currentCreateConfig ?? loadCreateExamConfig(courseId);
    generateExam.mutate({
      courseId,
      data: toExamGenerateRequest(config),
    });
  };

  const handleStartMasteryDrill = () => {
    if (!courseId || generateExam.isPending) return;
    generateExam.mutate({
      courseId,
      data: {
        exam_mode: MASTERY_DRILL_EXAM_MODE,
        num_questions: MASTERY_DRILL_QUESTION_COUNT,
      },
    });
  };

  if (!courseId) {
    return (
      <div className={EXAM_PAGE_SHELL_CLASS}>
        <div className={EXAM_ALERT_CLASS}>
          缺少课程标识，暂时无法加载训练中心。
        </div>
      </div>
    );
  }

  return (
    <>
      <div className={EXAM_PAGE_SHELL_CLASS}>
        <div className="flex flex-col gap-6">
          <CoursePagePillTitle icon={ClipboardCheck} label="训练中心" />

          <section className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl space-y-3">
              <div className="hidden items-center gap-2 rounded-full border border-slate-200/80 bg-white/70 px-3 py-1 text-xs font-medium text-slate-500 backdrop-blur dark:border-slate-700/80 dark:bg-slate-800/70 dark:text-slate-400">
                <FileText className="h-3.5 w-3.5" />
                训练中心
              </div>
              <div>
                <h1 className="break-words text-3xl font-semibold text-slate-950 dark:text-slate-100 sm:text-[34px]">
                  {courseName ?? "当前课程"}
                </h1>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500 dark:text-slate-400 sm:text-[15px]">
                  开始专项练习、闯关训练或整卷测试，并回看历史得分与题目沉淀。
                </p>
              </div>
            </div>

            <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap xl:justify-end">
              <Button
                size="lg"
                className="!h-12 w-full rounded-[10px] bg-black px-6 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-slate-900 sm:w-auto"
                onClick={handleStartMasteryDrill}
                disabled={generateExam.isPending}
              >
                {generateExam.isPending && generateExam.variables?.data.exam_mode === MASTERY_DRILL_EXAM_MODE ? (
                  <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4 shrink-0" />
                )}
                开始闯关训练
              </Button>
              <div className="flex w-full items-center gap-2 sm:w-auto">
                <div className="inline-flex h-12 w-full overflow-hidden rounded-[10px] border border-slate-200 bg-white text-slate-900 shadow-sm transition-colors hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:bg-slate-800 sm:w-auto">
                  <button
                    type="button"
                    className="flex min-w-0 flex-1 items-center justify-center gap-2 px-6 text-sm font-semibold focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 focus-visible:ring-offset-white active:scale-[0.99] sm:flex-none"
                    onClick={handleCreateExam}
                    disabled={generateExam.isPending}
                  >
                    {generateExam.isPending && generateExam.variables?.data.exam_mode !== MASTERY_DRILL_EXAM_MODE ? (
                      <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
                    ) : (
                      <Plus className="h-4 w-4 shrink-0" />
                    )}
                    <span className="whitespace-nowrap">
                      {generateExam.isPending && generateExam.variables?.data.exam_mode !== MASTERY_DRILL_EXAM_MODE
                        ? "创建中..."
                        : currentCreateConfig?.examMode === "paper_exam"
                          ? "创建整卷测试"
                          : "开始专项练习"}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="grid h-full w-10 shrink-0 place-items-center border-l border-slate-200 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
                    onClick={() => setIsCreateConfigOpen(true)}
                    aria-label="更多训练与测试设置"
                    title="更多设置"
                  >
                    <MoreVertical className="h-4 w-4" />
                  </button>
                </div>
                <ExamPrewarmStatusIcon
                  status={prewarmStatusQuery.data}
                  isFetching={prewarmStatusQuery.isFetching}
                  hasError={prewarmStatusQuery.isError}
                />
              </div>
              <Button
                size="lg"
                variant="outline"
                className="!h-12 w-full rounded-[10px] px-6 text-sm font-semibold text-slate-800 dark:border-slate-700 dark:text-slate-200 sm:w-auto"
                onClick={() => navigate(buildCourseSubPath(courseId, "exams", "question-templates"))}
              >
                <BookOpen className="h-4 w-4" />
                题库查看
              </Button>
              <Button
                size="lg"
                variant="outline"
                className="!h-12 w-full rounded-[10px] px-6 text-sm font-semibold text-slate-800 dark:border-slate-700 dark:text-slate-200 sm:w-auto"
                onClick={() => navigate(buildCourseSubPath(courseId, "exams", "question-types"))}
              >
                <Tags className="h-4 w-4" />
                题型查看
              </Button>
            </div>
          </section>

          <section>
            <div className="space-y-6">
              {historyQuery.isLoading && (
                <div className="rounded-[28px] border border-slate-200 bg-slate-50 px-5 py-10 text-center text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
                  正在加载记录列表...
                </div>
              )}

              {historyQuery.error && (
                <div className="rounded-[28px] border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
                  {getApiErrorMessage(historyQuery.error, "加载记录列表失败")}
                </div>
              )}


              {[
                { key: "active" as const, title: "待完成的记录", items: activeHistoryItems },
                { key: "completed" as const, title: "已完成的记录", items: completedHistoryItems },
              ].map((group) => (
                <div key={group.key} className="space-y-4">
                  <button
                    type="button"
                    onClick={() =>
                      setExpandedGroups((current) => ({
                        ...current,
                        [group.key]: !current[group.key],
                      }))
                    }
                    className="flex w-full items-center gap-5 px-1 py-2 text-left"
                  >
                    <h3 className="shrink-0 text-lg font-semibold text-slate-950 dark:text-slate-100">
                      {group.title}({group.items.length})
                    </h3>
                    <div className="h-px flex-1 bg-slate-200 dark:bg-slate-800" />
                    <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-slate-500 dark:text-slate-400">
                      <ChevronDown
                        className={`h-5 w-5 transition-transform ${
                          expandedGroups[group.key] ? "rotate-180" : ""
                        }`}
                      />
                    </div>
                  </button>

                  {expandedGroups[group.key] && (
                    <div className="mt-2 rounded-[24px] bg-white p-6 shadow-sm ring-1 ring-slate-900/5 dark:bg-slate-900/40 dark:ring-slate-800">
                      {group.items.length === 0 ? (
                        <div className="px-1 py-1 text-sm text-slate-500 dark:text-slate-400">这个分组下暂时没有记录。</div>
                      ) : (
                        <div className="grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-5">
                          {group.items.map((item: ExamHistoryItem) => {
                            const isDeleting = deleteExamMutation.isPending && deleteExamMutation.variables === item.id;

                            const handleDeleteExam = (event: MouseEvent<HTMLButtonElement>) => {
                              event.stopPropagation();
                              if (isDeleting) return;
                              const confirmed = window.confirm(
                                `确认删除这份记录吗？\n\n${buildExamTitle(item)}\n\n删除后无法恢复。`,
                              );
                              if (!confirmed) return;
                              deleteExamMutation.mutate(item.id);
                            };

                            return (
                              <ExamPaperCard
                                key={item.id}
                                item={item}
                                resultDisplayMode={examResultDisplayMode}
                                isDeleting={isDeleting}
                                onOpen={() => navigate(buildCourseSubPath(courseId, "exams", item.id))}
                                onDelete={handleDeleteExam}
                              />
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>

      <CreateExamModal
        open={isCreateConfigOpen}
        courseId={courseId}
        courseName={courseName}
        onClose={() => {
          setIsCreateConfigOpen(false);
          setCreateConfigRevision((current) => current + 1);
        }}
      />
    </>
  );
}

function JsonBadge({ value }: { value: unknown }) {
  const text = JSON.stringify(value ?? {}, null, 2);
  if (!text || text === "{}" || text === "[]") {
    return <span className="text-sm text-slate-400">无</span>;
  }
  return (
    <pre className="max-h-40 overflow-auto border-l-2 border-slate-200 pl-3 text-xs leading-5 text-slate-600 dark:border-slate-700 dark:text-slate-300">
      {text}
    </pre>
  );
}

function KnowledgeRefTags({ refs }: { refs: Array<Record<string, unknown>> }) {
  if (!refs.length) {
    return <span className="text-sm text-slate-400">无</span>;
  }

  return (
    <div className="flex flex-wrap gap-2">
      {refs.map((ref, index) => {
        const unitId = ref.knowledge_unit_id ?? ref.unit_id ?? "unknown";
        const role = String(ref.role ?? "related");
        const weight = Number(ref.coverage_weight ?? 1);
        const weightLabel = Number.isFinite(weight) ? weight.toFixed(2).replace(/\.?0+$/, "") : "1";

        return (
          <span
            key={`${String(unitId)}-${role}-${index}`}
            className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
          >
            <span className="text-slate-950 dark:text-slate-100">知识点 #{String(unitId)}</span>
            <span className="text-slate-400">|</span>
            <span>{role}</span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              {weightLabel}
            </span>
          </span>
        );
      })}
    </div>
  );
}

function QuestionTemplatePlainSection({
  title,
  children,
  showDivider = true,
}: {
  title: string;
  children: ReactNode;
  showDivider?: boolean;
}) {
  return (
    <section className={showDivider ? "border-t border-slate-200 pt-5 dark:border-slate-800" : ""}>
      <h3 className="font-serif text-lg font-bold text-slate-950 dark:text-slate-100">{title}</h3>
      <div className="mt-3 break-words text-sm leading-8 text-slate-700 dark:text-slate-300 [&_p]:mb-2 [&_.katex-display]:my-3">
        {children}
      </div>
    </section>
  );
}

function formatOptionLabel(index: number) {
  let value = index;
  let label = "";
  do {
    label = String.fromCharCode(65 + (value % 26)) + label;
    value = Math.floor(value / 26) - 1;
  } while (value >= 0);
  return label;
}

function buildQuestionTemplateContent(item: QuestionTemplateItem, emptyText: string) {
  const stem = item.stem || emptyText;
  const options = (item.options ?? []).map((option, index) => `${formatOptionLabel(index)}. ${option}`);
  return [stem, ...options].join("\n\n");
}

function getPrimaryKnowledgeUnitLabel(item: QuestionTemplateItem) {
  const primaryRef = item.knowledge_unit_refs.find((ref) => String(ref.role ?? "") === "primary") ?? item.knowledge_unit_refs[0];
  const unitId = primaryRef?.knowledge_unit_id ?? primaryRef?.unit_id;
  return unitId == null ? "未绑定" : String(unitId);
}

function formatQuestionTemplateHistoryTime(value?: string | null) {
  if (!value) return "暂无时间";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function getQuestionTemplateHistoryModeLabel(mode: string) {
  const labels: Record<string, string> = {
    web_practice: "专项练习",
    paper_exam: "整卷测试",
    mastery_drill: "闯关训练",
    practice: "练习",
    diagnostic: "诊断测验",
    weakpoint_boost: "弱点强化",
    review: "复习",
    mock_final: "模拟考试",
  };
  return labels[mode] ?? mode;
}

function getQuestionTemplateHistoryResultLabel(item: QuestionTemplateAnswerHistoryItem) {
  if (item.is_correct === true) return "正确";
  if (item.is_correct === false) return "需巩固";
  return "待批改";
}

function getQuestionTemplateHistoryResultClass(item: QuestionTemplateAnswerHistoryItem) {
  if (item.is_correct === true) {
    return "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200";
  }
  if (item.is_correct === false) {
    return "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200";
  }
  return "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300";
}

function formatQuestionTemplateScore(item: QuestionTemplateAnswerHistoryItem) {
  if (item.score_obtained == null || item.score_max == null) return null;
  return `${item.score_obtained}/${item.score_max} 分`;
}

function QuestionTemplateCard({
  item,
  questionTypeLabel,
  onOpen,
}: {
  item: QuestionTemplateItem;
  questionTypeLabel: string;
  onOpen: () => void;
}) {
  const previewContent = buildQuestionTemplateContent(item, "暂无题干内容");

  return (
    <button
      type="button"
      onClick={onOpen}
      className="group relative h-[360px] rounded-[26px] text-left outline-none transition duration-200 hover:-translate-y-1 focus-visible:ring-4 focus-visible:ring-indigo-200 dark:focus-visible:ring-indigo-500/25"
      aria-label={`查看题目模板 ${item.id}`}
    >
      <span className="absolute inset-x-4 bottom-[-10px] h-8 rounded-[24px] bg-slate-300/35 blur-xl transition group-hover:bg-indigo-300/30" />
      <span className="relative flex h-full flex-col overflow-hidden rounded-[26px] border border-slate-200 bg-white px-5 py-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.95),inset_0_-10px_24px_rgba(15,23,42,0.03),0_18px_38px_-24px_rgba(15,23,42,0.45)] transition group-hover:border-indigo-200 group-hover:shadow-[inset_0_1px_0_rgba(255,255,255,0.95),inset_0_-10px_24px_rgba(99,102,241,0.04),0_24px_42px_-24px_rgba(15,23,42,0.55)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_18px_42px_-30px_rgba(0,0,0,0.9)] dark:group-hover:border-indigo-500/40">
        <span className="pointer-events-none absolute inset-y-0 left-0 w-8 border-r border-slate-200/90 bg-[repeating-linear-gradient(180deg,rgba(148,163,184,0.22)_0px,rgba(148,163,184,0.22)_1px,transparent_1px,transparent_24px)] dark:border-slate-800 dark:bg-[repeating-linear-gradient(180deg,rgba(71,85,105,0.32)_0px,rgba(71,85,105,0.32)_1px,transparent_1px,transparent_24px)]" />
        <span className="pointer-events-none absolute right-4 top-4 h-12 w-12 rounded-full bg-indigo-50 blur-2xl" />
        {item.is_marked ? (
          <span className="pointer-events-none absolute left-4 top-0 z-20 h-[72px] w-5 drop-shadow-[0_8px_10px_rgba(127,29,29,0.28)]">
            <span
              className="absolute inset-0 bg-gradient-to-b from-red-500 via-red-600 to-red-700 shadow-[inset_1px_0_0_rgba(255,255,255,0.32),inset_-1px_0_0_rgba(127,29,29,0.36)]"
              style={{ clipPath: "polygon(0 0, 100% 0, 100% 100%, 50% 84%, 0 100%)" }}
            />
            <span className="absolute inset-x-0 top-0 h-1 bg-white/35" />
            <span className="absolute left-[4px] top-2 h-12 w-px rounded-full bg-white/30" />
          </span>
        ) : null}

        <span className="relative flex items-center justify-between gap-3 pl-8">
          <span className="inline-flex min-w-0 items-center gap-2 text-[12px] font-semibold text-slate-600 dark:text-slate-300">
            <FileText className="h-4 w-4 shrink-0 text-indigo-600" />
            <span className="truncate">{questionTypeLabel}</span>
          </span>
          <span className="inline-flex shrink-0 items-center gap-1.5 text-[11px] font-semibold">
            <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
              #{item.id}
            </span>
            <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {formatDifficultyLabel(item.difficulty)}
            </span>
          </span>
        </span>

        <span className="relative mt-4 flex min-h-0 flex-1 flex-col pl-8">
          <span className="relative block min-h-0 flex-1 overflow-hidden text-[15px] leading-7 text-slate-900 dark:text-slate-200">
            <ExamMarkdown content={previewContent} />
            <span className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-white via-white/95 to-transparent dark:from-slate-950 dark:via-slate-950/95" />
          </span>
        </span>

        <span className="relative mt-5 flex items-center gap-3 border-t border-slate-200 pl-8 pt-4 dark:border-slate-800">
          <span className="truncate text-xs font-medium text-slate-500 dark:text-slate-400">
            知识单元 #{getPrimaryKnowledgeUnitLabel(item)}
          </span>
        </span>
      </span>
    </button>
  );
}

function QuestionTemplateDetailCard({
  item,
  courseId,
  questionTypeLabel,
  onClose,
}: {
  item: QuestionTemplateItem | null;
  courseId: string;
  questionTypeLabel: string;
  onClose: () => void;
}) {
  const questionContent = item ? buildQuestionTemplateContent(item, "暂无题干") : "";
  const historyQuery = useQuery({
    queryKey: ["question-template-answer-history", courseId, item?.id],
    enabled: Boolean(courseId && item?.id),
    queryFn: async ({ signal }) => {
      const response = await getQuestionTemplateAnswerHistory(courseId, item?.id ?? 0, signal);
      return unwrapOrvalResponse<QuestionTemplateAnswerHistoryItem[]>(response) ?? [];
    },
  });
  const historyItems = historyQuery.data ?? [];

  return (
    <Modal
      open={Boolean(item)}
      onClose={onClose}
      title={item ? `题目模板 #${item.id}` : undefined}
      className="max-w-4xl rounded-[26px]"
    >
      {item ? (
        <div className="space-y-6">
          <header className="border-b border-slate-200 pb-5 dark:border-slate-800">
            <div className="min-w-0">
              <h2 className="font-serif text-2xl font-bold text-slate-950 dark:text-slate-100">
                {questionTypeLabel}
              </h2>
              <div className="mt-3 break-words text-sm leading-8 text-slate-700 dark:text-slate-300 [&_p]:mb-2 [&_.katex-display]:my-3">
                <ExamMarkdown content={questionContent} />
              </div>
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-500 dark:text-slate-400">
              {item.is_marked ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-950 px-3 py-1 text-xs font-semibold text-white dark:bg-slate-100 dark:text-slate-900">
                  <Bookmark className="h-3.5 w-3.5 fill-current" />
                  已标记
                </span>
              ) : null}
              <span className="rounded-full bg-slate-100 px-2.5 py-1 dark:bg-slate-800">{formatDifficultyLabel(item.difficulty)}</span>
              <span className="rounded-full bg-slate-100 px-2.5 py-1 dark:bg-slate-800">{item.status}</span>
              <span className="rounded-full bg-slate-100 px-2.5 py-1 dark:bg-slate-800">v{item.template_version}</span>
              <span className="text-slate-400">
                更新 {formatQuestionTemplateHistoryTime(item.updated_at || item.created_at)}
              </span>
            </div>
          </header>

          <QuestionTemplatePlainSection title="标准答案" showDivider={false}>
            <ExamMarkdown content={item.answer || "暂无答案"} />
          </QuestionTemplatePlainSection>

          <QuestionTemplatePlainSection title="解析">
            <ExamMarkdown content={item.explanation || "暂无解析"} />
          </QuestionTemplatePlainSection>

          <QuestionTemplatePlainSection title="知识点应用">
            <KnowledgeRefTags refs={item.knowledge_unit_refs} />
          </QuestionTemplatePlainSection>

          <QuestionTemplatePlainSection title="历史答题记录">
            {historyQuery.isLoading ? (
              <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
                <Loader2 className="h-4 w-4 animate-spin" />
                正在加载历史记录...
              </div>
            ) : historyQuery.error ? (
              <div className="rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-200">
                {getApiErrorMessage(historyQuery.error, "历史记录加载失败")}
              </div>
            ) : historyItems.length > 0 ? (
              <div className="space-y-4">
                {historyItems.map((record) => {
                  const scoreText = formatQuestionTemplateScore(record);

                  return (
                    <article
                      key={`${record.exam_paper_id}-${record.exam_paper_item_id}`}
                      className="rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-4 dark:border-slate-800 dark:bg-slate-900/70"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${getQuestionTemplateHistoryResultClass(record)}`}>
                          {getQuestionTemplateHistoryResultLabel(record)}
                        </span>
                        <span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-slate-600 ring-1 ring-inset ring-slate-200 dark:bg-slate-950 dark:text-slate-300 dark:ring-slate-800">
                          {getQuestionTemplateHistoryModeLabel(record.exam_mode)}
                        </span>
                        <span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-slate-600 ring-1 ring-inset ring-slate-200 dark:bg-slate-950 dark:text-slate-300 dark:ring-slate-800">
                          记录 #{record.exam_paper_id} · 第 {record.item_order} 题
                        </span>
                        {scoreText ? (
                          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">{scoreText}</span>
                        ) : null}
                        <span className="text-xs font-medium text-slate-400">
                          {formatQuestionTemplateHistoryTime(record.answered_at ?? record.submitted_at ?? record.created_at)}
                        </span>
                      </div>
                      <div className="mt-4 space-y-4 border-t border-slate-200 pt-4 dark:border-slate-800">
                        <div>
                          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">我的答案</p>
                          <ExamMarkdown content={record.user_answer || "未作答"} />
                        </div>
                        <div>
                          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">参考答案</p>
                          <ExamMarkdown content={record.correct_answer || "暂无答案"} />
                        </div>
                        {record.feedback_text || record.error_cause_label ? (
                          <div className="border-t border-dashed border-slate-200 pt-3 dark:border-slate-800">
                            {record.error_cause_label ? (
                              <p className="font-semibold text-slate-700 dark:text-slate-200">原因：{record.error_cause_label}</p>
                            ) : null}
                            {record.feedback_text ? <ExamMarkdown content={record.feedback_text} /> : null}
                          </div>
                        ) : null}
                      </div>
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-5 py-6 text-center text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
                这道题还没有历史答题记录。
              </div>
            )}
          </QuestionTemplatePlainSection>

          <QuestionTemplatePlainSection title="选择提示">
            <JsonBadge value={item.selection_hints} />
          </QuestionTemplatePlainSection>
        </div>
      ) : null}
    </Modal>
  );
}

function getQuestionTypeScopeLabel(scope: string) {
  if (scope === "global") return "基础题型";
  if (scope === "course") return "课程题型";
  return scope || "未分组";
}

function getQuestionTypeSourceLabel(source: string) {
  if (!source) return "未标注来源";
  if (source === "system") return "系统内置";
  if (source === "sample") return "样卷学习";
  if (source === "manual") return "人工配置";
  return source;
}

function getQuestionTypeConfidenceLabel(confidence: number) {
  const value = Number(confidence);
  if (!Number.isFinite(value)) return "置信度 --";
  return `置信度 ${Math.round(value * 100)}%`;
}

function hasUsefulRecord(value: unknown) {
  return Boolean(value && typeof value === "object" && Object.keys(value).length > 0);
}

function QuestionTypeCard({ item, onOpen }: { item: QuestionTypeRegistryItem; onOpen: () => void }) {
  const description = item.description || "暂无描述";
  const answerFormat = item.answer_format || "未配置答案格式";

  return (
    <button
      type="button"
      onClick={onOpen}
      className="group relative h-[340px] rounded-[26px] text-left outline-none transition duration-200 hover:-translate-y-1 focus-visible:ring-4 focus-visible:ring-indigo-200 dark:focus-visible:ring-indigo-500/25"
      aria-label={`查看题型 ${item.display_name || item.type_key}`}
    >
      <span className="absolute inset-x-4 bottom-[-10px] h-8 rounded-[24px] bg-slate-300/35 blur-xl transition group-hover:bg-indigo-300/30" />
      <span className="relative flex h-full flex-col overflow-hidden rounded-[26px] border border-slate-200 bg-white px-5 py-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.95),inset_0_-10px_24px_rgba(15,23,42,0.03),0_18px_38px_-24px_rgba(15,23,42,0.45)] transition group-hover:border-indigo-200 group-hover:shadow-[inset_0_1px_0_rgba(255,255,255,0.95),inset_0_-10px_24px_rgba(99,102,241,0.04),0_24px_42px_-24px_rgba(15,23,42,0.55)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_18px_42px_-30px_rgba(0,0,0,0.9)] dark:group-hover:border-indigo-500/40">
        <span className="pointer-events-none absolute inset-y-0 left-0 w-8 border-r border-slate-200/90 bg-[repeating-linear-gradient(180deg,rgba(148,163,184,0.22)_0px,rgba(148,163,184,0.22)_1px,transparent_1px,transparent_24px)] dark:border-slate-800 dark:bg-[repeating-linear-gradient(180deg,rgba(71,85,105,0.32)_0px,rgba(71,85,105,0.32)_1px,transparent_1px,transparent_24px)]" />
        <span className="pointer-events-none absolute right-4 top-4 h-12 w-12 rounded-full bg-indigo-50 blur-2xl" />

        <span className="relative flex items-center justify-between gap-3 pl-8">
          <span className="inline-flex min-w-0 items-center gap-2 text-[13px] font-semibold text-slate-700 dark:text-slate-300">
            <Tags className="h-4 w-4 shrink-0 text-indigo-600" />
            <span className="truncate">{item.display_name || item.type_key}</span>
          </span>
          <span className="inline-flex shrink-0 items-center gap-1.5 text-[11px] font-semibold">
            <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
              #{item.id}
            </span>
            <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {getQuestionTypeScopeLabel(item.scope)}
            </span>
          </span>
        </span>

        <span className="relative mt-4 flex min-h-0 flex-1 flex-col pl-8">
          <span className="font-mono text-[11px] font-semibold text-slate-400">{item.type_key}</span>
          <span className="relative mt-3 block min-h-0 flex-1 overflow-hidden text-sm leading-7 text-slate-700 dark:text-slate-300">
            <span className="block">{description}</span>
            <span className="mt-4 block rounded-2xl border border-slate-200 bg-slate-50/70 px-3.5 py-3 text-slate-600 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-300">
              <span className="mb-1 block text-[11px] font-semibold text-slate-400">答案格式</span>
              <span className="line-clamp-2">{answerFormat}</span>
            </span>
            <span className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-white via-white/95 to-transparent dark:from-slate-950 dark:via-slate-950/95" />
          </span>
        </span>

        <span className="relative mt-5 grid grid-cols-2 gap-2 border-t border-slate-200 pl-8 pt-4 text-[11px] font-semibold text-slate-500 dark:border-slate-800 dark:text-slate-400">
          <span className="truncate rounded-full border border-slate-200 bg-white px-2.5 py-1 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            {item.grading_method || "未配置评分"}
          </span>
          <span className="truncate rounded-full border border-slate-200 bg-white px-2.5 py-1 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            {getQuestionTypeSourceLabel(item.source)}
          </span>
          <span className="truncate rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            选项{hasUsefulRecord(item.option_schema) ? "已配置" : "无"}
          </span>
          <span className="truncate rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            {getQuestionTypeConfidenceLabel(item.confidence)}
          </span>
        </span>
      </span>
    </button>
  );
}

function QuestionTypeDetailCard({ item, onClose }: { item: QuestionTypeRegistryItem | null; onClose: () => void }) {
  return (
    <Modal
      open={Boolean(item)}
      onClose={onClose}
      title={item ? `题型 ${item.display_name || item.type_key}` : undefined}
      className="max-w-4xl rounded-[26px]"
    >
      {item ? (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-slate-950 px-3 py-1 text-xs font-semibold text-white dark:bg-slate-100 dark:text-slate-900">
              {getQuestionTypeScopeLabel(item.scope)}
            </span>
            <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300">
              {getQuestionTypeSourceLabel(item.source)}
            </span>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {item.is_active ? "启用中" : "已停用"}
            </span>
            {item.is_system && (
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                系统内置
              </span>
            )}
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {getQuestionTypeConfidenceLabel(item.confidence)}
            </span>
          </div>

          <section>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">题型标识</p>
            <div className="mt-3 rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_18px_36px_-28px_rgba(0,0,0,0.72)]">
              <h3 className="text-xl font-semibold text-slate-950 dark:text-slate-100">{item.display_name || item.type_key}</h3>
              <p className="mt-2 font-mono text-xs text-slate-500 dark:text-slate-400">{item.type_key}</p>
              <p className="mt-4 text-sm leading-7 text-slate-600 dark:text-slate-300">{item.description || "暂无描述"}</p>
            </div>
          </section>

          <div className="grid gap-5 lg:grid-cols-2">
            <section className="rounded-2xl border border-slate-200 bg-slate-50/70 px-5 py-4 dark:border-slate-800 dark:bg-slate-900/70">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">答案格式</p>
              <div className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-300">{item.answer_format || "未配置"}</div>
            </section>
            <section className="rounded-2xl border border-slate-200 bg-slate-50/70 px-5 py-4 dark:border-slate-800 dark:bg-slate-900/70">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">评分方式</p>
              <div className="mt-3 text-sm leading-7 text-slate-700 dark:text-slate-300">{item.grading_method || "未配置"}</div>
            </section>
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            <section>
              <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">选项结构</p>
              <JsonBadge value={item.option_schema} />
            </section>
            <section>
              <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">评分规则</p>
              <JsonBadge value={item.rubric} />
            </section>
          </div>
        </div>
      ) : null}
    </Modal>
  );
}

function ExamCatalogShell({
  courseId,
  eyebrow,
  title,
  description,
  children,
}: {
  courseId: string;
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  const navigate = useNavigate();
  return (
    <div className={EXAM_PAGE_SHELL_CLASS}>
      <div className="flex flex-col gap-6">
        <header>
          <button
            type="button"
            onClick={() => navigate(buildCoursePath(courseId, "exams"))}
            className="inline-flex items-center gap-2 text-sm font-medium text-slate-500 transition hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
          >
            <ArrowLeft className="h-4 w-4" />
            返回训练中心
          </button>
          <div className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-slate-200/80 bg-white/70 px-3 py-1 text-xs font-medium text-slate-500 backdrop-blur dark:border-slate-700/80 dark:bg-slate-800/70 dark:text-slate-400">
                <Sparkles className="h-3.5 w-3.5 text-indigo-500" />
                {eyebrow}
              </div>
              <h1 className="mt-4 text-3xl font-semibold text-slate-950 dark:text-slate-100 sm:text-[34px]">
                {title}
              </h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500 dark:text-slate-400 sm:text-[15px]">
                {description}
              </p>
            </div>
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}

export function QuestionTemplatesPage() {
  const { courseId } = useParams();
  const [selectedTemplate, setSelectedTemplate] = useState<QuestionTemplateItem | null>(null);
  const [showMarkedOnly, setShowMarkedOnly] = useState(false);
  const [showWrongOnly, setShowWrongOnly] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const templatesQuery = useQuery({
    queryKey: ["exam-question-templates", courseId],
    enabled: Boolean(courseId),
    queryFn: async ({ signal }) => {
      const response = await getQuestionTemplates(courseId ?? "", signal);
      return unwrapOrvalResponse<QuestionTemplateItem[]>(response) ?? [];
    },
  });
  const templates = templatesQuery.data ?? [];
  const markedTemplates = useMemo(
    () => templates.filter((item) => item.is_marked === true),
    [templates],
  );
  const wrongTemplates = useMemo(
    () => templates.filter((item) => item.has_wrong_attempt === true),
    [templates],
  );

  const typesQuery = useQuery({
    queryKey: ["exam-question-types", courseId],
    enabled: Boolean(courseId),
    queryFn: async ({ signal }) => {
      const response = await getQuestionTypes(courseId ?? "", signal);
      return unwrapOrvalResponse<QuestionTypeRegistryItem[]>(response) ?? [];
    },
  });
  const questionTypeLabelByKey = useMemo(() => {
    const labels = new Map<string, string>();
    for (const item of typesQuery.data ?? []) {
      const key = item.type_key?.trim();
      const label = item.display_name?.trim();
      if (key && label) {
        labels.set(key, label);
      }
    }
    return labels;
  }, [typesQuery.data]);
  const getQuestionTypeLabel = (typeKey: string) => questionTypeLabelByKey.get(typeKey) ?? typeKey;
  const normalizedSearchQuery = searchQuery.trim().toLowerCase();
  const visibleTemplates = useMemo(() => {
    let baseTemplates = templates;
    if (showMarkedOnly) {
      baseTemplates = baseTemplates.filter((item) => item.is_marked === true);
    }
    if (showWrongOnly) {
      baseTemplates = baseTemplates.filter((item) => item.has_wrong_attempt === true);
    }
    if (!normalizedSearchQuery) {
      return baseTemplates;
    }
    return baseTemplates.filter((item) => {
      const searchableText = [
        String(item.id),
        item.question_type,
        getQuestionTypeLabel(item.question_type),
        item.difficulty,
        item.status,
        getPrimaryKnowledgeUnitLabel(item),
        buildQuestionTemplateContent(item, ""),
        item.answer,
        item.explanation,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return searchableText.includes(normalizedSearchQuery);
    });
  }, [normalizedSearchQuery, questionTypeLabelByKey, showMarkedOnly, showWrongOnly, templates]);

  const emptyTitle = normalizedSearchQuery ? "没有匹配的题目" : showWrongOnly ? "还没有错题" : "还没有已标记题目";
  const emptyDescription = normalizedSearchQuery
    ? showMarkedOnly && showWrongOnly
      ? "当前只搜索已标记错题，可以换个关键词或关闭部分筛选。"
      : showMarkedOnly
        ? "当前只搜索已标记题目，可以换个关键词或关闭“只看已标记”。"
        : showWrongOnly
          ? "当前只搜索错题，可以换个关键词或关闭“只看错题”。"
          : "换个关键词试试，支持搜索题干、题型、难度、ID 和知识单元。"
    : showMarkedOnly && showWrongOnly
      ? "暂时没有同时满足已标记和做错过的题目。"
      : showWrongOnly
        ? "批改后判定错误的题目会出现在这里。"
        : "在做题页面点“标记”后，收藏的题目会出现在这里。";

  if (!courseId) {
    return (
      <div className={EXAM_PAGE_SHELL_CLASS}>
        <div className={EXAM_ALERT_CLASS}>
          缺少课程标识，暂时无法加载题库。
        </div>
      </div>
    );
  }

  return (
    <ExamCatalogShell
      courseId={courseId}
      eyebrow="Question Bank"
      title="题库模板"
      description="这里展示当前课程已经沉淀下来的所有 QuestionTemplate。它们是可复用的题目模板，生成试卷时会复制为本次考试的题目快照。"
    >
      {templatesQuery.isLoading && (
        <div className="px-6 py-12 text-center text-sm text-slate-500 dark:text-slate-400">
          正在加载题库模板...
        </div>
      )}

      {templatesQuery.error && (
        <div className="px-2 py-4 text-sm text-red-700">
          {getApiErrorMessage(templatesQuery.error, "题库模板加载失败")}
        </div>
      )}

      {!templatesQuery.isLoading && !templatesQuery.error && templates.length === 0 && (
        <div className="px-6 py-12 text-center">
          <BookOpen className="mx-auto h-10 w-10 text-slate-300" />
          <h3 className="mt-4 text-lg font-semibold text-slate-900 dark:text-slate-100">还没有题库模板</h3>
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">创建考试后，系统生成的题目会沉淀到这里。</p>
        </div>
      )}

      {templates.length > 0 ? (
        <>
          <div className="mb-4 px-1">
            <div className="flex min-w-0 items-center gap-2">
              <label className="relative block min-w-0 flex-1 sm:max-w-[360px]">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder="搜索题干、题型、难度、ID"
                  className="h-10 w-full rounded-full border border-slate-200 bg-slate-50 py-2 pl-9 pr-10 text-sm font-medium text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-indigo-300 focus:bg-white focus:ring-4 focus:ring-indigo-100"
                />
                {searchQuery ? (
                  <button
                    type="button"
                    onClick={() => setSearchQuery("")}
                    className="absolute right-2 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-full text-slate-400 transition hover:bg-slate-200 hover:text-slate-700"
                    aria-label="清空搜索"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                ) : null}
              </label>
              <button
                type="button"
                onClick={() => setShowMarkedOnly((current) => !current)}
                className={`inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-full border px-4 text-sm font-semibold transition ${
                  showMarkedOnly
                    ? "border-slate-950 bg-slate-950 text-white shadow-sm"
                    : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50"
                }`}
                aria-pressed={showMarkedOnly}
              >
                <Bookmark className={`h-4 w-4 ${showMarkedOnly ? "fill-current" : ""}`} />
                只看已标记
              </button>
              <button
                type="button"
                onClick={() => setShowWrongOnly((current) => !current)}
                className={`inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-full border px-4 text-sm font-semibold transition ${
                  showWrongOnly
                    ? "border-slate-950 bg-slate-950 text-white shadow-sm"
                    : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50"
                }`}
                aria-pressed={showWrongOnly}
              >
                <XCircle className="h-4 w-4" />
                只看错题
              </button>
            </div>
          </div>

          <section className="space-y-2 px-1">
            <div className="text-sm text-slate-500">
              共 {templates.length} 题 · 已标记 {markedTemplates.length} 题 · 错题 {wrongTemplates.length} 题 · 当前显示 {visibleTemplates.length} 题
            </div>

            {visibleTemplates.length > 0 ? (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-5 pb-2 sm:grid-cols-[repeat(auto-fill,minmax(260px,1fr))]">
                {visibleTemplates.map((item) => (
                  <QuestionTemplateCard
                    key={item.id}
                    item={item}
                    questionTypeLabel={getQuestionTypeLabel(item.question_type)}
                    onOpen={() => setSelectedTemplate(item)}
                  />
                ))}
              </div>
            ) : (
              <div className="rounded-[26px] border border-dashed border-slate-200 bg-white px-6 py-12 text-center">
                {normalizedSearchQuery ? (
                  <Search className="mx-auto h-10 w-10 text-slate-300" />
                ) : showWrongOnly ? (
                  <XCircle className="mx-auto h-10 w-10 text-slate-300" />
                ) : (
                  <Bookmark className="mx-auto h-10 w-10 text-slate-300" />
                )}
                <h3 className="mt-4 text-lg font-semibold text-slate-900">
                  {emptyTitle}
                </h3>
                <p className="mt-2 text-sm text-slate-500">
                  {emptyDescription}
                </p>
              </div>
            )}
          </section>
        </>
      ) : null}

      <QuestionTemplateDetailCard
        item={selectedTemplate}
        courseId={courseId}
        questionTypeLabel={selectedTemplate ? getQuestionTypeLabel(selectedTemplate.question_type) : ""}
        onClose={() => setSelectedTemplate(null)}
      />
    </ExamCatalogShell>
  );
}

export function QuestionTypesPage() {
  const { courseId } = useParams();
  const [selectedType, setSelectedType] = useState<QuestionTypeRegistryItem | null>(null);

  const typesQuery = useQuery({
    queryKey: ["exam-question-types", courseId],
    enabled: Boolean(courseId),
    queryFn: async ({ signal }) => {
      const response = await getQuestionTypes(courseId ?? "", signal);
      return unwrapOrvalResponse<QuestionTypeRegistryItem[]>(response) ?? [];
    },
  });

  if (!courseId) {
    return (
      <div className={EXAM_PAGE_SHELL_CLASS}>
        <div className={EXAM_ALERT_CLASS}>
          缺少课程标识，暂时无法加载题型。
        </div>
      </div>
    );
  }

  const rows = typesQuery.data ?? [];
  const globalRows = rows.filter((item) => item.scope === "global");
  const courseRows = rows.filter((item) => item.scope !== "global");

  return (
    <ExamCatalogShell
      courseId={courseId}
      eyebrow="Question Types"
      title="题型注册表"
      description="这里展示系统基础题型和当前课程题型。后续系统从样卷中学习出的特色题型，也可以进入这张注册表。"
    >
      {typesQuery.isLoading && (
        <div className="px-6 py-12 text-center text-sm text-slate-500 dark:text-slate-400">
          正在加载题型...
        </div>
      )}

      {typesQuery.error && (
        <div className="px-2 py-4 text-sm text-red-700">
          {getApiErrorMessage(typesQuery.error, "题型加载失败")}
        </div>
      )}

      {!typesQuery.isLoading && !typesQuery.error && (
        <div className="grid gap-6">
          {[
            { title: "基础题型", rows: globalRows, icon: <Tags className="h-5 w-5" /> },
            { title: "当前课程题型", rows: courseRows, icon: <Layers3 className="h-5 w-5" /> },
          ].map((group) => (
            <section key={group.title} className="space-y-4 px-1">
              <div className="flex items-center justify-between gap-3">
                <h2 className="inline-flex items-center gap-2 text-xl font-semibold text-slate-950 dark:text-slate-100">
                  {group.icon}
                  {group.title}
                </h2>
                <span className="rounded-full bg-slate-100 px-3 py-1 text-sm font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  {group.rows.length} 类
                </span>
              </div>

              {group.rows.length === 0 ? (
                <div className="px-5 py-8 text-center text-sm text-slate-500 dark:text-slate-400">
                  暂无{group.title}
                </div>
              ) : (
                <div className="grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-5 px-1 pb-2 sm:grid-cols-[repeat(auto-fill,minmax(280px,1fr))]">
                  {group.rows.map((item) => (
                    <QuestionTypeCard key={item.id} item={item} onOpen={() => setSelectedType(item)} />
                  ))}
                </div>
              )}
            </section>
          ))}
        </div>
      )}
      <QuestionTypeDetailCard item={selectedType} onClose={() => setSelectedType(null)} />
    </ExamCatalogShell>
  );
}

export function ExamPaperPage() {
  const { courseId, examPaperId } = useParams();

  if (!courseId || !examPaperId || Number.isNaN(Number(examPaperId))) {
    return (
      <div className={EXAM_PAGE_SHELL_CLASS}>
        <div className={EXAM_ALERT_CLASS}>
          缺少记录信息，暂时无法进入作答页面。
        </div>
      </div>
    );
  }

  return (
    <ExamPaperWorkspace
      courseId={courseId}
      paperId={Number(examPaperId)}
      backHref={buildCoursePath(courseId, "exams")}
    />
  );
}
