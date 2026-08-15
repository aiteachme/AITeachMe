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
import { useNavigate, useParams } from "react-router-dom";

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
import {
  COURSE_PAGE_CONTENT_CLASS,
  COURSE_PAGE_HEADER_ACTION_BUTTON_CLASS,
  COURSE_PAGE_SHELL_CLASS,
} from "../components/course/CoursePageHeader";
import { isReviewDueSoon } from "../components/profile";
import { buildCoursePath, buildCourseSubPath } from "../lib/courseNavigation";
import { cn } from "../lib/utils";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { useCourseDisplayName } from "../hooks/useCourseDisplayName";
import { buildExamTitle, formatModeLabel } from "../components/exams/examDisplay";
import { fetchKnowledgeBuildRuntime } from "../lib/knowledgeBuildRuntime";
import { fetchKnowledgeOverview, OVERVIEW_INCLUDE_PRESETS, buildKnowledgeOverviewQueryKey } from "../lib/knowledgeOverview";
import {
  graphFocusSubgraphApiV1CoursesCourseIdKnowledgeGraphSubgraphPost,
  graphFullApiV1CoursesCourseIdKnowledgeGraphFullPost,
} from "../api/generated/knowledge";

const pageShellClass = `${COURSE_PAGE_SHELL_CLASS} relative pt-8 sm:pt-10`;
const alertClass = "rounded-2xl border border-amber-250 bg-amber-500/5 px-6 py-5 text-sm text-amber-900 dark:border-amber-500/20 dark:text-amber-300 backdrop-blur-sm";
const INITIAL_FOCUSED_GRAPH_THRESHOLD = 180;
const INITIAL_FOCUSED_GRAPH_EDGE_THRESHOLD = 520;
const INITIAL_FOCUSED_GRAPH_LIMIT = 140;

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
      border: "border-slate-200 hover:border-indigo-300 dark:border-slate-800 dark:hover:border-indigo-500/50",
      iconContainer: "bg-indigo-50 text-indigo-600 dark:bg-indigo-950/50 dark:text-indigo-400",
      buttonClass: "border border-indigo-200 bg-white text-indigo-600 hover:bg-indigo-50 dark:border-indigo-500/30 dark:bg-slate-950 dark:text-indigo-300 dark:hover:bg-indigo-500/10",
    },
    violet: {
      border: "border-slate-200 hover:border-violet-300 dark:border-slate-800 dark:hover:border-violet-500/50",
      iconContainer: "bg-violet-50 text-violet-600 dark:bg-violet-950/50 dark:text-violet-400",
      buttonClass: "border border-violet-200 bg-white text-violet-600 hover:bg-violet-50 dark:border-violet-500/30 dark:bg-slate-950 dark:text-violet-300 dark:hover:bg-violet-500/10",
    },
    teal: {
      border: "border-slate-200 hover:border-teal-300 dark:border-slate-800 dark:hover:border-teal-500/50",
      iconContainer: "bg-teal-50 text-teal-700 dark:bg-teal-950/50 dark:text-teal-400",
      buttonClass: "border border-teal-200 bg-white text-teal-700 hover:bg-teal-50 dark:border-teal-500/30 dark:bg-slate-950 dark:text-teal-300 dark:hover:bg-teal-500/10",
    },
  }[theme];

  return (
    <div
      onClick={!disabled ? onClick : undefined}
      className={cn(
        "group relative flex min-h-[300px] w-full flex-col justify-between rounded-lg border bg-white p-5 text-left transition-colors dark:bg-slate-900/80",
        zIndexClass,
        disabled
          ? "cursor-not-allowed border-slate-200 bg-slate-50/50 opacity-60 dark:border-slate-800 dark:bg-slate-900/20"
          : isGenerating
            ? "cursor-pointer border-indigo-300 bg-indigo-50/20 dark:border-indigo-500/40 dark:bg-indigo-950/10"
            : cn(themeStyles.border, "cursor-pointer")
      )}
    >
      {/* Top Part: Icon, Title, Description and Live Preview */}
      <div className="flex flex-col gap-4 relative z-10 w-full">
        <span className={cn(
          "flex h-10 w-10 items-center justify-center rounded-lg",
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
            <Icon className="h-5 w-5" strokeWidth={1.5} />
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
            className={cn("flex h-8 shrink-0 items-center gap-1 rounded-lg px-3.5 text-xs font-semibold transition-colors", themeStyles.buttonClass)}
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
    <div className="flex min-h-[350px] flex-col border-t border-slate-200 py-6 dark:border-slate-800">
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
          <p className="max-w-[280px] leading-relaxed">暂无测验记录，您可以进入“训练中心”开始您的第一次测验。</p>
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
              className="group flex cursor-pointer items-center justify-between border-b border-slate-100 px-1 py-3.5 transition-colors last:border-b-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-900/50"
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
  } else if (!hasExams && totalCount === 0) {
    emptyStateContent = (
      <div className="flex-1 flex flex-col items-center justify-center text-center p-4">
        <div className="h-14 w-14 rounded-full bg-slate-50 dark:bg-slate-800/45 flex items-center justify-center text-slate-400 dark:text-slate-555 mb-3 border border-slate-100 dark:border-slate-800">
          <Lock className="h-6.5 w-6.5" strokeWidth={1.5} />
        </div>
        <p className="text-[13px] text-slate-400 dark:text-slate-555 max-w-[200px] leading-relaxed font-light">
          需先完成测验，以生成当前学科的课程画像。
        </p>
      </div>
    );
  }

  return (
    <div className="flex min-h-[350px] flex-col border-t border-slate-200 py-6 dark:border-slate-800">
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
    return Boolean(docMarkdownQuery.data?.exists);
  }, [docMarkdownQuery.data?.exists]);

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
          staleTime: 0,
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

        // 4. Prefetch the same initial graph window that the graph page will render first.
        const nodeCount = overviewData?.stats?.node_count ?? 0;
        const edgeCount = overviewData?.stats?.edge_count ?? 0;
        const shouldPrefetchFocusedGraph =
          nodeCount > INITIAL_FOCUSED_GRAPH_THRESHOLD ||
          edgeCount > INITIAL_FOCUSED_GRAPH_EDGE_THRESHOLD;
        const initialFocusedGraphLimit = Math.max(
          80,
          Math.min(
            INITIAL_FOCUSED_GRAPH_THRESHOLD,
            Math.max(
              INITIAL_FOCUSED_GRAPH_LIMIT,
              Math.round(Math.sqrt(Math.max(1, nodeCount)) * 12),
            ),
          ),
        );
        void queryClient.prefetchQuery({
          queryKey: [
            "graph-initial",
            courseId,
            nodeCount,
            edgeCount,
            shouldPrefetchFocusedGraph ? "focused" : "full",
            initialFocusedGraphLimit,
          ],
          queryFn: async () => {
            if (shouldPrefetchFocusedGraph) {
              return unwrapOrvalResponse(
                await graphFocusSubgraphApiV1CoursesCourseIdKnowledgeGraphSubgraphPost(courseId, {
                  center_knowledge_unit_id: null,
                  topic: null,
                  edge_type: null,
                  hops: 1,
                  limit: initialFocusedGraphLimit,
                }),
              ) ?? null;
            }
            return unwrapOrvalResponse(
              await graphFullApiV1CoursesCourseIdKnowledgeGraphFullPost(courseId),
            ) ?? null;
          },
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
      <div className={`${COURSE_PAGE_CONTENT_CLASS} gap-5 relative z-10`}>

        {/* Top Header & Version Switcher */}
        <section className="border-b border-slate-200 pb-5 dark:border-slate-800">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-3">
                  <h1 className="break-words text-[30px] font-bold leading-[1.12] tracking-[-0.025em] text-slate-950 dark:text-slate-50 sm:text-[34px] lg:text-[38px]">
                    {courseName ?? "当前课程"}
                  </h1>
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/25 bg-emerald-500/5 px-3 py-1 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                    <span className="h-2 w-2 rounded-full bg-emerald-500" />
                    v1.0 (当前版本)
                  </span>
                </div>
              </div>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-500 dark:text-slate-400 sm:text-[15px]">
                欢迎回到课程空间。您的专属学习大盘已准备就绪，在这里您可以纵览全局知识脉络，追踪学习动态。
              </p>
            </div>

            <div className="flex shrink-0 flex-wrap gap-2 lg:justify-end">
              <Button
                type="button"
                variant="outline"
                onClick={() => navigate(buildCoursePath(courseId, "build"))}
                className={COURSE_PAGE_HEADER_ACTION_BUTTON_CLASS}
              >
                <RefreshCw className="h-4 w-4 shrink-0" />
                课程配置与重构
              </Button>
            </div>
          </div>
        </section>

        {/* Three-Column Nav Tiles Layout */}
        <div className="relative z-10 grid grid-cols-1 gap-4 md:grid-cols-3">

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
                  {/* Desktop Connector - Disabled */}
                  <div className="absolute right-[-56px] top-1/2 -translate-y-1/2 w-[56px] h-[56px] flex items-center justify-center z-10 pointer-events-none hidden md:flex">
                    <div className="absolute w-full h-[2px] bg-slate-200 dark:bg-slate-800/60" />
                    <div
                      className="relative w-8 h-8 rounded-full bg-slate-50 dark:bg-[#0b0f19] flex items-center justify-center cursor-not-allowed pointer-events-auto"
                      title={isDocGenerating ? "知识库构建中" : "请先构建知识库"}
                    >
                      <div className="absolute inset-0 rounded-full border-2 border-slate-200 dark:border-slate-800" />
                      <ChevronRight className="w-4 h-4 text-slate-300 dark:text-slate-600 stroke-[3]" />
                    </div>
                  </div>
                  {/* Mobile Connector - Disabled */}
                  <div className="absolute bottom-[-24px] left-1/2 -translate-x-1/2 h-[24px] w-[56px] flex items-center justify-center z-10 pointer-events-none block md:hidden">
                    <div className="absolute h-full w-[2px] bg-slate-200 dark:bg-slate-800/60" />
                    <div
                      className="relative w-7 h-7 rounded-full bg-slate-50 dark:bg-[#0b0f19] flex items-center justify-center cursor-not-allowed pointer-events-auto"
                      title={isDocGenerating ? "知识库构建中" : "请先构建知识库"}
                    >
                      <div className="absolute inset-0 rounded-full border-2 border-slate-200 dark:border-slate-800" />
                      <ChevronRight className="w-3.5 h-3.5 text-slate-300 dark:text-slate-600 stroke-[3] rotate-90" />
                    </div>
                  </div>
                </>
              ) : (
                <>
                  {/* Desktop Connector */}
                  <div className="absolute right-[-56px] top-1/2 -translate-y-1/2 w-[56px] h-[56px] flex items-center justify-center z-20 pointer-events-none hidden md:flex group/arrow">
                    <div className="absolute w-full h-[2px] bg-indigo-500/40 shadow-[0_0_10px_rgba(99,102,241,0.3)] transition-colors" />
                    <div
                      onClick={(e) => { e.stopPropagation(); navigate(buildCoursePath(courseId, "exams")); }}
                      className="relative w-8 h-8 rounded-full bg-slate-50 dark:bg-[#0b0f19] flex items-center justify-center pointer-events-auto cursor-pointer transition-all duration-300"
                      title="进入 训练中心"
                    >
                      <div className="absolute inset-[-4px] rounded-full border-[1.5px] border-indigo-400/40 animate-ping opacity-50 duration-1000" />
                      <div className="absolute inset-0 rounded-full border-[2px] border-indigo-500/30 group-hover/arrow:border-indigo-500/80 transition-colors duration-300" />
                      <ChevronRight className="w-4 h-4 text-indigo-600 dark:text-indigo-400 stroke-[3] group-hover/arrow:translate-x-[2px] transition-transform duration-300" />
                    </div>
                  </div>
                  {/* Mobile Connector */}
                  <div className="absolute bottom-[-24px] left-1/2 -translate-x-1/2 h-[24px] w-[56px] flex items-center justify-center z-20 pointer-events-none block md:hidden group/arrow-v">
                    <div className="absolute h-full w-[2px] bg-indigo-500/40 shadow-[0_0_10px_rgba(99,102,241,0.3)] transition-colors" />
                    <div
                      onClick={(e) => { e.stopPropagation(); navigate(buildCoursePath(courseId, "exams")); }}
                      className="relative w-7 h-7 rounded-full bg-slate-50 dark:bg-[#0b0f19] flex items-center justify-center pointer-events-auto cursor-pointer transition-all duration-300"
                      title="进入 训练中心"
                    >
                      <div className="absolute inset-[-4px] rounded-full border-[1.5px] border-indigo-400/40 animate-ping opacity-50 duration-1000" />
                      <div className="absolute inset-0 rounded-full border-[2px] border-indigo-500/30 group-hover/arrow-v:border-indigo-500/80 transition-colors duration-300" />
                      <ChevronRight className="w-3.5 h-3.5 text-indigo-600 dark:text-indigo-400 stroke-[3] rotate-90 group-hover/arrow-v:translate-y-[2px] transition-transform duration-300" />
                    </div>
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

          {/* Card 2: 训练中心 */}
          <NavTile
            icon={FileText}
            title="训练中心"
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
              (!isBuilt || isDocGenerating) ? (
                <>
                  {/* Desktop Connector - Disabled */}
                  <div className="absolute right-[-56px] top-1/2 -translate-y-1/2 w-[56px] h-[56px] flex items-center justify-center z-10 pointer-events-none hidden md:flex">
                    <div className="absolute w-full h-[2px] bg-slate-200 dark:bg-slate-800/60" />
                    <div
                      className="relative w-8 h-8 rounded-full bg-slate-50 dark:bg-[#0b0f19] flex items-center justify-center cursor-not-allowed pointer-events-auto"
                      title={isDocGenerating ? "知识库构建中" : "请先构建知识库"}
                    >
                      <div className="absolute inset-0 rounded-full border-2 border-slate-200 dark:border-slate-800" />
                      <ChevronRight className="w-4 h-4 text-slate-300 dark:text-slate-600 stroke-[3]" />
                    </div>
                  </div>
                  {/* Mobile Connector - Disabled */}
                  <div className="absolute bottom-[-24px] left-1/2 -translate-x-1/2 h-[24px] w-[56px] flex items-center justify-center z-10 pointer-events-none block md:hidden">
                    <div className="absolute h-full w-[2px] bg-slate-200 dark:bg-slate-800/60" />
                    <div
                      className="relative w-7 h-7 rounded-full bg-slate-50 dark:bg-[#0b0f19] flex items-center justify-center cursor-not-allowed pointer-events-auto"
                      title={isDocGenerating ? "知识库构建中" : "请先构建知识库"}
                    >
                      <div className="absolute inset-0 rounded-full border-2 border-slate-200 dark:border-slate-800" />
                      <ChevronRight className="w-3.5 h-3.5 text-slate-300 dark:text-slate-600 stroke-[3] rotate-90" />
                    </div>
                  </div>
                </>
              ) : (
                <>
                  {/* Desktop Connector */}
                  <div className="absolute right-[-56px] top-1/2 -translate-y-1/2 w-[56px] h-[56px] flex items-center justify-center z-20 pointer-events-none hidden md:flex group/arrow-2">
                    <div className="absolute w-full h-[2px] bg-teal-500/40 shadow-[0_0_10px_rgba(20,184,166,0.3)] transition-colors" />
                    <div
                      onClick={(e) => { e.stopPropagation(); navigate(buildCoursePath(courseId, "profile")); }}
                      className="relative w-8 h-8 rounded-full bg-slate-50 dark:bg-[#0b0f19] flex items-center justify-center pointer-events-auto cursor-pointer transition-all duration-300"
                      title="进入课程画像"
                    >
                      <div className="absolute inset-[-4px] rounded-full border-[1.5px] border-teal-400/40 animate-ping opacity-50 duration-1000" />
                      <div className="absolute inset-0 rounded-full border-[2px] border-teal-500/30 group-hover/arrow-2:border-teal-500/80 transition-colors duration-300" />
                      <ChevronRight className="w-4 h-4 text-teal-600 dark:text-teal-400 stroke-[3] group-hover/arrow-2:translate-x-[2px] transition-transform duration-300" />
                    </div>
                  </div>
                  {/* Mobile Connector */}
                  <div className="absolute bottom-[-24px] left-1/2 -translate-x-1/2 h-[24px] w-[56px] flex items-center justify-center z-20 pointer-events-none block md:hidden group/arrow-2-v">
                    <div className="absolute h-full w-[2px] bg-teal-500/40 shadow-[0_0_10px_rgba(20,184,166,0.3)] transition-colors" />
                    <div
                      onClick={(e) => { e.stopPropagation(); navigate(buildCoursePath(courseId, "profile")); }}
                      className="relative w-7 h-7 rounded-full bg-slate-50 dark:bg-[#0b0f19] flex items-center justify-center pointer-events-auto cursor-pointer transition-all duration-300"
                      title="进入课程画像"
                    >
                      <div className="absolute inset-[-4px] rounded-full border-[1.5px] border-teal-400/40 animate-ping opacity-50 duration-1000" />
                      <div className="absolute inset-0 rounded-full border-[2px] border-teal-500/30 group-hover/arrow-2-v:border-teal-500/80 transition-colors duration-300" />
                      <ChevronRight className="w-3.5 h-3.5 text-teal-600 dark:text-teal-400 stroke-[3] rotate-90 group-hover/arrow-2-v:translate-y-[2px] transition-transform duration-300" />
                    </div>
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

          {/* Card 3: 课程画像 */}
          <NavTile
            icon={BarChart3}
            title="课程画像"
            description="基于测验 data、复习进度实时生成的深度诊断报告与今日学习计划。"
            theme="teal"
            disabled={!isBuilt || isDocGenerating}
            disabledReason={
              isDocGenerating
                ? "知识库构建中"
                : !isBuilt
                  ? "请先构建知识库"
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
          <div className="relative flex flex-col items-center justify-between gap-4 border-y border-slate-200 py-5 dark:border-slate-800 md:flex-row">
            <div className="flex items-center gap-3.5 relative z-10">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-teal-500/15 bg-teal-500/10 text-teal-655 dark:bg-teal-950/40 dark:text-teal-400">
                <RefreshCw className="h-4 w-4 animate-spin-slow" />
              </span>
              <div>
                <h4 className="text-[13.5px] font-bold text-slate-850 dark:text-slate-205 flex items-center gap-2">
                  画像自适应反馈闭环已激活
                </h4>
                <p className="text-[12px] text-slate-500 dark:text-slate-450 font-light mt-0.5 leading-relaxed">
                  系统已根据课程画像中的诊断结果，自动调整知识库中的讲义重点，并为下一次考试智能倾斜出题。
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
        <div className="relative z-10 mt-2 grid grid-cols-1 gap-8 lg:grid-cols-12">
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
