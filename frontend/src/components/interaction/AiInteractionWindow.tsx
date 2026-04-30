import { lazy, Suspense, useCallback, useEffect, useRef, useState, type ComponentType } from "react";
import { Bot } from "lucide-react";
import { useLocation } from "react-router-dom";

import { useResizablePanel } from "../../hooks/useResizablePanel";
import { cn } from "../../lib/utils";
import { useAiInteraction } from "./AiInteractionProvider";
import type { AiConversationScope, AiInteractionOpenRequest } from "./types";

interface AiInteractionWindowProps {
  variant: "sidebar" | "fullscreen";
  scope?: AiConversationScope | null;
  className?: string;
}

interface AiConversationPanelLoaderProps {
  scope: AiConversationScope | null;
  request?: AiInteractionOpenRequest | null;
  active: boolean;
  presentation: "sidebar" | "fullscreen";
  onClose?: () => void;
  className?: string;
}

const SIDEBAR_TRANSITION_MS = 220;

const LazyAiConversationPanel = lazy(() =>
  import("./AiConversationPanel").then((module) => ({
    default: module.AiConversationPanel as ComponentType<AiConversationPanelLoaderProps>,
  })),
);

function AiConversationPanelFallback() {
  return (
    <div className="flex h-full w-full items-center justify-center text-sm text-zinc-500 dark:text-slate-400">
      加载中...
    </div>
  );
}

export function AiInteractionWindow({ variant, scope, className }: AiInteractionWindowProps) {
  const { pathname } = useLocation();
  const panelShellRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const outsidePointerRef = useRef<{ x: number; y: number; selectedText: string } | null>(null);
  const [isSidebarMounted, setIsSidebarMounted] = useState(false);
  const [isSidebarVisible, setIsSidebarVisible] = useState(false);
  const {
    activeScope,
    sidebarScope,
    fullscreenScope,
    sidebarRequest,
    fullscreenRequest,
    isSidebarOpen,
    isSidebarStreaming,
    openAiInteraction,
    closeAiInteraction,
  } = useAiInteraction();

  const initialViewportWidth = typeof window !== "undefined" ? window.innerWidth : 1200;
  const isNarrowInitialViewport = initialViewportWidth < 640;
  const defaultSidebarWidth = isNarrowInitialViewport
    ? initialViewportWidth
    : Math.min(680, Math.max(460, initialViewportWidth * 0.34));
  const maxSidebarWidth = isNarrowInitialViewport
    ? initialViewportWidth
    : Math.min(820, initialViewportWidth * 0.5);
  const isBuildPage = /\/courses?\/[^/]+\/build\b/.test(pathname);
  const isAssistantPage = pathname === "/assistant";
  const canShowSidebar = variant === "sidebar" && Boolean(activeScope) && !isBuildPage && !isAssistantPage;
  const panelScope = sidebarScope ?? activeScope;
  const shouldShowSidebarPanel = isSidebarOpen && Boolean(panelScope) && canShowSidebar;
  const shouldReserveSidebarWidth = shouldShowSidebarPanel || isSidebarMounted;
  const shouldRenderSidebarPanel = canShowSidebar && (shouldReserveSidebarWidth || isSidebarStreaming);
  const isSidebarVisuallyOpen = shouldShowSidebarPanel && isSidebarVisible;
  const { width: panelWidth, isDragging, handleMouseDown } = useResizablePanel({
    defaultWidth: defaultSidebarWidth,
    minWidth: isNarrowInitialViewport ? initialViewportWidth : 400,
    maxWidth: maxSidebarWidth,
    liveResizeRef: panelShellRef,
    liveResizeEnabled: shouldRenderSidebarPanel,
  });

  useEffect(() => {
    if (!canShowSidebar) {
      setIsSidebarMounted(false);
      setIsSidebarVisible(false);
      return;
    }

    if (shouldShowSidebarPanel) {
      setIsSidebarMounted(true);
      const frame = window.requestAnimationFrame(() => setIsSidebarVisible(true));
      return () => window.cancelAnimationFrame(frame);
    }

    setIsSidebarVisible(false);
    const timeoutId = window.setTimeout(() => {
      setIsSidebarMounted(false);
    }, SIDEBAR_TRANSITION_MS);
    return () => window.clearTimeout(timeoutId);
  }, [canShowSidebar, shouldShowSidebarPanel]);

  const isInsidePanel = useCallback((target: EventTarget | null) => {
    const node = target instanceof Node ? target : null;
    return Boolean(node && panelRef.current?.contains(node));
  }, []);

  const isInsideAppSidebar = useCallback((target: EventTarget | null) => {
    const element = target instanceof Element ? target : null;
    return Boolean(element?.closest("[data-app-sidebar='true']"));
  }, []);

  useEffect(() => {
    if (!shouldShowSidebarPanel) {
      outsidePointerRef.current = null;
      return;
    }

    const readSelectionText = () => {
      const selection = window.getSelection();
      return selection && !selection.isCollapsed ? selection.toString().trim() : "";
    };

    const handlePointerDown = (event: PointerEvent) => {
      if (
        (event.pointerType === "mouse" && event.button !== 0) ||
        isInsidePanel(event.target) ||
        isInsideAppSidebar(event.target)
      ) {
        outsidePointerRef.current = null;
        return;
      }
      outsidePointerRef.current = {
        x: event.clientX,
        y: event.clientY,
        selectedText: readSelectionText(),
      };
    };

    const handleClick = (event: MouseEvent) => {
      if (isInsidePanel(event.target) || isInsideAppSidebar(event.target)) {
        outsidePointerRef.current = null;
        return;
      }

      const pointer = outsidePointerRef.current;
      outsidePointerRef.current = null;
      if (!pointer) {
        return;
      }

      const moved = Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y);
      if (moved > 6 || pointer.selectedText || readSelectionText()) {
        return;
      }

      closeAiInteraction();
    };

    const clearPointer = () => {
      outsidePointerRef.current = null;
    };

    document.addEventListener("pointerdown", handlePointerDown, true);
    document.addEventListener("click", handleClick, true);
    document.addEventListener("pointercancel", clearPointer, true);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown, true);
      document.removeEventListener("click", handleClick, true);
      document.removeEventListener("pointercancel", clearPointer, true);
    };
  }, [closeAiInteraction, isInsideAppSidebar, isInsidePanel, shouldShowSidebarPanel]);

  if (variant === "fullscreen") {
    const fullscreenConversationScope = scope ?? fullscreenScope ?? activeScope ?? { type: "global" };

    return (
      <section
        className={cn(
          "flex min-h-[calc(100dvh-8rem)] flex-col overflow-hidden bg-white dark:bg-slate-950",
          className,
        )}
      >
        <Suspense fallback={<AiConversationPanelFallback />}>
          <LazyAiConversationPanel
            scope={fullscreenConversationScope}
            request={fullscreenRequest}
            active
            presentation="fullscreen"
          />
        </Suspense>
      </section>
    );
  }

  return (
    <>
      {canShowSidebar ? (
        <button
          type="button"
          onClick={() => openAiInteraction({ mode: "sidebar", sessionId: null, newSession: true })}
          className={cn(
            "fixed bottom-[calc(1rem+env(safe-area-inset-bottom))] right-4 z-[86] inline-flex h-12 items-center gap-2 rounded-2xl border border-zinc-200/80 bg-white/95 px-3 text-[14px] font-medium text-zinc-700 shadow-[0_2px_8px_rgba(0,0,0,0.04),0_8px_24px_rgba(0,0,0,0.06)] backdrop-blur-xl transition duration-300 hover:border-zinc-300 hover:bg-white hover:text-zinc-900 active:scale-[0.98] dark:border-slate-800/80 dark:bg-slate-950/92 dark:text-slate-300 dark:shadow-[0_18px_40px_-22px_rgba(0,0,0,0.7)] dark:hover:border-slate-700 dark:hover:bg-slate-950 dark:hover:text-slate-100 sm:bottom-6 sm:right-6 sm:h-11 sm:px-4",
            shouldShowSidebarPanel ? "pointer-events-none translate-y-4 opacity-0" : "translate-y-0 opacity-100",
          )}
          aria-label="打开 AI 交互窗口"
        >
          <Bot className="h-4 w-4 text-zinc-500 dark:text-slate-400" />
          <span className="hidden sm:inline">AI 交互窗口</span>
        </button>
      ) : null}

      <div
        ref={panelShellRef}
        data-ai-interaction-window="true"
        className={cn(
          "relative z-[85] h-full min-h-0 shrink-0 overflow-hidden [contain:layout_paint_style]",
          shouldShowSidebarPanel ? "pointer-events-auto" : "pointer-events-none",
        )}
        style={{ width: shouldReserveSidebarWidth ? panelWidth : 0 }}
        aria-hidden={!shouldShowSidebarPanel}
      >
        {shouldRenderSidebarPanel ? (
          <div
            ref={panelRef}
            className={cn(
              "absolute bottom-0 right-0 top-0 flex transform-gpu border-l border-zinc-200/80 bg-white shadow-[0_0_40px_rgba(0,0,0,0.1)] will-change-transform dark:border-slate-800/80 dark:bg-slate-950 dark:shadow-[0_0_50px_rgba(0,0,0,0.55)]",
              isSidebarVisuallyOpen ? "translate-x-0 opacity-100" : "translate-x-full opacity-0",
              !isDragging && "transition-[transform,opacity] ease-[cubic-bezier(0.2,0.8,0.2,1)]",
              className,
            )}
            style={{ width: "100%", transitionDuration: `${SIDEBAR_TRANSITION_MS}ms` }}
          >
            <div
              className={cn(
                "absolute bottom-0 left-0 top-0 z-50 -ml-[0.5px] hidden w-1.5 cursor-col-resize transition-colors hover:bg-indigo-500/50 sm:block",
                isDragging && "bg-indigo-500/50",
              )}
              onMouseDown={handleMouseDown}
            />
            <Suspense fallback={<AiConversationPanelFallback />}>
              <LazyAiConversationPanel
                scope={panelScope}
                request={sidebarRequest}
                active={shouldShowSidebarPanel}
                presentation="sidebar"
                onClose={closeAiInteraction}
              />
            </Suspense>
          </div>
        ) : null}
      </div>
    </>
  );
}
