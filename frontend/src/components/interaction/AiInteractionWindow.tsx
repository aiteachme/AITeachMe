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

interface AiConversationViewLoaderProps {
  scope: AiConversationScope | null;
  request?: AiInteractionOpenRequest | null;
  active: boolean;
  presentation: "sidebar" | "fullscreen";
  onClose?: () => void;
  className?: string;
}

const SIDEBAR_TRANSITION_MS = 220;
const KNOWLEDGE_GRAPH_DRAWER_EVENT = "aiteachme:knowledge-graph-drawer";

const LazyAiConversationView = lazy(() =>
  import("./conversation/AiConversationView").then((module) => ({
    default: module.AiConversationView as ComponentType<AiConversationViewLoaderProps>,
  })),
);

function AiConversationViewFallback() {
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
  const [isKnowledgeGraphDrawerOpen, setIsKnowledgeGraphDrawerOpen] = useState(() => (
    typeof document !== "undefined" && document.body.dataset.knowledgeGraphDrawerOpen === "true"
  ));
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
  const shouldShowFloatingTrigger = canShowSidebar && !shouldReserveSidebarWidth && !isSidebarStreaming && !isKnowledgeGraphDrawerOpen;
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

  useEffect(() => {
    const syncFromBody = () => {
      setIsKnowledgeGraphDrawerOpen(document.body.dataset.knowledgeGraphDrawerOpen === "true");
    };
    const handleGraphDrawerEvent = (event: Event) => {
      const detail = (event as CustomEvent<{ open?: boolean }>).detail;
      if (typeof detail?.open === "boolean") {
        setIsKnowledgeGraphDrawerOpen(detail.open);
        return;
      }
      syncFromBody();
    };

    syncFromBody();
    window.addEventListener(KNOWLEDGE_GRAPH_DRAWER_EVENT, handleGraphDrawerEvent);
    return () => window.removeEventListener(KNOWLEDGE_GRAPH_DRAWER_EVENT, handleGraphDrawerEvent);
  }, []);

  const handleOpenSidebar = useCallback(() => {
    openAiInteraction({ mode: "sidebar" });
  }, [openAiInteraction]);

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
          "flex h-full min-h-0 flex-1 flex-col overflow-hidden bg-transparent",
          className,
        )}
      >
        <Suspense fallback={<AiConversationViewFallback />}>
          <LazyAiConversationView
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
      {shouldShowFloatingTrigger ? (
        <button
          type="button"
          className="fixed bottom-6 right-6 z-[80] inline-flex h-10 w-10 items-center justify-center gap-2 rounded-xl border border-slate-200/70 bg-white/90 text-[13px] font-medium text-slate-700 shadow-[0_12px_32px_-24px_rgba(15,23,42,0.55)] backdrop-blur-md transition duration-200 hover:-translate-y-0.5 hover:border-slate-300 hover:bg-white hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/30 active:translate-y-0 active:scale-[0.98] sm:w-[9.25rem] sm:justify-start sm:px-3 dark:border-slate-800/80 dark:bg-slate-950/88 dark:text-slate-300 dark:shadow-[0_18px_44px_-28px_rgba(0,0,0,0.9)] dark:hover:border-slate-700 dark:hover:bg-slate-950 dark:hover:text-slate-100"
          onClick={handleOpenSidebar}
          aria-label="打开 AI 交互窗口"
        >
          <Bot className="h-4 w-4 shrink-0" />
          <span className="hidden truncate sm:inline">AI 交互窗口</span>
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
            <Suspense fallback={<AiConversationViewFallback />}>
              <LazyAiConversationView
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
