import { lazy, Suspense, useCallback, useMemo, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { AiInteractionProvider, AiInteractionWindow, type AiConversationScope } from "../interaction";
import { isFullBleedCoursePath } from "../../lib/courseNavigation";
import { cn } from "../../lib/utils";
import { useSystemSettingsOverview } from "../../hooks/useSystemSettingsOverview";
import { isElectronRuntime } from "../../lib/electronRuntime";

const SettingsDialog = lazy(() =>
  import("../settings/SettingsDialog").then((module) => ({ default: module.SettingsDialog })),
);

export function Layout() {
  const { pathname } = useLocation();
  const isElectron = isElectronRuntime();
  const isFullBleed = isFullBleedCoursePath(pathname);
  const isExamFocusPage = /^\/course\/[^/]+\/exams\/\d+$/.test(pathname);
  const rawCourseId = pathname.match(/^\/course\/([^/]+)/)?.[1] ?? null;
  const courseId = useMemo(() => {
    if (!rawCourseId) {
      return null;
    }
    try {
      return decodeURIComponent(rawCourseId);
    } catch {
      return rawCourseId;
    }
  }, [rawCourseId]);
  const activeInteractionScope = useMemo<AiConversationScope | null>(() => {
    if (pathname === "/assistant") {
      return { type: "global" };
    }
    if (courseId) {
      return { type: "course", courseId };
    }
    return { type: "global" };
  }, [pathname, courseId]);

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [hasLoadedSettingsDialog, setHasLoadedSettingsDialog] = useState(false);
  const settingsOverview = useSystemSettingsOverview();
  const isCloudRuntime = settingsOverview?.mode === "cloud";
  const shouldShowTopBar = !isExamFocusPage && isCloudRuntime;
  const routeOutlet = <Outlet key={pathname} />;
  const contentContainerClassName = shouldShowTopBar
    ? "container mx-auto min-h-full max-w-7xl px-4 pb-4 pt-20 md:px-6 md:pb-6 lg:px-8 lg:pb-8"
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
          {!isExamFocusPage && <Sidebar onOpenSettings={openSettings} />}
          <div className="relative z-10 flex min-w-0 flex-1 flex-col">
            {shouldShowTopBar && (
              <header className="pointer-events-none absolute left-0 right-0 top-0 z-40 flex h-16 items-center justify-end px-4 md:px-6">
                <div className="pointer-events-auto">
                  <TopBar />
                </div>
              </header>
            )}

            <main className="relative flex min-h-0 w-full flex-1 flex-col overflow-x-hidden overflow-y-auto bg-transparent">
              {isFullBleed || pathname === "/" || pathname === "/spaces" ? (
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
          <AiInteractionWindow variant="sidebar" />
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
