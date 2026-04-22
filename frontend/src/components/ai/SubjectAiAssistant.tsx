import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  Bot,
  Loader2,
  MessageSquareText,
  PanelLeft,
  Plus,
  Sparkles,
  Trash2,
  X,
  ChevronRight,
} from "lucide-react";
import { apiClient, getApiErrorMessage } from "../../api/client";
import { useLocation } from "react-router-dom";
import type {
  ApiResponseChatSessionCreateData,
  ApiResponsePaginatedDataChatSessionItem,
  ChatSessionItem,
} from "../../api/generated/model";
import { ChatCitationModal } from "../chat/ChatCitationModal";
import { ChatComposer } from "../chat/ChatComposer";
import { ChatTranscript } from "../chat/ChatTranscript";
// import { Button } from "../ui/Button";
import { useChatSession } from "../../hooks/useChatSession";
import { cn } from "../../lib/utils";
import { useResizablePanel } from "../../hooks/useResizablePanel";

interface SubjectAiAssistantProviderProps {
  subjectId: string | null;
  children: ReactNode;
}

interface OpenAssistantOptions {
  sessionId?: string | null;
  draft?: string;
}

interface SubjectAiAssistantContextValue {
  openAssistant: (options?: OpenAssistantOptions) => void;
  closeAssistant: () => void;
  isOpen: boolean;
}

const SubjectAiAssistantContext = createContext<SubjectAiAssistantContextValue | null>(null);

export function useSubjectAiAssistant(): SubjectAiAssistantContextValue {
  const value = useContext(SubjectAiAssistantContext);
  if (!value) {
    throw new Error("useSubjectAiAssistant must be used inside SubjectAiAssistantProvider.");
  }
  return value;
}

export function SubjectAiAssistantProvider({ subjectId, children }: SubjectAiAssistantProviderProps) {
  const { pathname } = useLocation();
  const isBuildPage = /\/subject\/[^/]+\/build\b/.test(pathname);
  const [isOpen, setIsOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [sessions, setSessions] = useState<ChatSessionItem[]>([]);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [isSessionDrawerOpen, setIsSessionDrawerOpen] = useState(false);
  const [selectedChunkId, setSelectedChunkId] = useState<number | null>(null);

  const { width: panelWidth, isDragging, handleMouseDown } = useResizablePanel({
    defaultWidth: typeof window !== 'undefined' ? window.innerWidth * 0.6 : 800,
    minWidth: 400,
    maxWidth: typeof window !== 'undefined' ? window.innerWidth * 0.8 : 1200,
  });

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
    enabled: isOpen && Boolean(subjectId),
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
    if (!subjectId) {
      setIsOpen(false);
      setDraft("");
      setSessions([]);
      setSessionsLoaded(false);
      setSessionsError(null);
      setSelectedSessionId(null);
      setIsSessionDrawerOpen(false);
    }
  }, [subjectId]);

  useEffect(() => {
    if (!isOpen || !subjectId) {
      return;
    }
    void reloadSessions();
  }, [isOpen, reloadSessions, subjectId]);

  const closeAssistant = useCallback(() => {
    setIsOpen(false);
    setIsSessionDrawerOpen(false);
  }, []);

  const openAssistant = useCallback((options?: OpenAssistantOptions) => {
    if (!subjectId) {
      return;
    }
    setIsOpen(true);
    if (options?.sessionId !== undefined) {
      setSelectedSessionId(options.sessionId);
    }
    if (options?.draft) {
      setDraft(options.draft);
    }
  }, [subjectId]);

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

  const hasSubject = Boolean(subjectId);

  const contextValue = useMemo<SubjectAiAssistantContextValue>(() => ({
    openAssistant,
    closeAssistant,
    isOpen,
  }), [closeAssistant, isOpen, openAssistant]);

  return (
    <SubjectAiAssistantContext.Provider value={contextValue}>
      <div className="flex h-screen w-full overflow-hidden bg-transparent relative">
        <div className="relative flex-1 min-w-0 overflow-hidden">
          {children}
        </div>

      {hasSubject && !isBuildPage ? (
        <button
          type="button"
          onClick={() => openAssistant()}
          className={cn(
            "fixed bottom-6 right-6 z-[86] inline-flex h-11 items-center gap-2 rounded-2xl border border-zinc-200/80 bg-white/95 px-4 text-[14px] font-medium text-zinc-700 shadow-[0_2px_8px_rgba(0,0,0,0.04),0_8px_24px_rgba(0,0,0,0.06)] backdrop-blur-xl transition duration-300 hover:border-zinc-300 hover:bg-white hover:text-zinc-900 active:scale-[0.98]",
            isOpen ? "pointer-events-none translate-y-4 opacity-0" : "translate-y-0 opacity-100"
          )}
          aria-label="打开 AI 助手"
        >
          <Bot className="h-4 w-4 text-zinc-500" />
          <span>AI Assistant</span>
        </button>
      ) : null}

      <div
        className={cn(
          "fixed top-0 bottom-0 right-0 z-[85] bg-white border-l border-zinc-200/80 shadow-[0_0_40px_rgba(0,0,0,0.1)] flex",
          isOpen && hasSubject && !isBuildPage ? "translate-x-0" : "translate-x-full",
          !isDragging && "transition-transform duration-300 ease-[cubic-bezier(0.2,0.8,0.2,1)]"
        )}
        style={{ width: panelWidth }}
      >
        <div
          className={cn(
            "absolute top-0 bottom-0 left-0 w-1.5 -ml-[0.5px] cursor-col-resize z-50 hover:bg-blue-500/50 transition-colors",
            isDragging && "bg-blue-500/50"
          )}
          onMouseDown={handleMouseDown}
        />
        <div className="w-full h-full relative flex flex-col bg-white overflow-hidden">
          {/* Header */}
          <div className="flex shrink-0 items-center justify-between border-b border-zinc-200/60 bg-white px-4 py-2.5">
            <div className="flex min-w-0 items-center gap-2">
              <button
                type="button"
                onClick={closeAssistant}
                className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 px-2"
                aria-label="收起"
              >
                <ChevronRight className="h-4 w-4" />
                <span className="text-[13px] font-medium hidden lg:inline">收起</span>
              </button>
              <div className="mx-1 h-4 w-px bg-slate-200" />
              
              <button
                type="button"
                onClick={() => setIsSessionDrawerOpen(!isSessionDrawerOpen)}
                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-zinc-200/60 bg-white text-zinc-600 shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition hover:bg-zinc-50 hover:text-zinc-900"
                aria-label="打开会话列表"
              >
                <PanelLeft className="h-4 w-4" />
              </button>
              <div className="min-w-0 pr-2">
                <h2 className="truncate text-[14px] font-semibold tracking-tight text-zinc-900">
                  {selectedSession?.title ?? "新会话"}
                </h2>
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                onClick={() => void handleClearCurrentSession()}
                disabled={!selectedSessionId || isStreaming}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 disabled:opacity-50"
                aria-label="清空记录"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Error Notice */}
          {historyError ? (
            <div className="shrink-0 border-b border-red-100 bg-red-50/80 px-4 py-2 text-[13px] text-red-600">
              {historyError}
            </div>
          ) : null}

          {/* Main Chat Content */}
          <div className="min-h-0 flex-1 overflow-y-auto pb-4 pt-2">
            {!selectedSessionId ? (
              <div className="flex h-full items-center justify-center px-6">
                <div className="max-w-md text-center">
                  <div className="mx-auto inline-flex h-14 w-14 items-center justify-center rounded-xl border border-zinc-200/60 bg-white p-2 text-zinc-600 shadow-sm">
                    <img src="/logo.svg" alt="AI" className="h-full w-full object-contain" />
                  </div>
                  <h3 className="mt-5 text-[17px] font-semibold tracking-tight text-zinc-900">开始伴读</h3>
                  <p className="mt-2 text-[13px] leading-relaxed text-zinc-500">
                    直接从下方输入问题发送即可开始。系统会自动创建全新会话。
                  </p>
                </div>
              </div>
            ) : !historyLoaded ? (
              <div className="flex h-full items-center justify-center text-[13px] text-zinc-500">
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
                <MessageSquareText className="mb-3 h-8 w-8 text-zinc-300" />
                <p className="text-[13px] text-zinc-500">
                  这个会话还没有消息<br />
                  开始提问吧
                </p>
              </div>
            )}
          </div>

          {/* Input Area */}
          <div className="shrink-0 bg-white border-t border-transparent">
            {isPlannerConversation ? (
              <div className="border-t border-amber-100 bg-amber-50/80 px-4 py-2 text-[12px] leading-relaxed text-amber-700">
                这是构建规划会话，可在这里回看；继续修改计划请回到构建页操作。
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

          {/* Sessions Drawer (Overlay) */}
          <div
            className={cn(
              "absolute inset-0 z-20 bg-slate-900/10 backdrop-blur-[1px] transition-opacity duration-300",
              isSessionDrawerOpen ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"
            )}
            onClick={() => setIsSessionDrawerOpen(false)}
          />
          <aside
            className={cn(
              "absolute bottom-0 left-0 top-0 z-30 flex w-[280px] flex-col border-r border-zinc-200/80 bg-zinc-50 shadow-[4px_0_24px_rgba(0,0,0,0.05)] transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]",
              isSessionDrawerOpen ? "translate-x-0" : "-translate-x-full"
            )}
          >
            <div className="flex shrink-0 items-center justify-between border-b border-zinc-200/60 bg-zinc-100/50 px-4 py-3">
              <span className="text-[13px] font-semibold tracking-tight text-zinc-900">会话历史</span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={handleCreateSession}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-transparent text-zinc-500 transition hover:bg-white hover:text-zinc-900 hover:shadow-sm"
                  aria-label="新建会话"
                >
                  <Plus className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  onClick={() => setIsSessionDrawerOpen(false)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-200/50"
                  aria-label="关闭"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            {sessionsError ? (
              <div className="mx-3 mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
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
                          ? "border-zinc-200/80 bg-white shadow-sm"
                          : "border-transparent hover:border-zinc-200/60 hover:bg-zinc-100"
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <p className="line-clamp-2 text-[13px] font-medium leading-relaxed text-zinc-800">
                          {item.title}
                        </p>
                        <button
                          type="button"
                          onClick={(event) => {
                            event.preventDefault();
                            event.stopPropagation();
                            void handleDeleteSession(item.id);
                          }}
                          className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-zinc-400 opacity-0 transition-all hover:bg-red-50 hover:text-red-500 group-hover:opacity-100"
                          aria-label="删除会话"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      <p className="mt-1 text-[11px] text-zinc-400">
                        {item.source === "build_planner" ? "规划 · " : ""}
                        {formatSessionTime(item.last_message_at)} · {item.message_count} 条
                      </p>
                    </button>
                  ))
                ) : (
                  <div className="flex h-full items-center justify-center px-4 text-center text-[12px] text-zinc-400">
                    还没有会话，点击右上角创建一个。
                  </div>
                )
              ) : (
                <div className="flex h-full items-center justify-center text-zinc-400">
                  <Loader2 className="h-4 w-4 animate-spin" />
                </div>
              )}
            </div>
          </aside>
        </div>
      </div>

      <ChatCitationModal
        open={selectedChunkId !== null}
        onClose={() => setSelectedChunkId(null)}
        subject={subjectId ?? ""}
        chunkId={selectedChunkId}
      />
      </div>
    </SubjectAiAssistantContext.Provider>
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
