import { useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { Link, useParams, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { LucideIcon } from "lucide-react";
import {
  Compass,
  Sparkles,
  BookOpen,
  FileText,
  BarChart3,
  Lock,
} from "lucide-react";

import { cn } from "../../lib/utils";
import { buildCoursePath, getCourseRouteSegmentFromPathname } from "../../lib/courseNavigation";
import {
  buildKnowledgeBuildRuntimeQueryKey,
  buildRuntimeFailureBackoffMs,
  fetchKnowledgeBuildRuntime,
  hasKnowledgeBuildDraftFallback,
} from "../../lib/knowledgeBuildRuntime";
import {
  getExamHistoryApiV1CoursesCourseIdExamsHistoryGetQueryKey,
  useExamHistoryApiV1CoursesCourseIdExamsHistoryGet,
} from "../../api/generated/exams";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { apiClient } from "../../api/client";
import type { ApiResponse } from "../../api/types";
import type { DocGenGetResponse, ExamHistoryItem } from "../../api/generated/model";
import { TopBar } from "../layout/TopBar";
import { ACTIVE_DOC_BUILD_STATUSES } from "../knowledge-docs/utils";

interface CoursePagePillTitleProps {
  icon: LucideIcon;
  label: string;
  href?: string;
  className?: string;
  innerClassName?: string;
  placement?: "layout" | "page";
  scrollRootRef?: RefObject<HTMLElement | null>;
}

interface CourseNavTooltipState {
  text: string;
  left: number;
  top: number;
}

function courseNavTooltipFromTarget(text: string, target: HTMLElement): CourseNavTooltipState {
  const rect = target.getBoundingClientRect();
  return {
    text,
    left: rect.left + rect.width / 2,
    top: rect.bottom + 8,
  };
}

export const ENABLE_PERSISTENT_COURSE_NAV = true;
export const SHOW_COURSE_OVERVIEW_NAV_ENTRY = false;
const COURSE_NAV_TOP_REVEAL_PX = 24;
const COURSE_NAV_HIDE_DELTA_PX = 12;
const COURSE_NAV_SHOW_DELTA_PX = 6;

export function CoursePagePillTitle({
  icon: Icon,
  label,
  href,
  className,
  innerClassName,
  placement = "page",
  scrollRootRef,
}: CoursePagePillTitleProps) {
  const params = useParams<{ courseId: string }>();
  const { pathname } = useLocation();
  const queryClient = useQueryClient();
  const [tooltip, setTooltip] = useState<CourseNavTooltipState | null>(null);
  const [isScrollHidden, setIsScrollHidden] = useState(false);
  const previousTrainingUnlockedRef = useRef<boolean | null>(null);
  const courseId = params.courseId || (href ? href.split("/")[2] : undefined);
  const shouldHideInlineCourseNav = Boolean(courseId && ENABLE_PERSISTENT_COURSE_NAV && placement === "page");

  useLayoutEffect(() => {
    setIsScrollHidden(false);
  }, [pathname]);

  useEffect(() => {
    const scrollRoot = scrollRootRef?.current;
    if (!scrollRoot) return;

    const previousScrollTops = new WeakMap<HTMLElement, number>();
    let activeScrollTarget: HTMLElement | null = null;
    let accumulatedDelta = 0;
    let activeDirection = 0;
    let ignoreDirectionUntil = 0;

    const handleScroll = (event: Event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      if (
        target !== scrollRoot &&
        !target.classList.contains("course-page-scroll-container") &&
        !target.classList.contains("doc-scroll-container")
      ) return;

      const currentScrollTop = target.scrollTop;
      const previousScrollTop = previousScrollTops.get(target);
      previousScrollTops.set(target, currentScrollTop);

      if (currentScrollTop <= COURSE_NAV_TOP_REVEAL_PX) {
        activeScrollTarget = target;
        accumulatedDelta = 0;
        activeDirection = 0;
        setIsScrollHidden(false);
        return;
      }

      if (previousScrollTop === undefined || activeScrollTarget !== target) {
        activeScrollTarget = target;
        accumulatedDelta = 0;
        activeDirection = 0;
        return;
      }

      if (performance.now() < ignoreDirectionUntil) {
        accumulatedDelta = 0;
        activeDirection = 0;
        return;
      }

      const delta = currentScrollTop - previousScrollTop;
      if (Math.abs(delta) < 1) return;

      const direction = delta > 0 ? 1 : -1;
      accumulatedDelta = direction === activeDirection ? accumulatedDelta + delta : delta;
      activeDirection = direction;

      if (accumulatedDelta >= COURSE_NAV_HIDE_DELTA_PX) {
        accumulatedDelta = 0;
        ignoreDirectionUntil = performance.now() + 240;
        setIsScrollHidden(true);
      } else if (accumulatedDelta <= -COURSE_NAV_SHOW_DELTA_PX) {
        accumulatedDelta = 0;
        ignoreDirectionUntil = performance.now() + 240;
        setIsScrollHidden(false);
      }
    };

    scrollRoot.addEventListener("scroll", handleScroll, { capture: true, passive: true });
    return () => scrollRoot.removeEventListener("scroll", handleScroll, true);
  }, [pathname, scrollRootRef]);

  useEffect(() => {
    if (isScrollHidden) setTooltip(null);
  }, [isScrollHidden]);

  const shellClassName = cn(
    "sticky top-0 z-30 grid w-full shrink-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center border-b bg-[#fafafa]/92 px-4 backdrop-blur-md transition-[height,transform,opacity,border-color] duration-200 ease-out motion-reduce:transition-none dark:bg-[#0b0f19]/92",
    isScrollHidden
      ? "pointer-events-none h-0 -translate-y-3 overflow-hidden border-transparent opacity-0"
      : "h-16 translate-y-0 overflow-visible border-slate-200/70 opacity-100 dark:border-slate-800/60",
    className,
  );
  const navClassName = cn(
    "flex max-w-full items-center gap-1 overflow-x-auto rounded-[10px] border border-slate-200/80 bg-white/95 p-1 shadow-[0_2px_12px_rgba(15,23,42,0.05)] scrollbar-none dark:border-slate-800/80 dark:bg-slate-900/95",
    innerClassName,
  );

  // 1. Query Document Build Status
  const docMarkdownQuery = useQuery({
    queryKey: ["docgen-content", courseId, null, "metadata"],
    queryFn: async (): Promise<DocGenGetResponse> => {
      if (!courseId) throw new Error("缺少课程 ID");
      const response = await apiClient<ApiResponse<DocGenGetResponse>>({
        method: "POST",
        url: `/api/v1/courses/${courseId}/knowledge/docs`,
        params: {
          include_markdown: false,
          include_draft: false,
        },
      });
      if (!response.data) throw new Error("加载知识文档状态失败");
      return response.data;
    },
    enabled: Boolean(courseId) && !shouldHideInlineCourseNav,
    staleTime: 30000,
  });

  const runtimeQuery = useQuery({
    queryKey: courseId
      ? [...buildKnowledgeBuildRuntimeQueryKey(courseId), "course-nav"]
      : ["knowledge-doc-build-nav-empty"],
    queryFn: () => fetchKnowledgeBuildRuntime(courseId as string),
    enabled: Boolean(courseId) && !shouldHideInlineCourseNav,
    staleTime: 2500,
    refetchInterval: (query) => {
      const failureBackoff = buildRuntimeFailureBackoffMs(query.state.fetchFailureCount);
      if (failureBackoff !== null) return failureBackoff;
      const statuses = [
        query.state.data?.aggregate?.status,
        query.state.data?.docgen?.status,
        query.state.data?.graph?.status,
        query.state.data?.graph_status,
      ].map((status) => (status ?? "").trim());
      return statuses.some((status) => ACTIVE_DOC_BUILD_STATUSES.has(status) || status === "pending")
        ? 2500
        : false;
    },
  });

  const runtimeStatuses = useMemo(() => {
    return [
      runtimeQuery.data?.aggregate?.status,
      runtimeQuery.data?.docgen?.status,
      runtimeQuery.data?.graph?.status,
      runtimeQuery.data?.graph_status,
    ].map((status) => (status ?? "").trim());
  }, [
    runtimeQuery.data?.aggregate?.status,
    runtimeQuery.data?.docgen?.status,
    runtimeQuery.data?.graph?.status,
    runtimeQuery.data?.graph_status,
  ]);

  const buildStatus = useMemo(() => {
    return (
      runtimeQuery.data?.docgen?.status
      ?? runtimeQuery.data?.aggregate?.status
      ?? docMarkdownQuery.data?.build?.status
      ?? ""
    ).trim();
  }, [
    docMarkdownQuery.data?.build?.status,
    runtimeQuery.data?.aggregate?.status,
    runtimeQuery.data?.docgen?.status,
  ]);

  const isBuilding = useMemo(() => {
    return ACTIVE_DOC_BUILD_STATUSES.has(buildStatus)
      || runtimeStatuses.some((status) => ACTIVE_DOC_BUILD_STATUSES.has(status) || status === "pending");
  }, [buildStatus, runtimeStatuses]);

  const isBuilt = useMemo(() => {
    return Boolean(runtimeQuery.data?.docs_ready || docMarkdownQuery.data?.exists);
  }, [docMarkdownQuery.data?.exists, runtimeQuery.data?.docs_ready]);

  const isTrainingUnlocked = useMemo(() => {
    if (typeof runtimeQuery.data?.training_unlocked === "boolean") {
      return runtimeQuery.data.training_unlocked;
    }
    return isBuilt && !isBuilding;
  }, [isBuilding, isBuilt, runtimeQuery.data?.training_unlocked]);

  const hasDraftDoc = useMemo(() => {
    return Boolean(
      docMarkdownQuery.data?.build?.draft_available || hasKnowledgeBuildDraftFallback(runtimeQuery.data),
    );
  }, [docMarkdownQuery.data?.build?.draft_available, runtimeQuery.data]);

  const hasRuntimeBuildStarted = useMemo(() => {
    return Boolean(runtimeQuery.data?.build_group_id) || runtimeStatuses.some((status) => Boolean(status && status !== "idle"));
  }, [runtimeQuery.data?.build_group_id, runtimeStatuses]);

  const hasBuildStarted = useMemo(() => {
    return isBuilt || hasDraftDoc || hasRuntimeBuildStarted || Boolean(buildStatus && buildStatus !== "idle");
  }, [buildStatus, hasDraftDoc, hasRuntimeBuildStarted, isBuilt]);

  const hasResolvedBuildAvailability = docMarkdownQuery.isFetched && (runtimeQuery.isFetched || runtimeQuery.isError);

  useEffect(() => {
    if (!courseId) return;
    const previous = previousTrainingUnlockedRef.current;
    previousTrainingUnlockedRef.current = isTrainingUnlocked;
    if (previous !== false || !isTrainingUnlocked) return;

    void queryClient.invalidateQueries({ queryKey: ["docgen-content", courseId] });
    void queryClient.invalidateQueries({ queryKey: buildKnowledgeBuildRuntimeQueryKey(courseId) });
    void queryClient.invalidateQueries({ queryKey: ["exam-prewarm-status", courseId] });
    void queryClient.invalidateQueries({ queryKey: ["exam-question-templates", courseId] });
    void queryClient.invalidateQueries({
      queryKey: getExamHistoryApiV1CoursesCourseIdExamsHistoryGetQueryKey(courseId, { page: 1, size: 24 }),
    });
  }, [courseId, isTrainingUnlocked, queryClient]);

  // 2. Query Exam History
  const historyQuery = useExamHistoryApiV1CoursesCourseIdExamsHistoryGet(
    courseId ?? "",
    { page: 1, size: 24 },
    { query: { enabled: Boolean(courseId) && !shouldHideInlineCourseNav } }
  );

  const hasExams = useMemo(() => {
    const historyItems = unwrapOrvalResponse<{ items?: ExamHistoryItem[] }>(historyQuery.data)?.items ?? [];
    return historyItems.length > 0;
  }, [historyQuery.data]);

  const currentSegment = getCourseRouteSegmentFromPathname(pathname);

  const showTooltip = (text: string, target: HTMLElement) => {
    setTooltip(courseNavTooltipFromTarget(text, target));
  };

  const hideTooltip = () => {
    setTooltip(null);
  };

  if (!courseId) {
    const inner = (
      <div className={cn("inline-flex h-8 items-center gap-2 rounded-md px-3 text-[12px] font-semibold text-slate-600 dark:text-slate-300", innerClassName)}>
        <Icon className="h-3 w-3 shrink-0" />
        <span>{label}</span>
      </div>
    );
    return (
      <div className={shellClassName} onFocusCapture={() => setIsScrollHidden(false)}>
        <div />
        {inner}
        <div className="flex justify-end">
          <TopBar />
        </div>
      </div>
    );
  }

  if (shouldHideInlineCourseNav) {
    return null;
  }

  const navItems = [
    {
      id: "build",
      label: "方案规划",
      icon: Sparkles,
      href: buildCoursePath(courseId, "build"),
      description: "上传资料、完成前置诊断，并确认本轮学习路径。",
    },
    {
      id: "knowledge-docs",
      label: "知识库",
      icon: BookOpen,
      href: buildCoursePath(courseId, "knowledge-docs"),
      description: "查看知识文档、课程图谱和伴读式划选问答。",
    },
    {
      id: "exams",
      label: "训练中心",
      icon: FileText,
      href: buildCoursePath(courseId, "exams"),
      description: "生成测验或考卷，围绕薄弱点进行专项训练。",
    },
    {
      id: "profile",
      label: "课程画像",
      icon: BarChart3,
      href: buildCoursePath(courseId, "profile"),
      description: "查看掌握分布、测验记录和后续复习方向。",
    },
  ] as const;

  return (
    <div className={shellClassName} onFocusCapture={() => setIsScrollHidden(false)}>
      <div />
      <nav className={navClassName} aria-label="课程页面导航">
        {SHOW_COURSE_OVERVIEW_NAV_ENTRY && href ? (
          <>
            <Link
              to={href}
              className="group relative flex h-9 shrink-0 items-center gap-2 rounded-lg px-3 text-[12px] font-semibold text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white dark:focus-visible:ring-indigo-500"
              title="课程总览：回到课程入口与近期状态。"
              aria-label="课程总览：回到课程入口与近期状态。"
              onMouseEnter={(event) => showTooltip("课程总览：回到课程入口与近期状态。", event.currentTarget)}
              onMouseLeave={hideTooltip}
              onFocus={(event) => showTooltip("课程总览：回到课程入口与近期状态。", event.currentTarget)}
              onBlur={hideTooltip}
            >
              <Compass className="h-3.5 w-3.5 shrink-0 text-slate-400 transition-colors group-hover:text-indigo-600 dark:group-hover:text-indigo-300" />
              <span className="whitespace-nowrap">总览</span>
              <span className="h-3 w-3 shrink-0" aria-hidden="true" />
            </Link>
            <div className="h-5 w-px shrink-0 bg-slate-200 dark:bg-slate-800" />
          </>
        ) : null}

        {navItems.map((item) => {
          const isActive = item.id === currentSegment || (item.id === "exams" && label === "训练中心");
          let disabledReason = "";
          if (!isActive && item.id === "knowledge-docs" && hasResolvedBuildAvailability && !hasBuildStarted) {
            disabledReason = "请先开始构建知识库";
          } else if (!isActive && item.id === "exams" && !isTrainingUnlocked) {
            disabledReason = isBuilding ? "知识库构建中" : "请先构建知识库";
          } else if (!isActive && item.id === "profile") {
            if (!isTrainingUnlocked) {
              disabledReason = isBuilding ? "知识库构建中" : "请先构建知识库";
            } else if (!hasExams) {
              disabledReason = "需先完成测验";
            }
          }

          const ItemIcon = item.icon;
          const tooltipText = disabledReason
            ? `${item.label}：${disabledReason}`
            : `${item.label}：${item.description}`;
          const itemClassName = cn(
            "group relative flex h-9 shrink-0 items-center gap-2 rounded-lg px-3 text-[12px] font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 dark:focus-visible:ring-indigo-500",
            isActive
              ? "bg-slate-950 text-white shadow-sm dark:bg-slate-100 dark:text-slate-950"
              : "text-slate-600 hover:bg-slate-100 hover:text-slate-950 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white",
          );

          if (disabledReason) {
            return (
              <div
                key={item.id}
                role="link"
                tabIndex={0}
                title={tooltipText}
                aria-label={tooltipText}
                aria-disabled="true"
                onMouseEnter={(event) => showTooltip(tooltipText, event.currentTarget)}
                onMouseLeave={hideTooltip}
                onFocus={(event) => showTooltip(tooltipText, event.currentTarget)}
                onBlur={hideTooltip}
                className="flex h-9 shrink-0 cursor-not-allowed select-none items-center gap-2 rounded-lg px-3 text-[12px] font-semibold text-slate-400 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-indigo-400 dark:text-slate-600 dark:focus-visible:ring-indigo-500"
              >
                <ItemIcon className="h-3.5 w-3.5 shrink-0 text-slate-300 dark:text-slate-700" />
                <span className="whitespace-nowrap">{item.label}</span>
                <span className="flex h-3 w-3 shrink-0 items-center justify-center" aria-hidden="true">
                  <Lock className="h-3 w-3 text-slate-300 dark:text-slate-700" strokeWidth={1.5} />
                </span>
              </div>
            );
          }

          return (
            <Link
              key={item.id}
              to={item.href}
              className={itemClassName}
              aria-current={isActive ? "page" : undefined}
              aria-label={tooltipText}
              title={tooltipText}
              onMouseEnter={(event) => showTooltip(tooltipText, event.currentTarget)}
              onMouseLeave={hideTooltip}
              onFocus={(event) => showTooltip(tooltipText, event.currentTarget)}
              onBlur={hideTooltip}
            >
              <ItemIcon className={cn("h-3.5 w-3.5 shrink-0", isActive ? "text-white dark:text-slate-950" : "text-slate-400 transition-colors group-hover:text-indigo-600 dark:group-hover:text-indigo-300")} />
              <span className="whitespace-nowrap">{item.label}</span>
              <span className="h-3 w-3 shrink-0" aria-hidden="true" />
              {isActive ? (
                <span className="absolute inset-x-2 -bottom-1 h-0.5 rounded-full bg-indigo-400 dark:bg-indigo-500" />
              ) : null}
            </Link>
          );
        })}
      </nav>
      <div className="flex justify-end pr-1">
        <TopBar />
      </div>
      {tooltip && typeof document !== "undefined"
        ? createPortal(
            <div
              className="pointer-events-none fixed z-[140] max-w-[260px] rounded-lg border border-slate-200 bg-white px-3 py-2 text-[12px] font-medium leading-5 text-slate-700 shadow-[0_12px_32px_-18px_rgba(15,23,42,0.55)] dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              style={{ left: tooltip.left, top: tooltip.top, transform: "translateX(-50%)" }}
              role="tooltip"
            >
              {tooltip.text}
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
