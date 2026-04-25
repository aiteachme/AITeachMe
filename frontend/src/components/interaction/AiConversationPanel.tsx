import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronRight,
  Loader2,
  MessageSquareText,
  PanelLeft,
  Plus,
  Trash2,
  X,
} from "lucide-react";

import { apiClient, getApiErrorMessage } from "../../api/client";
import type {
  ApiResponseChatSessionCreateData,
  ApiResponsePaginatedDataChatSessionItem,
  ChatSessionItem,
} from "../../api/generated/model";
import { useChatSession } from "../../hooks/useChatSession";
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

const LOGO_SRC = publicAssetPath("logo.svg");

export function AiConversationPanel({
  scope,
  request,
  active,
  presentation,
  onClose,
  className,
}: AiConversationPanelProps) {
  const subjectId = getAiConversationBackendSubjectId(scope);
  const [draft, setDraft] = useState("");
  const [sessions, setSessions] = useState<ChatSessionItem[]>([]);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [isSessionDrawerOpen, setIsSessionDrawerOpen] = useState(false);
  const [selectedChunkId, setSelectedChunkId] = useState<number | null>(null);

  const {
    messages,
    historyLoaded,
    historyError,
    isStreaming,
    sendMessage,
    abortStream,
    clearHistory,
  } = useChatSession(subjectId ?? "", {
    sessionId: selectedSessionId,
    enabled: active && Boolean(subjectId),
    loadWithoutSession: false,
    onSessionResolved: (nextSessionId) => {
      setSelectedSessionId(nextSessionId);
      void reloadSessions(nextSessionId);
    },
  });

  const selectedSession = useMemo(
    () => sessions.find((item) => item.id === selectedSessionId) ?? null,
    [selectedSessionId, sessions],
  );
  const isPlannerConversation = selectedSession?.source === "build_planner";
  const isFullscreen = presentation === "fullscreen";

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
        return items[0]?.id ?? null;
      });
    } catch (error: unknown) {
      setSessionsError(getApiErrorMessage(error, "加载会话历史失败"));
    } finally {
      setSessionsLoaded(true);
    }
  }, [subjectId]);

  useEffect(() => {
    setDraft("");
    setSessions([]);
    setSessionsLoaded(false);
    setSessionsError(null);
    setSelectedSessionId(null);
    setIsSessionDrawerOpen(false);
    setSelectedChunkId(null);
  }, [subjectId]);

  useEffect(() => {
    if (!request) {
      return;
    }
    if (request.sessionId !== undefined) {
      setSelectedSessionId(request.sessionId);
    }
    if (request.draft !== undefined) {
      setDraft(request.draft);
    }
  }, [request]);

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
      setSessions((prev) => [created, ...prev.filter((item) => item.id !== created.id)]);
      setSelectedSessionId(created.id);
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

  async function handleSend() {
    const question = draft.trim();
    if (!question || !subjectId || isStreaming || isPlannerConversation) {
      return;
    }

    setDraft("");
    const result = await sendMessage({
      question,
      session_id: selectedSessionId ?? undefined,
    });
    if (!result.accepted) {
      setDraft(question);
      return;
    }
    const nextSessionId = result.sessionId ?? selectedSessionId;
    if (nextSessionId) {
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
            <h2 className="truncate text-[14px] font-semibold tracking-tight text-zinc-900 dark:text-slate-100">
              {selectedSession?.title ?? "新会话"}
            </h2>
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
        {!selectedSessionId ? (
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
        ) : messages.length > 0 ? (
          <ChatTranscript
            messages={messages}
            onOpenCitation={(chunkId) => setSelectedChunkId(chunkId)}
          />
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
        <ChatComposer
          value={draft}
          onChange={setDraft}
          onSend={() => void handleSend()}
          onAbort={abortStream}
          isStreaming={isStreaming}
          disabled={!subjectId || isPlannerConversation}
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
          "absolute bottom-0 left-0 top-0 z-30 flex w-[280px] flex-col border-r border-zinc-200/80 bg-zinc-50 shadow-[4px_0_24px_rgba(0,0,0,0.05)] transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[4px_0_24px_rgba(0,0,0,0.45)]",
          isSessionDrawerOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-zinc-200/60 bg-zinc-100/50 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/80">
          <span className="text-[13px] font-semibold tracking-tight text-zinc-900 dark:text-slate-100">会话历史</span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={handleCreateSession}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-transparent text-zinc-500 transition hover:bg-white hover:text-zinc-900 hover:shadow-sm dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
              aria-label="新建会话"
            >
              <Plus className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setIsSessionDrawerOpen(false)}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-200/50 dark:text-slate-400 dark:hover:bg-slate-800"
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
              sessions.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  onClick={() => {
                    setSelectedSessionId(item.id);
                    setIsSessionDrawerOpen(false);
                  }}
                  className={cn(
                    "group mb-1.5 w-full rounded-xl border px-3 py-2.5 text-left transition-colors",
                    selectedSessionId === item.id
                      ? "border-zinc-200/80 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-900"
                      : "border-transparent hover:border-zinc-200/60 hover:bg-zinc-100 dark:hover:border-slate-800 dark:hover:bg-slate-900/70",
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="line-clamp-2 text-[13px] font-medium leading-relaxed text-zinc-800 dark:text-slate-200">
                      {item.title}
                    </p>
                    <button
                      type="button"
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        void handleDeleteSession(item.id);
                      }}
                      className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-zinc-400 opacity-0 transition-all hover:bg-red-50 hover:text-red-500 group-hover:opacity-100 dark:text-slate-500 dark:hover:bg-red-500/10 dark:hover:text-red-300"
                      aria-label="删除会话"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <p className="mt-1 text-[11px] text-zinc-400 dark:text-slate-500">
                    {item.source === "build_planner" ? "规划 · " : ""}
                    {formatSessionTime(item.last_message_at)} · {item.message_count} 条
                  </p>
                </button>
              ))
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
