import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { AiInteractionProvider, AiInteractionWindow, type AiConversationScope } from "../interaction";
import {
  buildCoursePath,
  getCourseIdFromPathname,
  isFullBleedCoursePath,
  getCourseRouteSegmentFromPathname,
  rememberCourseRoute,
} from "../../lib/courseNavigation";
import {
  buildKnowledgeBuildRuntimeQueryKey,
  buildRuntimeFailureBackoffMs,
  fetchKnowledgeBuildRuntime,
} from "../../lib/knowledgeBuildRuntime";
import { cn } from "../../lib/utils";
import { isElectronRuntime } from "../../lib/electronRuntime";
import { ACTIVE_DOC_BUILD_STATUSES } from "../knowledge-docs/utils";
import { CoursePagePillTitle, ENABLE_PERSISTENT_COURSE_NAV } from "../course/CoursePagePillTitle";
import {
  BarChart3,
  BookOpen,
  ClipboardCheck,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

const SettingsDialog = lazy(() =>
  import("../settings/SettingsDialog").then((module) => ({ default: module.SettingsDialog })),
);

const COURSE_TOP_NAV_META: Record<string, { icon: LucideIcon; label: string }> = {
  build: { icon: Sparkles, label: "方案规划" },
  "knowledge-docs": { icon: BookOpen, label: "知识库" },
  exams: { icon: ClipboardCheck, label: "训练中心" },
  profile: { icon: BarChart3, label: "课程画像" },
};

export function Layout() {
  const location = useLocation();
  const { pathname } = location;
  const isElectron = isElectronRuntime();
  const isFullBleed = isFullBleedCoursePath(pathname);
  const isExamFocusPage = /^\/courses?\/[^/]+\/exams\/\d+$/.test(pathname);
  const isAssistantPage = pathname === "/assistant";
  const isHomePage = pathname === "/";
  const courseId = useMemo(() => getCourseIdFromPathname(pathname), [pathname]);
  const routeSegment = getCourseRouteSegmentFromPathname(pathname);
  const isKnowledgeDocsPage = !!courseId && routeSegment === "knowledge-docs";
  const hasCoursePageTopNavigation =
    !!courseId &&
    (routeSegment === "build" ||
      routeSegment === "knowledge-docs" ||
      routeSegment === "exams" ||
      routeSegment === "profile");
  const isCourseDashboardOrBuild = !!courseId && (routeSegment === "nav" || routeSegment === "build" || routeSegment === null);
  const buildRuntimeQuery = useQuery({
    queryKey: courseId
      ? [...buildKnowledgeBuildRuntimeQueryKey(courseId), "layout-interaction-visibility"]
      : ["knowledge-build-runtime-layout-empty"],
    queryFn: () => fetchKnowledgeBuildRuntime(courseId as string),
    enabled: Boolean(courseId && isKnowledgeDocsPage),
    refetchInterval: (query) => {
      const failureBackoff = buildRuntimeFailureBackoffMs(query.state.fetchFailureCount);
      if (failureBackoff !== null) return failureBackoff;
      const statuses = [
        query.state.data?.aggregate?.status,
        query.state.data?.docgen?.status,
      ].map((status) => (status ?? "").trim());
      return statuses.some((status) => ACTIVE_DOC_BUILD_STATUSES.has(status)) ? 2500 : false;
    },
  });
  const isKnowledgeDocBuildActive = useMemo(() => {
    if (!isKnowledgeDocsPage) return false;
    const statuses = [
      buildRuntimeQuery.data?.aggregate?.status,
      buildRuntimeQuery.data?.docgen?.status,
    ].map((status) => (status ?? "").trim());
    return statuses.some((status) => ACTIVE_DOC_BUILD_STATUSES.has(status));
  }, [buildRuntimeQuery.data?.aggregate?.status, buildRuntimeQuery.data?.docgen?.status, isKnowledgeDocsPage]);
  const activeInteractionScope = useMemo<AiConversationScope | null>(() => {
    if (isAssistantPage) {
      return { type: "global" };
    }
    if (courseId) {
      return { type: "course", courseId };
    }
    return { type: "global" };
  }, [isAssistantPage, courseId]);

  useEffect(() => {
    rememberCourseRoute(`${location.pathname}${location.search}${location.hash}`);
  }, [location.hash, location.pathname, location.search]);

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [hasLoadedSettingsDialog, setHasLoadedSettingsDialog] = useState(false);
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const courseTopNavMeta = routeSegment ? COURSE_TOP_NAV_META[routeSegment] : null;
  const shouldShowCourseTopNav = Boolean(
    ENABLE_PERSISTENT_COURSE_NAV &&
    courseId &&
    courseTopNavMeta &&
    hasCoursePageTopNavigation &&
    !isExamFocusPage,
  );
  const shouldShowTopBar = !isExamFocusPage && !isAssistantPage && !hasCoursePageTopNavigation;
  const routeOutlet = <Outlet key={pathname} />;
  const contentContainerClassName = shouldShowTopBar
    ? cn(
        "container mx-auto min-h-full max-w-7xl px-4 pb-4 md:px-6 md:pb-6 lg:px-8 lg:pb-8",
        hasCoursePageTopNavigation ? "pt-0" : "pt-20",
      )
    : "container mx-auto min-h-full max-w-7xl px-4 pb-4 pt-20 md:px-6 md:pb-6 lg:px-8 lg:pb-8 lg:pt-6";
  const openSettings = useCallback(() => {
    setHasLoadedSettingsDialog(true);
    setIsSettingsOpen(true);
  }, []);

  return (
    <>
      <AiInteractionProvider activeScope={activeInteractionScope}>
        <div
          className={cn(
            "app-shell relative flex min-h-0 overflow-hidden bg-[#fafafa] selection:bg-zinc-200 dark:bg-[#0b0f19] dark:selection:bg-slate-700",
            isElectron ? "w-full flex-1" : "h-dvh w-screen max-w-full",
          )}
        >
          {!isExamFocusPage && (
            <Sidebar
              onOpenSettings={openSettings}
              onMobileOpenChange={setIsMobileSidebarOpen}
            />
          )}
          <div
            className={cn(
              "relative z-10 flex min-w-0 flex-1 flex-col transition-transform duration-200 ease-out lg:translate-x-0",
              isMobileSidebarOpen && !isExamFocusPage ? "translate-x-[80vw]" : "translate-x-0",
            )}
          >
            {shouldShowTopBar && (
              <header className="pointer-events-none absolute left-0 right-0 top-0 z-40 flex h-16 items-center justify-end px-4 md:px-6">
                <div className="pointer-events-auto">
                  <TopBar />
                </div>
              </header>
            )}
            {shouldShowCourseTopNav && courseId && courseTopNavMeta ? (
              <CoursePagePillTitle
                icon={courseTopNavMeta.icon}
                label={courseTopNavMeta.label}
                href={buildCoursePath(courseId, "nav")}
                placement="layout"
              />
            ) : null}

            <main className="relative flex min-h-0 w-full flex-1 flex-col overflow-x-hidden overflow-y-auto bg-transparent">
              {isFullBleed || pathname === "/" || isAssistantPage ? (
                <div
                  className={cn(
                    "flex min-h-0 w-full flex-1 flex-col",
                    !isElectron && "min-h-[calc(100dvh-4rem)]",
                  )}
                >
                  {routeOutlet}
                </div>
              ) : (
                <div className={contentContainerClassName}>
                  {routeOutlet}
                </div>
              )}
            </main>
          </div>
          <AiInteractionWindow
            suppressFloatingTrigger={
              (isMobileSidebarOpen && !isExamFocusPage) ||
              isHomePage ||
              isCourseDashboardOrBuild ||
              isKnowledgeDocBuildActive
            }
          />
        </div>
      </AiInteractionProvider>

      {hasLoadedSettingsDialog ? (
        <Suspense fallback={null}>
          <SettingsDialog isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />
        </Suspense>
      ) : null}
    </>
  );
}
