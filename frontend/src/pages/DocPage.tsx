import { memo, useState, useRef, useEffect, useMemo, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import {
  FileText,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Send,
  Bot,
  Loader2,
  Sparkles,
  RefreshCw,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { cn } from "../lib/utils";
import { TopBar } from "../components/layout/TopBar";
import { getApiErrorMessage, postSseJson } from "../api/client";
import { mockFullMarkdownApiV1SubjectsSubjectKnowledgeMockFullMarkdownPost } from "../api/generated/knowledge";
import { unwrapOrvalResponse } from "../api/generated/utils";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface TocItem {
  id: string;
  text: string;
  level: number;
}

type HeadingLevel = 1 | 2 | 3 | 4 | 5 | 6;

interface Comment {
  id: string;
  anchorId: string;
  selectedText: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;
  streaming?: boolean;
}

interface FloatingComment {
  anchorId: string;
  selectedText: string;
  selectionViewportTop: number;
  top: number;
}

interface FloatingToolbar {
  anchorId: string;
  selectedText: string;
  top: number;
  left: number;
  selectionViewportTop: number;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function textToId(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\u4e00-\u9fff]+/g, "-")
    .replace(/^-|-$/g, "");
}

function createHeadingIdFactory() {
  const counts = new Map<string, number>();
  return (text: string) => {
    const base = textToId(text) || "section";
    const next = (counts.get(base) ?? 0) + 1;
    counts.set(base, next);
    return next === 1 ? base : `${base}-${next}`;
  };
}

function formatTime(ts: number): string {
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const COMMENT_THREAD_GAP = 12;
const COMMENT_THREAD_DEFAULT_HEIGHT = 140;
const COMMENT_THREAD_TOP_PADDING = 8;
const COMMENT_THREAD_BOTTOM_PADDING = 10;
const COMMENT_THREAD_EDGE_FADE = 68;
const COMMENT_THREAD_HIDE_OFFSET = 28;
const COMPACT_PANEL_BREAKPOINT = 1536;

function numberRecordEqual(a: Record<string, number>, b: Record<string, number>): boolean {
  const aKeys = Object.keys(a);
  const bKeys = Object.keys(b);
  if (aKeys.length !== bKeys.length) return false;
  for (const key of aKeys) {
    if (Math.abs((a[key] ?? 0) - (b[key] ?? 0)) > 0.5) return false;
  }
  return true;
}

function tocEqual(a: TocItem[], b: TocItem[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (
      a[i].id !== b[i].id ||
      a[i].text !== b[i].text ||
      a[i].level !== b[i].level
    ) {
      return false;
    }
  }
  return true;
}

/** Recursively extract plain text from React children */
function extractText(node: React.ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (!node) return "";
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (typeof node === "object" && "props" in node) {
    return extractText((node as React.ReactElement).props.children);
  }
  return "";
}

/* ------------------------------------------------------------------ */
/*  DocMarkdown                                                        */
/* ------------------------------------------------------------------ */

const DocMarkdown = memo(function DocMarkdown({ content }: { content: string }) {
  const nextHeadingId = useMemo(() => createHeadingIdFactory(), [content]);
  const makeHeading = (level: HeadingLevel) => {
    const Tag = `h${level}` as const;
    const styles: Record<number, string> = {
      1: "text-[26px] font-bold text-slate-900 mt-8 mb-4 pb-3 border-b border-slate-200",
      2: "text-[22px] font-semibold text-slate-800 mt-7 mb-3",
      3: "text-[18px] font-semibold text-slate-800 mt-5 mb-2",
      4: "text-base font-semibold text-slate-700 mt-4 mb-2",
      5: "text-[15px] font-semibold text-slate-700 mt-3.5 mb-2",
      6: "text-sm font-semibold uppercase tracking-wide text-slate-500 mt-3 mb-1.5",
    };
    return ({ children }: { children?: React.ReactNode }) => {
      const text = extractText(children);
      const id = nextHeadingId(text);
      return (
        <Tag id={id} data-heading-id={id} className={styles[level]}>
          {children}
        </Tag>
      );
    };
  };

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex, rehypeHighlight]}
      components={{
        h1: makeHeading(1),
        h2: makeHeading(2),
        h3: makeHeading(3),
        h4: makeHeading(4),
        h5: makeHeading(5),
        h6: makeHeading(6),
        p: ({ children }) => (
          <p className="text-[15px] text-slate-700 leading-[1.8] mb-4">{children}</p>
        ),
        ul: ({ children }) => (
          <ul className="list-disc text-[15px] text-slate-700 mb-4 space-y-1.5 pl-6">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="list-decimal text-[15px] text-slate-700 mb-4 space-y-1.5 pl-6">{children}</ol>
        ),
        li: ({ children }) => (
          <li className="leading-[1.8] [&>p]:inline [&>p]:mb-0">{children}</li>
        ),
        blockquote: ({ children }) => (
          <blockquote className="border-l-4 border-blue-200 bg-blue-50/40 pl-4 pr-3 py-2 text-slate-600 my-4 rounded-r-lg">
            {children}
          </blockquote>
        ),
        code: ({ className, children }) => {
          const codeText = String(children);
          const isBlock = Boolean(className) || codeText.includes("\n");
          if (isBlock) {
            return <code className={cn("font-mono text-[13px]", className)}>{children}</code>;
          }
          return (
            <code className={cn("bg-slate-100 text-slate-800 rounded px-1.5 py-0.5 text-sm font-mono", className)}>
              {children}
            </code>
          );
        },
        pre: ({ children }) => (
          <pre className="bg-slate-900 text-slate-100 rounded-lg p-4 overflow-x-auto text-sm my-4 leading-relaxed">
            {children}
          </pre>
        ),
        table: ({ children }) => (
          <div className="overflow-x-auto my-4">
            <table className="min-w-full text-sm border border-slate-200 rounded-lg">{children}</table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="bg-slate-50 border-b border-slate-200">{children}</thead>
        ),
        th: ({ children }) => (
          <th className="px-4 py-2.5 text-left font-semibold text-slate-700">{children}</th>
        ),
        td: ({ children }) => (
          <td className="px-4 py-2.5 text-slate-600 border-t border-slate-100">{children}</td>
        ),
        hr: () => <hr className="my-6 border-slate-200" />,
        a: ({ href, children }) => (
          <a href={href} className="text-blue-600 hover:underline" target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        ),
        strong: ({ children }) => <strong className="font-semibold text-slate-900">{children}</strong>,
        em: ({ children }) => <em className="italic text-slate-600">{children}</em>,
      }}
    >
      {content}
    </ReactMarkdown>
  );
});

const CommentMarkdown = memo(function CommentMarkdown({ content }: { content: string }) {
  return (
    <div className="text-xs text-slate-700 leading-relaxed break-words [&_h1]:text-sm [&_h1]:font-semibold [&_h1]:text-slate-800 [&_h1]:mt-3 [&_h1]:mb-1.5 [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-slate-800 [&_h2]:mt-3 [&_h2]:mb-1.5 [&_h3]:text-xs [&_h3]:font-semibold [&_h3]:text-slate-700 [&_h3]:mt-2.5 [&_h3]:mb-1 [&_p]:mb-1.5 [&_p:last-child]:mb-0 [&_ul]:list-disc [&_ul]:pl-4 [&_ul]:space-y-1 [&_ul]:mb-1.5 [&_ol]:list-decimal [&_ol]:pl-4 [&_ol]:space-y-1 [&_ol]:mb-1.5 [&_li]:leading-relaxed [&_blockquote]:border-l-2 [&_blockquote]:border-blue-200 [&_blockquote]:bg-blue-50/60 [&_blockquote]:px-2.5 [&_blockquote]:py-1.5 [&_blockquote]:rounded-r-md [&_blockquote]:my-2 [&_code]:font-mono [&_code]:text-[11px] [&_code]:bg-slate-100 [&_code]:rounded [&_code]:px-1 [&_code]:py-0.5 [&_pre]:bg-slate-900 [&_pre]:text-slate-100 [&_pre]:rounded-md [&_pre]:p-2.5 [&_pre]:overflow-x-auto [&_pre]:my-2 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_table]:min-w-full [&_table]:text-[11px] [&_table]:border [&_table]:border-slate-200 [&_table]:rounded-md [&_thead]:bg-slate-50 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-semibold [&_td]:px-2 [&_td]:py-1 [&_td]:border-t [&_td]:border-slate-100 [&_a]:text-blue-600 [&_a]:underline [&_a]:underline-offset-2">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex, rehypeHighlight]}>
        {content || " "}
      </ReactMarkdown>
    </div>
  );
});

function DocGeneratingState({
  isFetching,
}: {
  isFetching: boolean;
}) {
  return (
    <section className="rounded-3xl border border-slate-200 bg-gradient-to-b from-white via-slate-50 to-blue-50/40 p-7 md:p-9 shadow-[0_30px_70px_-45px_rgba(15,23,42,0.45)]">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-10 w-10 items-center justify-center rounded-2xl bg-blue-500/10 text-blue-600">
          {isFetching ? <Loader2 className="h-5 w-5 animate-spin" /> : <Sparkles className="h-5 w-5" />}
        </div>
        <div className="space-y-1">
          <h2 className="text-lg font-semibold text-slate-900">知识文档正在生成中</h2>
          <p className="text-sm text-slate-600">系统正在整理章节和结构化内容，完成后会自动展示在这里。</p>
        </div>
      </div>
      <div className="mt-7 grid gap-3">
        <div className="h-3 w-11/12 animate-pulse rounded-full bg-slate-200" />
        <div className="h-3 w-10/12 animate-pulse rounded-full bg-slate-200 [animation-delay:120ms]" />
        <div className="h-3 w-9/12 animate-pulse rounded-full bg-slate-200 [animation-delay:220ms]" />
        <div className="h-3 w-8/12 animate-pulse rounded-full bg-slate-200 [animation-delay:320ms]" />
      </div>
      <div className="mt-8 flex items-center gap-2 text-xs text-slate-500">
        <span className="inline-flex h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
        会在下一次拉取后自动刷新
      </div>
    </section>
  );
}

function DocLoadErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <section className="rounded-2xl border border-rose-200 bg-rose-50/60 px-5 py-5">
      <p className="text-sm text-rose-700">{message}</p>
      <button
        onClick={onRetry}
        className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-rose-200 bg-white px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-50"
      >
        <RefreshCw className="h-3.5 w-3.5" />
        重试加载
      </button>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  CommentList                                                        */
/* ------------------------------------------------------------------ */

function CommentCard({
  comment,
}: {
  comment: Comment;
}) {
  const isAssistant = comment.role === "assistant";
  return (
    <div
      className={cn(
        "w-full rounded-lg border shadow-sm transition-shadow",
        isAssistant
          ? "border-blue-100 bg-blue-50/60 hover:shadow-blue-100/70"
          : "border-slate-200 bg-white hover:shadow-md"
      )}
    >
      <div className="px-3 py-2">
        <div className="mb-1 flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <div
              className={cn(
                "flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold text-white",
                isAssistant ? "bg-blue-500" : "bg-slate-900"
              )}
            >
              {isAssistant ? "AI" : "我"}
            </div>
            <span className="text-xs font-medium text-slate-700">
              {isAssistant ? "AI 助手" : "我"}
            </span>
            <span className="text-[10px] text-slate-400">
              {formatTime(comment.createdAt)}
            </span>
          </div>
          {comment.streaming && <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-400" />}
        </div>
        {isAssistant ? (
          <CommentMarkdown content={comment.content} />
        ) : (
          <p className="text-xs leading-relaxed text-slate-700 whitespace-pre-wrap">
            {comment.content}
          </p>
        )}
      </div>
    </div>
  );
}

function CommentThread({
  anchorId,
  title,
  comments,
  selectedText,
  draft,
  isStreaming,
  isActive,
  onDraftChange,
  onSend,
  onJumpToAnchor,
}: {
  anchorId: string;
  title: string;
  comments: Comment[];
  selectedText: string;
  draft: string;
  isStreaming: boolean;
  isActive: boolean;
  onDraftChange: (value: string) => void;
  onSend: () => void;
  onJumpToAnchor: (id: string) => void;
}) {
  return (
    <section
      className={cn(
        "rounded-xl border bg-slate-50/60 shadow-sm overflow-hidden transition-colors",
        isActive ? "border-blue-300 shadow-blue-100/80" : "border-slate-200"
      )}
    >
      <div className="px-3 py-2 border-b border-slate-200 bg-white flex items-center justify-between gap-2">
        <button
          onClick={() => onJumpToAnchor(anchorId)}
          className="text-left text-xs font-semibold text-slate-700 hover:text-blue-600 truncate"
        >
          {title}
        </button>
        <span className="shrink-0 rounded-full bg-blue-100 text-blue-700 text-[10px] px-2 py-0.5 font-medium">
          {comments.length}
        </span>
      </div>
      {selectedText && (
        <div className="px-3 py-2 border-b border-slate-100 bg-white/80">
          <p className="truncate text-[11px] text-blue-500">&ldquo;{selectedText}&rdquo;</p>
        </div>
      )}
      <div className="max-h-64 overflow-y-auto p-2 space-y-2">
        {comments.map((comment) => (
          <CommentCard
            key={comment.id}
            comment={comment}
          />
        ))}
      </div>
      <div className="border-t border-slate-200 bg-white p-2">
        <textarea
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSend();
            }
          }}
          rows={2}
          disabled={isStreaming}
          placeholder={isStreaming ? "AI 正在回复..." : "继续追问这段内容..."}
          className="w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-300 disabled:bg-slate-50 disabled:text-slate-400"
        />
        <div className="mt-2 flex items-center justify-end">
          <button
            onClick={onSend}
            disabled={!draft.trim() || isStreaming}
            className={cn(
              "inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors",
              draft.trim() && !isStreaming
                ? "bg-blue-500 text-white hover:bg-blue-600"
                : "bg-slate-100 text-slate-300"
            )}
          >
            {isStreaming ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
            发送
          </button>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  DocPage                                                            */
/* ------------------------------------------------------------------ */

export function DocPage() {
  const navigate = useNavigate();
  const { subjectId } = useParams<{ subjectId: string }>();
  const docMarkdownQuery = useQuery({
    queryKey: ["docgen-content", subjectId],
    queryFn: async () => {
      if (!subjectId) {
        throw new Error("缺少学科 ID，无法加载知识文档。");
      }
      const response = await mockFullMarkdownApiV1SubjectsSubjectKnowledgeMockFullMarkdownPost(subjectId);
      return unwrapOrvalResponse(response)?.markdown ?? "";
    },
    enabled: Boolean(subjectId),
  });
  const markdown = docMarkdownQuery.data ?? "";
  const hasDocMarkdown = markdown.trim().length > 0;
  const showDocGeneratingState = !docMarkdownQuery.isError && !hasDocMarkdown;
  const [toc, setToc] = useState<TocItem[]>([]);
  const [activeHeading, setActiveHeading] = useState("");
  const [comments, setComments] = useState<Comment[]>([]);
  const [threadDrafts, setThreadDrafts] = useState<Record<string, string>>({});
  const [threadStreaming, setThreadStreaming] = useState<Record<string, boolean>>({});
  const [isTocCollapsed, setIsTocCollapsed] = useState(false);
  const [isCommentCollapsed, setIsCommentCollapsed] = useState(false);

  // Floating selection toolbar state
  const [floatingToolbar, setFloatingToolbar] = useState<FloatingToolbar | null>(null);
  const [floatingComment, setFloatingComment] = useState<FloatingComment | null>(null);
  const [floatingInput, setFloatingInput] = useState("");
  const [threadHeights, setThreadHeights] = useState<Record<string, number>>({});
  const [threadTops, setThreadTops] = useState<Record<string, number>>({});
  const [threadOpacity, setThreadOpacity] = useState<Record<string, number>>({});
  const [isCompactPanels, setIsCompactPanels] = useState(() =>
    typeof window !== "undefined" ? window.innerWidth < COMPACT_PANEL_BREAKPOINT : false
  );
  const [activeDrawer, setActiveDrawer] = useState<"toc" | "comment" | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const contentAreaRef = useRef<HTMLDivElement>(null);
  const floatingRef = useRef<HTMLDivElement>(null);
  const commentPanelRef = useRef<HTMLDivElement>(null);
  const commentViewportRef = useRef<HTMLDivElement>(null);
  const selectedRangeRef = useRef<Range | null>(null);
  const threadRefs = useRef(new Map<string, HTMLDivElement>());
  const headingFlashTimersRef = useRef(new Map<string, number>());
  const streamControllersRef = useRef(new Map<string, AbortController>());

  const isTocVisible = isCompactPanels ? activeDrawer === "toc" : !isTocCollapsed;
  const isCommentVisible = isCompactPanels ? activeDrawer === "comment" : !isCommentCollapsed;

  const activeTocItem = useMemo(
    () => toc.find((item) => item.id === activeHeading) ?? null,
    [activeHeading, toc]
  );

  useEffect(() => {
    const rafId = window.requestAnimationFrame(() => {
      const container = scrollRef.current;
      if (!container) return;
      const headingNodes = container.querySelectorAll<HTMLElement>("[data-heading-id]");
      const nextToc: TocItem[] = Array.from(headingNodes)
        .map((node) => {
          const id = node.getAttribute("data-heading-id") ?? node.id;
          if (!id) return null;
          const level = Number(node.tagName.replace("H", ""));
          if (!Number.isInteger(level) || level < 1 || level > 6) return null;
          const text = node.textContent?.trim() || id;
          return { id, text, level };
        })
        .filter((item): item is TocItem => item !== null);
      setToc((prev) => (tocEqual(prev, nextToc) ? prev : nextToc));
    });
    return () => window.cancelAnimationFrame(rafId);
  }, [markdown]);

  useEffect(() => {
    const syncCompactMode = () => {
      setIsCompactPanels(window.innerWidth < COMPACT_PANEL_BREAKPOINT);
    };
    syncCompactMode();
    window.addEventListener("resize", syncCompactMode);
    return () => window.removeEventListener("resize", syncCompactMode);
  }, []);

  useEffect(() => {
    if (!isCompactPanels) {
      setActiveDrawer(null);
    }
  }, [isCompactPanels]);

  useEffect(() => {
    return () => {
      for (const timer of headingFlashTimersRef.current.values()) {
        window.clearTimeout(timer);
      }
      headingFlashTimersRef.current.clear();
      for (const controller of streamControllersRef.current.values()) {
        controller.abort();
      }
      streamControllersRef.current.clear();
    };
  }, []);

  // Track active heading on scroll — uses the single scroll container
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;

    const handleScroll = () => {
      const headings = container.querySelectorAll("[data-heading-id]");
      let current = "";
      for (const el of headings) {
        const rect = el.getBoundingClientRect();
        if (rect.top <= 120) {
          current = el.getAttribute("data-heading-id") ?? "";
        }
      }
      setActiveHeading(current);
    };

    container.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();
    return () => container.removeEventListener("scroll", handleScroll);
  }, [markdown]);

  const flashHeading = useCallback((node: HTMLElement) => {
    const headingId = node.getAttribute("data-heading-id") ?? node.id;
    const existingTimer = headingFlashTimersRef.current.get(headingId);
    if (existingTimer) {
      window.clearTimeout(existingTimer);
    }
    node.classList.remove("heading-flash");
    void node.offsetWidth;
    node.classList.add("heading-flash");
    const timer = window.setTimeout(() => {
      node.classList.remove("heading-flash");
      headingFlashTimersRef.current.delete(headingId);
    }, 950);
    headingFlashTimersRef.current.set(headingId, timer);
  }, []);

  const scrollToHeading = useCallback((id: string) => {
    const container = scrollRef.current;
    if (!container) return;
    const el = container.querySelector(`[data-heading-id="${id}"]`) as HTMLElement | null;
    if (!el) return;

    const containerRect = container.getBoundingClientRect();
    const elRect = el.getBoundingClientRect();
    const headingTop = container.scrollTop + (elRect.top - containerRect.top);
    const maxScrollTop = Math.max(0, container.scrollHeight - container.clientHeight);
    const targetTop = Math.max(0, Math.min(maxScrollTop, headingTop - 8));
    container.scrollTo({ top: targetTop, behavior: "smooth" });
    flashHeading(el);
  }, [flashHeading]);

  const openTocDrawer = useCallback(() => {
    setActiveDrawer((prev) => (prev === "toc" ? null : "toc"));
  }, []);

  const openCommentDrawer = useCallback(() => {
    setActiveDrawer((prev) => (prev === "comment" ? null : "comment"));
  }, []);

  const closeDrawer = useCallback(() => {
    setActiveDrawer(null);
  }, []);

  const handleTocItemClick = useCallback((id: string) => {
    setActiveHeading(id);
    scrollToHeading(id);
    if (isCompactPanels) {
      setActiveDrawer(null);
    }
  }, [isCompactPanels, scrollToHeading]);

  const dismissCommentComposer = useCallback(() => {
    setFloatingComment(null);
    setFloatingInput("");
  }, []);

  const clearSelectionHighlight = useCallback(() => {
    selectedRangeRef.current = null;
    const selection = window.getSelection();
    if (selection && !selection.isCollapsed) {
      selection.removeAllRanges();
    }
  }, []);

  const computeCommentComposerTop = useCallback((selectionViewportTop: number) => {
    const panel = commentPanelRef.current;
    if (!panel) return 56;
    const panelRect = panel.getBoundingClientRect();
    const rawTop = selectionViewportTop - panelRect.top - 24;
    const minTop = 56;
    const estimatedComposerHeight = 208;
    const maxTop = Math.max(minTop, panelRect.height - estimatedComposerHeight - 12);
    return Math.min(maxTop, Math.max(minTop, rawTop));
  }, []);

  // Keep document selection behavior close to Feishu:
  // any click outside toolbar clears highlighted range state.
  useEffect(() => {
    const handlePointerDown = (e: MouseEvent) => {
      if (floatingRef.current?.contains(e.target as Node)) return;
      clearSelectionHighlight();
      setFloatingToolbar(null);
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [clearSelectionHighlight]);

  // Keep user text selection highlighted after toolbar render.
  useEffect(() => {
    if (!floatingToolbar) return;
    const raf = window.requestAnimationFrame(() => {
      const range = selectedRangeRef.current;
      if (!range) return;
      const selection = window.getSelection();
      if (!selection || !selection.isCollapsed) return;
      try {
        selection.removeAllRanges();
        selection.addRange(range);
      } catch {
        selectedRangeRef.current = null;
      }
    });
    return () => window.cancelAnimationFrame(raf);
  }, [floatingToolbar]);

  const updateThreadDraft = useCallback((anchorId: string, value: string) => {
    setThreadDrafts((prev) => {
      if (prev[anchorId] === value) return prev;
      return { ...prev, [anchorId]: value };
    });
  }, []);

  const streamAssistantReply = useCallback(async (
    anchorId: string,
    selectedText: string,
    question: string
  ) => {
    const text = question.trim();
    if (!text) return;

    const baseId = `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
    const userId = `${baseId}-user`;
    const assistantId = `${baseId}-assistant`;
    const now = Date.now();

    setComments((prev) => [
      ...prev,
      {
        id: userId,
        anchorId,
        selectedText,
        role: "user",
        content: text,
        createdAt: now,
      },
      {
        id: assistantId,
        anchorId,
        selectedText,
        role: "assistant",
        content: "",
        createdAt: now + 1,
        streaming: true,
      },
    ]);
    setThreadStreaming((prev) => ({ ...prev, [anchorId]: true }));

    const previousController = streamControllersRef.current.get(anchorId);
    if (previousController) {
      previousController.abort();
    }
    const controller = new AbortController();
    streamControllersRef.current.set(anchorId, controller);

    const appendAssistantDelta = (delta: string) => {
      if (!delta) return;
      setComments((prev) =>
        prev.map((item) =>
          item.id === assistantId
            ? { ...item, content: item.content + delta }
            : item
        )
      );
    };

    const replaceAssistantContent = (content: string) => {
      setComments((prev) =>
        prev.map((item) =>
          item.id === assistantId
            ? { ...item, content }
            : item
        )
      );
    };

    try {
      const subject = subjectId ?? "demo";
      const result = await postSseJson(
        `/api/v1/subjects/${subject}/chats/send`,
        {
          question: text,
          source: "quick_chat",
          selected_context: selectedText || undefined,
        },
        {
          signal: controller.signal,
          onToken: ({ content }) => {
            appendAssistantDelta(content);
          },
          onError: (payload) => {
            const detail =
              payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string"
                ? payload.detail
                : "请求失败，请重试。";
            replaceAssistantContent(detail);
          },
        }
      );

      if (!result.aborted && !result.receivedToken && !result.errorPayload) {
        replaceAssistantContent("已收到问题，但当前没有返回内容。");
      }
    } catch (err: unknown) {
      if (!(err instanceof Error) || err.name !== "AbortError") {
        const detail = err instanceof Error && err.message.trim()
          ? err.message.trim()
          : "请求失败，请重试。";
        replaceAssistantContent(detail);
      }
    } finally {
      setComments((prev) =>
        prev.map((item) =>
          item.id === assistantId ? { ...item, streaming: false } : item
        )
      );

      if (streamControllersRef.current.get(anchorId) === controller) {
        streamControllersRef.current.delete(anchorId);
        setThreadStreaming((prev) => ({ ...prev, [anchorId]: false }));
      }
    }
  }, [subjectId]);

  const addComment = useCallback(() => {
    if (!floatingInput.trim() || !floatingComment) return;
    const question = floatingInput.trim();
    const { anchorId, selectedText } = floatingComment;
    setFloatingInput("");
    setThreadDrafts((prev) => ({ ...prev, [anchorId]: "" }));
    dismissCommentComposer();
    setFloatingToolbar(null);
    clearSelectionHighlight();
    void streamAssistantReply(anchorId, selectedText, question);
  }, [
    clearSelectionHighlight,
    dismissCommentComposer,
    floatingComment,
    floatingInput,
    streamAssistantReply,
  ]);

  const sendThreadReply = useCallback((anchorId: string, selectedText: string) => {
    if (threadStreaming[anchorId]) return;
    const question = (threadDrafts[anchorId] ?? "").trim();
    if (!question) return;
    setThreadDrafts((prev) => ({ ...prev, [anchorId]: "" }));
    void streamAssistantReply(anchorId, selectedText, question);
  }, [streamAssistantReply, threadDrafts, threadStreaming]);

  const openCommentComposer = useCallback(() => {
    if (!floatingToolbar) return;
    if (isCompactPanels) {
      setActiveDrawer("comment");
    } else {
      setIsCommentCollapsed(false);
    }
    setFloatingComment({
      anchorId: floatingToolbar.anchorId,
      selectedText: floatingToolbar.selectedText,
      selectionViewportTop: floatingToolbar.selectionViewportTop,
      top: computeCommentComposerTop(floatingToolbar.selectionViewportTop),
    });
    setFloatingToolbar(null);
    setFloatingInput("");
  }, [computeCommentComposerTop, floatingToolbar, isCompactPanels]);

  // Feishu-style: detect text selection and show action toolbar near selection first
  const handleTextSelect = useCallback(() => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.toString().trim()) {
      setFloatingToolbar(null);
      selectedRangeRef.current = null;
      return;
    }

    const selectedText = sel.toString().trim();
    const range = sel.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    const container = scrollRef.current;
    if (!container) return;
    const contentArea = contentAreaRef.current;
    if (contentArea && !contentArea.contains(range.commonAncestorContainer)) return;
    const containerRect = container.getBoundingClientRect();

    // Find nearest heading above the selection
    let node: Node | null = sel.anchorNode;
    let headingId = "";
    while (node && node !== container) {
      if (node instanceof HTMLElement) {
        const hid = node.getAttribute("data-heading-id");
        if (hid) { headingId = hid; break; }
      }
      node = node.parentNode;
    }
    if (!headingId) {
      const allHeadings = container.querySelectorAll("[data-heading-id]");
      for (const h of allHeadings) {
        const hRange = document.createRange();
        hRange.selectNode(h);
        if (hRange.compareBoundaryPoints(Range.START_TO_START, range) <= 0) {
          headingId = h.getAttribute("data-heading-id") ?? "";
        }
      }
    }

    if (headingId) {
      selectedRangeRef.current = range.cloneRange();
      const contentTop = rect.top - containerRect.top + container.scrollTop;
      const contentLeft = rect.left - containerRect.left + container.scrollLeft + rect.width / 2;
      const top = Math.max(container.scrollTop + 8, contentTop - 46);
      const left = Math.min(
        container.scrollLeft + container.clientWidth - 170,
        Math.max(container.scrollLeft + 170, contentLeft)
      );
      setFloatingToolbar({
        anchorId: headingId,
        selectedText: selectedText.slice(0, 60),
        top,
        left,
        selectionViewportTop: rect.top + rect.height / 2,
      });
      setFloatingComment(null);
      setFloatingInput("");
    }
  }, []);

  useEffect(() => {
    if (!floatingComment) return;
    const container = scrollRef.current;
    let rafId = 0;

    const updateTop = () => {
      window.cancelAnimationFrame(rafId);
      rafId = window.requestAnimationFrame(() => {
        setFloatingComment((prev) => {
          if (!prev) return null;
          let selectionViewportTop = prev.selectionViewportTop;
          const range = selectedRangeRef.current;
          if (range) {
            const rect = range.getBoundingClientRect();
            if (rect.width > 0 || rect.height > 0) {
              selectionViewportTop = rect.top + rect.height / 2;
            }
          }
          const nextTop = computeCommentComposerTop(selectionViewportTop);
          if (
            Math.abs(prev.top - nextTop) < 0.5 &&
            Math.abs(prev.selectionViewportTop - selectionViewportTop) < 0.5
          ) {
            return prev;
          }
          return {
            ...prev,
            selectionViewportTop,
            top: nextTop,
          };
        });
      });
    };

    updateTop();
    window.addEventListener("resize", updateTop);
    container?.addEventListener("scroll", updateTop, { passive: true });
    return () => {
      window.cancelAnimationFrame(rafId);
      window.removeEventListener("resize", updateTop);
      container?.removeEventListener("scroll", updateTop);
    };
  }, [computeCommentComposerTop, floatingComment?.anchorId, isCommentVisible]);

  const activeStreamingCount = useMemo(
    () => Object.values(threadStreaming).filter(Boolean).length,
    [threadStreaming]
  );

  // Group QA messages by anchor for right-side threads
  const commentsByAnchor = useMemo(() => {
    const map = new Map<string, Comment[]>();
    for (const c of comments) {
      const list = map.get(c.anchorId) ?? [];
      list.push(c);
      map.set(c.anchorId, list);
    }
    return map;
  }, [comments]);

  const selectedTextByAnchor = useMemo(() => {
    const map = new Map<string, string>();
    for (const [anchorId, anchorComments] of commentsByAnchor.entries()) {
      const match = anchorComments.find((item) => item.selectedText);
      if (match?.selectedText) {
        map.set(anchorId, match.selectedText);
      }
    }
    return map;
  }, [commentsByAnchor]);

  const commentsForAnchor = useCallback(
    (anchorId: string) => commentsByAnchor.get(anchorId)?.length ?? 0,
    [commentsByAnchor]
  );
  const tocOrderMap = useMemo(
    () => new Map(toc.map((item, index) => [item.id, index])),
    [toc]
  );
  const tocTitleMap = useMemo(
    () => new Map(toc.map((item) => [item.id, item.text])),
    [toc]
  );
  const commentThreads = useMemo(
    () =>
      Array.from(commentsByAnchor.entries()).sort(
        ([anchorA], [anchorB]) =>
          (tocOrderMap.get(anchorA) ?? Number.MAX_SAFE_INTEGER) -
          (tocOrderMap.get(anchorB) ?? Number.MAX_SAFE_INTEGER)
      ),
    [commentsByAnchor, tocOrderMap]
  );
  const commentAnchorIds = useMemo(
    () => commentThreads.map(([anchorId]) => anchorId),
    [commentThreads]
  );
  const activeCommentIndex = useMemo(() => {
    if (commentAnchorIds.length === 0) return -1;
    if (!activeHeading) return 0;
    const directMatchIndex = commentAnchorIds.indexOf(activeHeading);
    if (directMatchIndex >= 0) return directMatchIndex;
    const activeOrder = tocOrderMap.get(activeHeading);
    if (activeOrder === undefined) return 0;
    let nearestIndex = 0;
    let nearestDistance = Number.MAX_SAFE_INTEGER;
    for (let i = 0; i < commentAnchorIds.length; i += 1) {
      const order = tocOrderMap.get(commentAnchorIds[i]);
      if (order === undefined) continue;
      const distance = Math.abs(order - activeOrder);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestIndex = i;
      }
    }
    return nearestIndex;
  }, [activeHeading, commentAnchorIds, tocOrderMap]);
  const activeCommentAnchorId = activeCommentIndex >= 0
    ? commentAnchorIds[activeCommentIndex]
    : null;
  const jumpCommentThread = useCallback((direction: -1 | 1) => {
    if (commentAnchorIds.length === 0) return;
    const baseIndex = activeCommentIndex < 0 ? 0 : activeCommentIndex;
    const nextIndex = Math.min(
      commentAnchorIds.length - 1,
      Math.max(0, baseIndex + direction)
    );
    scrollToHeading(commentAnchorIds[nextIndex]);
  }, [activeCommentIndex, commentAnchorIds, scrollToHeading]);
  const openAiAssistant = useCallback(() => {
    if (!subjectId) return;
    navigate(`/subject/${subjectId}/chat`);
  }, [navigate, subjectId]);

  const measureThreadHeights = useCallback(() => {
    const next: Record<string, number> = {};
    for (const [anchorId] of commentThreads) {
      const node = threadRefs.current.get(anchorId);
      if (node) {
        next[anchorId] = Math.ceil(node.getBoundingClientRect().height);
      }
    }
    setThreadHeights((prev) => (numberRecordEqual(prev, next) ? prev : next));
  }, [commentThreads]);

  const updateThreadTops = useCallback(() => {
    if (!isCommentVisible) {
      setThreadTops({});
      setThreadOpacity({});
      return;
    }
    const container = scrollRef.current;
    const viewport = commentViewportRef.current;
    if (!container || !viewport) return;
    const viewportRect = viewport.getBoundingClientRect();
    const maxBottom = viewportRect.height - COMMENT_THREAD_BOTTOM_PADDING;
    let cursorTop = -Infinity;
    const nextTops: Record<string, number> = {};
    const nextOpacity: Record<string, number> = {};

    for (const [anchorId] of commentThreads) {
      const anchor = container.querySelector(`[data-heading-id="${anchorId}"]`) as HTMLElement | null;
      if (!anchor) continue;
      const rect = anchor.getBoundingClientRect();
      const rawTop = rect.top - viewportRect.top;
      const threadHeight = threadHeights[anchorId] ?? COMMENT_THREAD_DEFAULT_HEIGHT;
      if (
        rawTop + threadHeight < -COMMENT_THREAD_HIDE_OFFSET ||
        rawTop > viewportRect.height + COMMENT_THREAD_HIDE_OFFSET
      ) {
        continue;
      }
      const maxTop = Math.max(COMMENT_THREAD_TOP_PADDING, maxBottom - threadHeight);
      const minVisibleTop = -threadHeight + 8;
      const stackedTop = Math.max(rawTop, cursorTop + COMMENT_THREAD_GAP);
      const top = Math.max(minVisibleTop, Math.min(maxTop, stackedTop));
      const topFade = top < COMMENT_THREAD_EDGE_FADE
        ? Math.max(0, top / COMMENT_THREAD_EDGE_FADE)
        : 1;
      const bottomDistance = viewportRect.height - (top + threadHeight);
      const bottomFade = bottomDistance < COMMENT_THREAD_EDGE_FADE
        ? Math.max(0, bottomDistance / COMMENT_THREAD_EDGE_FADE)
        : 1;
      const opacity = Math.min(1, Math.max(0, Math.min(topFade, bottomFade)));
      if (opacity <= 0.01) {
        continue;
      }
      nextTops[anchorId] = top;
      nextOpacity[anchorId] = opacity;
      cursorTop = top + threadHeight;
    }

    setThreadTops((prev) => (numberRecordEqual(prev, nextTops) ? prev : nextTops));
    setThreadOpacity((prev) => (numberRecordEqual(prev, nextOpacity) ? prev : nextOpacity));
  }, [commentThreads, isCommentVisible, threadHeights]);

  useEffect(() => {
    if (!isCommentVisible) return;
    const rafId = window.requestAnimationFrame(measureThreadHeights);
    return () => window.cancelAnimationFrame(rafId);
  }, [commentThreads, floatingComment, measureThreadHeights, isCommentVisible]);

  useEffect(() => {
    if (!isCommentVisible) return;
    const container = scrollRef.current;
    if (!container) return;
    let rafId = 0;
    const syncPositions = () => {
      window.cancelAnimationFrame(rafId);
      rafId = window.requestAnimationFrame(() => {
        updateThreadTops();
      });
    };
    syncPositions();
    container.addEventListener("scroll", syncPositions, { passive: true });
    window.addEventListener("resize", syncPositions);
    return () => {
      window.cancelAnimationFrame(rafId);
      container.removeEventListener("scroll", syncPositions);
      window.removeEventListener("resize", syncPositions);
    };
  }, [isCommentVisible, updateThreadTops]);

  const closeCommentPanel = useCallback(() => {
    if (isCompactPanels) {
      closeDrawer();
    } else {
      setIsCommentCollapsed(true);
    }
  }, [closeDrawer, isCompactPanels]);

  const tocNav = (
    <nav className="toc-scroll flex-1 overflow-y-auto py-2 pr-2">
      {toc.map((item) => {
        const count = commentsForAnchor(item.id);
        return (
          <button
            key={item.id}
            onClick={() => handleTocItemClick(item.id)}
            className={cn(
              "group w-full text-left px-2 py-1.5 rounded-md text-[13px] transition-all duration-150 flex items-center gap-1",
              item.level === 1 && "font-semibold text-slate-900 mt-2 first:mt-0",
              item.level === 2 && "pl-4 text-slate-700",
              item.level === 3 && "pl-7 text-slate-500",
              item.level >= 4 && "pl-9 text-slate-400",
              activeHeading === item.id
                ? "bg-blue-50 text-blue-700 font-medium"
                : "hover:bg-slate-100"
            )}
          >
            {item.level > 1 && (
              <ChevronRight
                className={cn(
                  "w-3 h-3 shrink-0",
                  activeHeading === item.id ? "text-blue-400" : "text-slate-300"
                )}
              />
            )}
            <span className="truncate flex-1">{item.text}</span>
            {count > 0 && (
              <span className="shrink-0 w-4 h-4 rounded-full bg-blue-100 text-blue-600 text-[10px] flex items-center justify-center font-medium">
                {count}
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );

  const commentPanel = (
    <div
      ref={commentPanelRef}
      className={cn(
        "relative w-full flex flex-col overflow-hidden",
        isCompactPanels
          ? "h-full rounded-2xl border border-slate-200 bg-white shadow-2xl"
          : "border-l border-slate-200/90 pl-3 bg-transparent"
      )}
    >
      <div className="px-1 h-11 border-b border-slate-200/80 flex items-center justify-between">
        <div className="flex items-center gap-2 text-slate-900">
          <Bot className="w-4 h-4" />
          <span className="text-sm font-semibold">问问 AI</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-slate-500">
            {commentThreads.length} 个片段
            {activeStreamingCount > 0 ? ` · ${activeStreamingCount} 条回复中` : ""}
          </span>
          <button
            onClick={() => jumpCommentThread(-1)}
            disabled={activeCommentIndex <= 0}
            className={cn(
              "w-7 h-7 rounded-lg transition-colors flex items-center justify-center",
              activeCommentIndex <= 0
                ? "text-slate-300 cursor-not-allowed"
                : "text-slate-500 hover:text-slate-700 hover:bg-slate-100"
            )}
            aria-label="定位上一段对话"
            title="定位上一段对话"
          >
            <ChevronUp className="w-4 h-4" />
          </button>
          <button
            onClick={() => jumpCommentThread(1)}
            disabled={activeCommentIndex < 0 || activeCommentIndex >= commentAnchorIds.length - 1}
            className={cn(
              "w-7 h-7 rounded-lg transition-colors flex items-center justify-center",
              activeCommentIndex < 0 || activeCommentIndex >= commentAnchorIds.length - 1
                ? "text-slate-300 cursor-not-allowed"
                : "text-slate-500 hover:text-slate-700 hover:bg-slate-100"
            )}
            aria-label="定位下一段对话"
            title="定位下一段对话"
          >
            <ChevronDown className="w-4 h-4" />
          </button>
          <button
            onClick={closeCommentPanel}
            className="w-7 h-7 rounded-lg hover:bg-slate-100 transition-colors flex items-center justify-center text-slate-500 hover:text-slate-700"
            aria-label="收起问答栏"
          >
            <ChevronRight className={cn("w-4 h-4", isCompactPanels && "rotate-180")} />
          </button>
        </div>
      </div>

      {floatingComment && (
        <div
          className="absolute left-3 right-3 z-30 rounded-xl border border-slate-200 bg-white shadow-lg"
          style={{ top: floatingComment.top }}
        >
          <div className="px-3 py-2 border-b border-slate-100 bg-slate-50/80 rounded-t-xl">
            <p className="text-xs text-slate-500 truncate">&ldquo;{floatingComment.selectedText}&rdquo;</p>
          </div>
          <div className="p-3">
            <textarea
              value={floatingInput}
              onChange={(e) => setFloatingInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  addComment();
                }
                if (e.key === "Escape") {
                  dismissCommentComposer();
                }
              }}
              placeholder="基于这段内容向 AI 提问..."
              rows={3}
              className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-300 resize-none"
              autoFocus
            />
            <div className="flex items-center justify-between mt-2">
              <button
                onClick={dismissCommentComposer}
                className="text-xs text-slate-400 hover:text-slate-600"
              >
                取消
              </button>
              <button
                onClick={addComment}
                disabled={!floatingInput.trim()}
                className={cn(
                  "flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
                  floatingInput.trim()
                    ? "bg-blue-500 text-white hover:bg-blue-600"
                    : "bg-slate-100 text-slate-300"
                )}
              >
                <Send className="w-3 h-3" />
                发送
              </button>
            </div>
          </div>
        </div>
      )}

      <div ref={commentViewportRef} className="relative flex-1 overflow-hidden">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-12 z-20 bg-gradient-to-b from-slate-50 via-slate-50/80 to-transparent" />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 z-20 bg-gradient-to-t from-slate-50 via-slate-50/80 to-transparent" />
        {commentThreads.length === 0 ? (
          <div className="h-full p-3">
            <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-center">
              <p className="text-sm text-slate-500">选中文本后点击“问问AI”即可开始对话</p>
            </div>
          </div>
        ) : (
          <div className="relative h-full">
            {commentThreads.map(([anchorId, anchorComments]) => {
              const top = threadTops[anchorId];
              const opacity = threadOpacity[anchorId] ?? 0;
              if (top === undefined || opacity <= 0) {
                return null;
              }
              return (
                <div
                  key={anchorId}
                  ref={(node: HTMLDivElement | null) => {
                    if (node) {
                      threadRefs.current.set(anchorId, node);
                    } else {
                      threadRefs.current.delete(anchorId);
                    }
                  }}
                  className="absolute left-1 right-2 transition-[top,opacity] duration-150"
                  style={{ top, opacity }}
                >
                  <CommentThread
                    anchorId={anchorId}
                    title={tocTitleMap.get(anchorId) ?? anchorId}
                    comments={anchorComments}
                    selectedText={selectedTextByAnchor.get(anchorId) ?? ""}
                    draft={threadDrafts[anchorId] ?? ""}
                    isStreaming={Boolean(threadStreaming[anchorId])}
                    isActive={activeCommentAnchorId === anchorId}
                    onDraftChange={(value) => updateThreadDraft(anchorId, value)}
                    onSend={() => sendThreadReply(anchorId, selectedTextByAnchor.get(anchorId) ?? "")}
                    onJumpToAnchor={scrollToHeading}
                  />
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );

  return (
    <div className="relative h-screen overflow-hidden bg-slate-50">
      <div className="fixed top-3 right-4 z-[70]">
        <TopBar />
      </div>

      {!isCompactPanels && (
        <div className="hidden lg:block absolute left-4 top-16 z-30">
          {isTocCollapsed ? (
            <aside className="w-11 h-11">
              <button
                onClick={() => setIsTocCollapsed(false)}
                className="w-11 h-11 rounded-xl border border-slate-200/80 bg-slate-50/95 backdrop-blur-sm shadow-sm text-slate-600 hover:text-slate-900 hover:bg-white transition-colors flex items-center justify-center"
                aria-label="展开目录"
                title={activeTocItem?.text ? `展开目录（当前：${activeTocItem.text}）` : "展开目录"}
              >
                <FileText className="w-4 h-4" />
                <ChevronRight className="w-3.5 h-3.5 -ml-0.5" />
              </button>
            </aside>
          ) : (
            <aside className="w-64 h-[calc(100vh-7rem)] max-h-[780px] flex flex-col overflow-hidden">
              <div className="px-2 h-10 flex items-center justify-between">
                <div className="flex items-center gap-2 text-slate-900">
                  <FileText className="w-4 h-4" />
                  <span className="text-sm font-semibold">目录</span>
                </div>
                <button
                  onClick={() => setIsTocCollapsed(true)}
                  className="w-7 h-7 rounded-lg hover:bg-slate-100 transition-colors flex items-center justify-center text-slate-500 hover:text-slate-700"
                  aria-label="收起目录"
                >
                  <ChevronRight className="w-4 h-4 rotate-180" />
                </button>
              </div>
              {tocNav}
            </aside>
          )}
        </div>
      )}

      {isCompactPanels && (
        <>
          <div className="fixed top-3 left-16 lg:left-[17rem] z-[79] flex items-center gap-2">
            <button
              onClick={openTocDrawer}
              className={cn(
                "h-10 w-10 rounded-xl border border-slate-200 bg-white/95 backdrop-blur-sm shadow-sm transition-colors flex items-center justify-center",
                isTocVisible ? "text-blue-600 bg-blue-50" : "text-slate-600 hover:text-slate-900 hover:bg-white"
              )}
              aria-label="切换目录抽屉"
              title={activeTocItem?.text ? `目录（当前：${activeTocItem.text}）` : "目录"}
            >
              <FileText className="w-4 h-4" />
            </button>
            <button
              onClick={openCommentDrawer}
              className={cn(
                "h-10 w-10 rounded-xl border border-slate-200 bg-white/95 backdrop-blur-sm shadow-sm transition-colors flex items-center justify-center relative",
                isCommentVisible ? "text-blue-600 bg-blue-50" : "text-slate-600 hover:text-slate-900 hover:bg-white"
              )}
              aria-label="切换问答抽屉"
              title="问问 AI"
            >
              <Bot className="w-4 h-4" />
              {commentThreads.length > 0 && (
                <span className="absolute -top-1 -right-1 min-w-4 h-4 px-1 rounded-full bg-blue-500 text-white text-[10px] leading-4 text-center">
                  {Math.min(commentThreads.length, 99)}
                </span>
              )}
            </button>
          </div>

          {activeDrawer && (
            <button
              onClick={closeDrawer}
              className="fixed inset-0 z-[76] bg-slate-900/25 backdrop-blur-[1px]"
              aria-label="关闭抽屉遮罩"
            />
          )}

          <aside
            className={cn(
              "fixed left-3 top-14 bottom-4 z-[78] w-[min(20rem,calc(100vw-1.5rem))] rounded-2xl border border-slate-200 bg-white/98 shadow-2xl flex flex-col overflow-hidden transition-transform duration-200",
              isTocVisible ? "translate-x-0" : "-translate-x-[110%] pointer-events-none"
            )}
          >
            <div className="px-3 h-11 border-b border-slate-200/80 flex items-center justify-between">
              <div className="flex items-center gap-2 text-slate-900">
                <FileText className="w-4 h-4" />
                <span className="text-sm font-semibold">目录</span>
              </div>
              <button
                onClick={closeDrawer}
                className="w-7 h-7 rounded-lg hover:bg-slate-100 transition-colors flex items-center justify-center text-slate-500 hover:text-slate-700"
                aria-label="收起目录"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
            <div className="px-1 pb-2 flex-1 overflow-hidden">{tocNav}</div>
          </aside>
        </>
      )}

      <div className="hidden lg:block absolute bottom-6 right-4 z-30">
        <button
          onClick={openAiAssistant}
          className="h-11 rounded-2xl border border-slate-200 bg-white/95 backdrop-blur-sm shadow-lg px-4 text-slate-700 hover:text-slate-900 hover:bg-white transition-colors inline-flex items-center gap-2"
          aria-label="AI 助手"
          title="AI 助手"
        >
          <Bot className="w-4 h-4" />
          <span className="text-xs font-semibold tracking-wide uppercase">AI</span>
        </button>
      </div>

      {!isCompactPanels && (
        <>
          {isCommentCollapsed ? (
            <aside className="hidden lg:flex absolute right-4 top-16 z-20">
              <button
                onClick={() => setIsCommentCollapsed(false)}
                className="rounded-xl border border-slate-200 bg-white/95 backdrop-blur-sm shadow-sm px-2 py-2.5 text-slate-600 hover:text-slate-900 hover:bg-white transition-colors flex items-center gap-1"
                aria-label="展开问答栏"
              >
                <Bot className="w-4 h-4" />
                <ChevronRight className="w-4 h-4 rotate-180" />
              </button>
            </aside>
          ) : (
            <aside className="hidden lg:flex absolute right-4 top-16 bottom-5 w-80 z-20">
              {commentPanel}
            </aside>
          )}
        </>
      )}

      {isCompactPanels && (
        <aside
          className={cn(
            "fixed right-3 top-14 bottom-4 z-[78] w-[min(24rem,calc(100vw-1.5rem))] transition-transform duration-200",
            isCommentVisible ? "translate-x-0" : "translate-x-[110%] pointer-events-none"
          )}
        >
          {commentPanel}
        </aside>
      )}

      <div
        ref={scrollRef}
        className="h-full overflow-y-auto relative"
        onMouseUp={handleTextSelect}
      >
        <div
          className={cn(
            "min-h-full pr-4 transition-[padding-left,padding-right] duration-300 pl-4 md:pl-6",
            isCompactPanels
              ? "lg:pr-6 lg:pl-6"
              : isCommentCollapsed
                ? "lg:pr-20"
                : "lg:pr-[22rem]",
            isCompactPanels
              ? null
              : isTocCollapsed
                ? "lg:pl-20"
                : "lg:pl-[18.5rem]"
          )}
        >
          <div className="mx-auto max-w-[1800px] px-6 py-8">
            <div
              ref={contentAreaRef}
              className="mx-auto flex min-h-full w-full max-w-[1380px]"
              >
                <article
                  className="min-w-0 flex-1 px-6 py-8 md:px-10 md:py-10"
                >
                  {docMarkdownQuery.isError ? (
                    <DocLoadErrorState
                      message={getApiErrorMessage(docMarkdownQuery.error, "获取知识文档失败，请稍后重试。")}
                      onRetry={() => {
                        void docMarkdownQuery.refetch();
                      }}
                    />
                  ) : showDocGeneratingState ? (
                    <DocGeneratingState isFetching={docMarkdownQuery.isFetching} />
                  ) : (
                    <DocMarkdown content={markdown} />
                  )}
                </article>
            </div>
          </div>

          {floatingToolbar && (
            <div
              ref={floatingRef}
              className="absolute z-50 -translate-x-1/2"
              style={{
                top: floatingToolbar.top,
                left: floatingToolbar.left,
              }}
              onMouseUp={(e) => e.stopPropagation()}
            >
              <div className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1 shadow-lg">
                <span className="max-w-36 truncate text-[11px] text-slate-400">
                  &ldquo;{floatingToolbar.selectedText}&rdquo;
                </span>
                <button
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={openCommentComposer}
                  className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
                >
                  <Bot className="w-3.5 h-3.5" />
                  问问AI
                </button>
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}

