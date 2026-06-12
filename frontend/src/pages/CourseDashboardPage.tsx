import { useMemo, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpen,
  FileText,
  Loader2,
  RefreshCw,
  ChevronRight,
  BarChart3,
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
import { isReviewDueSoon } from "../components/profile";
import { buildCoursePath, buildCourseSubPath } from "../lib/courseNavigation";
import { cn } from "../lib/utils";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { useCourseDisplayName } from "../hooks/useCourseDisplayName";
import { buildExamTitle, formatModeLabel } from "../components/exams/examDisplay";
import { fetchKnowledgeBuildRuntime } from "../lib/knowledgeBuildRuntime";
import { fetchKnowledgeOverview, OVERVIEW_INCLUDE_PRESETS, buildKnowledgeOverviewQueryKey } from "../lib/knowledgeOverview";
import { graphFullApiV1CoursesCourseIdKnowledgeGraphFullPost } from "../api/generated/knowledge";

const pageShellClass = "mx-auto min-h-full w-full max-w-[1400px] px-6 pb-24 sm:px-8 lg:px-12 pt-8 relative";
const alertClass = "rounded-2xl border border-amber-250 bg-amber-500/5 px-6 py-5 text-sm text-amber-900 dark:border-amber-500/20 dark:text-amber-300 backdrop-blur-sm";

interface ChapterHeading {
  id: string;
  title: string;
  level: number;
  anchorId: string;
}

// Parses raw Markdown to extract Chapters (H1) and Sections (H2/H3) for direct rendering on the Dashboard
function extractChaptersFromMarkdown(markdown: string | undefined): ChapterHeading[] {
  if (!markdown) return [];
  const lines = markdown.split("\n");
  const result: ChapterHeading[] = [];
  const counts = new Map<string, number>();

  for (const line of lines) {
    const match = line.match(/^(#{1,3})\s+(.+)$/);
    if (match) {
      const level = match[1].length;
      let title = match[2].trim();
      title = title.replace(/\{#.+\}/g, "").replace(/\[(.+?)\]\(.+?\)/g, "$1").trim();
      
      const base = title.toLowerCase().replace(/[^\w\u4e00-\u9fff]+/g, "-").replace(/^-|-$/g, "") || "section";
      const next = (counts.get(base) ?? 0) + 1;
      counts.set(base, next);
      const anchorId = next === 1 ? base : `${base}-${next}`;

      result.push({
        id: `${anchorId}-${level}`,
        title,
        level,
        anchorId,
      });
    }
  }
  return result;
}

function NavTile({
  icon: Icon,
  title,
  description,
  onClick,
  isGenerating = false,
  theme = "indigo",
  extra,
  previewContent,
  disabled = false,
  disabledReason,
  badge,
  connector,
  zIndexClass = "z-10",
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  onClick: () => void;
  isGenerating?: boolean;
  theme?: "indigo" | "violet" | "teal";
  extra?: React.ReactNode;
  previewContent?: React.ReactNode;
  disabled?: boolean;
  disabledReason?: string;
  badge?: React.ReactNode;
  connector?: React.ReactNode;
  zIndexClass?: string;
}) {
  const themeStyles = {
    indigo: {
      border: "border-slate-150/60 dark:border-slate-800 hover:border-indigo-305 dark:hover:border-indigo-900",
      shadow: "shadow-[0_2px_8px_rgba(0,0,0,0.01)] hover:shadow-[0_12px_24px_rgba(99,102,241,0.04)]",
      iconContainer: "bg-indigo-500/10 text-indigo-655 dark:bg-indigo-950/50 dark:text-indigo-400 border border-indigo-500/10 dark:border-indigo-500/20 shadow-sm shadow-indigo-500/5",
      gradient: "from-indigo-500/[0.005] via-transparent to-indigo-500/[0.02] dark:from-indigo-500/[0.002] dark:to-indigo-500/[0.006]",
      buttonClass: "bg-indigo-600 hover:bg-indigo-700 text-white dark:bg-indigo-700 dark:hover:bg-indigo-800",
    },
    violet: {
      border: "border-slate-150/60 dark:border-slate-800 hover:border-violet-305 dark:hover:border-violet-900",
      shadow: "shadow-[0_2px_8px_rgba(0,0,0,0.01)] hover:shadow-[0_12px_24px_rgba(139,92,246,0.04)]",
      iconContainer: "bg-violet-500/10 text-violet-600 dark:bg-violet-950/50 dark:text-violet-400 border border-violet-500/10 dark:border-violet-500/20 shadow-sm shadow-violet-505/5",
      gradient: "from-violet-500/[0.005] via-transparent to-violet-500/[0.02] dark:from-violet-500/[0.002] dark:to-violet-500/[0.006]",
      buttonClass: "bg-violet-600 hover:bg-violet-700 text-white dark:bg-violet-700 dark:hover:bg-violet-800",
    },
    teal: {
      border: "border-slate-150/60 dark:border-slate-800 hover:border-teal-305 dark:hover:border-teal-900",
      shadow: "shadow-[0_2px_8px_rgba(0,0,0,0.01)] hover:shadow-[0_12px_24px_rgba(20,184,166,0.04)]",
      iconContainer: "bg-teal-500/10 text-teal-650 dark:bg-teal-950/50 dark:text-teal-400 border border-teal-500/10 dark:border-teal-500/20 shadow-sm shadow-teal-500/5",
      gradient: "from-teal-500/[0.005] via-transparent to-teal-500/[0.02] dark:from-teal-500/[0.002] dark:to-teal-500/[0.006]",
      buttonClass: "bg-teal-600 hover:bg-teal-700 text-white dark:bg-teal-700 dark:hover:bg-teal-800",
    },
  }[theme];

  return (
    <div
      onClick={!disabled ? onClick : undefined}
      className={cn(
        "group relative flex w-full flex-col justify-between rounded-2xl bg-white/70 dark:bg-slate-900/70 backdrop-blur-md p-6 min-h-[340px] text-left border transition-all duration-500 ease-out",
        zIndexClass,
        disabled
          ? "opacity-60 bg-slate-50/50 dark:bg-slate-900/20 border-slate-150 dark:border-slate-800/40 cursor-not-allowed"
          : isGenerating
            ? "border-indigo-305 dark:border-indigo-850 bg-indigo-50/[0.01] dark:bg-indigo-950/[0.01] shadow-[0_4px_16px_rgba(99,102,241,0.04)] hover:-translate-y-0.5 hover:shadow-[0_12px_24px_rgba(99,102,241,0.06)] cursor-pointer"
            : cn(themeStyles.border, themeStyles.shadow, "hover:-translate-y-0.5 hover:bg-white dark:hover:bg-slate-900 cursor-pointer")
      )}
    >
      {!disabled && (
        <div className={cn("absolute inset-0 rounded-2xl bg-gradient-to-br opacity-0 transition-opacity duration-555 group-hover:opacity-100 pointer-events-none", themeStyles.gradient)} />
      )}

      {/* Top Part: Icon, Title, Description and Live Preview */}
      <div className="flex flex-col gap-4 relative z-10 w-full">
        <span className={cn(
          "flex h-10 w-10 items-center justify-center rounded-xl transition-all duration-500",
          isGenerating
            ? "bg-indigo-500/10 text-indigo-655 dark:bg-indigo-500/20 dark:text-indigo-300"
            : disabled
              ? "bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500"
              : themeStyles.iconContainer
        )}>
          {isGenerating ? (
            <Loader2 className="h-5 w-5 animate-spin" />
          ) : disabled ? (
            <Lock className="h-5 w-5" strokeWidth={1.5} />
          ) : (
            <Icon className="h-5 w-5 transition-all duration-500 ease-out group-hover:scale-105 group-hover:rotate-2" strokeWidth={1.5} />
          )}
        </span>

        <div className="space-y-2 w-full">
          <div className="flex items-center flex-wrap gap-2">
            <h2 className="text-[16px] font-bold tracking-tight text-slate-850 dark:text-slate-100 transition-colors duration-300">
              {title}
            </h2>
            {badge}
            {isGenerating && (
              <span className="inline-flex items-center gap-1 rounded-full bg-indigo-500/10 px-2 py-0.5 text-[9px] font-semibold text-indigo-655 dark:bg-indigo-500/20 dark:text-indigo-300">
                正在构建
              </span>
            )}
            {disabled && disabledReason && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 dark:bg-amber-950/30 px-2 py-0.5 text-[9px] font-semibold text-amber-700 dark:text-amber-400">
                {disabledReason}
              </span>
            )}
          </div>
          <p className="text-[13px] leading-relaxed text-slate-500 dark:text-slate-450 font-light">
            {description}
          </p>

          {/* Render Live Content/Syllabus Preview directly inside the cards */}
          {!disabled && previewContent && (
            <div className="w-full">
              {previewContent}
            </div>
          )}
        </div>
      </div>

      {/* Bottom Part: Extra Info & Action Button */}
      <div className="mt-6 pt-4 border-t border-slate-100/50 dark:border-slate-800/40 flex items-center justify-between relative z-10 w-full">
        <div className="min-w-0 flex-1">
          {extra}
        </div>
        {!disabled && (
          <Button
            type="button"
            className={cn("h-7.5 rounded-lg px-3.5 text-xs font-semibold shadow-sm transition-all duration-300 flex items-center gap-1 shrink-0", themeStyles.buttonClass)}
            onClick={(e) => {
              e.stopPropagation();
              onClick();
            }}
          >
            {isGenerating ? "查看进度" : "进入"}
            <ArrowRight className="h-3.5 w-3.5 transition-transform duration-300 ease-out group-hover:translate-x-0.5" />
          </Button>
        )}
      </div>
      {connector}
    </div>
  );
}

function RecentExamsWidget({
  items,
  courseId,
}: {
  items: ExamHistoryItem[];
  courseId: string;
}) {
  const navigate = useNavigate();
  const latestPapers = useMemo(() => items.slice(0, 4), [items]);

  return (
    <div className="rounded-2xl border border-slate-100 bg-white/70 dark:border-slate-800/60 dark:bg-slate-900/70 backdrop-blur-md p-6 shadow-sm hover:shadow-md transition-all duration-300 min-h-[350px] flex flex-col">
      <div className="flex items-center justify-between mb-5 pb-3 border-b border-slate-100/50 dark:border-slate-800/40 shrink-0">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-indigo-500 shadow-[0_0_6px_rgba(99,102,241,0.5)]" />
          <h3 className="text-[15px] font-bold text-slate-800 dark:text-slate-100">最近测验记录</h3>
        </div>
        <button
          onClick={() => navigate(buildCoursePath(courseId, "exams"))}
          className="text-xs text-indigo-650 hover:text-indigo-700 dark:text-indigo-400 dark:hover:text-indigo-350 hover:underline font-semibold transition-colors"
        >
          查看全部
        </button>
      </div>

      {latestPapers.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-sm text-slate-405 dark:text-slate-500 font-light py-8 text-center">
          <div className="h-14 w-14 rounded-full bg-slate-50 dark:bg-slate-800/40 flex items-center justify-center mb-3 text-slate-300 dark:text-slate-700">
            <FileText className="h-6.5 w-6.5" strokeWidth={1.5} />
          </div>
          <p className="max-w-[280px] leading-relaxed">暂无测验记录，您可以进入“考试中心”开始您的第一次测验。</p>
        </div>
      ) : (
        <div className="flex-1 space-y-3">
          {latestPapers.map((item) => {
            const hasScore = item.status === "graded" && item.score_obtained != null && item.total_score != null;
            const scoreText = hasScore
              ? `${item.score_obtained}/${item.total_score} 分`
              : `${item.total_items} 题`;

            const statusBadge =
              item.status === "graded" ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-bold text-emerald-650 dark:bg-emerald-500/20 dark:text-emerald-350 border border-emerald-500/10 dark:border-emerald-500/20 shadow-sm">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.4)]" />
                  {scoreText}
                </span>
              ) : item.status === "generating" ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-indigo-500/10 px-2.5 py-0.5 text-[11px] font-bold text-indigo-650 dark:bg-indigo-500/20 dark:text-indigo-350 border border-indigo-500/10 dark:border-indigo-500/20 animate-pulse shadow-sm">
                  <span className="h-1.5 w-1.5 rounded-full bg-indigo-500 animate-pulse" />
                  智能生成中
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2.5 py-0.5 text-[11px] font-bold text-amber-755 dark:bg-amber-500/20 dark:text-amber-355 border border-amber-500/10 dark:border-amber-500/20 shadow-sm">
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-500 shadow-[0_0_6px_rgba(245,158,11,0.4)]" />
                  {scoreText}
                </span>
              );

            return (
              <div
                key={item.id}
                onClick={() => navigate(buildCourseSubPath(courseId, "exams", String(item.id)))}
                className="group flex items-center justify-between rounded-2xl border border-slate-100/50 dark:border-slate-800/30 bg-slate-50/20 hover:bg-white dark:bg-slate-900/20 dark:hover:bg-slate-800/40 hover:border-slate-205 dark:hover:border-slate-700/50 p-3.5 transition-all duration-300 hover:shadow-sm cursor-pointer"
              >
                <div className="min-w-0 flex-1 flex items-center gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-[14px] font-bold text-slate-700 dark:text-slate-200 group-hover:text-indigo-655 dark:group-hover:text-indigo-400 transition-colors duration-300">
                      {buildExamTitle(item)}
                    </p>
                    <p className="mt-1 text-xs text-slate-400 dark:text-slate-500 font-light">
                      {formatModeLabel(item.exam_mode)}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  {statusBadge}
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="h-8 shrink-0 px-2.5 text-xs font-semibold text-slate-400 group-hover:text-indigo-600 dark:text-slate-500 dark:group-hover:text-indigo-400 hover:bg-slate-100/50 dark:hover:bg-slate-800/50 transition-all duration-200 flex items-center gap-0.5 rounded-lg"
                  >
                    进入
                    <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function MiniStatsWidget({
  masteredCount,
  goodCount,
  dueReviewCount,
  totalCount,
  hasExams,
  isDocGenerating,
  isBuilt,
}: {
  masteredCount: number;
  goodCount: number;
  dueReviewCount: number;
  totalCount: number;
  hasExams: boolean;
  isDocGenerating: boolean;
  isBuilt: boolean;
}) {
  const percentMastered = totalCount > 0 ? Math.round((masteredCount / totalCount) * 100) : 0;
  const percentGood = totalCount > 0 ? Math.round((goodCount / totalCount) * 100) : 0;

  let emptyStateContent = null;
  if (isDocGenerating || !isBuilt) {
    emptyStateContent = (
      <div className="flex-1 flex flex-col items-center justify-center text-center p-4">
        <div className="h-14 w-14 rounded-full bg-slate-50 dark:bg-slate-800/45 flex items-center justify-center text-slate-400 dark:text-slate-550 mb-3 border border-slate-100 dark:border-slate-800">
          <BarChart3 className="h-6.5 w-6.5" strokeWidth={1.5} />
        </div>
        <p className="text-[13px] text-slate-400 dark:text-slate-550 max-w-[200px] leading-relaxed font-light">
          知识库构建完成后，将在此展示您的知识掌握度分布。
        </p>
      </div>
    );
  } else if (!hasExams) {
    emptyStateContent = (
      <div className="flex-1 flex flex-col items-center justify-center text-center p-4">
        <div className="h-14 w-14 rounded-full bg-slate-50 dark:bg-slate-800/45 flex items-center justify-center text-slate-400 dark:text-slate-555 mb-3 border border-slate-100 dark:border-slate-800">
          <Lock className="h-6.5 w-6.5" strokeWidth={1.5} />
        </div>
        <p className="text-[13px] text-slate-400 dark:text-slate-555 max-w-[200px] leading-relaxed font-light">
          需先完成测验，以生成当前学科的学习画像。
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-slate-100/80 bg-white/70 dark:border-slate-800/60 dark:bg-slate-900/70 backdrop-blur-md p-6 shadow-sm hover:shadow-md transition-all duration-300 min-h-[350px] flex flex-col">
      <div className="flex items-center gap-2 mb-5 pb-3 border-b border-slate-100/50 dark:border-slate-800/40 shrink-0">
        <span className="h-2 w-2 rounded-full bg-teal-500 shadow-[0_0_6px_rgba(20,184,166,0.5)]" />
        <h3 className="text-[15px] font-bold text-slate-800 dark:text-slate-100">掌握分布</h3>
      </div>

      {emptyStateContent ? emptyStateContent : (
        <div className="flex-1 flex flex-col justify-center space-y-6">
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs font-semibold text-slate-655 dark:text-slate-350">
              <span className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_4px_rgba(16,185,129,0.3)]" />
                高熟练度 ({masteredCount} 个)
              </span>
              <span className="font-bold text-emerald-650 dark:text-emerald-400">{percentMastered}%</span>
            </div>
            <div className="h-2.5 w-full bg-slate-100/70 dark:bg-slate-800/60 rounded-full overflow-hidden shadow-inner">
              <div className="h-full bg-gradient-to-r from-emerald-400 to-teal-500 rounded-full transition-all duration-700 ease-out" style={{ width: `${percentMastered}%` }} />
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs font-semibold text-slate-655 dark:text-slate-350">
              <span className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-indigo-500 shadow-[0_0_4px_rgba(99,102,241,0.3)]" />
                良好掌握 ({goodCount} 个)
              </span>
              <span className="font-bold text-indigo-650 dark:text-indigo-400">{percentGood}%</span>
            </div>
            <div className="h-2.5 w-full bg-slate-100/70 dark:bg-slate-800/60 rounded-full overflow-hidden shadow-inner">
              <div className="h-full bg-gradient-to-r from-indigo-400 to-violet-500 rounded-full transition-all duration-700 ease-out" style={{ width: `${percentGood}%` }} />
            </div>
          </div>

          {dueReviewCount > 0 && (
            <div className="flex items-center justify-between p-3.5 rounded-2xl bg-rose-500/[0.04] border border-rose-500/10 dark:bg-rose-500/[0.02] mt-3 shrink-0 transition-all duration-300">
              <div className="text-[12.5px] text-rose-600 dark:text-rose-400 font-bold flex items-center gap-2">
                <span className="relative flex h-2 w-2 shrink-0">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-455 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-rose-500"></span>
                </span>
                有 {dueReviewCount} 个考点需要复习
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function CourseDashboardPage() {
  const { courseId } = useParams();
  const navigate = useNavigate();
  const { courseName } = useCourseDisplayName(courseId);
  const queryClient = useQueryClient();

  // Aligned Query Cache key: ["docgen-content", courseId, null] to prefetch/preload markdown
  const docMarkdownQuery = useQuery({
    queryKey: ["docgen-content", courseId, null],
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
    staleTime: 30000,
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
  const states = mastery?.knowledge_unit_states ?? [];

  const isBuilt = useMemo(() => {
    return Boolean(courseProfile?.generated_at);
  }, [courseProfile]);

  // Extract chapters from pre-loaded markdown content for rendering the syllabus preview inside the card
  const chapters = useMemo(() => {
    return extractChaptersFromMarkdown(docMarkdownQuery.data?.markdown);
  }, [docMarkdownQuery.data?.markdown]);

  // Background Prefetching for Components and Data
  useEffect(() => {
    if (!courseId) return;

    const prefetchPages = async () => {
      try {
        await Promise.all([
          import("./KnowledgeDocsPage"),
          import("./ExamsPage"),
          import("./ProfilePage"),
          import("../components/knowledge-graph/KnowledgeGraphSidePanel"),
          import("../components/knowledge-graph/KnowledgeGraphView"),
        ]);
      } catch (e) {
        // Ignore prefetch errors
      }
    };

    const prefetchData = async () => {
      try {
        // 1. Prefetch exam history (page size 24 as used in ExamsPage)
        void queryClient.prefetchQuery({
          queryKey: [`/api/v1/courses/${courseId}/exams/history`, { page: 1, size: 24 }],
          queryFn: async () => {
            const response = await apiClient<any>({
              method: "GET",
              url: `/api/v1/courses/${courseId}/exams/history`,
              params: { page: 1, size: 24 },
            });
            return response.data;
          },
          staleTime: 30000,
        });

        // 2. Prefetch knowledge doc build runtime
        void queryClient.prefetchQuery({
          queryKey: ["knowledge-doc-build", courseId, null],
          queryFn: () => fetchKnowledgeBuildRuntime(courseId),
          staleTime: 30000,
        });

        // 3. Prefetch knowledge overview stats
        const overviewInclude = OVERVIEW_INCLUDE_PRESETS.knowledgeGraph;
        const overviewData = await queryClient.fetchQuery({
          queryKey: buildKnowledgeOverviewQueryKey(courseId, overviewInclude),
          queryFn: () => fetchKnowledgeOverview(courseId, overviewInclude),
          staleTime: 30000,
        });

        // 4. Prefetch full D3 graph data using the retrieved node/edge counts
        const nodeCount = overviewData?.stats?.node_count ?? 0;
        const edgeCount = overviewData?.stats?.edge_count ?? 0;
        void queryClient.prefetchQuery({
          queryKey: ["graph-full", courseId, nodeCount, edgeCount],
          queryFn: async () =>
            unwrapOrvalResponse(
              await graphFullApiV1CoursesCourseIdKnowledgeGraphFullPost(courseId),
            ) ?? null,
          staleTime: 30000,
        });
      } catch (e) {
        // Ignore prefetch errors
      }
    };

    const componentTimer = setTimeout(prefetchPages, 1000);
    const dataTimer = setTimeout(prefetchData, 1500);

    return () => {
      clearTimeout(componentTimer);
      clearTimeout(dataTimer);
    };
  }, [courseId, queryClient]);

  // Redirect to Build Plan if course profile is empty/unbuilt
  if (masteryQuery.isSuccess && !masteryQuery.isLoading && !courseProfile?.generated_at && !masteryQuery.isError) {
    return <Navigate to={buildCoursePath(courseId!, "build")} replace />;
  }

  const activePaperCount = useMemo(
    () => historyItems.filter((item) => item.status !== "graded").length,
    [historyItems],
  );

  const dueReviewCount = courseProfile?.due_review_count ?? reviewTasks.filter(isReviewDueSoon).length;
  const masteredCount = useMemo(() => states.filter(s => (s.mastery_score ?? 0) >= 0.85).length, [states]);
  const goodCount = useMemo(() => states.filter(s => (s.mastery_score ?? 0) >= 0.6 && (s.mastery_score ?? 0) < 0.85).length, [states]);

  const avgMasteryVal = Math.round((courseProfile?.avg_mastery ?? 0) * 100);

  const handleChapterClick = (anchorId: string) => {
    if (!courseId) return;
    // Jump straight to the heading inside KnowledgeDocsPage
    navigate(buildCoursePath(courseId, "knowledge-docs"), {
      state: {
        selectionJump: { anchorId, courseId },
        selectionJumpAt: Date.now(),
      },
    });
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
      {/* Background Ambient Glows */}
      <div className="absolute top-1/4 left-1/4 -z-10 h-96 w-96 rounded-full bg-indigo-500/[0.04] blur-[120px] dark:bg-indigo-500/[0.02] pointer-events-none" />
      <div className="absolute bottom-1/3 right-1/4 -z-10 h-96 w-96 rounded-full bg-teal-500/[0.04] blur-[120px] dark:bg-teal-500/[0.02] pointer-events-none" />

      <div className="flex w-full flex-col gap-8 relative z-10">
        
        {/* Active DocGen Progress Banner */}
        {isDocGenerating && (
          <div className="relative overflow-hidden rounded-2xl border border-indigo-100/80 bg-gradient-to-r from-indigo-50/50 via-white/80 to-indigo-50/30 p-5 shadow-[0_4px_20px_rgba(99,102,241,0.04)] backdrop-blur-sm dark:border-indigo-950/80 dark:from-indigo-950/20 dark:via-slate-900/70 dark:to-indigo-950/15 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 transition-all duration-300">
            <div className="absolute inset-0 bg-gradient-to-r from-indigo-500/[0.02] to-transparent pointer-events-none" />
            <div className="flex items-center gap-4 relative z-10">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-500/10 text-indigo-650 dark:bg-indigo-500/20 dark:text-indigo-405 border border-indigo-200/20 dark:border-indigo-800/35 shadow-inner">
                <Loader2 className="h-5 w-5 animate-spin" />
              </span>
              <div>
                <h4 className="text-[15px] font-bold text-slate-850 dark:text-slate-205">
                  知识库正在后台构建中...
                </h4>
                <p className="mt-1 text-[13px] text-slate-500 dark:text-slate-400 font-light leading-relaxed">
                  系统正在智能解析资料、整理课程考点与深度讲义。您可以随时在此查看实时进度与日志。
                </p>
              </div>
            </div>
            <Button
              type="button"
              size="sm"
              onClick={() => navigate(buildCoursePath(courseId, "knowledge-docs"))}
              className="self-start sm:self-auto shrink-0 bg-indigo-650 hover:bg-indigo-700 text-white dark:bg-indigo-700 dark:hover:bg-indigo-800 text-xs font-semibold px-4 h-9 rounded-xl shadow-md shadow-indigo-500/10 hover:shadow-indigo-500/20 flex items-center gap-1.5 transition-all duration-300 relative z-10"
            >
              查看构建进度
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        )}

        {/* Top Header & Version Switcher */}
        <section className="flex flex-col gap-6 xl:flex-row xl:items-center xl:justify-between pt-4 relative z-10">
          <div className="max-w-4xl space-y-3">
            <div className="flex flex-wrap items-center gap-3.5">
              <h1 className="break-words text-[38px] font-extrabold tracking-tight text-slate-905 dark:text-slate-55 leading-tight">
                {courseName ?? "当前课程"}
              </h1>
              <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/25 bg-emerald-500/5 px-3 py-1 text-[13px] font-semibold text-emerald-600 dark:text-emerald-400 select-none shadow-[0_2px_8px_rgba(16,185,129,0.05)]">
                <span className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)] animate-pulse"></span>
                v1.0 (当前版本)
              </span>
            </div>
            <p className="max-w-3xl text-[15px] font-light leading-relaxed text-slate-500 dark:text-slate-400">
              欢迎回到课程空间。您的专属学习大盘已准备就绪，在这里您可以纵览全局知识脉络，追踪学习动态。
            </p>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center xl:justify-end shrink-0">
            <Button
              type="button"
              variant="outline"
              size="lg"
              onClick={() => navigate(buildCoursePath(courseId, "build"))}
              className="h-10 rounded-xl px-5 text-sm font-medium w-full sm:w-auto text-slate-605 hover:text-slate-900 dark:text-slate-300 dark:hover:text-slate-100 bg-white/60 hover:bg-slate-55 dark:bg-slate-900/40 border border-slate-205 dark:border-slate-800 transition-all duration-300 hover:shadow-sm"
            >
              <RefreshCw className="h-4 w-4 mr-2 text-slate-550 dark:text-slate-400 transition-transform duration-505 hover:rotate-180" />
              构建
            </Button>

            <Button
              type="button"
              size="lg"
              onClick={() => navigate(buildCoursePath(courseId, "knowledge-docs"))}
              className="h-10 rounded-xl px-6 text-sm font-semibold text-white bg-gradient-to-r from-indigo-600 to-violet-650 hover:from-indigo-550 hover:to-violet-600 border-0 shadow-md shadow-indigo-500/15 hover:shadow-lg hover:shadow-indigo-500/25 transition-all duration-300 transform hover:-translate-y-0.5 w-full sm:w-auto flex items-center justify-center gap-1.5"
            >
              <BookOpen className="h-4 w-4 text-white/90" />
              开始学习
            </Button>
          </div>
        </section>

        {/* Three-Column Nav Tiles Layout */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 relative z-10">
          
          {/* Card 1: 知识库 */}
          <NavTile
            icon={BookOpen}
            title="知识库"
            description="查阅课程文档、深度讲义以及全局知识图谱。"
            theme="indigo"
            onClick={() => navigate(buildCoursePath(courseId, "knowledge-docs"))}
            isGenerating={isDocGenerating}
            zIndexClass="z-30"
            badge={
              states.length > 0 ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-teal-500/10 px-2 py-0.5 text-[9px] font-bold text-teal-600 dark:bg-teal-950/40 dark:text-teal-400 border border-teal-500/15 dark:border-teal-900/30 animate-pulse">
                  <RefreshCw className="h-2.5 w-2.5" />
                  画像自适应精讲
                </span>
              ) : undefined
            }
            connector={
              (!isBuilt || isDocGenerating) ? (
                <>
                  {/* Desktop Connector (Horizontal) - Disabled */}
                  <div
                    className="absolute right-[-40px] top-1/2 -translate-y-1/2 z-20 pointer-events-auto cursor-not-allowed hidden md:block"
                    title={isDocGenerating ? "知识库构建中" : "请先构建知识库"}
                  >
                    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" className="overflow-visible">
                      <path
                        d="M4 16H44"
                        stroke="#cbd5e1"
                        className="dark:stroke-slate-800/60"
                        strokeWidth="4"
                        strokeLinecap="round"
                        strokeDasharray="6 5"
                      />
                      <path
                        d="M40 10L48 16L40 22"
                        fill="#cbd5e1"
                        stroke="#cbd5e1"
                        strokeWidth="2"
                        strokeLinejoin="round"
                        className="dark:fill-slate-800/60 dark:stroke-slate-800/60"
                      />
                    </svg>
                  </div>
                  {/* Mobile Connector (Vertical) - Disabled */}
                  <div
                    className="absolute bottom-[-40px] left-1/2 -translate-x-1/2 z-20 pointer-events-auto cursor-not-allowed block md:hidden"
                    title={isDocGenerating ? "知识库构建中" : "请先构建知识库"}
                  >
                    <svg width="32" height="56" viewBox="0 0 32 56" fill="none" className="overflow-visible">
                      <path
                        d="M16 4V44"
                        stroke="#cbd5e1"
                        className="dark:stroke-slate-800/60"
                        strokeWidth="4"
                        strokeLinecap="round"
                        strokeDasharray="6 5"
                      />
                      <path
                        d="M10 40L16 48L22 40"
                        fill="#cbd5e1"
                        stroke="#cbd5e1"
                        strokeWidth="2"
                        strokeLinejoin="round"
                        className="dark:fill-slate-800/60 dark:stroke-slate-800/60"
                      />
                    </svg>
                  </div>
                </>
              ) : (
                <>
                  {/* Desktop Connector (Horizontal) */}
                  <div
                    onClick={(e) => {
                      e.stopPropagation();
                      navigate(buildCoursePath(courseId, "exams"));
                    }}
                    className="absolute right-[-40px] top-1/2 -translate-y-1/2 z-20 pointer-events-auto cursor-pointer hover:scale-110 active:scale-95 transition-all duration-200 hidden md:block group/arrow"
                    title="进入 训练中心"
                  >
                    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" className="overflow-visible">
                      {/* Glow underlayer */}
                      <path
                        d="M4 16H48"
                        stroke="url(#indigo-violet)"
                        strokeWidth="10"
                        strokeLinecap="round"
                        opacity="0.15"
                        className="blur-[2px] group-hover/arrow:opacity-30 transition-opacity"
                      />
                      {/* Main connector line */}
                      <path
                        d="M4 16H44"
                        stroke="url(#indigo-violet)"
                        strokeWidth="4"
                        strokeLinecap="round"
                      />
                      {/* Flowing particle */}
                      <circle r="4" fill="#a78bfa">
                        <animateMotion dur="1.2s" repeatCount="indefinite" path="M4 16H42" />
                      </circle>
                      {/* Large solid arrowhead */}
                      <path
                        d="M40 10L48 16L40 22"
                        fill="#8b5cf6"
                        stroke="#8b5cf6"
                        strokeWidth="2"
                        strokeLinejoin="round"
                        className="group-hover/arrow:translate-x-0.5 transition-transform duration-200"
                      />
                      <defs>
                        <linearGradient id="indigo-violet" x1="6" y1="12" x2="47" y2="12" gradientUnits="userSpaceOnUse">
                          <stop stopColor="#6366f1" />
                          <stop offset="1" stopColor="#8b5cf6" />
                        </linearGradient>
                      </defs>
                    </svg>
                  </div>
                  {/* Mobile Connector (Vertical) */}
                  <div
                    onClick={(e) => {
                      e.stopPropagation();
                      navigate(buildCoursePath(courseId, "exams"));
                    }}
                    className="absolute bottom-[-40px] left-1/2 -translate-x-1/2 z-20 pointer-events-auto cursor-pointer hover:scale-110 active:scale-95 transition-all duration-200 block md:hidden group/arrow-v"
                    title="进入 训练中心"
                  >
                    <svg width="32" height="56" viewBox="0 0 32 56" fill="none" className="overflow-visible">
                      {/* Glow underlayer */}
                      <path
                        d="M16 4V48"
                        stroke="url(#indigo-violet-v)"
                        strokeWidth="10"
                        strokeLinecap="round"
                        opacity="0.15"
                        className="blur-[2px] group-hover/arrow-v:opacity-30 transition-opacity"
                      />
                      {/* Main connector line */}
                      <path
                        d="M16 4V44"
                        stroke="url(#indigo-violet-v)"
                        strokeWidth="4"
                        strokeLinecap="round"
                      />
                      {/* Flowing particle */}
                      <circle r="4" fill="#a78bfa">
                        <animateMotion dur="1.2s" repeatCount="indefinite" path="M16 4V42" />
                      </circle>
                      {/* Large solid arrowhead */}
                      <path
                        d="M10 40L16 48L22 40"
                        fill="#8b5cf6"
                        stroke="#8b5cf6"
                        strokeWidth="2"
                        strokeLinejoin="round"
                        className="group-hover/arrow-v:translate-y-0.5 transition-transform duration-200"
                      />
                      <defs>
                        <linearGradient id="indigo-violet-v" x1="12" y1="6" x2="12" y2="47" gradientUnits="userSpaceOnUse">
                          <stop stopColor="#6366f1" />
                          <stop offset="1" stopColor="#8b5cf6" />
                        </linearGradient>
                      </defs>
                    </svg>
                  </div>
                </>
              )
            }
            extra={
              <div className="flex items-center gap-1.5 text-[11.5px] text-slate-455 dark:text-slate-500 font-medium bg-slate-50/50 dark:bg-slate-800/30 px-3 py-1 rounded-full border border-slate-100/50 dark:border-slate-800/20 w-fit shadow-[0_1px_2px_rgba(0,0,0,0.01)]">
                <span className="inline-flex h-1.5 w-1.5 rounded-full bg-indigo-500 shadow-[0_0_4px_rgba(99,102,241,0.4)]" />
                <span>{states.length} 个画像知识点已生成</span>
              </div>
            }
            previewContent={
              !isDocGenerating && chapters.length > 0 ? (
                <div className="mt-4 space-y-2 border-t border-slate-100/40 dark:border-slate-800/30 pt-3.5 w-full">
                  <p className="text-[10px] font-bold text-slate-405 dark:text-slate-500 uppercase tracking-wider">章节大纲</p>
                  <div className="space-y-1">
                    {chapters.slice(0, 3).map((chapter, idx) => (
                      <div
                        key={chapter.id}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleChapterClick(chapter.anchorId);
                        }}
                        className="flex items-center justify-between text-[12px] text-slate-605 hover:text-indigo-650 dark:text-slate-400 dark:hover:text-indigo-400 py-1.5 px-2.5 rounded-xl hover:bg-indigo-50/40 dark:hover:bg-indigo-955/15 transition-all cursor-pointer group/item border border-transparent hover:border-indigo-100/40 dark:hover:border-indigo-900/15"
                      >
                        <span className="truncate flex items-center gap-2">
                          <span className="h-5 w-5 rounded-md bg-indigo-50 dark:bg-indigo-950/30 text-[10px] font-bold text-indigo-500 flex items-center justify-center border border-indigo-100/30 dark:border-indigo-900/25 shrink-0 group-hover/item:bg-indigo-100/50 dark:group-hover/item:bg-indigo-900/45 transition-colors">
                            {idx + 1}
                          </span>
                          <span className="font-semibold truncate">{chapter.title}</span>
                        </span>
                        <ChevronRight className="h-3.5 w-3.5 text-slate-355 dark:text-slate-650 group-hover/item:translate-x-0.5 transition-transform" />
                      </div>
                    ))}
                  </div>
                </div>
              ) : undefined
            }
          />

          {/* Card 2: 考试中心 */}
          <NavTile
            icon={FileText}
            title="考试中心"
            description="查看全部试卷，进行专项练习与题库测试。"
            theme="violet"
            disabled={!isBuilt || isDocGenerating}
            disabledReason={isDocGenerating ? "知识库构建中" : !isBuilt ? "请先构建知识库" : undefined}
            onClick={() => navigate(buildCoursePath(courseId, "exams"))}
            zIndexClass="z-20"
            badge={
              states.length > 0 ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-teal-500/10 px-2 py-0.5 text-[9px] font-bold text-teal-600 dark:bg-teal-950/40 dark:text-teal-400 border border-teal-500/15 dark:border-teal-900/30 animate-pulse">
                  <RefreshCw className="h-2.5 w-2.5" />
                  画像自适应出题
                </span>
              ) : undefined
            }
            connector={
              (!isBuilt || isDocGenerating || historyItems.length === 0) ? (
                <>
                  {/* Desktop Connector (Horizontal) - Disabled */}
                  <div
                    className="absolute right-[-40px] top-1/2 -translate-y-1/2 z-20 pointer-events-auto cursor-not-allowed hidden md:block"
                    title={isDocGenerating ? "知识库构建中" : !isBuilt ? "请先构建知识库" : "需先完成测验"}
                  >
                    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" className="overflow-visible">
                      <path
                        d="M4 16H44"
                        stroke="#cbd5e1"
                        className="dark:stroke-slate-800/60"
                        strokeWidth="4"
                        strokeLinecap="round"
                        strokeDasharray="6 5"
                      />
                      <path
                        d="M38 8L50 16L38 24Z"
                        fill="#cbd5e1"
                        className="dark:fill-slate-850"
                      />
                    </svg>
                  </div>
                  {/* Mobile Connector (Vertical) - Disabled */}
                  <div
                    className="absolute bottom-[-40px] left-1/2 -translate-x-1/2 z-20 pointer-events-auto cursor-not-allowed block md:hidden"
                    title={isDocGenerating ? "知识库构建中" : !isBuilt ? "请先构建知识库" : "需先完成测验"}
                  >
                    <svg width="32" height="56" viewBox="0 0 32 56" fill="none" className="overflow-visible">
                      <path
                        d="M16 4V44"
                        stroke="#cbd5e1"
                        className="dark:stroke-slate-800/60"
                        strokeWidth="4"
                        strokeLinecap="round"
                        strokeDasharray="6 5"
                      />
                      <path
                        d="M8 38L16 50L24 38Z"
                        fill="#cbd5e1"
                        className="dark:fill-slate-850"
                      />
                    </svg>
                  </div>
                </>
              ) : (
                <>
                  {/* Desktop Connector (Horizontal) */}
                  <div
                    onClick={(e) => {
                      e.stopPropagation();
                      navigate(buildCoursePath(courseId, "profile"));
                    }}
                    className="absolute right-[-40px] top-1/2 -translate-y-1/2 z-20 pointer-events-auto cursor-pointer hover:scale-110 active:scale-95 transition-all duration-200 hidden md:block group/arrow-2"
                    title="进入 学习画像"
                  >
                    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" className="overflow-visible">
                      {/* Glow underlayer */}
                      <path
                        d="M4 16H48"
                        stroke="url(#violet-teal)"
                        strokeWidth="10"
                        strokeLinecap="round"
                        opacity="0.15"
                        className="blur-[2px] group-hover/arrow-2:opacity-30 transition-opacity"
                      />
                      {/* Main connector line */}
                      <path
                        d="M4 16H44"
                        stroke="url(#violet-teal)"
                        strokeWidth="4"
                        strokeLinecap="round"
                      />
                      {/* Flowing particle */}
                      <circle r="6" fill="#2dd4bf" opacity="0.4">
                        <animateMotion dur="1.2s" repeatCount="indefinite" path="M4 16H42" />
                      </circle>
                      <circle r="3.5" fill="#ffffff">
                        <animateMotion dur="1.2s" repeatCount="indefinite" path="M4 16H42" />
                      </circle>
                      {/* Large solid arrowhead */}
                      <path
                        d="M38 8L50 16L38 24Z"
                        fill="#14b8a6"
                        className="group-hover/arrow-2:translate-x-1 transition-transform duration-200"
                      />
                      <defs>
                        <linearGradient id="violet-teal" x1="6" y1="12" x2="47" y2="12" gradientUnits="userSpaceOnUse">
                          <stop stopColor="#8b5cf6" />
                          <stop offset="1" stopColor="#14b8a6" />
                        </linearGradient>
                      </defs>
                    </svg>
                  </div>
                  {/* Mobile Connector (Vertical) */}
                  <div
                    onClick={(e) => {
                      e.stopPropagation();
                      navigate(buildCoursePath(courseId, "profile"));
                    }}
                    className="absolute bottom-[-40px] left-1/2 -translate-x-1/2 z-20 pointer-events-auto cursor-pointer hover:scale-110 active:scale-95 transition-all duration-200 block md:hidden group/arrow-2-v"
                    title="进入 学习画像"
                  >
                    <svg width="32" height="56" viewBox="0 0 32 56" fill="none" className="overflow-visible">
                      {/* Glow underlayer */}
                      <path
                        d="M16 4V48"
                        stroke="url(#violet-teal-v)"
                        strokeWidth="10"
                        strokeLinecap="round"
                        opacity="0.15"
                        className="blur-[2px] group-hover/arrow-2-v:opacity-30 transition-opacity"
                      />
                      {/* Main connector line */}
                      <path
                        d="M16 4V44"
                        stroke="url(#violet-teal-v)"
                        strokeWidth="4"
                        strokeLinecap="round"
                      />
                      {/* Flowing particle */}
                      <circle r="6" fill="#2dd4bf" opacity="0.4">
                        <animateMotion dur="1.2s" repeatCount="indefinite" path="M16 4V42" />
                      </circle>
                      <circle r="3.5" fill="#ffffff">
                        <animateMotion dur="1.2s" repeatCount="indefinite" path="M16 4V42" />
                      </circle>
                      {/* Large solid arrowhead */}
                      <path
                        d="M8 38L16 50L24 38Z"
                        fill="#14b8a6"
                        className="group-hover/arrow-2-v:translate-y-1 transition-transform duration-200"
                      />
                      <defs>
                        <linearGradient id="violet-teal-v" x1="12" y1="6" x2="12" y2="47" gradientUnits="userSpaceOnUse">
                          <stop stopColor="#8b5cf6" />
                          <stop offset="1" stopColor="#14b8a6" />
                        </linearGradient>
                      </defs>
                    </svg>
                  </div>
                </>
              )
            }
            extra={
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center rounded-full bg-slate-50/50 px-3 py-1 text-[11px] font-semibold text-slate-605 border border-slate-100/60 dark:bg-slate-800/30 dark:text-slate-400 dark:border-slate-800/30 shadow-[0_1px_2px_rgba(0,0,0,0.01)]">
                  {historyItems.length} 份已练试卷
                </span>
                {activePaperCount > 0 && (
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50/60 px-3 py-1 text-[11px] font-bold text-amber-705 border border-amber-205/30 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-500/20 shadow-sm animate-pulse">
                    <span className="h-1.5 w-1.5 rounded-full bg-amber-505 shadow-[0_0_4px_rgba(245,158,11,0.5)]" />
                    {activePaperCount} 份进行中
                  </span>
                )}
              </div>
            }
            previewContent={
              historyItems.length > 0 ? (
                <div className="mt-4 space-y-2 border-t border-slate-100/40 dark:border-slate-800/30 pt-3.5 w-full">
                  <p className="text-[10px] font-bold text-slate-405 dark:text-slate-500 uppercase tracking-wider">最近测验</p>
                  <div className="space-y-1">
                    {historyItems.slice(0, 3).map((item) => (
                      <div
                        key={item.id}
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(buildCourseSubPath(courseId, "exams", String(item.id)));
                        }}
                        className="flex items-center justify-between text-[12px] text-slate-605 hover:text-violet-655 dark:text-slate-400 dark:hover:text-violet-400 py-1.5 px-2.5 rounded-xl hover:bg-violet-50/40 dark:hover:bg-violet-955/15 transition-all cursor-pointer group/item border border-transparent hover:border-violet-100/40 dark:hover:border-violet-900/15"
                      >
                        <span className="truncate flex items-center gap-2">
                          <span className="h-2 w-2 rounded-full bg-violet-400 dark:bg-violet-600 group-hover/item:scale-125 transition-transform shrink-0" />
                          <span className="font-semibold truncate">{buildExamTitle(item)}</span>
                        </span>
                        <span className="inline-flex items-center rounded-full bg-violet-100/35 dark:bg-violet-900/25 px-2 py-0.5 text-[9px] font-bold text-violet-600 dark:text-violet-405 border border-violet-100/50 dark:border-violet-850/30 shrink-0">
                          {item.status === "graded" && item.score_obtained != null && item.total_score != null
                            ? `${item.score_obtained}/${item.total_score}分`
                            : item.status === "generating"
                              ? "出题中"
                              : "练习中"}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : undefined
            }
          />

          {/* Card 3: 学习画像 */}
          <NavTile
            icon={BarChart3}
            title="学习画像"
            description="基于测验 data、复习进度实时生成的深度诊断报告与今日学习计划。"
            theme="teal"
            disabled={!isBuilt || isDocGenerating || historyItems.length === 0}
            disabledReason={
              isDocGenerating
                ? "知识库构建中"
                : !isBuilt
                  ? "请先构建知识库"
                  : historyItems.length === 0
                    ? "需先完成测验"
                    : undefined
            }
            onClick={() => navigate(buildCoursePath(courseId, "profile"))}
            zIndexClass="z-10"
            extra={
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center rounded-full bg-slate-50/50 px-3 py-1 text-[11px] font-semibold text-slate-600 border border-slate-100/60 dark:bg-slate-800/30 dark:text-slate-400 dark:border-slate-800/30 shadow-[0_1px_2px_rgba(0,0,0,0.01)]">
                  平均掌握度 {avgMasteryVal}%
                </span>
                {dueReviewCount > 0 && (
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-rose-50/60 px-3 py-1 text-[11px] font-bold text-rose-705 border border-rose-205/30 dark:bg-rose-500/10 dark:text-rose-350 dark:border-rose-500/20 shadow-sm animate-pulse">
                    {dueReviewCount} 待复习
                  </span>
                )}
              </div>
            }
            previewContent={
              states.length > 0 ? (
                <div className="mt-4 space-y-2.5 border-t border-slate-100/40 dark:border-slate-800/30 pt-3.5 w-full">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold text-slate-405 dark:text-slate-500 uppercase tracking-wider">掌握分布比例</span>
                    <span className="text-[11px] font-extrabold text-teal-605 dark:text-teal-400 bg-teal-55 dark:bg-teal-950/30 border border-teal-100/40 dark:border-teal-900/30 px-2 py-0.5 rounded-md shadow-sm">
                      平均 {avgMasteryVal}%
                    </span>
                  </div>
                  <div className="space-y-2 px-1">
                    <div className="space-y-1">
                      <div className="flex justify-between text-[10.5px] text-slate-500 dark:text-slate-400 font-medium">
                        <span className="flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />高熟练度 ({masteredCount}个)</span>
                        <span className="font-bold text-emerald-650 dark:text-emerald-400">{Math.round((masteredCount / states.length) * 100)}%</span>
                      </div>
                      <div className="h-1.5 bg-slate-100 dark:bg-slate-800/60 rounded-full overflow-hidden shadow-inner">
                        <div className="h-full bg-gradient-to-r from-emerald-400 to-teal-500 rounded-full" style={{ width: `${(masteredCount / states.length) * 100}%` }} />
                      </div>
                    </div>
                    <div className="space-y-1">
                      <div className="flex justify-between text-[10.5px] text-slate-500 dark:text-slate-400 font-medium">
                        <span className="flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-indigo-500" />良好掌握 ({goodCount}个)</span>
                        <span className="font-bold text-indigo-650 dark:text-indigo-400">{Math.round((goodCount / states.length) * 100)}%</span>
                      </div>
                      <div className="h-1.5 bg-slate-100 dark:bg-slate-800/60 rounded-full overflow-hidden shadow-inner">
                        <div className="h-full bg-gradient-to-r from-indigo-400 to-violet-500 rounded-full" style={{ width: `${(goodCount / states.length) * 100}%` }} />
                      </div>
                    </div>
                  </div>
                </div>
              ) : undefined
            }
          />
        </div>

        {/* Feedback Loop Panel */}
        {states.length > 0 && (
          <div className="flex flex-col md:flex-row items-center justify-between gap-4 p-5 rounded-2xl bg-indigo-50/15 border border-indigo-100/35 dark:bg-slate-900/35 dark:border-slate-800/40 relative overflow-hidden animate-[fadeIn_0.5s_ease-out]">
            <div className="absolute inset-0 bg-gradient-to-r from-teal-500/[0.02] via-transparent to-indigo-500/[0.02] pointer-events-none" />
            <div className="flex items-center gap-3.5 relative z-10">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-teal-500/10 text-teal-655 dark:bg-teal-950/40 dark:text-teal-400 border border-teal-500/15 shadow-sm shadow-teal-500/5">
                <RefreshCw className="h-4 w-4 animate-spin-slow" />
              </span>
              <div>
                <h4 className="text-[13.5px] font-bold text-slate-850 dark:text-slate-205 flex items-center gap-2">
                  画像自适应反馈闭环已激活
                </h4>
                <p className="text-[12px] text-slate-500 dark:text-slate-450 font-light mt-0.5 leading-relaxed">
                  系统已根据学习画像中的诊断结果，自动调整知识库中的讲义重点，并为下一次考试智能倾斜出题。
                </p>
              </div>
            </div>
            
            <div className="flex items-center gap-2 shrink-0 text-xs font-semibold text-slate-405 dark:text-slate-500 relative z-10 bg-slate-50/40 dark:bg-slate-900/50 px-3.5 py-1.5 rounded-xl border border-slate-150/30 dark:border-slate-800/40">
              <span>掌握度画像</span>
              <svg width="24" height="12" viewBox="0 0 24 12" fill="none" className="overflow-visible text-teal-500">
                <path d="M24 6H4M4 6L8 2M4 6L8 10" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 2" />
              </svg>
              <span className="text-teal-600 dark:text-teal-405 font-bold">闭环优化中</span>
            </div>
          </div>
        )}

        {/* Bottom Section: Recent Exams & Mastery Distribution */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 mt-2 relative z-10">
          {/* Left Side: Recent Exams (Col-span 8) */}
          <div className="lg:col-span-8">
            <RecentExamsWidget items={historyItems} courseId={courseId} />
          </div>

          {/* Right Side: Mastery Distribution (Col-span 4) */}
          <div className="lg:col-span-4">
            <MiniStatsWidget
              masteredCount={masteredCount}
              goodCount={goodCount}
              dueReviewCount={dueReviewCount}
              totalCount={states.length}
              hasExams={historyItems.length > 0}
              isDocGenerating={isDocGenerating}
              isBuilt={isBuilt}
            />
          </div>
        </div>

        {(historyQuery.error || masteryQuery.error || reviewsQuery.error) ? (
          <div className="rounded-2xl border border-red-200 bg-red-500/5 px-5 py-4 text-sm text-red-700 dark:border-red-500/20 dark:text-red-305 backdrop-blur-sm relative z-10">
            {getApiErrorMessage(historyQuery.error ?? masteryQuery.error ?? reviewsQuery.error, "课程导航数据加载失败")}
          </div>
        ) : null}

      </div>
    </div>
  );
}
