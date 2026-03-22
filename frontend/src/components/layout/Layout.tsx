import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { AnimatePresence, motion } from "framer-motion";

/** Pages that manage their own header + layout (no shared TopBar / padding) */
const FULL_BLEED_SUFFIXES = ["/doc"];

export function Layout() {
  const { pathname } = useLocation();
  const hideTopBar = pathname.startsWith("/subject/");
  const isFullBleed = FULL_BLEED_SUFFIXES.some((s) => pathname.endsWith(s));
  const isHome = pathname === "/";

  return (
    <div className="flex h-screen bg-slate-50 overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 relative">
        {/* Top Bar — hidden when the page provides its own */}
        {!hideTopBar && (
          <header className="flex-shrink-0 h-16 bg-white border-b border-slate-200 px-6 flex items-center justify-end z-10">
            <TopBar />
          </header>
        )}

        {/* Main Content */}
        <main className="flex-1 overflow-x-hidden overflow-y-auto relative bg-slate-50/50">
          <AnimatePresence mode="wait">
            {isFullBleed || isHome ? (
              <motion.div
                key={pathname}
                initial={{ opacity: 0, scale: 0.99 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.3 }}
                className="min-h-full"
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
  );
}
