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
} from "lucide-react";
import { apiClient, getApiErrorMessage } from "../../api/client";
import type {
  ApiResponseChatSessionCreateData,
  ApiResponsePaginatedDataChatSessionItem,
  ChatSessionItem,
} from "../../api/generated/model";
import { ChatCitationModal } from "../chat/ChatCitationModal";
import { ChatComposer } from "../chat/ChatComposer";
import { ChatTranscript } from "../chat/ChatTranscript";
import { Button } from "../ui/Button";
import { useChatSession } from "../../hooks/useChatSession";
import { cn } from "../../lib/utils";

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
  const [isOpen, setIsOpen] = useState(false);
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
    if (!question || !subjectId || isStreaming) {
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
      {children}

      {hasSubject ? (
        <button
          type="button"
          onClick={() => openAssistant()}
          className="fixed bottom-6 right-6 z-[86] inline-flex h-12 items-center gap-2 rounded-2xl border border-slate-200 bg-white/95 px-4 text-sm font-semibold text-slate-700 shadow-[0_12px_34px_-18px_rgba(15,23,42,0.6)] backdrop-blur transition hover:bg-white hover:text-slate-900"
          aria-label="打开 AI 助手"
        >
          <Bot className="h-4 w-4" />
          <span>AI</span>
        </button>
      ) : null}

      {isOpen && hasSubject ? (
        <div className="fixed inset-0 z-[90]">
          <button
            type="button"
            onClick={closeAssistant}
            className="absolute inset-0 bg-slate-950/35 backdrop-blur-[2px]"
            aria-label="关闭 AI 助手"
          />

          <div className="absolute inset-0 flex items-center justify-center p-3 md:p-6">
            <div className="relative h-[min(92vh,780px)] w-[min(94vw,780px)] overflow-hidden rounded-[30px] border border-slate-200 bg-white shadow-[0_48px_130px_-52px_rgba(15,23,42,0.82)]">
              <div className="grid h-full grid-cols-1 lg:grid-cols-[260px_minmax(0,1fr)]">
                <aside className="hidden border-r border-slate-200 bg-slate-50 lg:flex lg:flex-col">
                  <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
                    <div className="flex items-center gap-2 text-slate-900">
                      <MessageSquareText className="h-4 w-4" />
                      <span className="text-sm font-semibold">会话历史</span>
                    </div>
                    <button
                      type="button"
                      onClick={handleCreateSession}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 transition hover:bg-white hover:text-slate-900"
                      aria-label="新建会话"
                    >
                      <Plus className="h-4 w-4" />
                    </button>
                  </div>

                  {sessionsError ? (
                    <div className="mx-3 mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-600">
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
                            onClick={() => setSelectedSessionId(item.id)}
                            className={cn(
                              "group mb-1.5 w-full rounded-xl border px-3 py-2.5 text-left transition",
                              selectedSessionId === item.id
                                ? "border-sky-200 bg-white shadow-sm"
                                : "border-transparent hover:border-slate-200 hover:bg-white/80",
                            )}
                          >
                            <div className="flex items-start justify-between gap-2">
                              <p className="line-clamp-2 text-sm font-medium text-slate-800">{item.title}</p>
                              <button
                                type="button"
                                onClick={(event) => {
                                  event.preventDefault();
                                  event.stopPropagation();
                                  void handleDeleteSession(item.id);
                                }}
                                className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-slate-300 transition hover:bg-rose-50 hover:text-rose-500"
                                aria-label="删除会话"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </div>
                            <p className="mt-1 text-[11px] text-slate-400">
                              {formatSessionTime(item.last_message_at)} · {item.message_count} 条
                            </p>
                          </button>
                        ))
                      ) : (
                        <div className="flex h-full items-center justify-center px-4 text-center text-xs text-slate-400">
                          还没有会话，点击右上角创建一个。
                        </div>
                      )
                    ) : (
                      <div className="flex h-full items-center justify-center text-slate-400">
                        <Loader2 className="h-4 w-4 animate-spin" />
                      </div>
                    )}
                  </div>
                </aside>

                <section className="flex min-h-0 flex-col bg-[radial-gradient(circle_at_top,_rgba(125,211,252,0.16),_transparent_35%),linear-gradient(180deg,#f8fbff_0%,#f8fafc_58%,#f3f6fb_100%)]">
                  <div className="flex items-center justify-between border-b border-slate-200/80 px-4 py-3 md:px-5">
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => setIsSessionDrawerOpen(true)}
                        className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 lg:hidden"
                        aria-label="打开会话列表"
                      >
                        <PanelLeft className="h-4 w-4" />
                      </button>
                      <div>
                        <p className="text-xs uppercase tracking-[0.18em] text-slate-400">AI Assistant</p>
                        <h2 className="text-sm font-semibold text-slate-900 md:text-base">
                          {selectedSession?.title ?? "新会话"}
                        </h2>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => void handleClearCurrentSession()}
                        disabled={!selectedSessionId || isStreaming}
                        className="hidden border-slate-200 text-slate-600 hover:bg-slate-50 md:inline-flex"
                      >
                        清空
                      </Button>
                      <button
                        type="button"
                        onClick={closeAssistant}
                        className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 transition hover:bg-white hover:text-slate-900"
                        aria-label="关闭"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                  </div>

                  {historyError ? (
                    <div className="border-b border-rose-100 bg-rose-50/80 px-4 py-2 text-xs text-rose-600 md:px-5">
                      {historyError}
                    </div>
                  ) : null}

                  <div className="min-h-0 flex-1 overflow-y-auto">
                    {!selectedSessionId ? (
                      <div className="flex h-full items-center justify-center px-6">
                        <div className="max-w-md text-center">
                          <div className="mx-auto inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-sky-500 via-cyan-500 to-blue-600 text-white shadow-lg">
                            <Sparkles className="h-6 w-6" />
                          </div>
                          <h3 className="mt-5 text-xl font-semibold text-slate-900">开始新会话</h3>
                          <p className="mt-2 text-sm leading-7 text-slate-500">
                            直接输入问题发送，系统会自动创建会话并进入流式对话。
                          </p>
                        </div>
                      </div>
                    ) : !historyLoaded ? (
                      <div className="flex h-full items-center justify-center text-slate-500">
                        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                        加载会话中...
                      </div>
                    ) : messages.length > 0 ? (
                      <ChatTranscript
                        messages={messages}
                        onOpenCitation={(chunkId) => setSelectedChunkId(chunkId)}
                      />
                    ) : (
                      <div className="flex h-full items-center justify-center px-6">
                        <p className="text-sm text-slate-500">这个会话还没有消息，开始提问吧。</p>
                      </div>
                    )}
                  </div>

                  <ChatComposer
                    value={draft}
                    onChange={setDraft}
                    onSend={() => void handleSend()}
                    onAbort={abortStream}
                    isStreaming={isStreaming}
                    disabled={!subjectId}
                  />
                </section>
              </div>

              {isSessionDrawerOpen ? (
                <div className="absolute inset-0 z-20 lg:hidden">
                  <button
                    type="button"
                    onClick={() => setIsSessionDrawerOpen(false)}
                    className="absolute inset-0 bg-slate-900/30"
                    aria-label="关闭会话抽屉"
                  />
                  <aside className="absolute bottom-0 left-0 top-0 w-72 border-r border-slate-200 bg-white shadow-2xl">
                    <div className="flex items-center justify-between border-b border-slate-200 px-3 py-3">
                      <span className="text-sm font-semibold text-slate-800">会话历史</span>
                      <button
                        type="button"
                        onClick={() => setIsSessionDrawerOpen(false)}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100"
                        aria-label="关闭会话抽屉"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                    <div className="border-b border-slate-200 p-2">
                      <Button
                        type="button"
                        size="sm"
                        className="w-full"
                        onClick={() => void handleCreateSession()}
                      >
                        <Plus className="h-4 w-4" />
                        新建会话
                      </Button>
                    </div>
                    <div className="h-[calc(100%-7.5rem)] overflow-y-auto p-2">
                      {sessions.map((item) => (
                        <button
                          type="button"
                          key={item.id}
                          onClick={() => {
                            setSelectedSessionId(item.id);
                            setIsSessionDrawerOpen(false);
                          }}
                          className={cn(
                            "mb-1 w-full rounded-lg px-3 py-2 text-left text-sm",
                            selectedSessionId === item.id
                              ? "bg-sky-50 text-sky-700"
                              : "text-slate-600 hover:bg-slate-100",
                          )}
                        >
                          {item.title}
                        </button>
                      ))}
                    </div>
                  </aside>
                </div>
              ) : null}
            </div>
          </div>

          <ChatCitationModal
            open={selectedChunkId !== null}
            onClose={() => setSelectedChunkId(null)}
            subject={subjectId ?? ""}
            chunkId={selectedChunkId}
          />
        </div>
      ) : null}
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
