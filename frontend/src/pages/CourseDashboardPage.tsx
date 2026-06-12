import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  BarChart3,
  BookOpen,
  CheckCircle2,
  FileText,
  Loader2,
  RefreshCw,
  Sparkles,
  Target,
  type LucideIcon,
} from "lucide-react";
import { useNavigate, useParams, Navigate } from "react-router-dom";

import {
  getExamHistoryApiV1CoursesCourseIdExamsHistoryGetQueryKey,
  useExamHistoryApiV1CoursesCourseIdExamsHistoryGet,
  useGenerateExamApiV1CoursesCourseIdExamsGeneratePost,
} from "../api/generated/exams";
import {
  useMasteryOverviewApiV1CoursesCourseIdProfileMasteryGet,
  useReviewTasksApiV1CoursesCourseIdProfileReviewsGet,
} from "../api/generated/profile";
import type {
  ExamGenerateResponse,
  ExamHistoryItem,
  MasteryOverviewResponse,
  MasteryStateResponse,
  ReviewTaskResponse,
  DocGenGetResponse,
} from "../api/generated/model";
import { apiClient, getApiErrorMessage } from "../api/client";
import type { ApiResponse } from "../api/types";
import { Button } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";
import {
  buildExamTitle,
  loadCreateExamConfig,
  toExamGenerateRequest,
} from "../components/exams";
import { formatModeLabel } from "../components/exams/examDisplay";
import {
  clamp01,
  formatDateTime as formatProfileDateTime,
  formatPercent,
  formatToken,
  isReviewDueSoon,
  masteryTone,
} from "../components/profile";
import { buildCoursePath, buildCourseSubPath } from "../lib/courseNavigation";
import { cn } from "../lib/utils";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { useCourseDisplayName } from "../hooks/useCourseDisplayName";

const pageShellClass = "mx-auto min-h-full w-full max-w-[1400px] px-6 pb-24 sm:px-8 lg:px-12 pt-8";
const alertClass = "rounded-xl border border-amber-200 bg-amber-50 px-6 py-5 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300";

const EXAM_STATUS_LABELS: Record<string, { label: string; className: string }> = {
  generating: {
    label: "生成中",
    className: "bg-indigo-50/80 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300",
  },
  graded: {
    label: "已批改",
    className: "bg-emerald-50/80 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
  },
  failed: {
    label: "生成失败",
    className: "bg-rose-50/80 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300",
  },
  submitted: {
    label: "已提交",
    className: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200",
  },
};

function formatExamStatus(status: string) {
  return EXAM_STATUS_LABELS[status] ?? {
    label: "待作答",
    className: "bg-amber-50/80 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
  };
}

function sortByNewestTimestamp<T>(items: T[], getTimestamp: (item: T) => string | null | undefined) {
  return [...items].sort((left, right) =>
    new Date(getTimestamp(right) ?? 0).getTime() - new Date(getTimestamp(left) ?? 0).getTime(),
  );
}

function getKnowledgeUnitName(state: Pick<MasteryStateResponse, "knowledge_unit_id" | "knowledge_unit_name">) {
  return state.knowledge_unit_name?.trim() || `知识点 #${state.knowledge_unit_id}`;
}

function NavTile({
  icon: Icon,
  title,
  description,
  meta,
  onClick,
  isGenerating = false,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  meta: string;
  onClick: () => void;
  isGenerating?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group relative flex flex-col justify-between overflow-hidden rounded-2xl bg-white p-6 text-left transition-all duration-300 border",
        isGenerating
          ? "border-indigo-400 dark:border-indigo-500 bg-indigo-50/[0.03] dark:bg-indigo-950/[0.04] shadow-[0_0_15px_rgba(99,102,241,0.06)] animate-[pulse_3s_infinite]"
          : "border-slate-200 dark:border-slate-800 hover:border-indigo-300/80 dark:hover:border-indigo-500/30 hover:-translate-y-0.5 hover:shadow-[0_12px_40px_rgba(79,70,229,0.04)] dark:hover:bg-slate-900/60"
      )}
    >
      <div className="absolute inset-0 bg-gradient-to-br from-transparent to-indigo-50/20 opacity-0 transition-opacity duration-300 group-hover:opacity-100 dark:to-indigo-500/5" />
      
      <div className="relative z-10 flex w-full flex-col gap-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className={cn(
              "flex h-10 w-10 items-center justify-center rounded-xl transition-colors duration-300 ring-1",
              isGenerating
                ? "bg-indigo-50 text-indigo-600 dark:bg-indigo-500/20 dark:text-indigo-300 ring-indigo-100 dark:ring-indigo-500/30"
                : "bg-slate-50 text-slate-600 group-hover:bg-indigo-50/80 group-hover:text-indigo-600 dark:bg-slate-800 dark:text-slate-400 dark:group-hover:bg-indigo-500/20 dark:group-hover:text-indigo-300 ring-slate-100 dark:ring-slate-800/50"
            )}>
              {isGenerating ? (
                <Loader2 className="h-5 w-5 animate-spin text-indigo-600 dark:text-indigo-400" />
              ) : (
                <Icon className="h-5 w-5" strokeWidth={1.5} />
              )}
            </span>
            <div className="flex items-center gap-2">
              <h2 className="text-[16px] font-semibold tracking-tight text-slate-900 dark:text-slate-100">{title}</h2>
              {isGenerating && (
                <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-medium text-indigo-600 ring-1 ring-indigo-500/10 dark:bg-indigo-500/10 dark:text-indigo-300 dark:ring-indigo-500/20">
                  <span className="h-1 w-1 rounded-full bg-indigo-500 animate-pulse"></span>
                  生成中
                </span>
              )}
            </div>
          </div>
          <ArrowRight className="h-4 w-4 text-slate-400 transition-all duration-300 group-hover:translate-x-1 group-hover:text-indigo-600 dark:text-slate-500 dark:group-hover:text-indigo-400" />
        </div>
        <p className="text-[13.5px] leading-relaxed text-slate-500 dark:text-slate-400 font-light line-clamp-2">{description}</p>
      </div>

      <div className="relative z-10 mt-5 w-full border-t border-slate-100/60 pt-3.5 dark:border-slate-800/40">
        <span className="text-[11px] font-medium tracking-wider text-slate-400 dark:text-slate-500 uppercase">{meta}</span>
      </div>
    </button>
  );
}

function RecentPaperRow({
  item,
  onOpen,
}: {
  item: ExamHistoryItem;
  onOpen: () => void;
}) {
  const status = formatExamStatus(item.status);
  const scoreText =
    item.status === "graded" && item.score_obtained != null && item.total_score != null
      ? `${item.score_obtained}/${item.total_score}`
      : `${item.total_items} 题`;
  const actionLabel =
    item.status === "graded"
      ? "查看"
      : item.status === "generating"
        ? "看进度"
        : item.status === "failed"
          ? "排查"
          : "直接考试";

  return (
    <div className="group flex flex-col gap-3 py-4 first:pt-2 last:pb-2 sm:flex-row sm:items-center sm:justify-between border-b border-slate-100/60 dark:border-slate-800/50 last:border-0 transition-colors hover:bg-slate-50/50 dark:hover:bg-slate-800/20 -mx-4 px-4 rounded-xl">
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 flex-wrap items-center gap-2.5">
          <p className="truncate text-[15px] font-medium text-slate-900 dark:text-slate-100">{buildExamTitle(item)}</p>
          <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", status.className)}>
            {status.label}
          </span>
        </div>
        <p className="mt-1.5 text-[13px] text-slate-500 dark:text-slate-400 font-light">
          {formatModeLabel(item.exam_mode)} · {scoreText}
        </p>
      </div>
      <Button type="button" size="sm" variant="ghost" onClick={onOpen} className="h-8 shrink-0 px-3 text-[13px] font-medium text-slate-600 group-hover:text-indigo-600 dark:text-slate-300 dark:group-hover:text-indigo-400 hover:bg-transparent">
        {actionLabel}
        <ArrowRight className="h-3.5 w-3.5 ml-1 transition-transform group-hover:translate-x-0.5" />
      </Button>
    </div>
  );
}

function FocusStateRow({ state }: { state: MasteryStateResponse }) {
  const score = clamp01(state.mastery_score);
  const tone = masteryTone(score);

  return (
    <div className="py-4 first:pt-2 last:pb-2 border-b border-slate-100/60 dark:border-slate-800/50 last:border-0">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="truncate text-[15px] font-medium text-slate-900 dark:text-slate-100">
            {getKnowledgeUnitName(state)}
          </p>
          <p className="mt-1.5 text-[13px] text-slate-500 dark:text-slate-400 font-light">
            {formatToken(state.knowledge_unit_type, "知识点")} · 尝试 {state.total_attempts} 次
          </p>
        </div>
        <span className={cn("shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold", tone.bg, tone.text)}>
          {formatPercent(score)}
        </span>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800/60">
        <div className={cn("h-full rounded-full transition-all duration-700 ease-out", tone.bar)} style={{ width: `${Math.max(5, score * 100)}%` }} />
      </div>
    </div>
  );
}

function ReviewTaskRow({
  task,
  onOpenSourceExam,
}: {
  task: ReviewTaskResponse;
  onOpenSourceExam: (paperId: number) => void;
}) {
  const dueSoon = isReviewDueSoon(task);

  return (
    <div className="group flex flex-col gap-3 py-4 first:pt-2 last:pb-2 sm:flex-row sm:items-center sm:justify-between border-b border-slate-100/60 dark:border-slate-800/50 last:border-0 -mx-4 px-4 rounded-xl transition-colors hover:bg-slate-50/50 dark:hover:bg-slate-800/20">
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 flex-wrap items-center gap-2.5">
          <p className="truncate text-[15px] font-medium text-slate-900 dark:text-slate-100">
            {task.knowledge_unit_name?.trim() || `知识点 #${task.knowledge_unit_id}`}
          </p>
          {dueSoon ? (
            <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
              优先
            </span>
          ) : null}
        </div>
        <p className="mt-1.5 text-[13px] text-slate-500 dark:text-slate-400 font-light">
          {formatToken(task.knowledge_unit_type, "知识点")} · {task.reason || "复习巩固"} · {formatProfileDateTime(task.scheduled_at)}
        </p>
      </div>
      {task.source_exam_paper_id ? (
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => onOpenSourceExam(task.source_exam_paper_id as number)}
          className="h-8 shrink-0 px-3 text-[13px] font-medium text-slate-600 group-hover:text-indigo-600 dark:text-slate-300 dark:group-hover:text-indigo-400 hover:bg-transparent"
        >
          来源试卷
          <ArrowRight className="h-3.5 w-3.5 ml-1 transition-transform group-hover:translate-x-0.5" />
        </Button>
      ) : null}
    </div>
  );
}

export function CourseDashboardPage() {
  const { courseId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { courseName } = useCourseDisplayName(courseId);

  const docMarkdownQuery = useQuery({
    queryKey: ["docgen-status", courseId],
    queryFn: async (): Promise<DocGenGetResponse> => {
      if (!courseId) {
        throw new Error("缺少课程 ID");
      }
      const response = await apiClient<ApiResponse<DocGenGetResponse>>({
        method: "POST",
        url: `/api/v1/courses/${courseId}/knowledge/docs`,
      });
      if (!response.data) {
        throw new Error("加载知识文档状态失败");
      }
      return response.data;
    },
    enabled: Boolean(courseId),
    staleTime: 15000,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      const status = (data.build?.status ?? "").trim();
      if (status === "accepted" || status === "running" || status === "publishing") {
        return 3000;
      }
      return false;
    },
  });

  const isDocGenerating = useMemo(() => {
    const status = (docMarkdownQuery.data?.build?.status ?? "").trim();
    return status === "accepted" || status === "running" || status === "publishing";
  }, [docMarkdownQuery.data]);

  const historyQuery = useExamHistoryApiV1CoursesCourseIdExamsHistoryGet(
    courseId ?? "",
    { page: 1, size: 8 },
    { query: { enabled: Boolean(courseId) } },
  );
  const masteryQuery = useMasteryOverviewApiV1CoursesCourseIdProfileMasteryGet(
    courseId ?? "",
    { query: { enabled: Boolean(courseId) } },
  );
  const reviewsQuery = useReviewTasksApiV1CoursesCourseIdProfileReviewsGet(
    courseId ?? "",
    { query: { enabled: Boolean(courseId) } },
  );

  const historyItems = useMemo(
    () => unwrapOrvalResponse<{ items?: ExamHistoryItem[] }>(historyQuery.data)?.items ?? [],
    [historyQuery.data],
  );
  const mastery = useMemo<MasteryOverviewResponse | null>(
    () => unwrapOrvalResponse<MasteryOverviewResponse>(masteryQuery.data),
    [masteryQuery.data],
  );
  const reviewTasks = useMemo<ReviewTaskResponse[]>(
    () => unwrapOrvalResponse<ReviewTaskResponse[]>(reviewsQuery.data) ?? [],
    [reviewsQuery.data],
  );

  const courseProfile = mastery?.course_profile;

  // 如果请求已经成功，但并没有 courseProfile (即还没构建过资料)，则直接跳到构建页。
  if (masteryQuery.isSuccess && !masteryQuery.isLoading && !courseProfile?.generated_at && !masteryQuery.isError) {
    return <Navigate to={buildCoursePath(courseId!, "build")} replace />;
  }

  const latestPapers = useMemo(
    () => sortByNewestTimestamp(historyItems, (item) => item.created_at).slice(0, 5),
    [historyItems],
  );
  const activePaperCount = useMemo(
    () => historyItems.filter((item) => item.status !== "graded").length,
    [historyItems],
  );
  const states = mastery?.knowledge_unit_states ?? [];
  
  const dueReviewCount = courseProfile?.due_review_count ?? reviewTasks.filter(isReviewDueSoon).length;
  const weakCount = courseProfile?.weak_knowledge_unit_count ?? mastery?.weak_knowledge_unit_count ?? 0;
  const focusUnitIds = new Set(courseProfile?.focus_knowledge_unit_ids ?? []);
  const focusStates = useMemo(
    () =>
      [...states]
        .sort((left, right) =>
          Number(focusUnitIds.has(right.knowledge_unit_id)) - Number(focusUnitIds.has(left.knowledge_unit_id)) ||
          left.mastery_score - right.mastery_score ||
          right.review_priority - left.review_priority,
        )
        .slice(0, 5),
    [focusUnitIds, states],
  );
  const topReviewTasks = useMemo(
    () => [...reviewTasks].sort((left, right) => right.priority - left.priority).slice(0, 4),
    [reviewTasks],
  );
  const focusNames = focusStates.map(getKnowledgeUnitName).slice(0, 3).join("、");

  const generateExam = useGenerateExamApiV1CoursesCourseIdExamsGeneratePost({
    mutation: {
      onSuccess: async (response) => {
        const created = unwrapOrvalResponse<ExamGenerateResponse>(response);
        if (!courseId || !created?.exam_paper_id) return;
        await queryClient.invalidateQueries({
          queryKey: getExamHistoryApiV1CoursesCourseIdExamsHistoryGetQueryKey(courseId, { page: 1, size: 8 }),
        });
        navigate(buildCourseSubPath(courseId, "exams", created.exam_paper_id));
        toast({
          title: "考试已创建",
          description: `已准备 ${created.num_questions} 题，正在进入作答页。`,
          variant: "success",
        });
      },
      onError: (error) => {
        toast({
          title: "创建考试失败",
          description: getApiErrorMessage(error, "请稍后重试"),
          variant: "error",
        });
      },
    },
  });

  const startConfiguredExam = () => {
    if (!courseId || generateExam.isPending) return;
    generateExam.mutate({
      courseId,
      data: toExamGenerateRequest(loadCreateExamConfig(courseId)),
    });
  };

  const startProfileExam = () => {
    if (!courseId || generateExam.isPending) return;
    const profileMode = courseProfile?.recommended_exam_mode === "paper_exam" ? "paper_exam" : "web_practice";
    generateExam.mutate({
      courseId,
      data: {
        exam_mode: profileMode,
        num_questions: Math.min(80, Math.max(1, courseProfile?.recommended_question_count ?? 8)),
        user_prompt: focusNames ? `重点覆盖：${focusNames}` : undefined,
      },
    });
  };

  const startMasteryDrill = () => {
    if (!courseId) return;
    navigate(buildCourseSubPath(courseId, "exams", "mastery-drill"));
  };

  if (!courseId) {
    return (
      <div className={pageShellClass}>
        <div className={alertClass}>缺少课程标识，暂时无法加载课程导航。</div>
      </div>
    );
  }

  const isLoading = historyQuery.isLoading || masteryQuery.isLoading || reviewsQuery.isLoading;

  return (
    <div className={pageShellClass}>
      <div className="flex w-full flex-col gap-8">
        
        {/* Top Header & Version Switcher */}
        <section className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between pt-4">
          <div className="max-w-4xl">
            <h1 className="break-words text-[36px] font-semibold tracking-tight text-slate-900 dark:text-slate-50 leading-tight flex flex-wrap items-center gap-3">
              <span>{courseName ?? "当前课程"}</span>
              <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200/60 dark:border-slate-800/80 bg-white dark:bg-[#0b0f19] px-2.5 py-1 text-[13px] font-medium text-slate-600 dark:text-slate-400 select-none">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.5)] animate-pulse"></span>
                v1.0 (当前版本)
              </span>
            </h1>
            <p className="mt-3 max-w-2xl text-[14.5px] font-light leading-relaxed text-slate-500 dark:text-slate-400">
              欢迎回到课程空间。您的专属学习大盘已准备就绪，在这里您可以纵览全局知识脉络，追踪学习动态。
            </p>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center xl:justify-end">
            <Button
              type="button"
              variant="outline"
              size="lg"
              onClick={() => navigate(buildCoursePath(courseId, "build"))}
              className="h-10 rounded-xl px-4 text-sm font-medium w-full sm:w-auto text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-slate-100 bg-white hover:bg-slate-50 dark:bg-slate-900/40 border border-slate-200 dark:border-slate-800"
            >
              <RefreshCw className="h-4 w-4 mr-1.5" />
              重新构建
            </Button>

            <Button
              type="button"
              size="lg"
              onClick={startMasteryDrill}
              className="h-10 rounded-xl px-6 text-sm font-semibold shadow-sm w-full sm:w-auto"
            >
              <Sparkles className="h-4 w-4 mr-1.5" />
              直接闯关
            </Button>
          </div>
        </section>

        {/* Main Navigation Tiles */}
        <section className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          <NavTile
            icon={BookOpen}
            title="知识库"
            description="查阅课程文档、深度讲义以及全局知识图谱。"
            meta={`${states.length} 个画像知识点`}
            onClick={() => navigate(buildCoursePath(courseId, "knowledge-docs"))}
            isGenerating={isDocGenerating}
          />
          <NavTile
            icon={FileText}
            title="考试中心"
            description="查看全部试卷，进行专项练习与题库测试。"
            meta={`${historyItems.length} 份记录，${activePaperCount} 份进行中`}
            onClick={() => navigate(buildCoursePath(courseId, "exams"))}
          />
          <NavTile
            icon={BarChart3}
            title="学习画像"
            description="追踪学习掌握度，接收智能复习计划。"
            meta={`平均掌握 ${formatPercent(courseProfile?.avg_mastery)}，待复习 ${courseProfile?.pending_review_count ?? reviewTasks.length}`}
            onClick={() => navigate(buildCoursePath(courseId, "profile"))}
          />
        </section>

        {(historyQuery.error || masteryQuery.error || reviewsQuery.error) ? (
          <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {getApiErrorMessage(historyQuery.error ?? masteryQuery.error ?? reviewsQuery.error, "课程导航数据加载失败")}
          </div>
        ) : null}

        {/* Dynamic Activity Area */}
        <div className="grid gap-6 xl:grid-cols-12 items-stretch">
          
          {/* Row 1 Left: 近期测验 */}
          <div className="xl:col-span-7 flex flex-col">
            <section className="flex flex-col h-full">
              <div className="flex flex-col justify-end mb-3 min-h-[48px] pb-1">
                <h2 className="text-[16px] font-semibold text-slate-900 dark:text-slate-100">近期测验</h2>
                <p className="mt-0.5 text-xs text-slate-500 font-light">查看近期完成的试卷，继续未完成的测验或阅读批改解析。</p>
              </div>
              <div className="flex-1 rounded-2xl bg-white border border-slate-100/70 p-6 shadow-[0_4px_20px_rgba(0,0,0,0.015)] dark:bg-[#0b0f19] dark:border-slate-800/80 flex flex-col justify-center min-h-[300px]">
                {isLoading ? (
                  <div className="py-8 flex justify-center"><Loader2 className="h-6 w-6 animate-spin text-slate-300" /></div>
                ) : latestPapers.length ? (
                  <div className="flex flex-col justify-between h-full flex-1">
                    {latestPapers.map((item) => (
                      <RecentPaperRow
                        key={item.id}
                        item={item}
                        onOpen={() => navigate(buildCourseSubPath(courseId, "exams", item.id))}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center py-6 text-center h-full flex-1">
                    <div className="relative mb-4">
                      <div className="absolute inset-0 rounded-full bg-indigo-500/10 blur-xl"></div>
                      <div className="relative flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-50 text-indigo-500 ring-1 ring-indigo-100 dark:bg-indigo-500/10 dark:text-indigo-400 dark:ring-indigo-500/20">
                        <FileText className="h-5 w-5" strokeWidth={1.5} />
                      </div>
                    </div>
                    <p className="text-[14px] font-medium text-slate-900 dark:text-slate-200">暂无测验记录</p>
                    <p className="mt-1.5 text-xs text-slate-500 max-w-sm font-light leading-relaxed">通过闯关或专项练习来生成你的第一份测验。</p>
                    <Button type="button" size="sm" onClick={startConfiguredExam} disabled={generateExam.isPending} className="mt-5 rounded-lg h-9 px-4 bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm">
                      开始练习
                    </Button>
                  </div>
                )}
              </div>
            </section>
          </div>

          {/* Row 1 Right: AI 学习洞察 */}
          <div className="xl:col-span-5 flex flex-col">
            <section className="flex flex-col h-full">
              <div className="flex flex-col justify-end mb-3 min-h-[48px] pb-1">
                <h2 className="text-[16px] font-semibold text-slate-900 dark:text-slate-100">AI 学习洞察</h2>
                <p className="mt-0.5 text-xs text-slate-500 font-light">基于当前学习画像，由 AI 智能定制的突击训练与画像快照。</p>
              </div>
              <div className="flex-1 rounded-2xl bg-white border border-slate-100/70 p-6 shadow-[0_4px_20px_rgba(0,0,0,0.015)] dark:bg-[#0b0f19] dark:border-slate-800/80 flex flex-col justify-between min-h-[300px] h-full">
                
                <div className="flex items-center justify-between gap-3 mb-5">
                  <div className="flex items-center gap-2">
                    <Sparkles className="h-5 w-5 text-indigo-600 dark:text-indigo-400" strokeWidth={2} />
                    <p className="text-[14px] font-semibold tracking-wide text-slate-900 dark:text-slate-100">画像快照</p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    onClick={startProfileExam}
                    disabled={generateExam.isPending}
                    className="h-8 rounded-lg px-3 text-xs font-semibold bg-indigo-50 hover:bg-indigo-100 text-indigo-600 dark:bg-indigo-950/40 dark:hover:bg-indigo-950/60 dark:text-indigo-400 border border-indigo-100/60 dark:border-indigo-900/30 transition-all"
                  >
                    {generateExam.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Target className="h-3.5 w-3.5 mr-1" />}
                    按画像开练
                  </Button>
                </div>

                <div className="grid grid-cols-3 gap-3 mb-5">
                  <div className="flex flex-col">
                    <span className="text-[10px] font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-0.5">掌握度</span>
                    <span className="text-xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
                      {courseProfile?.avg_mastery != null ? (
                        <span className="text-indigo-600 dark:text-indigo-400">
                          {formatPercent(courseProfile.avg_mastery)}
                        </span>
                      ) : (
                        <span className="text-slate-400 dark:text-slate-500 text-base font-normal">暂无</span>
                      )}
                    </span>
                  </div>
                  <div className="flex flex-col border-l border-slate-100 dark:border-slate-800/80 pl-3">
                    <span className="text-[10px] font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-0.5">薄弱点</span>
                    <span className={cn(
                      "text-xl font-bold tracking-tight transition-colors duration-300",
                      weakCount > 0 ? "text-rose-600 dark:text-rose-400" : "text-slate-900 dark:text-slate-100"
                    )}>
                      {weakCount}
                    </span>
                  </div>
                  <div className="flex flex-col border-l border-slate-100 dark:border-slate-800/80 pl-3">
                    <span className="text-[10px] font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-0.5">待复习</span>
                    <span className={cn(
                      "text-xl font-bold tracking-tight transition-colors duration-300",
                      dueReviewCount > 0 ? "text-amber-600 dark:text-amber-500" : "text-slate-900 dark:text-slate-100"
                    )}>
                      {dueReviewCount}
                    </span>
                  </div>
                </div>

                <div className="rounded-xl bg-slate-50/70 border border-slate-100 dark:bg-slate-950/40 dark:border-slate-800/80 p-4 mt-auto">
                  <p className="text-[13px] leading-relaxed text-slate-600 dark:text-slate-350 font-light">
                    推荐 {formatToken(courseProfile?.recommended_exam_mode, "网页练习")}，约 {courseProfile?.recommended_question_count ?? 8} 题 ({formatToken(courseProfile?.difficulty_focus, "中等")}难度)。
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {(courseProfile?.recommended_question_types ?? []).slice(0, 3).map((type) => (
                      <span key={type} className="rounded-full bg-slate-200/50 hover:bg-slate-200/80 dark:bg-slate-800 dark:hover:bg-slate-750 transition-colors px-2.5 py-0.5 text-[11px] font-medium text-slate-600 dark:text-slate-300 border border-slate-200/30 dark:border-slate-700/50">
                        {formatToken(type)}
                      </span>
                    ))}
                    {focusNames ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50 dark:bg-indigo-950/40 hover:bg-indigo-100/50 dark:hover:bg-indigo-950/70 transition-colors px-2.5 py-0.5 text-[11px] font-medium text-indigo-600 dark:text-indigo-400 border border-indigo-100/50 dark:border-indigo-900/30">
                        <Sparkles className="h-2.5 w-2.5 text-indigo-500 dark:text-indigo-400" />
                        {focusNames}
                      </span>
                    ) : null}
                  </div>
                </div>
              </div>
            </section>
          </div>

          {/* Row 2 Left: 优先知识点 */}
          <div className="xl:col-span-7 flex flex-col">
            <section className="flex flex-col h-full">
              <div className="flex flex-col justify-end mb-3 min-h-[48px] pb-1">
                <h2 className="text-[16px] font-semibold text-slate-900 dark:text-slate-100">优先知识点</h2>
                <p className="mt-0.5 text-xs text-slate-500 font-light">系统根据当前知识掌握度，智能推荐的优先突破点。</p>
              </div>
              <div className="flex-1 rounded-2xl bg-white border border-slate-100/70 p-6 shadow-[0_4px_20px_rgba(0,0,0,0.015)] dark:bg-[#0b0f19] dark:border-slate-800/80 flex flex-col justify-center min-h-[300px]">
                {isLoading ? (
                  <div className="py-8 flex justify-center"><Loader2 className="h-6 w-6 animate-spin text-slate-300" /></div>
                ) : focusStates.length ? (
                  <div className="flex flex-col justify-between h-full flex-1">
                    {focusStates.map((state) => <FocusStateRow key={state.id} state={state} />)}
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center py-6 text-center h-full flex-1">
                    <div className="relative mb-4">
                      <div className="absolute inset-0 rounded-full bg-slate-500/5 blur-xl"></div>
                      <div className="relative flex h-12 w-12 items-center justify-center rounded-xl bg-slate-50 text-slate-400 ring-1 ring-slate-100 dark:bg-slate-800/30 dark:text-slate-500 dark:ring-slate-800/50">
                        <Target className="h-5 w-5" strokeWidth={1.5} />
                      </div>
                    </div>
                    <p className="text-[14px] font-medium text-slate-900 dark:text-slate-200">暂无画像数据</p>
                    <p className="mt-1.5 text-xs text-slate-500 max-w-sm font-light leading-relaxed">完成任何一次测验后，系统将智能推荐出需要优先突破的薄弱知识点。</p>
                  </div>
                )}
              </div>
            </section>
          </div>

          {/* Row 2 Right: 复习任务 */}
          <div className="xl:col-span-5 flex flex-col">
            <section className="flex flex-col h-full">
              <div className="flex flex-col justify-end mb-3 min-h-[48px] pb-1">
                <h2 className="text-[16px] font-semibold text-slate-900 dark:text-slate-100">复习任务</h2>
                <p className="mt-0.5 text-xs text-slate-500 font-light">根据遗忘曲线自动规划的待复习内容，巩固薄弱环节。</p>
              </div>
              <div className="flex-1 rounded-2xl bg-white border border-slate-100/70 p-6 shadow-[0_4px_20px_rgba(0,0,0,0.015)] dark:bg-[#0b0f19] dark:border-slate-800/80 flex flex-col justify-center min-h-[300px]">
                {isLoading ? (
                  <div className="py-8 flex justify-center"><Loader2 className="h-6 w-6 animate-spin text-slate-300" /></div>
                ) : topReviewTasks.length ? (
                  <div className="flex flex-col justify-between h-full flex-1">
                    {topReviewTasks.map((task) => (
                      <ReviewTaskRow
                        key={task.id}
                        task={task}
                        onOpenSourceExam={(paperId) => navigate(buildCourseSubPath(courseId, "exams", paperId))}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center py-6 text-center h-full flex-1">
                    <div className="relative mb-4">
                      <div className="absolute inset-0 rounded-full bg-emerald-500/10 blur-xl"></div>
                      <div className="relative flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-50 text-emerald-500 ring-1 ring-emerald-100 dark:bg-emerald-500/10 dark:text-emerald-400 dark:ring-emerald-500/20">
                        <CheckCircle2 className="h-5 w-5" strokeWidth={1.5} />
                      </div>
                    </div>
                    <p className="text-[14px] font-medium text-slate-900 dark:text-slate-200">太棒了，暂无待办</p>
                    <p className="mt-1.5 text-xs text-slate-500 max-w-sm font-light leading-relaxed">当前没有高优先级复习任务，继续保持。</p>
                  </div>
                )}
              </div>
            </section>
          </div>
        </div>

      </div>
    </div>
  );
}
