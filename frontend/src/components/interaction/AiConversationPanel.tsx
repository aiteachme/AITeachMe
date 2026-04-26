import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { cn } from "../../lib/utils";
import { ChatCitationModal } from "../chat/ChatCitationModal";
import { ChatComposer } from "../chat/ChatComposer";
import { ChatTranscript } from "../chat/ChatTranscript";
import { HeroAnimation } from "../ui/HeroAnimation";
import { useAiInteraction } from "./AiInteractionProvider";
import type { AiConversationScope, AiInteractionOpenRequest } from "./types";
import { getAiConversationBackendSubjectId } from "./types";

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

type QuickChatSyncPhase = "start" | "token" | "done" | "error" | "settled";

interface QuickChatInputContext {
  source: string;
  anchorId: string;
  selectedText: string;
}

interface ChatSessionSelectionTarget {
  sessionId: string | null;
  anchorId: string;
  selectedText: string;
}

const QUICK_CHAT_UPDATED_EVENT = "aiteachme:quick-chat-updated";
const SELECTION_JUMP_EVENT = "aiteachme:selection-jump";

function getQuickChatInputContext(input: ChatSendRequest): QuickChatInputContext | null {
  const source = input.source?.trim() ?? "";
  const anchorId = input.anchor_id?.trim() ?? "";
  const selectedText = input.selected_text?.trim() ?? input.selection_context?.selected_text?.trim() ?? "";
  if (source !== "quick_chat" || !anchorId || !selectedText) {
    return null;
  }
  return { source, anchorId, selectedText };
}

function getSessionSelectionTarget(session: ChatSessionItem | null): ChatSessionSelectionTarget | null {
  if (!session) {
    return null;
  }
  const anchorId = session.anchor_id?.trim() ?? "";
  const selectedText = session.selected_text?.trim() ?? "";
  if (session.source !== "quick_chat" || !anchorId || !selectedText) {
    return null;
  }
  return {
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
  return {
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
    notifyConversationSessionsChanged,
  } = useAiInteraction();
  const subjectId = getAiConversationBackendSubjectId(scope);
  const docsSubjectId = scope?.type === "subject" ? scope.subjectId : null;
  const isKnowledgeDocsPage = Boolean(docsSubjectId && /^\/subject\/[^/]+\/knowledge-docs$/.test(pathname));

  const [draft, setDraft] = useState("");
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
  const activeQuickChatThreadIdRef = useRef("");

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
    if (!docsSubjectId) {
      return;
    }
    const quickChatContext = getQuickChatInputContext(payload.input);
    if (!quickChatContext) {
      return;
    }
    window.dispatchEvent(new CustomEvent(QUICK_CHAT_UPDATED_EVENT, {
      detail: {
        phase,
        subjectId: docsSubjectId,
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
  }, [docsSubjectId]);

  const applyResolvedSessionTitle = useCallback((sessionId: string | null, title: string | null) => {
    const nextTitle = title?.trim();
    if (!sessionId || !nextTitle) {
      return;
    }
    setSessions((current) =>
      current.map((item) => (getChatSessionItemId(item) === sessionId ? { ...item, title: nextTitle } : item)),
    );
  }, []);

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
  } = useChatSession(subjectId ?? "", {
    sessionId: selectedSessionId,
    enabled: active && Boolean(subjectId),
    loadWithoutSession: false,
    preserveMessagesWithoutSession: true,
    onSessionResolved: (nextSessionId) => {
      preferEmptySessionRef.current = false;
      setSelectedSessionId(nextSessionId);
      void reloadSessions(nextSessionId);
    },
    onMessageStart: (payload) => dispatchQuickChatSync("start", payload),
    onMessageToken: (payload) => dispatchQuickChatSync("token", payload),
    onMessageDone: (payload) => {
      applyResolvedSessionTitle(payload.sessionId, payload.sessionTitle);
      dispatchQuickChatSync("done", payload);
      notifyConversationSessionsChanged();
    },
    onMessageError: (payload) => dispatchQuickChatSync("error", payload),
    onMessageSettled: (payload) => dispatchQuickChatSync("settled", payload),
  });

  const selectedSession = useMemo(
    () => sessions.find((item) => getChatSessionItemId(item) === selectedSessionId) ?? null,
    [selectedSessionId, sessions],
  );
  const isPlannerConversation = selectedSession?.source === "build_planner";
  const isFullscreen = presentation === "fullscreen";
  const currentMessagesSessionId = selectedSessionId ?? null;
  const messagesBelongToCurrentSession = messagesSessionId === currentMessagesSessionId;
  const visibleMessages = messagesBelongToCurrentSession ? messages : [];
  const currentHistoryLoaded = historyLoaded && messagesBelongToCurrentSession;
  const panelTitle = selectedSession?.title ?? (
    selectedSessionId
      ? "加载会话..."
      : pendingSelectionContext || activeQuickChatContext
        ? "划词提问"
        : "新会话"
  );
  const activeQuickChatThreadId = activeQuickChatContext?.clientThreadId?.trim() ?? "";
  const currentSelectionTarget = useMemo(
    () => getSessionSelectionTarget(selectedSession) ?? getContextSelectionTarget(activeQuickChatContext),
    [activeQuickChatContext, selectedSession],
  );
  const handleOpenCitation = useCallback((chunkId: number) => {
    setSelectedChunkId(chunkId);
  }, []);

  const jumpToSelectionTarget = useCallback((target: ChatSessionSelectionTarget | null) => {
    if (!docsSubjectId || !target) {
      return;
    }
    const detail = {
      subjectId: docsSubjectId,
      sessionId: target.sessionId,
      anchorId: target.anchorId,
      selectedText: target.selectedText,
    };
    if (!isKnowledgeDocsPage) {
      navigate(`/subject/${docsSubjectId}/knowledge-docs`, {
        state: {
          selectionJump: detail,
          selectionJumpAt: Date.now(),
        },
      });
      return;
    }
    window.dispatchEvent(new CustomEvent(SELECTION_JUMP_EVENT, { detail }));
  }, [docsSubjectId, isKnowledgeDocsPage, navigate]);

  const reloadSessions = useCallback(async (preferredSessionId?: string | null) => {
    if (!subjectId) {
      setSessions([]);
      setSelectedSessionId(null);
      return;
    }

    setSessionsError(null);
    try {
      const res = await apiClient<ApiResponsePaginatedDataChatSessionItem>({
        method: "POST",
        url: `/api/v1/subjects/${subjectId}/chats/sessions/list`,
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
        if (preferEmptySessionRef.current || pendingSelectionContextRef.current) {
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
  }, [request?.sessionId, subjectId]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    activeQuickChatThreadIdRef.current = activeQuickChatThreadId;
  }, [activeQuickChatThreadId]);

  useEffect(() => {
    if (active) {
      setActiveConversationSessionId(selectedSessionId);
    }
  }, [active, selectedSessionId, setActiveConversationSessionId]);

  useEffect(() => {
    if (!active) {
      abortStream();
    }
  }, [abortStream, active]);

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
  }, [activeQuickChatThreadId, messages]);

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
  }, [subjectId]);

  useEffect(() => {
    if (!request) {
      return;
    }

    setComposerFocusKey((prev) => prev + 1);
    if (request.draft !== undefined) {
      setDraft(request.draft);
    }

    const selectedText = request.selectedText?.trim() ?? "";
    const shouldOpenEmptySession =
      request.sessionId === null ||
      Boolean(selectedText && (request.newSession ?? request.sessionId === undefined));

    if (shouldOpenEmptySession) {
      requestedSessionIdRef.current = null;
      preferEmptySessionRef.current = true;
      pendingSelectionSubmittedRef.current = false;
      setSelectedSessionId(null);
      setActiveConversationSessionId(null);
      const clientThreadId = request.clientThreadId?.trim() ?? "";
      const cachedMessages = clientThreadId ? quickChatMessagesRef.current[clientThreadId] : null;
      const currentThreadMessages =
        clientThreadId &&
        clientThreadId === activeQuickChatThreadIdRef.current &&
        messagesRef.current.length > 0
          ? messagesRef.current
          : null;
      replaceMessages(cachedMessages ?? currentThreadMessages ?? [], null);
    } else {
      preferEmptySessionRef.current = false;
      pendingSelectionSubmittedRef.current = false;
      if (request.sessionId !== undefined) {
        requestedSessionIdRef.current = request.sessionId;
        setSelectedSessionId(request.sessionId);
      }
    }

    if (selectedText) {
      const nextContext = {
        source: request.source?.trim() || "quick_chat",
        anchorId: request.anchorId?.trim() || null,
        selectedText,
        selectionContext: request.selectionContext ?? null,
        clientThreadId: request.clientThreadId?.trim() || null,
      };
      const shouldShowSelectionContext = request.showSelectionContext ?? shouldOpenEmptySession;
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
    if (!active || !subjectId) {
      return;
    }
    void reloadSessions();
  }, [active, reloadSessions, sessionListVersion, subjectId]);

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
    if (!question || !subjectId || isStreaming || isPlannerConversation) {
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
      pendingSelectionSubmittedRef.current = false;
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
                  className="inline-flex h-7 shrink-0 items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-2 text-[12px] font-medium text-amber-700 transition hover:border-amber-300 hover:bg-amber-100 hover:text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200 dark:hover:bg-amber-500/15"
                  title={`定位原文：${currentSelectionTarget.selectedText}`}
                  aria-label="定位原文"
                >
                  <MapPin className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">定位原文</span>
                </button>
              ) : null}
            </div>
            {currentSelectionTarget ? (
              <SelectionTextPreview
                prefix="划词："
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

      <div className="min-h-0 flex-1 overflow-y-auto pt-2">
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
            <div className="flex items-start gap-2 rounded-2xl border border-sky-100 bg-sky-50/80 px-3 py-2.5 text-sky-900 shadow-sm dark:border-sky-500/20 dark:bg-sky-500/10 dark:text-sky-100">
              <MessageSquareText className="mt-0.5 h-4 w-4 shrink-0 text-sky-600" />
              <div className="min-w-0 flex-1">
                <p className="text-[12px] font-semibold">已附加原文与相关上下文</p>
                <p className="mt-0.5 text-[11px] leading-4 text-sky-600 dark:text-sky-200/80">
                  将结合选中片段、所在段落和相关资料回答。
                </p>
                <SelectionTextPreview
                  prefix="选中："
                  text={pendingSelectionContext.selectedText}
                  placement="above"
                  className="mt-1 text-[12px] leading-5 text-sky-700 dark:text-sky-100/90"
                />
              </div>
              <button
                type="button"
                onClick={() => setPendingSelectionContext(null)}
                className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-sky-500 transition hover:bg-sky-100 hover:text-sky-800"
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
          disabled={!subjectId || isPlannerConversation}
          autoFocusKey={composerFocusKey}
          placeholder={pendingSelectionContext ? "结合原文上下文提问..." : undefined}
        />
      </div>

      <ChatCitationModal
        open={selectedChunkId !== null}
        onClose={() => setSelectedChunkId(null)}
        subject={subjectId ?? ""}
        chunkId={selectedChunkId}
      />
    </div>
  );
});
