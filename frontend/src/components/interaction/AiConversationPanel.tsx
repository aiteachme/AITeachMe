import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  ChevronRight,
  Loader2,
  MapPin,
  MessageSquareText,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import { apiClient, getApiErrorMessage } from "../../api/client";
import type {
  ApiResponsePaginatedDataChatSessionItem,
  ChatSelectionContext,
  ChatSendRequest,
  ChatSessionItem,
} from "../../api/generated/model";
import { type ChatSessionMessage, useChatSession } from "../../hooks/useChatSession";
import { buildCoursePath, buildCourseSubPath, isCourseRouteActive } from "../../lib/courseNavigation";
import { cn } from "../../lib/utils";
import { ChatCitationModal } from "../chat/ChatCitationModal";
import { ChatComposer } from "../chat/ChatComposer";
import {
  DEFAULT_CHAT_MODEL_CHOICE,
  type ChatModelChoice,
  toChatRequestModel,
} from "../chat/ChatModelSelect";
import { ChatTranscript } from "../chat/ChatTranscript";
import { HeroAnimation } from "../ui/HeroAnimation";
import { useAiInteraction } from "./AiInteractionProvider";
import type { AiConversationScope, AiInteractionOpenRequest, ExamQuestionJumpDetail } from "./types";
import {
  AI_SOURCE_DOCUMENT_SELECTION,
  AI_SOURCE_EXAM_QUESTION,
  EXAM_QUESTION_JUMP_EVENT,
  getAiConversationBackendCourseId,
  parseExamQuestionAnchorId,
} from "./types";

interface AiConversationPanelProps {
  scope: AiConversationScope | null;
  request?: AiInteractionOpenRequest | null;
  active: boolean;
  presentation: "sidebar" | "fullscreen";
  onClose?: () => void;
  className?: string;
}

interface PendingSelectionContext {
  source: string;
  anchorId: string | null;
  selectedText: string;
  selectionContext: ChatSelectionContext | null;
  clientThreadId: string | null;
}

type QuickChatSyncPhase = "start" | "session" | "token" | "done" | "error" | "settled";

interface QuickChatInputContext {
  source: string;
  anchorId: string;
  selectedText: string;
}

interface ChatSessionSelectionTarget {
  kind: "document" | "exam_question";
  sessionId: string | null;
  anchorId: string;
  selectedText: string;
  paperId?: number;
  questionOrder?: number;
}

const QUICK_CHAT_UPDATED_EVENT = "aiteachme:quick-chat-updated";
const SELECTION_JUMP_EVENT = "aiteachme:selection-jump";
const AUTO_SCROLL_BOTTOM_THRESHOLD = 96;

function getQuickChatInputContext(input: ChatSendRequest): QuickChatInputContext | null {
  const source = input.source?.trim() ?? "";
  const anchorId = input.anchor_id?.trim() ?? "";
  const selectedText = input.selected_text?.trim() ?? input.selection_context?.selected_text?.trim() ?? "";
  if (source !== AI_SOURCE_DOCUMENT_SELECTION || !anchorId || !selectedText) {
    return null;
  }
  return { source, anchorId, selectedText };
}

function normalizeQuickChatSelectionText(value: string | null | undefined): string {
  return (value ?? "").replace(/\s+/g, "").trim();
}

function updateQuickChatCachedMessage(
  messages: ChatSessionMessage[],
  localId: string,
  updater: (message: ChatSessionMessage) => ChatSessionMessage,
): ChatSessionMessage[] {
  let found = false;
  const nextMessages = messages.map((message) => {
    if (message.localId !== localId) {
      return message;
    }
    found = true;
    return updater(message);
  });
  return found ? nextMessages : messages;
}

function getSessionSelectionTarget(session: ChatSessionItem | null): ChatSessionSelectionTarget | null {
  if (!session) {
    return null;
  }
  const anchorId = session.anchor_id?.trim() ?? "";
  const selectedText = session.selected_text?.trim() ?? "";
  if (!anchorId || !selectedText) {
    return null;
  }
  if (session.source === AI_SOURCE_EXAM_QUESTION) {
    const parsed = parseExamQuestionAnchorId(anchorId);
    if (!parsed) {
      return null;
    }
    return {
      kind: "exam_question",
      sessionId: session.id,
      anchorId,
      selectedText,
      paperId: parsed.paperId,
      questionOrder: parsed.questionOrder,
    };
  }
  if (session.source !== AI_SOURCE_DOCUMENT_SELECTION) {
    return null;
  }
  return {
    kind: "document",
    sessionId: session.id,
    anchorId,
    selectedText,
  };
}

function getChatSessionItemId(session: ChatSessionItem | null): string | null {
  const sessionId = session?.id?.trim();
  if (sessionId) {
    return sessionId;
  }
  const legacySessionId = (session as { session_id?: string | null } | null)?.session_id?.trim();
  return legacySessionId || null;
}

function getContextSelectionTarget(context: PendingSelectionContext | null): ChatSessionSelectionTarget | null {
  const anchorId = context?.anchorId?.trim() ?? "";
  const selectedText = context?.selectedText?.trim() ?? "";
  if (!anchorId || !selectedText) {
    return null;
  }
  if (context?.source === AI_SOURCE_EXAM_QUESTION) {
    const parsed = parseExamQuestionAnchorId(anchorId);
    if (!parsed) {
      return null;
    }
    return {
      kind: "exam_question",
      sessionId: null,
      anchorId,
      selectedText,
      paperId: parsed.paperId,
      questionOrder: parsed.questionOrder,
    };
  }
  return {
    kind: "document",
    sessionId: null,
    anchorId,
    selectedText,
  };
}

function ConversationEmptyState({
  title,
  description,
  animationKey,
}: {
  title: string;
  description: string;
  animationKey: number;
}) {
  return (
    <div className="flex h-full items-center justify-center px-6">
      <div className="max-w-md text-center">
        <div className="flex justify-center">
          <HeroAnimation key={animationKey} width={84} height={78} />
        </div>
        <h3 className="mt-4 text-[17px] font-semibold tracking-tight text-zinc-900 dark:text-slate-100">
          {title}
        </h3>
        <p className="mt-2 text-[13px] leading-relaxed text-zinc-500 dark:text-slate-400">
          {description}
        </p>
      </div>
    </div>
  );
}

function SelectionTextPreview({
  prefix,
  text,
  className,
  placement = "below",
}: {
  prefix: string;
  text: string;
  className?: string;
  placement?: "above" | "below";
}) {
  const normalizedText = text.replace(/\s+/g, " ").trim();
  if (!normalizedText) {
    return null;
  }

  return (
    <div className={cn("group relative min-w-0 max-w-full", className)} aria-label={`${prefix}${normalizedText}`}>
      <p className="block min-w-0 max-w-full truncate whitespace-nowrap">
        {prefix}{normalizedText}
      </p>
      <div
        className={cn(
          "absolute left-0 z-[70] hidden max-h-44 w-max max-w-[min(34rem,calc(100vw-2rem))] overflow-y-auto whitespace-normal break-words rounded-lg border border-slate-200 bg-white px-3 py-2 text-[12px] leading-5 text-slate-700 shadow-xl shadow-slate-900/10 [overflow-wrap:anywhere] group-hover:block dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100",
          placement === "above" ? "bottom-full mb-2" : "top-full mt-2",
        )}
      >
        <span className="font-semibold text-slate-500 dark:text-slate-300">{prefix}</span>
        {normalizedText}
      </div>
    </div>
  );
}

export const AiConversationPanel = memo(function AiConversationPanel({
  scope,
  request,
  active,
  presentation,
  onClose,
  className,
}: AiConversationPanelProps) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const {
    sessionListVersion,
    setActiveConversationSessionId,
    setActiveConversationSelectionTarget,
    setSidebarStreaming,
    getQuickChatSessionId,
    bindQuickChatSession,
    getCachedQuickChatMessages,
    cacheQuickChatMessages,
    notifyConversationSessionsChanged,
  } = useAiInteraction();
  const courseId = getAiConversationBackendCourseId(scope);
  const docsCourseId = scope?.type === "course" ? scope.courseId : null;
  const isKnowledgeDocsPage = Boolean(docsCourseId && isCourseRouteActive(pathname, docsCourseId, "knowledge-docs"));

  const [draft, setDraft] = useState("");
  const [chatModel, setChatModel] = useState<ChatModelChoice>(DEFAULT_CHAT_MODEL_CHOICE);
  const [sessions, setSessions] = useState<ChatSessionItem[]>([]);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [selectedChunkId, setSelectedChunkId] = useState<number | null>(null);
  const [pendingSelectionContext, setPendingSelectionContext] = useState<PendingSelectionContext | null>(null);
  const [activeQuickChatContext, setActiveQuickChatContext] = useState<PendingSelectionContext | null>(null);
  const [composerFocusKey, setComposerFocusKey] = useState(0);
  const [emptyAnimationKey, setEmptyAnimationKey] = useState(0);
  const preferEmptySessionRef = useRef(false);
  const wasActiveRef = useRef(false);
  const pendingSelectionContextRef = useRef<PendingSelectionContext | null>(null);
  const pendingSelectionSubmittedRef = useRef(false);
  const requestedSessionIdRef = useRef<string | null>(null);
  const quickChatMessagesRef = useRef<Record<string, ChatSessionMessage[]>>({});
  const messagesRef = useRef<ChatSessionMessage[]>([]);
  const messagesSessionIdRef = useRef<string | null>(null);
  const selectedSessionIdRef = useRef<string | null>(null);
  const activeQuickChatContextRef = useRef<PendingSelectionContext | null>(null);
  const activeQuickChatThreadIdRef = useRef("");
  const messageScrollRef = useRef<HTMLDivElement | null>(null);
  const shouldStickToBottomRef = useRef(true);
  const lastMessageScrollKeyRef = useRef("");
  const lastStreamingRef = useRef(false);
  const scrollFrameRef = useRef<number | null>(null);

  const dispatchQuickChatSync = useCallback((
    phase: QuickChatSyncPhase,
    payload: {
      input: ChatSendRequest;
      localThreadId: string;
      assistantLocalId: string;
      sessionId: string | null;
      userLocalId?: string;
      question?: string;
      content?: string;
      detail?: string;
      createdAt?: string;
      turnId?: string;
    },
  ) => {
    if (!docsCourseId) {
      return;
    }
    const quickChatContext = getQuickChatInputContext(payload.input);
    if (!quickChatContext) {
      return;
    }
    window.dispatchEvent(new CustomEvent(QUICK_CHAT_UPDATED_EVENT, {
      detail: {
        phase,
        courseId: docsCourseId,
        source: quickChatContext.source,
        anchorId: quickChatContext.anchorId,
        selectedText: quickChatContext.selectedText,
        localThreadId: payload.localThreadId,
        sessionId: payload.sessionId,
        assistantLocalId: payload.assistantLocalId,
        userLocalId: payload.userLocalId,
        question: payload.question,
        content: payload.content,
        errorDetail: payload.detail,
        createdAt: payload.createdAt,
        turnId: payload.turnId,
      },
    }));
  }, [docsCourseId]);

  const applyResolvedSessionTitle = useCallback((sessionId: string | null, title: string | null) => {
    const nextTitle = title?.trim();
    if (!sessionId || !nextTitle) {
      return;
    }
    setSessions((current) =>
      current.map((item) => (getChatSessionItemId(item) === sessionId ? { ...item, title: nextTitle } : item)),
    );
  }, []);

  const rememberQuickChatMessages = useCallback((
    localThreadId: string | null | undefined,
    sessionId: string | null | undefined,
    nextMessages: ChatSessionMessage[],
  ) => {
    if (nextMessages.length === 0) {
      return;
    }
    const ids = Array.from(new Set([
      localThreadId?.trim() || null,
      sessionId?.trim() || null,
    ].filter((value): value is string => Boolean(value))));
    for (const id of ids) {
      quickChatMessagesRef.current[id] = nextMessages;
      cacheQuickChatMessages(id, nextMessages);
    }
  }, [cacheQuickChatMessages]);

  const updateRememberedQuickChatMessages = useCallback((
    localThreadId: string | null | undefined,
    sessionId: string | null | undefined,
    updater: (messages: ChatSessionMessage[]) => ChatSessionMessage[],
  ) => {
    const ids = Array.from(new Set([
      localThreadId?.trim() || null,
      sessionId?.trim() || null,
    ].filter((value): value is string => Boolean(value))));
    if (ids.length === 0) {
      return;
    }
    const baseMessages =
      ids.map((id) => quickChatMessagesRef.current[id] ?? getCachedQuickChatMessages(id)).find((item) => (item?.length ?? 0) > 0) ??
      (messagesRef.current.length > 0 ? messagesRef.current : null);
    if (!baseMessages) {
      return;
    }
    rememberQuickChatMessages(localThreadId, sessionId, updater(baseMessages));
  }, [getCachedQuickChatMessages, rememberQuickChatMessages]);

  const {
    messages,
    messagesSessionId,
    historyLoaded,
    historyError,
    isStreaming,
    sendMessage,
    abortStream,
    clearHistory,
    replaceMessages,
  } = useChatSession(courseId ?? "", {
    sessionId: selectedSessionId,
    enabled: active && Boolean(courseId),
    loadWithoutSession: false,
    preserveMessagesWithoutSession: true,
    onSessionResolved: (nextSessionId) => {
      preferEmptySessionRef.current = false;
      requestedSessionIdRef.current = nextSessionId;
      setSelectedSessionId(nextSessionId);
      setActiveConversationSessionId(nextSessionId);
    },
    onMessageStart: (payload) => {
      if (getQuickChatInputContext(payload.input)) {
        rememberQuickChatMessages(payload.localThreadId, payload.sessionId, [
          {
            localId: payload.userLocalId,
            role: "user",
            content: payload.question,
            turnId: null,
            contexts: null,
            createdAt: payload.createdAt,
            status: "ready",
            errorDetail: null,
          },
          {
            localId: payload.assistantLocalId,
            role: "assistant",
            content: "",
            turnId: null,
            contexts: null,
            createdAt: payload.createdAt,
            status: "streaming",
            errorDetail: null,
          },
        ]);
      }
      dispatchQuickChatSync("start", payload);
    },
    onMessageSessionResolved: (payload) => {
      bindQuickChatSession(payload.localThreadId, payload.sessionId);
      const currentMessages = messagesRef.current;
      if (currentMessages.length > 0) {
        cacheQuickChatMessages(payload.localThreadId, currentMessages);
        cacheQuickChatMessages(payload.sessionId, currentMessages);
      }
      dispatchQuickChatSync("session", payload);
      notifyConversationSessionsChanged();
    },
    onMessageToken: (payload) => {
      updateRememberedQuickChatMessages(payload.localThreadId, payload.sessionId, (current) =>
        updateQuickChatCachedMessage(current, payload.assistantLocalId, (message) => ({
          ...message,
          content: `${message.content}${payload.content}`,
        })),
      );
      dispatchQuickChatSync("token", payload);
    },
    onMessageDone: (payload) => {
      bindQuickChatSession(payload.localThreadId, payload.sessionId);
      updateRememberedQuickChatMessages(payload.localThreadId, payload.sessionId, (current) =>
        updateQuickChatCachedMessage(current, payload.assistantLocalId, (message) => ({
          ...message,
          turnId: payload.turnId,
          status: "ready",
          errorDetail: null,
        })),
      );
      applyResolvedSessionTitle(payload.sessionId, payload.sessionTitle);
      dispatchQuickChatSync("done", payload);
      notifyConversationSessionsChanged();
    },
    onMessageError: (payload) => {
      updateRememberedQuickChatMessages(payload.localThreadId, payload.sessionId, (current) =>
        updateQuickChatCachedMessage(current, payload.assistantLocalId, (message) => ({
          ...message,
          status: "error",
          errorDetail: payload.detail,
        })),
      );
      dispatchQuickChatSync("error", payload);
    },
    onMessageSettled: (payload) => dispatchQuickChatSync("settled", payload),
  });

  const selectedSession = useMemo(
    () => sessions.find((item) => getChatSessionItemId(item) === selectedSessionId) ?? null,
    [selectedSessionId, sessions],
  );
  const isPlannerConversation = selectedSession?.source === "build_planner";
  const isFullscreen = presentation === "fullscreen";
  const currentMessagesSessionId = selectedSessionId ?? null;
  const hasLocalStreamingMessages = isStreaming && messages.length > 0;
  const messagesBelongToCurrentSession = messagesSessionId === currentMessagesSessionId || hasLocalStreamingMessages;
  const visibleMessages = messagesBelongToCurrentSession ? messages : [];
  const currentHistoryLoaded = hasLocalStreamingMessages || (historyLoaded && messagesBelongToCurrentSession);
  const isQuestionContext = (pendingSelectionContext ?? activeQuickChatContext)?.source === AI_SOURCE_EXAM_QUESTION;
  const panelTitle = selectedSession?.title ?? (
    selectedSessionId
      ? pendingSelectionContext || activeQuickChatContext
        ? isQuestionContext ? "题目提问" : "划词提问"
        : "加载会话..."
      : pendingSelectionContext || activeQuickChatContext
        ? isQuestionContext ? "题目提问" : "划词提问"
        : "新会话"
  );
  const activeQuickChatThreadId = activeQuickChatContext?.clientThreadId?.trim() ?? "";
  const messageScrollKey = useMemo(() => {
    const lastMessage = visibleMessages[visibleMessages.length - 1];
    return [
      currentMessagesSessionId ?? "",
      visibleMessages.length,
      lastMessage?.localId ?? "",
      lastMessage?.status ?? "",
      lastMessage?.content.length ?? 0,
    ].join(":");
  }, [currentMessagesSessionId, visibleMessages]);
  const currentSelectionTarget = useMemo(
    () => getSessionSelectionTarget(selectedSession) ?? getContextSelectionTarget(activeQuickChatContext),
    [activeQuickChatContext, selectedSession],
  );

  useEffect(() => {
    if (presentation !== "sidebar") {
      return;
    }
    if (!active) {
      setActiveConversationSelectionTarget(null);
      return;
    }
    if (!currentSelectionTarget) {
      return;
    }
    setActiveConversationSelectionTarget({
      sessionId: currentSelectionTarget.sessionId ?? selectedSessionId ?? null,
      anchorId: currentSelectionTarget.anchorId,
      selectedText: currentSelectionTarget.selectedText,
    });
  }, [active, currentSelectionTarget, presentation, selectedSessionId, setActiveConversationSelectionTarget]);

  const scrollMessagesToBottom = useCallback(() => {
    const currentScrollElement = messageScrollRef.current;
    if (currentScrollElement) {
      currentScrollElement.scrollTop = currentScrollElement.scrollHeight;
    }
    if (scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current);
    }
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      const scrollElement = messageScrollRef.current;
      if (!scrollElement) {
        return;
      }
      scrollElement.scrollTo({
        top: scrollElement.scrollHeight,
        behavior: "auto",
      });
    });
  }, []);

  const handleMessageScroll = useCallback(() => {
    const scrollElement = messageScrollRef.current;
    if (!scrollElement) {
      return;
    }
    const distanceToBottom = scrollElement.scrollHeight - scrollElement.scrollTop - scrollElement.clientHeight;
    shouldStickToBottomRef.current = distanceToBottom <= AUTO_SCROLL_BOTTOM_THRESHOLD;
  }, []);
  const handleOpenCitation = useCallback((chunkId: number) => {
    setSelectedChunkId(chunkId);
  }, []);

  const jumpToSelectionTarget = useCallback((target: ChatSessionSelectionTarget | null) => {
    if (!docsCourseId || !target) {
      return;
    }
    if (target.kind === "exam_question") {
      if (!target.paperId || !target.questionOrder) {
        return;
      }
      const detail: ExamQuestionJumpDetail = {
        courseId: docsCourseId,
        paperId: target.paperId,
        questionOrder: target.questionOrder,
        anchorId: target.anchorId,
        selectedText: target.selectedText,
        sessionId: target.sessionId,
      };
      const targetPath = buildCourseSubPath(docsCourseId, "exams", target.paperId);
      if (pathname !== targetPath) {
        navigate(targetPath, {
          state: {
            examQuestionJump: detail,
            examQuestionJumpAt: Date.now(),
          },
        });
        return;
      }
      window.dispatchEvent(new CustomEvent(EXAM_QUESTION_JUMP_EVENT, { detail }));
      return;
    }
    const detail = {
      courseId: docsCourseId,
      sessionId: target.sessionId,
      anchorId: target.anchorId,
      selectedText: target.selectedText,
    };
    if (!isKnowledgeDocsPage) {
      navigate(buildCoursePath(docsCourseId, "knowledge-docs"), {
        state: {
          selectionJump: detail,
          selectionJumpAt: Date.now(),
        },
      });
      return;
    }
    window.dispatchEvent(new CustomEvent(SELECTION_JUMP_EVENT, { detail }));
  }, [docsCourseId, isKnowledgeDocsPage, navigate, pathname]);

  const reloadSessions = useCallback(async (preferredSessionId?: string | null) => {
    if (!courseId) {
      setSessions([]);
      setSelectedSessionId(null);
      return;
    }

    setSessionsError(null);
    try {
      const res = await apiClient<ApiResponsePaginatedDataChatSessionItem>({
        method: "POST",
        url: `/api/v1/courses/${courseId}/chats/sessions/list`,
        data: {
          page: 1,
          size: 100,
        },
      });
      const items = res.data?.items ?? [];
      const requestedSessionId =
        preferredSessionId !== undefined
          ? preferredSessionId
          : request?.sessionId !== undefined
            ? request.sessionId
            : requestedSessionIdRef.current;
      setSessions(items);
      setSelectedSessionId((current) => {
        if (requestedSessionId && items.some((item) => getChatSessionItemId(item) === requestedSessionId)) {
          return requestedSessionId;
        }
        if (requestedSessionId && (pendingSelectionSubmittedRef.current || isStreaming || current === requestedSessionId)) {
          return requestedSessionId;
        }
        if (preferEmptySessionRef.current || (pendingSelectionContextRef.current && !pendingSelectionSubmittedRef.current)) {
          return null;
        }
        if (current && items.some((item) => getChatSessionItemId(item) === current)) {
          return current;
        }
        return null;
      });
    } catch (error: unknown) {
      setSessionsError(getApiErrorMessage(error, "加载会话历史失败"));
    }
  }, [isStreaming, request?.sessionId, courseId]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    messagesSessionIdRef.current = messagesSessionId;
  }, [messagesSessionId]);

  useEffect(() => {
    selectedSessionIdRef.current = selectedSessionId;
  }, [selectedSessionId]);

  useEffect(() => {
    activeQuickChatContextRef.current = activeQuickChatContext;
  }, [activeQuickChatContext]);

  useEffect(() => {
    activeQuickChatThreadIdRef.current = activeQuickChatThreadId;
  }, [activeQuickChatThreadId]);

  useEffect(() => {
    if (active) {
      setActiveConversationSessionId(selectedSessionId);
    }
  }, [active, selectedSessionId, setActiveConversationSessionId]);

  useEffect(() => {
    return () => {
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current);
      }
    };
  }, []);

  useLayoutEffect(() => {
    if (visibleMessages.length === 0) {
      shouldStickToBottomRef.current = true;
      lastMessageScrollKeyRef.current = messageScrollKey;
      lastStreamingRef.current = isStreaming;
      return;
    }

    const messageChanged = lastMessageScrollKeyRef.current !== messageScrollKey;
    const streamingStarted = isStreaming && !lastStreamingRef.current;
    if (streamingStarted) {
      shouldStickToBottomRef.current = true;
    }
    if (messageChanged && (streamingStarted || shouldStickToBottomRef.current)) {
      scrollMessagesToBottom();
    }

    lastMessageScrollKeyRef.current = messageScrollKey;
    lastStreamingRef.current = isStreaming;
  }, [isStreaming, messageScrollKey, scrollMessagesToBottom, visibleMessages]);

  useEffect(() => {
    if (active && !wasActiveRef.current) {
      setEmptyAnimationKey((prev) => prev + 1);
    }
    wasActiveRef.current = active;
  }, [active]);

  useEffect(() => {
    if (!activeQuickChatThreadId || messages.length === 0) {
      return;
    }
    quickChatMessagesRef.current[activeQuickChatThreadId] = messages;
    cacheQuickChatMessages(activeQuickChatThreadId, messages);
    if (messagesSessionId) {
      bindQuickChatSession(activeQuickChatThreadId, messagesSessionId);
      cacheQuickChatMessages(messagesSessionId, messages);
    }
  }, [activeQuickChatThreadId, bindQuickChatSession, cacheQuickChatMessages, messages, messagesSessionId]);

  useEffect(() => {
    if (presentation !== "sidebar") {
      return;
    }
    setSidebarStreaming(isStreaming);
    return () => setSidebarStreaming(false);
  }, [isStreaming, presentation, setSidebarStreaming]);

  useEffect(() => {
    setDraft("");
    setSessions([]);
    setSessionsError(null);
    setSelectedSessionId(null);
    setSelectedChunkId(null);
    setPendingSelectionContext(null);
    setActiveQuickChatContext(null);
    pendingSelectionContextRef.current = null;
    pendingSelectionSubmittedRef.current = false;
    preferEmptySessionRef.current = false;
  }, [courseId]);

  useEffect(() => {
    if (!request) {
      return;
    }

    setComposerFocusKey((prev) => prev + 1);
    if (request.draft !== undefined) {
      setDraft(request.draft);
    }

    const selectedText = request.selectedText?.trim() ?? "";
    const requestSource = request.source?.trim() || "quick_chat";
    const requestAnchorId = request.anchorId?.trim() || null;
    const requestedClientThreadId = request.clientThreadId?.trim() ?? "";
    const existingQuickChatContext = activeQuickChatContextRef.current;
    const normalizedSelectedText = normalizeQuickChatSelectionText(selectedText);
    const isSameActiveQuickChatSelection = Boolean(
      normalizedSelectedText &&
      normalizeQuickChatSelectionText(existingQuickChatContext?.selectedText) === normalizedSelectedText &&
      existingQuickChatContext?.anchorId === requestAnchorId &&
      (existingQuickChatContext?.source || "quick_chat") === requestSource,
    );
    const effectiveClientThreadId =
      requestedClientThreadId ||
      (isSameActiveQuickChatSelection ? existingQuickChatContext?.clientThreadId?.trim() ?? "" : "");
    const mappedSessionId = getQuickChatSessionId(effectiveClientThreadId);
    const currentStreamingMessages =
      isStreaming &&
      messagesRef.current.length > 0 &&
      (
        isSameActiveQuickChatSelection ||
        Boolean(requestedClientThreadId && requestedClientThreadId === activeQuickChatThreadIdRef.current) ||
        Boolean(request.sessionId && request.sessionId === messagesSessionIdRef.current) ||
        Boolean(mappedSessionId && mappedSessionId === messagesSessionIdRef.current)
      )
        ? messagesRef.current
        : null;
    const activeStreamingSessionId =
      currentStreamingMessages
        ? messagesSessionIdRef.current ?? selectedSessionIdRef.current
        : null;
    const requestSessionId =
      request.sessionId === undefined
        ? undefined
        : request.sessionId?.trim() || null;
    const effectiveRequestSessionId =
      requestSessionId === undefined
        ? mappedSessionId ?? activeStreamingSessionId
        : requestSessionId ?? mappedSessionId ?? activeStreamingSessionId;
    const shouldOpenEmptySession =
      !effectiveRequestSessionId &&
      (
        request.sessionId === null ||
        Boolean(selectedText && (request.newSession ?? request.sessionId === undefined))
      );
    let restoredQuickChatMessages: ChatSessionMessage[] | null = null;

    if (shouldOpenEmptySession) {
      requestedSessionIdRef.current = null;
      preferEmptySessionRef.current = true;
      pendingSelectionSubmittedRef.current = false;
      setSelectedSessionId(null);
      setActiveConversationSessionId(null);
      const providerCachedMessages = getCachedQuickChatMessages(effectiveClientThreadId);
      const cachedMessages = effectiveClientThreadId ? quickChatMessagesRef.current[effectiveClientThreadId] : null;
      const currentThreadMessages =
        effectiveClientThreadId &&
        effectiveClientThreadId === activeQuickChatThreadIdRef.current &&
        messagesRef.current.length > 0
          ? messagesRef.current
          : null;
      restoredQuickChatMessages = currentStreamingMessages ?? currentThreadMessages ?? providerCachedMessages ?? cachedMessages ?? null;
      if (restoredQuickChatMessages?.length) {
        replaceMessages(restoredQuickChatMessages, activeStreamingSessionId ?? mappedSessionId ?? null);
      } else if (!isStreaming) {
        replaceMessages([], null);
      }
    } else {
      preferEmptySessionRef.current = false;
      pendingSelectionSubmittedRef.current = false;
      if (effectiveRequestSessionId !== undefined) {
        requestedSessionIdRef.current = effectiveRequestSessionId;
        setSelectedSessionId(effectiveRequestSessionId);
        setActiveConversationSessionId(effectiveRequestSessionId);
        const providerCachedMessages =
          getCachedQuickChatMessages(effectiveClientThreadId) ??
          getCachedQuickChatMessages(effectiveRequestSessionId);
        const currentThreadMessages =
          (
            effectiveClientThreadId &&
            effectiveClientThreadId === activeQuickChatThreadIdRef.current &&
            messagesRef.current.length > 0
          ) ||
          (
            effectiveRequestSessionId &&
            effectiveRequestSessionId === messagesSessionIdRef.current &&
            messagesRef.current.length > 0
          )
            ? messagesRef.current
            : null;
        restoredQuickChatMessages = currentStreamingMessages ?? currentThreadMessages ?? providerCachedMessages ?? null;
        if (restoredQuickChatMessages?.length) {
          replaceMessages(restoredQuickChatMessages, effectiveRequestSessionId);
        }
      }
    }

    if (selectedText) {
      const nextContext = {
        source: requestSource,
        anchorId: requestAnchorId,
        selectedText,
        selectionContext: request.selectionContext ?? null,
        clientThreadId: effectiveClientThreadId || null,
      };
      const hasRestoredQuickChatMessages = (restoredQuickChatMessages?.length ?? 0) > 0;
      const shouldShowSelectionContext =
        (request.showSelectionContext ?? shouldOpenEmptySession) && !hasRestoredQuickChatMessages;
      pendingSelectionContextRef.current = shouldShowSelectionContext ? nextContext : null;
      setActiveQuickChatContext(nextContext);
      if (shouldShowSelectionContext) {
        setPendingSelectionContext(nextContext);
      } else {
        setPendingSelectionContext(null);
      }
    } else {
      pendingSelectionContextRef.current = null;
      pendingSelectionSubmittedRef.current = false;
      setPendingSelectionContext(null);
      setActiveQuickChatContext(null);
    }
    // Apply once per open request key. React StrictMode replays effects in dev, so this
    // effect must be safe to run twice for the same request after scope reset runs.
  }, [request?.key]);

  useEffect(() => {
    pendingSelectionContextRef.current = pendingSelectionContext;
  }, [pendingSelectionContext]);

  useEffect(() => {
    if (!pendingSelectionContext || pendingSelectionSubmittedRef.current || !selectedSessionId) {
      return;
    }
    preferEmptySessionRef.current = true;
    setSelectedSessionId(null);
    setActiveConversationSessionId(null);
    replaceMessages([], null);
  }, [pendingSelectionContext, replaceMessages, selectedSessionId, setActiveConversationSessionId]);

  useEffect(() => {
    if (pendingSelectionContext || isStreaming || !pendingSelectionSubmittedRef.current) {
      return;
    }
    pendingSelectionSubmittedRef.current = false;
  }, [isStreaming, pendingSelectionContext]);

  useEffect(() => {
    if (!active || !courseId || isStreaming) {
      return;
    }
    void reloadSessions();
  }, [active, isStreaming, reloadSessions, sessionListVersion, courseId]);

  const handleStartNewSession = useCallback(() => {
    preferEmptySessionRef.current = true;
    setDraft("");
    setSelectedSessionId(null);
    setPendingSelectionContext(null);
    setActiveQuickChatContext(null);
    pendingSelectionContextRef.current = null;
    pendingSelectionSubmittedRef.current = false;
    requestedSessionIdRef.current = null;
    replaceMessages([], null);
    setActiveConversationSessionId(null);
  }, [replaceMessages, setActiveConversationSessionId]);

  async function handleSend() {
    const question = draft.trim();
    if (!question || !courseId || isStreaming || isPlannerConversation) {
      return;
    }

    const selectionContext = pendingSelectionContext ?? activeQuickChatContext;
    if (pendingSelectionContext) {
      pendingSelectionSubmittedRef.current = true;
    }
    setDraft("");
    const result = await sendMessage(
      {
        question,
        model: toChatRequestModel(chatModel),
        session_id: pendingSelectionContext ? undefined : selectedSessionId ?? undefined,
        source: selectionContext?.source,
        anchor_id: selectionContext?.anchorId,
        selected_text: selectionContext?.selectedText,
        selected_context: selectionContext?.selectedText,
        selection_context: selectionContext?.selectionContext,
      },
      {
        localThreadId: pendingSelectionContext?.clientThreadId ?? undefined,
      },
    );
    if (!result.accepted) {
      pendingSelectionSubmittedRef.current = false;
      setDraft(question);
      return;
    }
    if (pendingSelectionContext) {
      pendingSelectionContextRef.current = null;
      setPendingSelectionContext(null);
    }
    const nextSessionId = result.sessionId ?? selectedSessionId;
    if (nextSessionId) {
      preferEmptySessionRef.current = false;
      requestedSessionIdRef.current = nextSessionId;
      setSelectedSessionId(nextSessionId);
    }
    notifyConversationSessionsChanged();
    void reloadSessions(nextSessionId);
  }

  async function handleClearCurrentSession() {
    await clearHistory();
    notifyConversationSessionsChanged();
    void reloadSessions(selectedSessionId);
  }

  return (
    <div
      className={cn(
        "relative flex h-full min-h-0 w-full flex-col overflow-hidden bg-white dark:bg-slate-950",
        isFullscreen && "border border-zinc-200/80 shadow-sm dark:border-slate-800",
        className,
      )}
    >
      <div className="flex shrink-0 items-center justify-between border-b border-zinc-200/60 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-950">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {onClose ? (
            <>
              <button
                type="button"
                onClick={onClose}
                className="inline-flex h-8 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-2 text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
                aria-label="收起"
              >
                <ChevronRight className="h-4 w-4 shrink-0" />
                <span className="hidden whitespace-nowrap text-[13px] font-medium lg:inline">收起</span>
              </button>
              <div className="mx-1 h-4 w-px shrink-0 bg-slate-200 dark:bg-slate-800" />
            </>
          ) : null}

          <div className="min-w-0 flex-1 pr-2">
            <div className="flex min-w-0 items-center gap-2">
              <h2 className="truncate text-[14px] font-semibold tracking-tight text-zinc-900 dark:text-slate-100">
                {panelTitle}
              </h2>
              {currentSelectionTarget ? (
                <button
                  type="button"
                  onClick={() => jumpToSelectionTarget(currentSelectionTarget)}
                  className={cn(
                    "inline-flex h-7 shrink-0 items-center gap-1 rounded-md border px-2 text-[12px] font-medium transition",
                    currentSelectionTarget.kind === "exam_question"
                      ? "border-indigo-200 bg-indigo-50 text-indigo-700 hover:border-indigo-300 hover:bg-indigo-100 hover:text-indigo-800 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-200 dark:hover:bg-indigo-500/15"
                      : "border-amber-200 bg-amber-50 text-amber-700 hover:border-amber-300 hover:bg-amber-100 hover:text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200 dark:hover:bg-amber-500/15",
                  )}
                  title={`${currentSelectionTarget.kind === "exam_question" ? "定位题目" : "定位原文"}：${currentSelectionTarget.selectedText}`}
                  aria-label={currentSelectionTarget.kind === "exam_question" ? "定位题目" : "定位原文"}
                >
                  <MapPin className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">
                    {currentSelectionTarget.kind === "exam_question" ? "定位题目" : "定位原文"}
                  </span>
                </button>
              ) : null}
            </div>
            {currentSelectionTarget ? (
              <SelectionTextPreview
                prefix={currentSelectionTarget.kind === "exam_question" ? "题目：" : "划词："}
                text={currentSelectionTarget.selectedText}
                className="mt-0.5 hidden max-w-[32rem] text-[11px] text-zinc-400 dark:text-slate-500 md:block"
              />
            ) : null}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={handleStartNewSession}
            disabled={isStreaming}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 disabled:opacity-50 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
            aria-label="新建会话"
            title="新建会话"
          >
            <Plus className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => void handleClearCurrentSession()}
            disabled={!selectedSessionId || isStreaming}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 disabled:opacity-50 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
            aria-label="清空记录"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {historyError || sessionsError ? (
        <div className="shrink-0 border-b border-red-100 bg-red-50/80 px-4 py-2 text-[13px] text-red-600 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
          {historyError ?? sessionsError}
        </div>
      ) : null}

      <div
        ref={messageScrollRef}
        onScroll={handleMessageScroll}
        className="min-h-0 flex-1 overflow-y-auto pt-2"
      >
        {visibleMessages.length > 0 && (!selectedSessionId || currentHistoryLoaded || isStreaming) ? (
          <ChatTranscript
            messages={visibleMessages}
            onOpenCitation={handleOpenCitation}
          />
        ) : !selectedSessionId ? (
          <ConversationEmptyState
            animationKey={emptyAnimationKey}
            title="开始对话"
            description="直接从下方输入问题发送即可开始。系统会自动创建全新会话。"
          />
        ) : !currentHistoryLoaded ? (
          <div className="flex h-full items-center justify-center text-[13px] text-zinc-500 dark:text-slate-400">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            加载会话中...
          </div>
        ) : (
          <ConversationEmptyState
            animationKey={emptyAnimationKey}
            title="这个会话还没有消息"
            description="开始提问后，这里会展示你和 AITeachMe 的对话记录。"
          />
        )}
      </div>

      <div className="shrink-0 border-t border-transparent bg-white dark:bg-slate-950">
        {isPlannerConversation ? (
          <div className="border-t border-amber-100 bg-amber-50/80 px-4 py-2 text-[12px] leading-relaxed text-amber-700">
            这是构建规划会话，可在这里回看；继续修改规划请回到构建页操作。
          </div>
        ) : null}
        {pendingSelectionContext ? (
          <div className="mx-auto max-w-3xl px-4 pt-3 md:px-8 xl:max-w-4xl 2xl:max-w-5xl">
            <div
              className={cn(
                "flex items-start gap-2 rounded-2xl border px-3 py-2.5 shadow-sm",
                pendingSelectionContext.source === AI_SOURCE_EXAM_QUESTION
                  ? "border-indigo-100 bg-indigo-50/80 text-indigo-950 dark:border-indigo-500/20 dark:bg-indigo-500/10 dark:text-indigo-100"
                  : "border-indigo-100 bg-indigo-50/80 text-indigo-950 dark:border-indigo-500/20 dark:bg-indigo-500/10 dark:text-indigo-100",
              )}
            >
              <MessageSquareText
                className={cn(
                  "mt-0.5 h-4 w-4 shrink-0",
                  pendingSelectionContext.source === AI_SOURCE_EXAM_QUESTION ? "text-indigo-600" : "text-indigo-600",
                )}
              />
              <div className="min-w-0 flex-1">
                <p className="text-[12px] font-semibold">
                  {pendingSelectionContext.source === AI_SOURCE_EXAM_QUESTION ? "已附加这道题的上下文" : "已附加原文与相关上下文"}
                </p>
                <p
                  className={cn(
                    "mt-0.5 text-[11px] leading-4",
                    pendingSelectionContext.source === AI_SOURCE_EXAM_QUESTION
                      ? "text-indigo-600 dark:text-indigo-200/80"
                      : "text-indigo-600 dark:text-indigo-200/80",
                  )}
                >
                  {pendingSelectionContext.source === AI_SOURCE_EXAM_QUESTION
                    ? "将结合题干、选项和当前作答状态回答；未批改时不会主动泄露标准答案。"
                    : "将结合选中片段、所在段落和相关资料回答。"}
                </p>
                <SelectionTextPreview
                  prefix={pendingSelectionContext.source === AI_SOURCE_EXAM_QUESTION ? "题目：" : "选中："}
                  text={pendingSelectionContext.selectedText}
                  placement="above"
                  className={cn(
                    "mt-1 text-[12px] leading-5",
                    pendingSelectionContext.source === AI_SOURCE_EXAM_QUESTION
                      ? "text-indigo-700 dark:text-indigo-100/90"
                      : "text-indigo-700 dark:text-indigo-100/90",
                  )}
                />
              </div>
              <button
                type="button"
                onClick={() => setPendingSelectionContext(null)}
                className={cn(
                  "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg transition",
                  pendingSelectionContext.source === AI_SOURCE_EXAM_QUESTION
                    ? "text-indigo-500 hover:bg-indigo-100 hover:text-indigo-800"
                    : "text-indigo-500 hover:bg-indigo-100 hover:text-indigo-800",
                )}
                aria-label="移除参考上下文"
                title="移除参考上下文"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        ) : null}
        <ChatComposer
          value={draft}
          onChange={setDraft}
          onSend={() => void handleSend()}
          onAbort={abortStream}
          isStreaming={isStreaming}
          disabled={!courseId || isPlannerConversation}
          autoFocusKey={composerFocusKey}
          modelValue={chatModel}
          onModelChange={setChatModel}
          placeholder={pendingSelectionContext ? (
            pendingSelectionContext.source === AI_SOURCE_EXAM_QUESTION ? "围绕这道题提问..." : "结合原文上下文提问..."
          ) : undefined}
        />
      </div>

      <ChatCitationModal
        open={selectedChunkId !== null}
        onClose={() => setSelectedChunkId(null)}
        course={courseId ?? ""}
        chunkId={selectedChunkId}
      />
    </div>
  );
});
