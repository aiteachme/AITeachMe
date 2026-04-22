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
    <SubjectAiAssistantProvider subjectId={subjectId}>
      <div className="flex h-screen bg-[#fafafa] overflow-hidden relative selection:bg-zinc-200">
        {/* Global Ambient Background */}
        <div className="pointer-events-none absolute inset-0 z-0 overflow-hidden mix-blend-multiply transition-colors duration-1000">
          <div className="absolute -left-[5%] -top-[10%] h-[600px] w-[600px] rounded-full bg-indigo-100/40 blur-[120px] opacity-80" />
          <div className="absolute bottom-[-10%] right-[-5%] h-[600px] w-[600px] rounded-full bg-zinc-200/50 blur-[120px] opacity-60" />
          <div className="absolute left-[30%] top-[20%] h-[800px] w-[800px] rounded-full bg-sky-100/30 blur-[150px] opacity-70" />
        </div>

        {!isExamFocusPage && <Sidebar onOpenSettings={() => setIsSettingsOpen(true)} />}
        <div className="flex-1 flex flex-col min-w-0 relative z-10">
          {/* Top Bar — ALWAYS SHOW on all tabs to ensure User / Github buttons are visible */}
          {!isExamFocusPage && <header className="absolute top-0 left-0 right-0 h-16 px-4 md:px-6 flex items-center justify-end z-40 pointer-events-none">
            <div className="pointer-events-auto">
              <TopBar />
            </div>
          </header>}

          {/* Main Content */}
          <main className="flex-1 w-full overflow-x-hidden overflow-y-auto relative bg-transparent flex flex-col">
            {isFullBleed || isHome ? (
              <div className="flex-1 min-h-[calc(100vh-4rem)] flex flex-col w-full">
                <Outlet />
              </div>
            ) : (
              <div className="container mx-auto px-4 pb-4 pt-20 md:px-6 md:pb-6 lg:px-8 lg:pb-8 max-w-7xl min-h-full">
                <Outlet />
              </div>
            )}
          </main>
        </div>
      </div>

      <SettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />
    </SubjectAiAssistantProvider>
  );
}
