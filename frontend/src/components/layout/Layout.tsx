import { useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { SubjectAiAssistantProvider } from "../ai/SubjectAiAssistant";
import { isFullBleedSubjectPath } from "../../lib/subjectNavigation";
import { SettingsPanel as SettingsModal } from "../settings/SettingsPanel";

export function Layout() {
  const { pathname } = useLocation();
  const isFullBleed = isFullBleedSubjectPath(pathname);
  const isHome = pathname === "/";
  const isExamFocusPage = /^\/subject\/[^/]+\/exams\/[^/]+$/.test(pathname);
  const subjectId = pathname.match(/^\/subject\/([^/]+)/)?.[1] ?? null;

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  return (
    <>
      <SubjectAiAssistantProvider subjectId={subjectId}>
        <div className="relative flex h-screen overflow-hidden bg-[#fafafa] selection:bg-zinc-200">
          {!isSettingsOpen ? (
            <div className="pointer-events-none absolute inset-0 z-0 overflow-hidden mix-blend-multiply">
              <div className="absolute -left-[4%] -top-[8%] h-[440px] w-[440px] rounded-full bg-indigo-100/30 blur-[72px] opacity-75" />
              <div className="absolute bottom-[-8%] right-[-4%] h-[420px] w-[420px] rounded-full bg-zinc-200/40 blur-[72px] opacity-55" />
              <div className="absolute left-[32%] top-[22%] h-[520px] w-[520px] rounded-full bg-sky-100/24 blur-[88px] opacity-60" />
            </div>
          ) : null}

          {!isExamFocusPage && <Sidebar onOpenSettings={() => setIsSettingsOpen(true)} />}
          <div className="relative z-10 flex min-w-0 flex-1 flex-col">
            {!isExamFocusPage && (
              <header className="pointer-events-none absolute left-0 right-0 top-0 z-40 flex h-16 items-center justify-end px-4 md:px-6">
                <div className="pointer-events-auto">
                  <TopBar />
                </div>
              </header>
            )}

            <main className="relative flex w-full flex-1 flex-col overflow-x-hidden overflow-y-auto bg-transparent">
              {isFullBleed || isHome ? (
                <div className="flex min-h-[calc(100vh-4rem)] w-full flex-1 flex-col">
                  <Outlet />
                </div>
              ) : (
                <div className="container mx-auto min-h-full max-w-7xl px-4 pb-4 pt-20 md:px-6 md:pb-6 lg:px-8 lg:pb-8">
                  <Outlet />
                </div>
              )}
            </main>
          </div>
        </div>
      </SubjectAiAssistantProvider>

      <SettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />
    </>
  );
}
