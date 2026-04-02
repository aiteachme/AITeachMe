import { memo, Suspense, lazy, useState, useRef, useEffect, useMemo, useCallback } from "react";
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
  ChevronLeft,
  ChevronDown,
  ChevronUp,
  Send,
  Bot,
  Loader2,
  Sparkles,
  RefreshCw,
  ExternalLink,
} from "lucide-react";
import { useLocation, useParams } from "react-router-dom";
import { cn } from "../lib/utils";
import { getApiErrorMessage, postSseJson } from "../api/client";
import { apiClient } from "../api/client";
import { useSubjectAiAssistant } from "../components/ai/SubjectAiAssistant";
import { preprocessLaTeX } from "../components/ui/MarkdownViewer";

const KnowledgeGraphSidePanel = lazy(() =>
  import("../components/pages/KnowledgeGraphSidePanel").then((module) => ({
    default: module.KnowledgeGraphSidePanel,
  })),
);

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface TocItem {
  id: string;
  text: string;
  level: number;
}

interface TocTreeNode {
  item: TocItem;
  children: TocTreeNode[];
}

type HeadingLevel = 1 | 2 | 3 | 4 | 5 | 6;

interface Comment {
  id: string;
  threadId: string;
  sessionId: string | null;
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

interface HighlightSegment {
  top: number;
  left: number;
  width: number;
  height: number;
}

interface SelectionHighlight {
  id: string;
  threadId: string;
  anchorId: string;
  selectedText: string;
  segments: HighlightSegment[];
}

interface CommentThreadView {
  threadId: string;
  anchorId: string;
  selectedText: string;
  comments: Comment[];
  createdAt: number;
}

interface CommentThreadLayout {
  top: number;
  aligned: boolean;
}

interface CommentThreadLayoutResult {
  positions: Record<string, CommentThreadLayout>;
  totalHeight: number;
}

interface ApiResponse<T> {
  code: number;
  data: T;
}

interface PaginatedData<T> {
  items: T[];
  page?: number;
  size?: number;
  total?: number;
  pages?: number;
}

interface ThreadMessageItem {
  id: number;
  turn_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

interface ThreadTurnItem {
  turn_id: string;
  session_id: string;
  source?: string | null;
  anchor_id?: string | null;
  selected_text?: string | null;
  created_at: string;
  messages: ThreadMessageItem[];
}

interface DocGenBuildStatus {
  status?: string | null;
  requested_at?: string | null;
  stage?: string | null;
  error_message?: string | null;
  draft_available?: boolean;
}

interface DocGenGetResponse {
  exists: boolean;
  markdown?: string;
  updated_at?: string | null;
  source_file_uids?: string[];
  prompt?: string | null;
  draft_markdown?: string;
  draft_updated_at?: string | null;
  build?: DocGenBuildStatus | null;
}

type DocViewMode = "live" | "draft";

const ACTIVE_DOC_BUILD_STATUSES = new Set(["accepted", "running", "publishing"]);

const DOC_BUILD_STAGE_PROGRESS: Record<string, number> = {
  build_accepted: 8,
  prepare_shared: 24,
  doc_lane_staged: 62,
  graph_ready: 74,
  curriculum_deriving: 86,
  publishing: 94,
  completed: 100,
};

const DOC_BUILD_STAGE_CAP: Record<string, number> = {
  build_accepted: 20,
  prepare_shared: 48,
  doc_lane_staged: 76,
  graph_ready: 86,
  curriculum_deriving: 93,
  publishing: 97,
};

const DOC_BUILD_STAGE_TEXT: Record<string, string> = {
  build_accepted: "已接收知识构建请求",
  prepare_shared: "正在分析材料结构与内容画像",
  doc_lane_staged: "文档草稿已生成，正在等待统一发布",
  graph_ready: "知识图谱已就绪，正在推导课程结构",
  curriculum_deriving: "正在生成教学单元、主题树与先修关系",
  publishing: "正在发布正式版知识文档",
  completed: "最新知识文档已发布",
};

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

function parseIsoTimestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function formatDocTimestamp(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function resolveDocBuildStatusText(
  build: DocGenBuildStatus | null | undefined,
  hasLiveVersion: boolean,
  hasDraftVersion: boolean,
): string {
  if (!build) {
    if (hasLiveVersion) {
      return "当前显示已发布的正式版知识文档";
    }
    return "等待发起新的知识文档构建";
  }

  if (build.status === "failed") {
    return build.error_message?.trim() ? `构建失败：${build.error_message}` : "知识构建失败，请稍后重试";
  }

  if (build.status === "cancelled") {
    return "本轮知识构建已取消";
  }

  if (build.status === "completed") {
    return hasLiveVersion ? "最新知识文档已发布" : "构建已完成";
  }

  const stage = build.stage?.trim();
  if (stage && DOC_BUILD_STAGE_TEXT[stage]) {
    return DOC_BUILD_STAGE_TEXT[stage];
  }

  if (hasDraftVersion && !hasLiveVersion) {
    return "本轮草稿已生成，正在等待图谱与课程结构对齐";
  }

  if (hasLiveVersion) {
    return "正在更新知识文档";
  }

  return "正在生成知识文档";
}

function resolveDocBuildProgressFloor(
  build: DocGenBuildStatus | null | undefined,
  hasDraftVersion: boolean,
): number {
  if (!build) {
    return hasDraftVersion ? 62 : 0;
  }

  if (build.status === "completed") {
    return 100;
  }

  const stage = build.stage?.trim();
  if (stage && DOC_BUILD_STAGE_PROGRESS[stage] !== undefined) {
    return DOC_BUILD_STAGE_PROGRESS[stage];
  }

  if (hasDraftVersion || build.draft_available) {
    return 62;
  }

  return 8;
}

function resolveDocBuildProgressCap(
  build: DocGenBuildStatus | null | undefined,
  hasDraftVersion: boolean,
): number {
  if (!build) {
    return hasDraftVersion ? 78 : 45;
  }

  if (build.status === "completed") {
    return 100;
  }

  const stage = build.stage?.trim();
  if (stage && DOC_BUILD_STAGE_CAP[stage] !== undefined) {
    return DOC_BUILD_STAGE_CAP[stage];
  }

  if (hasDraftVersion || build.draft_available) {
    return 78;
  }

  return 45;
}

const COMPACT_PANEL_BREAKPOINT = 1536;
const THREAD_HISTORY_PAGE_SIZE = 100;

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

/** Build a hierarchical tree from a flat TocItem list (Feishu-style) */
function buildTocTree(items: TocItem[]): TocTreeNode[] {
  const roots: TocTreeNode[] = [];
  const stack: TocTreeNode[] = [];

  for (const item of items) {
    const node: TocTreeNode = { item, children: [] };
    // Pop stack until we find a parent with a smaller level
    while (stack.length > 0 && stack[stack.length - 1].item.level >= item.level) {
      stack.pop();
    }
    if (stack.length === 0) {
      roots.push(node);
    } else {
      stack[stack.length - 1].children.push(node);
    }
    stack.push(node);
  }

  return roots;
}

/** Find ancestor IDs for a given heading id in the tree */
function findAncestorIds(roots: TocTreeNode[], targetId: string): string[] {
  const path: string[] = [];
  const search = (nodes: TocTreeNode[]): boolean => {
    for (const node of nodes) {
      if (node.item.id === targetId) return true;
      path.push(node.item.id);
      if (search(node.children)) return true;
      path.pop();
    }
    return false;
  };
  search(roots);
  return path;
}

function moveRecordKey<T>(
  record: Record<string, T>,
  fromKey: string,
  toKey: string,
  merge: (incoming: T, existing: T | undefined) => T = (incoming) => incoming
): Record<string, T> {
  if (fromKey === toKey) {
    return record;
  }
  if (!(fromKey in record)) {
    return record;
  }
  const incoming = record[fromKey];
  const existing = record[toKey];
  const nextValue = merge(incoming, existing);
  const next: Record<string, T> = { ...record, [toKey]: nextValue };
  delete next[fromKey];
  return next;
}

function parseDoneSessionId(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const sessionId = (payload as { session_id?: unknown }).session_id;
  return typeof sessionId === "string" && sessionId.trim() ? sessionId : null;
}

function buildCommentThreadLayout(
  threads: CommentThreadView[],
  heightByThreadId: Map<string, number>,
  desiredTopByThreadId: Map<string, number>,
  pinnedThreadId: string | null
): CommentThreadLayoutResult {
  const gap = 12;
  const estimatedHeight = 236;

  if (threads.length === 0) {
    return { positions: {}, totalHeight: 0 };
  }

  const heights = threads.map((thread) => {
    const measured = heightByThreadId.get(thread.threadId);
    return Math.max(132, measured ?? estimatedHeight);
  });
  const positions: number[] = new Array(threads.length).fill(0);

  const pinnedIndex = pinnedThreadId
    ? threads.findIndex((thread) => thread.threadId === pinnedThreadId && desiredTopByThreadId.has(thread.threadId))
    : -1;

  if (pinnedIndex < 0) {
    let cursor = 0;
    for (let i = 0; i < threads.length; i += 1) {
      const desiredTop = desiredTopByThreadId.get(threads[i].threadId);
      const top = desiredTop === undefined ? cursor : Math.max(cursor, desiredTop);
      positions[i] = top;
      cursor = top + heights[i] + gap;
    }
  } else {
    const pinnedDesiredTop = desiredTopByThreadId.get(threads[pinnedIndex].threadId) ?? 0;
    positions[pinnedIndex] = Math.max(0, pinnedDesiredTop);

    let downCursor = positions[pinnedIndex] + heights[pinnedIndex] + gap;
    for (let i = pinnedIndex + 1; i < threads.length; i += 1) {
      const desiredTop = desiredTopByThreadId.get(threads[i].threadId);
      const top = desiredTop === undefined ? downCursor : Math.max(downCursor, desiredTop);
      positions[i] = top;
      downCursor = top + heights[i] + gap;
    }

    let upCursor = positions[pinnedIndex];
    for (let i = pinnedIndex - 1; i >= 0; i -= 1) {
      const maxTop = upCursor - gap - heights[i];
      const desiredTop = desiredTopByThreadId.get(threads[i].threadId);
      positions[i] = desiredTop === undefined ? maxTop : Math.min(maxTop, desiredTop);
      upCursor = positions[i];
    }

    const minTop = Math.min(...positions);
    if (minTop < 0) {
      const shift = -minTop;
      for (let i = 0; i < positions.length; i += 1) {
        positions[i] += shift;
      }
    }
  }

  const result: Record<string, CommentThreadLayout> = {};
  let totalHeight = 0;
  for (let i = 0; i < threads.length; i += 1) {
    const thread = threads[i];
    const desiredTop = desiredTopByThreadId.get(thread.threadId);
    const top = positions[i];
    const height = heights[i];
    result[thread.threadId] = {
      top,
      aligned: desiredTop !== undefined && Math.abs(desiredTop - top) <= 4,
    };
    totalHeight = Math.max(totalHeight, top + height);
  }

  return {
    positions: result,
    totalHeight: totalHeight + 2,
  };
}

/* ------------------------------------------------------------------ */
/*  DocMarkdown                                                        */
/* ------------------------------------------------------------------ */

const DocMarkdown = memo(function DocMarkdown({ content }: { content: string }) {
  const nextHeadingId = useMemo(() => createHeadingIdFactory(), [content]);
  const makeHeading = (level: HeadingLevel) => {
    const Tag = `h${level}` as const;
    const styles: Record<number, string> = {
      1: "text-[28px] font-bold text-slate-900 mt-10 mb-5 pb-3.5 border-b border-slate-200/80",
      2: "text-[24px] font-semibold text-slate-800 mt-9 mb-4",
      3: "text-[20px] font-semibold text-slate-800 mt-7 mb-3",
      4: "text-[17px] font-semibold text-slate-700 mt-5 mb-2.5",
      5: "text-[15px] font-semibold text-slate-700 mt-4 mb-2",
      6: "text-sm font-semibold uppercase tracking-wide text-slate-500 mt-3.5 mb-1.5",
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
          <p className="text-[15px] text-slate-700 leading-[2] mb-4">{children}</p>
        ),
        ul: ({ children }) => (
          <ul className="list-disc text-[15px] text-slate-700 mb-5 space-y-2 pl-6">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="list-decimal text-[15px] text-slate-700 mb-5 space-y-2 pl-6">{children}</ol>
        ),
        li: ({ children }) => (
          <li className="leading-[2] [&>p]:inline [&>p]:mb-0">{children}</li>
        ),
        blockquote: ({ children }) => (
          <blockquote className="border-l-[3px] border-blue-300/70 bg-blue-50/30 pl-4 pr-3 py-2.5 text-slate-600 my-5 rounded-r-lg">
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
            <code className={cn("bg-slate-100/80 text-slate-800 rounded-md px-1.5 py-0.5 text-sm font-mono", className)}>
              {children}
            </code>
          );
        },
        pre: ({ children }) => (
          <pre className="bg-slate-900 text-slate-100 rounded-xl p-5 overflow-x-auto text-sm my-5 leading-relaxed">
            {children}
          </pre>
        ),
        table: ({ children }) => (
          <div className="overflow-x-auto my-5 rounded-xl border border-slate-200">
            <table className="min-w-full text-sm">{children}</table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="bg-slate-50/80 border-b border-slate-200">{children}</thead>
        ),
        th: ({ children }) => (
          <th className="px-4 py-3 text-left font-semibold text-slate-700">{children}</th>
        ),
        td: ({ children }) => (
          <td className="px-4 py-3 text-slate-600 border-t border-slate-100">{children}</td>
        ),
        hr: () => <hr className="my-8 border-slate-200/60" />,
        a: ({ href, children }) => (
          <a href={href} className="text-blue-600 hover:text-blue-700 hover:underline underline-offset-2 transition-colors" target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        ),
        strong: ({ children }) => <strong className="font-semibold text-slate-900">{children}</strong>,
        em: ({ children }) => <em className="italic text-slate-600">{children}</em>,
      }}
    >
      {preprocessLaTeX(content)}
    </ReactMarkdown>
  );
});

const CommentMarkdown = memo(function CommentMarkdown({ content }: { content: string }) {
  return (
    <div className="text-xs text-slate-700 leading-relaxed break-words [&_h1]:text-sm [&_h1]:font-semibold [&_h1]:text-slate-800 [&_h1]:mt-3 [&_h1]:mb-1.5 [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-slate-800 [&_h2]:mt-3 [&_h2]:mb-1.5 [&_h3]:text-xs [&_h3]:font-semibold [&_h3]:text-slate-700 [&_h3]:mt-2.5 [&_h3]:mb-1 [&_p]:mb-1.5 [&_p:last-child]:mb-0 [&_ul]:list-disc [&_ul]:pl-4 [&_ul]:space-y-1 [&_ul]:mb-1.5 [&_ol]:list-decimal [&_ol]:pl-4 [&_ol]:space-y-1 [&_ol]:mb-1.5 [&_li]:leading-relaxed [&_blockquote]:border-l-2 [&_blockquote]:border-blue-200 [&_blockquote]:bg-blue-50/60 [&_blockquote]:px-2.5 [&_blockquote]:py-1.5 [&_blockquote]:rounded-r-md [&_blockquote]:my-2 [&_code]:font-mono [&_code]:text-[11px] [&_code]:bg-slate-100 [&_code]:rounded [&_code]:px-1 [&_code]:py-0.5 [&_pre]:bg-slate-900 [&_pre]:text-slate-100 [&_pre]:rounded-md [&_pre]:p-2.5 [&_pre]:overflow-x-auto [&_pre]:my-2 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_table]:min-w-full [&_table]:text-[11px] [&_table]:border [&_table]:border-slate-200 [&_table]:rounded-md [&_thead]:bg-slate-50 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-semibold [&_td]:px-2 [&_td]:py-1 [&_td]:border-t [&_td]:border-slate-100 [&_a]:text-blue-600 [&_a]:underline [&_a]:underline-offset-2">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex, rehypeHighlight]}>
        {preprocessLaTeX(content) || " "}
      </ReactMarkdown>
    </div>
  );
});

function DocBuildProgress({
  progress,
  statusText,
  isFetching,
}: {
  progress: number;
  statusText: string;
  isFetching: boolean;
}) {
  return (
    <>
      <div className="flex items-center justify-between text-xs text-slate-500">
        <div className="flex items-center gap-2">
          {isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          <span>{statusText}</span>
        </div>
        <span>{Math.round(progress)}%</span>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200">
        <div
          className="h-full rounded-full bg-[linear-gradient(90deg,#0f172a_0%,#0ea5e9_55%,#22c55e_100%)] transition-[width] duration-500"
          style={{ width: `${Math.min(Math.max(progress, 0), 100)}%` }}
        />
      </div>
    </>
  );
}

function DocGeneratingState({
  isFetching,
  progress,
  statusText,
}: {
  isFetching: boolean;
  progress: number;
  statusText: string;
}) {
  return (
    <section className="rounded-3xl border border-slate-200 bg-gradient-to-b from-white via-slate-50 to-blue-50/40 p-7 md:p-9 shadow-[0_30px_70px_-45px_rgba(15,23,42,0.45)]">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-10 w-10 items-center justify-center rounded-2xl bg-blue-500/10 text-blue-600">
          {isFetching ? <Loader2 className="h-5 w-5 animate-spin" /> : <Sparkles className="h-5 w-5" />}
        </div>
        <div className="space-y-1">
          <h2 className="text-lg font-semibold text-slate-900">知识文档正在生成中</h2>
          <p className="text-sm text-slate-600">前端会维持本地进度条，并轮询已发布文档；一旦新版本发布，这里会自动切换。</p>
        </div>
      </div>
      <div className="mt-7 grid gap-3">
        <div className="h-3 w-11/12 animate-pulse rounded-full bg-slate-200" />
        <div className="h-3 w-10/12 animate-pulse rounded-full bg-slate-200 [animation-delay:120ms]" />
        <div className="h-3 w-9/12 animate-pulse rounded-full bg-slate-200 [animation-delay:220ms]" />
        <div className="h-3 w-8/12 animate-pulse rounded-full bg-slate-200 [animation-delay:320ms]" />
      </div>
      <div className="mt-8">
        <DocBuildProgress
          progress={progress}
          statusText={statusText}
          isFetching={isFetching}
        />
      </div>
    </section>
  );
}

function DocUpdatingBanner({
  progress,
  statusText,
  isFetching,
  viewMode,
  hasLiveVersion,
  hasDraftVersion,
  liveUpdatedAt,
  draftUpdatedAt,
  onViewModeChange,
}: {
  progress: number;
  statusText: string;
  isFetching: boolean;
  viewMode: DocViewMode;
  hasLiveVersion: boolean;
  hasDraftVersion: boolean;
  liveUpdatedAt?: string | null;
  draftUpdatedAt?: string | null;
  onViewModeChange: (mode: DocViewMode) => void;
}) {
  const title =
    viewMode === "draft"
      ? "当前显示：本轮草稿预览"
      : hasDraftVersion
        ? "当前显示：正式版，可切换查看本轮草稿"
        : "正在更新知识文档";
  const description =
    viewMode === "draft"
      ? "草稿仅用于预览当前构建结果，正式版仍以 unified publish 成功后的版本为准。"
      : hasDraftVersion
        ? "正式版会持续可用；如果想提前看本轮结果，可以切换到草稿预览。"
        : hasLiveVersion
          ? "当前会继续显示旧正式版，等新正式版发布后这里会自动刷新。"
          : "文档草稿一旦可用，这里会直接切换显示预览内容。";
  const liveLabel = formatDocTimestamp(liveUpdatedAt);
  const draftLabel = formatDocTimestamp(draftUpdatedAt);

  return (
    <section className="mb-5 rounded-2xl border border-sky-200 bg-sky-50/70 px-4 py-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-slate-900">{title}</p>
          <p className="mt-1 text-xs leading-5 text-slate-600">{description}</p>
        </div>
        {(hasLiveVersion || hasDraftVersion) && (
          <div className="inline-flex rounded-full border border-sky-200 bg-white/80 p-1 shadow-sm">
            <button
              type="button"
              disabled={!hasLiveVersion}
              onClick={() => hasLiveVersion && onViewModeChange("live")}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                viewMode === "live"
                  ? "bg-sky-500 text-white shadow-sm"
                  : hasLiveVersion
                    ? "text-slate-600 hover:text-slate-900"
                    : "cursor-not-allowed text-slate-300",
              )}
            >
              正式版
            </button>
            <button
              type="button"
              disabled={!hasDraftVersion}
              onClick={() => hasDraftVersion && onViewModeChange("draft")}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                viewMode === "draft"
                  ? "bg-slate-900 text-white shadow-sm"
                  : hasDraftVersion
                    ? "text-slate-600 hover:text-slate-900"
                    : "cursor-not-allowed text-slate-300",
              )}
            >
              本轮草稿
            </button>
          </div>
        )}
      </div>
      {(liveLabel || draftLabel) && (
        <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-slate-500">
          {liveLabel ? <span className="rounded-full bg-white/80 px-2.5 py-1">正式版更新于 {liveLabel}</span> : null}
          {draftLabel ? <span className="rounded-full bg-white/80 px-2.5 py-1">草稿更新于 {draftLabel}</span> : null}
        </div>
      )}
      <div className="hidden">
      <p className="text-sm font-medium text-slate-900">正在更新知识文档</p>
      <p className="mt-1 text-xs text-slate-600">旧版本会继续显示，等新一轮 merged 文档发布后这里会自动刷新。</p>
      </div>
      <div className="mt-3">
        <DocBuildProgress
          progress={progress}
          statusText={statusText}
          isFetching={isFetching}
        />
      </div>
    </section>
  );
}

function DocEmptyState() {
  return (
    <section className="rounded-3xl border border-dashed border-slate-200 bg-white p-7 text-center shadow-sm">
      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 text-slate-500">
        <FileText className="h-6 w-6" />
      </div>
      <h2 className="mt-4 text-lg font-semibold text-slate-900">暂时还没有知识文档</h2>
      <p className="mt-2 text-sm leading-6 text-slate-600">
        先回到文件页发起一次知识文档构建，这里会显示最终发布的 merged 文档。
      </p>
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

function GraphPanelFallback() {
  return (
    <div className="flex h-full min-h-[320px] items-center justify-center text-sm text-slate-500">
      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
      正在加载知识图谱面板...
    </div>
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
  onFocus,
  onJumpToAnchor,
  onOpenAssistant,
  compactMode,
  isAligned,
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
  onFocus: () => void;
  onJumpToAnchor: (id: string) => void;
  onOpenAssistant: () => void;
  compactMode: boolean;
  isAligned: boolean;
}) {
  return (
    <section
      onClick={onFocus}
      className={cn(
        "rounded-xl border bg-slate-50/60 shadow-sm overflow-hidden transition-colors",
        isActive
          ? "border-blue-400 bg-blue-50/35 shadow-[0_0_0_1px_rgba(59,130,246,0.18),0_8px_26px_-18px_rgba(59,130,246,0.6)]"
          : "border-slate-200",
        isAligned && !isActive && "border-slate-300/80"
      )}
    >
      <div className="px-3 py-2 border-b border-slate-200 bg-white flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => onJumpToAnchor(anchorId)}
          className={cn(
            "text-left text-xs font-semibold truncate transition-colors",
            isActive ? "text-blue-700" : "text-slate-700 hover:text-blue-600"
          )}
        >
          {title}
        </button>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={onOpenAssistant}
            className={cn(
              "inline-flex h-6 items-center gap-1 rounded-md border border-sky-200 bg-gradient-to-r from-sky-50 to-cyan-50 px-2 text-[10px] font-semibold text-sky-700 transition hover:border-sky-300 hover:from-sky-100 hover:to-cyan-100",
            )}
            title="在 AI 面板继续对话"
          >
            <ExternalLink className="h-2.5 w-2.5" />
            AI 面板
          </button>
          <span className="shrink-0 rounded-full bg-blue-100 text-blue-700 text-[10px] px-2 py-0.5 font-medium">
            {comments.length}
          </span>
        </div>
      </div>
      {selectedText && (
        <div className={cn(
          "px-3 py-2 border-b border-slate-100 bg-white/80 transition-colors",
          isActive && "bg-blue-50/70 border-blue-100"
        )}>
          <p className={cn("truncate text-[11px]", isActive ? "text-blue-700 font-medium" : "text-blue-500")}>
            &ldquo;{selectedText}&rdquo;
          </p>
        </div>
      )}
      <div className={cn("p-2 space-y-2", compactMode ? "max-h-64 overflow-y-auto" : "overflow-visible")}>
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
/*  KnowledgeDocsPage                                                  */
/* ------------------------------------------------------------------ */

export function KnowledgeDocsPage() {
  const { openAssistant } = useSubjectAiAssistant();
  const { subjectId } = useParams<{ subjectId: string }>();
  const location = useLocation();
  const requestedAt = useMemo(
    () => new URLSearchParams(location.search).get("requested_at"),
    [location.search],
  );
  const requestedAtMs = useMemo(
    () => parseIsoTimestamp(requestedAt),
    [requestedAt],
  );
  const [docViewMode, setDocViewMode] = useState<DocViewMode>("live");
  const [buildProgress, setBuildProgress] = useState(0);
  const [buildStatusText, setBuildStatusText] = useState("正在整理知识文档...");
  const docMarkdownQuery = useQuery({
    queryKey: ["docgen-content", subjectId, requestedAt],
    queryFn: async () => {
      if (!subjectId) {
        throw new Error("缺少学科 ID，无法加载知识文档。");
      }
      const response = await apiClient<ApiResponse<DocGenGetResponse>>({
        method: "POST",
        url: `/api/v1/subjects/${subjectId}/knowledge/docs`,
      });
      return response.data;
    },
    enabled: Boolean(subjectId),
    refetchInterval: (query) => {
      const data = query.state.data;
      const build = data?.build;
      const buildStatus = build?.status ?? null;
      if (buildStatus && ACTIVE_DOC_BUILD_STATUSES.has(buildStatus)) {
        return 2500;
      }

      if (buildStatus === "failed" || buildStatus === "cancelled" || buildStatus === "completed") {
        return false;
      }

      const requestedBuildMs = parseIsoTimestamp(build?.requested_at) ?? requestedAtMs;
      if (requestedBuildMs === null) {
        return false;
      }

      const updatedAtMs = parseIsoTimestamp(data?.updated_at);
      const isReady = updatedAtMs !== null && updatedAtMs >= requestedBuildMs;
      return isReady ? false : 2500;
    },
  });
  const liveMarkdown = docMarkdownQuery.data?.markdown ?? "";
  const draftMarkdown = docMarkdownQuery.data?.draft_markdown ?? "";
  const buildMeta = docMarkdownQuery.data?.build ?? null;
  const buildStatus = buildMeta?.status ?? null;
  const liveUpdatedAt = docMarkdownQuery.data?.updated_at ?? null;
  const draftUpdatedAt = docMarkdownQuery.data?.draft_updated_at ?? null;
  const hasLiveDocMarkdown = Boolean(docMarkdownQuery.data?.exists && liveMarkdown.trim().length > 0);
  const hasDraftDocMarkdown = Boolean(draftMarkdown.trim().length > 0);
  const buildRequestedAtMs = useMemo(
    () => parseIsoTimestamp(buildMeta?.requested_at),
    [buildMeta?.requested_at],
  );
  const publishedUpdatedAtMs = useMemo(
    () => parseIsoTimestamp(liveUpdatedAt),
    [liveUpdatedAt],
  );
  const targetRequestedAtMs = requestedAtMs ?? buildRequestedAtMs;
  const isBuildActive = Boolean(buildStatus && ACTIVE_DOC_BUILD_STATUSES.has(buildStatus));
  const isBuildFailure = buildStatus === "failed" || buildStatus === "cancelled";
  const isRequestedBuildReady =
    targetRequestedAtMs !== null
      ? publishedUpdatedAtMs !== null && publishedUpdatedAtMs >= targetRequestedAtMs
      : buildStatus === "completed" && hasLiveDocMarkdown;
  const isWaitingForRequestedBuild =
    targetRequestedAtMs !== null && !isRequestedBuildReady && !isBuildFailure;
  const effectiveDocViewMode: DocViewMode =
    !hasLiveDocMarkdown && hasDraftDocMarkdown
      ? "draft"
      : docViewMode === "draft" && hasDraftDocMarkdown
        ? "draft"
        : "live";
  const renderedMarkdown = effectiveDocViewMode === "draft" ? draftMarkdown : liveMarkdown;
  const hasRenderedMarkdown = Boolean(renderedMarkdown.trim());
  const showDocGeneratingState =
    !docMarkdownQuery.isError &&
    !hasLiveDocMarkdown &&
    !hasDraftDocMarkdown &&
    (isBuildActive || isWaitingForRequestedBuild);
  const showDocBuildFailureState =
    !docMarkdownQuery.isError &&
    !hasLiveDocMarkdown &&
    !hasDraftDocMarkdown &&
    isBuildFailure;
  const showDocEmptyState =
    !docMarkdownQuery.isError &&
    !hasLiveDocMarkdown &&
    !hasDraftDocMarkdown &&
    !isBuildActive &&
    !isWaitingForRequestedBuild &&
    !isBuildFailure;
  const showDocUpdatingBanner =
    !docMarkdownQuery.isError &&
    hasRenderedMarkdown &&
    (isBuildActive || effectiveDocViewMode === "draft" || (!hasLiveDocMarkdown && hasDraftDocMarkdown));

  useEffect(() => {
    if (!hasLiveDocMarkdown && hasDraftDocMarkdown) {
      setDocViewMode("draft");
      return;
    }

    if (hasLiveDocMarkdown && !hasDraftDocMarkdown) {
      setDocViewMode("live");
      return;
    }

    if (buildStatus === "completed" && hasLiveDocMarkdown) {
      setDocViewMode("live");
    }
  }, [buildStatus, hasDraftDocMarkdown, hasLiveDocMarkdown]);

  useEffect(() => {
    const nextStatusText = resolveDocBuildStatusText(buildMeta, hasLiveDocMarkdown, hasDraftDocMarkdown);
    const progressFloor = resolveDocBuildProgressFloor(buildMeta, hasDraftDocMarkdown);
    setBuildStatusText(nextStatusText);

    if (buildStatus === "completed" || isRequestedBuildReady) {
      setBuildProgress(100);
      return;
    }

    if (isBuildFailure) {
      setBuildProgress(progressFloor);
      return;
    }

    if (!isBuildActive && !isWaitingForRequestedBuild) {
      setBuildProgress(progressFloor);
      return;
    }

    const progressCap = resolveDocBuildProgressCap(buildMeta, hasDraftDocMarkdown);
    setBuildProgress((prev) => {
      const base = prev > 0 ? prev : progressFloor;
      return Math.max(base, progressFloor);
    });

    const timer = window.setInterval(() => {
      setBuildProgress((prev) => {
        if (prev >= progressCap) {
          return progressCap;
        }
        if (prev < 20) {
          return Math.min(progressCap, prev + 6);
        }
        if (prev < 50) {
          return Math.min(progressCap, prev + 4);
        }
        if (prev < 75) {
          return Math.min(progressCap, prev + 2.5);
        }
        return Math.min(progressCap, prev + 1.2);
      });
    }, 600);

    return () => window.clearInterval(timer);
  }, [
    buildMeta,
    buildStatus,
    hasDraftDocMarkdown,
    hasLiveDocMarkdown,
    isBuildActive,
    isBuildFailure,
    isRequestedBuildReady,
    isWaitingForRequestedBuild,
  ]);

  const [toc, setToc] = useState<TocItem[]>([]);
  const [activeHeading, setActiveHeading] = useState("");
  const [comments, setComments] = useState<Comment[]>([]);
  const [threadSessionIds, setThreadSessionIds] = useState<Record<string, string>>({});
  const [threadHistoryLoaded, setThreadHistoryLoaded] = useState(false);
  const [threadHistoryError, setThreadHistoryError] = useState<string | null>(null);
  const [selectionHighlights, setSelectionHighlights] = useState<SelectionHighlight[]>([]);
  const [threadDrafts, setThreadDrafts] = useState<Record<string, string>>({});
  const [threadStreaming, setThreadStreaming] = useState<Record<string, boolean>>({});
  const [activeCommentThreadId, setActiveCommentThreadId] = useState<string | null>(null);
  const [pinnedThreadId, setPinnedThreadId] = useState<string | null>(null);
  const [commentListOriginTop, setCommentListOriginTop] = useState<number | null>(null);
  const [threadHeightsById, setThreadHeightsById] = useState<Record<string, number>>({});
  const [isTocCollapsed, setIsTocCollapsed] = useState(false);
  const [isCommentCollapsed, setIsCommentCollapsed] = useState(false);
  const [collapsedTocIds, setCollapsedTocIds] = useState<Set<string>>(new Set());

  // Floating selection toolbar state
  const [floatingToolbar, setFloatingToolbar] = useState<FloatingToolbar | null>(null);
  const [floatingComment, setFloatingComment] = useState<FloatingComment | null>(null);
  const [floatingInput, setFloatingInput] = useState("");
  const [isCompactPanels, setIsCompactPanels] = useState(() =>
    typeof window !== "undefined" ? window.innerWidth < COMPACT_PANEL_BREAKPOINT : false
  );
  const [activeDrawer, setActiveDrawer] = useState<"toc" | "comment" | null>(null);

  type GraphViewMode = "hidden" | "split" | "full";
  const [graphViewMode, setGraphViewMode] = useState<GraphViewMode>("hidden");
  const effectiveGraphViewMode: GraphViewMode =
    isCompactPanels && graphViewMode !== "hidden" ? "full" : graphViewMode;

  const scrollRef = useRef<HTMLDivElement>(null);
  const contentAreaRef = useRef<HTMLDivElement>(null);
  const floatingRef = useRef<HTMLDivElement>(null);
  const commentPanelRef = useRef<HTMLDivElement>(null);
  const commentViewportRef = useRef<HTMLDivElement>(null);
  const commentThreadListRef = useRef<HTMLDivElement>(null);
  const selectedRangeRef = useRef<Range | null>(null);
  const threadRefs = useRef(new Map<string, HTMLDivElement>());
  const headingFlashTimersRef = useRef(new Map<string, number>());
  const tocNavRef = useRef<HTMLElement>(null);
  const streamControllersRef = useRef(new Map<string, AbortController>());

  const isTocVisible = isCompactPanels ? activeDrawer === "toc" : !isTocCollapsed;
  const isCommentVisible = isCompactPanels ? activeDrawer === "comment" : !isCommentCollapsed;

  const openGraphPanel = useCallback(() => {
    setGraphViewMode((prev) => {
      if (isCompactPanels) {
        return prev === "hidden" ? "full" : "full";
      }
      return prev === "hidden" ? "split" : "full";
    });
  }, [isCompactPanels]);

  const closeGraphPanel = useCallback(() => {
    setGraphViewMode((prev) => {
      if (isCompactPanels) {
        return "hidden";
      }
      return prev === "full" ? "split" : "hidden";
    });
  }, [isCompactPanels]);

  const activeTocItem = useMemo(
    () => toc.find((item) => item.id === activeHeading) ?? null,
    [activeHeading, toc]
  );

  // Build hierarchical tree from flat TOC (Feishu-style)
  const tocTree = useMemo(() => buildTocTree(toc), [toc]);

  // Auto-expand ancestors of active heading
  useEffect(() => {
    if (!activeHeading || tocTree.length === 0) return;
    const ancestors = findAncestorIds(tocTree, activeHeading);
    if (ancestors.length === 0) return;
    setCollapsedTocIds((prev) => {
      let changed = false;
      const next = new Set(prev);
      for (const id of ancestors) {
        if (next.has(id)) {
          next.delete(id);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [activeHeading, tocTree]);

  // Auto-scroll TOC sidebar to keep active item visible
  useEffect(() => {
    if (!activeHeading || !tocNavRef.current) return;
    const activeBtn = tocNavRef.current.querySelector(`[data-toc-id="${activeHeading}"]`) as HTMLElement | null;
    if (!activeBtn) return;
    const nav = tocNavRef.current;
    const navRect = nav.getBoundingClientRect();
    const btnRect = activeBtn.getBoundingClientRect();
    if (btnRect.top < navRect.top + 8 || btnRect.bottom > navRect.bottom - 8) {
      activeBtn.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [activeHeading]);

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
  }, [renderedMarkdown]);

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

  useEffect(() => {
    let cancelled = false;

    async function loadThreadHistory() {
      if (!subjectId) {
        setComments([]);
        setThreadSessionIds({});
        setSelectionHighlights([]);
        setActiveCommentThreadId(null);
        setThreadHistoryError(null);
        setThreadHistoryLoaded(true);
        return;
      }

      setThreadHistoryLoaded(false);
      setThreadHistoryError(null);
      try {
        const items: ThreadTurnItem[] = [];
        let page = 1;
        let totalPages = 1;
        while (page <= totalPages) {
          if (cancelled) {
            return;
          }
          const response = await apiClient<ApiResponse<PaginatedData<ThreadTurnItem>>>({
            method: "POST",
            url: `/api/v1/subjects/${subjectId}/chats/threads/list`,
            data: {
              page,
              size: THREAD_HISTORY_PAGE_SIZE,
              source: "quick_chat",
            },
          });
          const payload = response.data;
          const pageItems = payload?.items ?? [];
          items.push(...pageItems);
          totalPages = Math.max(1, payload?.pages ?? page);
          page += 1;
          if (pageItems.length < THREAD_HISTORY_PAGE_SIZE) {
            break;
          }
        }

        if (cancelled) {
          return;
        }

        const nextComments: Comment[] = [];
        const nextSessionIds: Record<string, string> = {};
        const selectedTextByThread = new Map<string, string>();

        for (const turn of items) {
          const anchorId = turn.anchor_id?.trim();
          const threadId = turn.session_id?.trim();
          if (!anchorId || !threadId) {
            continue;
          }
          nextSessionIds[threadId] = threadId;

          const selectedText = turn.selected_text?.trim() ?? "";
          if (selectedText && !selectedTextByThread.has(threadId)) {
            selectedTextByThread.set(threadId, selectedText);
          }
          const resolvedSelectedText = selectedText || selectedTextByThread.get(threadId) || "";
          for (const message of turn.messages ?? []) {
            if (message.role !== "user" && message.role !== "assistant") {
              continue;
            }
            const createdAtTs = Date.parse(message.created_at);
            nextComments.push({
              id: `history-${message.id}`,
              threadId,
              sessionId: threadId,
              anchorId,
              selectedText: resolvedSelectedText,
              role: message.role,
              content: message.content,
              createdAt: Number.isFinite(createdAtTs) ? createdAtTs : Date.now(),
            });
          }
        }

        nextComments.sort((left, right) => left.createdAt - right.createdAt);
        setComments(nextComments);
        setThreadSessionIds(nextSessionIds);
        setSelectionHighlights([]);
      } catch (error: unknown) {
        if (cancelled) {
          return;
        }
        setComments([]);
        setThreadSessionIds({});
        setSelectionHighlights([]);
        setActiveCommentThreadId(null);
        setThreadHistoryError(getApiErrorMessage(error, "加载划词问答历史失败"));
      } finally {
        if (!cancelled) {
          setThreadHistoryLoaded(true);
        }
      }
    }

    void loadThreadHistory();
    return () => {
      cancelled = true;
    };
  }, [subjectId]);

  // Track active heading on scroll with throttle (Feishu-style)
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;

    let rafPending = false;
    const handleScroll = () => {
      if (rafPending) return;
      rafPending = true;
      window.requestAnimationFrame(() => {
        rafPending = false;
        const headings = container.querySelectorAll("[data-heading-id]");
        let current = "";
        for (const el of headings) {
          const rect = el.getBoundingClientRect();
          if (rect.top <= 120) {
            current = el.getAttribute("data-heading-id") ?? "";
          }
        }
        setActiveHeading(current);
      });
    };

    container.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();
    return () => container.removeEventListener("scroll", handleScroll);
  }, [renderedMarkdown]);

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

  const captureRangeSegments = useCallback((range: Range): HighlightSegment[] => {
    const container = scrollRef.current;
    if (!container) {
      return [];
    }

    const containerRect = container.getBoundingClientRect();
    const rects = Array.from(range.getClientRects()).filter(
      (rect) => rect.width > 1 || rect.height > 1,
    );
    const toSegment = (rect: DOMRect): HighlightSegment => ({
      top: rect.top - containerRect.top + container.scrollTop,
      left: rect.left - containerRect.left + container.scrollLeft,
      width: Math.max(16, rect.width),
      height: Math.max(18, rect.height),
    });

    if (rects.length === 0) {
      const rect = range.getBoundingClientRect();
      if (rect.width < 1 && rect.height < 1) {
        return [];
      }
      return [toSegment(rect)];
    }

    return rects.map(toSegment);
  }, []);

  const captureSelectionSegments = useCallback((): HighlightSegment[] => {
    const range = selectedRangeRef.current;
    if (!range) {
      return [];
    }
    return captureRangeSegments(range);
  }, [captureRangeSegments]);

  const buildSelectionSegmentsFromText = useCallback((anchorId: string, selectedText: string): HighlightSegment[] => {
    const contentRoot = contentAreaRef.current;
    if (!contentRoot) {
      return [];
    }
    const target = selectedText.trim();
    if (!target) {
      return [];
    }
    const heading = contentRoot.querySelector(`[data-heading-id="${anchorId}"]`) as HTMLElement | null;
    if (!heading) {
      return [];
    }
    const allHeadings = Array.from(contentRoot.querySelectorAll<HTMLElement>("[data-heading-id]"));
    const headingIndex = allHeadings.findIndex((node) => node === heading);
    const nextHeading = headingIndex >= 0 ? allHeadings[headingIndex + 1] ?? null : null;
    const sectionRoots: Node[] = [];
    let node: Node | null = heading;
    while (node && node !== nextHeading) {
      sectionRoots.push(node);
      node = node.nextSibling;
    }
    if (sectionRoots.length === 0) {
      return [];
    }

    const textEntries: Array<{ node: Text; start: number; end: number }> = [];
    let rawText = "";
    for (const rootNode of sectionRoots) {
      const walker = document.createTreeWalker(rootNode, NodeFilter.SHOW_TEXT);
      let current = walker.nextNode();
      while (current) {
        const textNode = current as Text;
        const value = textNode.nodeValue ?? "";
        if (value.length > 0) {
          const start = rawText.length;
          rawText += value;
          textEntries.push({ node: textNode, start, end: rawText.length });
        }
        current = walker.nextNode();
      }
    }
    if (!rawText || textEntries.length === 0) {
      return [];
    }

    let matchStart = rawText.indexOf(target);
    let matchEnd = matchStart >= 0 ? matchStart + target.length : -1;
    if (matchStart < 0) {
      const condensedRawChars: string[] = [];
      const rawIndexByCondensed: number[] = [];
      for (let i = 0; i < rawText.length; i += 1) {
        const char = rawText[i];
        if (!/\s/u.test(char)) {
          condensedRawChars.push(char);
          rawIndexByCondensed.push(i);
        }
      }
      const condensedRaw = condensedRawChars.join("");
      const condensedTarget = target.replace(/\s+/gu, "");
      const condensedStart = condensedTarget ? condensedRaw.indexOf(condensedTarget) : -1;
      if (condensedStart < 0) {
        return [];
      }
      const rawStart = rawIndexByCondensed[condensedStart];
      const rawEnd = rawIndexByCondensed[condensedStart + condensedTarget.length - 1];
      if (rawStart === undefined || rawEnd === undefined) {
        return [];
      }
      matchStart = rawStart;
      matchEnd = rawEnd + 1;
    }
    if (matchStart < 0 || matchEnd <= matchStart) {
      return [];
    }

    const startEntry = textEntries.find((entry) => matchStart >= entry.start && matchStart < entry.end);
    const endBoundary = Math.max(matchStart, matchEnd - 1);
    const endEntry = textEntries.find((entry) => endBoundary >= entry.start && endBoundary < entry.end);
    if (!startEntry || !endEntry) {
      return [];
    }

    const range = document.createRange();
    range.setStart(startEntry.node, matchStart - startEntry.start);
    range.setEnd(endEntry.node, matchEnd - endEntry.start);
    return captureRangeSegments(range);
  }, [captureRangeSegments]);

  const createLocalThreadId = useCallback((anchorId: string) => (
    `local-${anchorId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  ), []);

  const addSelectionHighlight = useCallback((threadId: string, anchorId: string, selectedText: string, preferred?: HighlightSegment[]) => {
    const segments = preferred ?? captureSelectionSegments();
    if (segments.length === 0) {
      return;
    }
    const next: SelectionHighlight = {
      id: `highlight-${threadId}`,
      threadId,
      anchorId,
      selectedText,
      segments,
    };
    setSelectionHighlights((prev) => {
      const kept = prev.filter((item) => item.threadId !== threadId);
      return [next, ...kept].slice(0, 200);
    });
  }, [captureSelectionSegments]);

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

  const updateThreadDraft = useCallback((threadId: string, value: string) => {
    setThreadDrafts((prev) => {
      if (prev[threadId] === value) return prev;
      return { ...prev, [threadId]: value };
    });
  }, []);

  const rebindThreadIdToSession = useCallback((threadId: string, candidateSessionId: string | null): string => {
    const resolvedSessionId = candidateSessionId?.trim() ?? "";
    if (!resolvedSessionId) {
      return threadId;
    }
    if (threadId === resolvedSessionId) {
      setThreadSessionIds((prev) => {
        if (prev[threadId] === resolvedSessionId) {
          return prev;
        }
        return { ...prev, [threadId]: resolvedSessionId };
      });
      setComments((prev) => {
        let changed = false;
        const next = prev.map((item) => {
          if (item.threadId !== threadId || item.sessionId === resolvedSessionId) {
            return item;
          }
          changed = true;
          return { ...item, sessionId: resolvedSessionId };
        });
        return changed ? next : prev;
      });
      return resolvedSessionId;
    }

    setComments((prev) =>
      prev.map((item) =>
        item.threadId === threadId
          ? { ...item, threadId: resolvedSessionId, sessionId: resolvedSessionId }
          : item
      )
    );
    setThreadSessionIds((prev) => {
      const withCurrent = prev[threadId] === resolvedSessionId
        ? prev
        : { ...prev, [threadId]: resolvedSessionId };
      return moveRecordKey(withCurrent, threadId, resolvedSessionId, (_, existing) => existing ?? resolvedSessionId);
    });
    setThreadDrafts((prev) => moveRecordKey(prev, threadId, resolvedSessionId, (incoming, existing) => existing ?? incoming));
    setThreadStreaming((prev) => moveRecordKey(
      prev,
      threadId,
      resolvedSessionId,
      (incoming, existing) => Boolean(existing || incoming),
    ));
    setSelectionHighlights((prev) => {
      const remapped = prev.map((item) => (
        item.threadId === threadId ? { ...item, threadId: resolvedSessionId } : item
      ));
      const deduped = new Map<string, SelectionHighlight>();
      for (const item of remapped) {
        if (!deduped.has(item.threadId)) {
          deduped.set(item.threadId, item);
        }
      }
      return Array.from(deduped.values());
    });
    setActiveCommentThreadId((prev) => (prev === threadId ? resolvedSessionId : prev));

    const controller = streamControllersRef.current.get(threadId);
    if (controller) {
      streamControllersRef.current.delete(threadId);
      streamControllersRef.current.set(resolvedSessionId, controller);
    }

    return resolvedSessionId;
  }, []);

  const streamAssistantReply = useCallback(async (
    threadId: string,
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
        threadId,
        sessionId: threadSessionIds[threadId] ?? null,
        anchorId,
        selectedText,
        role: "user",
        content: text,
        createdAt: now,
      },
      {
        id: assistantId,
        threadId,
        sessionId: threadSessionIds[threadId] ?? null,
        anchorId,
        selectedText,
        role: "assistant",
        content: "",
        createdAt: now + 1,
        streaming: true,
      },
    ]);
    setThreadStreaming((prev) => ({ ...prev, [threadId]: true }));

    const previousController = streamControllersRef.current.get(threadId);
    if (previousController) {
      previousController.abort();
    }
    const controller = new AbortController();
    streamControllersRef.current.set(threadId, controller);
    let boundThreadId = threadId;

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
    const bindSessionToThread = (candidateSessionId: string | null) => {
      boundThreadId = rebindThreadIdToSession(boundThreadId, candidateSessionId);
    };

    try {
      const subject = subjectId ?? "demo";
      const result = await postSseJson(
        `/api/v1/subjects/${subject}/chats/send`,
        {
          question: text,
          source: "quick_chat",
          session_id: threadSessionIds[threadId] ?? undefined,
          anchor_id: anchorId,
          selected_context: selectedText || undefined,
        },
        {
          signal: controller.signal,
          onToken: ({ content }) => {
            appendAssistantDelta(content);
          },
          onDone: (payload) => {
            bindSessionToThread(parseDoneSessionId(payload));
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

      bindSessionToThread(parseDoneSessionId(result.donePayload));
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

      let activeControllerThreadId: string | null = null;
      for (const [key, value] of streamControllersRef.current.entries()) {
        if (value === controller) {
          activeControllerThreadId = key;
          break;
        }
      }
      if (activeControllerThreadId) {
        streamControllersRef.current.delete(activeControllerThreadId);
        setThreadStreaming((prev) => ({ ...prev, [activeControllerThreadId]: false }));
      } else if (boundThreadId) {
        setThreadStreaming((prev) => ({ ...prev, [boundThreadId]: false }));
      }
    }
  }, [rebindThreadIdToSession, subjectId, threadSessionIds]);

  const addComment = useCallback(() => {
    if (!floatingInput.trim() || !floatingComment) return;
    const question = floatingInput.trim();
    const { anchorId, selectedText } = floatingComment;
    const threadId = createLocalThreadId(anchorId);
    const segments = captureSelectionSegments();
    addSelectionHighlight(threadId, anchorId, selectedText, segments);
    setActiveCommentThreadId(threadId);
    setPinnedThreadId(threadId);
    setFloatingInput("");
    setThreadDrafts((prev) => ({ ...prev, [threadId]: "" }));
    dismissCommentComposer();
    setFloatingToolbar(null);
    clearSelectionHighlight();
    void streamAssistantReply(threadId, anchorId, selectedText, question);
  }, [
    clearSelectionHighlight,
    addSelectionHighlight,
    captureSelectionSegments,
    createLocalThreadId,
    dismissCommentComposer,
    floatingComment,
    floatingInput,
    streamAssistantReply,
  ]);

  const sendThreadReply = useCallback((threadId: string, anchorId: string, selectedText: string) => {
    if (threadStreaming[threadId]) return;
    const question = (threadDrafts[threadId] ?? "").trim();
    if (!question) return;
    setThreadDrafts((prev) => ({ ...prev, [threadId]: "" }));
    setActiveCommentThreadId(threadId);
    setPinnedThreadId(threadId);
    void streamAssistantReply(threadId, anchorId, selectedText, question);
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
        selectedText,
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

  const commentsByThread = useMemo(() => {
    const map = new Map<string, Comment[]>();
    for (const item of comments) {
      const list = map.get(item.threadId) ?? [];
      list.push(item);
      map.set(item.threadId, list);
    }
    for (const list of map.values()) {
      list.sort((left, right) => left.createdAt - right.createdAt);
    }
    return map;
  }, [comments]);

  const tocOrderMap = useMemo(
    () => new Map(toc.map((item, index) => [item.id, index])),
    [toc]
  );
  const tocTitleMap = useMemo(
    () => new Map(toc.map((item) => [item.id, item.text])),
    [toc]
  );
  const commentThreads = useMemo<CommentThreadView[]>(() => (
    Array.from(commentsByThread.entries())
      .map(([threadId, threadComments]) => {
        const anchorId = threadComments.find((item) => item.anchorId)?.anchorId ?? "";
        const selectedText = threadComments.find((item) => item.selectedText)?.selectedText ?? "";
        const createdAt = threadComments[0]?.createdAt ?? 0;
        return {
          threadId,
          anchorId,
          selectedText,
          comments: threadComments,
          createdAt,
        };
      })
      .filter((item) => item.anchorId)
      .sort((left, right) => {
        const leftOrder = tocOrderMap.get(left.anchorId) ?? Number.MAX_SAFE_INTEGER;
        const rightOrder = tocOrderMap.get(right.anchorId) ?? Number.MAX_SAFE_INTEGER;
        if (leftOrder !== rightOrder) {
          return leftOrder - rightOrder;
        }
        return left.createdAt - right.createdAt;
      })
  ), [commentsByThread, tocOrderMap]);
  const commentThreadIds = useMemo(
    () => commentThreads.map((item) => item.threadId),
    [commentThreads]
  );
  const commentThreadById = useMemo(
    () => new Map(commentThreads.map((item) => [item.threadId, item] as const)),
    [commentThreads]
  );
  const highlightTopByThreadId = useMemo(() => {
    const next = new Map<string, number>();
    for (const highlight of selectionHighlights) {
      if (highlight.segments.length === 0) {
        continue;
      }
      const segmentTop = Math.min(...highlight.segments.map((segment) => segment.top));
      const existing = next.get(highlight.threadId);
      next.set(highlight.threadId, existing === undefined ? segmentTop : Math.min(existing, segmentTop));
    }
    return next;
  }, [selectionHighlights]);
  const measureCommentListOrigin = useCallback(() => {
    if (isCompactPanels) {
      setCommentListOriginTop(null);
      return;
    }
    const container = scrollRef.current;
    const list = commentThreadListRef.current;
    if (!container || !list) {
      return;
    }
    const containerRect = container.getBoundingClientRect();
    const listRect = list.getBoundingClientRect();
    const nextTop = listRect.top - containerRect.top + container.scrollTop;
    setCommentListOriginTop((prev) => {
      if (prev !== null && Math.abs(prev - nextTop) < 0.5) {
        return prev;
      }
      return nextTop;
    });
  }, [isCompactPanels]);
  const threadHeightMap = useMemo(
    () => new Map(Object.entries(threadHeightsById)),
    [threadHeightsById]
  );
  const desiredTopByThreadId = useMemo(() => {
    const next = new Map<string, number>();
    if (isCompactPanels || commentListOriginTop === null) {
      return next;
    }
    for (const thread of commentThreads) {
      const highlightTop = highlightTopByThreadId.get(thread.threadId);
      if (highlightTop === undefined) {
        continue;
      }
      next.set(thread.threadId, Math.max(0, highlightTop - commentListOriginTop - 2));
    }
    return next;
  }, [commentListOriginTop, commentThreads, highlightTopByThreadId, isCompactPanels]);
  const desktopThreadLayout = useMemo(
    () => buildCommentThreadLayout(commentThreads, threadHeightMap, desiredTopByThreadId, pinnedThreadId),
    [commentThreads, desiredTopByThreadId, pinnedThreadId, threadHeightMap]
  );
  const threadCountByAnchor = useMemo(() => {
    const next = new Map<string, number>();
    for (const item of commentThreads) {
      next.set(item.anchorId, (next.get(item.anchorId) ?? 0) + 1);
    }
    return next;
  }, [commentThreads]);
  const commentsForAnchor = useCallback(
    (anchorId: string) => threadCountByAnchor.get(anchorId) ?? 0,
    [threadCountByAnchor]
  );

  useEffect(() => {
    if (!pinnedThreadId) {
      return;
    }
    if (commentThreadById.has(pinnedThreadId)) {
      return;
    }
    setPinnedThreadId(null);
  }, [commentThreadById, pinnedThreadId]);

  useEffect(() => {
    if (isCompactPanels) {
      setCommentListOriginTop(null);
      return;
    }
    const rafId = window.requestAnimationFrame(() => {
      measureCommentListOrigin();
    });
    return () => window.cancelAnimationFrame(rafId);
  }, [
    isCompactPanels,
    measureCommentListOrigin,
    commentThreads.length,
    isCommentCollapsed,
    activeDrawer,
    isCommentVisible,
  ]);

  useEffect(() => {
    if (isCompactPanels) {
      return;
    }
    const handleLayoutChange = () => {
      measureCommentListOrigin();
    };
    const container = scrollRef.current;
    window.addEventListener("resize", handleLayoutChange);
    container?.addEventListener("scroll", handleLayoutChange, { passive: true });

    const observer = typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(() => handleLayoutChange())
      : null;
    if (observer) {
      if (commentPanelRef.current) {
        observer.observe(commentPanelRef.current);
      }
      if (commentThreadListRef.current) {
        observer.observe(commentThreadListRef.current);
      }
    }

    return () => {
      window.removeEventListener("resize", handleLayoutChange);
      container?.removeEventListener("scroll", handleLayoutChange);
      observer?.disconnect();
    };
  }, [isCompactPanels, measureCommentListOrigin]);

  useEffect(() => {
    if (isCompactPanels) {
      setThreadHeightsById({});
      return;
    }
    const next: Record<string, number> = {};
    for (const thread of commentThreads) {
      const node = threadRefs.current.get(thread.threadId);
      if (!node) {
        continue;
      }
      const measured = Math.ceil(node.getBoundingClientRect().height);
      if (measured > 0) {
        next[thread.threadId] = measured;
      }
    }
    setThreadHeightsById((prev) => {
      const prevKeys = Object.keys(prev);
      const nextKeys = Object.keys(next);
      if (prevKeys.length === nextKeys.length) {
        let same = true;
        for (const key of nextKeys) {
          if (prev[key] !== next[key]) {
            same = false;
            break;
          }
        }
        if (same) {
          return prev;
        }
      }
      return next;
    });
  }, [commentThreads, comments, isCompactPanels, threadDrafts, threadStreaming]);

  useEffect(() => {
    if (!activeCommentThreadId) {
      return;
    }
    if (commentThreads.some((item) => item.threadId === activeCommentThreadId)) {
      return;
    }
    setActiveCommentThreadId(commentThreads[0]?.threadId ?? null);
  }, [activeCommentThreadId, commentThreads]);

  useEffect(() => {
    if (!hasRenderedMarkdown || commentThreads.length === 0) {
      return;
    }
    setSelectionHighlights((prev) => {
      const threadIdSet = new Set(commentThreads.map((item) => item.threadId));
      const kept = prev.filter((item) => threadIdSet.has(item.threadId));
      const existing = new Set(kept.map((item) => item.threadId));
      const next: SelectionHighlight[] = [...kept];
      let changed = kept.length !== prev.length;
      for (const thread of commentThreads) {
        if (existing.has(thread.threadId) || !thread.selectedText) {
          continue;
        }
        const segments = buildSelectionSegmentsFromText(thread.anchorId, thread.selectedText);
        if (segments.length === 0) {
          continue;
        }
        next.push({
          id: `highlight-${thread.threadId}`,
          threadId: thread.threadId,
          anchorId: thread.anchorId,
          selectedText: thread.selectedText,
          segments,
        });
        changed = true;
      }
      return changed ? next.slice(0, 200) : prev;
    });
  }, [buildSelectionSegmentsFromText, commentThreads, hasRenderedMarkdown]);

  const activeCommentIndex = useMemo(() => {
    if (commentThreadIds.length === 0) return -1;
    if (activeCommentThreadId) {
      const activeByThreadId = commentThreadIds.indexOf(activeCommentThreadId);
      if (activeByThreadId >= 0) {
        return activeByThreadId;
      }
    }
    if (!activeHeading) return 0;
    const activeOrder = tocOrderMap.get(activeHeading);
    if (activeOrder === undefined) return 0;
    let nearestIndex = 0;
    let nearestDistance = Number.MAX_SAFE_INTEGER;
    for (let i = 0; i < commentThreadIds.length; i += 1) {
      const order = tocOrderMap.get(commentThreads[i]?.anchorId ?? "");
      if (order === undefined) continue;
      const distance = Math.abs(order - activeOrder);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestIndex = i;
      }
    }
    return nearestIndex;
  }, [activeCommentThreadId, activeHeading, commentThreadIds, commentThreads, tocOrderMap]);
  const activeThreadId = activeCommentIndex >= 0
    ? commentThreadIds[activeCommentIndex]
    : null;
  const highlightedThreadId = activeCommentThreadId ?? activeThreadId;

  const focusCommentThread = useCallback((
    threadId: string,
    options: { scrollToDoc?: boolean; pinToSelection?: boolean; scrollThreadIntoView?: boolean } = {}
  ) => {
    const thread = commentThreadById.get(threadId);
    if (!thread) {
      return;
    }
    if (isCompactPanels) {
      setActiveDrawer("comment");
    } else {
      setIsCommentCollapsed(false);
    }
    setActiveCommentThreadId(threadId);
    if (options.pinToSelection) {
      setPinnedThreadId(threadId);
    }
    if (options.scrollToDoc !== false) {
      scrollToHeading(thread.anchorId);
    }
    if (options.scrollThreadIntoView !== false) {
      window.requestAnimationFrame(() => {
        threadRefs.current.get(threadId)?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    }
  }, [commentThreadById, isCompactPanels, scrollToHeading]);

  const locateCommentThread = useCallback((threadId: string) => {
    focusCommentThread(threadId, {
      scrollToDoc: false,
      pinToSelection: true,
      scrollThreadIntoView: isCompactPanels,
    });
  }, [focusCommentThread, isCompactPanels]);

  const jumpCommentThread = useCallback((direction: -1 | 1) => {
    if (commentThreadIds.length === 0) return;
    const baseIndex = activeCommentIndex < 0 ? 0 : activeCommentIndex;
    const nextIndex = Math.min(
      commentThreadIds.length - 1,
      Math.max(0, baseIndex + direction)
    );
    const nextThreadId = commentThreadIds[nextIndex];
    if (!nextThreadId) {
      return;
    }
    focusCommentThread(nextThreadId);
  }, [activeCommentIndex, commentThreadIds, focusCommentThread]);
  const openAiAssistant = useCallback((threadId?: string) => {
    if (!subjectId) return;
    const targetThreadId = threadId ?? activeThreadId ?? commentThreadIds[0] ?? null;
    const targetSessionId = targetThreadId ? (threadSessionIds[targetThreadId] ?? null) : null;
    if (targetSessionId) {
      openAssistant({ sessionId: targetSessionId });
      return;
    }
    openAssistant();
  }, [activeThreadId, commentThreadIds, openAssistant, subjectId, threadSessionIds]);

  const closeCommentPanel = useCallback(() => {
    if (isCompactPanels) {
      closeDrawer();
    } else {
      setIsCommentCollapsed(true);
    }
  }, [closeDrawer, isCompactPanels]);

  const toggleTocCollapse = useCallback((id: string) => {
    setCollapsedTocIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const renderTocNodes = useCallback((nodes: TocTreeNode[], depth: number = 0): React.ReactNode => {
    return nodes.map((node) => {
      const { item } = node;
      const hasChildren = node.children.length > 0;
      const isCollapsed = collapsedTocIds.has(item.id);
      const isActive = activeHeading === item.id;
      const count = commentsForAnchor(item.id);
      const indent = depth * 16;

      return (
        <div key={item.id}>
          <div
            data-toc-id={item.id}
            className={cn(
              "group flex items-center rounded-md transition-all duration-150 relative",
              isActive
                ? "bg-blue-50/80 text-blue-700"
                : "text-slate-600 hover:bg-slate-100/70 hover:text-slate-900"
            )}
            style={{ paddingLeft: indent + 4 }}
          >
            {/* Left active indicator (Feishu-style) */}
            {isActive && (
              <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[2.5px] h-4 rounded-full bg-blue-500" />
            )}

            {/* Expand/collapse arrow */}
            {hasChildren ? (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  toggleTocCollapse(item.id);
                }}
                className={cn(
                  "w-5 h-5 shrink-0 flex items-center justify-center rounded transition-colors",
                  isActive ? "text-blue-500 hover:bg-blue-100" : "text-slate-400 hover:text-slate-600 hover:bg-slate-200/60"
                )}
              >
                <ChevronRight
                  className={cn(
                    "w-3.5 h-3.5 transition-transform duration-200",
                    !isCollapsed && "rotate-90"
                  )}
                />
              </button>
            ) : (
              <span className="w-5 shrink-0" />
            )}

            {/* Title text */}
            <button
              type="button"
              onClick={() => handleTocItemClick(item.id)}
              className={cn(
                "flex-1 min-w-0 text-left py-1.5 pr-1 text-[13px] truncate transition-colors",
                isActive ? "font-semibold" : "font-normal",
                item.level === 1 && "font-semibold text-[13.5px]"
              )}
            >
              {item.text}
            </button>

            {/* Comment count badge */}
            {count > 0 && (
              <span className="shrink-0 w-4 h-4 mr-1 rounded-full bg-blue-100 text-blue-600 text-[10px] flex items-center justify-center font-medium">
                {count}
              </span>
            )}
          </div>

          {/* Children (collapsible) */}
          {hasChildren && !isCollapsed && (
            <div className="overflow-hidden">
              {renderTocNodes(node.children, depth + 1)}
            </div>
          )}
        </div>
      );
    });
  }, [activeHeading, collapsedTocIds, commentsForAnchor, handleTocItemClick, toggleTocCollapse]);

  const tocNav = (
    <nav ref={tocNavRef} className="toc-scroll flex-1 overflow-y-auto py-2 pr-1">
      {tocTree.length > 0 ? (
        renderTocNodes(tocTree)
      ) : (
        <div className="px-3 py-4 text-xs text-slate-400 text-center">暂无目录</div>
      )}
    </nav>
  );

  const commentPanel = (
    <div
      ref={commentPanelRef}
      className={cn(
        "relative w-full",
        isCompactPanels
          ? "h-full rounded-2xl border border-slate-200 bg-white shadow-2xl flex flex-col overflow-hidden"
          : "border-l border-slate-200/90 pl-3 bg-transparent overflow-visible"
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
            {activeStreamingCount > 0 ? `，${activeStreamingCount} 条回复中` : ""}
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
            disabled={activeCommentIndex < 0 || activeCommentIndex >= commentThreadIds.length - 1}
            className={cn(
              "w-7 h-7 rounded-lg transition-colors flex items-center justify-center",
              activeCommentIndex < 0 || activeCommentIndex >= commentThreadIds.length - 1
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
          className="absolute left-3 right-3 z-30 overflow-hidden rounded-2xl border border-slate-200/90 bg-white/95 shadow-[0_28px_56px_-30px_rgba(15,23,42,0.68)] backdrop-blur"
          style={{ top: floatingComment.top }}
        >
          <div className="border-b border-slate-200/80 bg-[linear-gradient(130deg,rgba(236,253,255,0.85),rgba(248,250,252,0.95),rgba(239,246,255,0.85))] px-3 py-2.5">
            <div className="flex items-center gap-2">
              <span className="inline-flex h-6 w-6 items-center justify-center rounded-lg bg-slate-900 text-white shadow-sm">
                <Sparkles className="h-3.5 w-3.5" />
              </span>
              <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">AI Assistant</p>
                <p className="truncate text-xs text-slate-700">&ldquo;{floatingComment.selectedText.slice(0, 60)}&rdquo;</p>
              </div>
            </div>
          </div>
          <div className="space-y-2.5 p-3">
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
              className="w-full resize-none rounded-xl border border-slate-200/90 bg-white px-3 py-2.5 text-sm leading-6 text-slate-800 shadow-inner shadow-slate-100/70 outline-none transition focus:border-slate-300 focus:ring-4 focus:ring-sky-100/80"
              autoFocus
            />
            <div className="flex items-center justify-between">
              <button
                onClick={dismissCommentComposer}
                className="rounded-lg px-2.5 py-1 text-xs text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"
              >
                取消
              </button>
              <button
                onClick={addComment}
                disabled={!floatingInput.trim()}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-medium transition",
                  floatingInput.trim()
                    ? "bg-slate-900 text-white shadow-sm hover:bg-slate-800"
                    : "bg-slate-100 text-slate-300"
                )}
              >
                <Send className="h-3.5 w-3.5" />
                发送
              </button>
            </div>
          </div>
        </div>
      )}

      <div ref={commentViewportRef} className={cn("relative", isCompactPanels && "flex-1 overflow-y-auto")}>
        {isCompactPanels && (
          <>
            <div className="pointer-events-none absolute inset-x-0 top-0 h-12 z-20 bg-gradient-to-b from-slate-50 via-slate-50/80 to-transparent" />
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 z-20 bg-gradient-to-t from-slate-50 via-slate-50/80 to-transparent" />
          </>
        )}
        {!threadHistoryLoaded ? (
          <div className={cn("p-3", isCompactPanels && "h-full")}>
            <div className={cn(
              "flex items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 text-slate-400",
              isCompactPanels ? "h-full" : "h-24"
            )}>
              <Loader2 className="h-4 w-4 animate-spin" />
            </div>
          </div>
        ) : threadHistoryError ? (
          <div className={cn("p-3", isCompactPanels && "h-full")}>
            <div className="rounded-xl border border-rose-200 bg-rose-50/70 px-4 py-4 text-xs leading-5 text-rose-600">
              {threadHistoryError}
            </div>
          </div>
        ) : commentThreads.length === 0 ? (
          <div className={cn("p-3", isCompactPanels && "h-full")}>
            <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-center">
              <p className="text-sm text-slate-500">选中文本后点击“问问AI”即可开始对话</p>
            </div>
          </div>
        ) : isCompactPanels ? (
          <div ref={commentThreadListRef} className="relative p-3 space-y-3">
            {commentThreads.map((thread) => (
              <div
                key={thread.threadId}
                data-thread-id={thread.threadId}
                ref={(node: HTMLDivElement | null) => {
                  if (node) {
                    threadRefs.current.set(thread.threadId, node);
                  } else {
                    threadRefs.current.delete(thread.threadId);
                  }
                }}
              >
                <CommentThread
                  anchorId={thread.anchorId}
                  title={tocTitleMap.get(thread.anchorId) ?? thread.anchorId}
                  comments={thread.comments}
                  selectedText={thread.selectedText}
                  draft={threadDrafts[thread.threadId] ?? ""}
                  isStreaming={Boolean(threadStreaming[thread.threadId])}
                  isActive={highlightedThreadId === thread.threadId}
                  onDraftChange={(value) => updateThreadDraft(thread.threadId, value)}
                  onSend={() => sendThreadReply(thread.threadId, thread.anchorId, thread.selectedText)}
                  onFocus={() => focusCommentThread(thread.threadId, { scrollToDoc: false, scrollThreadIntoView: false })}
                  onJumpToAnchor={(id) => {
                    setActiveCommentThreadId(thread.threadId);
                    setPinnedThreadId(thread.threadId);
                    scrollToHeading(id);
                  }}
                  onOpenAssistant={() => openAiAssistant(thread.threadId)}
                  compactMode
                  isAligned
                />
              </div>
            ))}
          </div>
        ) : (
          <div
            ref={commentThreadListRef}
            className="relative px-3 py-3"
            style={{ minHeight: Math.max(160, desktopThreadLayout.totalHeight + 24) }}
          >
            {commentThreads.map((thread) => {
              const layout = desktopThreadLayout.positions[thread.threadId];
              const top = layout?.top ?? 0;
              return (
                <div
                  key={thread.threadId}
                  data-thread-id={thread.threadId}
                  ref={(node: HTMLDivElement | null) => {
                    if (node) {
                      threadRefs.current.set(thread.threadId, node);
                    } else {
                      threadRefs.current.delete(thread.threadId);
                    }
                  }}
                  className="absolute left-3 right-3 transition-[top] duration-200 ease-out"
                  style={{ top }}
                >
                  <CommentThread
                    anchorId={thread.anchorId}
                    title={tocTitleMap.get(thread.anchorId) ?? thread.anchorId}
                    comments={thread.comments}
                    selectedText={thread.selectedText}
                    draft={threadDrafts[thread.threadId] ?? ""}
                    isStreaming={Boolean(threadStreaming[thread.threadId])}
                    isActive={highlightedThreadId === thread.threadId}
                    onDraftChange={(value) => updateThreadDraft(thread.threadId, value)}
                    onSend={() => sendThreadReply(thread.threadId, thread.anchorId, thread.selectedText)}
                    onFocus={() => focusCommentThread(thread.threadId, {
                      scrollToDoc: false,
                      pinToSelection: true,
                      scrollThreadIntoView: false,
                    })}
                    onJumpToAnchor={(id) => {
                      setActiveCommentThreadId(thread.threadId);
                      setPinnedThreadId(thread.threadId);
                      scrollToHeading(id);
                    }}
                    onOpenAssistant={() => openAiAssistant(thread.threadId)}
                    compactMode={false}
                    isAligned={layout?.aligned ?? false}
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
    <div className="relative flex-1 w-full min-h-full overflow-hidden bg-slate-50 flex flex-row">
      
      {/* Doc + AI Panel Wrapper */}
      <div 
        className={cn(
          "relative h-full transition-all duration-500 ease-[cubic-bezier(0.25,1,0.5,1)] flex flex-col shrink-0 bg-white shadow-[10px_0_20px_-10px_rgba(0,0,0,0.05)] z-10",
          effectiveGraphViewMode === "hidden" ? "w-full" : 
          effectiveGraphViewMode === "split" ? "w-[65%] border-r border-slate-200" : "w-0 overflow-hidden opacity-0"
        )}
      >
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
            <aside className="w-[16%] min-w-[200px] max-w-[280px] h-[calc(100vh-7rem)] max-h-[820px] flex flex-col overflow-hidden">
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

      {!isCompactPanels && isCommentCollapsed && (
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
        className="h-full overflow-y-auto relative doc-scroll-container content-scroll"
        onMouseUp={handleTextSelect}
      >
        <div
          className={cn(
            "min-h-full pr-4 transition-[padding-left,padding-right] duration-300 pl-4 md:pl-6",
            isCompactPanels
              ? "lg:pr-6 lg:pl-6"
              : "lg:pr-6",
            isCompactPanels
              ? null
              : isTocCollapsed
                ? "lg:pl-20"
                : "lg:pl-[17%]"
          )}
        >
          <div className="mx-auto max-w-[1800px] px-6 py-8">
            <div
              ref={contentAreaRef}
              className="feishu-doc-content mx-auto flex min-h-full w-full max-w-[1380px] items-start gap-3"
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
                    <DocGeneratingState
                      isFetching={docMarkdownQuery.isFetching}
                      progress={buildProgress}
                      statusText={buildStatusText}
                    />
                  ) : showDocBuildFailureState ? (
                    <DocLoadErrorState
                      message={buildStatusText}
                      onRetry={() => {
                        void docMarkdownQuery.refetch();
                      }}
                    />
                  ) : showDocEmptyState ? (
                    <DocEmptyState />
                  ) : (
                    <>
                      {showDocUpdatingBanner && (
                        <DocUpdatingBanner
                          progress={buildProgress}
                          statusText={buildStatusText}
                          isFetching={docMarkdownQuery.isFetching}
                          viewMode={effectiveDocViewMode}
                          hasLiveVersion={hasLiveDocMarkdown}
                          hasDraftVersion={hasDraftDocMarkdown}
                          liveUpdatedAt={liveUpdatedAt}
                          draftUpdatedAt={draftUpdatedAt}
                          onViewModeChange={setDocViewMode}
                        />
                      )}
                      <DocMarkdown content={renderedMarkdown} />
                    </>
                  )}
                </article>
                {!isCompactPanels && !isCommentCollapsed && (
                  <aside className="hidden lg:block w-[22%] min-w-[260px] max-w-[380px] shrink-0 py-8">
                    {commentPanel}
                  </aside>
                )}
            </div>
          </div>

          {selectionHighlights.map((highlight) => (
            <div key={highlight.id}>
              {highlight.segments.map((segment, index) => (
                <button
                  key={`${highlight.id}-${index}`}
                  type="button"
                  onClick={() => locateCommentThread(highlight.threadId)}
                  data-highlight-thread-id={highlight.threadId}
                  className={cn(
                    "group absolute z-30 rounded-[3px] transition-colors focus-visible:outline-none",
                    highlightedThreadId === highlight.threadId
                      ? "bg-blue-100/45 ring-1 ring-blue-300/70 shadow-[0_0_0_1px_rgba(59,130,246,0.18)]"
                      : "bg-transparent hover:bg-amber-100/35 focus-visible:ring-2 focus-visible:ring-amber-300/70"
                  )}
                  style={{
                    top: segment.top,
                    left: segment.left,
                    width: segment.width,
                    height: segment.height,
                  }}
                  title={`定位问答：${highlight.selectedText}`}
                  aria-label="定位划词问答"
                >
                  <span
                    className={cn(
                      "pointer-events-none absolute inset-x-0 bottom-0 rounded-full transition-all",
                      highlightedThreadId === highlight.threadId
                        ? "h-[2.5px] bg-blue-500 shadow-[0_0_0_1px_rgba(59,130,246,0.28),0_4px_10px_-6px_rgba(37,99,235,0.85)]"
                        : "h-[1.5px] bg-amber-300/90 shadow-[0_0_0_1px_rgba(245,158,11,0.24),0_2px_8px_-6px_rgba(245,158,11,0.7)] group-hover:h-[2px] group-hover:bg-amber-400/95"
                    )}
                  />
                </button>
              ))}
            </div>
          ))}

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
              <div className="inline-flex items-center gap-2 rounded-2xl border border-slate-200/90 bg-white/95 px-2 py-1.5 shadow-[0_22px_44px_-28px_rgba(15,23,42,0.82)] backdrop-blur">
                <span className="max-w-40 truncate px-1 text-[11px] text-slate-500">
                  &ldquo;{floatingToolbar.selectedText.slice(0, 60)}&rdquo;
                </span>
                <button
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={openCommentComposer}
                  className="inline-flex h-8 items-center gap-1.5 rounded-xl bg-slate-900 px-3 text-xs font-medium text-white shadow-sm transition hover:bg-slate-800"
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  问问AI
                </button>
              </div>
            </div>
          )}

        </div>
      </div>
      </div>

      {/* Unified Sliding Handle for All States */}
      <div 
        className={cn(
          "absolute top-1/2 -translate-y-1/2 z-[70] transition-all duration-500 ease-[cubic-bezier(0.25,1,0.5,1)] flex items-center justify-center gap-[2px]",
          effectiveGraphViewMode === "hidden" ? "right-0 opacity-90 hover:opacity-100" : 
          effectiveGraphViewMode === "split" ? "right-[35%] translate-x-1/2 opacity-60 hover:opacity-100" : 
          "left-0 opacity-90 hover:opacity-100"
        )}
      >
        {effectiveGraphViewMode !== "full" && (
          <button 
            onClick={openGraphPanel}
            className="flex items-center justify-center h-[72px] w-7 rounded-l-full bg-slate-100/50 backdrop-blur-md border border-slate-200/50 shadow-[0_2px_8px_rgba(0,0,0,0.04)] text-slate-500 transition-all duration-300 hover:w-10 hover:bg-white/95 hover:shadow-[0_4px_16px_rgba(0,0,0,0.1)] hover:text-blue-600 hover:border-slate-200/80 focus:outline-none"
            title={effectiveGraphViewMode === "hidden" ? "打开知识图谱" : "全屏图谱"}
          >
            <ChevronLeft className="h-5 w-5 ml-1 transition-transform group-hover:-translate-x-0.5" />
          </button>
        )}
        
        {effectiveGraphViewMode !== "hidden" && (
          <button 
            onClick={closeGraphPanel}
            className="flex items-center justify-center h-[72px] w-7 rounded-r-full bg-slate-100/50 backdrop-blur-md border border-slate-200/50 shadow-[0_2px_8px_rgba(0,0,0,0.04)] text-slate-500 transition-all duration-300 hover:w-10 hover:bg-white/95 hover:shadow-[0_4px_16px_rgba(0,0,0,0.1)] hover:text-blue-600 hover:border-slate-200/80 focus:outline-none"
            title={effectiveGraphViewMode === "full" ? (isCompactPanels ? "收起图谱" : "分屏视图") : "收起图谱"}
          >
            <ChevronRight className="h-5 w-5 mr-1 transition-transform group-hover:translate-x-0.5" />
          </button>
        )}
      </div>

      {/* Graph Area Wrapper */}
      <div 
        className={cn(
          "relative h-full transition-all duration-500 ease-[cubic-bezier(0.25,1,0.5,1)] bg-slate-50 shrink-0 border-l border-slate-200/50",
          effectiveGraphViewMode === "hidden" ? "w-0 overflow-hidden opacity-0" : 
          effectiveGraphViewMode === "split" ? "w-[35%]" : "w-full"
        )}
      >
        {subjectId && effectiveGraphViewMode !== "hidden" && (
          <Suspense fallback={<GraphPanelFallback />}>
            <KnowledgeGraphSidePanel 
              subjectId={subjectId} 
            />
          </Suspense>
        )}
      </div>


    </div>
  );
}

