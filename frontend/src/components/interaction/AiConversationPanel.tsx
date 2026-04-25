import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronRight,
  Loader2,
  MapPin,
  MessageSquareText,
  PanelLeft,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import { apiClient, getApiErrorMessage } from "../../api/client";
import type {
  ApiResponseChatSessionCreateData,
  ApiResponsePaginatedDataChatSessionItem,
  ChatSelectionContext,
  ChatSendRequest,
  ChatSessionItem,
} from "../../api/generated/model";
import { type ChatSessionMessage, useChatSession } from "../../hooks/useChatSession";
import { cn } from "../../lib/utils";
import { publicAssetPath } from "../../lib/publicAsset";
import { ChatCitationModal } from "../chat/ChatCitationModal";
import { ChatComposer } from "../chat/ChatComposer";
import { ChatTranscript } from "../chat/ChatTranscript";
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

const LOGO_SRC = publicAssetPath("logo.svg");
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

export function AiConversationPanel({
  scope,
  request,
  active,
  presentation,
  onClose,
  className,
}: AiConversationPanelProps) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const subjectId = getAiConversationBackendSubjectId(scope);
  const docsSubjectId = scope?.type === "subject" ? scope.subjectId : null;
  const isKnowledgeDocsPage = Boolean(docsSubjectId && /^\/subject\/[^/]+\/knowledge-docs$/.test(pathname));

  const [draft, setDraft] = useState("");
  const [sessions, setSessions] = useState<ChatSessionItem[]>([]);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [isSessionDrawerOpen, setIsSessionDrawerOpen] = useState(false);
  const [selectedChunkId, setSelectedChunkId] = useState<number | null>(null);
  const [pendingSelectionContext, setPendingSelectionContext] = useState<PendingSelectionContext | null>(null);
  const [activeQuickChatContext, setActiveQuickChatContext] = useState<PendingSelectionContext | null>(null);
  const [composerFocusKey, setComposerFocusKey] = useState(0);
  const preferEmptySessionRef = useRef(false);
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
      current.map((item) => (item.id === sessionId ? { ...item, title: nextTitle } : item)),
    );
  }, []);

  const {
    messages,
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
    },
    onMessageError: (payload) => dispatchQuickChatSync("error", payload),
    onMessageSettled: (payload) => dispatchQuickChatSync("settled", payload),
  });

  const selectedSession = useMemo(
    () => sessions.find((item) => item.id === selectedSessionId) ?? null,
    [selectedSessionId, sessions],
  );
  const isPlannerConversation = selectedSession?.source === "build_planner";
  const isFullscreen = presentation === "fullscreen";
  const activeQuickChatThreadId = activeQuickChatContext?.clientThreadId?.trim() ?? "";
  const currentSelectionTarget = useMemo(
    () => getSessionSelectionTarget(selectedSession) ?? getContextSelectionTarget(activeQuickChatContext),
    [activeQuickChatContext, selectedSession],
  );

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
      setSessionsLoaded(true);
      return;
    }

    setSessionsLoaded(false);
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
      setSessions(items);
      setSelectedSessionId((current) => {
        if (preferredSessionId && items.some((item) => item.id === preferredSessionId)) {
          return preferredSessionId;
        }
        if (current && items.some((item) => item.id === current)) {
          return current;
        }
        if (preferEmptySessionRef.current) {
          return null;
        }
        return items[0]?.id ?? null;
      });
    } catch (error: unknown) {
      setSessionsError(getApiErrorMessage(error, "加载会话历史失败"));
    } finally {
      setSessionsLoaded(true);
    }
  }, [subjectId]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    activeQuickChatThreadIdRef.current = activeQuickChatThreadId;
  }, [activeQuickChatThreadId]);

  useEffect(() => {
    if (!activeQuickChatThreadId || messages.length === 0) {
      return;
    }
    quickChatMessagesRef.current[activeQuickChatThreadId] = messages;
  }, [activeQuickChatThreadId, messages]);

  useEffect(() => {
    setDraft("");
    setSessions([]);
    setSessionsLoaded(false);
    setSessionsError(null);
    setSelectedSessionId(null);
    setIsSessionDrawerOpen(false);
    setSelectedChunkId(null);
    setPendingSelectionContext(null);
    setActiveQuickChatContext(null);
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
      preferEmptySessionRef.current = true;
      setSelectedSessionId(null);
      const clientThreadId = request.clientThreadId?.trim() ?? "";
      const cachedMessages = clientThreadId ? quickChatMessagesRef.current[clientThreadId] : null;
      const currentThreadMessages =
        clientThreadId &&
        clientThreadId === activeQuickChatThreadIdRef.current &&
        messagesRef.current.length > 0
          ? messagesRef.current
          : null;
      replaceMessages(cachedMessages ?? currentThreadMessages ?? []);
    } else {
      preferEmptySessionRef.current = false;
      if (request.sessionId !== undefined) {
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
      setActiveQuickChatContext(nextContext);
      if (request.showSelectionContext ?? shouldOpenEmptySession) {
        setPendingSelectionContext(nextContext);
      } else {
        setPendingSelectionContext(null);
      }
    } else {
      setPendingSelectionContext(null);
      setActiveQuickChatContext(null);
    }
  }, [request, replaceMessages]);

  useEffect(() => {
    if (!active || !subjectId) {
      return;
    }
    void reloadSessions();
  }, [active, reloadSessions, subjectId]);

  async function handleCreateSession() {
    if (!subjectId) {
      return;
    }
    try {
      const res = await apiClient<ApiResponseChatSessionCreateData>({
        method: "POST",
        url: `/api/v1/subjects/${subjectId}/chats/sessions/create`,
        data: {},
      });
      const created = res.data?.session;
      if (!created) {
        throw new Error("创建会话成功，但响应缺少 session 数据。");
      }
      preferEmptySessionRef.current = false;
      setSessions((prev) => [created, ...prev.filter((item) => item.id !== created.id)]);
      setSelectedSessionId(created.id);
      setPendingSelectionContext(null);
      setActiveQuickChatContext(null);
      setSessionsError(null);
      setIsSessionDrawerOpen(false);
    } catch (error: unknown) {
      setSessionsError(getApiErrorMessage(error, "创建会话失败"));
    }
  }

  async function handleDeleteSession(sessionId: string) {
    if (!subjectId) {
      return;
    }
    try {
      await apiClient({
        method: "POST",
        url: `/api/v1/subjects/${subjectId}/chats/sessions/delete`,
        data: {
          session_id: sessionId,
        },
      });
      const nextSessions = sessions.filter((item) => item.id !== sessionId);
      setSessions(nextSessions);
      if (selectedSessionId === sessionId) {
        setSelectedSessionId(nextSessions[0]?.id ?? null);
      }
      setSessionsError(null);
    } catch (error: unknown) {
      setSessionsError(getApiErrorMessage(error, "删除会话失败"));
    }
  }

  const selectHistorySession = useCallback((item: ChatSessionItem) => {
    preferEmptySessionRef.current = false;
    setSelectedSessionId(item.id);
    setPendingSelectionContext(null);
    const selectionTarget = getSessionSelectionTarget(item);
    setActiveQuickChatContext(selectionTarget
      ? {
        source: "quick_chat",
        anchorId: selectionTarget.anchorId,
        selectedText: selectionTarget.selectedText,
        selectionContext: null,
        clientThreadId: null,
      }
      : null);
  }, []);

  const locateHistorySession = useCallback((item: ChatSessionItem, target: ChatSessionSelectionTarget) => {
    selectHistorySession(item);
    setIsSessionDrawerOpen(false);
    jumpToSelectionTarget(target);
  }, [jumpToSelectionTarget, selectHistorySession]);

  async function handleSend() {
    const question = draft.trim();
    if (!question || !subjectId || isStreaming || isPlannerConversation) {
      return;
    }

    const selectionContext = pendingSelectionContext ?? activeQuickChatContext;
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
      setDraft(question);
      return;
    }
    if (pendingSelectionContext) {
      setPendingSelectionContext(null);
    }
    const nextSessionId = result.sessionId ?? selectedSessionId;
    if (nextSessionId) {
      preferEmptySessionRef.current = false;
      setSelectedSessionId(nextSessionId);
    }
    void reloadSessions(nextSessionId);
  }

  async function handleClearCurrentSession() {
    await clearHistory();
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
        <div className="flex min-w-0 items-center gap-2">
          {onClose ? (
            <>
              <button
                type="button"
                onClick={onClose}
                className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md px-2 text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
                aria-label="收起"
              >
                <ChevronRight className="h-4 w-4" />
                <span className="hidden text-[13px] font-medium lg:inline">收起</span>
              </button>
              <div className="mx-1 h-4 w-px bg-slate-200 dark:bg-slate-800" />
            </>
          ) : null}

          <button
            type="button"
            onClick={() => setIsSessionDrawerOpen(!isSessionDrawerOpen)}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-zinc-200/60 bg-white text-zinc-600 shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition hover:bg-zinc-50 hover:text-zinc-900 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100"
            aria-label="打开会话列表"
          >
            <PanelLeft className="h-4 w-4" />
          </button>
          <div className="min-w-0 pr-2">
            <div className="flex min-w-0 items-center gap-2">
              <h2 className="truncate text-[14px] font-semibold tracking-tight text-zinc-900 dark:text-slate-100">
                {selectedSession?.title ?? "新会话"}
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
              <p className="mt-0.5 hidden max-w-[32rem] truncate text-[11px] text-zinc-400 dark:text-slate-500 md:block">
                划词：{currentSelectionTarget.selectedText}
              </p>
            ) : null}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1">
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

      {historyError ? (
        <div className="shrink-0 border-b border-red-100 bg-red-50/80 px-4 py-2 text-[13px] text-red-600 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
          {historyError}
        </div>
      ) : null}

      <div className="min-h-0 flex-1 overflow-y-auto pt-2">
        {messages.length > 0 && (!selectedSessionId || historyLoaded || isStreaming) ? (
          <ChatTranscript
            messages={messages}
            onOpenCitation={(chunkId) => setSelectedChunkId(chunkId)}
          />
        ) : !selectedSessionId ? (
          <div className="flex h-full items-center justify-center px-6">
            <div className="max-w-md text-center">
              <div className="mx-auto inline-flex h-14 w-14 items-center justify-center rounded-xl border border-zinc-200/60 bg-white p-2 text-zinc-600 shadow-sm dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
                <img src={LOGO_SRC} alt="AI" className="h-full w-full object-contain" />
              </div>
              <h3 className="mt-5 text-[17px] font-semibold tracking-tight text-zinc-900 dark:text-slate-100">
                开始对话
              </h3>
              <p className="mt-2 text-[13px] leading-relaxed text-zinc-500 dark:text-slate-400">
                直接从下方输入问题发送即可开始。系统会自动创建全新会话。
              </p>
            </div>
          </div>
        ) : !historyLoaded ? (
          <div className="flex h-full items-center justify-center text-[13px] text-zinc-500 dark:text-slate-400">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            加载会话中...
          </div>
        ) : (
          <div className="flex h-full flex-col items-center justify-center px-6 text-center">
            <MessageSquareText className="mb-3 h-8 w-8 text-zinc-300 dark:text-slate-600" />
            <p className="text-[13px] text-zinc-500 dark:text-slate-400">
              这个会话还没有消息
              <br />
              开始提问吧
            </p>
          </div>
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
            <div className="flex items-start gap-2 rounded-2xl border border-sky-100 bg-sky-50/80 px-3 py-2.5 text-sky-900 shadow-sm">
              <MessageSquareText className="mt-0.5 h-4 w-4 shrink-0 text-sky-600" />
              <div className="min-w-0 flex-1">
                <p className="text-[12px] font-semibold">已带入划词上下文</p>
                <p className="mt-1 line-clamp-2 text-[12px] leading-5 text-sky-700">
                  {pendingSelectionContext.selectedText}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setPendingSelectionContext(null)}
                className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-sky-500 transition hover:bg-sky-100 hover:text-sky-800"
                aria-label="移除划词上下文"
                title="移除划词上下文"
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
          placeholder={pendingSelectionContext ? "围绕选中的这段内容提问..." : undefined}
        />
      </div>

      <div
        className={cn(
          "absolute inset-0 z-20 bg-slate-900/14 transition-opacity duration-300 dark:bg-black/45",
          isSessionDrawerOpen ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0",
        )}
        onClick={() => setIsSessionDrawerOpen(false)}
      />
      <aside
        className={cn(
          "absolute bottom-0 left-0 top-0 z-30 flex w-[304px] flex-col border-r border-zinc-200/80 bg-white/96 shadow-[8px_0_32px_rgba(15,23,42,0.08)] backdrop-blur-xl transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] dark:border-slate-800 dark:bg-slate-950/96 dark:shadow-[8px_0_32px_rgba(0,0,0,0.45)]",
          isSessionDrawerOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-zinc-200/70 bg-white/90 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/90">
          <div className="min-w-0">
            <span className="text-[13px] font-semibold tracking-tight text-zinc-900 dark:text-slate-100">会话历史</span>
            <p className="mt-0.5 text-[11px] text-zinc-400 dark:text-slate-500">
              {sessions.length > 0 ? `${sessions.length} 个会话` : "暂无会话"}
            </p>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={handleCreateSession}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-transparent text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
              aria-label="新建会话"
            >
              <Plus className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setIsSessionDrawerOpen(false)}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-zinc-500 transition hover:bg-zinc-100 dark:text-slate-400 dark:hover:bg-slate-800"
              aria-label="关闭"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {sessionsError ? (
          <div className="mx-3 mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {sessionsError}
          </div>
        ) : null}

        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
          {sessionsLoaded ? (
            sessions.length > 0 ? (
              sessions.map((item) => {
                const selectionTarget = getSessionSelectionTarget(item);
                const isSelected = selectedSessionId === item.id;
                const sourceLabel = item.source === "build_planner" ? "规划" : selectionTarget ? "划词" : "普通";
                return (
                  <div
                    key={item.id}
                    className={cn(
                      "group relative mb-1.5 overflow-hidden rounded-xl border transition-colors",
                      isSelected
                        ? "border-zinc-200 bg-zinc-50/95 shadow-sm ring-1 ring-zinc-100 dark:border-slate-700 dark:bg-slate-900/80 dark:ring-slate-800"
                        : "border-transparent hover:border-zinc-200/80 hover:bg-zinc-50/90 dark:hover:border-slate-800 dark:hover:bg-slate-900/70",
                    )}
                  >
                    {isSelected ? (
                      <span className="absolute bottom-3 left-0 top-3 w-0.5 rounded-r-full bg-zinc-900 dark:bg-slate-100" />
                    ) : null}
                    <button
                      type="button"
                      onClick={() => {
                        selectHistorySession(item);
                        setIsSessionDrawerOpen(false);
                      }}
                      className="block w-full px-3 py-2.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/30"
                    >
                      <p className="line-clamp-2 pr-7 text-[13px] font-medium leading-relaxed text-zinc-800 dark:text-slate-200">
                        {item.title || "未命名会话"}
                      </p>
                      <div className="mt-1.5 flex min-w-0 items-center gap-1.5 text-[11px] text-zinc-400 dark:text-slate-500">
                        <span
                          className={cn(
                            "inline-flex h-5 shrink-0 items-center rounded-full px-1.5 text-[10px] font-medium",
                            selectionTarget
                              ? "bg-sky-50 text-sky-600 dark:bg-sky-500/10 dark:text-sky-300"
                              : item.source === "build_planner"
                                ? "bg-violet-50 text-violet-600 dark:bg-violet-500/10 dark:text-violet-300"
                                : "bg-zinc-100 text-zinc-500 dark:bg-slate-800 dark:text-slate-400",
                          )}
                        >
                          {sourceLabel}
                        </span>
                        <span className="truncate">{formatSessionTime(item.last_message_at)}</span>
                        <span>·</span>
                        <span className="shrink-0">{item.message_count} 条</span>
                      </div>
                    </button>
                    <button
                      type="button"
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        void handleDeleteSession(item.id);
                      }}
                      className="absolute right-2.5 top-2.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-zinc-400 opacity-0 transition-all hover:bg-red-50 hover:text-red-500 group-hover:opacity-100 dark:text-slate-500 dark:hover:bg-red-500/10 dark:hover:text-red-300"
                      aria-label="删除会话"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                    {selectionTarget ? (
                      <div className="mx-3 mb-2.5 flex items-start gap-2 rounded-lg border border-zinc-200/70 bg-white px-2.5 py-2 shadow-[0_1px_2px_rgba(15,23,42,0.03)] dark:border-slate-800 dark:bg-slate-950/55">
                        <MessageSquareText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-sky-500 dark:text-sky-300" />
                        <p className="min-w-0 flex-1 line-clamp-2 text-[11px] leading-4 text-zinc-500 dark:text-slate-400">
                          {selectionTarget.selectedText}
                        </p>
                        <button
                          type="button"
                          onClick={(event) => {
                            event.preventDefault();
                            event.stopPropagation();
                            locateHistorySession(item, selectionTarget);
                          }}
                          className="inline-flex h-6 shrink-0 items-center gap-1 rounded-md border border-zinc-200 bg-white px-1.5 text-[11px] font-medium text-zinc-600 transition hover:border-sky-200 hover:bg-sky-50 hover:text-sky-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-sky-500/40 dark:hover:bg-sky-500/10 dark:hover:text-sky-200"
                          title={`定位原文：${selectionTarget.selectedText}`}
                          aria-label="定位原文"
                        >
                          <MapPin className="h-3.5 w-3.5" />
                          定位
                        </button>
                      </div>
                    ) : null}
                  </div>
                );
              })
            ) : (
              <div className="flex h-full items-center justify-center px-4 text-center text-[12px] text-zinc-400 dark:text-slate-500">
                还没有会话，点击右上角创建一个。
              </div>
            )
          ) : (
            <div className="flex h-full items-center justify-center text-zinc-400 dark:text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" />
            </div>
          )}
        </div>
      </aside>

      <ChatCitationModal
        open={selectedChunkId !== null}
        onClose={() => setSelectedChunkId(null)}
        subject={subjectId ?? ""}
        chunkId={selectedChunkId}
      />
    </div>
  );
}

function formatSessionTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "刚刚";
  }
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
