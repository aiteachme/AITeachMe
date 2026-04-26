import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { AiInteractionProvider, AiInteractionWindow, type AiConversationScope } from "../interaction";
import { isFullBleedSubjectPath } from "../../lib/subjectNavigation";
import { SettingsDialog } from "../settings/SettingsDialog";
import { cn } from "../../lib/utils";
import {
  ensureSystemSettingsOverviewLoaded,
  getStoredSystemSettingsOverview,
  subscribeSystemSettingsOverview,
} from "../../lib/systemSettings";
import { isElectronRuntime } from "../../lib/electronRuntime";

export function Layout() {
  const { pathname } = useLocation();
  const isElectron = isElectronRuntime();
  const isFullBleed = isFullBleedSubjectPath(pathname);
  const isExamFocusPage = /^\/subject\/[^/]+\/exams\/\d+$/.test(pathname);
  const subjectId = pathname.match(/^\/subject\/([^/]+)/)?.[1] ?? null;
  const activeInteractionScope = useMemo<AiConversationScope | null>(() => {
    if (pathname === "/assistant") {
      return { type: "global" };
    }
    if (subjectId) {
      return { type: "subject", subjectId };
    }
    return { type: "global" };
  }, [pathname, subjectId]);

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const settingsOverview = useSyncExternalStore(
    subscribeSystemSettingsOverview,
    getStoredSystemSettingsOverview,
    () => null,
  );

  useEffect(() => {
    if (!settingsOverview) {
      void ensureSystemSettingsOverviewLoaded();
    }
  }, [settingsOverview]);

  const isCloudRuntime = settingsOverview?.mode === "cloud";
  const shouldShowTopBar = !isExamFocusPage && isCloudRuntime;
  const routeOutlet = <Outlet key={pathname} />;
  const contentContainerClassName = shouldShowTopBar
    ? "container mx-auto min-h-full max-w-7xl px-4 pb-4 pt-20 md:px-6 md:pb-6 lg:px-8 lg:pb-8"
    : "container mx-auto min-h-full max-w-7xl px-4 pb-4 pt-6 md:px-6 md:pb-6 md:pt-6 lg:px-8 lg:pb-8";

  return (
    <>
      <AiInteractionProvider activeScope={activeInteractionScope}>
        <div
          className={cn(
            "app-shell relative flex min-h-0 overflow-hidden bg-[#fafafa] selection:bg-zinc-200 dark:bg-[#0b0f19] dark:selection:bg-slate-700",
            isElectron ? "w-full flex-1" : "h-dvh w-screen max-w-full",
          )}
        >
          {!isSettingsOpen ? (
            <div className="pointer-events-none absolute inset-0 z-0 overflow-hidden mix-blend-multiply dark:mix-blend-screen">
              <div className="absolute -left-[4%] -top-[8%] h-[440px] w-[440px] rounded-full bg-indigo-100/30 dark:bg-indigo-900/20 blur-[72px] opacity-75 dark:opacity-40" />
              <div className="absolute bottom-[-8%] right-[-4%] h-[420px] w-[420px] rounded-full bg-zinc-200/40 dark:bg-slate-800/30 blur-[72px] opacity-55 dark:opacity-40" />
              <div className="absolute left-[32%] top-[22%] h-[520px] w-[520px] rounded-full bg-sky-100/24 dark:bg-sky-900/10 blur-[88px] opacity-60 dark:opacity-30" />
            </div>
          ) : null}

          {!isExamFocusPage && <Sidebar onOpenSettings={() => setIsSettingsOpen(true)} />}
          <div className="relative z-10 flex min-w-0 flex-1 flex-col">
            {shouldShowTopBar && (
              <header className="pointer-events-none absolute left-0 right-0 top-0 z-40 flex h-16 items-center justify-end px-4 md:px-6">
                <div className="pointer-events-auto">
                  <TopBar />
                </div>
              </header>
            )}

            <main className="relative flex min-h-0 w-full flex-1 flex-col overflow-x-hidden overflow-y-auto bg-transparent">
              {isFullBleed || pathname === "/" ? (
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

      <SettingsDialog isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />
    </>
  );
}
