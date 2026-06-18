import { memo, Suspense, lazy, startTransition, useState, useRef, useEffect, useMemo, useCallback, useLayoutEffect, type CSSProperties } from "react";
import { createPortal } from "react-dom";

import { useLocation } from "react-router-dom";
import {
  BookOpen,
  FileText,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  ChevronDown,
  ChevronUp,
  Send,
  Bot,
  Network,
  Download,
  Layers3,
  StickyNote,
  Highlighter,
  Loader2,
  MessageCircle,
  Sparkles,
  RefreshCw,
  ExternalLink,
  ListCollapse,
  ListTree,
  SlidersHorizontal,
} from "lucide-react";
import { cn } from "../lib/utils";
import { getApiErrorMessage, LONG_RUNNING_API_TIMEOUT_MS, postSseJson } from "../api/client";
import { apiClient } from "../api/client";
import { AI_SCENE_DOCUMENT_SELECTION, useAiInteraction } from "../components/interaction";
import { useResizablePanel } from "../hooks/useResizablePanel";
import {
  BuildView,
  type DocViewMode,
  useDocBuildProgress,
  useDocMarkdown,
} from "../components/knowledge-docs";
import { CourseVectorNotice } from "../components/knowledge-graph/CourseVectorNotice";
import { MarkdownViewer } from "../components/ui/MarkdownViewer";
import { useToast } from "../components/ui/Toast";
import { CoursePagePillTitle } from "../components/course/CoursePagePillTitle";
import { buildCoursePath } from "../lib/courseNavigation";
import type { KnowledgeGraphSourceRefNavigationTarget } from "../components/knowledge-graph/KnowledgeGraphNodeDetailPanel";

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
  hasInteractive?: boolean;
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

interface FloatingInteractiveComposer {
  anchorId: string;
  selectedText: string;
  top: number;
  left: number;
  selectionContext: SelectionContextPayload;
}

interface PendingInteractiveBlock {
  id: string;
  anchorId: string;
  title: string;
  selectedText: string;
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

interface KnowledgeDocsReadingPosition {
  scrollTop: number;
  headingId: string;
  contentLength: number;
  updatedAt: number;
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
  sourceOrder: number;
}

interface KnowledgeCard {
  id: string;
  front: string;
  back: string;
  source: string;
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

interface KnowledgeDocInteractiveSelectionResponse {
  overlay_id: string;
  anchor_id: string;
  title: string;
  asset_path: string;
  preview_url: string;
  link_markdown: string;
  version_no: number;
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

type QuickChatSyncPhase = "start" | "session" | "token" | "done" | "error" | "settled";

interface QuickChatSyncEventDetail {
  phase?: QuickChatSyncPhase;
  courseId?: string | null;
  source?: string | null;
  anchorId?: string | null;
  selectedText?: string | null;
  localThreadId?: string | null;
  sessionId?: string | null;
  assistantLocalId?: string | null;
  userLocalId?: string | null;
  question?: string | null;
  content?: string | null;
  errorDetail?: string | null;
  createdAt?: string | null;
}

interface SelectionJumpEventDetail {
  courseId?: string | null;
  sessionId?: string | null;
  anchorId?: string | null;
  selectedText?: string | null;
}

interface KnowledgeDocsLocationState {
  selectionJump?: SelectionJumpEventDetail | null;
  selectionJumpAt?: number | null;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatTime(ts: number): string {
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function sanitizeExportText(value: string | null | undefined): string {
  return String(value ?? "").replace(/\r\n/g, "\n").trim();
}

function stripMarkdownSyntax(value: string | null | undefined): string {
  return sanitizeExportText(value)
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION|EXAMPLE|PRACTICE)\]/gi, "")
    .replace(/!\[[^\]]*]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)]\([^)]*\)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^[\s>*-]+/gm, "")
    .replace(/[*_~]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function isMarkdownTableLine(value: string): boolean {
  const text = String(value || "").trim();
  return /^\|.*\|\s*$/.test(text) || /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(text);
}

function cleanKnowledgeCardMarkdownLine(value: string | null | undefined): string {
  return sanitizeExportText(value)
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!\[[^\]]*]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)]\([^)]*\)/g, "$1")
    .replace(/^#{1,6}\s+/g, "")
    .replace(/^>\s*\[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION|EXAMPLE|PRACTICE)\]\s*/i, "")
    .replace(/^>\s?/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function truncatePlainText(value: string, maxLength: number): string {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`;
}

function tsvCell(value: string | null | undefined): string {
  return stripMarkdownSyntax(value).replace(/\t/g, " ").replace(/\r?\n/g, " ").trim();
}

function downloadTextFile(filename: string, content: string, mimeType = "text/plain;charset=utf-8") {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return;
  }
  const blob = new Blob([content], { type: mimeType });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

function quoteMindmapLabel(value: string): string {
  return `"${stripMarkdownSyntax(value).replace(/"/g, "'").slice(0, 72)}"`;
}

function buildAnnotationExportMarkdown(threads: CommentThreadView[], courseId?: string): string {
  const lines: string[] = [
    "# AITeachMe 知识文档选区问答",
    "",
    `- 课程：${courseId ?? "当前课程"}`,
    `- 导出时间：${new Date().toLocaleString("zh-CN")}`,
    `- 选区片段：${threads.length}`,
    "",
    "## 选区列表",
    "",
  ];

  threads.forEach((thread, index) => {
    lines.push(`### ${index + 1}. ${stripMarkdownSyntax(thread.selectedText).slice(0, 48) || "未命名片段"}`);
    lines.push("");
    lines.push(`- 位置：${thread.anchorId}`);
    lines.push(`- 创建：${formatTime(thread.createdAt)}`);
    lines.push("");
    lines.push("> 选中文本");
    lines.push("");
    lines.push(sanitizeExportText(thread.selectedText));
    lines.push("");
    for (const comment of thread.comments) {
      const role = comment.role === "assistant" ? "AI" : "我";
      lines.push(`**${role}（${formatTime(comment.createdAt)}）**`);
      lines.push("");
      lines.push(sanitizeExportText(comment.content));
      lines.push("");
    }
  });

  lines.push("## 思维导图式记录");
  lines.push("");
  lines.push("```mermaid");
  lines.push("mindmap");
  lines.push("  root((知识文档选区问答))");
  threads.slice(0, 24).forEach((thread, index) => {
    const title = stripMarkdownSyntax(thread.selectedText).slice(0, 36) || `片段 ${index + 1}`;
    lines.push(`    ${quoteMindmapLabel(`${index + 1}. ${title}`)}`);
    thread.comments.slice(0, 3).forEach((comment) => {
      const role = comment.role === "assistant" ? "AI" : "笔记";
      lines.push(`      ${quoteMindmapLabel(`${role}: ${comment.content}`)}`);
    });
  });
  lines.push("```");
  lines.push("");
  return lines.join("\n");
}

function buildKnowledgeCardsFromMarkdown(markdown: string, toc: TocItem[]): KnowledgeCard[] {
  const lines = sanitizeExportText(markdown).split("\n");
  const cards: KnowledgeCard[] = [];
  const tocTitleByText = new Map(toc.map((item) => [stripMarkdownSyntax(item.text), item.text]));
  let currentTitle = "";
  let buffer: string[] = [];

  const flush = () => {
    const front = stripMarkdownSyntax(currentTitle);
    const back = truncatePlainText(stripMarkdownSyntax(buffer.join("\n")), 320);
    if (front.length >= 2 && back.length >= 18) {
      cards.push({
        id: `doc-card-${cards.length + 1}`,
        front: `请解释：${front}`,
        back,
        source: tocTitleByText.get(front) ?? currentTitle,
      });
    }
    buffer = [];
  };

  for (const line of lines) {
    const headingMatch = line.match(/^(#{1,4})\s+(.+?)\s*$/);
    if (headingMatch) {
      flush();
      currentTitle = headingMatch[2];
      continue;
    }
    if (!currentTitle) {
      continue;
    }
    if (isMarkdownTableLine(line)) {
      continue;
    }
    const cleanLine = cleanKnowledgeCardMarkdownLine(line);
    if (!cleanLine || cleanLine.length < 8) {
      continue;
    }
    buffer.push(cleanLine);
  }
  flush();

  if (cards.length === 0) {
    const fallbackParagraphs = sanitizeExportText(markdown)
      .split(/\n{2,}/)
      .map((item) => item.split(/\n/).filter((line) => !isMarkdownTableLine(line)).map(cleanKnowledgeCardMarkdownLine).join("\n"))
      .filter((item) => item.length >= 32)
      .slice(0, 12);
    fallbackParagraphs.forEach((paragraph, index) => {
      cards.push({
        id: `doc-card-fallback-${index + 1}`,
        front: `记忆卡片 ${index + 1}`,
        back: truncatePlainText(paragraph, 320),
        source: "知识文档",
      });
    });
  }

  return cards
    .filter((card) => card.front.trim() && card.back.trim())
    .slice(0, 24);
}

function buildKnowledgeCardsTsv(cards: KnowledgeCard[]): string {
  return cards.map((card) => [tsvCell(card.front), tsvCell(card.back), tsvCell(card.source)].join("\t")).join("\n");
}

function normalizeGraphSourceTitle(value: string | null | undefined): string {
  return String(value ?? "")
    .replace(/\s+/g, "")
    .replace(/^折叠标题内容/, "")
    .replace(/^\d+(?:\.\d+)*\.?/, "")
    .trim()
    .toLowerCase();
}

function headingTextForSourceMatch(heading: HTMLElement): string {
  const clone = heading.cloneNode(true) as HTMLElement;
  clone.querySelectorAll("[data-heading-toggle], [data-heading-number]").forEach((node) => node.remove());
  return normalizeGraphSourceTitle(clone.textContent ?? "");
}

function headingMajorNumber(heading: HTMLElement): number | null {
  const rawNumber = heading.querySelector<HTMLElement>("[data-heading-number]")?.textContent?.trim() ?? "";
  const match = rawNumber.match(/^(\d+)/);
  if (!match) return null;
  const value = Number(match[1]);
  return Number.isFinite(value) && value > 0 ? value : null;
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
const KNOWLEDGE_DOCS_VIEW_PREFS_VERSION = 2;
const FLOATING_COMPOSER_THREAD_ID = "__floating-composer__";
const QUICK_CHAT_UPDATED_EVENT = "aiteachme:quick-chat-updated";
const SELECTION_JUMP_EVENT = "aiteachme:selection-jump";
const AI_INTERACTION_CLOSED_EVENT = "aiteachme:ai-sidebar-closed";
const KNOWLEDGE_GRAPH_DRAWER_EVENT = "aiteachme:knowledge-graph-drawer";
const SELECTION_SELECTED_TEXT_LIMIT = 1200;
const SELECTION_LOCAL_CONTEXT_CHARS = 900;
const SELECTION_SECTION_CONTEXT_CHARS = 3200;
const SELECTION_SOURCE_ORDER_STRIDE = 1_000_000;

function isTransientSelectionThreadId(threadId: string): boolean {
  return (
    threadId === FLOATING_COMPOSER_THREAD_ID ||
    threadId.startsWith("local-") ||
    threadId.startsWith("mark-") ||
    threadId.startsWith("jump-")
  );
}

function isStandaloneHighlightThreadId(threadId: string): boolean {
  return threadId.startsWith("mark-");
}

function resolveSelectionThreadSessionId(
  threadId: string | null,
  threadSessionIds: Record<string, string>,
): string | null {
  const normalizedThreadId = threadId?.trim() ?? "";
  if (!normalizedThreadId) {
    return null;
  }
  const mappedSessionId = threadSessionIds[normalizedThreadId]?.trim();
  if (mappedSessionId) {
    return mappedSessionId;
  }
  return isTransientSelectionThreadId(normalizedThreadId) ? null : normalizedThreadId;
}

function getHeadingActivationOffset(container: HTMLElement): number {
  return Math.min(128, Math.max(76, container.clientHeight * 0.18));
}

function createDefaultKnowledgeDocsViewPrefs(): KnowledgeDocsViewPrefs {
  return {
    widePage: false,
    showToc: true,
    showCommentPanel: false,
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
    showCommentPanel: false,
  };
}

function knowledgeDocsViewPrefsStorageKey(courseId?: string): string {
  return `aiteachme:knowledge-docs-view:v${KNOWLEDGE_DOCS_VIEW_PREFS_VERSION}:${courseId ?? "default"}`;
}

function knowledgeDocsReadingPositionStorageKey(courseId?: string): string {
  return `aiteachme:knowledge-docs-reading:v1:${courseId ?? "default"}`;
}

function readKnowledgeDocsViewPrefs(courseId?: string): KnowledgeDocsViewPrefs {
  if (!courseId || typeof window === "undefined") {
    return createDefaultKnowledgeDocsViewPrefs();
  }
  try {
    const raw = window.localStorage.getItem(knowledgeDocsViewPrefsStorageKey(courseId));
    if (!raw) {
      return createDefaultKnowledgeDocsViewPrefs();
    }
    return normalizeKnowledgeDocsViewPrefs(JSON.parse(raw));
  } catch {
    return createDefaultKnowledgeDocsViewPrefs();
  }
}

function persistKnowledgeDocsViewPrefs(courseId: string | undefined, prefs: KnowledgeDocsViewPrefs) {
  if (!courseId || typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(
      knowledgeDocsViewPrefsStorageKey(courseId),
      JSON.stringify({
        version: KNOWLEDGE_DOCS_VIEW_PREFS_VERSION,
        ...prefs,
      }),
    );
  } catch {
    // Ignore storage failures and fall back to in-memory state.
  }
}

function readKnowledgeDocsReadingPosition(courseId?: string): KnowledgeDocsReadingPosition | null {
  if (!courseId || typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(knowledgeDocsReadingPositionStorageKey(courseId));
    if (!raw) {
      return null;
    }
    const value = JSON.parse(raw) as Partial<KnowledgeDocsReadingPosition>;
    const scrollTop = Number(value.scrollTop ?? 0);
    if (!Number.isFinite(scrollTop) || scrollTop < 0) {
      return null;
    }
    return {
      scrollTop,
      headingId: String(value.headingId ?? ""),
      contentLength: Number(value.contentLength ?? 0) || 0,
      updatedAt: Number(value.updatedAt ?? 0) || 0,
    };
  } catch {
    return null;
  }
}

function persistKnowledgeDocsReadingPosition(courseId: string | undefined, position: KnowledgeDocsReadingPosition) {
  if (!courseId || typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(
      knowledgeDocsReadingPositionStorageKey(courseId),
      JSON.stringify(position),
    );
  } catch {
    // Ignore storage failures; reading continuity is a progressive enhancement.
  }
}

function tocEqual(a: TocItem[], b: TocItem[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (
      a[i].id !== b[i].id ||
      a[i].text !== b[i].text ||
      a[i].level !== b[i].level ||
      Boolean(a[i].hasInteractive) !== Boolean(b[i].hasInteractive)
    ) {
      return false;
    }
  }
  return true;
}

function stringSetEqual(a: ReadonlySet<string>, b: ReadonlySet<string>): boolean {
  if (a.size !== b.size) return false;
  for (const item of a) {
    if (!b.has(item)) return false;
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
      item.level === previous.level + 1 &&
      !item.hasInteractive
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

function collectCollapsibleTocIds(nodes: TocTreeNode[]): Set<string> {
  const ids = new Set<string>();
  const visit = (items: TocTreeNode[]) => {
    for (const node of items) {
      if (node.children.length > 0) {
        ids.add(node.item.id);
        visit(node.children);
      }
    }
  };
  visit(nodes);
  return ids;
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

function splitTocDisplayText(text: string): { number: string | null; title: string } {
  const trimmed = text.trim();
  const match = trimmed.match(/^((?:\d+\.)*\d+)\s+(.+)$/);
  if (!match) {
    return { number: null, title: trimmed };
  }
  const number = match[1]
    .split(".")
    .map((part) => String(Number(part) || part))
    .join(".");
  return { number, title: match[2].trim() };
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

function decodeRoutePart(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function routeIdsEqual(a: string | null | undefined, b: string | null | undefined): boolean {
  const left = a?.trim() ?? "";
  const right = b?.trim() ?? "";
  return left === right || (Boolean(left) && Boolean(right) && decodeRoutePart(left) === decodeRoutePart(right));
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

function isVisibleHeading(heading: HTMLElement): boolean {
  return heading.getClientRects().length > 0;
}

function isTocTrackedHeading(heading: HTMLElement): boolean {
  const level = getHeadingLevel(heading);
  return level >= 1 && level <= 3;
}

function findHeadingSectionElement(heading: HTMLElement): HTMLElement | null {
  const headingId = heading.getAttribute("data-heading-id");
  if (!headingId) return null;
  const section = heading.parentElement;
  if (!section?.matches("[data-heading-section-id]")) return null;
  return section.getAttribute("data-heading-section-id") === headingId ? section : null;
}

function findDirectSectionHeading(section: HTMLElement): HTMLElement | null {
  for (const child of Array.from(section.children)) {
    if (child instanceof HTMLElement && child.hasAttribute("data-heading-id")) {
      return child;
    }
  }
  return null;
}

function sectionHasOwnInteractiveEmbed(section: HTMLElement): boolean {
  return Array.from(section.querySelectorAll<HTMLElement>("[data-doc-interactive-embed]")).some(
    (embed) => embed.closest<HTMLElement>("[data-heading-section-id]") === section,
  );
}

function findNearestVisibleHeadingForTarget(heading: HTMLElement): HTMLElement | null {
  if (isVisibleHeading(heading)) {
    return heading;
  }

  let node = heading.parentElement;
  while (node) {
    if (node.matches("[data-heading-section-id]")) {
      const sectionHeading = findDirectSectionHeading(node);
      if (sectionHeading && isVisibleHeading(sectionHeading)) {
        return sectionHeading;
      }
    }
    node = node.parentElement;
  }
  return null;
}

function getElementContentTop(container: HTMLElement, element: HTMLElement): number {
  const containerRect = container.getBoundingClientRect();
  const rect = element.getBoundingClientRect();
  return rect.top - containerRect.top + container.scrollTop;
}

function collectSectionNodes(heading: HTMLElement): Node[] {
  const section = findHeadingSectionElement(heading);
  if (section) {
    return [section];
  }

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

function escapeCssAttributeValue(value: string): string {
  return value
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"')
    .replace(/\n/g, "\\a ");
}

function findHeadingById(contentRoot: HTMLElement | null, headingId: string): HTMLElement | null {
  if (!contentRoot || !headingId) {
    return null;
  }
  return contentRoot.querySelector<HTMLElement>(
    `[data-heading-id="${escapeCssAttributeValue(headingId)}"]`,
  );
}

function findHeadingFromCollapseSource(contentRoot: HTMLElement | null, headingId: string, source?: HTMLElement | null): HTMLElement | null {
  const section = source?.closest<HTMLElement>(".markdown-collapsible-section[data-heading-section-id]");
  const heading = section?.firstElementChild instanceof HTMLElement ? section.firstElementChild : null;
  if (heading?.getAttribute("data-heading-id") === headingId) {
    return heading;
  }
  return findHeadingById(contentRoot, headingId);
}

function PendingInteractiveBlockPortal({
  block,
  contentRoot,
}: {
  block: PendingInteractiveBlock;
  contentRoot: HTMLElement | null;
}) {
  const [host, setHost] = useState<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!contentRoot) {
      setHost(null);
      return;
    }
    const heading = findHeadingById(contentRoot, block.anchorId);
    const section = heading ? findHeadingSectionElement(heading) : null;
    const sectionBody = section?.querySelector<HTMLElement>(':scope > [data-heading-section-body="true"]') ?? null;
    const target = sectionBody ?? section ?? heading?.parentElement ?? contentRoot;
    const node = document.createElement("div");
    node.dataset.pendingInteractiveId = block.id;
    node.dataset.docInteractiveEmbed = "true";
    target.appendChild(node);
    setHost(node);
    return () => {
      node.remove();
      setHost(null);
    };
  }, [block.anchorId, block.id, contentRoot]);

  if (!host) {
    return null;
  }

  return createPortal(
    <div className="my-5 overflow-hidden rounded-xl border border-emerald-200 bg-white shadow-sm dark:border-emerald-500/25 dark:bg-slate-950">
      <div className="flex items-center gap-3 px-4 py-3">
        <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300">
          <Loader2 className="h-4 w-4 animate-spin" />
        </span>
        <span className="min-w-0">
          <span className="block truncate text-[13px] font-semibold text-slate-900 dark:text-slate-100">
            {block.title || "正在生成交互演示"}
          </span>
          <span className="mt-0.5 block text-xs text-slate-500 dark:text-slate-400">
            正在把划选内容转换成可操作的 HTML 微实验，完成后会在这里加载。
          </span>
        </span>
      </div>
      <div className="border-t border-emerald-100 bg-slate-50/70 p-3 dark:border-emerald-500/20 dark:bg-slate-900/45">
        <div className="flex min-h-[220px] items-center justify-center rounded-lg border border-dashed border-emerald-200 bg-white text-sm text-emerald-700 dark:border-emerald-500/25 dark:bg-slate-950 dark:text-emerald-300">
          <span className="flex max-w-md flex-col items-center px-5 text-center">
            <span className="inline-flex items-center">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              正在生成交互页...
            </span>
            {block.selectedText && (
              <span className="mt-3 line-clamp-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                {block.selectedText}
              </span>
            )}
          </span>
        </div>
      </div>
    </div>,
    host,
  );
}

function applyDocHeadingCollapseDomState(contentRoot: HTMLElement | null, headingId: string, collapsed: boolean): boolean {
  const heading = findHeadingById(contentRoot, headingId);
  const section = heading?.parentElement?.matches(".markdown-collapsible-section[data-heading-section-id]")
    ? heading.parentElement
    : heading?.closest<HTMLElement>(".markdown-collapsible-section[data-heading-section-id]");
  if (!heading || !section || section.getAttribute("data-heading-section-id") !== headingId) {
    return false;
  }

  if (collapsed) {
    section.setAttribute("data-collapsed", "true");
    heading.setAttribute("data-heading-collapsed", "true");
  } else {
    section.removeAttribute("data-collapsed");
    heading.removeAttribute("data-heading-collapsed");
  }

  const toggle = heading.querySelector<HTMLButtonElement>('[data-heading-toggle="true"]');
  if (toggle) {
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.setAttribute("aria-label", collapsed ? "展开标题内容" : "折叠标题内容");
    toggle.title = collapsed ? "展开标题内容" : "折叠标题内容";
  }

  return true;
}

function findSelectionHeading(anchorHeading: HTMLElement | null, selectedText: string): HTMLElement | null {
  if (!anchorHeading) {
    return null;
  }

  const target = selectedText.trim();
  if (!target) {
    return anchorHeading;
  }

  const anchorSection = findHeadingSectionElement(anchorHeading);
  if (!anchorSection) {
    return anchorHeading;
  }

  let bestHeading: HTMLElement = anchorHeading;
  let bestLevel = getHeadingLevel(anchorHeading);
  let bestScore = 0;
  let bestTextLength = Number.POSITIVE_INFINITY;
  let bestIndex = Number.MAX_SAFE_INTEGER;
  const candidateSections = [
    anchorSection,
    ...Array.from(anchorSection.querySelectorAll<HTMLElement>("[data-heading-section-id]")),
  ];

  for (const section of candidateSections) {
    const heading = findDirectSectionHeading(section);
    if (!heading) {
      continue;
    }
    const sectionText = collectNodeText([section]);
    const match = scoreSelectionInText(sectionText, target);
    if (match.score <= 0) {
      continue;
    }

    const level = getHeadingLevel(heading);
    const textLength = sectionText.length;
    const isBetter =
      match.score > bestScore ||
      (match.score === bestScore && level > bestLevel) ||
      (match.score === bestScore && level === bestLevel && textLength < bestTextLength) ||
      (match.score === bestScore && level === bestLevel && textLength === bestTextLength && match.index < bestIndex);
    if (isBetter) {
      bestHeading = heading;
      bestLevel = level;
      bestScore = match.score;
      bestTextLength = textLength;
      bestIndex = match.index;
    }
  }

  return bestHeading;
}

function findSelectionHeadingInDocument(
  contentRoot: HTMLElement | null,
  anchorId: string,
  selectedText: string
): HTMLElement | null {
  if (!contentRoot) {
    return null;
  }

  const target = selectedText.trim();
  const anchorHeading = findHeadingById(contentRoot, anchorId);
  if (!target) {
    return anchorHeading;
  }

  if (anchorHeading) {
    const anchorSectionText = collectNodeText(collectSectionNodes(anchorHeading));
    if (scoreSelectionInText(anchorSectionText, target).score > 0) {
      return findSelectionHeading(anchorHeading, target);
    }
  }

  let bestHeading: HTMLElement | null = null;
  let bestLevel = 0;
  let bestScore = 0;
  let bestTextLength = Number.POSITIVE_INFINITY;
  let bestIndex = Number.MAX_SAFE_INTEGER;
  const candidateSections = Array.from(contentRoot.querySelectorAll<HTMLElement>("[data-heading-section-id]"));

  for (const section of candidateSections) {
    const heading = findDirectSectionHeading(section);
    if (!heading) {
      continue;
    }
    const sectionText = collectNodeText([section]);
    const match = scoreSelectionInText(sectionText, target);
    if (match.score <= 0) {
      continue;
    }

    const level = getHeadingLevel(heading);
    const textLength = sectionText.length;
    const isBetter =
      !bestHeading ||
      match.score > bestScore ||
      (match.score === bestScore && level > bestLevel) ||
      (match.score === bestScore && level === bestLevel && textLength < bestTextLength) ||
      (match.score === bestScore && level === bestLevel && textLength === bestTextLength && match.index < bestIndex);
    if (isBetter) {
      bestHeading = heading;
      bestLevel = level;
      bestScore = match.score;
      bestTextLength = textLength;
      bestIndex = match.index;
    }
  }

  return bestHeading ?? anchorHeading;
}

function resolveSelectionSourceOrder(
  contentRoot: HTMLElement | null,
  anchorId: string,
  selectedText: string,
  tocOrderMap: Map<string, number>
): number {
  const fallbackOrder = tocOrderMap.get(anchorId) ?? Number.MAX_SAFE_INTEGER;
  if (!contentRoot || !anchorId) {
    return fallbackOrder;
  }

  const anchorHeading = findHeadingById(contentRoot, anchorId);
  const selectionHeading = findSelectionHeadingInDocument(contentRoot, anchorId, selectedText) ?? anchorHeading;
  const selectionHeadingId = selectionHeading?.getAttribute("data-heading-id") ?? anchorId;
  const headingOrder = tocOrderMap.get(selectionHeadingId) ?? fallbackOrder;
  if (headingOrder === Number.MAX_SAFE_INTEGER) {
    return headingOrder;
  }
  if (!selectionHeading || !selectedText.trim()) {
    return headingOrder * SELECTION_SOURCE_ORDER_STRIDE;
  }

  let selectionIndex = scoreSelectionInText(collectNodeText(collectSectionNodes(selectionHeading)), selectedText).index;
  if (selectionIndex < 0 && anchorHeading && anchorHeading !== selectionHeading) {
    selectionIndex = scoreSelectionInText(collectNodeText(collectSectionNodes(anchorHeading)), selectedText).index;
  }
  const boundedIndex = selectionIndex >= 0
    ? Math.min(selectionIndex, SELECTION_SOURCE_ORDER_STRIDE - 1)
    : 0;
  return headingOrder * SELECTION_SOURCE_ORDER_STRIDE + boundedIndex;
}

function compareCommentThreadViewOrder(left: CommentThreadView, right: CommentThreadView): number {
  if (left.sourceOrder !== right.sourceOrder) {
    return left.sourceOrder - right.sourceOrder;
  }
  return left.createdAt - right.createdAt;
}

interface TextSearchPosition {
  node: Text;
  offset: number;
  endOffset: number;
}

interface TextSearchIndex {
  text: string;
  positions: Array<TextSearchPosition | null>;
}

function normalizeSelectionSearchChar(char: string): string {
  if (/[\u200B-\u200D\uFEFF]/u.test(char)) return "";
  if (char === "\u00A0") return " ";
  return char;
}

function normalizeSelectionSearchText(text: string): string {
  return Array.from(text)
    .map(normalizeSelectionSearchChar)
    .join("")
    .trim();
}

function shouldIgnoreSelectionTextNode(textNode: Text): boolean {
  const parent = textNode.parentElement;
  if (!parent) return true;
  if (parent.closest("script, style, noscript, .katex-mathml, [hidden], [data-heading-number], [data-heading-toggle]")) {
    return true;
  }
  try {
    const style = window.getComputedStyle(parent);
    return style.display === "none" || style.visibility === "hidden";
  } catch {
    return false;
  }
}

function appendSearchTextNode(index: TextSearchIndex, textNode: Text) {
  if (shouldIgnoreSelectionTextNode(textNode)) return;
  const value = textNode.nodeValue ?? "";
  let offset = 0;
  for (const char of Array.from(value)) {
    const endOffset = offset + char.length;
    const normalized = normalizeSelectionSearchChar(char);
    for (const normalizedChar of Array.from(normalized)) {
      index.text += normalizedChar;
      index.positions.push({ node: textNode, offset, endOffset });
    }
    offset = endOffset;
  }
}

function appendVirtualSearchSeparator(index: TextSearchIndex) {
  if (!index.text || /\s$/u.test(index.text)) return;
  index.text += " ";
  index.positions.push(null);
}

function buildTextSearchIndex(roots: Node[]): TextSearchIndex {
  const index: TextSearchIndex = { text: "", positions: [] };
  for (const rootNode of roots) {
    if (rootNode.nodeType === Node.TEXT_NODE) {
      appendSearchTextNode(index, rootNode as Text);
      appendVirtualSearchSeparator(index);
      continue;
    }
    const walker = document.createTreeWalker(rootNode, NodeFilter.SHOW_TEXT);
    let current = walker.nextNode();
    while (current) {
      appendSearchTextNode(index, current as Text);
      current = walker.nextNode();
    }
    appendVirtualSearchSeparator(index);
  }
  return index;
}

function createCondensedSearchText(text: string): { text: string; sourceIndexByCondensed: number[] } {
  const chars: string[] = [];
  const sourceIndexByCondensed: number[] = [];
  Array.from(text).forEach((char, index) => {
    if (/\s/u.test(char)) return;
    chars.push(char);
    sourceIndexByCondensed.push(index);
  });
  return {
    text: chars.join(""),
    sourceIndexByCondensed,
  };
}

function rangeFromSearchSpan(index: TextSearchIndex, start: number, end: number): Range | null {
  if (end <= start) return null;
  let startPosition: TextSearchPosition | null = null;
  let endPosition: TextSearchPosition | null = null;

  for (let cursor = start; cursor < end; cursor += 1) {
    const position = index.positions[cursor];
    if (position) {
      startPosition = position;
      break;
    }
  }
  for (let cursor = end - 1; cursor >= start; cursor -= 1) {
    const position = index.positions[cursor];
    if (position) {
      endPosition = position;
      break;
    }
  }

  if (!startPosition || !endPosition) return null;

  const range = document.createRange();
  range.setStart(startPosition.node, startPosition.offset);
  range.setEnd(endPosition.node, endPosition.endOffset);
  return range;
}

function findRangesForSelectedText(index: TextSearchIndex, selectedText: string): Range[] {
  const target = normalizeSelectionSearchText(selectedText);
  if (!index.text || !target) return [];

  const exactRanges: Range[] = [];
  let exactStart = index.text.indexOf(target);
  while (exactStart >= 0) {
    const range = rangeFromSearchSpan(index, exactStart, exactStart + target.length);
    if (range) {
      exactRanges.push(range);
    }
    exactStart = index.text.indexOf(target, exactStart + Math.max(target.length, 1));
  }
  if (exactRanges.length > 0) {
    return exactRanges;
  }

  const condensedSource = createCondensedSearchText(index.text);
  const condensedTarget = target.replace(/\s+/gu, "");
  if (!condensedTarget) return [];

  const ranges: Range[] = [];
  let condensedStart = condensedSource.text.indexOf(condensedTarget);
  while (condensedStart >= 0) {
    const sourceStart = condensedSource.sourceIndexByCondensed[condensedStart];
    const sourceEnd = condensedSource.sourceIndexByCondensed[condensedStart + condensedTarget.length - 1];
    if (sourceStart !== undefined && sourceEnd !== undefined) {
      const range = rangeFromSearchSpan(index, sourceStart, sourceEnd + 1);
      if (range) {
        ranges.push(range);
      }
    }
    condensedStart = condensedSource.text.indexOf(
      condensedTarget,
      condensedStart + Math.max(condensedTarget.length, 1),
    );
  }
  return ranges;
}

function buildSelectionMatchTokens(selectedText: string): string[] {
  const tokens = normalizeSelectionSearchText(selectedText)
    .match(/[\u4e00-\u9fff]+|[A-Za-z_][A-Za-z0-9_]*|[\u0370-\u03FFA-Za-z0-9_]+|[0-9]+(?:\.[0-9]+)?/gu) ?? [];
  const unique = new Set<string>();
  for (const token of tokens) {
    const condensed = token.replace(/\s+/gu, "");
    if (!condensed) continue;
    const meaningful =
      condensed.length >= 2 ||
      /[\u4e00-\u9fff]/u.test(condensed) ||
      /[\u0370-\u03FF]/u.test(condensed);
    if (meaningful) {
      unique.add(condensed);
    }
  }
  return Array.from(unique);
}

function findApproximateRangeForSelectedText(index: TextSearchIndex, selectedText: string): Range | null {
  const tokens = buildSelectionMatchTokens(selectedText);
  if (tokens.length === 0) return null;

  const condensedSource = createCondensedSearchText(index.text);
  let matchedCount = 0;
  let matchedWeight = 0;
  let totalWeight = 0;
  let sourceStart = Number.POSITIVE_INFINITY;
  let sourceEnd = -1;

  for (const token of tokens) {
    const tokenWeight = Math.min(token.length, 12);
    totalWeight += tokenWeight;
    const condensedStart = condensedSource.text.indexOf(token);
    if (condensedStart < 0) continue;

    const tokenSourceStart = condensedSource.sourceIndexByCondensed[condensedStart];
    const tokenSourceEnd = condensedSource.sourceIndexByCondensed[condensedStart + token.length - 1];
    if (tokenSourceStart === undefined || tokenSourceEnd === undefined) continue;

    matchedCount += 1;
    matchedWeight += tokenWeight;
    sourceStart = Math.min(sourceStart, tokenSourceStart);
    sourceEnd = Math.max(sourceEnd, tokenSourceEnd + 1);
  }

  const hasStrongSingleToken = matchedCount === 1 && matchedWeight >= 8;
  const hasEnoughTokenCoverage =
    matchedCount >= 2 &&
    matchedWeight >= Math.min(10, Math.max(4, totalWeight * 0.35));

  if ((!hasStrongSingleToken && !hasEnoughTokenCoverage) || !Number.isFinite(sourceStart) || sourceEnd <= sourceStart) {
    return null;
  }

  return rangeFromSearchSpan(index, sourceStart, sourceEnd);
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

function scoreSelectionInText(sectionText: string, selectedText: string): { score: number; index: number } {
  const exactIndex = findSelectionIndex(sectionText, selectedText);
  if (exactIndex >= 0) {
    return { score: 10_000 + Math.min(normalizeSelectionContextText(selectedText).length, 1_000), index: exactIndex };
  }

  const tokens = buildSelectionMatchTokens(selectedText);
  if (tokens.length === 0) {
    return { score: 0, index: -1 };
  }

  const condensedSource = createCondensedSearchText(normalizeSelectionSearchText(sectionText));
  if (!condensedSource.text) {
    return { score: 0, index: -1 };
  }

  let matchedCount = 0;
  let matchedWeight = 0;
  let totalWeight = 0;
  let sourceStart = Number.POSITIVE_INFINITY;

  for (const token of tokens) {
    const tokenWeight = Math.min(token.length, 12);
    totalWeight += tokenWeight;
    const tokenIndex = condensedSource.text.indexOf(token);
    if (tokenIndex < 0) {
      continue;
    }
    const tokenSourceStart = condensedSource.sourceIndexByCondensed[tokenIndex];
    if (tokenSourceStart === undefined) {
      continue;
    }
    matchedCount += 1;
    matchedWeight += tokenWeight;
    sourceStart = Math.min(sourceStart, tokenSourceStart);
  }

  const hasStrongSingleToken = matchedCount === 1 && matchedWeight >= 8;
  const hasEnoughTokenCoverage =
    matchedCount >= 2 &&
    matchedWeight >= Math.min(10, Math.max(4, totalWeight * 0.35));

  if ((!hasStrongSingleToken && !hasEnoughTokenCoverage) || !Number.isFinite(sourceStart)) {
    return { score: 0, index: -1 };
  }

  const coverage = totalWeight > 0 ? matchedWeight / totalWeight : 0;
  return {
    score: Math.round(coverage * 1_000) + matchedWeight,
    index: sourceStart,
  };
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
  const gap = 16;
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

const DocMarkdown = memo(function DocMarkdown({
  content,
  courseId,
  onHeadingCollapseChange,
}: {
  content: string;
  courseId?: string;
  onHeadingCollapseChange: (id: string, collapsed: boolean, source?: HTMLElement | null) => boolean | void;
}) {
  return (
    <MarkdownViewer
      content={content}
      variant="document"
      headingAnchors
      headingNumbering
      collapsibleHeadings
      onHeadingCollapseChange={onHeadingCollapseChange}
      assetCourse={courseId}
    />
  );
});

const CommentMarkdown = memo(function CommentMarkdown({ content }: { content: string }) {
  return (
    <div className="break-words text-xs leading-relaxed text-slate-700 dark:text-slate-300 [&_a]:text-indigo-600 [&_a]:underline [&_a]:underline-offset-2 dark:[&_a]:text-indigo-300 [&_blockquote]:my-2 [&_blockquote]:rounded-r-md [&_blockquote]:border-l-2 [&_blockquote]:border-indigo-200 [&_blockquote]:bg-indigo-50/60 [&_blockquote]:px-2.5 [&_blockquote]:py-1.5 dark:[&_blockquote]:border-indigo-500/30 dark:[&_blockquote]:bg-indigo-500/10 [&_code]:rounded [&_code]:bg-slate-100 [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[11px] dark:[&_code]:bg-slate-800 dark:[&_code]:text-slate-200 [&_h1]:mb-1.5 [&_h1]:mt-3 [&_h1]:text-sm [&_h1]:font-semibold [&_h1]:text-slate-800 dark:[&_h1]:text-slate-100 [&_h2]:mb-1.5 [&_h2]:mt-3 [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-slate-800 dark:[&_h2]:text-slate-100 [&_h3]:mb-1 [&_h3]:mt-2.5 [&_h3]:text-xs [&_h3]:font-semibold [&_h3]:text-slate-700 dark:[&_h3]:text-slate-200 [&_li]:leading-relaxed [&_ol]:mb-1.5 [&_ol]:list-decimal [&_ol]:space-y-1 [&_ol]:pl-4 [&_p:last-child]:mb-0 [&_p]:mb-1.5 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-slate-900 [&_pre]:p-2.5 [&_pre]:text-slate-100 dark:[&_pre]:bg-slate-950 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_table]:min-w-full [&_table]:rounded-md [&_table]:border [&_table]:border-slate-200 [&_table]:text-[11px] dark:[&_table]:border-slate-700 [&_td]:border-t [&_td]:border-slate-100 [&_td]:px-2 [&_td]:py-1 dark:[&_td]:border-slate-800 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-semibold [&_thead]:bg-slate-50 dark:[&_thead]:bg-slate-900 [&_ul]:mb-1.5 [&_ul]:list-disc [&_ul]:space-y-1 [&_ul]:pl-4">
      <MarkdownViewer content={content || " "} />
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
          className="h-full rounded-full bg-[linear-gradient(90deg,#1d4ed8_0%,#2563eb_58%,#60a5fa_100%)] transition-[width] duration-500"
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
    <section className="mb-5 rounded-2xl border border-stone-200 bg-stone-50 px-4 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/70">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-slate-900 dark:text-slate-100">{title}</p>
          <p className="mt-1 text-[13px] leading-5 text-slate-600 dark:text-slate-400">{description}</p>
        </div>
        {(hasLiveVersion || hasDraftVersion) && (
          <div className="inline-flex rounded-full border border-stone-200 bg-white/80 p-1 shadow-sm dark:border-slate-700 dark:bg-slate-950/80">
            <button
              type="button"
              disabled={!hasLiveVersion}
              onClick={() => hasLiveVersion && onViewModeChange("live")}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                viewMode === "live"
                  ? "bg-stone-800 text-white shadow-sm dark:bg-slate-100 dark:text-slate-900"
                  : hasLiveVersion
                    ? "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
                    : "cursor-not-allowed text-slate-300 dark:text-slate-600",
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
                    ? "bg-slate-900 text-white shadow-sm dark:bg-slate-100 dark:text-slate-900"
                  : hasDraftVersion
                    ? "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
                    : "cursor-not-allowed text-slate-300 dark:text-slate-600",
              )}
            >
              本轮草稿
            </button>
          </div>
        )}
      </div>
      {(liveLabel || draftLabel) && (
        <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-slate-500 dark:text-slate-400">
          {liveLabel ? <span className="rounded-full bg-white/80 px-2.5 py-1 dark:bg-slate-950/80">正式版更新于 {liveLabel}</span> : null}
          {draftLabel ? <span className="rounded-full bg-white/80 px-2.5 py-1 dark:bg-slate-950/80">草稿更新于 {draftLabel}</span> : null}
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

function DocLoadingState() {
  return (
    <section className="mx-auto flex min-h-[360px] w-full max-w-3xl flex-col items-center justify-center rounded-xl border border-slate-200/80 bg-white px-6 py-12 text-center shadow-sm dark:border-slate-800 dark:bg-slate-950">
      <div className="relative flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300">
        <FileText className="h-5 w-5" />
        <Loader2 className="absolute -right-1 -top-1 h-4 w-4 animate-spin text-indigo-500 dark:text-indigo-300" />
      </div>
      <h2 className="mt-4 text-base font-semibold text-slate-900 dark:text-slate-100">正在加载知识文档</h2>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">正在加载内容。</p>
      <div className="mt-6 w-full max-w-md space-y-2" aria-hidden="true">
        <div className="h-2.5 w-full animate-pulse rounded-full bg-slate-100 dark:bg-slate-800" />
        <div className="h-2.5 w-4/5 animate-pulse rounded-full bg-slate-100 dark:bg-slate-800" />
        <div className="h-2.5 w-2/3 animate-pulse rounded-full bg-slate-100 dark:bg-slate-800" />
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
    <section className="rounded-2xl border border-rose-200 bg-rose-50/60 px-5 py-5 dark:border-rose-500/30 dark:bg-rose-500/10">
      <p className="text-sm text-rose-700 dark:text-rose-300">{message}</p>
      <button
        onClick={onRetry}
        className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-rose-200 bg-white px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-50 dark:border-rose-500/30 dark:bg-slate-950 dark:text-rose-300 dark:hover:bg-rose-500/10"
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
  onSizeChange,
}: {
  comment: Comment;
  defaultCollapsed?: boolean;
  onSizeChange?: () => void;
}) {
  const isAssistant = comment.role === "assistant";
  const contentRef = useRef<HTMLDivElement>(null);
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed);
  const [canCollapse, setCanCollapse] = useState(false);

  useLayoutEffect(() => {
    if (!onSizeChange || typeof window === "undefined") return;

    let secondFrameId = 0;
    onSizeChange();
    const firstFrameId = window.requestAnimationFrame(() => {
      onSizeChange();
      secondFrameId = window.requestAnimationFrame(onSizeChange);
    });

    return () => {
      window.cancelAnimationFrame(firstFrameId);
      if (secondFrameId) {
        window.cancelAnimationFrame(secondFrameId);
      }
    };
  }, [canCollapse, comment.content, isCollapsed, onSizeChange]);

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
          ? "border-indigo-100 bg-indigo-50/60 dark:border-indigo-500/30 dark:bg-indigo-500/10"
          : "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950/80"
      )}
    >
      <div className="px-3 py-2">
        <div className="mb-1.5 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <div
              className={cn(
                "flex h-5 w-5 items-center justify-center rounded-md text-[10px] font-semibold text-white",
                isAssistant ? "bg-indigo-500" : "bg-slate-900"
              )}
            >
              {isAssistant ? "AI" : "我"}
            </div>
            <span className="text-xs font-medium text-slate-700 dark:text-slate-300">
              {isAssistant ? "AI 助手" : "我"}
            </span>
            <span className="text-[10px] text-slate-400 dark:text-slate-500">
              {formatTime(comment.createdAt)}
            </span>
          </div>
          <div className="flex items-center gap-1">
            {comment.streaming && <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-400" />}
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
                      ? "gap-1 bg-indigo-100 px-2 text-[10px] font-medium text-indigo-700 hover:bg-indigo-200 dark:bg-indigo-500/10 dark:text-indigo-300 dark:hover:bg-indigo-500/15"
                      : "gap-1 bg-slate-100 px-2 text-[10px] font-medium text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                    : "w-6 text-slate-400 hover:bg-white/80 hover:text-slate-700 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-200"
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
            "relative text-xs leading-relaxed text-slate-700 dark:text-slate-300",
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
                  isAssistant ? "from-indigo-50 via-indigo-50/95 dark:from-slate-950 dark:via-slate-950/95" : "from-white via-white/95 dark:from-slate-950 dark:via-slate-950/95"
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
                    ? "border-indigo-200 bg-white/95 text-indigo-700 hover:border-indigo-300 hover:bg-indigo-50 dark:border-indigo-500/30 dark:bg-slate-950/95 dark:text-indigo-300 dark:hover:bg-indigo-500/10"
                    : "border-slate-200 bg-white/95 text-slate-700 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950/95 dark:text-slate-300 dark:hover:bg-slate-800"
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
  isActive,
  onFocus,
  onJumpToAnchor,
  onOpenAiInteraction,
  onSizeChange,
  compactMode,
  isAligned,
}: {
  anchorId: string;
  comments: Comment[];
  selectedText: string;
  isActive: boolean;
  onFocus: () => void;
  onJumpToAnchor: (id: string) => void;
  onOpenAiInteraction: () => void;
  onSizeChange?: () => void;
  compactMode: boolean;
  isAligned: boolean;
}) {
  const [isThreadCollapsed, setIsThreadCollapsed] = useState(false);
  const selectedPreview = selectedText.trim() || "定位划词位置";

  return (
    <section
      onClick={onFocus}
      className={cn(
        "rounded-lg border bg-white overflow-hidden transition-colors dark:bg-slate-950/80",
        isActive
          ? "border-indigo-300 bg-indigo-50/25 dark:border-indigo-500/40 dark:bg-indigo-500/10"
          : "border-slate-200 dark:border-slate-800",
        isAligned && !isActive && "border-slate-300/80"
      )}
    >
      <div className="flex items-center justify-between gap-2 border-b border-slate-200/80 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-950">
        <button
          type="button"
          onClick={() => onJumpToAnchor(anchorId)}
          title={selectedText ? `定位划词：${selectedText}` : "定位划词位置"}
          className={cn(
            "group flex min-w-0 flex-1 items-center gap-2 rounded-md px-1 py-0.5 text-left transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/70",
            isActive && "bg-indigo-50/70 dark:bg-indigo-500/10"
          )}
        >
          <span
            className={cn(
              "h-5 w-[3px] shrink-0 rounded-full",
              isActive ? "bg-indigo-400" : "bg-slate-300"
            )}
          />
          <span
            className={cn(
              "min-w-0 truncate text-[11px] font-medium",
              isActive ? "text-indigo-700 dark:text-indigo-300" : "text-slate-600 group-hover:text-slate-800 dark:text-slate-400 dark:group-hover:text-slate-200"
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
              onOpenAiInteraction();
            }}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-500 transition hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400 dark:hover:border-indigo-500/30 dark:hover:bg-indigo-500/10 dark:hover:text-indigo-300"
            aria-label="在 AI 面板继续对话"
            title="在 AI 面板继续对话"
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </button>
          <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            {comments.length}
          </span>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setIsThreadCollapsed((prev) => !prev);
            }}
            className="flex h-6 w-6 items-center justify-center rounded-md text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-200"
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
                onSizeChange={onSizeChange}
              />
            ))}
          </div>
          <div className="border-t border-slate-200 bg-white p-2 dark:border-slate-800 dark:bg-slate-950">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onOpenAiInteraction();
              }}
              className="flex w-full items-center justify-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-600 transition hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-indigo-500/30 dark:hover:bg-indigo-500/10 dark:hover:text-indigo-300"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              在右侧 AI 面板继续对话
            </button>
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
  const {
    openAiInteraction,
    isSidebarOpen: isAssistantOpen,
    activeConversationSessionId,
    activeConversationSelectionTarget,
    sidebarRequest,
  } = useAiInteraction();
  const location = useLocation();
  const { toast } = useToast();
  const {
    courseId,
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
    showDocLoadingState,
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
  const [threadHistoryRefreshKey, setThreadHistoryRefreshKey] = useState(0);
  const [selectionHighlights, setSelectionHighlights] = useState<SelectionHighlight[]>([]);
  const [, setThreadDrafts] = useState<Record<string, string>>({});
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
  const [collapsedDocHeadingIds, setCollapsedDocHeadingIds] = useState<Set<string>>(new Set());

  // Floating selection toolbar state
  const [floatingToolbar, setFloatingToolbar] = useState<FloatingToolbar | null>(null);
  const [floatingComment, setFloatingComment] = useState<FloatingComment | null>(null);
  const [floatingInteractive, setFloatingInteractive] = useState<FloatingInteractiveComposer | null>(null);
  const [pendingInteractiveBlocks, setPendingInteractiveBlocks] = useState<PendingInteractiveBlock[]>([]);
  const [interactivePrompt, setInteractivePrompt] = useState("");
  const [isGeneratingInteractive, setIsGeneratingInteractive] = useState(false);
  const [interactiveError, setInteractiveError] = useState<string | null>(null);
  const [floatingInput, setFloatingInput] = useState("");
  const [floatingComposerHeight, setFloatingComposerHeight] = useState(236);
  const initialViewportWidth = typeof window !== "undefined" ? window.innerWidth : 1200;
  const [viewportWidth, setViewportWidth] = useState(() =>
    typeof window !== "undefined" ? initialViewportWidth : COMMENT_DRAWER_BREAKPOINT
  );
  const [viewPrefs, setViewPrefs] = useState<KnowledgeDocsViewPrefs>(() => readKnowledgeDocsViewPrefs(courseId));
  const [isCardsPanelOpen, setIsCardsPanelOpen] = useState(false);
  const [knowledgeCards, setKnowledgeCards] = useState<KnowledgeCard[]>([]);
  const [cardsGenerated, setCardsGenerated] = useState(false);
  const [activeDrawer, setActiveDrawer] = useState<"toc" | "comment" | null>(null);
  const [isTocScrollbarVisible, setIsTocScrollbarVisible] = useState(false);
  const [tocScrollThumbStyle, setTocScrollThumbStyle] = useState<TocScrollThumbStyle>({ top: 0, height: 0 });

  const [isGraphDrawerOpen, setIsGraphDrawerOpen] = useState(false);
  const graphDrawerRef = useRef<HTMLDivElement>(null);
  const isNarrowInitialViewport = initialViewportWidth < 640;
  const graphDesktopMaxWidth = Math.max(400, initialViewportWidth * 0.94);
  const graphDesktopDefaultWidth = Math.min(graphDesktopMaxWidth, Math.max(760, initialViewportWidth * 0.82));
  const graphDesktopMinWidth = Math.min(graphDesktopMaxWidth, Math.max(560, initialViewportWidth * 0.52));
  const { width: graphPanelWidth, isDragging: isGraphDragging, handleMouseDown: handleGraphMouseDown } = useResizablePanel({
    defaultWidth: isNarrowInitialViewport ? initialViewportWidth : graphDesktopDefaultWidth,
    minWidth: isNarrowInitialViewport ? initialViewportWidth : graphDesktopMinWidth,
    maxWidth: isNarrowInitialViewport ? initialViewportWidth : graphDesktopMaxWidth,
    liveResizeRef: graphDrawerRef,
  });

  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }
    document.body.classList.toggle("knowledge-graph-panel-open", isGraphDrawerOpen);
    return () => {
      document.body.classList.remove("knowledge-graph-panel-open");
    };
  }, [isGraphDrawerOpen]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const contentAreaRef = useRef<HTMLDivElement>(null);
  const floatingRef = useRef<HTMLDivElement>(null);
  const commentPanelRef = useRef<HTMLDivElement>(null);
  const commentViewportRef = useRef<HTMLDivElement>(null);
  const commentThreadListRef = useRef<HTMLDivElement>(null);
  const desktopCommentTrackRef = useRef<HTMLDivElement>(null);
  const floatingComposerCardRef = useRef<HTMLDivElement>(null);
  const floatingComposerTextareaRef = useRef<HTMLTextAreaElement>(null);
  const selectedRangeRef = useRef<Range | null>(null);
  const selectedRangeThreadIdRef = useRef<string | null>(null);
  const commentsRef = useRef<Comment[]>([]);

  useEffect(() => {
    if (!courseId || typeof window === "undefined") {
      return;
    }
    const storageKey = `aiteachme:knowledge-docs-selection-hint:${courseId}`;
    let shouldShowHint = true;
    try {
      if (window.sessionStorage.getItem(storageKey) === "1") {
        shouldShowHint = false;
      }
    } catch {
      // Ignore storage failures; the hint is helpful but not required for reading.
    }
    if (!shouldShowHint) {
      return;
    }
    const timer = window.setTimeout(() => {
      toast({
        title: "可以滑选文字提问",
        description: "在正文中拖动选中一段内容，就能让 AI 围绕这段知识解释、追问或总结。",
        variant: "info",
        duration: 8000,
      });
      try {
        window.sessionStorage.setItem(storageKey, "1");
      } catch {
        // Ignore storage failures; the hint is helpful but not required for reading.
      }
    }, 700);
    return () => window.clearTimeout(timer);
  }, [courseId, toast]);
  const quickChatStartedThreadIdsRef = useRef(new Set<string>());
  const threadRefs = useRef(new Map<string, HTMLDivElement>());
  const headingFlashTimersRef = useRef(new Map<string, number>());
  const tocNavRef = useRef<HTMLElement>(null);
  const tocDefaultInitializedRef = useRef(false);
  const streamControllersRef = useRef(new Map<string, AbortController>());
  const tocScrollbarTimerRef = useRef<number | null>(null);
  const tocAutoScrollingRef = useRef(false);
  const tocAutoScrollReleaseTimerRef = useRef<number | null>(null);
  const readingPositionSaveTimerRef = useRef<number | null>(null);
  const readingPositionRestoredRef = useRef<string>("");
  const activeHeadingRef = useRef(activeHeading);
  const lastAutoCommentHighlightHeadingRef = useRef(activeHeading);
  const pendingSelectionJumpRef = useRef<SelectionJumpEventDetail | null>(null);
  const handledRouteSelectionJumpRef = useRef<number | null>(null);
  const collapsedDocHeadingIdsRef = useRef<Set<string>>(new Set());
  const collapsedDocHeadingCommitTimerRef = useRef<number | null>(null);
  const scrollingToHeadingTargetRef = useRef<string | null>(null);
  const scrollspyIgnoreTimerRef = useRef<number | null>(null);
  const scrollRestorationTimerRef = useRef<number | null>(null);
  const docCollapseLayoutRefreshNeededRef = useRef(false);
  const pendingHeadingCollapseScrollRef = useRef<{ id: string; top: number } | null>(null);

  const isCompactToc = viewportWidth < TOC_DRAWER_BREAKPOINT;
  const isCompactComment = viewportWidth < COMMENT_DRAWER_BREAKPOINT;
  const isCompactPanels = isCompactToc || isCompactComment;
  const hasCompactTocControl = isCompactToc && viewPrefs.showToc;
  const shouldHideCommentPanelForAssistant = isAssistantOpen;
  const hasCompactCommentControl = isCompactComment && viewPrefs.showCommentPanel && !shouldHideCommentPanelForAssistant;
  const isTocVisible = viewPrefs.showToc && (isCompactToc ? activeDrawer === "toc" : !isTocCollapsed);
  const isCommentVisible =
    viewPrefs.showCommentPanel &&
    !shouldHideCommentPanelForAssistant &&
    (isCompactComment ? activeDrawer === "comment" : !isCommentCollapsed);
  const showDesktopCommentPanel =
    !isCompactComment &&
    viewPrefs.showCommentPanel &&
    !isCommentCollapsed &&
    !shouldHideCommentPanelForAssistant;
  const pageWideMode = viewPrefs.widePage;

  const updateViewPrefs = useCallback((updater: (prev: KnowledgeDocsViewPrefs) => KnowledgeDocsViewPrefs) => {
    setViewPrefs((prev) => normalizeKnowledgeDocsViewPrefs(updater(prev)));
  }, []);

  const scheduleCollapsedDocHeadingStateCommit = useCallback((delayMs = 180) => {
    if (!docCollapseLayoutRefreshNeededRef.current) {
      return;
    }
    if (collapsedDocHeadingCommitTimerRef.current !== null) {
      window.clearTimeout(collapsedDocHeadingCommitTimerRef.current);
    }
    collapsedDocHeadingCommitTimerRef.current = window.setTimeout(() => {
      collapsedDocHeadingCommitTimerRef.current = null;
      const snapshot = new Set(collapsedDocHeadingIdsRef.current);
      startTransition(() => {
        setCollapsedDocHeadingIds((prev) => (stringSetEqual(prev, snapshot) ? prev : snapshot));
      });
    }, delayMs);
  }, []);

  useEffect(() => () => {
    if (collapsedDocHeadingCommitTimerRef.current !== null) {
      window.clearTimeout(collapsedDocHeadingCommitTimerRef.current);
      collapsedDocHeadingCommitTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    const needsRefresh = Boolean(
      comments.length > 0 ||
      selectionHighlights.length > 0 ||
      floatingComment ||
      showDesktopCommentPanel ||
      isAssistantOpen
    );
    docCollapseLayoutRefreshNeededRef.current = needsRefresh;
    if (needsRefresh) {
      scheduleCollapsedDocHeadingStateCommit(0);
    }
  }, [
    comments.length,
    floatingComment,
    isAssistantOpen,
    scheduleCollapsedDocHeadingStateCommit,
    selectionHighlights.length,
    showDesktopCommentPanel,
  ]);

  const handleDocHeadingCollapseChange = useCallback((id: string, collapsed: boolean, source?: HTMLElement | null) => {
    const container = scrollRef.current;
    const heading = findHeadingFromCollapseSource(contentAreaRef.current, id, source);
    const previousTop = container && heading && isVisibleHeading(heading)
      ? heading.getBoundingClientRect().top
      : null;

    const next = new Set(collapsedDocHeadingIdsRef.current);
    if (collapsed) {
      next.add(id);
    } else {
      next.delete(id);
    }
    collapsedDocHeadingIdsRef.current = next;

    const handledDom = applyDocHeadingCollapseDomState(contentAreaRef.current, id, collapsed);
    if (handledDom) {
      if (container && previousTop !== null) {
        const nextHeading = findHeadingFromCollapseSource(contentAreaRef.current, id, source);
        if (nextHeading && isVisibleHeading(nextHeading)) {
          const delta = nextHeading.getBoundingClientRect().top - previousTop;
          if (Math.abs(delta) >= 0.5) {
            const previousScrollBehavior = container.style.scrollBehavior;
            container.style.scrollBehavior = "auto";
            container.scrollTop += delta;
            if (previousScrollBehavior) {
              container.style.scrollBehavior = previousScrollBehavior;
            } else {
              container.style.removeProperty("scroll-behavior");
            }
          }
        }
      }
      pendingHeadingCollapseScrollRef.current = null;
      scheduleCollapsedDocHeadingStateCommit();
      window.requestAnimationFrame(() => {
        container?.dispatchEvent(new Event("scroll"));
      });
      return true;
    }

    if (container && previousTop !== null) {
      pendingHeadingCollapseScrollRef.current = { id, top: previousTop };
    }
    scheduleCollapsedDocHeadingStateCommit();
    window.requestAnimationFrame(() => {
      const pending = pendingHeadingCollapseScrollRef.current;
      const nextHeading = findHeadingFromCollapseSource(contentAreaRef.current, id, source);
      if (!container || !pending || pending.id !== id || !nextHeading || !isVisibleHeading(nextHeading)) {
        container?.dispatchEvent(new Event("scroll"));
        return;
      }
      const delta = nextHeading.getBoundingClientRect().top - pending.top;
      if (Math.abs(delta) >= 0.5) {
        const previousScrollBehavior = container.style.scrollBehavior;
        container.style.scrollBehavior = "auto";
        container.scrollTop += delta;
        if (previousScrollBehavior) {
          container.style.scrollBehavior = previousScrollBehavior;
        } else {
          container.style.removeProperty("scroll-behavior");
        }
      }
      pendingHeadingCollapseScrollRef.current = null;
      container.dispatchEvent(new Event("scroll"));
    });
    return false;
  }, [scheduleCollapsedDocHeadingStateCommit]);

  useLayoutEffect(() => {
    const restoreHeadingPosition = () => {
      const pending = pendingHeadingCollapseScrollRef.current;
      if (!pending) {
        return;
      }

      const container = scrollRef.current;
      const heading = findHeadingById(contentAreaRef.current, pending.id);
      if (!container || !heading || !isVisibleHeading(heading)) {
        return;
      }

      const nextTop = heading.getBoundingClientRect().top;
      const delta = nextTop - pending.top;
      if (Math.abs(delta) < 0.5) {
        return;
      }

      const previousScrollBehavior = container.style.scrollBehavior;
      container.style.scrollBehavior = "auto";
      container.scrollTop += delta;
      if (previousScrollBehavior) {
        container.style.scrollBehavior = previousScrollBehavior;
      } else {
        container.style.removeProperty("scroll-behavior");
      }
    };

    restoreHeadingPosition();
    const rafId = window.requestAnimationFrame(() => {
      restoreHeadingPosition();
      pendingHeadingCollapseScrollRef.current = null;
    });

    return () => window.cancelAnimationFrame(rafId);
  }, [collapsedDocHeadingIds]);

  const expandCollapsedDocHeadingSections = useCallback((heading: HTMLElement, options?: { includeSelf?: boolean }): boolean => {
    const headingId = heading.getAttribute("data-heading-id") ?? "";
    const includeSelf = options?.includeSelf === true;
    const idsToExpand: string[] = [];
    let node = heading.parentElement;
    const collapsedIds = collapsedDocHeadingIdsRef.current;

    while (node) {
      if (node.matches("[data-heading-section-id]")) {
        const sectionId = node.getAttribute("data-heading-section-id") ?? "";
        const isSelfSection = sectionId === headingId;
        if (sectionId && (includeSelf || !isSelfSection) && collapsedIds.has(sectionId)) {
          idsToExpand.push(sectionId);
        }
      }
      node = node.parentElement;
    }

    if (idsToExpand.length === 0) {
      return false;
    }

    const next = new Set(collapsedIds);
    let changed = false;
    for (const id of idsToExpand) {
      if (next.delete(id)) {
        applyDocHeadingCollapseDomState(contentAreaRef.current, id, false);
        changed = true;
      }
    }
    if (!changed) {
      return false;
    }
    collapsedDocHeadingIdsRef.current = next;
    scheduleCollapsedDocHeadingStateCommit(0);
    scrollRef.current?.dispatchEvent(new Event("scroll"));
    return true;
  }, [scheduleCollapsedDocHeadingStateCommit]);

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
    setIsCardsPanelOpen(false);
    setIsGraphDrawerOpen(true);
  }, []);

  const closeGraphPanel = useCallback(() => {
    setIsGraphDrawerOpen(false);
  }, []);

  useEffect(() => {
    document.body.dataset.knowledgeGraphDrawerOpen = isGraphDrawerOpen ? "true" : "false";
    window.dispatchEvent(new CustomEvent(KNOWLEDGE_GRAPH_DRAWER_EVENT, {
      detail: { open: isGraphDrawerOpen },
    }));
    return () => {
      document.body.dataset.knowledgeGraphDrawerOpen = "false";
      window.dispatchEvent(new CustomEvent(KNOWLEDGE_GRAPH_DRAWER_EVENT, {
        detail: { open: false },
      }));
    };
  }, [isGraphDrawerOpen]);

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

  const alignActiveTocItem = useCallback((behavior: ScrollBehavior = "smooth") => {
    if (!visibleActiveHeading || !isTocVisible) return;
    const nav = tocNavRef.current;
    if (!nav) return;

    const escapedId = CSS.escape(visibleActiveHeading);
    const activeNode = nav.querySelector(`[data-toc-id="${escapedId}"]`) as HTMLElement | null;
    if (!activeNode) return;

    const navRect = nav.getBoundingClientRect();
    const activeRect = activeNode.getBoundingClientRect();

    // Check if the active node is already comfortably visible in the viewport
    // (e.g., within the middle 60% of the container's height)
    const threshold = nav.clientHeight * 0.2;
    const isComfortablyVisible =
      (activeRect.top >= navRect.top + threshold) &&
      (activeRect.bottom <= navRect.bottom - threshold);

    if (isComfortablyVisible) return;

    // Calculate center positions safely using getBoundingClientRect
    const activeRelativeCenter = (activeRect.top - navRect.top) + (activeRect.height / 2);
    const targetRelativeCenter = nav.clientHeight / 2;
    let nextScrollTop = nav.scrollTop + (activeRelativeCenter - targetRelativeCenter);

    const maxScrollTop = Math.max(0, nav.scrollHeight - nav.clientHeight);
    nextScrollTop = Math.max(0, Math.min(maxScrollTop, nextScrollTop));

    if (Math.abs(nextScrollTop - nav.scrollTop) < 10) return;

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
    let scanRafId = 0;
    const paintRafId = window.requestAnimationFrame(() => {
      scanRafId = window.requestAnimationFrame(() => {
        const container = scrollRef.current;
        if (!container) return;
        const headingNodes = container.querySelectorAll<HTMLElement>("[data-heading-id]");
        const nextToc = compactTocItems(Array.from(headingNodes)
          .map((node): TocItem | null => {
            const id = node.getAttribute("data-heading-id") ?? node.id;
            if (!id) return null;
            if (!isTocTrackedHeading(node)) return null;
            const level = getHeadingLevel(node);
            const text = node.textContent?.trim() || id;
            const section = findHeadingSectionElement(node);
            const hasInteractive = section ? sectionHasOwnInteractiveEmbed(section) : false;
            return { id, text, level, hasInteractive };
          })
          .filter((item): item is TocItem => item !== null));
        const shouldInitializeCollapsedToc = !tocDefaultInitializedRef.current && nextToc.length > 0;
        if (shouldInitializeCollapsedToc) {
          tocDefaultInitializedRef.current = true;
        }
        startTransition(() => {
          setToc((prev) => (tocEqual(prev, nextToc) ? prev : nextToc));
          if (shouldInitializeCollapsedToc) {
            setCollapsedTocIds(buildDefaultCollapsedTocIds(nextToc));
          }
        });
      });
    });
    return () => {
      window.cancelAnimationFrame(paintRafId);
      if (scanRafId) {
        window.cancelAnimationFrame(scanRafId);
      }
    };
  }, [renderedMarkdown]);

  useEffect(() => {
    if (collapsedDocHeadingCommitTimerRef.current !== null) {
      window.clearTimeout(collapsedDocHeadingCommitTimerRef.current);
      collapsedDocHeadingCommitTimerRef.current = null;
    }
    const next = new Set<string>();
    collapsedDocHeadingIdsRef.current = next;
    startTransition(() => {
      setCollapsedDocHeadingIds((prev) => (prev.size === 0 ? prev : next));
    });
  }, [renderedMarkdown]);

  useEffect(() => {
    setViewPrefs(readKnowledgeDocsViewPrefs(courseId));
  }, [courseId]);

  useEffect(() => {
    persistKnowledgeDocsViewPrefs(courseId, viewPrefs);
  }, [courseId, viewPrefs]);

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
    if (isAssistantOpen && activeDrawer === "comment") {
      setActiveDrawer(null);
    }
  }, [activeDrawer, isAssistantOpen]);

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
      if (readingPositionSaveTimerRef.current !== null) {
        window.clearTimeout(readingPositionSaveTimerRef.current);
      }
      if (scrollspyIgnoreTimerRef.current !== null) {
        window.clearTimeout(scrollspyIgnoreTimerRef.current);
      }
      if (scrollRestorationTimerRef.current !== null) {
        window.clearTimeout(scrollRestorationTimerRef.current);
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
      if (!courseId) {
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
            url: `/api/v1/courses/${courseId}/chats/threads/list`,
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
        setSelectionHighlights((prev) => {
          const next = prev.filter((item) => isTransientSelectionThreadId(item.threadId));
          return next.length === prev.length ? prev : next;
        });
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
  }, [courseId, threadHistoryRefreshKey]);

  useEffect(() => {
    commentsRef.current = comments;
  }, [comments]);

  useEffect(() => {
    activeHeadingRef.current = activeHeading;
  }, [activeHeading]);

  useEffect(() => {
    readingPositionRestoredRef.current = "";
  }, [courseId, renderedMarkdown]);

  useEffect(() => {
    if (!courseId || !renderedMarkdown.trim()) {
      return;
    }
    const restoreKey = `${courseId}:${renderedMarkdown.length}`;
    if (readingPositionRestoredRef.current === restoreKey || pendingSelectionJumpRef.current) {
      return;
    }
    readingPositionRestoredRef.current = restoreKey;
    const saved = readKnowledgeDocsReadingPosition(courseId);
    if (!saved) {
      return;
    }

    const restorePosition = () => {
      const container = scrollRef.current;
      if (!container) return false;

      const targetHeading = saved.headingId
        ? contentAreaRef.current?.querySelector<HTMLElement>(`[data-heading-id="${CSS.escape(saved.headingId)}"]`) ?? null
        : null;

      let nextScrollTop = saved.scrollTop;
      if (saved.headingId && !targetHeading) {
        // Heading is specified but not yet in the DOM, we should wait and retry
        // (the Markdown rendering is in progress)
        return false;
      }

      if (targetHeading) {
        const containerRect = container.getBoundingClientRect();
        const headingRect = targetHeading.getBoundingClientRect();
        nextScrollTop = container.scrollTop + (headingRect.top - containerRect.top) - 28;
      }

      const maxScrollTop = Math.max(0, container.scrollHeight - container.clientHeight);

      // If the container's scrollHeight is still loading and cannot support the scroll top yet,
      // and we are not at the very top, we should wait and retry
      if (nextScrollTop > 0 && maxScrollTop < nextScrollTop && container.scrollHeight < 500) {
        return false;
      }

      const previousScrollBehavior = container.style.scrollBehavior;
      container.style.scrollBehavior = "auto";
      container.scrollTop = Math.max(0, Math.min(maxScrollTop, nextScrollTop));
      if (previousScrollBehavior) {
        container.style.scrollBehavior = previousScrollBehavior;
      } else {
        container.style.removeProperty("scroll-behavior");
      }
      container.dispatchEvent(new Event("scroll"));
      return true;
    };

    let attempts = 0;
    const maxAttempts = 15;
    const tryRestore = () => {
      if (restorePosition()) {
        return;
      }
      attempts++;
      if (attempts < maxAttempts) {
        scrollRestorationTimerRef.current = window.setTimeout(tryRestore, 50);
      }
    };
    tryRestore();

    return () => {
      if (scrollRestorationTimerRef.current !== null) {
        window.clearTimeout(scrollRestorationTimerRef.current);
        scrollRestorationTimerRef.current = null;
      }
    };
  }, [courseId, renderedMarkdown]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!courseId || !renderedMarkdown.trim() || !container) {
      return;
    }

    const saveNow = () => {
      persistKnowledgeDocsReadingPosition(courseId, {
        scrollTop: container.scrollTop,
        headingId: activeHeadingRef.current,
        contentLength: renderedMarkdown.length,
        updatedAt: Date.now(),
      });
    };

    const scheduleSave = () => {
      if (readingPositionSaveTimerRef.current !== null) {
        window.clearTimeout(readingPositionSaveTimerRef.current);
      }
      readingPositionSaveTimerRef.current = window.setTimeout(() => {
        readingPositionSaveTimerRef.current = null;
        saveNow();
      }, 240);
    };

    container.addEventListener("scroll", scheduleSave, { passive: true });
    window.addEventListener("beforeunload", saveNow);

    return () => {
      container.removeEventListener("scroll", scheduleSave);
      window.removeEventListener("beforeunload", saveNow);
      if (readingPositionSaveTimerRef.current !== null) {
        window.clearTimeout(readingPositionSaveTimerRef.current);
        readingPositionSaveTimerRef.current = null;
      }
      saveNow();
    };
  }, [courseId, renderedMarkdown]);

  // Track active heading from a single scroll position so the TOC highlight does not bounce.
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    const scrollParent = container;

    const headingRoot = contentAreaRef.current;
    const headings = Array.from((headingRoot ?? container).querySelectorAll<HTMLElement>("[data-heading-id]"))
      .filter(isTocTrackedHeading);
    if (headings.length === 0) {
      setActiveHeading("");
      return;
    }

    let rafId = 0;
    let positionRafId = 0;
    let headingPositions: Array<{ id: string; top: number }> = [];

    const refreshHeadingPositions = () => {
      headingPositions = headings
        .map((heading) => {
          const id = heading.getAttribute("data-heading-id") ?? "";
          if (!id || !isVisibleHeading(heading)) {
            return null;
          }
          return {
            id,
            top: getElementContentTop(scrollParent, heading),
          };
        })
        .filter((item): item is { id: string; top: number } => item !== null)
        .sort((left, right) => left.top - right.top);
    };

    const schedulePositionRefresh = () => {
      window.cancelAnimationFrame(positionRafId);
      positionRafId = window.requestAnimationFrame(() => {
        positionRafId = 0;
        refreshHeadingPositions();
        syncActiveHeading();
      });
    };

    const findActiveHeadingId = () => {
      const isScrollable = scrollParent.scrollHeight > scrollParent.clientHeight;
      const isAtBottom = isScrollable && (scrollParent.scrollTop + scrollParent.clientHeight >= scrollParent.scrollHeight - 15);
      if (isAtBottom) {
        const lastHeading = headingPositions[headingPositions.length - 1];
        if (lastHeading) {
          return lastHeading.id;
        }
      }

      if (headingPositions.length === 0) {
        return "";
      }

      const activationTop = scrollParent.scrollTop + getHeadingActivationOffset(scrollParent);
      let left = 0;
      let right = headingPositions.length - 1;
      let activeIndex = 0;
      while (left <= right) {
        const mid = Math.floor((left + right) / 2);
        if (headingPositions[mid].top <= activationTop) {
          activeIndex = mid;
          left = mid + 1;
        } else {
          right = mid - 1;
        }
      }
      return headingPositions[activeIndex]?.id ?? "";
    };

    const syncActiveHeading = () => {
      if (scrollingToHeadingTargetRef.current !== null) {
        const targetId = scrollingToHeadingTargetRef.current;
        setActiveHeading((prev) => (prev === targetId ? prev : targetId));
        return;
      }
      window.cancelAnimationFrame(rafId);
      rafId = window.requestAnimationFrame(() => {
        const nextId = findActiveHeadingId();
        setActiveHeading((prev) => (prev === nextId ? prev : nextId));
      });
    };

    const handleScroll = () => {
      syncActiveHeading();
    };

    const handleScrollEnd = () => {
      scrollingToHeadingTargetRef.current = null;
      if (scrollspyIgnoreTimerRef.current !== null) {
        window.clearTimeout(scrollspyIgnoreTimerRef.current);
        scrollspyIgnoreTimerRef.current = null;
      }
      syncActiveHeading();
    };

    refreshHeadingPositions();
    scrollParent.addEventListener("scroll", handleScroll, { passive: true });
    scrollParent.addEventListener("scrollend", handleScrollEnd, { passive: true });
    window.addEventListener("resize", schedulePositionRefresh);
    const resizeObserverTarget = headingRoot;
    const resizeObserver = typeof ResizeObserver !== "undefined" && resizeObserverTarget
      ? new ResizeObserver(schedulePositionRefresh)
      : null;
    if (resizeObserver && resizeObserverTarget) {
      resizeObserver.observe(resizeObserverTarget);
    }
    syncActiveHeading();

    return () => {
      window.cancelAnimationFrame(rafId);
      window.cancelAnimationFrame(positionRafId);
      scrollParent.removeEventListener("scroll", handleScroll);
      scrollParent.removeEventListener("scrollend", handleScrollEnd);
      window.removeEventListener("resize", schedulePositionRefresh);
      resizeObserver?.disconnect();
    };
  }, [renderedMarkdown]);

  // Keep the active TOC item aligned when layout changes or window resizes
  useEffect(() => {
    if (!isTocVisible) return;
    const handleResize = () => {
      alignActiveTocItem();
    };
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
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

  const scrollToHeading = useCallback((id: string, options: { retryingAfterExpand?: boolean } = {}) => {
    const scroll = (headingId: string, opts: { retryingAfterExpand?: boolean }) => {
      const container = scrollRef.current;
      if (!container) return;
      const headingRoot = contentAreaRef.current;
      const el = findHeadingById(headingRoot ?? container, headingId);
      if (!el) return;

      if (!opts.retryingAfterExpand && expandCollapsedDocHeadingSections(el)) {
        window.requestAnimationFrame(() => {
          scroll(headingId, { ...opts, retryingAfterExpand: true });
        });
        return;
      }

      setActiveHeading((prev) => (prev === headingId ? prev : headingId));

      const containerRect = container.getBoundingClientRect();
      const elRect = el.getBoundingClientRect();
      const headingTop = container.scrollTop + (elRect.top - containerRect.top);
      const maxScrollTop = Math.max(0, container.scrollHeight - container.clientHeight);
      const targetTop = Math.max(0, Math.min(maxScrollTop, headingTop - getHeadingActivationOffset(container)));

      scrollingToHeadingTargetRef.current = headingId;
      if (scrollspyIgnoreTimerRef.current !== null) {
        window.clearTimeout(scrollspyIgnoreTimerRef.current);
      }
      scrollspyIgnoreTimerRef.current = window.setTimeout(() => {
        scrollingToHeadingTargetRef.current = null;
        scrollspyIgnoreTimerRef.current = null;
      }, 1000);

      container.scrollTo({ top: targetTop, behavior: "smooth" });
      flashHeading(el);
    };

    scroll(id, options);
  }, [expandCollapsedDocHeadingSections, flashHeading]);

  const scrollElementIntoDocView = useCallback((element: HTMLElement, behavior: ScrollBehavior = "smooth") => {
    const container = scrollRef.current;
    if (!container) return;
    const containerRect = container.getBoundingClientRect();
    const elementRect = element.getBoundingClientRect();
    const elementTop = container.scrollTop + (elementRect.top - containerRect.top);
    const maxScrollTop = Math.max(0, container.scrollHeight - container.clientHeight);
    const targetTop = Math.max(0, Math.min(maxScrollTop, elementTop - 88));
    container.scrollTo({ top: targetTop, behavior });
  }, []);

  const scrollToPendingInteractiveBlock = useCallback((pendingId: string, anchorId: string) => {
    const root = contentAreaRef.current;
    const pending = root?.querySelector<HTMLElement>(
      `[data-pending-interactive-id="${escapeCssAttributeValue(pendingId)}"]`,
    );
    if (pending) {
      scrollElementIntoDocView(pending);
      return;
    }
    scrollToHeading(anchorId);
  }, [scrollElementIntoDocView, scrollToHeading]);

  const scrollToInteractiveAsset = useCallback((assetPath: string, anchorId: string) => {
    const root = contentAreaRef.current;
    const embed = root?.querySelector<HTMLElement>(
      `[data-doc-interactive-asset="${escapeCssAttributeValue(assetPath)}"]`,
    );
    if (embed) {
      if (embed instanceof HTMLDetailsElement && !embed.open) {
        embed.open = true;
      }
      scrollElementIntoDocView(embed);
      return;
    }
    scrollToHeading(anchorId);
  }, [scrollElementIntoDocView, scrollToHeading]);


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

  const buildSelectionSegmentsFromText = useCallback((
    anchorId: string,
    selectedText: string,
    preferredSegments?: HighlightSegment[],
  ): HighlightSegment[] => {
    const contentRoot = contentAreaRef.current;
    if (!contentRoot) {
      return [];
    }
    const target = selectedText.trim();
    if (!target) {
      return [];
    }

    const segmentFromRect = (rect: DOMRect): HighlightSegment => {
      const container = scrollRef.current;
      if (!container) {
        return {
          top: rect.top,
          left: rect.left,
          width: Math.max(4, rect.width),
          height: Math.max(12, rect.height),
        };
      }
      const containerRect = container.getBoundingClientRect();
      return {
        top: rect.top - containerRect.top + container.scrollTop,
        left: rect.left - containerRect.left + container.scrollLeft,
        width: Math.max(4, rect.width),
        height: Math.max(12, rect.height),
      };
    };

    const captureElementSegments = (element: Element): HighlightSegment[] => (
      Array.from(element.getClientRects())
        .filter((rect) => rect.width > 1 && rect.height > 1)
        .map(segmentFromRect)
    );

    const chooseNearestSegments = (candidates: HighlightSegment[][]): HighlightSegment[] => {
      const validCandidates = candidates.filter((segments) => segments.length > 0);
      if (validCandidates.length === 0) {
        return [];
      }
      if (!preferredSegments || preferredSegments.length === 0) {
        return validCandidates[0];
      }

      const preferredTop = Math.min(...preferredSegments.map((segment) => segment.top));
      const preferredLeft = Math.min(...preferredSegments.map((segment) => segment.left));
      let best = validCandidates[0];
      let bestScore = Number.POSITIVE_INFINITY;
      for (const segments of validCandidates) {
        const top = Math.min(...segments.map((segment) => segment.top));
        const left = Math.min(...segments.map((segment) => segment.left));
        const score = Math.abs(top - preferredTop) * 3 + Math.abs(left - preferredLeft);
        if (score < bestScore) {
          best = segments;
          bestScore = score;
        }
      }
      return best;
    };

    const locateApproximateTableSelection = (roots: Node[]): HighlightSegment[] => {
      const rows: HTMLTableRowElement[] = [];
      const seen = new Set<HTMLTableRowElement>();
      const addRow = (row: HTMLTableRowElement) => {
        if (seen.has(row)) return;
        seen.add(row);
        rows.push(row);
      };

      for (const rootNode of roots) {
        if (rootNode instanceof HTMLTableRowElement) {
          addRow(rootNode);
          continue;
        }
        if (rootNode instanceof Element) {
          if (rootNode.matches("tr")) {
            addRow(rootNode as HTMLTableRowElement);
          }
          rootNode.querySelectorAll<HTMLTableRowElement>("tr").forEach(addRow);
        }
      }

      let bestMatch: { row: HTMLTableRowElement; range: Range; score: number } | null = null;
      const targetTokens = buildSelectionMatchTokens(target);
      if (targetTokens.length === 0) {
        return [];
      }

      for (const row of rows) {
        const index = buildTextSearchIndex([row]);
        if (!index.text.trim()) continue;
        const range = findApproximateRangeForSelectedText(index, target);
        if (!range) continue;
        const condensedRow = createCondensedSearchText(index.text).text;
        const score = targetTokens.reduce((sum, token) => (
          condensedRow.includes(token) ? sum + Math.min(token.length, 12) : sum
        ), 0);
        if (!bestMatch || score > bestMatch.score) {
          bestMatch = { row, range, score };
        }
      }

      if (!bestMatch) {
        return [];
      }

      const rangeSegments = captureRangeSegments(bestMatch.range);
      return rangeSegments.length > 0 ? rangeSegments : captureElementSegments(bestMatch.row);
    };

    const locateInRoots = (roots: Node[]): HighlightSegment[] => {
      const index = buildTextSearchIndex(roots);
      const matchedSegments = findRangesForSelectedText(index, target)
        .map((range) => captureRangeSegments(range))
        .filter((segments) => segments.length > 0);
      if (matchedSegments.length > 0) {
        return chooseNearestSegments(matchedSegments);
      }
      const approximateRange = findApproximateRangeForSelectedText(index, target);
      if (approximateRange) {
        const approximateSegments = captureRangeSegments(approximateRange);
        if (approximateSegments.length > 0) {
          return approximateSegments;
        }
      }
      return locateApproximateTableSelection(roots);
    };

    const heading = findHeadingById(contentRoot, anchorId);
    if (heading) {
      const selectionHeading = findSelectionHeadingInDocument(contentRoot, anchorId, target);
      const sectionSegments = locateInRoots(collectSectionNodes(selectionHeading ?? heading));
      if (sectionSegments.length > 0) {
        return sectionSegments;
      }
      if (selectionHeading && selectionHeading !== heading) {
        const anchorSegments = locateInRoots(collectSectionNodes(heading));
        if (anchorSegments.length > 0) {
          return anchorSegments;
        }
      }
    }

    return locateInRoots([contentRoot]);
  }, [captureRangeSegments]);

  const resolveHighlightSegments = useCallback((highlight: SelectionHighlight): HighlightSegment[] => {
    if (selectedRangeThreadIdRef.current === highlight.threadId && selectedRangeRef.current) {
      const liveSegments = captureSelectionSegments();
      if (liveSegments.length > 0) {
        return liveSegments;
      }
    }
    return buildSelectionSegmentsFromText(
      highlight.anchorId,
      highlight.selectedText,
      highlight.segments,
    );
  }, [buildSelectionSegmentsFromText, captureSelectionSegments]);

  const refreshSelectionHighlightSegments = useCallback(() => {
    setSelectionHighlights((prev) => {
      let changed = false;
      const next = prev.map((highlight) => {
        const segments = resolveHighlightSegments(highlight);
        if (highlightSegmentsEqual(highlight.segments, segments)) {
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
  }, [resolveHighlightSegments]);

  const createLocalThreadId = useCallback((anchorId: string) => (
    `local-${anchorId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  ), []);

  const createStandaloneHighlightId = useCallback((anchorId: string) => (
    `mark-${anchorId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
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
    setActiveHeading((prev) => (prev === id ? prev : id));
    scrollToHeading(id);
    if (isCompactToc) {
      setActiveDrawer(null);
    }
  }, [isCompactToc, scrollToHeading]);

  const dismissCommentComposer = useCallback(() => {
    setFloatingComment(null);
    setFloatingInput("");
  }, []);

  const clearSelectionHighlight = useCallback((options?: { keepStoredRange?: boolean }) => {
    if (!options?.keepStoredRange) {
      selectedRangeRef.current = null;
      selectedRangeThreadIdRef.current = null;
    }
    const selection = window.getSelection();
    if (selection && !selection.isCollapsed) {
      selection.removeAllRanges();
    }
  }, []);

  const highlightSelectedText = useCallback(() => {
    if (!floatingToolbar) return;
    const toolbar = floatingToolbar;
    const threadId = createStandaloneHighlightId(toolbar.anchorId);
    const segments = captureSelectionSegments();
    addSelectionHighlight(threadId, toolbar.anchorId, toolbar.selectedText, segments.length > 0 ? segments : undefined);
    setActiveCommentThreadId(threadId);
    setPinnedThreadId(threadId);
    setIsAutoCommentHighlightSuppressed(false);
    setFloatingToolbar(null);
    setFloatingComment(null);
    setFloatingInput("");
    clearSelectionHighlight();
  }, [
    addSelectionHighlight,
    captureSelectionSegments,
    clearSelectionHighlight,
    createStandaloneHighlightId,
    floatingToolbar,
  ]);

  useEffect(() => {
    const handleAiInteractionClosed = () => {
      const currentThreadId = selectedRangeThreadIdRef.current?.trim() ?? "";

      const shouldRemoveUnstartedThread = (threadId: string | null | undefined) => {
        const normalizedThreadId = threadId?.trim() ?? "";
        if (!normalizedThreadId) {
          return false;
        }
        const shouldConsider =
          normalizedThreadId.startsWith("local-") ||
          (currentThreadId !== "" && normalizedThreadId === currentThreadId);
        if (!shouldConsider || !isTransientSelectionThreadId(normalizedThreadId)) {
          return false;
        }
        const hasStartedConversation =
          quickChatStartedThreadIdsRef.current.has(normalizedThreadId) ||
          commentsRef.current.some((item) => (
            item.threadId === normalizedThreadId || item.sessionId === normalizedThreadId
          ));
        return !hasStartedConversation;
      };

      setSelectionHighlights((prev) => {
        const next = prev.filter((item) => !shouldRemoveUnstartedThread(item.threadId));
        return next.length === prev.length ? prev : next;
      });
      setActiveCommentThreadId((prev) => (shouldRemoveUnstartedThread(prev) ? null : prev));
      setPinnedThreadId((prev) => (shouldRemoveUnstartedThread(prev) ? null : prev));
      setThreadStreaming((prev) => {
        let changed = false;
        const next = { ...prev };
        for (const threadId of Object.keys(next)) {
          if (shouldRemoveUnstartedThread(threadId)) {
            delete next[threadId];
            changed = true;
          }
        }
        return changed ? next : prev;
      });
      setThreadDrafts((prev) => {
        let changed = false;
        const next = { ...prev };
        for (const threadId of Object.keys(next)) {
          if (shouldRemoveUnstartedThread(threadId)) {
            delete next[threadId];
            changed = true;
          }
        }
        return changed ? next : prev;
      });

      clearSelectionHighlight();
    };

    window.addEventListener(AI_INTERACTION_CLOSED_EVENT, handleAiInteractionClosed);
    return () => window.removeEventListener(AI_INTERACTION_CLOSED_EVENT, handleAiInteractionClosed);
  }, [clearSelectionHighlight]);

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

  // Keep document selection behavior close to Feishu:
  // any click outside toolbar clears highlighted range state.
  useEffect(() => {
    const handlePointerDown = (e: MouseEvent) => {
      const targetElement = e.target instanceof Element ? e.target : null;
      if (targetElement?.closest("[data-app-sidebar='true']")) return;
      if (targetElement?.closest("[data-ai-interaction-window='true']")) return;
      if (floatingRef.current?.contains(e.target as Node)) return;
      if (floatingComposerCardRef.current?.contains(e.target as Node)) return;
      if (commentPanelRef.current?.contains(e.target as Node)) return;
      clearSelectionHighlight();
      setFloatingToolbar(null);
      setFloatingComment(null);
      setFloatingInteractive(null);
      setInteractivePrompt("");
      setInteractiveError(null);
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
    if (selectedRangeThreadIdRef.current === threadId) {
      selectedRangeThreadIdRef.current = resolvedSessionId;
    }
    if (quickChatStartedThreadIdsRef.current.has(threadId)) {
      quickChatStartedThreadIdsRef.current.delete(threadId);
      quickChatStartedThreadIdsRef.current.add(resolvedSessionId);
    }

    const controller = streamControllersRef.current.get(threadId);
    if (controller) {
      streamControllersRef.current.delete(threadId);
      streamControllersRef.current.set(resolvedSessionId, controller);
    }

    return resolvedSessionId;
  }, []);

  useEffect(() => {
    const handleQuickChatUpdated = (event: Event) => {
      const detail = (event as CustomEvent<QuickChatSyncEventDetail>).detail;
      if (detail?.courseId && !routeIdsEqual(detail.courseId, courseId)) {
        return;
      }
      if (!detail?.phase) {
        setThreadHistoryRefreshKey((prev) => prev + 1);
        return;
      }

      const localThreadId = detail.localThreadId?.trim() || detail.sessionId?.trim() || "";
      const sessionId = detail.sessionId?.trim() || null;
      const assistantLocalId = detail.assistantLocalId?.trim() || "";
      if (!localThreadId) {
        return;
      }

      if (detail.phase === "start") {
        const anchorId = detail.anchorId?.trim() ?? "";
        const selectedText = detail.selectedText?.trim() ?? "";
        const question = detail.question?.trim() ?? "";
        if (!anchorId || !selectedText || !question || !assistantLocalId) {
          return;
        }

        quickChatStartedThreadIdsRef.current.add(localThreadId);
        const createdAt = detail.createdAt ? Date.parse(detail.createdAt) : Date.now();
        const startedAt = Number.isFinite(createdAt) ? createdAt : Date.now();
        const userLocalId = detail.userLocalId?.trim() || `${localThreadId}-user-${startedAt}`;
        setComments((prev) => {
          if (prev.some((item) => item.id === userLocalId || item.id === assistantLocalId)) {
            return prev;
          }
          return [
            ...prev,
            {
              id: userLocalId,
              threadId: localThreadId,
              sessionId,
              anchorId,
              selectedText,
              role: "user",
              content: question,
              createdAt: startedAt,
            },
            {
              id: assistantLocalId,
              threadId: localThreadId,
              sessionId,
              anchorId,
              selectedText,
              role: "assistant",
              content: "",
              createdAt: startedAt + 1,
              streaming: true,
            },
          ];
        });
        if (sessionId) {
          setThreadSessionIds((prev) => ({ ...prev, [localThreadId]: sessionId }));
        }
        setThreadStreaming((prev) => ({ ...prev, [localThreadId]: true }));
        const segments = buildSelectionSegmentsFromText(anchorId, selectedText);
        addSelectionHighlight(localThreadId, anchorId, selectedText, segments.length > 0 ? segments : undefined);
        setActiveCommentThreadId(localThreadId);
        setPinnedThreadId(localThreadId);
        setIsAutoCommentHighlightSuppressed(false);
        return;
      }

      if (detail.phase === "session") {
        if (sessionId) {
          rebindThreadIdToSession(localThreadId, sessionId);
        }
        return;
      }

      if (detail.phase === "token") {
        const content = detail.content ?? "";
        if (!assistantLocalId || !content) {
          return;
        }
        setComments((prev) => prev.map((item) => (
          item.id === assistantLocalId ? { ...item, content: item.content + content } : item
        )));
        return;
      }

      if (detail.phase === "done") {
        const finalThreadId = sessionId ? rebindThreadIdToSession(localThreadId, sessionId) : localThreadId;
        if (assistantLocalId) {
          setComments((prev) => prev.map((item) => (
            item.id === assistantLocalId
              ? { ...item, threadId: finalThreadId, sessionId, streaming: false }
              : item
          )));
        }
        setThreadStreaming((prev) => ({ ...prev, [finalThreadId]: false }));
        return;
      }

      if (detail.phase === "error") {
        const finalThreadId = sessionId ? rebindThreadIdToSession(localThreadId, sessionId) : localThreadId;
        if (assistantLocalId) {
          setComments((prev) => prev.map((item) => (
            item.id === assistantLocalId
              ? {
                ...item,
                threadId: finalThreadId,
                sessionId,
                content: detail.errorDetail?.trim() || item.content || "请求失败，请重试。",
                streaming: false,
              }
              : item
          )));
        }
        setThreadStreaming((prev) => ({ ...prev, [finalThreadId]: false }));
        return;
      }

      if (detail.phase === "settled") {
        const finalThreadId = sessionId ? rebindThreadIdToSession(localThreadId, sessionId) : localThreadId;
        setThreadStreaming((prev) => ({ ...prev, [finalThreadId]: false }));
      }
    };

    window.addEventListener(QUICK_CHAT_UPDATED_EVENT, handleQuickChatUpdated);
    return () => window.removeEventListener(QUICK_CHAT_UPDATED_EVENT, handleQuickChatUpdated);
  }, [addSelectionHighlight, buildSelectionSegmentsFromText, rebindThreadIdToSession, courseId]);

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
      const course = courseId ?? "demo";
      const selectionContext = buildSelectionContextPayload(contentAreaRef.current, anchorId, selectedText);
      const result = await postSseJson(
        `/api/v1/courses/${course}/chats/send`,
        {
          question: text,
          scene: AI_SCENE_DOCUMENT_SELECTION,
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
  }, [rebindThreadIdToSession, courseId, threadSessionIds]);

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

  const openCommentComposer = useCallback(() => {
    if (!floatingToolbar || !courseId) return;
    const toolbar = floatingToolbar;
    const threadId = createLocalThreadId(toolbar.anchorId);
    const segments = captureSelectionSegments();
    selectedRangeThreadIdRef.current = threadId;
    addSelectionHighlight(threadId, toolbar.anchorId, toolbar.selectedText, segments.length > 0 ? segments : undefined);
    setActiveCommentThreadId(threadId);
    setPinnedThreadId(threadId);
    setIsAutoCommentHighlightSuppressed(false);
    const selectionContext = buildSelectionContextPayload(contentAreaRef.current, toolbar.anchorId, toolbar.selectedText);
    openAiInteraction({
      scope: { type: "course", courseId },
      sessionId: null,
      draft: "",
      scene: AI_SCENE_DOCUMENT_SELECTION,
      source: "quick_chat",
      anchorId: toolbar.anchorId,
      selectedText: toolbar.selectedText,
      selectionContext,
      clientThreadId: threadId,
      newSession: true,
      showSelectionContext: true,
    });
    setFloatingToolbar(null);
    setFloatingComment(null);
    setFloatingInput("");
    clearSelectionHighlight({ keepStoredRange: true });
  }, [addSelectionHighlight, captureSelectionSegments, clearSelectionHighlight, createLocalThreadId, floatingToolbar, openAiInteraction, courseId]);

  const openInteractiveComposer = useCallback(() => {
    if (!floatingToolbar || !courseId) return;
    const toolbar = floatingToolbar;
    const selectionContext = buildSelectionContextPayload(contentAreaRef.current, toolbar.anchorId, toolbar.selectedText);
    const container = scrollRef.current;
    const composerWidth = 360;
    const composerLeft = container
      ? Math.max(
        container.scrollLeft + 12,
        Math.min(
          toolbar.left,
          container.scrollLeft + container.clientWidth - composerWidth - 12,
        ),
      )
      : toolbar.left;
    setFloatingInteractive({
      anchorId: toolbar.anchorId,
      selectedText: toolbar.selectedText,
      top: toolbar.top + 48,
      left: composerLeft,
      selectionContext,
    });
    setInteractivePrompt("");
    setInteractiveError(null);
    setFloatingToolbar(null);
    setFloatingComment(null);
    clearSelectionHighlight({ keepStoredRange: true });
  }, [clearSelectionHighlight, courseId, floatingToolbar]);

  const cancelInteractiveComposer = useCallback(() => {
    setFloatingInteractive(null);
    setInteractivePrompt("");
    setInteractiveError(null);
    clearSelectionHighlight();
  }, [clearSelectionHighlight]);

  const submitInteractiveComposer = useCallback(async () => {
    if (!courseId || !floatingInteractive || isGeneratingInteractive) return;
    const composer = floatingInteractive;
    const prompt = interactivePrompt.trim();
    const pendingId = `pending-interactive-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    const pendingBlock: PendingInteractiveBlock = {
      id: pendingId,
      anchorId: composer.anchorId,
      title: prompt || "正在生成交互演示",
      selectedText: composer.selectedText,
    };
    setIsGeneratingInteractive(true);
    setInteractiveError(null);
    setPendingInteractiveBlocks((prev) => [...prev, pendingBlock]);
    setFloatingInteractive(null);
    setInteractivePrompt("");
    setFloatingToolbar(null);
    clearSelectionHighlight();
    if (!isCompactToc && viewPrefs.showToc) {
      setIsTocCollapsed(false);
    }
    window.requestAnimationFrame(() => {
      scrollToPendingInteractiveBlock(pendingId, composer.anchorId);
      window.setTimeout(() => scrollToPendingInteractiveBlock(pendingId, composer.anchorId), 80);
    });
    try {
      const response = await apiClient<ApiResponse<KnowledgeDocInteractiveSelectionResponse>>({
        url: `/api/v1/courses/${courseId}/knowledge/docs/interactive-selections`,
        method: "POST",
        timeout: LONG_RUNNING_API_TIMEOUT_MS,
        data: {
          anchor_id: composer.anchorId,
          selected_text: composer.selectedText,
          prompt: prompt || undefined,
          selection_context: composer.selectionContext,
        },
      });
      toast({
        title: "交互演示已生成",
        description: "新的交互块已添加到当前章节下方。",
        variant: "success",
      });
      await docMarkdownQuery.refetch();
      setPendingInteractiveBlocks((prev) => prev.filter((item) => item.id !== pendingId));
      const created = response.data;
      window.requestAnimationFrame(() => {
        scrollToInteractiveAsset(created.asset_path, created.anchor_id);
        window.setTimeout(() => scrollToInteractiveAsset(created.asset_path, created.anchor_id), 120);
      });
    } catch (error) {
      const message = getApiErrorMessage(error, "生成交互演示失败，请稍后重试。");
      setInteractiveError(message);
      setPendingInteractiveBlocks((prev) => prev.filter((item) => item.id !== pendingId));
      setFloatingInteractive(composer);
      setInteractivePrompt(prompt);
      toast({
        title: "生成交互演示失败",
        description: message,
        variant: "error",
      });
    } finally {
      setIsGeneratingInteractive(false);
    }
  }, [
    clearSelectionHighlight,
    courseId,
    docMarkdownQuery,
    floatingInteractive,
    interactivePrompt,
    isCompactToc,
    isGeneratingInteractive,
    scrollToInteractiveAsset,
    scrollToPendingInteractiveBlock,
    toast,
    viewPrefs.showToc,
  ]);

  // Feishu-style: detect text selection and show a small ask-AI action first.
  const handleTextSelect = useCallback(() => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.toString().trim()) {
      setFloatingToolbar(null);
      if (!isGeneratingInteractive) {
        setFloatingInteractive(null);
      }
      selectedRangeRef.current = null;
      selectedRangeThreadIdRef.current = null;
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
    const visibleClientRects = Array.from(range.getClientRects()).filter(
      (item) => item.width > 1 && item.height > 1
    );
    const anchorRect = visibleClientRects[0] ?? rect;
    const containerRect = container.getBoundingClientRect();
    const contentAreaRect = contentArea?.getBoundingClientRect();

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
    selectedRangeThreadIdRef.current = null;
    const segments = captureRangeSegments(range);
    if (segments.length === 0) {
      return;
    }

    const contentTop = rect.top - containerRect.top + container.scrollTop;
    const selectionViewportTop = rect.top + rect.height / 2;
    const toolbarWidth = 334;
    const contentLeft = (contentAreaRect?.left ?? containerRect.left) - containerRect.left + container.scrollLeft;
    const contentRight = (contentAreaRect?.right ?? containerRect.right) - containerRect.left + container.scrollLeft;
    const minToolbarLeft = Math.max(container.scrollLeft + 12, contentLeft + 8);
    const maxToolbarLeft = Math.min(
      container.scrollLeft + container.clientWidth - toolbarWidth - 12,
      contentRight - toolbarWidth - 8
    );
    const preferredToolbarLeft = anchorRect.right - containerRect.left + container.scrollLeft + 8;
    const fallbackToolbarLeft = anchorRect.right - containerRect.left + container.scrollLeft - toolbarWidth;
    const toolbarLeft = Math.max(
      minToolbarLeft,
      Math.min(maxToolbarLeft, preferredToolbarLeft <= maxToolbarLeft ? preferredToolbarLeft : fallbackToolbarLeft)
    );
    const toolbarTop = Math.max(
      container.scrollTop + 10,
      anchorRect.top - containerRect.top + container.scrollTop - 46
    );

    setFloatingComment(null);
    if (!isGeneratingInteractive) {
      setFloatingInteractive(null);
      setInteractiveError(null);
    }
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
    isGeneratingInteractive,
  ]);

  useEffect(() => {
    const shouldIgnoreSelectionEventTarget = (target: EventTarget | null) => {
      const targetNode = target instanceof Node ? target : null;
      const targetElement = targetNode instanceof Element ? targetNode : targetNode?.parentElement ?? null;
      if (targetElement?.closest("[data-app-sidebar='true']")) return true;
      if (targetElement?.closest("[data-ai-interaction-window='true']")) return true;
      if (targetElement?.closest("input, textarea, select, [contenteditable]")) return true;
      if (targetNode && commentPanelRef.current?.contains(targetNode)) return true;
      if (targetNode && floatingRef.current?.contains(targetNode)) return true;
      if (targetNode && floatingComposerCardRef.current?.contains(targetNode)) return true;
      return false;
    };

    const handleDocumentMouseUp = (event: MouseEvent) => {
      const target = event.target as Node;
      if (shouldIgnoreSelectionEventTarget(target)) return;
      window.requestAnimationFrame(() => {
        handleTextSelect();
      });
    };
    const handleDocumentKeyUp = (event: KeyboardEvent) => {
      if (shouldIgnoreSelectionEventTarget(event.target)) return;
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
            segments = nextSegments;
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
  }, [captureRangeSegments, collapsedDocHeadingIds, computeCommentComposerTop, floatingComment?.anchorId, isCommentVisible, showDesktopCommentPanel]);

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
        const sourceOrder = resolveSelectionSourceOrder(contentAreaRef.current, anchorId, selectedText, tocOrderMap);
        return {
          threadId,
          anchorId,
          selectedText,
          comments: threadComments,
          createdAt,
          sourceOrder,
        };
      })
      .filter((item) => item.anchorId)
      .sort(compareCommentThreadViewOrder)
  ), [commentsByThread, hasRenderedMarkdown, renderedMarkdown, tocOrderMap]);
  useEffect(() => {
    setKnowledgeCards([]);
    setCardsGenerated(false);
  }, [renderedMarkdown]);

  const generateKnowledgeCards = useCallback(() => {
    const cards = buildKnowledgeCardsFromMarkdown(renderedMarkdown, toc);
    setKnowledgeCards(cards);
    setCardsGenerated(true);
    toast({
      title: cards.length > 0 ? "知识卡片已生成" : "暂未生成卡片",
      description: cards.length > 0 ? `已整理 ${cards.length} 张正反面卡片。` : "当前文档内容还不足以整理成稳定卡片。",
      variant: cards.length > 0 ? "success" : "info",
    });
  }, [renderedMarkdown, toast, toc]);
  const commentThreadIds = useMemo(
    () => commentThreads.map((item) => item.threadId),
    [commentThreads]
  );
  const commentThreadById = useMemo(
    () => new Map(commentThreads.map((item) => [item.threadId, item] as const)),
    [commentThreads]
  );

  const exportAnnotations = useCallback(() => {
    if (commentThreads.length === 0) {
      toast({
        title: "暂无可导出的选区问答",
        description: "先在正文中划选内容并与 AI 对话，系统会把这些片段整理为记录。",
        variant: "info",
      });
      return;
    }
    const filename = `aiteachme-selection-notes-${courseId ?? "course"}.md`;
    downloadTextFile(filename, buildAnnotationExportMarkdown(commentThreads, courseId), "text/markdown;charset=utf-8");
    toast({
      title: "选区问答已导出",
      description: "已生成 Markdown 文件，包含选中文本、笔记和思维导图式记录。",
      variant: "success",
    });
  }, [commentThreads, courseId, toast]);

  const exportKnowledgeCards = useCallback(() => {
    if (knowledgeCards.length === 0) {
      toast({
        title: "暂无可导出的知识卡片",
        description: "当前知识文档内容较少，暂未识别出适合生成卡片的知识点。",
        variant: "info",
      });
      return;
    }
    const filename = `aiteachme-cards-${courseId ?? "course"}.tsv`;
    downloadTextFile(filename, buildKnowledgeCardsTsv(knowledgeCards), "text/tab-separated-values;charset=utf-8");
    toast({
      title: "知识卡片已导出",
      description: "TSV 文件包含正面、背面和来源三列，可导入 Anki 或 Quizlet。",
      variant: "success",
    });
  }, [courseId, knowledgeCards, toast]);

  const centerThreadInViewport = useCallback((threadId: string) => {
    const container = scrollRef.current;
    if (!container) return;

    const thread = commentThreadById.get(threadId);
    if (!thread) return;

    const highlight = selectionHighlights.find((item) => item.threadId === threadId);
    const headingRoot = contentAreaRef.current;
    const heading = findHeadingById(headingRoot ?? container, thread.anchorId);
    const selectionHeading = findSelectionHeadingInDocument(headingRoot ?? container, thread.anchorId, thread.selectedText);
    const fallbackHeading = selectionHeading ?? heading;

    if (selectionHeading && expandCollapsedDocHeadingSections(selectionHeading, { includeSelf: true })) {
      window.requestAnimationFrame(() => {
        centerThreadInViewport(threadId);
      });
      return;
    }

    const currentSegments = thread.selectedText
      ? buildSelectionSegmentsFromText(thread.anchorId, thread.selectedText, highlight?.segments)
      : [];
    if (currentSegments.length > 0) {
      setSelectionHighlights((prev) => {
        const existingIndex = prev.findIndex((item) => item.threadId === threadId);
        const nextHighlight: SelectionHighlight = {
          id: `highlight-${threadId}`,
          threadId,
          anchorId: thread.anchorId,
          selectedText: thread.selectedText,
          segments: currentSegments,
        };
        if (existingIndex < 0) {
          return [nextHighlight, ...prev].slice(0, 200);
        }
        if (
          prev[existingIndex].anchorId === thread.anchorId &&
          prev[existingIndex].selectedText === thread.selectedText &&
          highlightSegmentsEqual(prev[existingIndex].segments, currentSegments)
        ) {
          return prev;
        }
        const next = [...prev];
        next[existingIndex] = {
          ...next[existingIndex],
          anchorId: thread.anchorId,
          selectedText: thread.selectedText,
          segments: currentSegments,
        };
        return next;
      });
    }

    let targetCenter = 0;
    const targetSegments = currentSegments.length > 0 ? currentSegments : highlight?.segments ?? [];
    if (targetSegments.length > 0) {
      const top = Math.min(...targetSegments.map((segment) => segment.top));
      const bottom = Math.max(...targetSegments.map((segment) => segment.top + segment.height));
      targetCenter = (top + bottom) / 2;
    } else if (fallbackHeading) {
      const containerRect = container.getBoundingClientRect();
      const headingRect = fallbackHeading.getBoundingClientRect();
      targetCenter = container.scrollTop + (headingRect.top - containerRect.top) + headingRect.height / 2;
    } else {
      return;
    }

    const maxScrollTop = Math.max(0, container.scrollHeight - container.clientHeight);
    const targetTop = Math.max(0, Math.min(maxScrollTop, targetCenter - container.clientHeight / 2));
    container.scrollTo({ top: targetTop, behavior: "smooth" });

    const targetHeadingId = selectionHeading?.getAttribute("data-heading-id") ?? thread.anchorId;
    if (fallbackHeading) {
      flashHeading(fallbackHeading);
    }
    setActiveHeading(targetHeadingId);
  }, [buildSelectionSegmentsFromText, commentThreadById, expandCollapsedDocHeadingSections, flashHeading, selectionHighlights]);

  const jumpToSelectionLocation = useCallback((detail: SelectionJumpEventDetail): boolean => {
    if (detail.courseId && !routeIdsEqual(detail.courseId, courseId)) {
      return true;
    }
    const anchorId = detail.anchorId?.trim() ?? "";
    const selectedText = detail.selectedText?.trim() ?? "";
    if ((!anchorId && !selectedText) || !hasRenderedMarkdown) {
      return false;
    }

    const container = scrollRef.current;
    const contentRoot = contentAreaRef.current;
    if (!container || !contentRoot) {
      return false;
    }

    const heading = findHeadingById(contentRoot, anchorId);
    const selectionHeading = findSelectionHeadingInDocument(contentRoot, anchorId, selectedText);
    const fallbackHeading = selectionHeading ?? heading;
    const sessionId = detail.sessionId?.trim() ?? "";
    const threadId = sessionId || `jump-${anchorId || "selection"}-${selectedText.slice(0, 16)}`;
    if (sessionId) {
      setThreadSessionIds((prev) => (prev[threadId] === sessionId ? prev : { ...prev, [threadId]: sessionId }));
    }

    if (selectionHeading && expandCollapsedDocHeadingSections(selectionHeading, { includeSelf: true })) {
      window.requestAnimationFrame(() => {
        jumpToSelectionLocation(detail);
      });
      return true;
    }

    const segments = selectedText ? buildSelectionSegmentsFromText(anchorId, selectedText) : [];

    if (selectedText && segments.length > 0) {
      addSelectionHighlight(threadId, anchorId, selectedText, segments);
      setActiveCommentThreadId(threadId);
      setPinnedThreadId(threadId);
      setIsAutoCommentHighlightSuppressed(false);

      const targetTop = Math.min(...segments.map((segment) => segment.top));
      const targetBottom = Math.max(...segments.map((segment) => segment.top + segment.height));
      const targetCenter = (targetTop + targetBottom) / 2;
      const maxScrollTop = Math.max(0, container.scrollHeight - container.clientHeight);
      const nextTop = Math.max(0, Math.min(maxScrollTop, targetCenter - container.clientHeight / 2));
      const activeTargetHeadingId = selectionHeading?.getAttribute("data-heading-id") ?? anchorId;
      setActiveHeading((prev) => (prev === activeTargetHeadingId ? prev : activeTargetHeadingId));
      container.scrollTo({ top: nextTop, behavior: "smooth" });
      if (fallbackHeading) {
        flashHeading(fallbackHeading);
      }
      return true;
    }

    if (fallbackHeading) {
      scrollToHeading(selectionHeading?.getAttribute("data-heading-id") ?? anchorId);
      if (selectedText) {
        setActiveCommentThreadId(threadId);
        setPinnedThreadId(threadId);
        setIsAutoCommentHighlightSuppressed(false);
      }
      return true;
    }

    return false;
  }, [addSelectionHighlight, buildSelectionSegmentsFromText, expandCollapsedDocHeadingSections, flashHeading, hasRenderedMarkdown, scrollToHeading, courseId]);

  const resolveGraphSourceHeadingId = useCallback((ref: KnowledgeGraphSourceRefNavigationTarget): string => {
    const contentRoot = contentAreaRef.current;
    if (!contentRoot) return "";

    const directAnchor = ref.anchor?.trim() ?? "";
    if (directAnchor && findHeadingById(contentRoot, directAnchor)) {
      return directAnchor;
    }

    const headings = Array.from(contentRoot.querySelectorAll<HTMLElement>("[data-heading-id]"));
    const chapterIndex = Number(ref.chapter_index ?? 0);
    if (Number.isFinite(chapterIndex) && chapterIndex > 0) {
      const numberedHeading = headings.find((heading) => headingMajorNumber(heading) === chapterIndex);
      if (numberedHeading) {
        return numberedHeading.getAttribute("data-heading-id") ?? "";
      }

      const headingLevels = headings
        .map((heading) => getHeadingLevel(heading))
        .filter((level) => Number.isFinite(level) && level > 0);
      const shallowestLevel = headingLevels.length > 0 ? Math.min(...headingLevels) : 1;
      const topLevelHeadings = headings.filter((heading) => getHeadingLevel(heading) === shallowestLevel);
      const ordinalHeading = topLevelHeadings[chapterIndex - 1];
      if (ordinalHeading) {
        return ordinalHeading.getAttribute("data-heading-id") ?? "";
      }
    }

    const sourceTitle = normalizeGraphSourceTitle(ref.chapter_title);
    if (sourceTitle) {
      const exactTitle = headings.find((heading) => headingTextForSourceMatch(heading) === sourceTitle);
      if (exactTitle) {
        return exactTitle.getAttribute("data-heading-id") ?? "";
      }

      const closeTitle = headings.find((heading) => {
        const headingText = headingTextForSourceMatch(heading);
        return Boolean(headingText) && (headingText.includes(sourceTitle) || sourceTitle.includes(headingText));
      });
      if (closeTitle) {
        return closeTitle.getAttribute("data-heading-id") ?? "";
      }
    }

    const quoteText = ref.quote_text?.trim() ?? "";
    const quoteHeading = quoteText ? findSelectionHeadingInDocument(contentRoot, "", quoteText) : null;
    if (quoteHeading) {
      return quoteHeading.getAttribute("data-heading-id") ?? "";
    }

    const normalizedQuote = normalizeGraphSourceTitle(quoteText);
    if (normalizedQuote) {
      const headingByQuote = headings.find((heading) => {
        const headingText = headingTextForSourceMatch(heading);
        return Boolean(headingText) && (headingText.includes(normalizedQuote) || normalizedQuote.includes(headingText));
      });
      if (headingByQuote) {
        return headingByQuote.getAttribute("data-heading-id") ?? "";
      }

      const sectionByQuote = Array.from(contentRoot.querySelectorAll<HTMLElement>("[data-heading-section-id]")).find((section) =>
        normalizeGraphSourceTitle(collectNodeText([section])).includes(normalizedQuote),
      );
      const sectionHeading = sectionByQuote ? findDirectSectionHeading(sectionByQuote) : null;
      if (sectionHeading) {
        return sectionHeading.getAttribute("data-heading-id") ?? "";
      }
    }

    return "";
  }, []);

  const handleGraphSourceRefClick = useCallback((ref: KnowledgeGraphSourceRefNavigationTarget) => {
    const anchorId = resolveGraphSourceHeadingId(ref);
    const quoteText = ref.quote_text?.trim() ?? "";
    let handled = false;

    if (anchorId) {
      handled = jumpToSelectionLocation({
        courseId,
        anchorId,
        selectedText: quoteText || null,
      });
    }

    if (!handled && quoteText) {
      handled = jumpToSelectionLocation({
        courseId,
        anchorId: "",
        selectedText: quoteText,
      });
    }

    if (!handled && anchorId) {
      scrollToHeading(anchorId);
      handled = true;
    }

    if (handled) {
      closeGraphPanel();
      return;
    }

    toast({
      title: "暂时无法定位到原文",
      description: "这条图谱来源没有可匹配的章节或引用片段。",
      variant: "warning",
    });
  }, [closeGraphPanel, courseId, jumpToSelectionLocation, resolveGraphSourceHeadingId, scrollToHeading, toast]);

  useEffect(() => {
    const handleSelectionJump = (event: Event) => {
      const detail = (event as CustomEvent<SelectionJumpEventDetail>).detail;
      if (!detail) {
        return;
      }
      const handled = jumpToSelectionLocation(detail);
      pendingSelectionJumpRef.current = handled ? null : detail;
    };

    window.addEventListener(SELECTION_JUMP_EVENT, handleSelectionJump);
    return () => window.removeEventListener(SELECTION_JUMP_EVENT, handleSelectionJump);
  }, [jumpToSelectionLocation]);

  useEffect(() => {
    const state = location.state as KnowledgeDocsLocationState | null;
    const detail = state?.selectionJump ?? null;
    if (!detail) {
      return;
    }
    const marker = state?.selectionJumpAt ?? 0;
    if (handledRouteSelectionJumpRef.current === marker) {
      return;
    }
    handledRouteSelectionJumpRef.current = marker;
    const handled = jumpToSelectionLocation(detail);
    pendingSelectionJumpRef.current = handled ? null : detail;
  }, [jumpToSelectionLocation, location.state]);

  useEffect(() => {
    const pending = pendingSelectionJumpRef.current;
    if (!pending || !hasRenderedMarkdown) {
      return;
    }
    const rafId = window.requestAnimationFrame(() => {
      if (pendingSelectionJumpRef.current && jumpToSelectionLocation(pendingSelectionJumpRef.current)) {
        pendingSelectionJumpRef.current = null;
      }
    });
    return () => window.cancelAnimationFrame(rafId);
  }, [hasRenderedMarkdown, jumpToSelectionLocation, renderedMarkdown]);

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
    const container = scrollRef.current;
    const headingRoot = contentAreaRef.current;
    const resolveThreadDocumentTop = (thread: CommentThreadView): number | undefined => {
      if (!container || !headingRoot) {
        return undefined;
      }
      const heading = findHeadingById(headingRoot, thread.anchorId);
      const selectionHeading = findSelectionHeadingInDocument(headingRoot, thread.anchorId, thread.selectedText);
      const targetHeading = selectionHeading ?? heading;
      if (!targetHeading) {
        return undefined;
      }
      const visibleHeading = findNearestVisibleHeadingForTarget(targetHeading);
      return visibleHeading ? getElementContentTop(container, visibleHeading) : undefined;
    };
    for (const thread of commentThreads) {
      const highlightTop = highlightTopByThreadId.get(thread.threadId) ?? resolveThreadDocumentTop(thread);
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
  }, [collapsedDocHeadingIds, commentListOriginTop, commentThreads, floatingComment, highlightTopByThreadId, isCompactComment]);
  const desktopCommentLayoutThreads = useMemo<CommentThreadView[]>(() => {
    const threads = isCompactComment || !floatingComment
      ? commentThreads
      : [...commentThreads, {
      threadId: FLOATING_COMPOSER_THREAD_ID,
      anchorId: floatingComment.anchorId,
      selectedText: floatingComment.selectedText,
      comments: [],
      createdAt: Number.MAX_SAFE_INTEGER,
      sourceOrder: resolveSelectionSourceOrder(
        contentAreaRef.current,
        floatingComment.anchorId,
        floatingComment.selectedText,
        tocOrderMap,
      ),
    }];

    return [...threads].sort((left, right) => {
      if (left.sourceOrder !== right.sourceOrder) {
        return left.sourceOrder - right.sourceOrder;
      }
      const leftTop = desiredTopByThreadId.get(left.threadId);
      const rightTop = desiredTopByThreadId.get(right.threadId);
      if (leftTop !== undefined && rightTop !== undefined && Math.abs(leftTop - rightTop) > 2) {
        return leftTop - rightTop;
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
    const countedThreadIds = new Set<string>();
    for (const item of commentThreads) {
      countedThreadIds.add(item.threadId);
      next.set(item.anchorId, (next.get(item.anchorId) ?? 0) + 1);
    }
    for (const item of selectionHighlights) {
      const anchorId = item.anchorId.trim();
      if (
        !anchorId ||
        item.threadId === FLOATING_COMPOSER_THREAD_ID ||
        isStandaloneHighlightThreadId(item.threadId) ||
        countedThreadIds.has(item.threadId)
      ) {
        continue;
      }
      next.set(anchorId, (next.get(anchorId) ?? 0) + 1);
    }
    return next;
  }, [commentThreads, selectionHighlights]);
  const highlightCountByAnchor = useMemo(() => {
    const next = new Map<string, number>();
    for (const item of selectionHighlights) {
      const anchorId = item.anchorId.trim();
      if (!anchorId || item.threadId === FLOATING_COMPOSER_THREAD_ID) {
        continue;
      }
      next.set(anchorId, (next.get(anchorId) ?? 0) + 1);
    }
    return next;
  }, [selectionHighlights]);
  const tocAnchorDescendantIds = useMemo(() => {
    const next = new Map<string, string[]>();
    const visit = (node: TocTreeNode): string[] => {
      const ids = [node.item.id];
      for (const child of node.children) {
        ids.push(...visit(child));
      }
      next.set(node.item.id, ids);
      return ids;
    };
    for (const node of tocTree) {
      visit(node);
    }
    return next;
  }, [tocTree]);
  const countTocAnchorItems = useCallback(
    (anchorId: string, source: Map<string, number>) => {
      const ids = tocAnchorDescendantIds.get(anchorId) ?? [anchorId];
      let total = 0;
      for (const id of ids) {
        total += source.get(id) ?? 0;
      }
      return total;
    },
    [tocAnchorDescendantIds]
  );
  const commentsForTocAnchor = useCallback(
    (anchorId: string) => countTocAnchorItems(anchorId, threadCountByAnchor),
    [countTocAnchorItems, threadCountByAnchor]
  );
  const highlightsForTocAnchor = useCallback(
    (anchorId: string) => countTocAnchorItems(anchorId, highlightCountByAnchor),
    [countTocAnchorItems, highlightCountByAnchor]
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

  const scheduleDesktopCommentLayoutRefresh = useCallback(() => {
    if (isCompactComment || typeof window === "undefined") {
      return;
    }

    const refresh = () => {
      refreshThreadHeights();
      updateDesktopCommentScrollExtent();
      syncDesktopCommentTrack();
    };

    refresh();
    window.requestAnimationFrame(refresh);
    window.setTimeout(refresh, 80);
  }, [
    isCompactComment,
    refreshThreadHeights,
    syncDesktopCommentTrack,
    updateDesktopCommentScrollExtent,
  ]);

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
      const kept = prev.filter((item) => threadIdSet.has(item.threadId) || isTransientSelectionThreadId(item.threadId));
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
        refreshSelectionHighlightSegments();
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
    collapsedDocHeadingIds,
    hasRenderedMarkdown,
    isCommentCollapsed,
    isCompactComment,
    refreshSelectionHighlightSegments,
    isTocCollapsed,
    pageWideMode,
    viewPrefs.showCommentPanel,
    viewPrefs.showToc,
  ]);

  useLayoutEffect(() => {
    if (!isAssistantOpen || !hasRenderedMarkdown) {
      return;
    }

    let rafId = 0;
    let settleTimer = 0;

    const startedAt = performance.now();
    const tick = () => {
      refreshSelectionHighlightSegments();
      if (performance.now() - startedAt < 1200) {
        rafId = window.requestAnimationFrame(tick);
      }
    };

    refreshSelectionHighlightSegments();
    rafId = window.requestAnimationFrame(tick);
    settleTimer = window.setTimeout(refreshSelectionHighlightSegments, 1400);

    return () => {
      window.cancelAnimationFrame(rafId);
      window.clearTimeout(settleTimer);
    };
  }, [collapsedDocHeadingIds, hasRenderedMarkdown, isAssistantOpen, refreshSelectionHighlightSegments]);

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
  const aiMatchedHighlightedThreadId = useMemo(() => {
    if (!isAssistantOpen || selectionHighlights.length === 0) {
      return null;
    }

    const activeSessionId = activeConversationSessionId?.trim() ?? "";
    const requestSessionId = typeof sidebarRequest?.sessionId === "string"
      ? sidebarRequest.sessionId.trim()
      : "";
    const requestThreadId = sidebarRequest?.clientThreadId?.trim() ?? "";
    const requestAnchorId = sidebarRequest?.anchorId?.trim() ?? "";
    const requestSelectedText = sidebarRequest?.selectedText?.trim() ?? "";
    const activeSelectionSessionId = activeConversationSelectionTarget?.sessionId?.trim() ?? "";
    const activeSelectionAnchorId = activeConversationSelectionTarget?.anchorId.trim() ?? "";
    const activeSelectionText = activeConversationSelectionTarget?.selectedText.trim() ?? "";

    return selectionHighlights.find((highlight) => {
      const threadId = highlight.threadId.trim();
      const resolvedSessionId = resolveSelectionThreadSessionId(threadId, threadSessionIds);
      if (
        activeSelectionSessionId &&
        (threadId === activeSelectionSessionId || resolvedSessionId === activeSelectionSessionId)
      ) {
        return true;
      }
      if (
        activeSelectionAnchorId &&
        activeSelectionText &&
        highlight.anchorId === activeSelectionAnchorId &&
        highlight.selectedText.trim() === activeSelectionText
      ) {
        return true;
      }
      if (activeSessionId && (threadId === activeSessionId || resolvedSessionId === activeSessionId)) {
        return true;
      }
      if (requestSessionId && (threadId === requestSessionId || resolvedSessionId === requestSessionId)) {
        return true;
      }
      if (requestThreadId && threadId === requestThreadId) {
        return true;
      }
      return Boolean(
        requestAnchorId &&
        requestSelectedText &&
        highlight.anchorId === requestAnchorId &&
        highlight.selectedText.trim() === requestSelectedText,
      );
    })?.threadId ?? null;
  }, [
    activeConversationSessionId,
    activeConversationSelectionTarget,
    isAssistantOpen,
    selectionHighlights,
    sidebarRequest,
    threadSessionIds,
  ]);

  const focusCommentThread = useCallback((
    threadId: string,
    options: { scrollToDoc?: boolean; pinToSelection?: boolean; scrollThreadIntoView?: boolean } = {}
  ) => {
    const thread = commentThreadById.get(threadId);
    if (!thread) {
      return;
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
  }, [centerThreadInViewport, commentThreadById, isCompactComment]);

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
  const openAiInteractionFromThread = useCallback((threadId?: string) => {
    if (!courseId) return;
    const targetThreadId = threadId ?? activeThreadId ?? commentThreadIds[0] ?? null;
    const targetThread = targetThreadId ? commentThreadById.get(targetThreadId) ?? null : null;
    const targetHighlight = targetThreadId
      ? selectionHighlights.find((item) => item.threadId === targetThreadId) ?? null
      : null;
    const targetSessionId = resolveSelectionThreadSessionId(targetThreadId, threadSessionIds);
    const anchorId = targetThread?.anchorId ?? targetHighlight?.anchorId ?? "";
    const selectedText = targetThread?.selectedText ?? targetHighlight?.selectedText ?? "";
    if (targetSessionId) {
      if (anchorId && selectedText) {
        openAiInteraction({
          scope: { type: "course", courseId },
          sessionId: targetSessionId,
          scene: AI_SCENE_DOCUMENT_SELECTION,
          source: "quick_chat",
          anchorId,
          selectedText,
          selectionContext: buildSelectionContextPayload(contentAreaRef.current, anchorId, selectedText),
          showSelectionContext: false,
        });
        return;
      }
      openAiInteraction({ scope: { type: "course", courseId }, sessionId: targetSessionId });
      return;
    }
    if (targetThreadId && anchorId && selectedText) {
      openAiInteraction({
        scope: { type: "course", courseId },
        sessionId: null,
        draft: "",
        scene: AI_SCENE_DOCUMENT_SELECTION,
        source: "quick_chat",
        anchorId,
        selectedText,
        selectionContext: buildSelectionContextPayload(contentAreaRef.current, anchorId, selectedText),
        clientThreadId: targetThreadId,
        newSession: true,
        showSelectionContext: true,
      });
      return;
    }
    openAiInteraction({ scope: { type: "course", courseId } });
  }, [activeThreadId, commentThreadById, commentThreadIds, openAiInteraction, selectionHighlights, courseId, threadSessionIds]);

  const openSelectionHighlightThread = useCallback((threadId: string) => {
    if (isStandaloneHighlightThreadId(threadId)) {
      setActiveCommentThreadId(threadId);
      setPinnedThreadId(threadId);
      setIsAutoCommentHighlightSuppressed(false);
      return;
    }
    if (viewPrefs.showCommentPanel && commentThreadById.has(threadId)) {
      focusCommentThread(threadId, {
        scrollToDoc: false,
        pinToSelection: true,
        scrollThreadIntoView: isCompactComment,
      });
    } else {
      setActiveCommentThreadId(threadId);
      setPinnedThreadId(threadId);
      setIsAutoCommentHighlightSuppressed(false);
    }
    openAiInteractionFromThread(threadId);
  }, [commentThreadById, focusCommentThread, isCompactComment, openAiInteractionFromThread, viewPrefs.showCommentPanel]);

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

  const collapsibleTocIds = useMemo(() => collectCollapsibleTocIds(tocTree), [tocTree]);

  const expandAllTocLevels = useCallback(() => {
    setCollapsedTocIds(new Set());
  }, []);

  const collapseAllTocLevels = useCallback(() => {
    setCollapsedTocIds(new Set(collapsibleTocIds));
  }, [collapsibleTocIds]);

  const canExpandAllTocLevels = collapsedTocIds.size > 0;
  const canCollapseAllTocLevels = collapsibleTocIds.size > 0 && collapsedTocIds.size < collapsibleTocIds.size;

  const renderTocNodes = useCallback((nodes: TocTreeNode[], depth: number = 0): React.ReactNode => {
    return nodes.map((node) => {
      const { item } = node;
      const hasChildren = node.children.length > 0;
      const isCollapsed = collapsedTocIds.has(item.id);
      const isActive = visibleActiveHeading === item.id;
      const count = commentsForTocAnchor(item.id);
      const highlightCount = highlightsForTocAnchor(item.id);
      const indent = depth * 12;
      const displayText = splitTocDisplayText(item.text);

      return (
        <div key={item.id}>
          <div
            data-toc-id={item.id}
            className={cn(
              "group relative flex items-center rounded-md transition-colors duration-150 overflow-hidden",
              isActive
                ? "bg-indigo-50/70 text-indigo-700 dark:bg-indigo-950/30 dark:text-indigo-300"
                : "text-slate-600 hover:bg-slate-100/60 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-100"
            )}
            style={{ paddingLeft: indent + 8 }}
          >
            {/* Active indicator bar */}
            {isActive && (
              <span
                className="absolute top-1/2 -translate-y-1/2 w-[3px] h-4 bg-indigo-600 dark:bg-indigo-400 rounded-r-full"
                style={{ left: indent + 2 }}
              />
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
                  isActive
                    ? "text-indigo-500 hover:bg-indigo-100/50 dark:text-indigo-300 dark:hover:bg-indigo-500/20"
                    : "text-slate-400 hover:bg-slate-200/60 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300"
                )}
                title={isCollapsed ? `展开：${item.text}` : `收起：${item.text}`}
                aria-label={isCollapsed ? `展开：${item.text}` : `收起：${item.text}`}
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
              title={item.text}
              aria-label={`跳转到：${item.text}`}
              className={cn(
                "flex-1 min-w-0 text-left py-1.5 pr-1 text-[14px] leading-5 truncate transition-colors",
                isActive
                  ? "font-semibold text-indigo-700 dark:text-indigo-300"
                  : item.level === 1
                    ? "font-semibold text-slate-800 dark:text-slate-100"
                    : "font-normal text-slate-700 dark:text-slate-300",
                item.level === 1 && "text-[14.5px]",
                item.level >= 3 && "text-[13.5px]"
              )}
            >
              {displayText.number ? (
                <span
                  className="mr-1.5 select-none font-semibold text-indigo-600 dark:text-indigo-400"
                >
                  {displayText.number}
                </span>
              ) : null}
              <span>{displayText.title}</span>
            </button>

            {item.hasInteractive && (
              <span
                className="mr-1 inline-flex h-4 shrink-0 items-center gap-0.5 rounded-full bg-indigo-100 px-1.5 text-[10px] font-medium text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300"
                title="本章节包含交互网页"
              >
                <SlidersHorizontal className="h-2.5 w-2.5" />
                交互
              </span>
            )}
            {count > 0 && (
              <span
                className="mr-1 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-sky-50 text-sky-600 ring-1 ring-sky-100 dark:bg-sky-500/10 dark:text-sky-300 dark:ring-sky-400/15"
                title={`本章节${node.children.length > 0 ? "或子章节" : ""}有 ${count} 个划选问答`}
                aria-label={`本章节${node.children.length > 0 ? "或子章节" : ""}有划选问答`}
              >
                <MessageCircle className="h-3 w-3" />
              </span>
            )}
            {highlightCount > 0 && (
              <span
                className="mr-1 inline-flex h-2.5 w-2.5 shrink-0 rounded-full bg-amber-400 shadow-[0_0_0_3px_rgba(251,191,36,0.16)]"
                title={`本章节${node.children.length > 0 ? "或子章节" : ""}有 ${highlightCount} 个高亮`}
                aria-label={`本章节${node.children.length > 0 ? "或子章节" : ""}有高亮`}
              >
                <span className="sr-only">本章节有高亮</span>
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
  }, [collapsedTocIds, commentsForTocAnchor, handleTocItemClick, highlightsForTocAnchor, toggleTocCollapse, visibleActiveHeading]);

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

  const renderTocNav = (showBulkControls: boolean) => (
    <div className="relative h-full">
      <nav
        ref={tocNavRef}
        className={cn("toc-scroll h-full overflow-y-auto pr-2", showBulkControls ? "py-2" : "pb-2 pt-0")}
        onWheel={handleTocManualScrollStart}
        onTouchStart={handleTocManualScrollStart}
        onPointerDown={handleTocManualScrollStart}
        onScroll={handleTocNavScroll}
      >
        {showBulkControls && tocTree.length > 0 && (
          <div className="sticky top-0 z-10 mb-1 flex h-8 items-center justify-end bg-white/95 px-1 pb-1 pt-0.5 backdrop-blur dark:bg-slate-950/95">
            <div className="flex items-center gap-0.5 text-slate-400">
              <button
                type="button"
                onClick={expandAllTocLevels}
                disabled={!canExpandAllTocLevels}
                className="inline-flex h-6 w-6 items-center justify-center rounded-[4px] transition hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 disabled:cursor-default disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200 dark:focus-visible:ring-indigo-500"
                aria-label="展开所有目录层级"
                title="展开所有层级"
              >
                <ListTree className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={collapseAllTocLevels}
                disabled={!canCollapseAllTocLevels}
                className="inline-flex h-6 w-6 items-center justify-center rounded-[4px] transition hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 disabled:cursor-default disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200 dark:focus-visible:ring-indigo-500"
                aria-label="收起所有目录层级"
                title="收起所有层级"
              >
                <ListCollapse className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
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
  const compactTocNav = renderTocNav(true);
  const desktopTocNav = renderTocNav(false);

  const commentPanel = (
    <div
      ref={commentPanelRef}
      className={cn(
        "relative flex h-full w-full min-h-0 flex-col",
        isCompactComment
          ? "flex h-full flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_24px_56px_-24px_rgba(0,0,0,0.85)]"
          : "overflow-hidden bg-white/86 dark:bg-slate-950/88"
      )}
    >
      <div className="flex h-11 items-center justify-between border-b border-slate-200/80 px-1 dark:border-slate-800">
        <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
          <StickyNote className="w-4 h-4" />
          <span className="text-sm font-semibold">选区问答</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {commentThreads.length} 个片段
            {activeStreamingCount > 0 ? `（${activeStreamingCount} 条回复中）` : ""}
          </span>
          <button
            onClick={exportAnnotations}
            disabled={commentThreads.length === 0}
            className={cn(
              "w-7 h-7 rounded-lg transition-colors flex items-center justify-center",
              commentThreads.length === 0
                ? "cursor-not-allowed text-slate-300 dark:text-slate-700"
                : "text-slate-500 hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
            )}
            aria-label="导出选区问答"
            title="导出选区问答"
          >
            <Download className="w-4 h-4" />
          </button>
          <button
            onClick={() => jumpCommentThread(-1)}
            disabled={activeCommentIndex <= 0}
            className={cn(
              "w-7 h-7 rounded-lg transition-colors flex items-center justify-center",
              activeCommentIndex <= 0
                ? "cursor-not-allowed text-slate-300 dark:text-slate-700"
                : "text-slate-500 hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
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
                ? "cursor-not-allowed text-slate-300 dark:text-slate-700"
                : "text-slate-500 hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
            )}
            aria-label="定位下一段对话"
            title="定位下一段对话"
          >
            <ChevronDown className="w-4 h-4" />
          </button>
          <button
            onClick={closeCommentPanel}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
            aria-label="收起问答栏"
          >
            <ChevronRight className={cn("w-4 h-4", isCompactComment && "rotate-180")} />
          </button>
        </div>
      </div>

      {isCompactComment && floatingComment && (
        <div
          className="absolute left-3 right-3 z-30 overflow-hidden rounded-2xl border border-slate-200/90 bg-white/95 shadow-[0_28px_56px_-30px_rgba(15,23,42,0.68)] backdrop-blur dark:border-slate-800 dark:bg-slate-950/95 dark:shadow-[0_28px_56px_-24px_rgba(0,0,0,0.86)]"
          style={{ top: floatingComment.top }}
        >
          <div className="border-b border-slate-200/80 bg-[linear-gradient(130deg,rgba(238,242,255,0.85),rgba(248,250,252,0.95),rgba(224,231,255,0.85))] px-3 py-2.5 dark:border-slate-800 dark:bg-[linear-gradient(130deg,rgba(99,102,241,0.12),rgba(15,23,42,0.96),rgba(79,70,229,0.10))]">
            <div className="flex items-center gap-2">
              <span className="inline-flex h-6 w-6 items-center justify-center rounded-lg bg-slate-900 text-white shadow-sm">
                <Sparkles className="h-3.5 w-3.5" />
              </span>
              <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">AI Assistant</p>
                <p className="truncate text-xs text-slate-700 dark:text-slate-300">&ldquo;{floatingComment.selectedText.slice(0, 60)}&rdquo;</p>
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
              className="w-full resize-none rounded-xl border border-slate-200/90 bg-white px-3 py-2.5 text-sm leading-6 text-slate-800 shadow-inner shadow-slate-100/70 outline-none transition focus:border-slate-300 focus:ring-4 focus:ring-indigo-100/80 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:shadow-none dark:placeholder:text-slate-500 dark:focus:border-indigo-500/50 dark:focus:ring-indigo-500/20"
            />
            <div className="flex items-center justify-between">
              <button
                onClick={dismissCommentComposer}
                className="rounded-lg px-2.5 py-1 text-xs text-slate-500 transition hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
              >
                取消
              </button>
              <button
                onClick={addComment}
                disabled={!floatingInput.trim()}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-medium transition",
                  floatingInput.trim()
                    ? "bg-slate-900 text-white shadow-sm hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200"
                    : "bg-slate-100 text-slate-300 dark:bg-slate-800 dark:text-slate-600"
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
          isCompactComment ? "overflow-y-auto bg-slate-50/80 dark:bg-slate-900/70" : "overflow-hidden pr-1"
        )}
      >
        {isCompactComment && (
          <>
            <div className="pointer-events-none absolute inset-x-0 top-0 z-20 h-12 bg-gradient-to-b from-slate-50 via-slate-50/80 to-transparent dark:from-slate-900 dark:via-slate-900/80" />
            <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 h-12 bg-gradient-to-t from-slate-50 via-slate-50/80 to-transparent dark:from-slate-900 dark:via-slate-900/80" />
          </>
        )}
        {!threadHistoryLoaded ? (
          <div className={cn("p-3", isCompactComment && "h-full")}>
            <div className={cn(
              "flex items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 text-slate-400 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-500",
              isCompactComment ? "h-full" : "h-24"
            )}>
              <Loader2 className="h-4 w-4 animate-spin" />
            </div>
          </div>
        ) : threadHistoryError ? (
          <div className={cn("p-3", isCompactComment && "h-full")}>
            <div className="rounded-xl border border-rose-200 bg-rose-50/70 px-4 py-4 text-xs leading-5 text-rose-600 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
              {threadHistoryError}
            </div>
          </div>
        ) : commentThreads.length === 0 && !floatingComment ? (
          <div className={cn("p-3", isCompactComment && "h-full")}>
            <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-center dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
              <p className="text-sm text-slate-500 dark:text-slate-400">选中文本后点击“问问 AI”，即可形成可导出的划词问答记录</p>
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
                    isActive={highlightedThreadId === thread.threadId}
                    onFocus={() => focusCommentThread(thread.threadId, { scrollToDoc: false, scrollThreadIntoView: false })}
                    onJumpToAnchor={() => focusCommentThread(thread.threadId, { pinToSelection: true, scrollThreadIntoView: false })}
                  onOpenAiInteraction={() => openAiInteractionFromThread(thread.threadId)}
                  onSizeChange={scheduleDesktopCommentLayoutRefresh}
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
                      <div className="overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-[0_22px_48px_-32px_rgba(15,23,42,0.45)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_22px_48px_-24px_rgba(0,0,0,0.86)]">
                        <div className="border-b border-slate-200/80 bg-[linear-gradient(130deg,rgba(238,242,255,0.82),rgba(248,250,252,0.96),rgba(224,231,255,0.88))] px-3 py-2.5 dark:border-slate-800 dark:bg-[linear-gradient(130deg,rgba(99,102,241,0.12),rgba(15,23,42,0.96),rgba(79,70,229,0.10))]">
                          <div className="flex items-center gap-2">
                            <span className="inline-flex h-7 w-7 items-center justify-center rounded-xl bg-slate-900 text-white shadow-sm">
                              <Sparkles className="h-3.5 w-3.5" />
                            </span>
                            <div className="min-w-0">
                              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">问问 AI</p>
                              <p className="truncate text-xs text-slate-700 dark:text-slate-300">&ldquo;{floatingComment.selectedText.slice(0, 72)}&rdquo;</p>
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
                            className="w-full resize-none rounded-xl border border-slate-200/90 bg-white px-3 py-2.5 text-sm leading-6 text-slate-800 shadow-inner shadow-slate-100/70 outline-none transition focus:border-slate-300 focus:ring-4 focus:ring-indigo-100/80 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:shadow-none dark:placeholder:text-slate-500 dark:focus:border-indigo-500/50 dark:focus:ring-indigo-500/20"
                          />
                          <div className="flex items-center justify-between">
                            <button
                              onClick={dismissCommentComposer}
                              className="rounded-lg px-2.5 py-1 text-xs text-slate-500 transition hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                            >
                              取消
                            </button>
                            <button
                              onClick={addComment}
                              disabled={!floatingInput.trim()}
                              className={cn(
                                "inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-medium transition",
                                floatingInput.trim()
                                  ? "bg-slate-900 text-white shadow-sm hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200"
                                  : "bg-slate-100 text-slate-300 dark:bg-slate-800 dark:text-slate-600"
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
                      isActive={highlightedThreadId === thread.threadId}
                      onFocus={() => focusCommentThread(thread.threadId, {
                        pinToSelection: true,
                        scrollThreadIntoView: false,
                      })}
                      onJumpToAnchor={() => focusCommentThread(thread.threadId, { pinToSelection: true, scrollThreadIntoView: false })}
                      onOpenAiInteraction={() => openAiInteractionFromThread(thread.threadId)}
                      onSizeChange={scheduleDesktopCommentLayoutRefresh}
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
  const showFloatingActions = Boolean(courseId && !isBuildActive && !showDocLoadingState && !showDocGeneratingState && !isAssistantOpen && !isGraphDrawerOpen);

  if (!hasRenderedMarkdown && (isBuildActive || isWaitingForRequestedBuild || showDocGeneratingState)) {
    return (
      <div className="relative flex h-full min-h-0 flex-1 w-full flex-col overflow-hidden bg-white dark:bg-slate-950">
        <CoursePagePillTitle
          icon={BookOpen}
          label="知识库"
          className="shrink-0 bg-white/92 backdrop-blur-md dark:bg-slate-900/92"
          href={courseId ? buildCoursePath(courseId, "nav") : undefined}
        />
        <div className="relative flex-1 min-h-0 w-full overflow-hidden">
          <BuildView
            className="h-full"
            isFetching={docMarkdownQuery.isFetching}
            progress={buildProgress}
            statusText={buildStatusText}
            buildPreview={buildPreview}
            buildMetrics={buildMetrics}
            sourceFiles={sourceFiles}
            sourceFilesFetching={sourceFilesFetching}
            buildStage={buildMeta?.stage}
            buildStatus={buildStatus}
            isDocumentReady={isRequestedBuildReady}
            courseId={courseId}
          />
        </div>
      </div>
    );
  }

  if (!hasRenderedMarkdown && showDocLoadingState) {
    return (
      <div className="relative flex h-full min-h-0 flex-1 w-full flex-col overflow-hidden bg-white dark:bg-slate-950">
        <CoursePagePillTitle
          icon={BookOpen}
          label="知识库"
          className="shrink-0 bg-white/92 backdrop-blur-md dark:bg-slate-900/92"
          href={courseId ? buildCoursePath(courseId, "nav") : undefined}
        />
        <div className="relative flex-1 min-h-0 w-full flex items-center justify-center overflow-hidden bg-white px-4 dark:bg-slate-950">
          <DocLoadingState />
        </div>
      </div>
    );
  }

  if (!hasRenderedMarkdown && docMarkdownQuery.isError) {
    return (
      <div className="relative flex h-full min-h-0 flex-1 w-full flex-col overflow-hidden bg-white dark:bg-slate-950">
        <CoursePagePillTitle
          icon={BookOpen}
          label="知识库"
          className="shrink-0 bg-white/92 backdrop-blur-md dark:bg-slate-900/92"
          href={courseId ? buildCoursePath(courseId, "nav") : undefined}
        />
        <div className="relative flex min-h-0 w-full flex-1 items-center justify-center overflow-hidden bg-white px-4 dark:bg-slate-950">
          <DocLoadErrorState
            message={getApiErrorMessage(docMarkdownQuery.error, "获取知识文档失败，请稍后重试。")}
            onRetry={() => {
              void docMarkdownQuery.refetch();
            }}
          />
        </div>
      </div>
    );
  }

  if (!hasRenderedMarkdown && showDocBuildFailureState) {
    return (
      <div className="relative flex h-full min-h-0 flex-1 w-full flex-col overflow-hidden bg-white dark:bg-slate-950">
        <CoursePagePillTitle
          icon={BookOpen}
          label="知识库"
          className="shrink-0 bg-white/92 backdrop-blur-md dark:bg-slate-900/92"
          href={courseId ? buildCoursePath(courseId, "nav") : undefined}
        />
        <div className="relative flex min-h-0 w-full flex-1 items-center justify-center overflow-hidden bg-white px-4 dark:bg-slate-950">
          <DocLoadErrorState
            message={buildStatusText}
            onRetry={() => {
              void docMarkdownQuery.refetch();
            }}
          />
        </div>
      </div>
    );
  }

  if (!hasRenderedMarkdown && showDocEmptyState) {
    return (
      <div className="relative flex h-full min-h-0 flex-1 w-full flex-col overflow-hidden bg-white dark:bg-slate-950">
        <CoursePagePillTitle
          icon={BookOpen}
          label="知识库"
          className="shrink-0 bg-white/92 backdrop-blur-md dark:bg-slate-900/92"
          href={courseId ? buildCoursePath(courseId, "nav") : undefined}
        />
        <div className="relative flex min-h-0 w-full flex-1 items-center justify-center overflow-hidden bg-white px-4 dark:bg-slate-950">
          <DocEmptyState />
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex h-full min-h-0 flex-1 w-full overflow-hidden bg-slate-50 dark:bg-slate-900">
      <div className="relative z-10 flex min-h-0 h-full w-full bg-white dark:bg-slate-900">
      {hasCompactTocControl && (
          <div className="fixed left-[4.75rem] top-[calc(1.25rem+env(safe-area-inset-top))] z-[79] flex items-center gap-2">
            <button
              onClick={openTocDrawer}
              className={cn(
                "flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 bg-white/95 shadow-sm backdrop-blur-sm transition-colors dark:border-slate-800 dark:bg-slate-950/92",
                isTocVisible ? "bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300" : "text-slate-600 hover:bg-white hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-900 dark:hover:text-slate-100"
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
                "relative flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 bg-white/95 shadow-sm backdrop-blur-sm transition-colors dark:border-slate-800 dark:bg-slate-950/92",
                isCommentVisible ? "bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300" : "text-slate-600 hover:bg-white hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-900 dark:hover:text-slate-100"
              )}
              aria-label="切换选区问答"
              title="选区问答"
            >
              <StickyNote className="w-4 h-4" />
              {commentThreads.length > 0 && (
                <span className="absolute -top-1 -right-1 min-w-4 h-4 px-1 rounded-full bg-indigo-500 text-white text-[10px] leading-4 text-center">
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
              "fixed bottom-4 left-3 top-[calc(3.875rem+env(safe-area-inset-top))] z-[78] flex w-[min(20rem,calc(100vw-1.5rem))] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl transition-transform duration-200 dark:border-slate-800 dark:bg-slate-950",
              isTocVisible ? "translate-x-0" : "-translate-x-[110%] pointer-events-none"
            )}
          >
            <div className="flex h-11 items-center justify-between border-b border-slate-200/80 px-3 dark:border-slate-800">
              <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
                <FileText className="w-4 h-4" />
                <span className="text-sm font-semibold">目录</span>
              </div>
              <button
                onClick={closeDrawer}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                aria-label="收起目录"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
            <div className="flex-1 overflow-hidden px-1 pb-2">{compactTocNav}</div>
          </aside>
      )}

      {hasCompactCommentControl && (
        <aside
          className={cn(
            "fixed right-3 top-[calc(3.875rem+env(safe-area-inset-top))] bottom-4 z-[78] w-[min(24rem,calc(100vw-1.5rem))] transition-transform duration-200",
            isCommentVisible ? "translate-x-0" : "translate-x-[110%] pointer-events-none"
          )}
        >
          {commentPanel}
        </aside>
      )}

      {!isCompactToc && viewPrefs.showToc && (
        <aside
          className={cn(
            "h-full min-h-0 shrink-0 overflow-hidden bg-white/88 backdrop-blur-md transition-[width] duration-300 ease-out dark:bg-slate-950/88",
            isTocCollapsed ? "w-[56px]" : desktopTocWidthClass
          )}
        >
          <div className="flex h-full flex-col">
            {isTocCollapsed ? (
              <div className="flex flex-1 items-start justify-start px-2 py-3">
                <button
                  onClick={() => setIsTocCollapsed(false)}
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-[#4F46E5] transition-colors hover:bg-[#EEF2FF] hover:text-[#4338CA] dark:text-indigo-300 dark:hover:bg-indigo-500/10 dark:hover:text-indigo-200"
                  aria-label="展开目录"
                  title={activeTocItem?.text ? `展开目录（当前：${activeTocItem.text}）` : "展开目录"}
                >
                  <ChevronsRight className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <>
                <div className="sticky top-0 z-10 flex items-center justify-between bg-white/92 px-3 pb-1 pt-3 backdrop-blur-md dark:bg-slate-950/92">
                  <div className="flex min-w-0 items-center gap-2">
                    <button
                      onClick={() => setIsTocCollapsed(true)}
                      className="flex h-8 w-8 items-center justify-center rounded-lg text-[#4F46E5] transition-colors hover:bg-[#EEF2FF] hover:text-[#4338CA] dark:text-indigo-300 dark:hover:bg-indigo-500/10 dark:hover:text-indigo-200"
                      aria-label="收起目录"
                      title="收起目录"
                    >
                      <ChevronsLeft className="h-4 w-4" />
                    </button>
                    <span className="truncate text-sm font-semibold text-slate-800 dark:text-slate-100">目录</span>
                  </div>
                  <div className="flex items-center gap-0.5 text-slate-400">
                    <button
                      type="button"
                      onClick={expandAllTocLevels}
                      disabled={!canExpandAllTocLevels}
                      className="inline-flex h-6 w-6 items-center justify-center rounded-[4px] transition hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 disabled:cursor-default disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200 dark:focus-visible:ring-indigo-500"
                      aria-label="展开所有目录层级"
                      title="展开所有层级"
                    >
                      <ListTree className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      onClick={collapseAllTocLevels}
                      disabled={!canCollapseAllTocLevels}
                      className="inline-flex h-6 w-6 items-center justify-center rounded-[4px] transition hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 disabled:cursor-default disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200 dark:focus-visible:ring-indigo-500"
                      aria-label="收起所有目录层级"
                      title="收起所有层级"
                    >
                      <ListCollapse className="h-4 w-4" />
                    </button>
                  </div>
                </div>
                <div className="min-h-0 flex-1 overflow-hidden px-2 pb-3 pt-0.5">
                  {desktopTocNav}
                </div>
              </>
            )}
          </div>
        </aside>
      )}

      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        {!isCompactComment && viewPrefs.showCommentPanel && isCommentCollapsed && !shouldHideCommentPanelForAssistant && (
          <aside className="absolute right-4 top-4 z-20 hidden lg:flex">
            <button
              onClick={() => setIsCommentCollapsed(false)}
              className="rounded-xl border border-slate-200 bg-white/95 px-2 py-2.5 text-slate-600 shadow-sm transition-colors hover:bg-white hover:text-slate-900 dark:border-slate-800 dark:bg-slate-950/92 dark:text-slate-400 dark:hover:bg-slate-900 dark:hover:text-slate-100"
              aria-label="展开问答栏"
            >
              <Bot className="w-4 h-4" />
            </button>
          </aside>
        )}

        <CoursePagePillTitle
          icon={BookOpen}
          label="知识库"
          className="shrink-0 bg-white/92 backdrop-blur-md dark:bg-slate-900/92 transition-all duration-300 ease-in-out"
          href={courseId ? buildCoursePath(courseId, "nav") : undefined}
        />

        <div
          ref={scrollRef}
          className="relative h-full overflow-y-auto doc-scroll-container content-scroll"
          onMouseUp={handleTextSelect}
        >
          <div
            className="min-h-full px-4 pb-8 pt-4 md:px-6 lg:px-8"
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
                <div className="relative flex min-w-0 items-start">
                  <article className="min-w-0 flex-1 px-2 py-2 md:px-4">
                  <CourseVectorNotice status={docMarkdownQuery.data?.vector_status} className="mb-6" />
                  {docMarkdownQuery.isError ? (
                    <DocLoadErrorState
                      message={getApiErrorMessage(docMarkdownQuery.error, "获取知识文档失败，请稍后重试。")}
                      onRetry={() => {
                        void docMarkdownQuery.refetch();
                      }}
                    />
                  ) : showDocLoadingState ? (
                    <DocLoadingState />
                  ) : isBuildActive || isWaitingForRequestedBuild || showDocGeneratingState ? (
                    <BuildView
                      className="h-[70vh] min-h-[600px] overflow-hidden rounded-xl border border-zinc-100 dark:border-slate-800"
                      isFetching={docMarkdownQuery.isFetching}
                      progress={buildProgress}
                      statusText={buildStatusText}
                      buildPreview={buildPreview}
                      buildMetrics={buildMetrics}
                      sourceFiles={sourceFiles}
                      sourceFilesFetching={sourceFilesFetching}
                      buildStage={buildMeta?.stage}
                      buildStatus={buildStatus}
                      isDocumentReady={isRequestedBuildReady}
                      courseId={courseId}
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
                      <DocMarkdown
                        content={renderedMarkdown}
                        courseId={courseId}
                        onHeadingCollapseChange={handleDocHeadingCollapseChange}
                      />
                      {pendingInteractiveBlocks.map((block) => (
                        <PendingInteractiveBlockPortal
                          key={block.id}
                          block={block}
                          contentRoot={contentAreaRef.current}
                        />
                      ))}
                    </>
                  )}
                  </article>
                </div>
              </div>
              {showDesktopCommentPanel && (
                <aside
                  className={cn(
                    "sticky top-4 h-[calc(100dvh-2rem)] min-h-0 shrink-0 border-l border-slate-200/80 bg-white/92 px-3 py-4 backdrop-blur-md dark:border-slate-800 dark:bg-slate-950/92",
                    desktopCommentWidthClass,
                  )}
                >
                  {commentPanel}
                </aside>
              )}
            </div>

          {selectionHighlights.map((highlight) => (
            <div key={highlight.id}>
              {highlight.segments.map((segment, index) => {
                const isAiMatchedHighlight = aiMatchedHighlightedThreadId === highlight.threadId;
                const isStandaloneHighlight = isStandaloneHighlightThreadId(highlight.threadId);
                return (
                  <button
                    key={`${highlight.id}-${index}`}
                    type="button"
                    onClick={() => openSelectionHighlightThread(highlight.threadId)}
                    data-highlight-thread-id={highlight.threadId}
                    className={cn(
                      "group absolute z-30 rounded-[2px] transition-shadow duration-150 focus-visible:outline-none",
                      isAiMatchedHighlight || isStandaloneHighlight
                        ? "bg-amber-100/60 shadow-[0_4px_12px_-14px_rgba(180,83,9,0.65)]"
                        : "bg-transparent focus-visible:ring-2 focus-visible:ring-amber-300/45"
                    )}
                    style={{
                      top: segment.top,
                      left: segment.left,
                      width: segment.width,
                      height: segment.height,
                      backgroundColor: isAiMatchedHighlight
                        ? "rgba(254, 243, 199, 0.6)"
                        : isStandaloneHighlight
                          ? "rgba(254, 240, 138, 0.38)"
                          : undefined,
                    }}
                    title={`${isStandaloneHighlight ? "高亮片段" : "定位问答"}：${highlight.selectedText}`}
                    aria-label={isStandaloneHighlight ? "定位高亮片段" : "定位划词问答"}
                  >
                    <span
                      className={cn(
                        "pointer-events-none absolute inset-x-[1px] bottom-[-3px] rounded-full transition-shadow duration-150",
                        isAiMatchedHighlight || isStandaloneHighlight
                          ? "h-[1.5px] bg-amber-600/95 shadow-[0_3px_8px_-5px_rgba(180,83,9,0.85)]"
                          : "h-px bg-amber-400/65 shadow-[0_2px_6px_-5px_rgba(180,83,9,0.65)] group-hover:bg-amber-500/75"
                      )}
                    />
                  </button>
                );
              })}
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
              <div className="inline-flex items-center gap-1 rounded-full border border-slate-200/90 bg-white/96 p-1 text-xs font-medium text-slate-700 shadow-[0_18px_42px_-24px_rgba(15,23,42,0.85)] backdrop-blur dark:border-slate-700 dark:bg-slate-950/95 dark:text-slate-300 dark:shadow-[0_18px_42px_-24px_rgba(0,0,0,0.9)]">
                <button
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={highlightSelectedText}
                  className="group inline-flex h-8 items-center gap-1.5 rounded-full px-2 pr-2.5 transition hover:bg-amber-50 hover:text-amber-700 dark:hover:bg-amber-500/10 dark:hover:text-amber-200"
                  title="高亮选中内容"
                  aria-label="高亮选中内容"
                >
                  <Highlighter className="h-3.5 w-3.5" />
                  高亮
                </button>
                <span className="h-5 w-px bg-slate-200 dark:bg-slate-700" aria-hidden="true" />
                <button
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={openCommentComposer}
                  className="group inline-flex h-8 items-center gap-1.5 rounded-full px-2 pr-2.5 transition hover:bg-indigo-50 hover:text-indigo-700 dark:hover:bg-indigo-500/10 dark:hover:text-indigo-300"
                  title="基于选中内容问问 AI"
                  aria-label="基于选中内容问问 AI"
                >
                  <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-slate-900 text-white shadow-sm transition group-hover:bg-indigo-600">
                    <Sparkles className="h-3 w-3" />
                  </span>
                  问问 AI
                </button>
                <span className="h-5 w-px bg-slate-200 dark:bg-slate-700" aria-hidden="true" />
                <button
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={openInteractiveComposer}
                  className="group inline-flex h-8 items-center gap-1.5 rounded-full px-2 pr-2.5 transition hover:bg-emerald-50 hover:text-emerald-700 dark:hover:bg-emerald-500/10 dark:hover:text-emerald-300"
                  title="基于选中内容生成交互演示"
                  aria-label="基于选中内容生成交互演示"
                >
                  <SlidersHorizontal className="h-3.5 w-3.5" />
                  生成交互
                </button>
              </div>
            </div>
          )}
          {floatingInteractive && (
            <div
              ref={floatingRef}
              className="absolute z-50 w-[min(360px,calc(100vw-32px))] rounded-2xl border border-slate-200/90 bg-white p-3 shadow-[0_24px_64px_-28px_rgba(15,23,42,0.9)] dark:border-slate-700 dark:bg-slate-950"
              style={{
                top: floatingInteractive.top,
                left: floatingInteractive.left,
              }}
              onMouseDown={(e) => e.stopPropagation()}
              onMouseUp={(e) => e.stopPropagation()}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">生成交互演示</p>
                  <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                    {floatingInteractive.selectedText}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={cancelInteractiveComposer}
                  disabled={isGeneratingInteractive}
                  className="shrink-0 rounded-full px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                >
                  取消
                </button>
              </div>
              <textarea
                value={interactivePrompt}
                onChange={(event) => setInteractivePrompt(event.target.value)}
                disabled={isGeneratingInteractive}
                rows={3}
                maxLength={1000}
                placeholder="可选：输入你想要的交互形式，例如用滑块演示变化、用步骤展示推导、用图形对比概念。"
                className="mt-3 w-full resize-none rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-800 outline-none transition focus:border-emerald-300 focus:bg-white focus:ring-2 focus:ring-emerald-100 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-emerald-500/50 dark:focus:bg-slate-950 dark:focus:ring-emerald-500/10"
              />
              {interactiveError && (
                <p className="mt-2 text-xs leading-5 text-red-600 dark:text-red-300">{interactiveError}</p>
              )}
              <div className="mt-3 flex items-center justify-between gap-3">
                <span className="text-[11px] text-slate-400 dark:text-slate-500">会添加到当前章节下方</span>
                <button
                  type="button"
                  onClick={submitInteractiveComposer}
                  disabled={isGeneratingInteractive}
                  className="inline-flex h-9 items-center gap-2 rounded-full bg-slate-900 px-3 text-xs font-semibold text-white shadow-sm transition hover:bg-emerald-600 disabled:cursor-wait disabled:opacity-70 dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-emerald-200"
                >
                  {isGeneratingInteractive ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <SlidersHorizontal className="h-3.5 w-3.5" />}
                  {isGeneratingInteractive ? "生成中..." : "生成"}
                </button>
              </div>
            </div>
          )}
        </div>
        </div>
      </div>

      </div>

      {showFloatingActions && isCardsPanelOpen && (
        <div className="fixed bottom-[17.75rem] right-6 z-[87] flex max-h-[min(30rem,calc(100dvh-10rem))] w-[min(24rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl border border-slate-200/90 bg-white/96 shadow-[0_22px_60px_-32px_rgba(15,23,42,0.42)] backdrop-blur-xl dark:border-slate-800 dark:bg-slate-950/96 dark:shadow-[0_24px_64px_-28px_rgba(0,0,0,0.9)]">
          <div className="flex items-start justify-between gap-3 border-b border-slate-200/80 px-4 py-3 dark:border-slate-800">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">知识卡片</p>
              <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                从当前知识文档整理正反面复习卡。
              </p>
            </div>
            <button
              type="button"
              onClick={exportKnowledgeCards}
              disabled={!cardsGenerated || knowledgeCards.length === 0}
              className={cn(
                "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium transition",
                !cardsGenerated || knowledgeCards.length === 0
                  ? "cursor-not-allowed bg-slate-100 text-slate-300 dark:bg-slate-800 dark:text-slate-600"
                  : "bg-slate-900 text-white hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200"
              )}
            >
              <Download className="h-3.5 w-3.5" />
              导出
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            {!cardsGenerated ? (
              <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-center dark:border-slate-800 dark:bg-slate-900">
                <p className="text-sm font-medium text-slate-700 dark:text-slate-200">文档生成后再整理卡片</p>
                <p className="mx-auto mt-1 max-w-[18rem] text-xs leading-5 text-slate-500 dark:text-slate-400">
                  会按章节标题和重点段落提取正面问题、背面答案和来源。
                </p>
                <button
                  type="button"
                  onClick={generateKnowledgeCards}
                  className="mt-4 inline-flex h-9 items-center gap-2 rounded-lg bg-slate-900 px-3 text-xs font-semibold text-white transition hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-slate-200"
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  生成知识卡片
                </button>
              </div>
            ) : knowledgeCards.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
                当前文档还没有足够稳定的知识点可生成卡片。
              </div>
            ) : (
              <div className="space-y-2.5">
                {knowledgeCards.slice(0, 10).map((card) => (
                  <div
                    key={card.id}
                    className="overflow-hidden rounded-xl border border-slate-200/90 bg-white text-left shadow-sm dark:border-slate-800 dark:bg-slate-900/80"
                  >
                    <div className="border-b border-slate-100 bg-slate-50/80 px-3 py-2 dark:border-slate-800 dark:bg-slate-950/50">
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">正面</p>
                      <p className="mt-1 text-sm font-semibold leading-5 text-slate-900 dark:text-slate-100">{card.front}</p>
                    </div>
                    <div className="px-3 py-2.5">
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">背面</p>
                      <div className="mt-1 max-h-[7.5rem] overflow-hidden text-xs leading-5 text-slate-600 dark:text-slate-300 [&_.katex]:text-[1em] [&_li]:my-0 [&_ol]:my-1 [&_p]:my-0 [&_p]:text-xs [&_p]:leading-5 [&_strong]:font-semibold [&_ul]:my-1">
                        <MarkdownViewer content={card.back} variant="default" />
                      </div>
                      <p className="mt-2 truncate rounded-full bg-slate-100 px-2 py-1 text-[11px] text-slate-500 dark:bg-slate-800 dark:text-slate-400">{card.source}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {showFloatingActions && (
        <button
          type="button"
          onClick={() => {
            setIsCardsPanelOpen((prev) => !prev);
          }}
          className={cn(
            "fixed bottom-[10.5rem] right-6 z-[88] inline-flex h-10 w-10 items-center justify-center gap-2 rounded-xl border border-slate-200/70 bg-white/90 text-[13px] font-medium text-slate-700 shadow-[0_12px_32px_-24px_rgba(15,23,42,0.55)] backdrop-blur-md transition duration-200 hover:-translate-y-0.5 hover:border-slate-300 hover:bg-white hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/30 active:translate-y-0 active:scale-[0.98] sm:w-[9.25rem] sm:justify-start sm:px-3 dark:border-slate-800/80 dark:bg-slate-950/88 dark:text-slate-300 dark:shadow-[0_18px_44px_-28px_rgba(0,0,0,0.9)] dark:hover:border-slate-700 dark:hover:bg-slate-950 dark:hover:text-slate-100",
            isCardsPanelOpen && "border-indigo-200 bg-indigo-50/95 text-indigo-700 shadow-[0_14px_34px_-22px_rgba(79,70,229,0.45)] dark:border-indigo-500/40 dark:bg-indigo-500/12 dark:text-indigo-200"
          )}
          aria-label="打开知识卡片"
          aria-expanded={isCardsPanelOpen}
        >
          <Layers3 className="h-4 w-4 shrink-0" />
          <span className="hidden truncate sm:inline">知识卡片</span>
        </button>
      )}

      {showFloatingActions && (
        <button
          type="button"
          onClick={() => {
            updateViewPrefs((prev) => ({ ...prev, widePage: !prev.widePage }));
          }}
          className={cn(
            "fixed bottom-[7.5rem] right-6 z-[88] inline-flex h-10 w-10 items-center justify-center gap-2 rounded-xl border border-slate-200/70 bg-white/90 text-[13px] font-medium text-slate-700 shadow-[0_12px_32px_-24px_rgba(15,23,42,0.55)] backdrop-blur-md transition duration-200 hover:-translate-y-0.5 hover:border-slate-300 hover:bg-white hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/30 active:translate-y-0 active:scale-[0.98] sm:w-[9.25rem] sm:justify-start sm:px-3 dark:border-slate-800/80 dark:bg-slate-950/88 dark:text-slate-300 dark:shadow-[0_18px_44px_-28px_rgba(0,0,0,0.9)] dark:hover:border-slate-700 dark:hover:bg-slate-950 dark:hover:text-slate-100",
            pageWideMode && "border-indigo-200 bg-indigo-50/95 text-indigo-700 shadow-[0_14px_34px_-22px_rgba(79,70,229,0.45)] dark:border-indigo-500/40 dark:bg-indigo-500/12 dark:text-indigo-200"
          )}
          aria-label={pageWideMode ? "关闭宽页模式" : "开启宽页模式"}
          aria-pressed={pageWideMode}
        >
          <ExternalLink className="h-4 w-4 shrink-0" />
          <span className="hidden truncate sm:inline">{pageWideMode ? "标准宽度" : "宽页模式"}</span>
        </button>
      )}

      {/* Graph Floating Button */}
      {showFloatingActions && (
        <button
          type="button"
          onClick={openGraphPanel}
          className={cn(
            "fixed bottom-[4.5rem] right-6 z-[86] inline-flex h-10 w-10 items-center justify-center gap-2 rounded-xl border border-slate-200/70 bg-white/90 text-[13px] font-medium text-slate-700 shadow-[0_12px_32px_-24px_rgba(15,23,42,0.55)] backdrop-blur-md transition duration-200 hover:-translate-y-0.5 hover:border-slate-300 hover:bg-white hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/30 active:translate-y-0 active:scale-[0.98] sm:w-[9.25rem] sm:justify-start sm:px-3 dark:border-slate-800/80 dark:bg-slate-950/88 dark:text-slate-300 dark:shadow-[0_18px_44px_-28px_rgba(0,0,0,0.9)] dark:hover:border-slate-700 dark:hover:bg-slate-950 dark:hover:text-slate-100",
            isGraphDrawerOpen ? "pointer-events-none translate-y-4 opacity-0" : "translate-y-0 opacity-100"
          )}
          aria-label="打开知识图谱"
        >
          <Network className="h-4 w-4 shrink-0 text-slate-500 dark:text-slate-400" />
          <span className="hidden truncate sm:inline">知识图谱</span>
        </button>
      )}

      {/* Graph Drawer Panel */}
      <div
        ref={graphDrawerRef}
        className={cn(
          "fixed bottom-0 right-0 top-0 z-[110] flex w-screen border-l border-zinc-200/80 bg-slate-50 shadow-[0_0_40px_rgba(0,0,0,0.15)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_0_44px_rgba(0,0,0,0.55)] lg:z-[84] lg:w-[var(--graph-panel-width)]",
          isGraphDrawerOpen && courseId ? "translate-x-0 pointer-events-auto" : "translate-x-full pointer-events-none",
          !isGraphDragging && "transition-transform duration-300 ease-[cubic-bezier(0.2,0.8,0.2,1)]"
        )}
        style={{
          "--graph-panel-width": `${graphPanelWidth}px`,
          willChange: isGraphDragging ? "width" : undefined,
        } as CSSProperties}
      >
        <div
          className={cn(
            "absolute bottom-0 left-0 top-0 z-50 -ml-[1px] hidden w-2 cursor-col-resize transition-colors hover:bg-indigo-500/30 lg:block",
            isGraphDragging && "bg-indigo-500/30"
          )}
          onMouseDown={handleGraphMouseDown}
        />
        <div className="relative flex h-full w-full flex-1 flex-col overflow-hidden bg-slate-50 shadow-inner dark:bg-slate-950">
          {courseId && isGraphDrawerOpen && (
            <Suspense fallback={<GraphPanelFallback />}>
              <KnowledgeGraphSidePanel
                courseId={courseId}
                onClose={closeGraphPanel}
                onSourceRefClick={handleGraphSourceRefClick}
              />
            </Suspense>
          )}
        </div>
      </div>


    </div>
  );
}
