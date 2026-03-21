import { useState, useRef, useEffect, useCallback } from "react";
import { Send, Plus, Trash2, Menu, X, MessageSquare, Loader2 } from "lucide-react";
import { useParams } from "react-router-dom";
import { Button } from "../components/ui/Button";
import { MarkdownViewer } from "../components/ui/MarkdownViewer";
import { cn } from "../lib/utils";
import { apiClient, getApiErrorMessage } from "../api/client";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
}

interface ChatHistoryItem {
  id: number;
  turn_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

interface ApiResponse<T> { code: number; data: T; }
interface PaginatedData<T> { items: T[]; total: number; }

async function fetchHistory(subject: string): Promise<ChatHistoryItem[]> {
  const res = await apiClient<ApiResponse<PaginatedData<ChatHistoryItem>>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/chats/list`,
    data: { page: 1, size: 100 },
  });
  return res.data.items;
}

async function clearHistory(subject: string): Promise<void> {
  await apiClient({ method: "POST", url: `/api/v1/subjects/${subject}/chats/clear`, data: {} });
}

export function ChatPage() {
  const { subjectId = "" } = useParams();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // 加载历史记录
  useEffect(() => {
    if (!subjectId) return;
    fetchHistory(subjectId).then((items) => {
      const msgs: Message[] = items.map((item) => ({
        id: String(item.id),
        role: item.role,
        content: item.content,
      }));
      setMessages(msgs);
      setHistoryError(null);
      setHistoryLoaded(true);
    }).catch((error: unknown) => {
      setHistoryError(getApiErrorMessage(error, "加载聊天记录失败"));
      setHistoryLoaded(true);
    });
  }, [subjectId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + "px";
    }
  }, [input]);

  const handleSend = useCallback(async () => {
    const question = input.trim();
    if (!question || isStreaming || !subjectId) return;

    const userMsg: Message = { id: Date.now().toString(), role: "user", content: question };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsStreaming(true);

    const assistantId = (Date.now() + 1).toString();
    setMessages((prev) => [...prev, { id: assistantId, role: "assistant", content: "" }]);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const baseUrl = import.meta.env.VITE_API_URL ?? "";
      const response = await fetch(`${baseUrl}/api/v1/subjects/${subjectId}/chats/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) throw new Error("请求失败");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const raw = line.slice(5).trim();
          if (!raw || raw === "[DONE]") continue;
          try {
            const parsed = JSON.parse(raw);
            if (parsed.content !== undefined) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId ? { ...m, content: m.content + parsed.content } : m
                )
              );
            }
          } catch { /* ignore malformed */ }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError") {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, content: "请求失败，请重试。" } : m
          )
        );
      }
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
    }
  }, [input, isStreaming, subjectId]);

  const handleClear = async () => {
    if (!subjectId) return;
    try {
      await clearHistory(subjectId);
      setMessages([]);
      setHistoryError(null);
    } catch (error: unknown) {
      setHistoryError(getApiErrorMessage(error, "清空聊天记录失败"));
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex h-[calc(100vh-4rem)] bg-gradient-to-b from-white to-slate-50/30 -m-6 lg:-m-8 relative">
      {/* Mobile Header */}
      <div className="lg:hidden absolute top-0 left-0 right-0 h-14 bg-white/80 backdrop-blur-md border-b border-slate-200/60 flex items-center px-4 z-10">
        <button onClick={() => setIsMobileSidebarOpen(true)} className="p-2 hover:bg-slate-100 rounded-lg -ml-2">
          <Menu className="w-5 h-5 text-slate-700" />
        </button>
        <div className="flex-1 text-center">
          <h1 className="text-sm font-medium text-slate-900">AI 对话</h1>
        </div>
        <div className="w-9" />
      </div>

      {isMobileSidebarOpen && (
        <div className="lg:hidden fixed inset-0 bg-black/20 backdrop-blur-sm z-40" onClick={() => setIsMobileSidebarOpen(false)} />
      )}

      {/* Sidebar: actions */}
      <div className={cn(
        "w-56 border-r border-slate-200/60 flex flex-col bg-white/50 backdrop-blur-sm transition-transform duration-300",
        "lg:relative lg:translate-x-0 fixed inset-y-0 left-0 z-50",
        isMobileSidebarOpen ? "translate-x-0" : "-translate-x-full"
      )}>
        <div className="lg:hidden flex items-center justify-between p-4 border-b border-slate-200/60">
          <h2 className="text-sm font-semibold text-slate-900">操作</h2>
          <button onClick={() => setIsMobileSidebarOpen(false)} className="p-1.5 hover:bg-slate-100 rounded-lg">
            <X className="w-4 h-4 text-slate-600" />
          </button>
        </div>
        <div className="p-3 space-y-2">
          <Button onClick={() => { setMessages([]); setIsMobileSidebarOpen(false); }} className="w-full justify-start gap-2 bg-slate-900 hover:bg-slate-800 text-white">
            <Plus className="w-4 h-4" />
            新建对话
          </Button>
          <Button onClick={handleClear} variant="outline" className="w-full justify-start gap-2 text-red-500 hover:text-red-600 hover:border-red-300">
            <Trash2 className="w-4 h-4" />
            清空记录
          </Button>
        </div>
      </div>

      {/* Chat Area */}
      <div className="flex-1 flex flex-col lg:mt-0 mt-14 min-w-0">
        {!historyLoaded ? (
          <div className="flex-1 flex items-center justify-center text-slate-400">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />加载中...
          </div>
        ) : messages.length === 0 ? (
          <div className="flex-1 flex items-center justify-center px-4 pb-32">
            <div className="text-center">
              <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-slate-900 to-slate-700 mb-6 shadow-lg">
                <MessageSquare className="w-8 h-8 text-white" />
              </div>
              <h2 className="text-2xl font-semibold text-slate-900 mb-2">开始对话</h2>
              <p className="text-slate-500">向 AI 提问，获得即时解答</p>
              {historyError && (
                <p className="text-sm text-red-500 mt-3">{historyError}</p>
              )}
            </div>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto">
            <div className="max-w-3xl mx-auto px-4 py-8">
              {messages.map((message) => (
                <div key={message.id} className={cn(
                  "flex gap-4 mb-6",
                  message.role === "assistant" && "bg-slate-50/50 -mx-4 px-4 py-6 rounded-2xl"
                )}>
                  <div className={cn(
                    "flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center text-white text-sm font-medium shadow-sm",
                    message.role === "user" ? "bg-slate-900" : "bg-gradient-to-br from-blue-500 to-indigo-600"
                  )}>
                    {message.role === "user" ? "U" : "AI"}
                  </div>
                  <div className="flex-1 min-w-0 pt-1.5">
                    {message.role === "assistant" ? (
                      <div className="text-[15px] leading-7 text-slate-800 [&_.katex-display]:my-2">
                        <MarkdownViewer content={message.content} />
                        {isStreaming && message.id === messages[messages.length - 1]?.id && (
                          <span className="inline-block w-0.5 h-4 bg-slate-600 ml-0.5 animate-pulse" />
                        )}
                      </div>
                    ) : (
                      <p className="text-[15px] leading-7 whitespace-pre-wrap text-slate-800">
                        {message.content}
                      </p>
                    )}
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>
          </div>
        )}

        {/* Input */}
        <div className="border-t border-slate-200/60 bg-white/80 backdrop-blur-md">
          <div className="max-w-3xl mx-auto px-4 py-4">
            <div className="relative bg-white border border-slate-300 rounded-2xl shadow-sm hover:shadow-md focus-within:border-slate-400 transition-all">
              <div className="flex items-end gap-2 p-3">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="输入消息..."
                  rows={1}
                  disabled={isStreaming}
                  className="flex-1 px-2 py-2 resize-none focus:outline-none text-[15px] text-slate-900 placeholder:text-slate-400 bg-transparent disabled:opacity-50"
                  style={{ maxHeight: "200px" }}
                />
                <button
                  onClick={handleSend}
                  disabled={!input.trim() || isStreaming}
                  className={cn(
                    "p-2.5 rounded-xl transition-all flex-shrink-0",
                    input.trim() && !isStreaming
                      ? "bg-slate-900 text-white hover:bg-slate-800 shadow-sm"
                      : "bg-slate-100 text-slate-300 cursor-not-allowed"
                  )}
                >
                  {isStreaming ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
                </button>
              </div>
            </div>
            <p className="text-xs text-slate-400 text-center mt-3">AI 可能会出错，请核实重要信息</p>
          </div>
        </div>
      </div>
    </div>
  );
}
