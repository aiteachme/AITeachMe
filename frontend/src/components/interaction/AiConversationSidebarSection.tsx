import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronRight,
  Loader2,
  MessageSquareText,
  SquarePen,
  Trash2,
} from "lucide-react";
import { AnimatePresence, motion, type Variants } from "framer-motion";
import { useLocation } from "react-router-dom";

import { apiClient, getApiErrorMessage } from "../../api/client";
import type {
  ApiResponsePaginatedDataChatSessionItem,
  ChatSessionItem,
} from "../../api/generated/model";
import { cn } from "../../lib/utils";
import { useAiInteraction } from "./AiInteractionProvider";
import type { AiConversationScope, AiInteractionDisplayMode } from "./types";
import {
  AI_SOURCE_DOCUMENT_SELECTION,
  AI_SOURCE_EXAM_QUESTION,
  getLibrarySelectionSource,
  getAiConversationScopeKey,
  isLibrarySelectionSource,
  parseLibrarySelectionSource,
} from "./types";

interface AiConversationSidebarSectionProps {
  collapsed: boolean;
  onExpandSidebar: () => void;
  onNavigate?: () => void;
  targetScope?: AiConversationScope;
  title?: string;
  storageKey?: string;
  initialExpanded?: boolean;
  showTopBorder?: boolean;
  showCourseBadge?: boolean;
  maxItems?: number;
  emptyText?: string;
  className?: string;
  hideHeader?: boolean;
  showCollapsedNewButton?: boolean;
}

type ConversationKind = "document" | "question" | "builder" | "library" | "general";

const GLOBAL_COURSE_ID = "global";
const RECENT_SECTION_EXPANDED_STORAGE_KEY = "aiteachme.aiConversations.recentExpanded";
const DEFAULT_GLOBAL_SCOPE: AiConversationScope = { type: "global" };

const conversationListMotion: Variants = {
  visible: {
    transition: {
      staggerChildren: 0.025,
      delayChildren: 0.02,
    },
  },
};

const conversationItemMotion: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { duration: 0.12, ease: [0.2, 0, 0, 1] },
  },
  exit: {
    opacity: 0,
    transition: { duration: 0.08, ease: [0.4, 0, 1, 1] },
  },
};

const CONVERSATION_SELECTED_CLASS_NAME =
  "bg-[#edf3f8] font-medium text-[#243246] dark:bg-slate-800 dark:text-slate-200";
const CONVERSATION_SELECTED_ICON_CLASS_NAME = "text-[#556b86] dark:text-slate-300";
const CONVERSATION_FOCUS_CLASS_NAME =
  "focus-visible:bg-[#edf3f8] focus-visible:text-[#243246] dark:focus-visible:bg-slate-800 dark:focus-visible:text-slate-200";

const CONVERSATION_KIND_STYLES: Record<ConversationKind, {
  label: string;
  badgeClassName: string;
}> = {
  document: {
    label: "文档",
    badgeClassName: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-200",
  },
  question: {
    label: "题目",
    badgeClassName: "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-200",
  },
  builder: {
    label: "构建",
    badgeClassName: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-200",
  },
  library: {
    label: "资料库",
    badgeClassName: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200",
  },
  general: {
    label: "通用",
    badgeClassName: "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-200",
  },
};

function hasSelectionTarget(session: ChatSessionItem): boolean {
  return Boolean(session.anchor_id?.trim() && session.selected_text?.trim());
}

function getConversationKindBySource(source?: string | null, hasSelection = false): ConversationKind {
  const normalizedSource = source?.trim() ?? "";
  if (normalizedSource === AI_SOURCE_EXAM_QUESTION) {
    return "question";
  }
  if (isLibrarySelectionSource(normalizedSource)) {
    return "library";
  }
  if (normalizedSource === AI_SOURCE_DOCUMENT_SELECTION || hasSelection) {
    return "document";
  }
  if (normalizedSource === "build_planner" || normalizedSource.includes("build")) {
    return "builder";
  }
  return "general";
}

function getSessionKind(session: ChatSessionItem): ConversationKind {
  return getConversationKindBySource(session.source, hasSelectionTarget(session));
}

function getSessionCourseId(session: ChatSessionItem): string {
  return session.course_id?.trim() || GLOBAL_COURSE_ID;
}

function getSessionId(session: ChatSessionItem): string | null {
  const sessionId = session.id?.trim();
  if (sessionId) {
    return sessionId;
  }
  const legacySessionId = (session as { session_id?: string | null }).session_id?.trim();
  return legacySessionId || null;
}

function sessionTimeMs(session: ChatSessionItem): number {
  const raw = session.last_message_at || session.updated_at || session.created_at;
  const parsed = raw ? Date.parse(raw) : Number.NaN;
  return Number.isFinite(parsed) ? parsed : 0;
}

function collapseBuildPlannerSessions(items: ChatSessionItem[]): ChatSessionItem[] {
  const latestByCourse = new Map<string, ChatSessionItem>();
  for (const item of items) {
    if (getSessionKind(item) !== "builder") {
      continue;
    }
    const key = getSessionCourseId(item);
    const existing = latestByCourse.get(key);
    if (!existing || sessionTimeMs(item) > sessionTimeMs(existing)) {
      latestByCourse.set(key, item);
    }
  }

  if (latestByCourse.size === 0) {
    return items;
  }

  const emittedBuildCourses = new Set<string>();
  return items.filter((item) => {
    if (getSessionKind(item) !== "builder") {
      return true;
    }
    const key = getSessionCourseId(item);
    if (emittedBuildCourses.has(key)) {
      return false;
    }
    if (latestByCourse.get(key) !== item) {
      return false;
    }
    emittedBuildCourses.add(key);
    return true;
  });
}

function getSessionCourseLabel(session: ChatSessionItem): string {
  if (isLibrarySelectionSource(session.source)) {
    return "资料库";
  }
  const courseId = getSessionCourseId(session);
  return session.course_name?.trim() || (courseId === GLOBAL_COURSE_ID ? "通用" : "未命名课程");
}

function getSessionScope(session: ChatSessionItem): AiConversationScope {
  const libraryFileId = parseLibrarySelectionSource(session.source);
  if (libraryFileId) {
    return { type: "library", fileId: libraryFileId };
  }
  const courseId = getSessionCourseId(session);
  return courseId === GLOBAL_COURSE_ID
    ? { type: "global" }
    : { type: "course", courseId };
}

function getSessionPrimaryBadge(session: ChatSessionItem): { label: string; className: string } {
  const kind = getSessionKind(session);
  if (kind !== "general") {
    const style = CONVERSATION_KIND_STYLES[kind];
    return { label: style.label, className: style.badgeClassName };
  }
  const isGlobal = getSessionCourseId(session) === GLOBAL_COURSE_ID;
  return {
    label: isGlobal ? "全局" : "课程",
    className: isGlobal
      ? "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
      : "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-200",
  };
}

function getSessionDeleteUrl(session: ChatSessionItem): string {
  const courseId = getSessionCourseId(session);
  return courseId === GLOBAL_COURSE_ID
    ? "/api/v1/chats/sessions/delete"
    : `/api/v1/courses/${courseId}/chats/sessions/delete`;
}

function readSectionExpanded(storageKey: string, defaultValue: boolean): boolean {
  if (typeof window === "undefined") {
    return defaultValue;
  }
  try {
    const value = window.localStorage.getItem(storageKey);
    return value === null ? defaultValue : value === "true";
  } catch {
    return defaultValue;
  }
}

function writeSectionExpanded(storageKey: string, value: boolean) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(storageKey, value ? "true" : "false");
  } catch {
    // Storage can be unavailable in restricted webviews; the in-memory state still works.
  }
}

function getSessionListRequest(scope: AiConversationScope, size: number) {
  if (scope.type === "global") {
    return {
      url: "/api/v1/chats/sessions/list",
      data: { page: 1, size, include_all_courses: false },
    };
  }

  if (scope.type === "library") {
    return {
      url: "/api/v1/chats/sessions/list",
      data: { page: 1, size, include_all_courses: false, source: getLibrarySelectionSource(scope.fileId) },
    };
  }

  return {
    url: `/api/v1/courses/${scope.courseId}/chats/sessions/list`,
    data: { page: 1, size },
  };
}

function getNewConversationLabel(scope: AiConversationScope): string {
  if (scope.type === "global") return "新建全局对话";
  if (scope.type === "library") return "新建资料库对话";
  return "新建课程对话";
}

function getConversationOpenMode(scope: AiConversationScope, isAssistantPage: boolean): AiInteractionDisplayMode {
  return isAssistantPage || scope.type === "global" ? "fullscreen" : "sidebar";
}

export function AiConversationSidebarSection({
  collapsed,
  onExpandSidebar,
  onNavigate,
  targetScope,
  title = "最近",
  storageKey = RECENT_SECTION_EXPANDED_STORAGE_KEY,
  initialExpanded = false,
  showTopBorder = true,
  showCourseBadge = true,
  maxItems = 30,
  emptyText = "暂无对话",
  className,
  hideHeader = false,
  showCollapsedNewButton = true,
}: AiConversationSidebarSectionProps) {
  const {
    activeScope,
    sidebarScope,
    fullscreenScope,
    isSidebarOpen,
    activeConversationSessionId,
    sessionListVersion,
    openAiInteraction,
    setActiveConversationSessionId,
    notifyConversationSessionsChanged,
  } = useAiInteraction();
  const location = useLocation();
  const isAssistantPage = location.pathname === "/assistant";
  const currentViewScope = isAssistantPage ? fullscreenScope ?? activeScope : sidebarScope ?? activeScope;
  const listScope = targetScope ?? currentViewScope ?? activeScope ?? DEFAULT_GLOBAL_SCOPE;
  const listScopeKey = getAiConversationScopeKey(listScope);
  const currentViewScopeKey = getAiConversationScopeKey(currentViewScope);
  const newConversationScope = listScope;
  const newConversationLabel = getNewConversationLabel(listScope);
  const isGlobalListScope = listScope.type === "global";
  const isActiveViewForListScope = currentViewScopeKey === listScopeKey;
  const [isExpanded, setIsExpanded] = useState(() => readSectionExpanded(storageKey, initialExpanded));
  const [sessions, setSessions] = useState<ChatSessionItem[]>([]);
  const [sessionsScopeKey, setSessionsScopeKey] = useState(listScopeKey);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isConversationViewActive = isAssistantPage || isSidebarOpen;
  const isListExpanded = hideHeader || isExpanded;
  const shouldLoadSessions = isListExpanded || (isConversationViewActive && isActiveViewForListScope);
  const hasCurrentScopeSessions = sessionsScopeKey === listScopeKey;
  const isListLoading = isLoading || (shouldLoadSessions && !hasCurrentScopeSessions);
  const visibleSessions = useMemo(
    () => collapseBuildPlannerSessions(hasCurrentScopeSessions ? sessions : []).slice(0, maxItems),
    [hasCurrentScopeSessions, maxItems, sessions],
  );
  const updateExpanded = useCallback((next: boolean | ((current: boolean) => boolean)) => {
    setIsExpanded((current) => {
      const value = typeof next === "function" ? next(current) : next;
      writeSectionExpanded(storageKey, value);
      return value;
    });
  }, [storageKey]);

  useEffect(() => {
    if (isSidebarOpen && isActiveViewForListScope) {
      updateExpanded(true);
      if (collapsed) {
        onExpandSidebar();
      }
    }
  }, [collapsed, isActiveViewForListScope, isSidebarOpen, onExpandSidebar, updateExpanded]);

  useEffect(() => {
    if (!shouldLoadSessions) {
      return;
    }

    let cancelled = false;
    async function loadSessions() {
      setIsLoading(true);
      setError(null);
      try {
        const request = getSessionListRequest(listScope, maxItems);
        const res = await apiClient<ApiResponsePaginatedDataChatSessionItem>({
          method: "POST",
          url: request.url,
          data: request.data,
        });
        if (cancelled) {
          return;
        }
        const items = res.data?.items ?? [];
        setSessions(isGlobalListScope
          ? items.filter((item) => getSessionCourseId(item) === GLOBAL_COURSE_ID)
          : items);
        setSessionsScopeKey(listScopeKey);
      } catch (requestError: unknown) {
        if (!cancelled) {
          setSessions([]);
          setSessionsScopeKey(listScopeKey);
          setError(getApiErrorMessage(requestError, "加载对话失败"));
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadSessions();
    return () => {
      cancelled = true;
    };
  }, [isGlobalListScope, listScope, listScopeKey, maxItems, sessionListVersion, shouldLoadSessions]);

  const openNewConversation = useCallback(() => {
    openAiInteraction({
      mode: "fullscreen",
      scope: newConversationScope,
      sessionId: null,
      newSession: true,
    });
    onNavigate?.();
  }, [newConversationScope, onNavigate, openAiInteraction]);

  const openSession = useCallback((session: ChatSessionItem) => {
    const sessionId = getSessionId(session);
    if (!sessionId) {
      setError("这条会话缺少会话 ID，暂时无法打开");
      return;
    }
    updateExpanded(true);
    const sessionScope = getSessionScope(session);
    const mode = getConversationOpenMode(sessionScope, isAssistantPage);
    if (mode === "sidebar") {
      onExpandSidebar();
    }
    openAiInteraction({
      mode,
      scope: sessionScope,
      sessionId,
      source: session.source,
      anchorId: session.anchor_id,
      selectedText: session.selected_text,
      showSelectionContext: false,
    });
    onNavigate?.();
  }, [isAssistantPage, onExpandSidebar, onNavigate, openAiInteraction, updateExpanded]);

  const deleteSession = useCallback(async (target: ChatSessionItem) => {
    const sessionId = getSessionId(target);
    if (!sessionId) {
      setError("这条会话缺少会话 ID，暂时无法删除");
      return;
    }
    const previousSessions = sessions;
    setSessions((current) => current.filter((item) => getSessionId(item) !== sessionId));
    if (activeConversationSessionId === sessionId) {
      setActiveConversationSessionId(null);
    }
    setError(null);
    notifyConversationSessionsChanged();
    try {
      await apiClient({
        method: "POST",
        url: getSessionDeleteUrl(target),
        data: { session_id: sessionId },
      });
      notifyConversationSessionsChanged();
    } catch (requestError: unknown) {
      setSessions(previousSessions);
      setError(getApiErrorMessage(requestError, "删除对话失败"));
    }
  }, [
    activeConversationSessionId,
    notifyConversationSessionsChanged,
    sessions,
    setActiveConversationSessionId,
  ]);

  const renderSessionItem = (session: ChatSessionItem) => {
    const sessionId = getSessionId(session);
    const isSelected =
      isConversationViewActive &&
      isActiveViewForListScope &&
      sessionId !== null &&
      activeConversationSessionId === sessionId;
    const primaryBadge = getSessionPrimaryBadge(session);
    const courseLabel = getSessionCourseLabel(session);

    return (
      <motion.div
        key={sessionId ?? `${getSessionCourseId(session)}-${session.title}-${session.last_message_at}`}
        variants={conversationItemMotion}
        initial="hidden"
        animate="visible"
        exit="exit"
        whileTap={{ scale: 0.985 }}
        className={cn(
          "group relative h-7 overflow-hidden rounded-md transition-colors",
          isSelected
            ? CONVERSATION_SELECTED_CLASS_NAME
            : "text-slate-700 hover:bg-[#eef3f8] hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200",
        )}
      >
        <button
          type="button"
          onClick={() => openSession(session)}
          className={cn(
            "flex h-7 w-full items-center gap-1.5 px-2 pr-7 text-left focus-visible:outline-none",
            CONVERSATION_FOCUS_CLASS_NAME,
          )}
          title={session.title || "未命名对话"}
        >
          <span className="min-w-0 flex-1 truncate text-xs leading-7">
            {session.title || "未命名对话"}
          </span>
          {showCourseBadge ? (
            <span
              className="inline-flex h-4 max-w-[4.75rem] shrink-0 items-center truncate rounded bg-slate-100 px-1 text-[9px] font-semibold leading-none text-slate-500 dark:bg-slate-800 dark:text-slate-300"
              title={courseLabel}
            >
              {courseLabel}
            </span>
          ) : null}
          <span className={cn("inline-flex h-4 w-8 shrink-0 items-center justify-center rounded text-[9px] font-semibold leading-none", primaryBadge.className)}>
            {primaryBadge.label}
          </span>
        </button>
        <button
          type="button"
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            void deleteSession(session);
          }}
          className={cn(
            "absolute right-0.5 top-0.5 flex h-6 w-6 items-center justify-center rounded-md text-slate-400 transition-all hover:bg-red-50 hover:text-red-500 dark:text-slate-500 dark:hover:bg-red-500/10 dark:hover:text-red-300",
            isSelected ? "opacity-100" : "opacity-0 group-hover:opacity-100",
          )}
          aria-label="删除对话"
          title="删除对话"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </motion.div>
    );
  };

  if (collapsed) {
    return (
      <section className="space-y-1">
        <div className="flex h-5 items-center justify-center">
          <div className="h-px w-8 bg-slate-200 dark:bg-slate-800" />
        </div>
        {showCollapsedNewButton ? (
          <button
            type="button"
            onClick={openNewConversation}
            className="mx-auto flex h-8 w-8 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-[#eef3f8] hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#9fb0c4]/45 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200"
            aria-label={newConversationLabel}
            title={newConversationLabel}
          >
            <SquarePen className="h-3.5 w-3.5" strokeWidth={2.1} />
          </button>
        ) : null}
        {isListLoading && visibleSessions.length === 0 ? (
          <div className="mx-auto flex h-8 w-8 items-center justify-center rounded-md text-slate-400 dark:text-slate-500">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          </div>
        ) : null}
        {!isListLoading && visibleSessions.length === 0 && !showCollapsedNewButton ? (
          <button
            type="button"
            onClick={() => {
              updateExpanded(true);
              onExpandSidebar();
            }}
            className="mx-auto flex h-8 w-8 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-[#eef3f8] hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#9fb0c4]/45 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200"
            aria-label={title}
            title={title}
          >
            <MessageSquareText className="h-3.5 w-3.5" strokeWidth={2.2} />
          </button>
        ) : null}
        {visibleSessions.map((session) => {
          const sessionId = getSessionId(session);
          const isSelected =
            isConversationViewActive &&
            isActiveViewForListScope &&
            sessionId !== null &&
            activeConversationSessionId === sessionId;
          const courseLabel = getSessionCourseLabel(session);
          return (
            <button
              key={sessionId ?? `${getSessionCourseId(session)}-${session.title}-${session.last_message_at}`}
              type="button"
              onClick={() => openSession(session)}
              className={cn(
                "group mx-auto flex h-8 w-8 items-center justify-center rounded-md transition-colors focus-visible:outline-none",
                CONVERSATION_FOCUS_CLASS_NAME,
                isSelected
                  ? CONVERSATION_SELECTED_CLASS_NAME
                  : "text-slate-500 hover:bg-[#eef3f8] hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200",
              )}
              title={showCourseBadge ? `${courseLabel} - ${session.title || "未命名对话"}` : session.title || "未命名对话"}
              aria-label={`打开对话：${session.title || "未命名对话"}`}
            >
              <MessageSquareText
                className={cn(
                  "h-3.5 w-3.5 shrink-0",
                  isSelected ? CONVERSATION_SELECTED_ICON_CLASS_NAME : undefined,
                )}
                strokeWidth={2.2}
              />
            </button>
          );
        })}
      </section>
    );
  }

  return (
    <section
      className={cn(
        showTopBorder
          ? "mt-3 border-t border-slate-200/70 pt-2 dark:border-slate-800/70"
          : hideHeader
            ? ""
            : "mt-1",
        className,
      )}
    >
      {!hideHeader ? (
        <div className="flex h-8 items-center gap-1">
          <button
            type="button"
            onClick={() => updateExpanded((value) => !value)}
            className="group flex min-w-0 flex-1 items-center gap-1 rounded-md px-2 text-left text-[13px] font-medium text-slate-500 transition-colors hover:bg-[#eef3f8] hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200"
            aria-expanded={isExpanded}
          >
            <span className="truncate">{title}</span>
            <ChevronRight
              className={cn(
                "h-3 w-3 shrink-0 opacity-0 transition-[opacity,transform] group-hover:opacity-100 group-focus-visible:opacity-100",
                isExpanded && "rotate-90",
              )}
            />
            {isListLoading ? <Loader2 className="h-3 w-3 animate-spin text-current opacity-70" /> : null}
          </button>
          <button
            type="button"
            onClick={openNewConversation}
            className="flex h-7 shrink-0 items-center justify-center gap-1 rounded-md px-1.5 text-[13px] font-medium text-slate-500 transition hover:bg-[#eef3f8] hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#9fb0c4]/45 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200"
            aria-label={newConversationLabel}
            title={newConversationLabel}
          >
            <SquarePen className="h-3.5 w-3.5" strokeWidth={2.1} />
            <span>新建对话</span>
          </button>
        </div>
      ) : null}

      <AnimatePresence initial={false} mode="wait">
        {isListExpanded ? (
          <motion.div
            key={`conversation-list-${listScopeKey}`}
            variants={conversationListMotion}
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="space-y-0.5 overflow-hidden pb-2"
          >
          {error ? (
            <p className="mx-1 rounded-md border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] leading-4 text-red-600 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
              {error}
            </p>
          ) : null}

          {hasCurrentScopeSessions ? (
            <AnimatePresence initial={false}>
              {visibleSessions.map(renderSessionItem)}
            </AnimatePresence>
          ) : null}
          {!isListLoading && !error && visibleSessions.length === 0 && emptyText ? (
            <p className="px-2 py-1 text-[11px] text-slate-300 dark:text-slate-600">{emptyText}</p>
          ) : null}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </section>
  );
}
