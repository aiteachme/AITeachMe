import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  BarChart3,
  BookOpen,
  FileText,
  Loader2,
  RefreshCw,
  Sparkles,
  Lock,
  type LucideIcon,
} from "lucide-react";
import { useNavigate, useParams, Navigate } from "react-router-dom";

import {
  useExamHistoryApiV1CoursesCourseIdExamsHistoryGet,
} from "../api/generated/exams";
import {
  useMasteryOverviewApiV1CoursesCourseIdProfileMasteryGet,
  useReviewTasksApiV1CoursesCourseIdProfileReviewsGet,
} from "../api/generated/profile";
import type {
  ExamHistoryItem,
  MasteryOverviewResponse,
  ReviewTaskResponse,
  DocGenGetResponse,
} from "../api/generated/model";
import { apiClient, getApiErrorMessage } from "../api/client";
import type { ApiResponse } from "../api/types";
import { Button } from "../components/ui/Button";
import { formatPercent, isReviewDueSoon } from "../components/profile";
import { buildCoursePath, buildCourseSubPath } from "../lib/courseNavigation";
import { cn } from "../lib/utils";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { useCourseDisplayName } from "../hooks/useCourseDisplayName";

const pageShellClass = "mx-auto min-h-full w-full max-w-[1400px] px-6 pb-24 sm:px-8 lg:px-12 pt-8";
const alertClass = "rounded-xl border border-amber-200 bg-amber-50 px-6 py-5 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300";

function NavTile({
  icon: Icon,
  title,
  description,
  onClick,
  isGenerating = false,
  theme = "indigo",
  extra,
  disabled = false,
  disabledReason,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  onClick: () => void;
  isGenerating?: boolean;
  theme?: "indigo" | "violet" | "teal";
  extra?: React.ReactNode;
  disabled?: boolean;
  disabledReason?: string;
}) {
  const themeStyles = {
    indigo: {
      border: "border-slate-200/60 dark:border-slate-800/80 hover:border-indigo-400/50 dark:hover:border-indigo-500/45",
      shadow: "hover:shadow-[0_24px_50px_rgba(99,102,241,0.08)] dark:hover:shadow-[0_24px_50px_rgba(0,0,0,0.36)]",
      iconContainer: "bg-indigo-50/70 text-indigo-600 dark:bg-indigo-950/45 dark:text-indigo-400 ring-indigo-100/55 dark:ring-indigo-900/30",
      gradient: "from-indigo-500/[0.02] to-indigo-500/[0.08] dark:from-indigo-500/[0.01] dark:to-indigo-500/[0.04]",
      textHover: "group-hover:text-indigo-650 dark:group-hover:text-indigo-400",
      buttonBg: "bg-indigo-600 hover:bg-indigo-700 text-white dark:bg-indigo-650 dark:hover:bg-indigo-700",
    },
    violet: {
      border: "border-slate-200/60 dark:border-slate-800/80 hover:border-violet-400/50 dark:hover:border-violet-500/45",
      shadow: "hover:shadow-[0_24px_50px_rgba(139,92,246,0.08)] dark:hover:shadow-[0_24px_50px_rgba(0,0,0,0.36)]",
      iconContainer: "bg-violet-50/70 text-violet-600 dark:bg-violet-950/45 dark:text-violet-400 ring-violet-100/55 dark:ring-violet-900/30",
      gradient: "from-violet-500/[0.02] to-violet-500/[0.08] dark:from-violet-500/[0.01] dark:to-violet-500/[0.04]",
      textHover: "group-hover:text-violet-650 dark:group-hover:text-violet-400",
      buttonBg: "bg-violet-600 hover:bg-violet-700 text-white dark:bg-violet-650 dark:hover:bg-violet-700",
    },
    teal: {
      border: "border-slate-200/60 dark:border-slate-800/80 hover:border-teal-400/50 dark:hover:border-teal-500/45",
      shadow: "hover:shadow-[0_24px_50px_rgba(20,184,166,0.08)] dark:hover:shadow-[0_24px_50px_rgba(0,0,0,0.36)]",
      iconContainer: "bg-teal-50/70 text-teal-650 dark:bg-teal-950/45 dark:text-teal-400 ring-teal-100/55 dark:ring-teal-900/30",
      gradient: "from-teal-500/[0.02] to-teal-500/[0.08] dark:from-teal-500/[0.01] dark:to-teal-500/[0.04]",
      textHover: "group-hover:text-teal-655 dark:group-hover:text-teal-400",
      buttonBg: "bg-teal-600 hover:bg-teal-700 text-white dark:bg-teal-650 dark:hover:bg-teal-700",
    },
  }[theme];

  return (
    <div
      onClick={(!disabled && !isGenerating) ? onClick : undefined}
      className={cn(
        "group relative flex w-full flex-col justify-between overflow-hidden rounded-2xl bg-white/70 backdrop-blur-[2px] p-8 min-h-[150px] text-left border transition-all duration-550 cubic-bezier(0.16, 1, 0.3, 1)",
        disabled
          ? "opacity-60 grayscale bg-slate-50/40 dark:bg-slate-900/30 border-slate-200 dark:border-slate-800/80 cursor-not-allowed"
          : isGenerating
            ? "border-indigo-400 dark:border-indigo-500 bg-indigo-50/[0.03] dark:bg-indigo-950/[0.04] shadow-[0_0_20px_rgba(99,102,241,0.08)] animate-[pulse_3s_infinite]"
            : cn(themeStyles.border, themeStyles.shadow, "hover:-translate-y-1 hover:scale-[1.012] dark:hover:bg-[#0f1422]/60 cursor-pointer")
      )}
    >
      {!isGenerating && !disabled && (
        <div className={cn("absolute inset-0 bg-gradient-to-br opacity-0 transition-opacity duration-500 group-hover:opacity-100", themeStyles.gradient)} />
      )}
      
      <div className="relative z-10 flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between w-full">
        {/* Left Part: Icon & Details */}
        <div className="flex-1 flex gap-5 items-start">
          <span className={cn(
            "flex h-14 w-14 shrink-0 items-center justify-center rounded-xl transition-all duration-500 ring-1",
            isGenerating
              ? "bg-indigo-50 text-indigo-600 dark:bg-indigo-500/20 dark:text-indigo-300 ring-indigo-100 dark:ring-indigo-500/30"
              : disabled
                ? "bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500 ring-slate-200/50 dark:ring-slate-800/50"
                : themeStyles.iconContainer
          )}>
            {isGenerating ? (
              <Loader2 className="h-6 w-6 animate-spin" />
            ) : disabled ? (
              <Lock className="h-5 w-5" strokeWidth={1.5} />
            ) : (
              <Icon className="h-6 w-6 transition-transform duration-500 group-hover:scale-110" strokeWidth={1.25} />
            )}
          </span>
          <div className="space-y-1.5 pt-0.5">
            <div className="flex items-center flex-wrap gap-2.5">
              <h2 className="text-[17px] font-semibold tracking-tight text-slate-900 dark:text-slate-50 transition-colors duration-250">{title}</h2>
              {isGenerating && (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-indigo-50/80 px-2.5 py-0.5 text-[11px] font-medium text-indigo-600 ring-1 ring-indigo-500/10 dark:bg-indigo-500/15 dark:text-indigo-300 dark:ring-indigo-500/25 animate-pulse">
                  <span className="h-1.5 w-1.5 rounded-full bg-indigo-500" />
                  生成中
                </span>
              )}
              {disabled && disabledReason && (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50/80 dark:bg-amber-950/20 px-2.5 py-0.5 text-[11px] font-semibold text-amber-705 dark:text-amber-400 ring-1 ring-amber-500/10 dark:ring-amber-500/20">
                  {disabledReason}
                </span>
              )}
            </div>
            <p className="text-[14px] leading-relaxed text-slate-550 dark:text-slate-400 font-light max-w-3xl">{description}</p>
          </div>
        </div>

        {/* Right Part: Action Button */}
        <div className="flex items-center gap-5 shrink-0 mt-3 sm:mt-0 pl-19 sm:pl-0 self-stretch sm:self-center justify-between sm:justify-end">
          {extra && (
            <div className="text-left sm:text-right shrink-0">
              {extra}
            </div>
          )}
          {!disabled && !isGenerating && (
            <Button
              type="button"
              className={cn("h-10 rounded-xl px-5 text-xs font-semibold shadow-sm transition-all duration-300 flex items-center gap-1 shrink-0", themeStyles.buttonBg)}
              onClick={(e) => {
                e.stopPropagation();
                onClick();
              }}
            >
              进入
              <ArrowRight className="h-3.5 w-3.5 transition-transform duration-300 group-hover:translate-x-1" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

export function CourseDashboardPage() {
  const { courseId } = useParams();
  const navigate = useNavigate();
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

  const activePaperCount = useMemo(
    () => historyItems.filter((item) => item.status !== "graded").length,
    [historyItems],
  );
  const states = mastery?.knowledge_unit_states ?? [];
  
  const dueReviewCount = courseProfile?.due_review_count ?? reviewTasks.filter(isReviewDueSoon).length;

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

        {/* Main Navigation Tiles (Vertically Stacked) */}
        <section className="flex flex-col gap-5">
          <NavTile
            icon={BookOpen}
            title="知识库"
            description="查阅课程文档、深度讲义以及全局知识图谱。"
            theme="indigo"
            onClick={() => navigate(buildCoursePath(courseId, "knowledge-docs"))}
            isGenerating={isDocGenerating}
            extra={
              <div className="flex items-center gap-1.5 text-[11.5px] text-slate-400 dark:text-slate-500 font-medium">
                <span className="inline-flex h-1.5 w-1.5 rounded-full bg-indigo-500" />
                <span>{states.length} 个画像知识点已生成</span>
              </div>
            }
          />
          <NavTile
            icon={FileText}
            title="考试中心"
            description="查看全部试卷，进行专项练习与题库测试。"
            theme="violet"
            disabled={isDocGenerating}
            disabledReason={isDocGenerating ? "知识库构建中，完成后解锁" : undefined}
            onClick={() => navigate(buildCoursePath(courseId, "exams"))}
            extra={
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center rounded-md bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-600 ring-1 ring-slate-500/10 dark:bg-slate-800/50 dark:text-slate-400 dark:ring-slate-700">
                  {historyItems.length} 份已练试卷
                </span>
                {activePaperCount > 0 && (
                  <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700 ring-1 ring-amber-600/15 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/20">
                    <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
                    {activePaperCount} 份正在进行中
                  </span>
                )}
              </div>
            }
          />
          <NavTile
            icon={BarChart3}
            title="学习画像"
            description="基于测验数据、复习进度与艾宾浩斯记忆模型实时生成的深度诊断报告与今日学习计划。"
            theme="teal"
            disabled={isDocGenerating}
            disabledReason={isDocGenerating ? "知识库构建中，完成后解锁" : undefined}
            onClick={() => navigate(buildCoursePath(courseId, "profile"))}
            extra={
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center rounded-md bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-600 ring-1 ring-slate-500/10 dark:bg-slate-800/50 dark:text-slate-400 dark:ring-slate-700">
                  平均掌握度 {formatPercent(courseProfile?.avg_mastery)}
                </span>
                {dueReviewCount > 0 && (
                  <span className="inline-flex items-center gap-1 rounded-md bg-rose-50 px-2 py-0.5 text-[11px] font-semibold text-rose-700 ring-1 ring-rose-600/15 dark:bg-rose-500/10 dark:text-rose-350 dark:ring-rose-500/20">
                    {dueReviewCount} 个待复习
                  </span>
                )}
              </div>
            }
          />
        </section>

        {(historyQuery.error || masteryQuery.error || reviewsQuery.error) ? (
          <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {getApiErrorMessage(historyQuery.error ?? masteryQuery.error ?? reviewsQuery.error, "课程导航数据加载失败")}
          </div>
        ) : null}

      </div>
    </div>
  );
}
