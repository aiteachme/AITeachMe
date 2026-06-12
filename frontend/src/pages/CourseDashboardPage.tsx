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
      border: "border-slate-100 dark:border-slate-800/60 hover:border-indigo-200 dark:hover:border-indigo-800/50",
      shadow: "shadow-sm hover:shadow-[0_8px_20px_rgba(99,102,241,0.04)]",
      iconContainer: "bg-indigo-50 text-indigo-600 dark:bg-indigo-950/45 dark:text-indigo-400 ring-indigo-100/35 dark:ring-indigo-900/20",
      gradient: "from-indigo-500/[0.01] to-indigo-500/[0.03] dark:from-indigo-500/[0.002] dark:to-indigo-500/[0.01]",
      textHover: "group-hover:text-indigo-600 dark:group-hover:text-indigo-400",
      buttonBg: "bg-indigo-600 hover:bg-indigo-700 text-white dark:bg-indigo-700 dark:hover:bg-indigo-800",
    },
    violet: {
      border: "border-slate-100 dark:border-slate-800/60 hover:border-violet-200 dark:hover:border-violet-800/50",
      shadow: "shadow-sm hover:shadow-[0_8px_20px_rgba(139,92,246,0.04)]",
      iconContainer: "bg-violet-50 text-violet-650 dark:bg-violet-950/45 dark:text-violet-400 ring-violet-100/35 dark:ring-violet-900/20",
      gradient: "from-violet-500/[0.01] to-violet-500/[0.03] dark:from-violet-500/[0.002] dark:to-violet-500/[0.01]",
      textHover: "group-hover:text-violet-600 dark:group-hover:text-violet-400",
      buttonBg: "bg-violet-600 hover:bg-violet-700 text-white dark:bg-violet-700 dark:hover:bg-violet-800",
    },
    teal: {
      border: "border-slate-100 dark:border-slate-800/60 hover:border-teal-200 dark:hover:border-teal-800/50",
      shadow: "shadow-sm hover:shadow-[0_8px_20px_rgba(20,184,166,0.04)]",
      iconContainer: "bg-teal-50 text-teal-600 dark:bg-teal-950/45 dark:text-teal-400 ring-teal-100/35 dark:ring-teal-900/20",
      gradient: "from-teal-500/[0.01] to-teal-500/[0.03] dark:from-teal-500/[0.002] dark:to-teal-500/[0.01]",
      textHover: "group-hover:text-teal-600 dark:group-hover:text-teal-400",
      buttonBg: "bg-teal-600 hover:bg-teal-700 text-white dark:bg-teal-700 dark:hover:bg-teal-800",
    },
  }[theme];

  return (
    <div
      onClick={(!disabled && !isGenerating) ? onClick : undefined}
      className={cn(
        "group relative flex w-full flex-col justify-between overflow-hidden rounded-2xl bg-white dark:bg-slate-900 p-8 min-h-[160px] text-left border transition-all duration-300 ease-out",
        disabled
          ? "opacity-60 grayscale bg-slate-50/50 dark:bg-slate-900/20 border-slate-150 dark:border-slate-800/40 cursor-not-allowed"
          : isGenerating
            ? "border-indigo-400 dark:border-indigo-500 bg-indigo-50/[0.01] dark:bg-indigo-950/[0.01] shadow-[0_0_20px_rgba(99,102,241,0.04)] animate-pulse"
            : cn(themeStyles.border, themeStyles.shadow, "hover:-translate-y-0.5 dark:hover:bg-[#0f1422]/20 cursor-pointer")
      )}
    >
      {!isGenerating && !disabled && (
        <div className={cn("absolute inset-0 bg-gradient-to-br opacity-0 transition-opacity duration-300 group-hover:opacity-100 pointer-events-none", themeStyles.gradient)} />
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
              <Icon className="h-6 w-6 transition-all duration-350 ease-out group-hover:scale-105 group-hover:rotate-3" strokeWidth={1.3} />
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
                <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50/80 dark:bg-amber-950/20 px-2.5 py-0.5 text-[11px] font-semibold text-amber-700 dark:text-amber-400 ring-1 ring-amber-500/10 dark:ring-amber-500/20">
                  {disabledReason}
                </span>
              )}
            </div>
            <p className="text-[14px] leading-relaxed text-slate-500 dark:text-slate-400 font-light max-w-3xl">{description}</p>
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
              className={cn("h-9 rounded-xl px-4 text-xs font-semibold shadow-sm transition-all duration-300 flex items-center gap-1 shrink-0", themeStyles.buttonBg)}
              onClick={(e) => {
                e.stopPropagation();
                onClick();
              }}
            >
              进入
              <ArrowRight className="h-3.5 w-3.5 transition-transform duration-300 ease-out group-hover:translate-x-1" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

function AICompanionWidget({
  dueReviewCount,
  activePaperCount,
  courseId,
}: {
  dueReviewCount: number;
  activePaperCount: number;
  courseId: string;
}) {
  const navigate = useNavigate();

  const companionText = useMemo(() => {
    if (dueReviewCount > 0) {
      return `您目前有 ${dueReviewCount} 个知识点临近遗忘期。建议您今天优先进行“艾宾浩斯复习闯关”，以巩固记忆基础。`;
    }
    if (activePaperCount > 0) {
      return `您有 ${activePaperCount} 份未完成的测试。趁热打铁，抽空前往考试中心完成它们吧！`;
    }
    return "目前您的学习进度与掌握情况良好，继续保持！如果准备好了，可以前往考试中心开启一次新挑战。";
  }, [dueReviewCount, activePaperCount]);

  return (
    <div className="group relative overflow-hidden rounded-2xl border border-slate-100 bg-white dark:border-slate-800/60 dark:bg-slate-900 p-6 shadow-sm transition-all duration-300 hover:shadow-[0_8px_24px_rgba(99,102,241,0.04)]">
      <div className="absolute top-0 inset-x-0 h-[2.5px] bg-gradient-to-r from-indigo-500/80 to-violet-500/80" />
      <div className="flex gap-4">
        <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600 dark:bg-indigo-950/50 dark:text-indigo-400 ring-1 ring-indigo-100/30 dark:ring-indigo-900/20">
          <Sparkles className="h-5 w-5 animate-[pulse_2s_infinite]" />
          <span className="absolute bottom-0 right-0 h-2.5 w-2.5 rounded-full border-2 border-white bg-emerald-500 dark:border-slate-900" />
        </div>
        <div className="space-y-2 flex-1">
          <div className="flex items-center justify-between">
            <h3 className="text-[14.5px] font-semibold text-slate-800 dark:text-slate-200">AI 学习助手</h3>
            <span className="text-[11px] text-indigo-600 dark:text-indigo-400 bg-indigo-50/50 dark:bg-indigo-950/50 px-2 py-0.5 rounded-full font-medium">在线</span>
          </div>
          <p className="text-[13px] leading-relaxed text-slate-500 dark:text-slate-400 font-light pr-1">
            {companionText}
          </p>
        </div>
      </div>
      <div className="mt-4 pt-3 border-t border-slate-100 dark:border-slate-800/40 flex justify-end">
        <button
          onClick={() => navigate(buildCoursePath(courseId, "profile"))}
          className="text-[12px] font-semibold text-indigo-600 hover:text-indigo-700 dark:text-indigo-400 dark:hover:text-indigo-300 flex items-center gap-1 transition-colors"
        >
          查看分析建议
          <ArrowRight className="h-3 w-3" />
        </button>
      </div>
    </div>
  );
}

function MiniStatsWidget({
  masteredCount,
  goodCount,
  dueReviewCount,
  totalCount,
}: {
  masteredCount: number;
  goodCount: number;
  dueReviewCount: number;
  totalCount: number;
}) {
  const percentMastered = totalCount > 0 ? Math.round((masteredCount / totalCount) * 100) : 0;
  const percentGood = totalCount > 0 ? Math.round((goodCount / totalCount) * 100) : 0;
  
  return (
    <div className="rounded-2xl border border-slate-100 bg-white dark:border-slate-800/60 dark:bg-slate-900 p-6 shadow-sm transition-all duration-300 hover:shadow-[0_8px_24px_rgba(99,102,241,0.04)]">
      <h3 className="text-[14.5px] font-semibold text-slate-800 dark:text-slate-200 mb-4">掌握分布</h3>
      
      <div className="space-y-4">
        <div>
          <div className="flex items-center justify-between text-[12px] mb-1.5 font-medium text-slate-600 dark:text-slate-400">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              高熟练度 ({masteredCount} 个)
            </span>
            <span>{percentMastered}%</span>
          </div>
          <div className="h-1.5 w-full bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
            <div className="h-full bg-emerald-500 rounded-full transition-all duration-500" style={{ width: `${percentMastered}%` }} />
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between text-[12px] mb-1.5 font-medium text-slate-600 dark:text-slate-400">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-indigo-500" />
              良好掌握 ({goodCount} 个)
            </span>
            <span>{percentGood}%</span>
          </div>
          <div className="h-1.5 w-full bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
            <div className="h-full bg-indigo-500 rounded-full transition-all duration-500" style={{ width: `${percentGood}%` }} />
          </div>
        </div>

        {dueReviewCount > 0 && (
          <div className="flex items-center justify-between p-2.5 rounded-xl bg-rose-500/[0.03] border border-rose-500/10 dark:bg-rose-500/[0.01] mt-2">
            <div className="text-[12px] text-rose-605 dark:text-rose-400 font-semibold flex items-center gap-1.5">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-450 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-rose-500"></span>
              </span>
              有 {dueReviewCount} 个考点需要复习
            </div>
          </div>
        )}
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

  const masteredCount = useMemo(() => states.filter(s => (s.mastery_score ?? 0) >= 0.85).length, [states]);
  const goodCount = useMemo(() => states.filter(s => (s.mastery_score ?? 0) >= 0.6 && (s.mastery_score ?? 0) < 0.85).length, [states]);

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

        {/* Two-Column Grid Layout */}
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-12">
          {/* Left Column: Main Tiles (Col-span 8) */}
          <div className="flex flex-col gap-5 lg:col-span-8">
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
          </div>

          {/* Right Column: Interactive Widgets (Col-span 4) */}
          <div className="flex flex-col gap-6 lg:col-span-4">
            <AICompanionWidget
              dueReviewCount={dueReviewCount}
              activePaperCount={activePaperCount}
              courseId={courseId}
            />
            <MiniStatsWidget
              masteredCount={masteredCount}
              goodCount={goodCount}
              dueReviewCount={dueReviewCount}
              totalCount={states.length}
            />
          </div>
        </div>



        {(historyQuery.error || masteryQuery.error || reviewsQuery.error) ? (
          <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {getApiErrorMessage(historyQuery.error ?? masteryQuery.error ?? reviewsQuery.error, "课程导航数据加载失败")}
          </div>
        ) : null}

      </div>
    </div>
  );
}
