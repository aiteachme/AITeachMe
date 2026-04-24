import { memo, Suspense, lazy, useState, useRef, useEffect, useMemo, useCallback } from "react";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import {
  FileText,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  ChevronDown,
  ChevronUp,
  Send,
  Bot,
  Network,
  Loader2,
  Sparkles,
  RefreshCw,
  ExternalLink,
  SlidersHorizontal,
} from "lucide-react";
import { cn } from "../lib/utils";
import { getApiErrorMessage, postSseJson } from "../api/client";
import { apiClient } from "../api/client";
import { useSubjectAiAssistant } from "../components/ai/SubjectAiAssistant";
import { useResizablePanel } from "../hooks/useResizablePanel";
import {
  BuildView,
  type DocViewMode,
  useDocBuildProgress,
  useDocMarkdown,
} from "../components/knowledge-docs";
import { SubjectVectorNotice } from "../components/knowledge-graph/SubjectVectorNotice";
import { MarkdownViewer, preprocessLaTeX } from "../components/ui/MarkdownViewer";

const KnowledgeGraphSidePanel = lazy(() =>
  import("../components/knowledge-graph/KnowledgeGraphSidePanel").then((module) => ({
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
  selectionContentTop: number;
  top: number;
  segments: HighlightSegment[];
}

interface SelectionContextPayload {
  selected_text: string;
  anchor_id: string;
  anchor_title?: string;
  heading_path: string[];
  before_text?: string;
  after_text?: string;
  section_title?: string;
  section_excerpt?: string;
  section_truncated: boolean;
  local_context_truncated: boolean;
}

interface FloatingToolbar {
  anchorId: string;
  selectedText: string;
  top: number;
  left: number;
  selectionViewportTop: number;
  selectionContentTop: number;
}

interface HighlightSegment {
  top: number;
  left: number;
  width: number;
  height: number;
}

interface KnowledgeDocsViewPrefs {
  widePage: boolean;
  showToc: boolean;
  showCommentPanel: boolean;
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

interface TocScrollThumbStyle {
  top: number;
  height: number;
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

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatTime(ts: number): string {
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function isHistoryComment(comment: Pick<Comment, "id">): boolean {
  return comment.id.startsWith("history-");
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

const TOC_DRAWER_BREAKPOINT = 960;
const COMMENT_DRAWER_BREAKPOINT = 1280;
const THREAD_HISTORY_PAGE_SIZE = 100;
const KNOWLEDGE_DOCS_VIEW_PREFS_VERSION = 1;
const FLOATING_COMPOSER_THREAD_ID = "__floating-composer__";
const SELECTION_SELECTED_TEXT_LIMIT = 1200;
const SELECTION_LOCAL_CONTEXT_CHARS = 900;
const SELECTION_SECTION_CONTEXT_CHARS = 3200;

function getHeadingActivationOffset(container: HTMLElement): number {
  return Math.min(128, Math.max(76, container.clientHeight * 0.18));
}

function createDefaultKnowledgeDocsViewPrefs(): KnowledgeDocsViewPrefs {
  return {
    widePage: false,
    showToc: true,
    showCommentPanel: true,
  };
}

function normalizeKnowledgeDocsViewPrefs(raw: unknown): KnowledgeDocsViewPrefs {
  const defaults = createDefaultKnowledgeDocsViewPrefs();
  if (!raw || typeof raw !== "object") {
    return defaults;
  }
  const candidate = raw as Partial<KnowledgeDocsViewPrefs>;
  return {
    widePage: candidate.widePage === true,
    showToc: candidate.showToc !== false,
    showCommentPanel: candidate.showCommentPanel !== false,
  };
}

function knowledgeDocsViewPrefsStorageKey(subjectId?: string): string {
  return `aiteachme:knowledge-docs-view:v${KNOWLEDGE_DOCS_VIEW_PREFS_VERSION}:${subjectId ?? "default"}`;
}

function readKnowledgeDocsViewPrefs(subjectId?: string): KnowledgeDocsViewPrefs {
  if (!subjectId || typeof window === "undefined") {
    return createDefaultKnowledgeDocsViewPrefs();
  }
  try {
    const raw = window.localStorage.getItem(knowledgeDocsViewPrefsStorageKey(subjectId));
    if (!raw) {
      return createDefaultKnowledgeDocsViewPrefs();
    }
    return normalizeKnowledgeDocsViewPrefs(JSON.parse(raw));
  } catch {
    return createDefaultKnowledgeDocsViewPrefs();
  }
}

function persistKnowledgeDocsViewPrefs(subjectId: string | undefined, prefs: KnowledgeDocsViewPrefs) {
  if (!subjectId || typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(
      knowledgeDocsViewPrefsStorageKey(subjectId),
      JSON.stringify({
        version: KNOWLEDGE_DOCS_VIEW_PREFS_VERSION,
        ...prefs,
      }),
    );
  } catch {
    // Ignore storage failures and fall back to in-memory state.
  }
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

function highlightSegmentsEqual(a: HighlightSegment[], b: HighlightSegment[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (
      Math.abs(a[i].top - b[i].top) > 0.5 ||
      Math.abs(a[i].left - b[i].left) > 0.5 ||
      Math.abs(a[i].width - b[i].width) > 0.5 ||
      Math.abs(a[i].height - b[i].height) > 0.5
    ) {
      return false;
    }
  }
  return true;
}

function compactTocItems(items: TocItem[]): TocItem[] {
  const compacted: TocItem[] = [];
  for (const item of items) {
    const previous = compacted[compacted.length - 1];
    if (
      previous &&
      previous.text.trim() === item.text.trim() &&
      item.level === previous.level + 1
    ) {
      continue;
    }
    compacted.push(item);
  }
  return compacted;
}

function buildDefaultCollapsedTocIds(items: TocItem[]): Set<string> {
  const collapsed = new Set<string>();
  for (let index = 0; index < items.length; index += 1) {
    const item = items[index];
    const next = items[index + 1];
    if (item.level === 2 && next && next.level > item.level) {
      collapsed.add(item.id);
    }
  }
  return collapsed;
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

function findTocPath(roots: TocTreeNode[], targetId: string): TocTreeNode[] {
  const path: TocTreeNode[] = [];
  const search = (nodes: TocTreeNode[]): boolean => {
    for (const node of nodes) {
      if (node.item.id === targetId) return true;
      path.push(node);
      if (search(node.children)) return true;
      path.pop();
    }
    return false;
  };
  return search(roots) ? path : [];
}

function resolveVisibleActiveTocId(
  roots: TocTreeNode[],
  activeId: string,
  collapsedIds: Set<string>
): string {
  if (!activeId) return "";
  const ancestorPath = findTocPath(roots, activeId);
  for (const ancestor of ancestorPath) {
    if (collapsedIds.has(ancestor.item.id)) {
      return ancestor.item.id;
    }
  }
  return activeId;
}

function getHeadingLevel(node: Element | null | undefined): number {
  if (!node) return 0;
  const level = Number(node.tagName.replace("H", ""));
  return Number.isInteger(level) ? level : 0;
}

function normalizeSelectionContextText(text: string): string {
  return text
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function clipContextText(text: string, limit: number): string {
  const normalized = normalizeSelectionContextText(text);
  if (normalized.length <= limit) return normalized;
  return `${normalized.slice(0, Math.max(0, limit - 1)).trimEnd()}…`;
}

function collectNodeText(nodes: Node[]): string {
  return normalizeSelectionContextText(
    nodes
      .map((node) => node.textContent ?? "")
      .filter(Boolean)
      .join("\n")
  );
}

function findHeadingPath(contentRoot: HTMLElement, anchorId: string): HTMLElement[] {
  const headings = Array.from(contentRoot.querySelectorAll<HTMLElement>("[data-heading-id]"));
  const targetIndex = headings.findIndex((heading) => heading.getAttribute("data-heading-id") === anchorId);
  if (targetIndex < 0) return [];

  const stack: HTMLElement[] = [];
  for (let index = 0; index <= targetIndex; index += 1) {
    const heading = headings[index];
    const level = getHeadingLevel(heading);
    if (!level) continue;
    while (stack.length > 0 && getHeadingLevel(stack[stack.length - 1]) >= level) {
      stack.pop();
    }
    stack.push(heading);
  }
  return stack;
}

function collectSectionNodes(heading: HTMLElement): Node[] {
  const boundaryLevel = getHeadingLevel(heading);
  const nodes: Node[] = [heading];
  let node = heading.nextSibling;
  while (node) {
    if (node instanceof HTMLElement && node.hasAttribute("data-heading-id")) {
      const level = getHeadingLevel(node);
      if (level > 0 && level <= boundaryLevel) break;
    }
    nodes.push(node);
    node = node.nextSibling;
  }
  return nodes;
}

function findSelectionIndex(sectionText: string, selectedText: string): number {
  const normalizedSelection = normalizeSelectionContextText(selectedText);
  if (!normalizedSelection) return -1;

  const exactIndex = sectionText.indexOf(normalizedSelection);
  if (exactIndex >= 0) return exactIndex;

  const compactSection = sectionText.replace(/\s+/g, "");
  const compactSelection = normalizedSelection.replace(/\s+/g, "");
  if (!compactSelection) return -1;
  const compactIndex = compactSection.indexOf(compactSelection.slice(0, Math.min(120, compactSelection.length)));
  if (compactIndex < 0) return -1;

  let compactCursor = 0;
  for (let index = 0; index < sectionText.length; index += 1) {
    if (/\s/.test(sectionText[index])) continue;
    if (compactCursor === compactIndex) return index;
    compactCursor += 1;
  }
  return -1;
}

function excerptAroundSelection(sectionText: string, selectedText: string, maxChars: number): { text: string; truncated: boolean } {
  if (sectionText.length <= maxChars) {
    return { text: sectionText, truncated: false };
  }

  const selectionIndex = findSelectionIndex(sectionText, selectedText);
  const selectedLength = Math.max(clipContextText(selectedText, SELECTION_SELECTED_TEXT_LIMIT).length, 1);
  const fallbackStart = Math.max(0, Math.floor((sectionText.length - maxChars) / 2));
  const start = selectionIndex >= 0
    ? Math.max(0, selectionIndex - Math.floor(maxChars * 0.42))
    : fallbackStart;
  const adjustedStart = Math.min(start, Math.max(0, sectionText.length - maxChars));
  const end = Math.min(sectionText.length, Math.max(adjustedStart + maxChars, selectionIndex + selectedLength));
  const finalStart = Math.max(0, Math.min(adjustedStart, end - maxChars));
  const prefix = finalStart > 0 ? "… " : "";
  const suffix = end < sectionText.length ? " …" : "";
  return {
    text: `${prefix}${sectionText.slice(finalStart, end).trim()}${suffix}`,
    truncated: true,
  };
}

function buildSelectionContextPayload(
  contentRoot: HTMLElement | null,
  anchorId: string,
  selectedText: string
): SelectionContextPayload {
  const fallbackSelectedText = clipContextText(selectedText, SELECTION_SELECTED_TEXT_LIMIT);
  if (!contentRoot) {
    return {
      selected_text: fallbackSelectedText,
      anchor_id: anchorId,
      heading_path: [],
      section_truncated: false,
      local_context_truncated: false,
    };
  }

  const headingPath = findHeadingPath(contentRoot, anchorId);
  const currentHeading = headingPath[headingPath.length - 1] ?? null;
  const currentLevel = getHeadingLevel(currentHeading);
  const sectionHeading = currentLevel >= 3
    ? [...headingPath].reverse().find((heading) => getHeadingLevel(heading) < currentLevel) ?? currentHeading
    : currentHeading;
  const sectionText = sectionHeading ? collectNodeText(collectSectionNodes(sectionHeading)) : normalizeSelectionContextText(contentRoot.textContent ?? "");
  const selectedIndex = findSelectionIndex(sectionText, selectedText);
  const normalizedSelectedText = normalizeSelectionContextText(selectedText);
  const beforeRaw = selectedIndex >= 0 ? sectionText.slice(0, selectedIndex) : "";
  const afterRaw = selectedIndex >= 0 ? sectionText.slice(selectedIndex + normalizedSelectedText.length) : "";
  const beforeText = beforeRaw.length > SELECTION_LOCAL_CONTEXT_CHARS
    ? `… ${beforeRaw.slice(-SELECTION_LOCAL_CONTEXT_CHARS).trimStart()}`
    : beforeRaw;
  const afterText = afterRaw.length > SELECTION_LOCAL_CONTEXT_CHARS
    ? `${afterRaw.slice(0, SELECTION_LOCAL_CONTEXT_CHARS).trimEnd()} …`
    : afterRaw;
  const sectionExcerpt = excerptAroundSelection(sectionText, selectedText, SELECTION_SECTION_CONTEXT_CHARS);

  return {
    selected_text: fallbackSelectedText,
    anchor_id: anchorId,
    anchor_title: currentHeading?.textContent?.trim() || undefined,
    heading_path: headingPath
      .map((heading) => heading.textContent?.trim() ?? "")
      .filter(Boolean),
    before_text: beforeText ? clipContextText(beforeText, SELECTION_LOCAL_CONTEXT_CHARS + 4) : undefined,
    after_text: afterText ? clipContextText(afterText, SELECTION_LOCAL_CONTEXT_CHARS + 4) : undefined,
    section_title: sectionHeading?.textContent?.trim() || undefined,
    section_excerpt: sectionExcerpt.text ? clipContextText(sectionExcerpt.text, SELECTION_SECTION_CONTEXT_CHARS + 4) : undefined,
    section_truncated: sectionExcerpt.truncated,
    local_context_truncated: beforeRaw.length > SELECTION_LOCAL_CONTEXT_CHARS || afterRaw.length > SELECTION_LOCAL_CONTEXT_CHARS,
  };
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
    let cursor = desiredTopByThreadId.get(threads[0].threadId) ?? 0;
    for (let i = 0; i < threads.length; i += 1) {
      const desiredTop = desiredTopByThreadId.get(threads[i].threadId);
      const top = desiredTop === undefined ? cursor : (i === 0 ? desiredTop : Math.max(cursor, desiredTop));
      positions[i] = top;
      cursor = top + heights[i] + gap;
    }
  } else {
    const pinnedDesiredTop = desiredTopByThreadId.get(threads[pinnedIndex].threadId) ?? 0;
    positions[pinnedIndex] = pinnedDesiredTop;

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

const DocMarkdown = memo(function DocMarkdown({
  content,
  subjectId,
}: {
  content: string;
  subjectId?: string;
}) {
  return (
    <MarkdownViewer
      content={content}
      variant="document"
      headingAnchors
      assetSubject={subjectId}
    />
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
      ? "草稿仅用于预览当前构建结果，正式版会在文档发布完成后自动刷新。"
      : hasDraftVersion
        ? "正式版会持续可用；如果想提前看本轮结果，可以切换到草稿预览。"
        : hasLiveVersion
          ? "当前会继续显示旧正式版，待新正式版发布后这里会自动刷新。"
          : "文档草稿一旦可用，这里会直接切换显示预览内容。";
  const liveLabel = formatDocTimestamp(liveUpdatedAt);
  const draftLabel = formatDocTimestamp(draftUpdatedAt);

  return (
    <section className="mb-5 rounded-2xl border border-stone-200 bg-stone-50 px-4 py-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-slate-900">{title}</p>
          <p className="mt-1 text-[13px] leading-5 text-slate-600">{description}</p>
        </div>
        {(hasLiveVersion || hasDraftVersion) && (
          <div className="inline-flex rounded-full border border-stone-200 bg-white/80 p-1 shadow-sm">
            <button
              type="button"
              disabled={!hasLiveVersion}
              onClick={() => hasLiveVersion && onViewModeChange("live")}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                viewMode === "live"
                  ? "bg-stone-800 text-white shadow-sm"
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
    <section className="rounded-3xl border border-dashed border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-7 text-center shadow-sm dark:shadow-[0_4px_16px_rgba(0,0,0,0.2)]">
      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400">
        <FileText className="h-6 w-6" />
      </div>
      <h2 className="mt-4 text-lg font-semibold text-slate-900 dark:text-slate-100">暂时还没有知识文档</h2>
      <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-400">
        先回到文件页发起一次知识文档构建，这里会展示最终发布的 merged 文档。
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
  defaultCollapsed = false,
}: {
  comment: Comment;
  defaultCollapsed?: boolean;
}) {
  const isAssistant = comment.role === "assistant";
  const contentRef = useRef<HTMLDivElement>(null);
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed);
  const [canCollapse, setCanCollapse] = useState(false);

  useEffect(() => {
    const rafId = window.requestAnimationFrame(() => {
      const node = contentRef.current;
      if (!node) return;
      const lineHeight = Number.parseFloat(window.getComputedStyle(node).lineHeight) || 18;
      const nextCanCollapse = node.scrollHeight > lineHeight * 3 + 8;
      setCanCollapse(nextCanCollapse);
      if (!nextCanCollapse) {
        setIsCollapsed(false);
      }
    });
    return () => window.cancelAnimationFrame(rafId);
  }, [comment.content]);

  return (
    <div
      className={cn(
        "w-full rounded-lg border transition-colors",
        isAssistant
          ? "border-sky-100 bg-sky-50/60"
          : "border-slate-200 bg-white"
      )}
    >
      <div className="px-3 py-2">
        <div className="mb-1.5 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <div
              className={cn(
                "flex h-5 w-5 items-center justify-center rounded-md text-[10px] font-semibold text-white",
                isAssistant ? "bg-sky-500" : "bg-slate-900"
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
          <div className="flex items-center gap-1">
            {comment.streaming && <Loader2 className="h-3.5 w-3.5 animate-spin text-sky-400" />}
            {canCollapse && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setIsCollapsed((prev) => !prev);
                }}
                className={cn(
                  "inline-flex h-6 items-center justify-center rounded-md transition",
                  isCollapsed
                    ? isAssistant
                      ? "gap-1 bg-sky-100 px-2 text-[10px] font-medium text-sky-700 hover:bg-sky-200"
                      : "gap-1 bg-slate-100 px-2 text-[10px] font-medium text-slate-700 hover:bg-slate-200"
                    : "w-6 text-slate-400 hover:bg-white/80 hover:text-slate-700"
                )}
                aria-label={isCollapsed ? "展开消息" : "收起消息"}
                title={isCollapsed ? "展开消息" : "收起消息"}
              >
                {isCollapsed ? (
                  <>
                    <ChevronDown className="h-3.5 w-3.5" />
                    <span>展开</span>
                  </>
                ) : (
                  <ChevronUp className="h-3.5 w-3.5" />
                )}
              </button>
            )}
          </div>
        </div>
        <div
          ref={contentRef}
          className={cn(
            "relative text-xs leading-relaxed text-slate-700",
            isCollapsed && "max-h-[5.1rem] overflow-hidden rounded-md"
          )}
        >
          {isAssistant ? (
            <CommentMarkdown content={comment.content} />
          ) : (
            <p className="whitespace-pre-wrap">
              {comment.content}
            </p>
          )}
          {isCollapsed && (
            <>
              <div
                className={cn(
                  "pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t via-70% to-transparent",
                  isAssistant ? "from-sky-50 via-sky-50/95" : "from-white via-white/95"
                )}
              />
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setIsCollapsed(false);
                }}
                className={cn(
                  "absolute bottom-1 right-1 inline-flex h-6 items-center gap-1 rounded-md border px-2 text-[10px] font-medium shadow-sm transition",
                  isAssistant
                    ? "border-sky-200 bg-white/95 text-sky-700 hover:border-sky-300 hover:bg-sky-50"
                    : "border-slate-200 bg-white/95 text-slate-700 hover:border-slate-300 hover:bg-slate-50"
                )}
                aria-label="展开完整内容"
                title="展开完整内容"
              >
                <ChevronDown className="h-3 w-3" />
                已收起，展开全部
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function CommentThread({
  anchorId,
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
  const [isThreadCollapsed, setIsThreadCollapsed] = useState(false);
  const selectedPreview = selectedText.trim() || "定位划词位置";

  return (
    <section
      onClick={onFocus}
      className={cn(
        "rounded-lg border bg-white overflow-hidden transition-colors",
        isActive
          ? "border-sky-300 bg-sky-50/25"
          : "border-slate-200",
        isAligned && !isActive && "border-slate-300/80"
      )}
    >
      <div className="px-3 py-2 border-b border-slate-200/80 bg-white flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => onJumpToAnchor(anchorId)}
          title={selectedText ? `定位划词：${selectedText}` : "定位划词位置"}
          className={cn(
            "group flex min-w-0 flex-1 items-center gap-2 rounded-md px-1 py-0.5 text-left transition-colors hover:bg-slate-50",
            isActive && "bg-sky-50/70"
          )}
        >
          <span
            className={cn(
              "h-5 w-[3px] shrink-0 rounded-full",
              isActive ? "bg-sky-400" : "bg-slate-300"
            )}
          />
          <span
            className={cn(
              "min-w-0 truncate text-[11px] font-medium",
              isActive ? "text-sky-700" : "text-slate-600 group-hover:text-slate-800"
            )}
          >
            {selectedPreview}
          </span>
        </button>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onOpenAssistant();
            }}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-500 transition hover:border-sky-200 hover:bg-sky-50 hover:text-sky-700"
            aria-label="在 AI 面板继续对话"
            title="在 AI 面板继续对话"
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </button>
          <span className="shrink-0 rounded-full bg-slate-100 text-slate-600 text-[10px] px-2 py-0.5 font-medium">
            {comments.length}
          </span>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setIsThreadCollapsed((prev) => !prev);
            }}
            className="flex h-6 w-6 items-center justify-center rounded-md text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
            aria-label={isThreadCollapsed ? "展开问答" : "收起问答"}
            title={isThreadCollapsed ? "展开问答" : "收起问答"}
          >
            {isThreadCollapsed ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronUp className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>
      {!isThreadCollapsed && (
        <>
          <div className={cn("p-2 space-y-2", compactMode ? "max-h-64 overflow-y-auto" : "overflow-visible")}>
            {comments.map((comment) => (
              <CommentCard
                key={comment.id}
                comment={comment}
                defaultCollapsed={isHistoryComment(comment)}
              />
            ))}
          </div>
          <div className="border-t border-slate-200 bg-white p-2">
            <textarea
              value={draft}
              onChange={(e) => onDraftChange(e.target.value)}
              onClick={(e) => e.stopPropagation()}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  onSend();
                }
              }}
              rows={2}
              disabled={isStreaming}
              placeholder={isStreaming ? "AI 正在回复..." : "继续追问这段内容..."}
              className="w-full resize-none rounded-md border border-slate-200 px-3 py-2 text-xs text-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-100 focus:border-sky-300 disabled:bg-slate-50 disabled:text-slate-400"
            />
            <div className="mt-2 flex items-center justify-end">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onSend();
                }}
                disabled={!draft.trim() || isStreaming}
                className={cn(
                  "inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors",
                  draft.trim() && !isStreaming
                    ? "bg-slate-900 text-white hover:bg-slate-800"
                    : "bg-slate-100 text-slate-300"
                )}
              >
                {isStreaming ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
                发送
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  KnowledgeDocsPage                                                  */
/* ------------------------------------------------------------------ */

export function KnowledgeDocsPage() {
  const { openAssistant } = useSubjectAiAssistant();
  const {
    subjectId,
    docMarkdownQuery,
    buildMeta,
    buildPreview,
    buildMetrics,
    buildStatus,
    liveUpdatedAt,
    draftUpdatedAt,
    hasLiveDocMarkdown,
    hasDraftDocMarkdown,
    isBuildActive,
    isBuildFailure,
    isRequestedBuildReady,
    isWaitingForRequestedBuild,
    setDocViewMode,
    effectiveDocViewMode,
    renderedMarkdown,
    hasRenderedMarkdown,
    showDocGeneratingState,
    showDocBuildFailureState,
    showDocEmptyState,
    showDocUpdatingBanner,
    sourceFiles,
    sourceFilesFetching,
  } = useDocMarkdown();
  const { buildProgress, buildStatusText } = useDocBuildProgress({
    buildMeta,
    buildStatus,
    hasLiveDocMarkdown,
    hasDraftDocMarkdown,
    isBuildActive,
    isBuildFailure,
    isRequestedBuildReady,
    isWaitingForRequestedBuild,
  });

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
  const [isAutoCommentHighlightSuppressed, setIsAutoCommentHighlightSuppressed] = useState(false);
  const [commentListOriginTop, setCommentListOriginTop] = useState<number | null>(null);
  const [desktopCommentScrollMinHeight, setDesktopCommentScrollMinHeight] = useState(0);
  const [threadHeightsById, setThreadHeightsById] = useState<Record<string, number>>({});
  const [isTocCollapsed, setIsTocCollapsed] = useState(false);
  const [isCommentCollapsed, setIsCommentCollapsed] = useState(false);
  const [collapsedTocIds, setCollapsedTocIds] = useState<Set<string>>(new Set());

  // Floating selection toolbar state
  const [floatingToolbar, setFloatingToolbar] = useState<FloatingToolbar | null>(null);
  const [floatingComment, setFloatingComment] = useState<FloatingComment | null>(null);
  const [floatingInput, setFloatingInput] = useState("");
  const [floatingComposerHeight, setFloatingComposerHeight] = useState(236);
  const [viewportWidth, setViewportWidth] = useState(() =>
    typeof window !== "undefined" ? window.innerWidth : COMMENT_DRAWER_BREAKPOINT
  );
  const [viewPrefs, setViewPrefs] = useState<KnowledgeDocsViewPrefs>(() => readKnowledgeDocsViewPrefs(subjectId));
  const [isSettingsPanelOpen, setIsSettingsPanelOpen] = useState(false);
  const [activeDrawer, setActiveDrawer] = useState<"toc" | "comment" | null>(null);
  const [isTocScrollbarVisible, setIsTocScrollbarVisible] = useState(false);
  const [tocScrollThumbStyle, setTocScrollThumbStyle] = useState<TocScrollThumbStyle>({ top: 0, height: 0 });

  const [isGraphDrawerOpen, setIsGraphDrawerOpen] = useState(false);
  const initialViewportWidth = typeof window !== "undefined" ? window.innerWidth : 1200;
  const isNarrowInitialViewport = initialViewportWidth < 640;
  const { width: graphPanelWidth, isDragging: isGraphDragging, handleMouseDown: handleGraphMouseDown } = useResizablePanel({
    defaultWidth: isNarrowInitialViewport ? initialViewportWidth : initialViewportWidth * 0.6,
    minWidth: isNarrowInitialViewport ? initialViewportWidth : 400,
    maxWidth: isNarrowInitialViewport ? initialViewportWidth : initialViewportWidth * 0.8,
  });

  const scrollRef = useRef<HTMLDivElement>(null);
  const contentAreaRef = useRef<HTMLDivElement>(null);
  const floatingRef = useRef<HTMLDivElement>(null);
  const commentPanelRef = useRef<HTMLDivElement>(null);
  const commentViewportRef = useRef<HTMLDivElement>(null);
  const commentThreadListRef = useRef<HTMLDivElement>(null);
  const desktopCommentTrackRef = useRef<HTMLDivElement>(null);
  const floatingComposerCardRef = useRef<HTMLDivElement>(null);
  const floatingComposerTextareaRef = useRef<HTMLTextAreaElement>(null);
  const settingsPanelRef = useRef<HTMLDivElement>(null);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const selectedRangeRef = useRef<Range | null>(null);
  const threadRefs = useRef(new Map<string, HTMLDivElement>());
  const headingFlashTimersRef = useRef(new Map<string, number>());
  const tocNavRef = useRef<HTMLElement>(null);
  const tocDefaultInitializedRef = useRef(false);
  const streamControllersRef = useRef(new Map<string, AbortController>());
  const tocScrollbarTimerRef = useRef<number | null>(null);
  const tocAutoScrollingRef = useRef(false);
  const tocAutoScrollReleaseTimerRef = useRef<number | null>(null);
  const activeHeadingLockRef = useRef<string | null>(null);
  const lastAutoCommentHighlightHeadingRef = useRef(activeHeading);

  const isCompactToc = viewportWidth < TOC_DRAWER_BREAKPOINT;
  const isCompactComment = viewportWidth < COMMENT_DRAWER_BREAKPOINT;
  const isCompactPanels = isCompactToc || isCompactComment;
  const hasCompactTocControl = isCompactToc && viewPrefs.showToc;
  const hasCompactCommentControl = isCompactComment && viewPrefs.showCommentPanel;
  const isTocVisible = viewPrefs.showToc && (isCompactToc ? activeDrawer === "toc" : !isTocCollapsed);
  const isCommentVisible = viewPrefs.showCommentPanel && (isCompactComment ? activeDrawer === "comment" : !isCommentCollapsed);
  const showDesktopCommentPanel = !isCompactComment && viewPrefs.showCommentPanel && !isCommentCollapsed;
  const pageWideMode = viewPrefs.widePage;

  const updateViewPrefs = useCallback((updater: (prev: KnowledgeDocsViewPrefs) => KnowledgeDocsViewPrefs) => {
    setViewPrefs((prev) => normalizeKnowledgeDocsViewPrefs(updater(prev)));
  }, []);

  const showTocScrollbarTemporarily = useCallback(() => {
    setIsTocScrollbarVisible(true);
    if (tocScrollbarTimerRef.current !== null) {
      window.clearTimeout(tocScrollbarTimerRef.current);
    }
    tocScrollbarTimerRef.current = window.setTimeout(() => {
      setIsTocScrollbarVisible(false);
      tocScrollbarTimerRef.current = null;
    }, 680);
  }, []);

  const updateTocScrollThumb = useCallback(() => {
    const nav = tocNavRef.current;
    if (!nav) {
      setTocScrollThumbStyle((prev) => (prev.height === 0 ? prev : { top: 0, height: 0 }));
      return;
    }
    const maxScrollTop = nav.scrollHeight - nav.clientHeight;
    if (maxScrollTop <= 0) {
      setTocScrollThumbStyle((prev) => (prev.height === 0 ? prev : { top: 0, height: 0 }));
      return;
    }

    const trackInset = 8;
    const trackHeight = Math.max(0, nav.clientHeight - trackInset * 2);
    const minThumbHeight = 26;
    const thumbHeight = Math.max(minThumbHeight, (nav.clientHeight / nav.scrollHeight) * trackHeight);
    const maxThumbTop = Math.max(0, trackHeight - thumbHeight);
    const top = trackInset + (nav.scrollTop / maxScrollTop) * maxThumbTop;

    setTocScrollThumbStyle((prev) => {
      if (Math.abs(prev.top - top) < 0.5 && Math.abs(prev.height - thumbHeight) < 0.5) {
        return prev;
      }
      return { top, height: thumbHeight };
    });
  }, []);

  const markTocAutoScrolling = useCallback(() => {
    tocAutoScrollingRef.current = true;
    if (tocAutoScrollReleaseTimerRef.current !== null) {
      window.clearTimeout(tocAutoScrollReleaseTimerRef.current);
    }
    tocAutoScrollReleaseTimerRef.current = window.setTimeout(() => {
      tocAutoScrollingRef.current = false;
      tocAutoScrollReleaseTimerRef.current = null;
    }, 260);
  }, []);

  const openGraphPanel = useCallback(() => {
    setIsSettingsPanelOpen(false);
    setIsGraphDrawerOpen(true);
  }, []);

  const closeGraphPanel = useCallback(() => {
    setIsGraphDrawerOpen(false);
  }, []);

  // Build hierarchical tree from flat TOC (Feishu-style)
  const tocTree = useMemo(() => buildTocTree(toc), [toc]);

  const visibleActiveHeading = useMemo(
    () => resolveVisibleActiveTocId(tocTree, activeHeading, collapsedTocIds),
    [activeHeading, collapsedTocIds, tocTree]
  );

  const activeTocItem = useMemo(
    () => toc.find((item) => item.id === visibleActiveHeading) ?? null,
    [toc, visibleActiveHeading]
  );

  const alignActiveTocItem = useCallback((behavior: ScrollBehavior = "auto") => {
    if (!visibleActiveHeading || !isTocVisible) return;
    const nav = tocNavRef.current;
    if (!nav) return;

    const activeNode = nav.querySelector(`[data-toc-id="${visibleActiveHeading}"]`) as HTMLElement | null;
    if (!activeNode) return;

    const activeTop = activeNode.offsetTop;
    const activeBottom = activeTop + activeNode.offsetHeight;
    const edgeGuard = Math.min(34, Math.max(16, nav.clientHeight * 0.08));
    const visibleTop = nav.scrollTop + edgeGuard;
    const visibleBottom = Math.max(
      visibleTop + activeNode.offsetHeight,
      nav.scrollTop + nav.clientHeight - edgeGuard,
    );

    let nextScrollTop = nav.scrollTop;
    if (activeBottom > visibleBottom) {
      nextScrollTop = activeBottom - nav.clientHeight + edgeGuard;
    } else if (activeTop < visibleTop) {
      nextScrollTop = activeTop - edgeGuard;
    } else {
      return;
    }

    const maxScrollTop = Math.max(0, nav.scrollHeight - nav.clientHeight);
    nextScrollTop = Math.max(0, Math.min(maxScrollTop, nextScrollTop));
    if (Math.abs(nextScrollTop - nav.scrollTop) < 1) return;

    markTocAutoScrolling();
    if (behavior === "smooth") {
      nav.scrollTo({ top: nextScrollTop, behavior });
      return;
    }

    const previousScrollBehavior = nav.style.scrollBehavior;
    nav.style.scrollBehavior = "auto";
    nav.scrollTop = nextScrollTop;
    if (previousScrollBehavior) {
      nav.style.scrollBehavior = previousScrollBehavior;
    } else {
      nav.style.removeProperty("scroll-behavior");
    }
  }, [isTocVisible, markTocAutoScrolling, visibleActiveHeading]);

  useEffect(() => {
    if (lastAutoCommentHighlightHeadingRef.current === activeHeading) {
      return;
    }
    lastAutoCommentHighlightHeadingRef.current = activeHeading;
    setIsAutoCommentHighlightSuppressed(false);
  }, [activeHeading]);

  // Keep the active TOC item visible without mirroring the document's scroll position.
  useEffect(() => {
    alignActiveTocItem();
  }, [visibleActiveHeading, collapsedTocIds, alignActiveTocItem]);

  useEffect(() => {
    tocDefaultInitializedRef.current = false;
    const rafId = window.requestAnimationFrame(() => {
      const container = scrollRef.current;
      if (!container) return;
      const headingNodes = container.querySelectorAll<HTMLElement>("[data-heading-id]");
      const nextToc = compactTocItems(Array.from(headingNodes)
        .map((node) => {
          const id = node.getAttribute("data-heading-id") ?? node.id;
          if (!id) return null;
          const level = Number(node.tagName.replace("H", ""));
          if (!Number.isInteger(level) || level < 1 || level > 3) return null;
          const text = node.textContent?.trim() || id;
          return { id, text, level };
        })
        .filter((item): item is TocItem => item !== null));
      setToc((prev) => (tocEqual(prev, nextToc) ? prev : nextToc));
      if (!tocDefaultInitializedRef.current && nextToc.length > 0) {
        tocDefaultInitializedRef.current = true;
        setCollapsedTocIds(buildDefaultCollapsedTocIds(nextToc));
      }
    });
    return () => window.cancelAnimationFrame(rafId);
  }, [renderedMarkdown]);

  useEffect(() => {
    setViewPrefs(readKnowledgeDocsViewPrefs(subjectId));
  }, [subjectId]);

  useEffect(() => {
    persistKnowledgeDocsViewPrefs(subjectId, viewPrefs);
  }, [subjectId, viewPrefs]);

  useEffect(() => {
    const syncViewportWidth = () => {
      setViewportWidth(window.innerWidth);
    };
    syncViewportWidth();
    window.addEventListener("resize", syncViewportWidth);
    return () => window.removeEventListener("resize", syncViewportWidth);
  }, []);

  useEffect(() => {
    if (
      (activeDrawer === "toc" && (!isCompactToc || !viewPrefs.showToc)) ||
      (activeDrawer === "comment" && (!isCompactComment || !viewPrefs.showCommentPanel))
    ) {
      setActiveDrawer(null);
    }
  }, [activeDrawer, isCompactComment, isCompactToc, viewPrefs.showCommentPanel, viewPrefs.showToc]);

  useEffect(() => {
    if (!viewPrefs.showCommentPanel) {
      setFloatingComment(null);
      if (activeDrawer === "comment") {
        setActiveDrawer(null);
      }
    }
    if (!viewPrefs.showToc && activeDrawer === "toc") {
      setActiveDrawer(null);
    }
  }, [activeDrawer, viewPrefs.showCommentPanel, viewPrefs.showToc]);

  useEffect(() => {
    if (!isSettingsPanelOpen) return;
    const handlePointerDown = (event: MouseEvent) => {
      if (settingsPanelRef.current?.contains(event.target as Node)) return;
      if (settingsButtonRef.current?.contains(event.target as Node)) return;
      setIsSettingsPanelOpen(false);
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [isSettingsPanelOpen]);

  useEffect(() => {
    return () => {
      for (const timer of headingFlashTimersRef.current.values()) {
        window.clearTimeout(timer);
      }
      headingFlashTimersRef.current.clear();
      if (tocScrollbarTimerRef.current !== null) {
        window.clearTimeout(tocScrollbarTimerRef.current);
      }
      if (tocAutoScrollReleaseTimerRef.current !== null) {
        window.clearTimeout(tocAutoScrollReleaseTimerRef.current);
      }
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

  // Track active heading from a single scroll position so the TOC highlight does not bounce.
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;

    const headingRoot = contentAreaRef.current;
    const headings = Array.from((headingRoot ?? container).querySelectorAll<HTMLElement>("[data-heading-id]"));
    if (headings.length === 0) {
      setActiveHeading("");
      return;
    }

    let rafId = 0;

    const findActiveHeadingId = () => {
      const containerRect = container.getBoundingClientRect();
      const activationTop = containerRect.top + getHeadingActivationOffset(container);
      let current = headings[0]?.getAttribute("data-heading-id") ?? "";
      for (const heading of headings) {
        const rect = heading.getBoundingClientRect();
        const id = heading.getAttribute("data-heading-id") ?? "";
        if (!id) continue;
        if (rect.top <= activationTop) {
          current = id;
        } else {
          break;
        }
      }
      return current;
    };

    const syncActiveHeading = () => {
      window.cancelAnimationFrame(rafId);
      rafId = window.requestAnimationFrame(() => {
        const lockedHeadingId = activeHeadingLockRef.current;
        if (lockedHeadingId && headings.some((heading) => heading.getAttribute("data-heading-id") === lockedHeadingId)) {
          setActiveHeading((prev) => (prev === lockedHeadingId ? prev : lockedHeadingId));
          return;
        }

        const nextId = findActiveHeadingId();
        setActiveHeading((prev) => (prev === nextId ? prev : nextId));
      });
    };

    const handleScroll = () => {
      syncActiveHeading();
    };
    const clearHeadingLock = () => {
      activeHeadingLockRef.current = null;
      syncActiveHeading();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].includes(event.key)) {
        clearHeadingLock();
      }
    };

    container.addEventListener("scroll", handleScroll, { passive: true });
    container.addEventListener("wheel", clearHeadingLock, { passive: true });
    container.addEventListener("touchstart", clearHeadingLock, { passive: true });
    container.addEventListener("pointerdown", clearHeadingLock);
    window.addEventListener("resize", handleScroll);
    window.addEventListener("keydown", handleKeyDown);
    syncActiveHeading();

    return () => {
      window.cancelAnimationFrame(rafId);
      container.removeEventListener("scroll", handleScroll);
      container.removeEventListener("wheel", clearHeadingLock);
      container.removeEventListener("touchstart", clearHeadingLock);
      container.removeEventListener("pointerdown", clearHeadingLock);
      window.removeEventListener("resize", handleScroll);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [renderedMarkdown]);

  useEffect(() => {
    if (!isTocVisible) return;
    const container = scrollRef.current;
    if (!container) return;

    let rafId = 0;
    const syncTocPosition = () => {
      window.cancelAnimationFrame(rafId);
      rafId = window.requestAnimationFrame(() => {
        alignActiveTocItem();
      });
    };

    container.addEventListener("scroll", syncTocPosition, { passive: true });
    window.addEventListener("resize", syncTocPosition);
    syncTocPosition();

    return () => {
      window.cancelAnimationFrame(rafId);
      container.removeEventListener("scroll", syncTocPosition);
      window.removeEventListener("resize", syncTocPosition);
    };
  }, [alignActiveTocItem, isTocVisible]);

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

  const scrollToHeading = useCallback((id: string, options: { lockActive?: boolean } = {}) => {
    const container = scrollRef.current;
    if (!container) return;
    const headingRoot = contentAreaRef.current;
    const el = (headingRoot ?? container).querySelector(`[data-heading-id="${id}"]`) as HTMLElement | null;
    if (!el) return;

    if (options.lockActive !== false) {
      activeHeadingLockRef.current = id;
      setActiveHeading((prev) => (prev === id ? prev : id));
    }

    const containerRect = container.getBoundingClientRect();
    const elRect = el.getBoundingClientRect();
    const headingTop = container.scrollTop + (elRect.top - containerRect.top);
    const maxScrollTop = Math.max(0, container.scrollHeight - container.clientHeight);
    const targetTop = Math.max(0, Math.min(maxScrollTop, headingTop - getHeadingActivationOffset(container)));
    container.scrollTo({ top: targetTop, behavior: "smooth" });
    flashHeading(el);
  }, [flashHeading]);


  const captureRangeSegments = useCallback((range: Range): HighlightSegment[] => {
    const container = scrollRef.current;
    if (!container) {
      return [];
    }

    const containerRect = container.getBoundingClientRect();
    const rangeRoot = range.commonAncestorContainer.nodeType === Node.TEXT_NODE
      ? range.commonAncestorContainer.parentNode
      : range.commonAncestorContainer;
    const textNodes: Text[] = [];

    if (range.commonAncestorContainer.nodeType === Node.TEXT_NODE) {
      textNodes.push(range.commonAncestorContainer as Text);
    } else if (rangeRoot) {
      const walker = document.createTreeWalker(rangeRoot, NodeFilter.SHOW_TEXT);
      let current = walker.nextNode();
      while (current) {
        const textNode = current as Text;
        if ((textNode.nodeValue ?? "").trim()) {
          try {
            if (range.intersectsNode(textNode)) {
              textNodes.push(textNode);
            }
          } catch {
            // Ignore nodes that cannot be compared against this range.
          }
        }
        current = walker.nextNode();
      }
    }

    const textRects: DOMRect[] = [];
    for (const textNode of textNodes) {
      const value = textNode.nodeValue ?? "";
      if (!value) continue;

      let startOffset = textNode === range.startContainer ? range.startOffset : 0;
      let endOffset = textNode === range.endContainer ? range.endOffset : value.length;
      startOffset = Math.max(0, Math.min(value.length, startOffset));
      endOffset = Math.max(0, Math.min(value.length, endOffset));
      if (endOffset <= startOffset) continue;

      const selectedSlice = value.slice(startOffset, endOffset);
      const firstVisibleOffset = selectedSlice.search(/\S/u);
      if (firstVisibleOffset < 0) continue;
      const trailingWhitespaceLength = selectedSlice.match(/\s+$/u)?.[0].length ?? 0;
      const visibleStartOffset = startOffset + firstVisibleOffset;
      const visibleEndOffset = endOffset - trailingWhitespaceLength;
      if (visibleEndOffset <= visibleStartOffset) continue;

      const textRange = document.createRange();
      textRange.setStart(textNode, visibleStartOffset);
      textRange.setEnd(textNode, visibleEndOffset);
      textRects.push(
        ...Array.from(textRange.getClientRects()).filter((rect) => rect.width > 1 && rect.height > 1),
      );
    }

    const rects = textRects.length > 0
      ? textRects
      : Array.from(range.getClientRects()).filter((rect) => rect.width > 1 && rect.height > 1);

    const toSegment = (rect: DOMRect): HighlightSegment => ({
      top: rect.top - containerRect.top + container.scrollTop,
      left: rect.left - containerRect.left + container.scrollLeft,
      width: Math.max(4, rect.width),
      height: Math.max(12, rect.height),
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

    const locateInRoots = (roots: Node[]): HighlightSegment[] => {
      const textEntries: Array<{ node: Text; start: number; end: number }> = [];
      let rawText = "";
      const pushTextNode = (textNode: Text) => {
        const value = textNode.nodeValue ?? "";
        if (!value) return;
        const start = rawText.length;
        rawText += value;
        textEntries.push({ node: textNode, start, end: rawText.length });
      };

      for (const rootNode of roots) {
        if (rootNode.nodeType === Node.TEXT_NODE) {
          pushTextNode(rootNode as Text);
          continue;
        }
        const walker = document.createTreeWalker(rootNode, NodeFilter.SHOW_TEXT);
        let current = walker.nextNode();
        while (current) {
          pushTextNode(current as Text);
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
    };

    const heading = contentRoot.querySelector(`[data-heading-id="${anchorId}"]`) as HTMLElement | null;
    if (heading) {
      const allHeadings = Array.from(contentRoot.querySelectorAll<HTMLElement>("[data-heading-id]"));
      const headingIndex = allHeadings.findIndex((node) => node === heading);
      const nextHeading = headingIndex >= 0 ? allHeadings[headingIndex + 1] ?? null : null;
      const sectionRoots: Node[] = [];
      let node: Node | null = heading;
      while (node && node !== nextHeading) {
        sectionRoots.push(node);
        node = node.nextSibling;
      }
      const sectionSegments = locateInRoots(sectionRoots);
      if (sectionSegments.length > 0) {
        return sectionSegments;
      }
    }

    return locateInRoots([contentRoot]);
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

  const handleTocManualScrollStart = useCallback(() => {
    updateTocScrollThumb();
    showTocScrollbarTemporarily();
  }, [showTocScrollbarTemporarily, updateTocScrollThumb]);

  const handleTocNavScroll = useCallback(() => {
    updateTocScrollThumb();
    if (tocAutoScrollingRef.current) {
      return;
    }
    showTocScrollbarTemporarily();
  }, [showTocScrollbarTemporarily, updateTocScrollThumb]);

  const handleTocItemClick = useCallback((id: string) => {
    scrollToHeading(id);
    if (isCompactToc) {
      setActiveDrawer(null);
    }
  }, [isCompactToc, scrollToHeading]);

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
    if (!panel) return isCompactComment ? 18 : 56;
    const panelRect = panel.getBoundingClientRect();
    const rawTop = selectionViewportTop - panelRect.top - (isCompactComment ? 18 : 24);
    const minTop = isCompactComment ? 18 : 56;
    const estimatedComposerHeight = 208;
    const maxTop = Math.max(minTop, panelRect.height - estimatedComposerHeight - (isCompactComment ? 18 : 14));
    return Math.min(maxTop, Math.max(minTop, rawTop));
  }, [isCompactComment]);

  const buildFloatingCommentFromToolbar = useCallback((toolbar: FloatingToolbar): FloatingComment => {
    const container = scrollRef.current;
    const range = selectedRangeRef.current;
    let selectionViewportTop = toolbar.selectionViewportTop;
    let selectionContentTop = toolbar.selectionContentTop;
    let segments: HighlightSegment[] = [];

    if (container && range) {
      const rect = range.getBoundingClientRect();
      if (rect.width > 0 || rect.height > 0) {
        const containerRect = container.getBoundingClientRect();
        selectionViewportTop = rect.top + rect.height / 2;
        selectionContentTop = rect.top - containerRect.top + container.scrollTop + rect.height / 2;
      }
      segments = captureRangeSegments(range);
    }

    return {
      anchorId: toolbar.anchorId,
      selectedText: toolbar.selectedText,
      selectionViewportTop,
      selectionContentTop,
      top: computeCommentComposerTop(selectionViewportTop),
      segments,
    };
  }, [captureRangeSegments, computeCommentComposerTop]);

  // Keep document selection behavior close to Feishu:
  // any click outside toolbar clears highlighted range state.
  useEffect(() => {
    const handlePointerDown = (e: MouseEvent) => {
      if (floatingRef.current?.contains(e.target as Node)) return;
      if (floatingComposerCardRef.current?.contains(e.target as Node)) return;
      if (commentPanelRef.current?.contains(e.target as Node)) return;
      clearSelectionHighlight();
      setFloatingToolbar(null);
      setFloatingComment(null);
      setFloatingInput("");
      setActiveCommentThreadId(null);
      setPinnedThreadId(null);
      setIsAutoCommentHighlightSuppressed(true);
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

  useEffect(() => {
    if (!floatingComment || !isCommentVisible) return;
    const raf = window.requestAnimationFrame(() => {
      const textarea = floatingComposerTextareaRef.current;
      if (!textarea) return;
      textarea.focus({ preventScroll: true });
      const valueLength = textarea.value.length;
      textarea.setSelectionRange(valueLength, valueLength);
    });
    return () => window.cancelAnimationFrame(raf);
  }, [floatingComment, isCommentVisible]);

  useEffect(() => {
    if (isCompactComment || !floatingComment) {
      setFloatingComposerHeight(236);
      return;
    }

    const measure = () => {
      const node = floatingComposerCardRef.current;
      if (!node) return;
      const nextHeight = Math.ceil(node.getBoundingClientRect().height);
      if (nextHeight > 0) {
        setFloatingComposerHeight((prev) => (Math.abs(prev - nextHeight) < 1 ? prev : nextHeight));
      }
    };

    measure();
    const observer = typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(() => measure())
      : null;
    if (observer && floatingComposerCardRef.current) {
      observer.observe(floatingComposerCardRef.current);
    }
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [floatingComment, isCompactComment]);

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
      const selectionContext = buildSelectionContextPayload(contentAreaRef.current, anchorId, selectedText);
      const result = await postSseJson(
        `/api/v1/subjects/${subject}/chats/send`,
        {
          question: text,
          source: "quick_chat",
          session_id: threadSessionIds[threadId] ?? undefined,
          anchor_id: anchorId,
          selected_text: selectedText || undefined,
          selected_context: selectedText || undefined,
          selection_context: selectionContext,
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
    const segments = floatingComment.segments.length > 0 ? floatingComment.segments : captureSelectionSegments();
    addSelectionHighlight(threadId, anchorId, selectedText, segments);
    setActiveCommentThreadId(threadId);
    setPinnedThreadId(threadId);
    setIsAutoCommentHighlightSuppressed(false);
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
    setIsAutoCommentHighlightSuppressed(false);
    void streamAssistantReply(threadId, anchorId, selectedText, question);
  }, [streamAssistantReply, threadDrafts, threadStreaming]);

  const openCommentComposer = useCallback(() => {
    if (!floatingToolbar) return;
    const toolbar = floatingToolbar;
    if (!viewPrefs.showCommentPanel) {
      updateViewPrefs((prev) => ({ ...prev, showCommentPanel: true }));
    }
    if (isCompactComment) {
      setActiveDrawer("comment");
    } else {
      setIsCommentCollapsed(false);
    }
    setFloatingToolbar(null);
    setFloatingInput("");
    const showComposer = () => {
      setFloatingComment(buildFloatingCommentFromToolbar(toolbar));
    };
    if (isCommentVisible) {
      showComposer();
      window.requestAnimationFrame(showComposer);
      return;
    }
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(showComposer);
    });
  }, [buildFloatingCommentFromToolbar, floatingToolbar, isCommentVisible, isCompactComment, updateViewPrefs, viewPrefs.showCommentPanel]);

  // Feishu-style: detect text selection and show a small ask-AI action first.
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
    if (rect.width < 1 && rect.height < 1) return;
    const containerRect = container.getBoundingClientRect();

    // Find nearest heading above the selection
    let node: Node | null = range.startContainer;
    let headingId = "";
    while (node && node !== container) {
      if (node instanceof HTMLElement) {
        const hid = node.getAttribute("data-heading-id");
        if (hid) { headingId = hid; break; }
      }
      node = node.parentNode;
    }
    if (!headingId) {
      const allHeadings = (contentArea ?? container).querySelectorAll("[data-heading-id]");
      for (const h of allHeadings) {
        const hRange = document.createRange();
        hRange.selectNode(h);
        if (hRange.compareBoundaryPoints(Range.START_TO_START, range) <= 0) {
          headingId = h.getAttribute("data-heading-id") ?? "";
        }
      }
    }
    if (!headingId) {
      headingId = activeHeading || "document";
    }

    selectedRangeRef.current = range.cloneRange();
    const segments = captureRangeSegments(range);
    if (segments.length === 0) {
      return;
    }

    const contentTop = rect.top - containerRect.top + container.scrollTop;
    const selectionViewportTop = rect.top + rect.height / 2;
    const toolbarWidth = 112;
    const minToolbarLeft = container.scrollLeft + 12;
    const maxToolbarLeft = container.scrollLeft + container.clientWidth - toolbarWidth - 12;
    const toolbarLeft = Math.max(
      minToolbarLeft,
      Math.min(maxToolbarLeft, rect.right - containerRect.left + container.scrollLeft + 8)
    );
    const toolbarTop = Math.max(container.scrollTop + 10, contentTop - 44);

    setFloatingComment(null);
    setFloatingToolbar({
      anchorId: headingId,
      selectedText,
      top: toolbarTop,
      left: toolbarLeft,
      selectionViewportTop,
      selectionContentTop: contentTop + rect.height / 2,
    });
    setFloatingInput("");
    setActiveCommentThreadId(null);
  }, [
    activeHeading,
    captureRangeSegments,
  ]);

  useEffect(() => {
    const handleDocumentMouseUp = (event: MouseEvent) => {
      const target = event.target as Node;
      if (commentPanelRef.current?.contains(target)) return;
      if (floatingRef.current?.contains(target)) return;
      window.requestAnimationFrame(() => {
        handleTextSelect();
      });
    };
    const handleDocumentKeyUp = () => {
      window.requestAnimationFrame(() => {
        handleTextSelect();
      });
    };
    document.addEventListener("mouseup", handleDocumentMouseUp);
    document.addEventListener("keyup", handleDocumentKeyUp);
    return () => {
      document.removeEventListener("mouseup", handleDocumentMouseUp);
      document.removeEventListener("keyup", handleDocumentKeyUp);
    };
  }, [handleTextSelect]);

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
          let selectionContentTop = prev.selectionContentTop;
          let segments = prev.segments;
          const range = selectedRangeRef.current;
          const containerNode = scrollRef.current;
          if (range && containerNode) {
            const rect = range.getBoundingClientRect();
            if (rect.width > 0 || rect.height > 0) {
              const containerRect = containerNode.getBoundingClientRect();
              selectionViewportTop = rect.top + rect.height / 2;
              selectionContentTop = rect.top - containerRect.top + containerNode.scrollTop + rect.height / 2;
            }
            const nextSegments = captureRangeSegments(range);
            if (nextSegments.length > 0) {
              segments = nextSegments;
            }
          }
          const nextTop = computeCommentComposerTop(selectionViewportTop);
          if (
            Math.abs(prev.top - nextTop) < 0.5 &&
            Math.abs(prev.selectionViewportTop - selectionViewportTop) < 0.5 &&
            Math.abs(prev.selectionContentTop - selectionContentTop) < 0.5 &&
            highlightSegmentsEqual(prev.segments, segments)
          ) {
            return prev;
          }
          return {
            ...prev,
            selectionViewportTop,
            selectionContentTop,
            top: nextTop,
            segments,
          };
        });
      });
    };

    updateTop();
    window.addEventListener("resize", updateTop);
    container?.addEventListener("scroll", updateTop, { passive: true });

    const observer = typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(() => updateTop())
      : null;
    if (observer) {
      if (contentAreaRef.current) {
        observer.observe(contentAreaRef.current);
      }
      if (commentPanelRef.current) {
        observer.observe(commentPanelRef.current);
      }
    }

    return () => {
      window.cancelAnimationFrame(rafId);
      window.removeEventListener("resize", updateTop);
      container?.removeEventListener("scroll", updateTop);
      observer?.disconnect();
    };
  }, [captureRangeSegments, computeCommentComposerTop, floatingComment?.anchorId, isCommentVisible, showDesktopCommentPanel]);

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
  const centerThreadInViewport = useCallback((threadId: string) => {
    const container = scrollRef.current;
    if (!container) return;

    const thread = commentThreadById.get(threadId);
    if (!thread) return;

    const highlight = selectionHighlights.find((item) => item.threadId === threadId);
    const headingRoot = contentAreaRef.current;
    const heading = (headingRoot ?? container).querySelector(`[data-heading-id="${thread.anchorId}"]`) as HTMLElement | null;

    let targetCenter = 0;
    if (highlight && highlight.segments.length > 0) {
      const top = Math.min(...highlight.segments.map((segment) => segment.top));
      const bottom = Math.max(...highlight.segments.map((segment) => segment.top + segment.height));
      targetCenter = (top + bottom) / 2;
    } else if (heading) {
      const containerRect = container.getBoundingClientRect();
      const headingRect = heading.getBoundingClientRect();
      targetCenter = container.scrollTop + (headingRect.top - containerRect.top) + headingRect.height / 2;
    } else {
      return;
    }

    const maxScrollTop = Math.max(0, container.scrollHeight - container.clientHeight);
    const targetTop = Math.max(0, Math.min(maxScrollTop, targetCenter - container.clientHeight / 2));
    container.scrollTo({ top: targetTop, behavior: "smooth" });

    if (heading) {
      flashHeading(heading);
    }
    setActiveHeading(thread.anchorId);
  }, [commentThreadById, flashHeading, selectionHighlights]);
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
    if (isCompactComment) {
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
    const nextTop = listRect.top - containerRect.top;
    setCommentListOriginTop((prev) => {
      if (prev !== null && Math.abs(prev - nextTop) < 0.5) {
        return prev;
      }
      return nextTop;
    });
  }, [isCompactComment]);

  const syncDesktopCommentTrack = useCallback(() => {
    const track = desktopCommentTrackRef.current;
    if (!track) return;
    if (isCompactComment || !isCommentVisible) {
      track.style.removeProperty("transform");
      return;
    }
    const container = scrollRef.current;
    const list = commentThreadListRef.current;
    if (!container || !list) return;
    const containerRect = container.getBoundingClientRect();
    const listRect = list.getBoundingClientRect();
    const currentTop = listRect.top - containerRect.top;
    const baseTop = commentListOriginTop ?? currentTop;
    const translateY = baseTop - currentTop - container.scrollTop;
    track.style.transform = `translate3d(0, ${translateY}px, 0)`;
  }, [commentListOriginTop, isCommentVisible, isCompactComment]);
  const threadHeightMap = useMemo(
    () => new Map(Object.entries(threadHeightsById)),
    [threadHeightsById]
  );
  const desiredTopByThreadId = useMemo(() => {
    const next = new Map<string, number>();
    if (isCompactComment || commentListOriginTop === null) {
      return next;
    }
    for (const thread of commentThreads) {
      const highlightTop = highlightTopByThreadId.get(thread.threadId);
      if (highlightTop === undefined) {
        continue;
      }
      next.set(thread.threadId, highlightTop - commentListOriginTop - 2);
    }
    if (floatingComment) {
      next.set(
        FLOATING_COMPOSER_THREAD_ID,
        floatingComment.selectionContentTop - commentListOriginTop - 18,
      );
    }
    return next;
  }, [commentListOriginTop, commentThreads, floatingComment, highlightTopByThreadId, isCompactComment]);
  const desktopCommentLayoutThreads = useMemo<CommentThreadView[]>(() => {
    const threads = isCompactComment || !floatingComment
      ? commentThreads
      : [...commentThreads, {
      threadId: FLOATING_COMPOSER_THREAD_ID,
      anchorId: floatingComment.anchorId,
      selectedText: floatingComment.selectedText,
      comments: [],
      createdAt: Number.MAX_SAFE_INTEGER,
    }];

    return [...threads].sort((left, right) => {
      const leftTop = desiredTopByThreadId.get(left.threadId);
      const rightTop = desiredTopByThreadId.get(right.threadId);
      if (leftTop !== undefined && rightTop !== undefined && Math.abs(leftTop - rightTop) > 2) {
        return leftTop - rightTop;
      }
      if (leftTop !== undefined && rightTop === undefined) {
        return -1;
      }
      if (leftTop === undefined && rightTop !== undefined) {
        return 1;
      }
      const leftOrder = tocOrderMap.get(left.anchorId) ?? Number.MAX_SAFE_INTEGER;
      const rightOrder = tocOrderMap.get(right.anchorId) ?? Number.MAX_SAFE_INTEGER;
      if (leftOrder !== rightOrder) {
        return leftOrder - rightOrder;
      }
      return left.createdAt - right.createdAt;
    });
  }, [commentThreads, desiredTopByThreadId, floatingComment, isCompactComment, tocOrderMap]);
  const desktopThreadHeightMap = useMemo(() => {
    const next = new Map(threadHeightMap);
    if (!isCompactComment && floatingComment) {
      next.set(FLOATING_COMPOSER_THREAD_ID, Math.max(180, floatingComposerHeight));
    }
    return next;
  }, [floatingComment, floatingComposerHeight, isCompactComment, threadHeightMap]);
  const desktopThreadLayout = useMemo(
    () => buildCommentThreadLayout(
      desktopCommentLayoutThreads,
      desktopThreadHeightMap,
      desiredTopByThreadId,
      floatingComment ? FLOATING_COMPOSER_THREAD_ID : pinnedThreadId,
    ),
    [desktopCommentLayoutThreads, desktopThreadHeightMap, desiredTopByThreadId, floatingComment, pinnedThreadId]
  );
  const updateDesktopCommentScrollExtent = useCallback(() => {
    if (!showDesktopCommentPanel || !isCommentVisible || commentListOriginTop === null || desktopThreadLayout.totalHeight <= 0) {
      setDesktopCommentScrollMinHeight((prev) => (prev === 0 ? prev : 0));
      return;
    }

    const container = scrollRef.current;
    const viewport = commentViewportRef.current;
    if (!container || !viewport) {
      return;
    }

    const containerRect = container.getBoundingClientRect();
    const viewportRect = viewport.getBoundingClientRect();
    const viewportBottom = viewportRect.bottom - containerRect.top;
    const bottomGutter = 32;
    const trackHeight = desktopThreadLayout.totalHeight + 24;
    const requiredScrollHeight = Math.ceil(
      commentListOriginTop +
      trackHeight +
      container.clientHeight -
      viewportBottom +
      bottomGutter
    );
    const nextMinHeight = Math.max(container.clientHeight, requiredScrollHeight);

    setDesktopCommentScrollMinHeight((prev) => (
      Math.abs(prev - nextMinHeight) < 1 ? prev : nextMinHeight
    ));
  }, [commentListOriginTop, desktopThreadLayout.totalHeight, isCommentVisible, showDesktopCommentPanel]);
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
    if (isCompactComment) {
      setCommentListOriginTop(null);
      syncDesktopCommentTrack();
      return;
    }
    const rafId = window.requestAnimationFrame(() => {
      measureCommentListOrigin();
      syncDesktopCommentTrack();
      updateDesktopCommentScrollExtent();
    });
    return () => window.cancelAnimationFrame(rafId);
  }, [
    isCompactComment,
    measureCommentListOrigin,
    syncDesktopCommentTrack,
    updateDesktopCommentScrollExtent,
    commentThreads.length,
    isCommentCollapsed,
    activeDrawer,
    isCommentVisible,
  ]);

  useEffect(() => {
    if (isCompactComment) {
      syncDesktopCommentTrack();
      return;
    }
    const handleLayoutChange = () => {
      measureCommentListOrigin();
      syncDesktopCommentTrack();
      updateDesktopCommentScrollExtent();
    };
    const handleDocumentScroll = () => {
      syncDesktopCommentTrack();
    };
    const container = scrollRef.current;
    window.addEventListener("resize", handleLayoutChange);
    container?.addEventListener("scroll", handleDocumentScroll, { passive: true });

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
      container?.removeEventListener("scroll", handleDocumentScroll);
      observer?.disconnect();
    };
  }, [isCompactComment, measureCommentListOrigin, syncDesktopCommentTrack, updateDesktopCommentScrollExtent]);

  useEffect(() => {
    if (isCompactComment || !showDesktopCommentPanel) {
      setDesktopCommentScrollMinHeight((prev) => (prev === 0 ? prev : 0));
      return;
    }

    const rafId = window.requestAnimationFrame(() => {
      updateDesktopCommentScrollExtent();
      syncDesktopCommentTrack();
    });
    return () => window.cancelAnimationFrame(rafId);
  }, [
    isCompactComment,
    showDesktopCommentPanel,
    updateDesktopCommentScrollExtent,
    syncDesktopCommentTrack,
    desktopThreadLayout.totalHeight,
    threadHeightsById,
    floatingComposerHeight,
    commentThreads.length,
  ]);

  const refreshThreadHeights = useCallback(() => {
    if (isCompactComment) {
      setThreadHeightsById((prev) => (Object.keys(prev).length === 0 ? prev : {}));
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
  }, [commentThreads, isCompactComment]);

  useEffect(() => {
    if (isCompactComment) {
      refreshThreadHeights();
      return;
    }

    let rafId = 0;
    const scheduleMeasure = () => {
      if (rafId) {
        return;
      }
      rafId = window.requestAnimationFrame(() => {
        rafId = 0;
        refreshThreadHeights();
      });
    };

    refreshThreadHeights();

    const observer = typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(() => scheduleMeasure())
      : null;
    if (observer) {
      for (const thread of commentThreads) {
        const node = threadRefs.current.get(thread.threadId);
        if (node) {
          observer.observe(node);
        }
      }
    }
    window.addEventListener("resize", scheduleMeasure);

    return () => {
      if (rafId) {
        window.cancelAnimationFrame(rafId);
      }
      observer?.disconnect();
      window.removeEventListener("resize", scheduleMeasure);
    };
  }, [commentThreads, isCompactComment, refreshThreadHeights]);

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

  useEffect(() => {
    if (!hasRenderedMarkdown) {
      return;
    }

    let rafId = 0;
    const refreshHighlightLayout = () => {
      window.cancelAnimationFrame(rafId);
      rafId = window.requestAnimationFrame(() => {
        setSelectionHighlights((prev) => {
          let changed = false;
          const next = prev.map((highlight) => {
            const segments = buildSelectionSegmentsFromText(highlight.anchorId, highlight.selectedText);
            if (segments.length === 0 || highlightSegmentsEqual(highlight.segments, segments)) {
              return highlight;
            }
            changed = true;
            return {
              ...highlight,
              segments,
            };
          });
          return changed ? next : prev;
        });
      });
    };

    const container = scrollRef.current;
    const contentArea = contentAreaRef.current;
    const observer = typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(() => refreshHighlightLayout())
      : null;

    if (observer && container) {
      observer.observe(container);
    }
    if (observer && contentArea) {
      observer.observe(contentArea);
    }

    window.addEventListener("resize", refreshHighlightLayout);
    refreshHighlightLayout();

    return () => {
      window.cancelAnimationFrame(rafId);
      window.removeEventListener("resize", refreshHighlightLayout);
      observer?.disconnect();
    };
  }, [
    buildSelectionSegmentsFromText,
    hasRenderedMarkdown,
    isCommentCollapsed,
    isCompactComment,
    isTocCollapsed,
    pageWideMode,
    viewPrefs.showCommentPanel,
    viewPrefs.showToc,
  ]);

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
  const highlightedThreadId = activeCommentThreadId ?? (isAutoCommentHighlightSuppressed ? null : activeThreadId);

  const focusCommentThread = useCallback((
    threadId: string,
    options: { scrollToDoc?: boolean; pinToSelection?: boolean; scrollThreadIntoView?: boolean } = {}
  ) => {
    const thread = commentThreadById.get(threadId);
    if (!thread) {
      return;
    }
    if (!viewPrefs.showCommentPanel) {
      updateViewPrefs((prev) => ({ ...prev, showCommentPanel: true }));
    }
    if (isCompactComment) {
      setActiveDrawer("comment");
    } else {
      setIsCommentCollapsed(false);
    }
    setActiveCommentThreadId(threadId);
    setIsAutoCommentHighlightSuppressed(false);
    const shouldPin = options.pinToSelection ?? !isCompactComment;
    if (shouldPin) {
      setPinnedThreadId(threadId);
    }
    if (options.scrollToDoc !== false) {
      centerThreadInViewport(threadId);
    }
    if (isCompactComment && options.scrollThreadIntoView !== false) {
      window.requestAnimationFrame(() => {
        threadRefs.current.get(threadId)?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    }
  }, [centerThreadInViewport, commentThreadById, isCompactComment, updateViewPrefs, viewPrefs.showCommentPanel]);

  const locateCommentThread = useCallback((threadId: string) => {
    focusCommentThread(threadId, {
      scrollToDoc: false,
      pinToSelection: true,
      scrollThreadIntoView: isCompactComment,
    });
  }, [focusCommentThread, isCompactComment]);

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
    if (isCompactComment) {
      closeDrawer();
    } else {
      setIsCommentCollapsed(true);
    }
  }, [closeDrawer, isCompactComment]);

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
      const isActive = visibleActiveHeading === item.id;
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
  }, [collapsedTocIds, commentsForAnchor, handleTocItemClick, toggleTocCollapse, visibleActiveHeading]);

  useEffect(() => {
    if (!isTocVisible) {
      setTocScrollThumbStyle((prev) => (prev.height === 0 ? prev : { top: 0, height: 0 }));
      return;
    }

    const syncThumb = () => {
      window.requestAnimationFrame(() => {
        updateTocScrollThumb();
      });
    };

    syncThumb();
    window.addEventListener("resize", syncThumb);
    return () => window.removeEventListener("resize", syncThumb);
  }, [collapsedTocIds, isTocVisible, tocTree, updateTocScrollThumb]);

  const tocNav = (
    <div className="relative h-full">
      <nav
        ref={tocNavRef}
        className="toc-scroll h-full overflow-y-auto py-2 pr-2"
        onWheel={handleTocManualScrollStart}
        onTouchStart={handleTocManualScrollStart}
        onPointerDown={handleTocManualScrollStart}
        onScroll={handleTocNavScroll}
      >
        {tocTree.length > 0 ? (
          renderTocNodes(tocTree)
        ) : (
          <div className="px-3 py-4 text-xs text-slate-400 text-center">暂无目录</div>
        )}
      </nav>
      {tocScrollThumbStyle.height > 0 && (
        <div
          className={cn(
            "pointer-events-none absolute right-[3px] w-[3px] rounded-full bg-slate-400/55 transition-opacity duration-150",
            isTocScrollbarVisible ? "opacity-100" : "opacity-0"
          )}
          style={{
            top: tocScrollThumbStyle.top,
            height: tocScrollThumbStyle.height,
          }}
        />
      )}
    </div>
  );

  const commentPanel = (
    <div
      ref={commentPanelRef}
      className={cn(
        "relative flex h-full w-full min-h-0 flex-col",
        isCompactComment
          ? "h-full rounded-2xl border border-slate-200 bg-white shadow-2xl flex flex-col overflow-hidden"
          : "bg-white/86 overflow-hidden"
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
            {activeStreamingCount > 0 ? `（${activeStreamingCount} 条回复中）` : ""}
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
            <ChevronRight className={cn("w-4 h-4", isCompactComment && "rotate-180")} />
          </button>
        </div>
      </div>

      {isCompactComment && floatingComment && (
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
              ref={floatingComposerTextareaRef}
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

      <div
        ref={commentViewportRef}
        className={cn(
          "relative min-h-0 flex-1",
          isCompactComment ? "overflow-y-auto bg-slate-50/80" : "overflow-hidden pr-1"
        )}
      >
        {isCompactComment && (
          <>
            <div className="pointer-events-none absolute inset-x-0 top-0 h-12 z-20 bg-gradient-to-b from-slate-50 via-slate-50/80 to-transparent" />
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 z-20 bg-gradient-to-t from-slate-50 via-slate-50/80 to-transparent" />
          </>
        )}
        {!threadHistoryLoaded ? (
          <div className={cn("p-3", isCompactComment && "h-full")}>
            <div className={cn(
              "flex items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 text-slate-400",
              isCompactComment ? "h-full" : "h-24"
            )}>
              <Loader2 className="h-4 w-4 animate-spin" />
            </div>
          </div>
        ) : threadHistoryError ? (
          <div className={cn("p-3", isCompactComment && "h-full")}>
            <div className="rounded-xl border border-rose-200 bg-rose-50/70 px-4 py-4 text-xs leading-5 text-rose-600">
              {threadHistoryError}
            </div>
          </div>
        ) : commentThreads.length === 0 && !floatingComment ? (
          <div className={cn("p-3", isCompactComment && "h-full")}>
            <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-center">
              <p className="text-sm text-slate-500">选中文本后点击“问问 AI”即可开始对话</p>
            </div>
          </div>
        ) : isCompactComment ? (
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
                    setIsAutoCommentHighlightSuppressed(false);
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
          >
            <div
              ref={desktopCommentTrackRef}
              className="relative will-change-transform"
              style={{ minHeight: Math.max(160, desktopThreadLayout.totalHeight + 24) }}
            >
              {desktopCommentLayoutThreads.map((thread) => {
                if (thread.threadId === FLOATING_COMPOSER_THREAD_ID && floatingComment) {
                  const layout = desktopThreadLayout.positions[FLOATING_COMPOSER_THREAD_ID];
                  const top = layout?.top ?? 0;
                  return (
                    <div
                      key={FLOATING_COMPOSER_THREAD_ID}
                      ref={floatingComposerCardRef}
                      className="absolute left-0 right-0"
                      style={{ top }}
                    >
                      <div className="overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-[0_22px_48px_-32px_rgba(15,23,42,0.45)]">
                        <div className="border-b border-slate-200/80 bg-[linear-gradient(130deg,rgba(236,253,255,0.82),rgba(248,250,252,0.96),rgba(239,246,255,0.88))] px-3 py-2.5">
                          <div className="flex items-center gap-2">
                            <span className="inline-flex h-7 w-7 items-center justify-center rounded-xl bg-slate-900 text-white shadow-sm">
                              <Sparkles className="h-3.5 w-3.5" />
                            </span>
                            <div className="min-w-0">
                              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">问问 AI</p>
                              <p className="truncate text-xs text-slate-700">&ldquo;{floatingComment.selectedText.slice(0, 72)}&rdquo;</p>
                            </div>
                          </div>
                        </div>
                        <div className="space-y-2.5 p-3">
                          <textarea
                            ref={floatingComposerTextareaRef}
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
                    </div>
                  );
                }

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
                    className="absolute left-0 right-0"
                    style={{ top }}
                  >
                    <CommentThread
                      anchorId={thread.anchorId}
                      comments={thread.comments}
                      selectedText={thread.selectedText}
                      draft={threadDrafts[thread.threadId] ?? ""}
                      isStreaming={Boolean(threadStreaming[thread.threadId])}
                      isActive={highlightedThreadId === thread.threadId}
                      onDraftChange={(value) => updateThreadDraft(thread.threadId, value)}
                      onSend={() => sendThreadReply(thread.threadId, thread.anchorId, thread.selectedText)}
                      onFocus={() => focusCommentThread(thread.threadId, {
                        pinToSelection: true,
                        scrollThreadIntoView: false,
                      })}
                      onJumpToAnchor={() => focusCommentThread(thread.threadId, { pinToSelection: true, scrollThreadIntoView: false })}
                      onOpenAssistant={() => openAiAssistant(thread.threadId)}
                      compactMode={false}
                      isAligned={layout?.aligned ?? false}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );

  const desktopTocWidthClass = "w-[clamp(14rem,16vw,18rem)]";
  const desktopCommentWidthClass = "w-[clamp(18rem,23vw,26rem)]";
  const pageShellMaxWidthClass = pageWideMode ? "max-w-none" : showDesktopCommentPanel ? "max-w-[1480px]" : "max-w-[1120px]";
  const docColumnMaxWidthClass = pageWideMode ? "max-w-none" : showDesktopCommentPanel ? "max-w-[920px]" : "max-w-[980px]";
  const showFloatingActions = Boolean(subjectId && !isBuildActive && !showDocGeneratingState);

  if (!hasRenderedMarkdown && (isBuildActive || isWaitingForRequestedBuild || showDocGeneratingState)) {
    return (
      <div className="relative flex h-[100dvh] w-full overflow-hidden bg-white">
        <BuildView
          isFetching={docMarkdownQuery.isFetching}
          progress={buildProgress}
          statusText={buildPreview?.current_stage_description?.trim() || buildStatusText}
          buildPreview={buildPreview}
          buildMetrics={buildMetrics}
          sourceFiles={sourceFiles}
          sourceFilesFetching={sourceFilesFetching}
          buildStage={buildMeta?.stage}
          subjectId={subjectId}
        />
      </div>
    );
  }

  return (
    <div className="relative flex h-full min-h-0 flex-1 w-full overflow-hidden bg-slate-50 dark:bg-slate-900">
      <div className="relative z-10 flex min-h-0 h-full w-full bg-white dark:bg-slate-900">
      {hasCompactTocControl && (
          <div className="fixed left-3 top-3 z-[79] flex items-center gap-2">
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
          </div>
      )}

      {hasCompactCommentControl && (
          <div className="fixed top-3 right-6 z-[79] flex items-center gap-2">
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
      )}

      {activeDrawer && isCompactPanels && (
        <button
          onClick={closeDrawer}
          className="fixed inset-0 z-[76] bg-slate-900/24"
          aria-label="关闭抽屉遮罩"
        />
      )}

      {hasCompactTocControl && (
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
      )}

      {hasCompactCommentControl && (
        <aside
          className={cn(
            "fixed right-3 top-14 bottom-4 z-[78] w-[min(24rem,calc(100vw-1.5rem))] transition-transform duration-200",
            isCommentVisible ? "translate-x-0" : "translate-x-[110%] pointer-events-none"
          )}
        >
          {commentPanel}
        </aside>
      )}

      {!isCompactToc && viewPrefs.showToc && (
        <aside
          className={cn(
            "h-full min-h-0 shrink-0 overflow-hidden bg-white/88 backdrop-blur-md transition-[width] duration-300 ease-out",
            isTocCollapsed ? "w-[56px]" : desktopTocWidthClass
          )}
        >
          <div className="flex h-full flex-col">
            {isTocCollapsed ? (
              <div className="flex flex-1 items-start justify-start px-2 py-3">
                <button
                  onClick={() => setIsTocCollapsed(false)}
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-[#3370FF] transition-colors hover:bg-[#EDF3FF] hover:text-[#245BDB]"
                  aria-label="展开目录"
                  title={activeTocItem?.text ? `展开目录（当前：${activeTocItem.text}）` : "展开目录"}
                >
                  <ChevronsRight className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <>
                <div className="sticky top-0 z-10 bg-white/92 px-3 pb-1 pt-3 backdrop-blur-md">
                  <button
                    onClick={() => setIsTocCollapsed(true)}
                    className="flex h-8 w-8 items-center justify-center rounded-lg text-[#3370FF] transition-colors hover:bg-[#EDF3FF] hover:text-[#245BDB]"
                    aria-label="收起目录"
                    title="收起目录"
                  >
                    <ChevronsLeft className="h-4 w-4" />
                  </button>
                </div>
                <div className="min-h-0 flex-1 overflow-hidden px-2 pb-3 pt-0.5">
                  {tocNav}
                </div>
              </>
            )}
          </div>
        </aside>
      )}

      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        {!isCompactComment && viewPrefs.showCommentPanel && isCommentCollapsed && (
          <aside className="absolute right-4 top-4 z-20 hidden lg:flex">
            <button
              onClick={() => setIsCommentCollapsed(false)}
              className="rounded-xl border border-slate-200 bg-white/95 px-2 py-2.5 text-slate-600 shadow-sm transition-colors hover:bg-white hover:text-slate-900"
              aria-label="展开问答栏"
            >
              <Bot className="w-4 h-4" />
            </button>
          </aside>
        )}

        <div
          ref={scrollRef}
          className="relative h-full overflow-y-auto doc-scroll-container content-scroll"
          onMouseUp={handleTextSelect}
        >
          <div
            className="min-h-full px-4 py-8 md:px-6 lg:px-8"
            style={desktopCommentScrollMinHeight > 0 ? { minHeight: desktopCommentScrollMinHeight } : undefined}
          >
            <div
              className={cn(
                "mx-auto flex min-h-full w-full items-start justify-center",
                showDesktopCommentPanel && "gap-4 xl:gap-5",
                pageShellMaxWidthClass,
              )}
              style={desktopCommentScrollMinHeight > 0 ? { minHeight: desktopCommentScrollMinHeight } : undefined}
            >
              <div
                ref={contentAreaRef}
                className={cn("feishu-doc-content min-w-0 w-full", docColumnMaxWidthClass)}
              >
                <article className="min-w-0 px-2 py-2 md:px-4">
                  <SubjectVectorNotice status={docMarkdownQuery.data?.vector_status} className="mb-6" />
                  {docMarkdownQuery.isError ? (
                    <DocLoadErrorState
                      message={getApiErrorMessage(docMarkdownQuery.error, "获取知识文档失败，请稍后重试。")}
                      onRetry={() => {
                        void docMarkdownQuery.refetch();
                      }}
                    />
                  ) : showDocGeneratingState ? (
                    <BuildView
                      className="min-h-[600px] h-[70vh] rounded-xl border border-zinc-100 overflow-hidden"
                      isFetching={docMarkdownQuery.isFetching}
                      progress={buildProgress}
                      statusText={buildPreview?.current_stage_description?.trim() || buildStatusText}
                      buildPreview={buildPreview}
                      buildMetrics={buildMetrics}
                      sourceFiles={sourceFiles}
                      sourceFilesFetching={sourceFilesFetching}
                      buildStage={buildMeta?.stage}
                      subjectId={subjectId}
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
                      <DocMarkdown content={renderedMarkdown} subjectId={subjectId} />
                    </>
                  )}
                </article>
              </div>
              {showDesktopCommentPanel && (
                <aside
                  className={cn(
                    "sticky top-4 h-[calc(100dvh-2rem)] min-h-0 shrink-0 border-l border-slate-200/80 bg-white/92 px-3 py-4 backdrop-blur-md",
                    desktopCommentWidthClass,
                  )}
                >
                  {commentPanel}
                </aside>
              )}
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
                    "group absolute z-30 rounded-[2px] transition-[background-color,box-shadow] duration-150 focus-visible:outline-none",
                    highlightedThreadId === highlight.threadId
                      ? "bg-amber-100/60 shadow-[0_4px_12px_-14px_rgba(180,83,9,0.65)]"
                      : "bg-transparent hover:bg-amber-50/25 focus-visible:ring-2 focus-visible:ring-amber-300/45"
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
                      "pointer-events-none absolute inset-x-[1px] bottom-[-3px] rounded-full transition-all duration-150",
                      highlightedThreadId === highlight.threadId
                        ? "h-[1.5px] bg-amber-600/95 shadow-[0_3px_8px_-5px_rgba(180,83,9,0.85)]"
                        : "h-px bg-amber-400/65 shadow-[0_2px_6px_-5px_rgba(180,83,9,0.65)] group-hover:bg-amber-500/75"
                    )}
                  />
                </button>
              ))}
            </div>
          ))}

          {floatingComment?.segments.map((segment, index) => (
            <div
              key={`floating-selection-${index}`}
              className="pointer-events-none absolute z-30 rounded-[2px] bg-amber-50/40"
              style={{
                top: segment.top,
                left: segment.left,
                width: segment.width,
                height: segment.height,
              }}
            >
              <span className="absolute inset-x-[1px] bottom-[-3px] h-px rounded-full bg-amber-500/80 shadow-[0_2px_6px_-5px_rgba(180,83,9,0.75)]" />
            </div>
          ))}

          {floatingToolbar && (
            <div
              ref={floatingRef}
              className="absolute z-50"
              style={{
                top: floatingToolbar.top,
                left: floatingToolbar.left,
              }}
              onMouseUp={(e) => e.stopPropagation()}
            >
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={openCommentComposer}
                className="group inline-flex h-10 items-center gap-2 rounded-full border border-slate-200/90 bg-white/96 px-2.5 pr-3 text-xs font-medium text-slate-700 shadow-[0_18px_42px_-24px_rgba(15,23,42,0.85)] backdrop-blur transition hover:border-sky-200 hover:bg-sky-50 hover:text-sky-700"
                title="基于选中内容问问 AI"
                aria-label="基于选中内容问问 AI"
              >
                <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-white shadow-sm transition group-hover:bg-sky-600">
                  <Sparkles className="h-3.5 w-3.5" />
                </span>
                问问 AI
              </button>
            </div>
          )}
        </div>
        </div>
      </div>

      </div>

      {showFloatingActions && isSettingsPanelOpen && (
        <div
          ref={settingsPanelRef}
          className="fixed bottom-20 right-6 z-[87] w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-3xl border border-slate-200/90 bg-white/96 shadow-[0_22px_60px_-32px_rgba(15,23,42,0.36)] backdrop-blur-xl"
        >
          <div className="border-b border-slate-200/80 px-4 py-3">
            <p className="text-sm font-semibold text-slate-900">页面设置</p>
            <p className="mt-1 text-xs leading-5 text-slate-500">切换文档页的阅读宽度与侧栏显示方式。</p>
          </div>
          <div className="p-3">
            <button
              type="button"
              onClick={() => {
                updateViewPrefs((prev) => ({ ...prev, widePage: !prev.widePage }));
              }}
              className="flex w-full items-center justify-between rounded-2xl px-3 py-3 text-left transition hover:bg-slate-50"
              aria-pressed={pageWideMode}
            >
              <div className="flex min-w-0 items-start gap-3">
                <span className="mt-0.5 inline-flex h-8 w-8 items-center justify-center rounded-xl bg-slate-100 text-slate-600">
                  <ExternalLink className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-900">宽页模式</p>
                  <p className="mt-1 text-xs leading-5 text-slate-500">正文根据剩余空间自适应铺开，目录和问答栏同步扩展。</p>
                </div>
              </div>
              <span className={cn("ml-3 flex h-6 w-11 shrink-0 rounded-full p-0.5 transition", pageWideMode ? "bg-slate-900" : "bg-slate-200")}>
                <span className={cn("h-5 w-5 rounded-full bg-white shadow-sm transition", pageWideMode ? "translate-x-5" : "translate-x-0")} />
              </span>
            </button>
            <button
              type="button"
              onClick={() => {
                updateViewPrefs((prev) => ({ ...prev, showToc: !prev.showToc }));
                if (!viewPrefs.showToc) {
                  setIsTocCollapsed(false);
                }
              }}
              className="flex w-full items-center justify-between rounded-2xl px-3 py-3 text-left transition hover:bg-slate-50"
              aria-pressed={viewPrefs.showToc}
            >
              <div className="flex min-w-0 items-start gap-3">
                <span className="mt-0.5 inline-flex h-8 w-8 items-center justify-center rounded-xl bg-slate-100 text-slate-600">
                  <FileText className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-900">显示目录</p>
                  <p className="mt-1 text-xs leading-5 text-slate-500">保留左侧目录轨道，跟随正文标题高亮。</p>
                </div>
              </div>
              <span className={cn("ml-3 flex h-6 w-11 shrink-0 rounded-full p-0.5 transition", viewPrefs.showToc ? "bg-slate-900" : "bg-slate-200")}>
                <span className={cn("h-5 w-5 rounded-full bg-white shadow-sm transition", viewPrefs.showToc ? "translate-x-5" : "translate-x-0")} />
              </span>
            </button>
            <button
              type="button"
              onClick={() => {
                updateViewPrefs((prev) => ({ ...prev, showCommentPanel: !prev.showCommentPanel }));
                if (!viewPrefs.showCommentPanel) {
                  setIsCommentCollapsed(false);
                }
              }}
              className="flex w-full items-center justify-between rounded-2xl px-3 py-3 text-left transition hover:bg-slate-50"
              aria-pressed={viewPrefs.showCommentPanel}
            >
              <div className="flex min-w-0 items-start gap-3">
                <span className="mt-0.5 inline-flex h-8 w-8 items-center justify-center rounded-xl bg-slate-100 text-slate-600">
                  <Bot className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-900">显示问答栏</p>
                  <p className="mt-1 text-xs leading-5 text-slate-500">显示右侧 AI 问答会话区，并让划词追问对齐到对应段落。</p>
                </div>
              </div>
              <span className={cn("ml-3 flex h-6 w-11 shrink-0 rounded-full p-0.5 transition", viewPrefs.showCommentPanel ? "bg-slate-900" : "bg-slate-200")}>
                <span className={cn("h-5 w-5 rounded-full bg-white shadow-sm transition", viewPrefs.showCommentPanel ? "translate-x-5" : "translate-x-0")} />
              </span>
            </button>
          </div>
        </div>
      )}

      {showFloatingActions && (
        <button
          ref={settingsButtonRef}
          type="button"
          onClick={() => setIsSettingsPanelOpen((prev) => !prev)}
          className="fixed bottom-6 right-6 z-[88] inline-flex h-11 w-11 items-center justify-center rounded-2xl border border-zinc-200/80 bg-white/95 text-zinc-700 shadow-[0_2px_8px_rgba(0,0,0,0.04),0_8px_24px_rgba(0,0,0,0.06)] backdrop-blur-xl transition duration-300 hover:border-zinc-300 hover:bg-white hover:text-zinc-900 active:scale-[0.98]"
          aria-label="打开页面设置"
          aria-expanded={isSettingsPanelOpen}
        >
          <SlidersHorizontal className="h-4 w-4" />
        </button>
      )}

      {/* Graph Floating Button */}
      {showFloatingActions && (
        <button
          type="button"
          onClick={openGraphPanel}
          className={cn(
            "fixed bottom-20 right-6 z-[86] inline-flex h-11 items-center gap-2 rounded-2xl border border-zinc-200/80 bg-white/95 px-4 text-[14px] font-medium text-zinc-700 shadow-[0_2px_8px_rgba(0,0,0,0.04),0_8px_24px_rgba(0,0,0,0.06)] backdrop-blur-xl transition duration-300 hover:border-zinc-300 hover:bg-white hover:text-zinc-900 active:scale-[0.98]",
            isGraphDrawerOpen || isSettingsPanelOpen ? "pointer-events-none translate-y-4 opacity-0" : "translate-y-0 opacity-100"
          )}
          aria-label="打开知识图谱"
        >
          <Network className="h-4 w-4 text-zinc-500" />
          <span className="hidden sm:inline">知识图谱</span>
        </button>
      )}

      {/* Graph Drawer Panel */}
      <div
        className={cn(
          "fixed top-0 bottom-0 right-0 z-[84] bg-slate-50 border-l border-zinc-200/80 shadow-[0_0_40px_rgba(0,0,0,0.15)] flex",
          isGraphDrawerOpen && subjectId ? "translate-x-0 pointer-events-auto" : "translate-x-full pointer-events-none",
          !isGraphDragging && "transition-transform duration-300 ease-[cubic-bezier(0.2,0.8,0.2,1)]"
        )}
        style={{ width: graphPanelWidth }}
      >
        <div
          className={cn(
            "absolute bottom-0 left-0 top-0 z-50 -ml-[1px] hidden w-2 cursor-col-resize transition-colors hover:bg-blue-500/30 sm:block",
            isGraphDragging && "bg-blue-500/30"
          )}
          onMouseDown={handleGraphMouseDown}
        />
        <div className="flex-1 w-full h-full relative bg-slate-50 overflow-hidden shadow-inner flex flex-col">
          {subjectId && isGraphDrawerOpen && (
            <Suspense fallback={<GraphPanelFallback />}>
              <KnowledgeGraphSidePanel subjectId={subjectId} onClose={closeGraphPanel} />
            </Suspense>
          )}
        </div>
      </div>


    </div>
  );
}

