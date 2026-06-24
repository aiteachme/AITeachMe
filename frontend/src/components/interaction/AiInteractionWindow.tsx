import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type TransitionEvent,
} from "react";
import { Bot } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import { useResizablePanel } from "../../hooks/useResizablePanel";
import { buildCoursePath, getCourseIdFromPathname } from "../../lib/courseNavigation";
import { cn } from "../../lib/utils";
import type { ChatPageContext } from "../../api/generated/model";
import { useAiInteraction } from "./AiInteractionProvider";
import type { AiConversationScope, AiInteractionOpenRequest, OpenAiInteractionOptions } from "./types";

interface AiInteractionWindowProps {
  scope?: AiConversationScope | null;
  className?: string;
  suppressFloatingTrigger?: boolean;
  defaultPageContext?: ChatPageContext | null;
}

interface AiConversationViewLoaderProps {
  scope: AiConversationScope | null;
  request?: AiInteractionOpenRequest | null;
  active: boolean;
  presentation: "sidebar" | "fullscreen";
  onClose?: () => void;
  onReturnToSidebar?: (options?: OpenAiInteractionOptions) => void;
  className?: string;
}

type AiWindowDisplayMode = "closed" | "sidebar" | "fullscreen";
type OpenAiWindowDisplayMode = Exclude<AiWindowDisplayMode, "closed">;

const WINDOW_TRANSITION_MS = 220;
const SIDEBAR_BOUNDARY_ACTION_THRESHOLD = 160;
const KNOWLEDGE_GRAPH_DRAWER_EVENT = "aiteachme:knowledge-graph-drawer";
const DEFAULT_GLOBAL_SCOPE: AiConversationScope = { type: "global" };
const BUILD_PAGE_PATTERN = /^\/courses?\/[^/?#]+\/build\b/;

function getViewportWidth() {
  return typeof window !== "undefined" ? window.innerWidth : 1200;
}

function getVisibleAppSidebarWidth() {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return 0;
  }

  const sidebar = document.querySelector<HTMLElement>("[data-app-sidebar='true']");
  if (!sidebar) {
    return 0;
  }

  const rect = sidebar.getBoundingClientRect();
  const style = window.getComputedStyle(sidebar);
  if (
    style.display === "none" ||
    style.visibility === "hidden" ||
    rect.width <= 0 ||
    rect.right <= 0 ||
    rect.left >= window.innerWidth
  ) {
    return 0;
  }

  return Math.min(rect.width, window.innerWidth);
}

function getPathnameOnly(path: string) {
  return path.split(/[?#]/)[0] || "/";
}

function clampSidebarPanelWidth(width: number, minWidth: number, maxWidth: number) {
  if (typeof window === "undefined") {
    return Math.max(minWidth, Math.min(maxWidth, width));
  }

  const maxAllowed = Math.min(maxWidth, window.innerWidth);
  const minAllowed = Math.min(minWidth, maxAllowed);
  return Math.max(minAllowed, Math.min(maxAllowed, width));
}

function getSidebarReturnPath(targetScope: AiConversationScope, lastNonAssistantPath: string) {
  const fallbackPath = targetScope.type === "course"
    ? buildCoursePath(targetScope.courseId, "knowledge-docs")
    : "/";
  const candidatePath = lastNonAssistantPath.trim() || fallbackPath;
  if (!candidatePath.startsWith("/")) {
    return fallbackPath;
  }

  const candidatePathname = getPathnameOnly(candidatePath);
  if (candidatePathname === "/assistant" || BUILD_PAGE_PATTERN.test(candidatePathname)) {
    return fallbackPath;
  }

  if (targetScope.type === "course") {
    return getCourseIdFromPathname(candidatePathname) === targetScope.courseId
      ? candidatePath
      : fallbackPath;
  }

  return candidatePath;
}

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

export function AiInteractionWindow({
  scope,
  className,
  suppressFloatingTrigger = false,
  defaultPageContext = null,
}: AiInteractionWindowProps) {
  const location = useLocation();
  const { pathname } = location;
  const navigate = useNavigate();
  const panelShellRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const outsidePointerRef = useRef<{ x: number; y: number; selectedText: string } | null>(null);
  const [viewportWidth, setViewportWidth] = useState(getViewportWidth);
  const [appSidebarWidth, setAppSidebarWidth] = useState(getVisibleAppSidebarWidth);
  const [isWindowMounted, setIsWindowMounted] = useState(false);
  const [lastOpenDisplayMode, setLastOpenDisplayMode] = useState<OpenAiWindowDisplayMode>("sidebar");
  const [isKnowledgeGraphDrawerOpen, setIsKnowledgeGraphDrawerOpen] = useState(() => (
    typeof document !== "undefined" && document.body.dataset.knowledgeGraphDrawerOpen === "true"
  ));
  const {
    activeScope,
    sidebarScope,
    fullscreenScope,
    sidebarRequest,
    fullscreenRequest,
    displayMode: requestedDisplayMode,
    isSidebarOpen,
    isSidebarStreaming,
    activeConversationSessionId,
    sidebarPanelWidth,
    lastNonAssistantPath,
    openAiInteraction,
    closeAiInteraction,
    setSidebarPanelWidth,
  } = useAiInteraction();

  const updateLayoutMeasurements = useCallback(() => {
    setViewportWidth(getViewportWidth());
    setAppSidebarWidth(getVisibleAppSidebarWidth());
  }, []);

  useEffect(() => {
    updateLayoutMeasurements();
    window.addEventListener("resize", updateLayoutMeasurements);

    const appSidebar = document.querySelector<HTMLElement>("[data-app-sidebar='true']");
    const resizeObserver = typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(updateLayoutMeasurements)
      : null;
    if (appSidebar) {
      resizeObserver?.observe(appSidebar);
      appSidebar.addEventListener("transitionend", updateLayoutMeasurements);
    }
    const appShell = panelShellRef.current?.parentElement;
    if (appShell) {
      resizeObserver?.observe(appShell);
    }

    return () => {
      window.removeEventListener("resize", updateLayoutMeasurements);
      resizeObserver?.disconnect();
      appSidebar?.removeEventListener("transitionend", updateLayoutMeasurements);
    };
  }, [updateLayoutMeasurements]);

  const isNarrowViewport = viewportWidth < 640;
  const defaultSidebarWidth = isNarrowViewport
    ? viewportWidth
    : Math.min(680, Math.max(460, viewportWidth * 0.34));
  const minSidebarWidth = isNarrowViewport ? viewportWidth : 400;
  const maxSidebarWidth = isNarrowViewport
    ? viewportWidth
    : Math.min(820, viewportWidth * 0.5);
  const resolvedSidebarPanelWidth = clampSidebarPanelWidth(
    sidebarPanelWidth ?? defaultSidebarWidth,
    minSidebarWidth,
    maxSidebarWidth,
  );

  const isBuildPage = /\/courses?\/[^/]+\/build\b/.test(pathname);
  const isAssistantPage = pathname === "/assistant";
  const canUseWindow = Boolean(activeScope) && !isBuildPage;
  const canUseSidebar = canUseWindow && (!isAssistantPage || requestedDisplayMode === "sidebar");
  const panelScope = sidebarScope ?? activeScope;
  const fullscreenConversationScope = scope ?? fullscreenScope ?? activeScope ?? DEFAULT_GLOBAL_SCOPE;
  const wantsFullscreen = requestedDisplayMode === "fullscreen" || (!requestedDisplayMode && isAssistantPage);
  const wantsSidebar = requestedDisplayMode === "sidebar" && isSidebarOpen && Boolean(panelScope);
  const displayMode: AiWindowDisplayMode = canUseWindow && wantsFullscreen
    ? "fullscreen"
    : canUseSidebar && wantsSidebar
    ? "sidebar"
    : "closed";
  const isWindowOpen = displayMode !== "closed";
  const renderMode: OpenAiWindowDisplayMode = displayMode === "closed" ? lastOpenDisplayMode : displayMode;
  const renderedScope = renderMode === "fullscreen" ? fullscreenConversationScope : panelScope;
  const renderedRequest = renderMode === "fullscreen" ? fullscreenRequest : sidebarRequest;
  const shouldRenderWindowContent = Boolean(renderedScope) && (isWindowOpen || isWindowMounted || isSidebarStreaming);
  const shouldShowFloatingTrigger = canUseSidebar &&
    displayMode === "closed" &&
    !isWindowMounted &&
    !isSidebarStreaming &&
    !isKnowledgeGraphDrawerOpen &&
    !suppressFloatingTrigger;
  const fullscreenShellWidth = Math.max(0, viewportWidth - appSidebarWidth);
  const shellWidth = displayMode === "fullscreen"
    ? fullscreenShellWidth
    : displayMode === "sidebar"
    ? resolvedSidebarPanelWidth
    : 0;

  useEffect(() => {
    if (displayMode !== "closed") {
      setIsWindowMounted(true);
      setLastOpenDisplayMode(displayMode);
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setIsWindowMounted(false);
    }, WINDOW_TRANSITION_MS);
    return () => window.clearTimeout(timeoutId);
  }, [displayMode]);

  const handleExpandSidebarToFullscreen = useCallback(() => {
    const nextScope = panelScope ?? activeScope;
    if (displayMode !== "sidebar" || !nextScope) {
      return;
    }

    setSidebarPanelWidth(clampSidebarPanelWidth(maxSidebarWidth, minSidebarWidth, maxSidebarWidth));
    openAiInteraction({
      mode: "fullscreen",
      scope: nextScope,
      sessionId: activeConversationSessionId ?? sidebarRequest?.sessionId,
      scene: sidebarRequest?.scene,
      source: sidebarRequest?.source,
      anchorId: sidebarRequest?.anchorId,
      selectedText: sidebarRequest?.selectedText,
      selectionContext: sidebarRequest?.selectionContext,
      pageContext: sidebarRequest?.pageContext,
      clientThreadId: sidebarRequest?.clientThreadId,
      showSelectionContext: sidebarRequest?.showSelectionContext,
    });
  }, [
    activeConversationSessionId,
    activeScope,
    displayMode,
    maxSidebarWidth,
    minSidebarWidth,
    openAiInteraction,
    panelScope,
    setSidebarPanelWidth,
    sidebarRequest?.anchorId,
    sidebarRequest?.clientThreadId,
    sidebarRequest?.selectedText,
    sidebarRequest?.selectionContext,
    sidebarRequest?.pageContext,
    sidebarRequest?.sessionId,
    sidebarRequest?.showSelectionContext,
    sidebarRequest?.scene,
    sidebarRequest?.source,
  ]);

  const handleCollapseSidebarFromDrag = useCallback(() => {
    if (displayMode === "sidebar") {
      closeAiInteraction();
    }
  }, [closeAiInteraction, displayMode]);

  const { width: panelWidth, isDragging, handleMouseDown, resetWidth } = useResizablePanel({
    defaultWidth: resolvedSidebarPanelWidth,
    minWidth: minSidebarWidth,
    maxWidth: maxSidebarWidth,
    onResize: setSidebarPanelWidth,
    boundaryActionThreshold: SIDEBAR_BOUNDARY_ACTION_THRESHOLD,
    onDragBeyondMax: handleExpandSidebarToFullscreen,
    onDragBeyondMin: handleCollapseSidebarFromDrag,
    liveResizeRef: panelShellRef,
    liveResizeEnabled: displayMode === "sidebar",
  });

  const handleReturnFullscreenToSidebar = useCallback((options?: OpenAiInteractionOptions) => {
    const nextSessionId = options?.sessionId !== undefined
      ? options.sessionId
      : activeConversationSessionId ?? fullscreenRequest?.sessionId;

    openAiInteraction({
      ...options,
      mode: "sidebar",
      scope: fullscreenConversationScope,
      sessionId: nextSessionId,
      scene: options?.scene !== undefined ? options.scene : fullscreenRequest?.scene,
      source: options?.source !== undefined ? options.source : fullscreenRequest?.source,
      anchorId: options?.anchorId !== undefined ? options.anchorId : fullscreenRequest?.anchorId,
      selectedText: options?.selectedText !== undefined ? options.selectedText : fullscreenRequest?.selectedText,
      selectionContext: options?.selectionContext !== undefined ? options.selectionContext : fullscreenRequest?.selectionContext,
      pageContext: options?.pageContext !== undefined ? options.pageContext : fullscreenRequest?.pageContext,
      clientThreadId: options?.clientThreadId !== undefined ? options.clientThreadId : fullscreenRequest?.clientThreadId,
      showSelectionContext: options?.showSelectionContext !== undefined
        ? options.showSelectionContext
        : fullscreenRequest?.showSelectionContext,
    });
    navigate(getSidebarReturnPath(fullscreenConversationScope, lastNonAssistantPath), { replace: true });
  }, [
    activeConversationSessionId,
    fullscreenConversationScope,
    fullscreenRequest?.anchorId,
    fullscreenRequest?.clientThreadId,
    fullscreenRequest?.selectedText,
    fullscreenRequest?.selectionContext,
    fullscreenRequest?.pageContext,
    fullscreenRequest?.sessionId,
    fullscreenRequest?.showSelectionContext,
    fullscreenRequest?.scene,
    fullscreenRequest?.source,
    lastNonAssistantPath,
    navigate,
    openAiInteraction,
  ]);

  const handleCloseFullscreen = useCallback(() => {
    closeAiInteraction();
    navigate(getSidebarReturnPath(fullscreenConversationScope, lastNonAssistantPath), { replace: true });
  }, [
    closeAiInteraction,
    fullscreenConversationScope,
    lastNonAssistantPath,
    navigate,
  ]);

  const handleWindowTransitionEnd = useCallback((event: TransitionEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget || event.propertyName !== "width") {
      return;
    }
    if (displayMode === "closed") {
      setIsWindowMounted(false);
    }
  }, [displayMode]);

  useEffect(() => {
    if (isDragging || sidebarPanelWidth === null) {
      return;
    }

    const nextWidth = clampSidebarPanelWidth(sidebarPanelWidth, minSidebarWidth, maxSidebarWidth);
    if (typeof panelWidth === "number" && Math.abs(panelWidth - nextWidth) < 1) {
      return;
    }

    resetWidth(nextWidth);
  }, [
    isDragging,
    maxSidebarWidth,
    minSidebarWidth,
    panelWidth,
    resetWidth,
    sidebarPanelWidth,
  ]);

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
    openAiInteraction({
      mode: "sidebar",
      pageContext: defaultPageContext,
    });
  }, [defaultPageContext, openAiInteraction]);

  const isInsidePanel = useCallback((target: EventTarget | null) => {
    const node = target instanceof Node ? target : null;
    return Boolean(node && panelRef.current?.contains(node));
  }, []);

  const isInsideAppSidebar = useCallback((target: EventTarget | null) => {
    const element = target instanceof Element ? target : null;
    return Boolean(element?.closest("[data-app-sidebar='true']"));
  }, []);

  const isInsideAiInteractionPortal = useCallback((target: EventTarget | null) => {
    const element = target instanceof Element ? target : null;
    return Boolean(element?.closest("[data-ai-interaction-portal='true']"));
  }, []);

  const shouldKeepSelectionContextOpen = sidebarRequest?.showSelectionContext === true;

  useEffect(() => {
    if (displayMode !== "sidebar") {
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
        isInsideAppSidebar(event.target) ||
        isInsideAiInteractionPortal(event.target)
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
      if (
        isInsidePanel(event.target) ||
        isInsideAppSidebar(event.target) ||
        isInsideAiInteractionPortal(event.target)
      ) {
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
      if (shouldKeepSelectionContextOpen) {
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
  }, [
    closeAiInteraction,
    displayMode,
    shouldKeepSelectionContextOpen,
    isInsideAiInteractionPortal,
    isInsideAppSidebar,
    isInsidePanel,
  ]);

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
        data-ai-interaction-display={displayMode}
        className={cn(
          "relative z-[85] h-full min-h-0 shrink-0 overflow-hidden [contain:layout_paint_style]",
          !isDragging && "transition-[width] ease-[cubic-bezier(0.2,0.8,0.2,1)]",
          isWindowOpen ? "pointer-events-auto" : "pointer-events-none",
        )}
        style={{ width: shellWidth, transitionDuration: `${WINDOW_TRANSITION_MS}ms` }}
        aria-hidden={!isWindowOpen}
        onTransitionEnd={handleWindowTransitionEnd}
      >
        {shouldRenderWindowContent ? (
          <div
            ref={panelRef}
            className={cn(
              "absolute bottom-0 right-0 top-0 flex min-w-0 overflow-hidden",
              renderMode === "sidebar"
                ? "border-l border-zinc-200/80 bg-white shadow-[0_0_40px_rgba(0,0,0,0.1)] dark:border-slate-800/80 dark:bg-slate-950 dark:shadow-[0_0_50px_rgba(0,0,0,0.55)]"
                : "bg-[#fafafa] dark:bg-[#0b0f19]",
              className,
            )}
            style={{ width: "100%" }}
          >
            {displayMode === "sidebar" ? (
              <div
                className={cn(
                  "absolute bottom-0 left-0 top-0 z-50 -ml-[0.5px] hidden w-1.5 cursor-col-resize transition-colors hover:bg-indigo-500/50 sm:block",
                  isDragging && "bg-indigo-500/50",
                )}
                onMouseDown={handleMouseDown}
              />
            ) : null}
            <Suspense fallback={<AiConversationViewFallback />}>
              <LazyAiConversationView
                scope={renderedScope}
                request={renderedRequest}
                active={isWindowOpen}
                presentation={renderMode}
                onClose={displayMode === "sidebar" ? closeAiInteraction : handleCloseFullscreen}
                onReturnToSidebar={renderMode === "fullscreen" ? handleReturnFullscreenToSidebar : undefined}
              />
            </Suspense>
          </div>
        ) : null}
      </div>
    </>
  );
}
