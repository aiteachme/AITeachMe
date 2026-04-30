import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronRight,
  Loader2,
  MessageSquareText,
  Plus,
  Sparkles,
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
import type { AiConversationScope, AiInteractionOpenRequest } from "./types";
import {
  AI_SOURCE_DOCUMENT_SELECTION,
  AI_SOURCE_EXAM_QUESTION,
  getAiConversationScopeKey,
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
}

type ConversationKind = "document" | "question" | "builder" | "general";

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
  hidden: { opacity: 0, x: -8, scale: 0.985 },
  visible: {
    opacity: 1,
    x: 0,
    scale: 1,
    transition: { type: "spring", stiffness: 420, damping: 34 },
  },
  exit: {
    opacity: 0,
    x: -8,
    scale: 0.985,
    transition: { duration: 0.14, ease: "easeOut" },
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

function getRequestKind(request: AiInteractionOpenRequest | null): ConversationKind {
  return getConversationKindBySource(
    request?.source,
    Boolean(request?.anchorId?.trim() && request?.selectedText?.trim()),
  );
}

function isPendingAnchoredRequest(request: AiInteractionOpenRequest | null): boolean {
  return Boolean(
    request?.sessionId === null &&
    request.anchorId?.trim() &&
    request.selectedText?.trim(),
  );
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

function getSessionCourseLabel(session: ChatSessionItem): string {
  const courseId = getSessionCourseId(session);
  return session.course_name?.trim() || (courseId === GLOBAL_COURSE_ID ? "通用" : "未命名课程");
}

function getSessionScope(session: ChatSessionItem): AiConversationScope {
  const courseId = getSessionCourseId(session);
  return courseId === GLOBAL_COURSE_ID
    ? { type: "global" }
    : { type: "course", courseId };
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

  return {
    url: `/api/v1/courses/${scope.courseId}/chats/sessions/list`,
    data: { page: 1, size },
  };
}

function getNewConversationLabel(scope: AiConversationScope): string {
  return scope.type === "global" ? "新建全局对话" : "新建课程对话";
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
}: AiConversationSidebarSectionProps) {
  const {
    activeScope,
    sidebarScope,
    fullscreenScope,
    sidebarRequest,
    fullscreenRequest,
    isSidebarOpen,
    activeConversationSessionId,
    sessionListVersion,
    openAiInteraction,
    setActiveConversationSessionId,
    notifyConversationSessionsChanged,
  } = useAiInteraction();
  const location = useLocation();
  const isAssistantPage = location.pathname === "/assistant";
  const currentRequest = isAssistantPage ? fullscreenRequest : sidebarRequest;
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
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isConversationViewActive = isAssistantPage || isSidebarOpen;
  const isListExpanded = hideHeader || isExpanded;
  const shouldLoadSessions = isListExpanded || (isConversationViewActive && isActiveViewForListScope);
  const hasActiveEmptyConversation =
    isConversationViewActive &&
    isActiveViewForListScope &&
    activeConversationSessionId === null &&
    !isPendingAnchoredRequest(currentRequest);
  const activeEmptyKind = getRequestKind(currentRequest);
  const activeEmptyStyle = CONVERSATION_KIND_STYLES[activeEmptyKind];
  const visibleSessions = useMemo(() => sessions.slice(0, maxItems), [maxItems, sessions]);
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
      } catch (requestError: unknown) {
        if (!cancelled) {
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
    updateExpanded(true);
    onExpandSidebar();
    openAiInteraction({
      mode: isAssistantPage ? "fullscreen" : "sidebar",
      scope: newConversationScope,
      sessionId: null,
      newSession: true,
    });
    onNavigate?.();
  }, [isAssistantPage, newConversationScope, onExpandSidebar, onNavigate, openAiInteraction, updateExpanded]);

  const openSession = useCallback((session: ChatSessionItem) => {
    const sessionId = getSessionId(session);
    if (!sessionId) {
      setError("这条会话缺少会话 ID，暂时无法打开");
      return;
    }
    updateExpanded(true);
    onExpandSidebar();
    openAiInteraction({
      mode: isAssistantPage ? "fullscreen" : "sidebar",
      scope: getSessionScope(session),
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
    try {
      await apiClient({
        method: "POST",
        url: getSessionDeleteUrl(target),
        data: { session_id: sessionId },
      });
      setSessions((current) => current.filter((item) => getSessionId(item) !== sessionId));
      if (activeConversationSessionId === sessionId) {
        setActiveConversationSessionId(null);
      }
      setError(null);
      notifyConversationSessionsChanged();
    } catch (requestError: unknown) {
      setError(getApiErrorMessage(requestError, "删除对话失败"));
    }
  }, [
    activeConversationSessionId,
    notifyConversationSessionsChanged,
    setActiveConversationSessionId,
  ]);

  if (collapsed) {
    return (
      <section className="space-y-0.5">
        <div className="flex h-6 items-center px-1">
          <div className="h-px w-full bg-slate-200 dark:bg-slate-800" />
        </div>
        {isLoading && visibleSessions.length === 0 ? (
          <div className="flex h-7 w-full items-center justify-center rounded-md text-slate-400 dark:text-slate-500">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          </div>
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
                "group flex h-7 w-full items-center justify-center rounded-md transition-colors focus-visible:outline-none",
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
        <div className="flex h-7 items-center gap-1">
          <button
            type="button"
            onClick={() => updateExpanded((value) => !value)}
            className="group flex min-w-0 flex-1 items-center gap-1 rounded-md px-2 text-left text-[11px] font-medium text-slate-400 transition-colors hover:bg-[#eef3f8] hover:text-slate-700 dark:text-slate-500 dark:hover:bg-slate-800/60 dark:hover:text-slate-300"
            aria-expanded={isExpanded}
          >
            <span className="truncate">{title}</span>
            <ChevronRight
              className={cn(
                "h-3 w-3 shrink-0 opacity-0 transition-[opacity,transform] group-hover:opacity-100 group-focus-visible:opacity-100",
                isExpanded && "rotate-90",
              )}
            />
            {isLoading ? <Loader2 className="h-3 w-3 animate-spin text-current opacity-70" /> : null}
          </button>
          <button
            type="button"
            onClick={openNewConversation}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-slate-400 transition hover:bg-[#eef3f8] hover:text-sky-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#9fb0c4]/45 dark:text-slate-500 dark:hover:bg-slate-800/60 dark:hover:text-sky-300"
            aria-label={newConversationLabel}
            title={newConversationLabel}
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>
      ) : null}

      <AnimatePresence initial={false}>
        {isListExpanded ? (
          <motion.div
            key="conversation-list"
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

          {hasActiveEmptyConversation ? (
            <motion.button
              type="button"
              onClick={openNewConversation}
              variants={conversationItemMotion}
              initial="hidden"
              animate="visible"
              exit="exit"
              whileTap={{ scale: 0.985 }}
              className={cn(
                "group relative flex h-7 w-full items-center gap-1.5 overflow-hidden rounded-md px-2 text-left",
                CONVERSATION_SELECTED_CLASS_NAME,
              )}
            >
              <Sparkles className={cn("h-3.5 w-3.5 shrink-0", CONVERSATION_SELECTED_ICON_CLASS_NAME)} />
              <span className={cn("inline-flex h-4 shrink-0 items-center rounded px-1 text-[9px] font-semibold leading-none", activeEmptyStyle.badgeClassName)}>
                {activeEmptyStyle.label}
              </span>
              <span className="min-w-0 flex-1 truncate text-xs font-medium">新会话</span>
            </motion.button>
          ) : null}

          <AnimatePresence initial={false}>
            {visibleSessions.map((session) => {
              const sessionId = getSessionId(session);
              const isSelected =
                isConversationViewActive &&
                isActiveViewForListScope &&
                sessionId !== null &&
                activeConversationSessionId === sessionId;
              const kindStyle = CONVERSATION_KIND_STYLES[getSessionKind(session)];
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
                  <span className={cn("inline-flex h-4 shrink-0 items-center rounded px-1 text-[9px] font-semibold leading-none", kindStyle.badgeClassName)}>
                    {kindStyle.label}
                  </span>
                  {showCourseBadge ? (
                    <span
                      className="inline-flex h-4 max-w-[4.75rem] shrink-0 items-center truncate rounded bg-slate-100 px-1 text-[9px] font-semibold leading-none text-slate-500 dark:bg-slate-800 dark:text-slate-300"
                      title={courseLabel}
                    >
                      {courseLabel}
                    </span>
                  ) : null}
                  <span className="min-w-0 flex-1 truncate text-xs leading-7">
                    {session.title || "未命名对话"}
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
            })}
          </AnimatePresence>
          {!isLoading && !error && !hasActiveEmptyConversation && visibleSessions.length === 0 ? (
            <p className="px-2 py-1 text-[11px] text-slate-300 dark:text-slate-600">{emptyText}</p>
          ) : null}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </section>
  );
}
