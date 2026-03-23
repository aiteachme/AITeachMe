import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { AnimatePresence, motion } from "framer-motion";
import { SubjectAiAssistantProvider } from "../ai/SubjectAiAssistant";

/** Pages that manage their own header + layout (no shared TopBar / padding) */
const FULL_BLEED_SUFFIXES = [
  "/doc",
  "/upload",
  "/exam",
  "/analysis",
  "/docs",
  "/files",
  "/exams",
  "/profile",
  "/knowledge-docs",
];

export function Layout() {
  const { pathname } = useLocation();
  const isFullBleed = FULL_BLEED_SUFFIXES.some((s) => pathname.endsWith(s));
  const isHome = pathname === "/";
  const subjectId = pathname.match(/^\/subject\/([^/]+)/)?.[1] ?? null;

  return (
    <SubjectAiAssistantProvider subjectId={subjectId}>
      <div className="flex h-screen bg-slate-50 overflow-hidden">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0 relative">
          {/* Top Bar — ALWAYS SHOW on all tabs to ensure User / Github buttons are visible */}
          <header className="absolute top-0 left-0 right-0 h-16 px-4 md:px-6 flex items-center justify-end z-40 pointer-events-none">
            <div className="pointer-events-auto">
              <TopBar />
            </div>
          </header>

          {/* Main Content */}
          <main className="flex-1 w-full overflow-x-hidden overflow-y-auto relative bg-slate-50 flex flex-col">
            <AnimatePresence mode="wait">
              {isFullBleed || isHome ? (
                <motion.div
                  key={pathname}
                  initial={{ opacity: 0, scale: 0.99 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.3 }}
                  className="flex-1 min-h-[calc(100vh-4rem)] flex flex-col w-full"
                >
                  <Outlet />
                </motion.div>
              ) : (
                <motion.div
                  key={pathname}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.3 }}
                  className="container mx-auto p-4 md:p-6 lg:p-8 max-w-7xl min-h-full"
                >
                  <Outlet />
                </motion.div>
              )}
            </AnimatePresence>
          </main>
        </div>
      </div>
    </SubjectAiAssistantProvider>
  );
}
