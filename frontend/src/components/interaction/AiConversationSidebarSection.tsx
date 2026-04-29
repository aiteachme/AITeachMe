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

import { apiClient, getApiErrorMessage } from "../../api/client";
import type {
  ApiResponsePaginatedDataChatSessionItem,
  ChatSessionItem,
} from "../../api/generated/model";
import { cn } from "../../lib/utils";
import { useAiInteraction } from "./AiInteractionProvider";
import type { AiConversationScope, AiInteractionOpenRequest } from "./types";
import { AI_SOURCE_DOCUMENT_SELECTION, AI_SOURCE_EXAM_QUESTION } from "./types";

interface AiConversationSidebarSectionProps {
  collapsed: boolean;
  onExpandSidebar: () => void;
  onNavigate?: () => void;
}

type ConversationKind = "document" | "question" | "builder" | "general";

const GLOBAL_COURSE_ID = "global";
const RECENT_SECTION_EXPANDED_STORAGE_KEY = "aiteachme.aiConversations.recentExpanded";

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

const CONVERSATION_KIND_STYLES: Record<ConversationKind, {
  label: string;
  badgeClassName: string;
  selectedClassName: string;
  stripClassName: string;
  pulseClassName: string;
  iconClassName: string;
}> = {
  document: {
    label: "文档",
    badgeClassName: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-200",
    selectedClassName: "bg-sky-50 text-sky-950 ring-2 ring-sky-300/70 shadow-[0_0_0_4px_rgba(14,165,233,0.10)] dark:bg-sky-500/14 dark:text-sky-50 dark:ring-sky-400/45 dark:shadow-[0_0_0_4px_rgba(56,189,248,0.10)]",
    stripClassName: "bg-sky-500 dark:bg-sky-300",
    pulseClassName: "ring-sky-300/80 dark:ring-sky-300/45",
    iconClassName: "text-sky-600 dark:text-sky-200",
  },
  question: {
    label: "题目",
    badgeClassName: "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-200",
    selectedClassName: "bg-violet-50 text-violet-950 ring-2 ring-violet-300/70 shadow-[0_0_0_4px_rgba(139,92,246,0.10)] dark:bg-violet-500/14 dark:text-violet-50 dark:ring-violet-400/45 dark:shadow-[0_0_0_4px_rgba(167,139,250,0.10)]",
    stripClassName: "bg-violet-500 dark:bg-violet-300",
    pulseClassName: "ring-violet-300/80 dark:ring-violet-300/45",
    iconClassName: "text-violet-600 dark:text-violet-200",
  },
  builder: {
    label: "构建",
    badgeClassName: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-200",
    selectedClassName: "bg-amber-50 text-amber-950 ring-2 ring-amber-300/75 shadow-[0_0_0_4px_rgba(245,158,11,0.12)] dark:bg-amber-500/14 dark:text-amber-50 dark:ring-amber-400/45 dark:shadow-[0_0_0_4px_rgba(251,191,36,0.10)]",
    stripClassName: "bg-amber-500 dark:bg-amber-300",
    pulseClassName: "ring-amber-300/80 dark:ring-amber-300/45",
    iconClassName: "text-amber-600 dark:text-amber-200",
  },
  general: {
    label: "通用",
    badgeClassName: "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-200",
    selectedClassName: "bg-indigo-50 text-indigo-950 ring-2 ring-indigo-300/70 shadow-[0_0_0_4px_rgba(99,102,241,0.10)] dark:bg-indigo-500/14 dark:text-indigo-50 dark:ring-indigo-400/45 dark:shadow-[0_0_0_4px_rgba(129,140,248,0.10)]",
    stripClassName: "bg-indigo-500 dark:bg-indigo-300",
    pulseClassName: "ring-indigo-300/80 dark:ring-indigo-300/45",
    iconClassName: "text-indigo-600 dark:text-indigo-200",
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

function readRecentSectionExpanded(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    return window.localStorage.getItem(RECENT_SECTION_EXPANDED_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function writeRecentSectionExpanded(value: boolean) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(RECENT_SECTION_EXPANDED_STORAGE_KEY, value ? "true" : "false");
  } catch {
    // Storage can be unavailable in restricted webviews; the in-memory state still works.
  }
}

export function AiConversationSidebarSection({
  collapsed,
  onExpandSidebar,
  onNavigate,
}: AiConversationSidebarSectionProps) {
  const {
    activeScope,
    sidebarScope,
    sidebarRequest,
    isSidebarOpen,
    activeConversationSessionId,
    sessionListVersion,
    openAiInteraction,
    setActiveConversationSessionId,
    notifyConversationSessionsChanged,
  } = useAiInteraction();
  const scope = sidebarScope ?? activeScope;
  const newConversationScope = activeScope ?? scope ?? { type: "global" as const };
  const [isExpanded, setIsExpanded] = useState(readRecentSectionExpanded);
  const [sessions, setSessions] = useState<ChatSessionItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const shouldLoadSessions = isExpanded || isSidebarOpen;
  const hasActiveEmptyConversation =
    isSidebarOpen && activeConversationSessionId === null && !isPendingAnchoredRequest(sidebarRequest);
  const activeEmptyKind = getRequestKind(sidebarRequest);
  const activeEmptyStyle = CONVERSATION_KIND_STYLES[activeEmptyKind];
  const visibleSessions = useMemo(() => sessions.slice(0, 30), [sessions]);
  const updateExpanded = useCallback((next: boolean | ((current: boolean) => boolean)) => {
    setIsExpanded((current) => {
      const value = typeof next === "function" ? next(current) : next;
      writeRecentSectionExpanded(value);
      return value;
    });
  }, []);

  useEffect(() => {
    if (isSidebarOpen) {
      updateExpanded(true);
      if (collapsed) {
        onExpandSidebar();
      }
    }
  }, [collapsed, isSidebarOpen, onExpandSidebar, updateExpanded]);

  useEffect(() => {
    if (!shouldLoadSessions) {
      return;
    }

    let cancelled = false;
    async function loadSessions() {
      setIsLoading(true);
      setError(null);
      try {
        const res = await apiClient<ApiResponsePaginatedDataChatSessionItem>({
          method: "POST",
          url: "/api/v1/chats/sessions/list",
          data: { page: 1, size: 30, include_all_courses: true },
        });
        if (cancelled) {
          return;
        }
        setSessions(res.data?.items ?? []);
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
  }, [sessionListVersion, shouldLoadSessions]);

  const openNewConversation = useCallback(() => {
    updateExpanded(true);
    onExpandSidebar();
    openAiInteraction({ mode: "sidebar", scope: newConversationScope, sessionId: null, newSession: true });
    onNavigate?.();
  }, [newConversationScope, onExpandSidebar, onNavigate, openAiInteraction, updateExpanded]);

  const openSession = useCallback((session: ChatSessionItem) => {
    const sessionId = getSessionId(session);
    if (!sessionId) {
      setError("这条会话缺少会话 ID，暂时无法打开");
      return;
    }
    updateExpanded(true);
    onExpandSidebar();
    openAiInteraction({
      mode: "sidebar",
      scope: getSessionScope(session),
      sessionId,
      source: session.source,
      anchorId: session.anchor_id,
      selectedText: session.selected_text,
      showSelectionContext: false,
    });
    onNavigate?.();
  }, [onExpandSidebar, onNavigate, openAiInteraction, updateExpanded]);

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
          const isSelected = isSidebarOpen && sessionId !== null && activeConversationSessionId === sessionId;
          const kindStyle = CONVERSATION_KIND_STYLES[getSessionKind(session)];
          const courseLabel = getSessionCourseLabel(session);
          return (
            <button
              key={sessionId ?? `${getSessionCourseId(session)}-${session.title}-${session.last_message_at}`}
              type="button"
              onClick={() => openSession(session)}
              className={cn(
                "group flex h-7 w-full items-center justify-center rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#9fb0c4]/45",
                isSelected
                  ? kindStyle.selectedClassName
                  : "text-slate-500 hover:bg-[#eef3f8] hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200",
              )}
              title={`${courseLabel} - ${session.title || "未命名对话"}`}
              aria-label={`打开对话：${session.title || "未命名对话"}`}
            >
              <MessageSquareText
                className={cn(
                  "h-3.5 w-3.5 shrink-0",
                  isSelected ? kindStyle.iconClassName : undefined,
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
    <section className="mt-3 border-t border-slate-200/70 pt-2 dark:border-slate-800/70">
      <div className="flex h-7 items-center gap-1">
        <button
          type="button"
          onClick={() => updateExpanded((value) => !value)}
          className="group flex min-w-0 flex-1 items-center gap-1 rounded-md px-2 text-left text-[11px] font-medium text-slate-400 transition-colors hover:bg-[#eef3f8] hover:text-slate-700 dark:text-slate-500 dark:hover:bg-slate-800/60 dark:hover:text-slate-300"
          aria-expanded={isExpanded}
        >
          <span className="truncate">最近</span>
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
          aria-label="新建 AI 对话"
          title="新建 AI 对话"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>

      <AnimatePresence initial={false}>
        {isExpanded ? (
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
                activeEmptyStyle.selectedClassName,
              )}
            >
              <span className={cn("pointer-events-none absolute inset-0 rounded-md ring-2 opacity-60 animate-pulse", activeEmptyStyle.pulseClassName)} />
              <Sparkles className={cn("h-3.5 w-3.5 shrink-0", activeEmptyStyle.iconClassName)} />
              <span className={cn("inline-flex h-4 shrink-0 items-center rounded px-1 text-[9px] font-semibold leading-none", activeEmptyStyle.badgeClassName)}>
                {activeEmptyStyle.label}
              </span>
              <span className="min-w-0 flex-1 truncate text-xs font-medium">新会话</span>
            </motion.button>
          ) : null}

          <AnimatePresence initial={false}>
            {visibleSessions.map((session) => {
              const sessionId = getSessionId(session);
              const isSelected = isSidebarOpen && sessionId !== null && activeConversationSessionId === sessionId;
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
                      ? kindStyle.selectedClassName
                      : "text-slate-700 hover:bg-[#eef3f8] hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200",
                  )}
                >
                {isSelected ? (
                  <>
                    <span className={cn("absolute bottom-1.5 left-0 top-1.5 w-0.5 rounded-r-full", kindStyle.stripClassName)} />
                    <span className={cn("pointer-events-none absolute inset-0 rounded-md ring-2 opacity-60 animate-pulse", kindStyle.pulseClassName)} />
                  </>
                ) : null}
                <button
                  type="button"
                  onClick={() => openSession(session)}
                  className="flex h-7 w-full items-center gap-1.5 px-2 pr-7 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#9fb0c4]/45"
                  title={session.title || "未命名对话"}
                >
                  <span className={cn("inline-flex h-4 shrink-0 items-center rounded px-1 text-[9px] font-semibold leading-none", kindStyle.badgeClassName)}>
                    {kindStyle.label}
                  </span>
                  <span
                    className="inline-flex h-4 max-w-[4.75rem] shrink-0 items-center truncate rounded bg-slate-100 px-1 text-[9px] font-semibold leading-none text-slate-500 dark:bg-slate-800 dark:text-slate-300"
                    title={courseLabel}
                  >
                    {courseLabel}
                  </span>
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
          </motion.div>
        ) : null}
      </AnimatePresence>
    </section>
  );
}
