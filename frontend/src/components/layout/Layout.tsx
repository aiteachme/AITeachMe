import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

/** Pages that manage their own header + layout (no shared TopBar / padding) */
const FULL_BLEED_SUFFIXES = ["/doc"];

export function Layout() {
  const { pathname } = useLocation();
  const hideTopBar = pathname.startsWith("/subject/");
  const isFullBleed = FULL_BLEED_SUFFIXES.some((s) => pathname.endsWith(s));
  const isHome = pathname === "/";

  return (
    <div className={`flex h-screen ${isHome ? "bg-transparent" : "bg-slate-50"}`}>
      {!isHome && <Sidebar />}
      <div className="flex-1 flex flex-col overflow-hidden relative">
        {/* Top Bar — hidden when the page provides its own or if it's home */}
        {!hideTopBar && !isHome && (
          <header className="flex-shrink-0 h-16 bg-white border-b border-slate-200 px-6 flex items-center justify-end">
            <TopBar />
          </header>
        )}

        {/* Main Content */}
        <main className={`flex-1 ${isHome ? "overflow-x-hidden" : "overflow-y-auto"}`}>
          {isFullBleed || isHome ? (
            <Outlet />
          ) : (
            <div className="container mx-auto p-6 lg:p-8 max-w-7xl">
              <Outlet />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
