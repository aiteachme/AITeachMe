import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { SubjectAiAssistantProvider } from "../ai/SubjectAiAssistant";

/** Pages that manage their own header + layout (no shared TopBar / padding) */
const FULL_BLEED_SUFFIXES = ["/doc"];

export function Layout() {
  const { pathname } = useLocation();
  const hideTopBar = pathname.startsWith("/subject/");
  const isFullBleed = FULL_BLEED_SUFFIXES.some((s) => pathname.endsWith(s));
  const subjectId = pathname.match(/^\/subject\/([^/]+)/)?.[1] ?? null;

  return (
    <SubjectAiAssistantProvider subjectId={subjectId}>
      <div className="flex h-screen bg-slate-50">
        <Sidebar />
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Top Bar — hidden when the page provides its own */}
          {!hideTopBar && (
            <header className="flex-shrink-0 h-16 bg-white border-b border-slate-200 px-6 flex items-center justify-end">
              <TopBar />
            </header>
          )}

          {/* Main Content */}
          <main className="flex-1 overflow-y-auto">
            {isFullBleed ? (
              <Outlet />
            ) : (
              <div className="container mx-auto p-6 lg:p-8 max-w-7xl">
                <Outlet />
              </div>
            )}
          </main>
        </div>
      </div>
    </SubjectAiAssistantProvider>
  );
}
