import { Bot } from "lucide-react";
import { useLocation } from "react-router-dom";

import { useResizablePanel } from "../../hooks/useResizablePanel";
import { cn } from "../../lib/utils";
import { AiConversationPanel } from "./AiConversationPanel";
import { useAiInteraction } from "./AiInteractionProvider";
import type { AiConversationScope } from "./types";

interface AiInteractionWindowProps {
  variant: "sidebar" | "fullscreen";
  scope?: AiConversationScope | null;
  className?: string;
}

export function AiInteractionWindow({ variant, scope, className }: AiInteractionWindowProps) {
  const { pathname } = useLocation();
  const {
    activeScope,
    sidebarScope,
    fullscreenScope,
    sidebarRequest,
    fullscreenRequest,
    isSidebarOpen,
    openAiInteraction,
    closeAiInteraction,
  } = useAiInteraction();

  const initialViewportWidth = typeof window !== "undefined" ? window.innerWidth : 1200;
  const isNarrowInitialViewport = initialViewportWidth < 640;
  const { width: panelWidth, isDragging, handleMouseDown } = useResizablePanel({
    defaultWidth: isNarrowInitialViewport ? initialViewportWidth : initialViewportWidth * 0.6,
    minWidth: isNarrowInitialViewport ? initialViewportWidth : 400,
    maxWidth: isNarrowInitialViewport ? initialViewportWidth : initialViewportWidth * 0.8,
  });

  if (variant === "fullscreen") {
    const fullscreenConversationScope = scope ?? fullscreenScope ?? activeScope ?? { type: "global" };

    return (
      <section
        className={cn(
          "flex min-h-[calc(100dvh-8rem)] flex-col overflow-hidden bg-white dark:bg-slate-950",
          className,
        )}
      >
        <AiConversationPanel
          scope={fullscreenConversationScope}
          request={fullscreenRequest}
          active
          presentation="fullscreen"
        />
      </section>
    );
  }

  const isBuildPage = /\/subject\/[^/]+\/build\b/.test(pathname);
  const isAssistantPage = pathname === "/assistant";
  const canShowSidebar = Boolean(activeScope) && !isBuildPage && !isAssistantPage;
  const panelScope = sidebarScope ?? activeScope;
  const shouldShowSidebarPanel = isSidebarOpen && Boolean(panelScope) && canShowSidebar;

  return (
    <>
      {canShowSidebar ? (
        <button
          type="button"
          onClick={() => openAiInteraction({ mode: "sidebar" })}
          className={cn(
            "fixed bottom-4 right-4 z-[86] inline-flex h-12 items-center gap-2 rounded-2xl border border-zinc-200/80 bg-white/95 px-3 text-[14px] font-medium text-zinc-700 shadow-[0_2px_8px_rgba(0,0,0,0.04),0_8px_24px_rgba(0,0,0,0.06)] backdrop-blur-xl transition duration-300 hover:border-zinc-300 hover:bg-white hover:text-zinc-900 active:scale-[0.98] dark:border-slate-800/80 dark:bg-slate-950/92 dark:text-slate-300 dark:shadow-[0_18px_40px_-22px_rgba(0,0,0,0.7)] dark:hover:border-slate-700 dark:hover:bg-slate-950 dark:hover:text-slate-100 sm:bottom-6 sm:right-6 sm:h-11 sm:px-4",
            shouldShowSidebarPanel ? "pointer-events-none translate-y-4 opacity-0" : "translate-y-0 opacity-100",
          )}
          aria-label="打开 AI 交互窗口"
        >
          <Bot className="h-4 w-4 text-zinc-500 dark:text-slate-400" />
          <span className="hidden sm:inline">AI 交互窗口</span>
        </button>
      ) : null}

      <button
        type="button"
        className={cn(
          "fixed inset-0 z-[84] cursor-default bg-transparent transition-opacity",
          shouldShowSidebarPanel ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0",
        )}
        onClick={closeAiInteraction}
        aria-label="收起 AI 交互窗口"
        tabIndex={shouldShowSidebarPanel ? 0 : -1}
      />

      <div
        className={cn(
          "fixed bottom-0 right-0 top-0 z-[85] flex border-l border-zinc-200/80 bg-white shadow-[0_0_40px_rgba(0,0,0,0.1)] dark:border-slate-800/80 dark:bg-slate-950 dark:shadow-[0_0_50px_rgba(0,0,0,0.55)]",
          shouldShowSidebarPanel ? "translate-x-0" : "translate-x-full",
          !isDragging && "transition-transform duration-300 ease-[cubic-bezier(0.2,0.8,0.2,1)]",
          className,
        )}
        style={{ width: panelWidth }}
      >
        <div
          className={cn(
            "absolute bottom-0 left-0 top-0 z-50 -ml-[0.5px] hidden w-1.5 cursor-col-resize transition-colors hover:bg-blue-500/50 sm:block",
            isDragging && "bg-blue-500/50",
          )}
          onMouseDown={handleMouseDown}
        />
        <AiConversationPanel
          scope={panelScope}
          request={sidebarRequest}
          active={shouldShowSidebarPanel}
          presentation="sidebar"
          onClose={closeAiInteraction}
        />
      </div>
    </>
  );
}
