import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";

import { apiClient, getApiErrorMessage } from "../../../api/client";
import type {
  ApiResponsePaginatedDataChatSessionItem,
  ChatSendRequest,
  ChatSessionItem,
} from "../../../api/generated/model";
import { type ChatClientAction, type ChatSessionMessage, useChatSession } from "../../../hooks/useChatSession";
import { buildCoursePath, buildCourseSubPath, isCourseRouteActive } from "../../../lib/courseNavigation";
import { cn } from "../../../lib/utils";
import { ChatCitationModal } from "../../chat/ChatCitationModal";
import {
  DEFAULT_CHAT_MODEL_CHOICE,
  type ChatModelChoice,
  toChatModelChoice,
  toChatRequestModel,
} from "../../chat/ChatModelSelect";
import { AiConversationComposerDock } from "./AiConversationComposerDock";
import { AiConversationHeader } from "./AiConversationHeader";
import { AiConversationMessageView } from "./AiConversationMessageView";
import type { ChatSessionSelectionTarget, PendingSelectionContext } from "./AiConversationTypes";
import { useAiInteraction } from "../AiInteractionProvider";
import type { AiConversationScope, AiInteractionOpenRequest, ExamQuestionJumpDetail } from "../types";
import {
  AI_SOURCE_DOCUMENT_SELECTION,
  AI_SOURCE_EXAM_QUESTION,
  EXAM_QUESTION_JUMP_EVENT,
  getAiConversationBackendCourseId,
  parseExamQuestionAnchorId,
} from "../types";

interface AiConversationViewProps {
  scope: AiConversationScope | null;
  request?: AiInteractionOpenRequest | null;
  active: boolean;
  presentation: "sidebar" | "fullscreen";
  onClose?: () => void;
  className?: string;
}

type QuickChatSyncPhase = "start" | "session" | "token" | "done" | "error" | "settled";

interface QuickChatInputContext {
  source: string;
  anchorId: string;
  selectedText: string;
}

interface PendingAutoSendRequest {
  key: number;
  question: string;
  model: string | null;
  source: string | null;
  attachedFileIds: string[];
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function getClientActionPayload(action: ChatClientAction): Record<string, unknown> {
  return isRecord(action.payload) ? action.payload : {};
}

function payloadString(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function payloadBoolean(payload: Record<string, unknown>, key: string): boolean | null {
  const value = payload[key];
  return typeof value === "boolean" ? value : null;
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

export const AiConversationView = memo(function AiConversationView({
  scope,
  request,
  active,
  presentation,
  onClose,
  className,
}: AiConversationViewProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
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
  const [pendingAutoSendRequest, setPendingAutoSendRequest] = useState<PendingAutoSendRequest | null>(null);
  const [activeQuickChatContext, setActiveQuickChatContext] = useState<PendingSelectionContext | null>(null);
  const [composerFocusKey, setComposerFocusKey] = useState(0);
  const [emptyAnimationKey, setEmptyAnimationKey] = useState(0);
  const preferEmptySessionRef = useRef(false);
  const wasActiveRef = useRef(false);
  const pendingSelectionContextRef = useRef<PendingSelectionContext | null>(null);
  const pendingSelectionSubmittedRef = useRef(false);
  const autoSentRequestKeysRef = useRef<Set<number>>(new Set());
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

  const handleClientActions = useCallback((actions: ChatClientAction[]) => {
    const action = actions.find((item) => item.type === "open_build_planner");
    if (!action) {
      return;
    }
    const payload = getClientActionPayload(action);
    const nextCourseId = payloadString(payload, "course_id");
    if (!nextCourseId) {
      return;
    }

    const initialPrompt = payloadString(payload, "initial_prompt") ?? undefined;
    const model = payloadString(payload, "model") ?? toChatRequestModel(chatModel);
    void queryClient.invalidateQueries({ queryKey: ["courses"] });
    void queryClient.invalidateQueries({ queryKey: ["files", nextCourseId] });
    navigate(buildCoursePath(nextCourseId, "build"), {
      state: {
        initialPrompt,
        autoStart: payloadBoolean(payload, "auto_start") ?? Boolean(initialPrompt),
        model,
      },
    });
  }, [chatModel, navigate, queryClient]);

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
      handleClientActions(payload.clientActions);
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
    setPendingAutoSendRequest(null);
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
    if (request.model !== undefined) {
      setChatModel(toChatModelChoice(request.model));
    }
    if (request.autoSend && request.draft?.trim()) {
      setPendingAutoSendRequest({
        key: request.key,
        question: request.draft.trim(),
        model: request.model?.trim() || null,
        source: request.source?.trim() || null,
        attachedFileIds: Array.from(new Set((request.attachedFileIds ?? []).map((item) => item.trim()).filter(Boolean))),
      });
    } else {
      setPendingAutoSendRequest(null);
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

  const sendAutoRequest = useCallback(async (autoRequest: PendingAutoSendRequest) => {
    if (!courseId || isStreaming || isPlannerConversation) {
      return;
    }
    if (autoSentRequestKeysRef.current.has(autoRequest.key)) {
      return;
    }

    autoSentRequestKeysRef.current.add(autoRequest.key);
    setDraft("");
    const requestModel =
      autoRequest.model && autoRequest.model !== DEFAULT_CHAT_MODEL_CHOICE
        ? autoRequest.model
        : toChatRequestModel(chatModel);
    const result = await sendMessage({
      question: autoRequest.question,
      model: requestModel,
      session_id: undefined,
      source: autoRequest.source,
      attached_file_ids: autoRequest.attachedFileIds,
    });
    if (!result.accepted) {
      autoSentRequestKeysRef.current.delete(autoRequest.key);
      setDraft(autoRequest.question);
      return;
    }

    const nextSessionId = result.sessionId ?? null;
    if (nextSessionId) {
      preferEmptySessionRef.current = false;
      requestedSessionIdRef.current = nextSessionId;
      setSelectedSessionId(nextSessionId);
      setActiveConversationSessionId(nextSessionId);
    }
    setPendingAutoSendRequest(null);
    notifyConversationSessionsChanged();
    void reloadSessions(nextSessionId);
  }, [
    chatModel,
    courseId,
    isPlannerConversation,
    isStreaming,
    notifyConversationSessionsChanged,
    reloadSessions,
    sendMessage,
    setActiveConversationSessionId,
  ]);

  useEffect(() => {
    if (!pendingAutoSendRequest) {
      return;
    }
    void sendAutoRequest(pendingAutoSendRequest);
  }, [pendingAutoSendRequest, sendAutoRequest]);

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
        "relative flex h-full min-h-0 w-full flex-col overflow-hidden",
        isFullscreen ? "bg-transparent" : "bg-white dark:bg-slate-950",
        isFullscreen && "border border-zinc-200/80 shadow-sm dark:border-slate-800",
        className,
      )}
    >
      <AiConversationHeader
        title={panelTitle}
        selectionTarget={currentSelectionTarget}
        onClose={onClose}
        onStartNewSession={handleStartNewSession}
        onClearCurrentSession={() => void handleClearCurrentSession()}
        onJumpToSelectionTarget={jumpToSelectionTarget}
        isStreaming={isStreaming}
        selectedSessionId={selectedSessionId}
      />

      {historyError || sessionsError ? (
        <div className="shrink-0 border-b border-red-100 bg-red-50/80 px-4 py-2 text-[13px] text-red-600 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
          {historyError ?? sessionsError}
        </div>
      ) : null}

      <AiConversationMessageView
        scrollRef={messageScrollRef}
        onScroll={handleMessageScroll}
        messages={visibleMessages}
        selectedSessionId={selectedSessionId}
        historyLoaded={currentHistoryLoaded}
        isStreaming={isStreaming}
        emptyAnimationKey={emptyAnimationKey}
        onOpenCitation={handleOpenCitation}
      />

      <AiConversationComposerDock
        draft={draft}
        onDraftChange={setDraft}
        onSend={() => void handleSend()}
        onAbort={abortStream}
        isStreaming={isStreaming}
        disabled={!courseId || isPlannerConversation}
        autoFocusKey={composerFocusKey}
        modelValue={chatModel}
        onModelChange={setChatModel}
        isPlannerConversation={isPlannerConversation}
        pendingSelectionContext={pendingSelectionContext}
        onClearPendingSelectionContext={() => setPendingSelectionContext(null)}
      />

      <ChatCitationModal
        open={selectedChunkId !== null}
        onClose={() => setSelectedChunkId(null)}
        course={courseId ?? ""}
        chunkId={selectedChunkId}
      />
    </div>
  );
});
