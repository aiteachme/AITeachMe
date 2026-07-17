import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import {
  ChatModelSelect,
  toChatRequestModel,
  useGlobalChatModelChoice,
} from "../components/chat/ChatModelSelect";
import { LibraryMarkdownViewer } from "../components/knowledge-docs/LibraryMarkdownViewer";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Clock3,
  Database,
  Download,
  FileCode,
  FileImage,
  FileText,
  FileType,
  FolderOpen,
  HardDrive,
  Highlighter,
  Loader2,
  Maximize2,
  MessageSquare,
  Minimize2,
  MoreHorizontal,
  Search,
  RefreshCw,
  Trash2,
  Upload,
  Wand2,
  X,
} from "lucide-react";

import { apiClient, getApiErrorMessage } from "../api/client";
import { useAiInteraction } from "../components/interaction/AiInteractionProvider";
import { AI_SCENE_LIBRARY_SELECTION, getLibrarySelectionSource } from "../components/interaction/types";
import { resolveFileProcessingLabel } from "../components/knowledge-docs/utils";
import { useToast } from "../components/ui/Toast";
import {
  buildImageParserUnavailableMessage,
  buildUnsupportedFilesMessage,
  FILE_ACCEPT,
  IMAGE_UPLOAD_PARSER_UNAVAILABLE_TITLE,
  partitionUploadFilesForRuntime,
} from "../lib/fileUpload";
import { patchHtmlForIframe } from "../lib/interactiveHtml";
import { cn } from "../lib/utils";
import type { FileRecord, FilesData, FilesUploadData } from "../types/files";

interface ApiResponse<T> {
  code: number;
  data: T;
}

type FileStatusFilter = "all" | "ready" | "processing" | "failed";
type FileStatusKind = Exclude<FileStatusFilter, "all">;
type FileSortKey = "updated_desc" | "name_asc" | "size_desc";

interface SelectOption<T extends string> {
  value: T;
  label: string;
}

const FILE_STATUS_FILTER_OPTIONS: Array<SelectOption<FileStatusFilter>> = [
  { value: "all", label: "全部状态" },
  { value: "ready", label: "已解析" },
  { value: "processing", label: "解析中" },
  { value: "failed", label: "失败" },
];

const FILE_SORT_OPTIONS: Array<SelectOption<FileSortKey>> = [
  { value: "updated_desc", label: "最近更新" },
  { value: "name_asc", label: "文件名 A-Z" },
  { value: "size_desc", label: "文件大小" },
];

// Backend owns the LLM timeouts; axios should not abort while generation keeps running server-side.
const LIBRARY_INTERACTIVE_API_TIMEOUT_MS = 0;

const fileNameCollator = new Intl.Collator("zh-Hans-CN", {
  numeric: true,
  sensitivity: "base",
});

async function fetchLibraryFiles(): Promise<FilesData> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "GET",
    url: "/api/v1/files",
  });
  return response.data ?? {
    course_id: null,
    total: 0,
    ready_count: 0,
    processing_count: 0,
    failed_count: 0,
    items: [],
  };
}

async function fetchLibraryFile(fileId: string): Promise<FileRecord | null> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "GET",
    url: `/api/v1/files?file_ids=${encodeURIComponent(fileId)}`,
  });
  return response.data?.items?.[0] ?? null;
}

async function uploadLibraryFiles(files: File[]): Promise<FilesUploadData> {
  const data = new FormData();
  files.forEach((file) => data.append("files", file));
  const response = await apiClient<ApiResponse<FilesUploadData>>({
    method: "POST",
    url: "/api/v1/files/upload",
    data,
    headers: { "Content-Type": "multipart/form-data" },
  });
  return response.data;
}

async function deleteLibraryFile(fileId: string): Promise<void> {
  await apiClient<ApiResponse<{ deleted_file_ids: string[] }>>({
    method: "POST",
    url: "/api/v1/files/delete",
    data: { file_id: fileId },
  });
}

async function downloadLibraryFile(fileId: string, filename: string): Promise<void> {
  const response = await apiClient<Blob>({
    method: "GET",
    url: `/api/v1/files/${fileId}/download`,
    responseType: "blob",
  });
  const url = URL.createObjectURL(response);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.includes(".") ? filename.replace(/\.[^.]+$/, ".md") : `${filename}.md`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/* ---------- Highlight types & API ---------- */

interface LibraryHighlight {
  id: number;
  file_id: string;
  selected_text: string;
  anchor_id: string | null;
  color: string;
  description?: string | null;
  interactive_html?: string | null;
  interactive_status?: "generating" | "failed" | null;
  interactive_error?: string | null;
  segments?: HighlightSegment[] | null;
  created_at: string;
}

interface HighlightSegment {
  top: number;
  left: number;
  width: number;
  height: number;
}

interface ViewportBand {
  top: number;
  bottom: number;
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

function getInteractiveHighlightStatus(highlight: LibraryHighlight): "ready" | "generating" | "failed" | null {
  if (highlight.interactive_status === "generating") return "generating";
  if (highlight.interactive_status === "failed") return "failed";
  if (highlight.interactive_html) return "ready";
  return null;
}

function isInteractiveHighlight(highlight: LibraryHighlight): boolean {
  return getInteractiveHighlightStatus(highlight) !== null;
}

function patchLibraryInteractivePreviewHtml(html: string, scale: number): string {
  const patched = patchHtmlForIframe(html);
  const safeScale = Math.max(0.45, Math.min(1, Number.isFinite(scale) ? scale : 0.72));
  const fitCss = `<style data-aiteachme-library-fit-preview>
  html {
    overflow: hidden !important;
    width: 100% !important;
    height: 100% !important;
    min-height: 0 !important;
  }
  body {
    overflow: auto !important;
    width: 100% !important;
    height: 100% !important;
    min-height: 0 !important;
    min-width: 100% !important;
    box-sizing: border-box;
    zoom: ${safeScale} !important;
    transform-origin: top left;
    overscroll-behavior: contain;
  }
</style>`;
  const fitScript = `<script data-aiteachme-library-fit-script>
(function () {
  var scale = ${JSON.stringify(safeScale)};
  function applyFit() {
    try {
      document.documentElement.style.setProperty('overflow', 'hidden', 'important');
      document.documentElement.style.setProperty('width', '100%', 'important');
      document.documentElement.style.setProperty('height', '100%', 'important');
      document.documentElement.style.setProperty('min-height', '0', 'important');
      document.documentElement.style.setProperty('min-width', '100%', 'important');
      document.body.style.setProperty('overflow', 'auto', 'important');
      document.body.style.setProperty('box-sizing', 'border-box', 'important');
      document.body.style.setProperty('zoom', String(scale), 'important');
      document.body.style.setProperty('width', '100%', 'important');
      document.body.style.setProperty('height', '100%', 'important');
      document.body.style.setProperty('min-height', '0', 'important');
      document.body.style.setProperty('min-width', '100%', 'important');
      document.body.style.setProperty('overscroll-behavior', 'contain', 'important');
    } catch (e) {}
  }
  applyFit();
  window.addEventListener('load', applyFit);
  window.setTimeout(applyFit, 120);
  window.setTimeout(applyFit, 600);
})();
</script>`;
  const withCss = (() => {
    const closingHeadIndex = patched.search(/<\/head\s*>/i);
    if (closingHeadIndex >= 0) {
      return patched.slice(0, closingHeadIndex) + `\n${fitCss}\n` + patched.slice(closingHeadIndex);
    }
    const headWithAttrs = patched.match(/<head(?:\s[^>]*)?>/i);
    if (headWithAttrs?.index !== undefined) {
      const insertPos = headWithAttrs.index + headWithAttrs[0].length;
      return patched.slice(0, insertPos) + `\n${fitCss}` + patched.slice(insertPos);
    }
    return `${fitCss}\n${patched}`;
  })();
  const closingBodyIndex = withCss.search(/<\/body\s*>/i);
  if (closingBodyIndex >= 0) {
    return withCss.slice(0, closingBodyIndex) + `\n${fitScript}\n` + withCss.slice(closingBodyIndex);
  }
  return `${withCss}\n${fitScript}`;
}

async function fetchHighlights(fileId: string): Promise<LibraryHighlight[]> {
  const response = await apiClient<ApiResponse<{ items: LibraryHighlight[] }>>({
    method: "GET",
    url: `/api/v1/files/${encodeURIComponent(fileId)}/highlights`,
  });
  return response.data?.items ?? [];
}

async function createHighlight(
  fileId: string,
  payload: { selected_text: string; anchor_id?: string; color?: string; segments?: HighlightSegment[] },
): Promise<LibraryHighlight> {
  const response = await apiClient<ApiResponse<LibraryHighlight>>({
    method: "POST",
    url: `/api/v1/files/${encodeURIComponent(fileId)}/highlights`,
    data: payload,
  });
  return response.data;
}

async function deleteHighlight(fileId: string, highlightId: number): Promise<void> {
  await apiClient<ApiResponse<{ deleted: boolean }>>({
    method: "DELETE",
    url: `/api/v1/files/${encodeURIComponent(fileId)}/highlights/${highlightId}`,
  });
}

async function generateInteractive(
  fileId: string,
  payload: {
    selected_text: string;
    description?: string;
    model?: string;
    replace_highlight_id?: number;
    segments?: HighlightSegment[];
  },
): Promise<{ html: string; highlight_id?: number | null; highlight?: LibraryHighlight | null }> {
  const response = await apiClient<ApiResponse<{ html: string; highlight_id?: number | null; highlight?: LibraryHighlight | null }>>({
    method: "POST",
    url: `/api/v1/files/${encodeURIComponent(fileId)}/interactive`,
    data: payload,
    timeout: LIBRARY_INTERACTIVE_API_TIMEOUT_MS,
  });
  return response.data;
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

function getHighlightSegmentsBounds(segments: HighlightSegment[]): {
  top: number;
  left: number;
  right: number;
  bottom: number;
} | null {
  if (segments.length === 0) return null;
  return {
    top: Math.min(...segments.map((segment) => segment.top)),
    left: Math.min(...segments.map((segment) => segment.left)),
    right: Math.max(...segments.map((segment) => segment.left + segment.width)),
    bottom: Math.max(...segments.map((segment) => segment.top + segment.height)),
  };
}

function getHighlightSegmentsDistance(a: HighlightSegment[], b: HighlightSegment[]): number {
  const boundsA = getHighlightSegmentsBounds(a);
  const boundsB = getHighlightSegmentsBounds(b);
  if (!boundsA || !boundsB) return Number.POSITIVE_INFINITY;
  const centerAX = (boundsA.left + boundsA.right) / 2;
  const centerAY = (boundsA.top + boundsA.bottom) / 2;
  const centerBX = (boundsB.left + boundsB.right) / 2;
  const centerBY = (boundsB.top + boundsB.bottom) / 2;
  return Math.hypot(centerAX - centerBX, centerAY - centerBY);
}

function chooseClosestHighlightSegments(
  candidates: HighlightSegment[][],
  preferredSegments?: HighlightSegment[] | null,
): HighlightSegment[] {
  if (candidates.length === 0) return [];
  const preferred = preferredSegments?.length ? preferredSegments : null;
  if (!preferred || candidates.length === 1) return candidates[0];
  return candidates.reduce((best, candidate) => (
    getHighlightSegmentsDistance(candidate, preferred) < getHighlightSegmentsDistance(best, preferred)
      ? candidate
      : best
  ), candidates[0]);
}

function medianNumber(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle];
}

function filterHighlightRects(rects: DOMRect[], containerRect: DOMRect, viewportBand?: ViewportBand | null): DOMRect[] {
  const candidates = rects.filter((rect) => rect.width > 1 && rect.height > 1);
  if (candidates.length === 0) return [];

  const medianHeight = medianNumber(candidates.map((rect) => rect.height)) || 18;
  const maxReasonableHeight = Math.max(96, medianHeight * 4);
  const maxReasonableWidth = Math.max(8, containerRect.width + 8);
  const bandFiltered = viewportBand
    ? candidates.filter((rect) => rect.bottom >= viewportBand.top && rect.top <= viewportBand.bottom)
    : candidates;
  const filtered = bandFiltered.filter((rect) => (
    rect.height <= maxReasonableHeight &&
    rect.width <= maxReasonableWidth
  ));

  if (filtered.length > 0) {
    return filtered;
  }

  const relaxedMaxHeight = Math.max(160, medianHeight * 8);
  return bandFiltered.filter((rect) => (
    rect.height <= relaxedMaxHeight &&
    rect.width <= maxReasonableWidth
  ));
}

function highlightSegmentsSpanTooLarge(segments: HighlightSegment[], selectedText: string): boolean {
  if (segments.length === 0) return false;
  const compactLength = createCondensedSearchText(normalizeSelectionSearchText(selectedText)).text.length;
  if (compactLength >= 400) return false;

  const top = Math.min(...segments.map((segment) => segment.top));
  const bottom = Math.max(...segments.map((segment) => segment.top + segment.height));
  const spanHeight = bottom - top;
  const medianHeight = medianNumber(segments.map((segment) => segment.height)) || 18;
  const expectedLines = Math.max(4, Math.ceil(compactLength / 24) + 3);
  const maxExpectedHeight = Math.max(180, medianHeight * expectedLines * 1.8);
  return spanHeight > maxExpectedHeight;
}

function rangeIntersectsSelector(range: Range, root: ParentNode, selector: string): boolean {
  const elements = Array.from(root.querySelectorAll(selector));
  return elements.some((element) => {
    try {
      return range.intersectsNode(element);
    } catch {
      return false;
    }
  });
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

function stripMathDelimiters(text: string): string {
  return text
    .trim()
    .replace(/^\$\$([\s\S]*?)\$\$$/u, "$1")
    .replace(/^\$([\s\S]*?)\$$/u, "$1")
    .replace(/^\\\(([\s\S]*?)\\\)$/u, "$1")
    .replace(/^\\\[([\s\S]*?)\\\]$/u, "$1")
    .trim();
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

function shouldIgnoreLibrarySelectionTextNode(textNode: Text): boolean {
  const parent = textNode.parentElement;
  if (!parent) return true;
  if (parent.closest("script, style, noscript, .katex-mathml, [hidden], [data-library-highlight-layer='true']")) {
    return true;
  }
  try {
    const style = window.getComputedStyle(parent);
    return style.display === "none" || style.visibility === "hidden";
  } catch {
    return false;
  }
}

function appendLibrarySearchTextNode(index: TextSearchIndex, textNode: Text) {
  if (shouldIgnoreLibrarySelectionTextNode(textNode)) return;
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
      appendLibrarySearchTextNode(index, rootNode as Text);
      appendVirtualSearchSeparator(index);
      continue;
    }
    const walker = document.createTreeWalker(rootNode, NodeFilter.SHOW_TEXT);
    let current = walker.nextNode();
    while (current) {
      appendLibrarySearchTextNode(index, current as Text);
      current = walker.nextNode();
    }
    appendVirtualSearchSeparator(index);
  }
  return index;
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

function formatFileSize(bytes?: number | null): string {
  if (bytes == null || !Number.isFinite(bytes)) return "未知";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value >= 10 || unitIndex === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unitIndex]}`;
}

function normalizeFileExt(filetype?: string | null): string {
  return String(filetype ?? "").trim().toLowerCase().replace(/^\./, "");
}

function fileIcon(file: Pick<FileRecord, "filetype">) {
  const ext = normalizeFileExt(file.filetype);
  if (ext === "pdf") return <FileText className="h-4 w-4 text-red-500" />;
  if (["png", "jpg", "jpeg", "webp"].includes(ext)) return <FileImage className="h-4 w-4 text-emerald-500" />;
  if (["md", "markdown"].includes(ext)) return <FileCode className="h-4 w-4 text-indigo-500" />;
  if (["docx", "doc"].includes(ext)) return <FileText className="h-4 w-4 text-indigo-500" />;
  if (["ppt", "pptx"].includes(ext)) return <FileType className="h-4 w-4 text-orange-500" />;
  return <FileText className="h-4 w-4 text-slate-400" />;
}

function getFileStatusKind(file: FileRecord): FileStatusKind {
  if (file.markdown_ready) {
    return "ready";
  }
  if (file.error_message?.trim() || file.status === "failed") {
    return "failed";
  }
  return "processing";
}

function getFileUpdatedTime(file: FileRecord): number {
  const value = Date.parse(file.latest_updated_at || file.created_at || "");
  return Number.isFinite(value) ? value : 0;
}

function statusMeta(file: FileRecord) {
  const status = getFileStatusKind(file);
  if (status === "ready") {
    return {
      label: "已解析",
      icon: <CheckCircle2 className="h-4 w-4 text-emerald-500" />,
      className: "bg-emerald-50 text-emerald-700 ring-emerald-100 dark:bg-emerald-950/30 dark:text-emerald-300 dark:ring-emerald-900/60",
    };
  }
  if (status === "failed") {
    return {
      label: "解析失败",
      icon: <AlertCircle className="h-4 w-4 text-red-500" />,
      className: "bg-red-50 text-red-700 ring-red-100 dark:bg-red-950/30 dark:text-red-300 dark:ring-red-900/60",
    };
  }
  return {
    label: resolveFileProcessingLabel(file),
    icon: <Loader2 className="h-4 w-4 animate-spin text-indigo-500" />,
    className: "bg-indigo-50 text-indigo-700 ring-indigo-100 dark:bg-indigo-950/30 dark:text-indigo-300 dark:ring-indigo-900/60",
  };
}

export function LibraryPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [uploadingNames, setUploadingNames] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<FileStatusFilter>("all");
  const [sortKey, setSortKey] = useState<FileSortKey>("updated_desc");
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [menuButtonRect, setMenuButtonRect] = useState<DOMRect | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const handleUploadFiles = useCallback(
    async (candidateFiles: File[]) => {
      const { supportedFiles, unsupportedFiles, imageParserUnavailableFiles, limitExceededMessage } =
        await partitionUploadFilesForRuntime(candidateFiles);
      const unsupportedMessage = unsupportedFiles.length
        ? buildUnsupportedFilesMessage(unsupportedFiles)
        : null;
      const imageParserUnavailableMessage = imageParserUnavailableFiles.length
        ? buildImageParserUnavailableMessage(imageParserUnavailableFiles)
        : null;
      setError(unsupportedMessage ?? imageParserUnavailableMessage ?? limitExceededMessage);
      if (unsupportedMessage) {
        toast({
          title: "文件类型暂不支持",
          description: unsupportedMessage,
          variant: "error",
        });
      }
      if (imageParserUnavailableMessage) {
        toast({
          title: IMAGE_UPLOAD_PARSER_UNAVAILABLE_TITLE,
          description: imageParserUnavailableMessage,
          variant: "error",
        });
      }
      if (limitExceededMessage) {
        toast({
          title: "上传超出限制",
          description: limitExceededMessage,
          variant: "error",
        });
        return;
      }
      if (supportedFiles.length > 0) {
        uploadMutation.mutate(supportedFiles);
      }
    },
    // uploadMutation is stable per render; toast is stable per the hook contract
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  useEffect(() => {
    const onDocumentPaste = (e: ClipboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target) return;
      // Don't intercept paste inside input / textarea — let the user paste text normally.
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable) {
        return;
      }
      const files = Array.from(e.clipboardData?.items ?? [])
        .filter((item) => item.kind === "file")
        .map((item) => item.getAsFile())
        .filter((file): file is File => file !== null);
      if (files.length === 0) return;
      e.preventDefault();
      void handleUploadFiles(files);
    };
    document.addEventListener("paste", onDocumentPaste);
    return () => document.removeEventListener("paste", onDocumentPaste);
  }, [handleUploadFiles]);

  // 点击外部关闭菜单
  useEffect(() => {
    if (!openMenuId) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpenMenuId(null);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [openMenuId]);

  const filesQuery = useQuery({
    queryKey: ["files-library"],
    queryFn: fetchLibraryFiles,
    refetchInterval: (query) => {
      const data = query.state.data as FilesData | undefined;
      return (data?.processing_count ?? 0) > 0 ? 2000 : false;
    },
  });

  const uploadMutation = useMutation({
    mutationFn: uploadLibraryFiles,
    onMutate: (files) => {
      setError(null);
      setUploadingNames(files.map((file) => file.name));
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["files-library"] });
    },
    onError: (err: unknown) => {
      setError(getApiErrorMessage(err, "资料上传失败"));
    },
    onSettled: () => {
      setUploadingNames([]);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteLibraryFile,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["files-library"] });
    },
    onError: (err: unknown) => {
      setError(getApiErrorMessage(err, "删除资料失败"));
    },
  });

  const files = filesQuery.data?.items ?? [];
  const hasFiles = files.length > 0;
  const statusCounts = useMemo<Record<FileStatusFilter, number>>(() => {
    const counts: Record<FileStatusFilter, number> = {
      all: files.length,
      ready: 0,
      processing: 0,
      failed: 0,
    };

    files.forEach((file) => {
      counts[getFileStatusKind(file)] += 1;
    });

    return counts;
  }, [files]);
  const visibleFiles = useMemo(() => {
    const keyword = searchQuery.trim().toLowerCase();
    const next = files.filter((file) => {
      if (statusFilter !== "all" && getFileStatusKind(file) !== statusFilter) {
        return false;
      }
      if (!keyword) {
        return true;
      }

      const meta = statusMeta(file);
      const searchable = [
        file.filename,
        normalizeFileExt(file.filetype),
        meta.label,
        file.error_message ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return searchable.includes(keyword);
    });

    return next.sort((a, b) => {
      if (sortKey === "name_asc") {
        return fileNameCollator.compare(a.filename, b.filename);
      }
      if (sortKey === "size_desc") {
        return (b.file_size_bytes ?? 0) - (a.file_size_bytes ?? 0);
      }
      return getFileUpdatedTime(b) - getFileUpdatedTime(a);
    });
  }, [files, searchQuery, sortKey, statusFilter]);
  const hasVisibleFiles = visibleFiles.length > 0;
  const hasActiveFilters = searchQuery.trim().length > 0 || statusFilter !== "all";
  const visibleCountLabel = visibleFiles.length === files.length ? `${files.length} 份` : `${visibleFiles.length}/${files.length} 份`;
  const libraryStats = [
    {
      label: "全部资料",
      value: filesQuery.data?.total ?? files.length,
      icon: <Database className="h-4 w-4" />,
      tone: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
    },
    {
      label: "已解析",
      value: filesQuery.data?.ready_count ?? 0,
      icon: <CheckCircle2 className="h-4 w-4" />,
      tone: "bg-emerald-50 text-emerald-600 dark:bg-emerald-950/30 dark:text-emerald-300",
    },
    {
      label: "解析中",
      value: filesQuery.data?.processing_count ?? 0,
      icon: <Clock3 className="h-4 w-4" />,
      tone: "bg-indigo-50 text-indigo-600 dark:bg-indigo-950/30 dark:text-indigo-300",
    },
    {
      label: "失败",
      value: filesQuery.data?.failed_count ?? 0,
      icon: <AlertCircle className="h-4 w-4" />,
      tone: "bg-red-50 text-red-600 dark:bg-red-950/30 dark:text-red-300",
    },
  ];

  return (
    <div className="min-h-full pb-24 sm:pb-12">
      <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 rounded-full bg-white/85 px-3 py-1 text-xs font-medium text-slate-500 ring-1 ring-slate-200/80 backdrop-blur dark:bg-slate-800/85 dark:text-slate-400 dark:ring-slate-700/80">
            <FolderOpen className="h-3.5 w-3.5" />
            我的资料库
          </div>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100 sm:text-[32px]">我的资料库</h1>
            <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
              集中查看已上传资料、解析状态和文件信息。
            </p>
          </div>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row">
          <button
            type="button"
            onClick={() => filesQuery.refetch()}
            disabled={filesQuery.isFetching}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:bg-slate-800"
          >
            <RefreshCw className={cn("h-4 w-4", filesQuery.isFetching && "animate-spin")} />
            刷新
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={FILE_ACCEPT}
            className="hidden"
            onChange={(event) => {
              const selected = Array.from(event.target.files ?? []);
              if (fileInputRef.current) fileInputRef.current.value = "";
              if (selected.length > 0) {
                void handleUploadFiles(selected);
              }
            }}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadMutation.isPending}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-4 py-3 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
          >
            {uploadMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            上传资料
          </button>
        </div>
      </div>

      <div className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {libraryStats.map((item) => (
          <div key={item.label} className="rounded-xl border border-slate-200/80 bg-white/90 px-4 py-4 shadow-sm dark:border-slate-800/80 dark:bg-slate-900/80">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-xs font-medium text-slate-500 dark:text-slate-400">{item.label}</div>
                <div className="mt-1 text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">{item.value}</div>
              </div>
              <div className={cn("flex h-9 w-9 items-center justify-center rounded-lg", item.tone)}>{item.icon}</div>
            </div>
          </div>
        ))}
      </div>

      {error ? (
        <div className="mt-5 rounded-lg border border-red-100 bg-red-50 px-4 py-3 text-sm font-medium text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
          {error}
        </div>
      ) : null}

      {uploadingNames.length > 0 ? (
        <div className="mt-5 rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-3 dark:border-indigo-900/60 dark:bg-indigo-950/30">
          <div className="flex items-center gap-2 text-sm font-medium text-indigo-700 dark:text-indigo-300">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在上传 {uploadingNames.length} 份资料
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {uploadingNames.map((name) => (
              <span key={name} className="max-w-full truncate rounded-full bg-white/80 px-3 py-1 text-xs text-indigo-700 ring-1 ring-indigo-100 dark:bg-indigo-950/50 dark:text-indigo-300 dark:ring-indigo-900/60">
                {name}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {filesQuery.isLoading ? (
        <div className="mt-10 flex min-h-[180px] items-center justify-center pb-12 sm:mt-12 sm:pb-0">
          <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在加载资料库...
          </div>
        </div>
      ) : null}

      {!filesQuery.isLoading && !hasFiles ? (
        <div className="mt-10 flex min-h-[180px] flex-col items-center justify-center px-6 pb-12 text-center sm:mt-14 sm:pb-0">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-slate-100/80 text-slate-500 dark:bg-slate-800/80 dark:text-slate-400">
            <FolderOpen className="h-5 w-5" />
          </div>
          <h2 className="mt-4 text-lg font-semibold text-slate-900 dark:text-slate-100">还没有资料</h2>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="mt-5 inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
          >
            <Upload className="h-4 w-4" />
            上传资料
          </button>
        </div>
      ) : null}

      {!filesQuery.isLoading && hasFiles ? (
        <div className="mt-6 rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="rounded-t-xl border-b border-slate-100 bg-white px-4 py-4 dark:border-slate-800 dark:bg-slate-900">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">文件列表</h2>
                <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                  搜索、筛选和排序资料，解析完成后可直接用于课程构建和提问。
                </p>
              </div>
              <div className="inline-flex w-fit shrink-0 items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs font-medium text-slate-500 dark:bg-slate-800/70 dark:text-slate-400">
                <HardDrive className="h-3.5 w-3.5" />
                {visibleCountLabel}
              </div>
            </div>

            <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
              <label className="relative block min-w-0">
                <span className="sr-only">搜索资料</span>
                <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  type="search"
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder="搜索文件名、类型或状态"
                  className="h-11 w-full rounded-xl border border-slate-200 bg-slate-50/60 pl-10 pr-10 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-slate-300 focus:bg-white focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-slate-600 dark:focus:bg-slate-900 dark:focus:ring-slate-700/60"
                />
                {searchQuery ? (
                  <button
                    type="button"
                    onClick={() => setSearchQuery("")}
                    className="absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-200/70 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                    aria-label="清空搜索"
                  >
                    <X className="h-4 w-4" />
                  </button>
                ) : null}
              </label>

              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <label className="block min-w-0">
                  <span className="sr-only">状态筛选</span>
                  <select
                    value={statusFilter}
                    onChange={(event) => setStatusFilter(event.target.value as FileStatusFilter)}
                    className="h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 outline-none transition hover:border-slate-300 focus:border-slate-300 focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:focus:ring-slate-700/60"
                  >
                    {FILE_STATUS_FILTER_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label} ({statusCounts[option.value]})
                      </option>
                    ))}
                  </select>
                </label>

                <label className="block min-w-0">
                  <span className="sr-only">排序方式</span>
                  <select
                    value={sortKey}
                    onChange={(event) => setSortKey(event.target.value as FileSortKey)}
                    className="h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 outline-none transition hover:border-slate-300 focus:border-slate-300 focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:focus:ring-slate-700/60"
                  >
                    {FILE_SORT_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
          </div>

          {hasVisibleFiles ? (
            <div className="hidden grid-cols-[minmax(0,1.7fr)_120px_170px_120px_48px] gap-4 border-b border-slate-100 bg-slate-50/80 px-4 py-3 text-xs font-medium text-slate-500 dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-400 md:grid">
              <div>文件</div>
              <div>大小</div>
              <div>状态</div>
              <div>更新时间</div>
              <div />
            </div>
          ) : null}

          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            {visibleFiles.map((file) => {
              const meta = statusMeta(file);
              return (
                <div
                  key={file.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => navigate(`/library/${encodeURIComponent(file.id)}`)}
                  onKeyDown={(event) => {
                    if (event.target !== event.currentTarget) return;
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      navigate(`/library/${encodeURIComponent(file.id)}`);
                    }
                  }}
                  className="atm-deferred-row group grid cursor-pointer gap-3 px-4 py-4 transition hover:bg-slate-50/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 dark:hover:bg-slate-800/35 dark:focus-visible:ring-slate-600 md:grid-cols-[minmax(0,1.7fr)_120px_170px_120px_48px] md:items-center md:gap-4"
                  aria-label={`查看资料 ${file.filename}`}
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-100 dark:bg-slate-800">
                      {fileIcon(file)}
                    </div>
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">{file.filename}</div>
                      <div className="mt-1 flex items-center gap-2 text-xs text-slate-400 dark:text-slate-500">
                        <span>{normalizeFileExt(file.filetype).toUpperCase() || "FILE"}</span>
                        {file.estimated_pages ? <span>{file.estimated_pages} 页</span> : null}
                        {file.image_count ? <span>{file.image_count} 图</span> : null}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center justify-between gap-3 text-sm text-slate-500 dark:text-slate-400 md:block">
                    <span className="text-xs font-medium text-slate-400 md:hidden">大小</span>
                    <span>{formatFileSize(file.file_size_bytes)}</span>
                  </div>

                  <div className="flex items-start justify-between gap-3 md:block">
                    <span className="pt-1 text-xs font-medium text-slate-400 md:hidden">状态</span>
                    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1", meta.className)} title={resolveFileProcessingLabel(file)}>
                      {meta.icon}
                      {meta.label}
                    </span>
                    {file.error_message ? <div className="mt-1 line-clamp-2 text-xs text-red-500">{file.error_message}</div> : null}
                  </div>

                  <div className="flex items-center justify-between gap-3 text-xs text-slate-400 dark:text-slate-500 md:block">
                    <span className="font-medium md:hidden">更新</span>
                    <span>{new Date(file.latest_updated_at || file.created_at).toLocaleDateString()}</span>
                  </div>

                  <div className="flex justify-end">
                    <div className="relative" ref={openMenuId === file.id ? menuRef : undefined}>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          if (openMenuId === file.id) {
                            setOpenMenuId(null);
                            setMenuButtonRect(null);
                          } else {
                            const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
                            setMenuButtonRect(rect);
                            setOpenMenuId(file.id);
                          }
                        }}
                        className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300"
                        title="更多操作"
                      >
                        <MoreHorizontal className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {!hasVisibleFiles ? (
            <div className="flex min-h-[220px] flex-col items-center justify-center px-6 py-12 text-center">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-slate-100/80 text-slate-500 dark:bg-slate-800/80 dark:text-slate-400">
                <Search className="h-5 w-5" />
              </div>
              <h2 className="mt-4 text-base font-semibold text-slate-900 dark:text-slate-100">没有匹配的资料</h2>
              <p className="mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">
                换个关键词，或切回全部状态查看完整资料库。
              </p>
              {hasActiveFilters ? (
                <button
                  type="button"
                  onClick={() => {
                    setSearchQuery("");
                    setStatusFilter("all");
                  }}
                  className="mt-5 inline-flex h-10 items-center justify-center rounded-xl border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:bg-slate-800"
                >
                  清除筛选
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Portal 渲染的下拉菜单，脱离父容器裁剪 */}
      {openMenuId &&
        createPortal(
          <div
            ref={menuRef}
            className="fixed z-[9999] w-32 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900"
            style={{
              top: menuButtonRect ? menuButtonRect.bottom + 4 : 0,
              right: menuButtonRect ? window.innerWidth - menuButtonRect.right : 0,
            }}
          >
            <button
              type="button"
              onClick={() => {
                const file = visibleFiles.find((f) => f.id === openMenuId);
                setOpenMenuId(null);
                if (file) void downloadLibraryFile(file.id, file.filename);
              }}
              className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-slate-700 transition hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              <Download className="h-4 w-4" />
              下载
            </button>
            <button
              type="button"
              onClick={() => {
                setOpenMenuId(null);
                setPendingDeleteId(openMenuId);
              }}
              className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-red-600 transition hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/30"
            >
              <Trash2 className="h-4 w-4" />
              删除
            </button>
          </div>,
          document.body,
        )}

      {pendingDeleteId &&
        createPortal(
          <div className="fixed inset-0 z-[10001] flex items-center justify-center">
            <div className="absolute inset-0 bg-black/40" onClick={() => setPendingDeleteId(null)} />
            <div className="relative z-10 mx-4 w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl dark:border-slate-700 dark:bg-slate-900">
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">确认删除</h3>
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                删除后不可恢复，确定要删除这份资料吗？
              </p>
              <div className="mt-5 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setPendingDeleteId(null)}
                  className="rounded-lg px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={() => {
                    deleteMutation.mutate(pendingDeleteId);
                    setPendingDeleteId(null);
                  }}
                  disabled={deleteMutation.isPending}
                  className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {deleteMutation.isPending ? "删除中..." : "确认删除"}
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}

export function LibraryFilePage() {
  const { fileId = "" } = useParams<{ fileId: string }>();
  const navigate = useNavigate();
  const decodedFileId = decodeURIComponent(fileId);
  const { openAiInteraction } = useAiInteraction();
  const [interactiveModel, setInteractiveModel] = useGlobalChatModelChoice();
  const { toast } = useToast();
  const contentRef = useRef<HTMLDivElement>(null);
  const markdownBodyRef = useRef<HTMLDivElement>(null);

  /* ---- file query ---- */
  const fileQuery = useQuery({
    queryKey: ["files-library-file", decodedFileId],
    queryFn: () => fetchLibraryFile(decodedFileId),
    enabled: decodedFileId.length > 0,
    refetchInterval: (query) => {
      const file = query.state.data;
      return file && getFileStatusKind(file) === "processing" ? 2000 : false;
    },
  });

  const file = fileQuery.data ?? null;
  const meta = file ? statusMeta(file) : null;
  const markdownContent = file?.markdown_content?.trim() ?? "";
  const [viewMode, setViewMode] = useState<"rendered" | "source">("rendered");
  const assetBaseUrl = file?.asset_base_url ?? null;
  const fileExt = file ? normalizeFileExt(file.filetype).toUpperCase() || "FILE" : "FILE";

  /* ========== Highlight state ========== */
  const [highlights, setHighlights] = useState<LibraryHighlight[]>([]);
  const [highlightSegmentsById, setHighlightSegmentsById] = useState<Record<number, HighlightSegment[]>>({});
  const [activeHighlightMenu, setActiveHighlightMenu] = useState<{
    visible: boolean;
    top: number;
    left: number;
    highlight: LibraryHighlight | null;
  }>({ visible: false, top: 0, left: 0, highlight: null });
  const highlightMenuRef = useRef<HTMLDivElement>(null);
  const selectedRangeRef = useRef<Range | null>(null);
  const selectedTextRef = useRef("");
  const selectionDragStartRef = useRef<{ x: number; y: number } | null>(null);
  const selectedViewportBandRef = useRef<ViewportBand | null>(null);
  const pendingInteractiveSegmentsRef = useRef<Record<string, HighlightSegment[]>>({});
  const interactivePreviewStageRef = useRef<HTMLDivElement>(null);
  const interactivePreviewFrameRef = useRef<HTMLIFrameElement>(null);
  const [interactivePreviewScale, setInteractivePreviewScale] = useState(0.72);
  const [interactivePreviewRuntimeError, setInteractivePreviewRuntimeError] = useState<string | null>(null);
  const [interactiveModal, setInteractiveModal] = useState<{
    visible: boolean;
    highlightId: number | null;
    selectedText: string;
    selectionSegments: HighlightSegment[];
    description: string;
    improvePrompt: string;
    improveFormOpen: boolean;
    loading: boolean;
    resultHtml: string | null;
    error: string | null;
    expanded: boolean;
    mode: "create" | "view";
  }>({
    visible: false,
    highlightId: null,
    selectedText: "",
    selectionSegments: [],
    description: "",
    improvePrompt: "",
    improveFormOpen: false,
    loading: false,
    resultHtml: null,
    error: null,
    expanded: false,
    mode: "create",
  });

  const segmentFromViewportRect = useCallback((rect: DOMRect): HighlightSegment => {
    const container = contentRef.current;
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
      top: rect.top - containerRect.top,
      left: rect.left - containerRect.left,
      width: Math.max(4, rect.width),
      height: Math.max(12, rect.height),
    };
  }, []);

  const captureRangeSegments = useCallback((range: Range, viewportBand?: ViewportBand | null): HighlightSegment[] => {
    const container = contentRef.current;
    if (!container) return [];
    const containerRect = container.getBoundingClientRect();

    if (markdownBodyRef.current && rangeIntersectsSelector(range, markdownBodyRef.current, ".katex")) {
      const nativeRects = filterHighlightRects(Array.from(range.getClientRects()), containerRect, viewportBand);
      if (nativeRects.length > 0) {
        return nativeRects.map(segmentFromViewportRect);
      }
    }

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
            if (range.intersectsNode(textNode) && !shouldIgnoreLibrarySelectionTextNode(textNode)) {
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
        ...filterHighlightRects(Array.from(textRange.getClientRects()), containerRect, viewportBand),
      );
    }

    const rects = textRects.length > 0
      ? textRects
      : filterHighlightRects(Array.from(range.getClientRects()), containerRect, viewportBand);

    if (rects.length === 0) {
      const rect = range.getBoundingClientRect();
      if (rect.width < 1 && rect.height < 1) {
        return [];
      }
      return [segmentFromViewportRect(rect)];
    }

    return rects.map(segmentFromViewportRect);
  }, [segmentFromViewportRect]);

  const captureElementSegments = useCallback((element: Element): HighlightSegment[] => (
    Array.from(element.getClientRects())
      .filter((rect) => rect.width > 1 && rect.height > 1)
      .map(segmentFromViewportRect)
  ), [segmentFromViewportRect]);

  const buildHighlightSegmentsFromText = useCallback((
    selectedText: string,
    preferredSegments?: HighlightSegment[] | null,
  ): HighlightSegment[] => {
    const contentRoot = markdownBodyRef.current ?? contentRef.current;
    const target = selectedText.trim();
    if (!contentRoot || !target || viewMode !== "rendered") {
      return [];
    }

    const index = buildTextSearchIndex([contentRoot]);
    const matchedSegments = findRangesForSelectedText(index, target)
      .map((range) => captureRangeSegments(range))
      .filter((segments) => segments.length > 0 && !highlightSegmentsSpanTooLarge(segments, target));
    if (matchedSegments.length > 0) {
      return chooseClosestHighlightSegments(matchedSegments, preferredSegments);
    }

    const approximateRange = findApproximateRangeForSelectedText(index, target);
    if (approximateRange) {
      const approximateSegments = captureRangeSegments(approximateRange);
      if (approximateSegments.length > 0 && !highlightSegmentsSpanTooLarge(approximateSegments, target)) {
        return approximateSegments;
      }
    }

    const normalizedTargets = Array.from(new Set([
      target,
      stripMathDelimiters(target),
    ].map((item) => createCondensedSearchText(normalizeSelectionSearchText(item)).text).filter(Boolean)));
    if (normalizedTargets.length > 0) {
      const mathCandidates = Array.from(contentRoot.querySelectorAll<HTMLElement>(".katex"));
      const matchedMathSegments: HighlightSegment[][] = [];
      for (const element of mathCandidates) {
        const elementTexts = Array.from(new Set([
          element.innerText || "",
          element.textContent || "",
          ...Array.from(element.querySelectorAll<HTMLElement>(".katex-mathml annotation")).map((item) => item.textContent || ""),
        ].map((item) => createCondensedSearchText(normalizeSelectionSearchText(stripMathDelimiters(item))).text).filter(Boolean)));
        const matched = normalizedTargets.some((normalizedTarget) => (
          elementTexts.some((normalizedElementText) => (
            normalizedElementText.includes(normalizedTarget) || normalizedTarget.includes(normalizedElementText)
          ))
        ));
        if (matched) {
          const elementSegments = captureElementSegments(element);
          if (elementSegments.length > 0) {
            matchedMathSegments.push(elementSegments);
          }
        }
      }
      if (matchedMathSegments.length > 0) {
        return chooseClosestHighlightSegments(matchedMathSegments, preferredSegments);
      }
    }

    return [];
  }, [captureElementSegments, captureRangeSegments, viewMode]);

  const refreshHighlightSegments = useCallback(() => {
    if (viewMode !== "rendered") {
      setHighlightSegmentsById({});
      return;
    }
    setHighlightSegmentsById((prev) => {
      let changed = false;
      const next: Record<number, HighlightSegment[]> = {};
      for (const highlight of highlights) {
        const storedSegments = highlight.segments?.length ? highlight.segments : [];
        const previousSegments = prev[highlight.id]?.length ? prev[highlight.id] : [];
        const isInteractive = isInteractiveHighlight(highlight);
        const preferredSegments = isInteractive
          ? storedSegments.length > 0 ? storedSegments : previousSegments
          : previousSegments.length > 0 ? previousSegments : storedSegments;
        if (isInteractive && preferredSegments.length > 0) {
          next[highlight.id] = preferredSegments;
          if (!highlightSegmentsEqual(prev[highlight.id] ?? [], preferredSegments)) {
            changed = true;
          }
          continue;
        }
        const rebuiltSegments = buildHighlightSegmentsFromText(highlight.selected_text, preferredSegments);
        const segments = rebuiltSegments.length > 0 ? rebuiltSegments : preferredSegments;
        next[highlight.id] = segments;
        if (!highlightSegmentsEqual(prev[highlight.id] ?? [], segments)) {
          changed = true;
        }
      }
      const prevKeys = Object.keys(prev);
      if (prevKeys.length !== highlights.length) {
        changed = true;
      }
      return changed ? next : prev;
    });
  }, [buildHighlightSegmentsFromText, highlights, viewMode]);

  // Load highlights when file is ready
  useEffect(() => {
    if (!decodedFileId) return;
    let cancelled = false;
    fetchHighlights(decodedFileId)
      .then((list) => {
        if (!cancelled) {
          setHighlights(list);
          setHighlightSegmentsById(() => {
            const next: Record<number, HighlightSegment[]> = {};
            for (const highlight of list) {
              if (highlight.segments?.length) {
                next[highlight.id] = highlight.segments;
              }
            }
            return next;
          });
        }
      })
      .catch(() => {
        /* ignore – highlights are optional */
      });
    return () => {
      cancelled = true;
    };
  }, [decodedFileId]);

  useEffect(() => {
    if (viewMode !== "rendered" || highlights.length === 0) {
      setHighlightSegmentsById({});
      return;
    }

    let raf = 0;
    const scheduleRefresh = () => {
      if (raf) {
        window.cancelAnimationFrame(raf);
      }
      raf = window.requestAnimationFrame(() => {
        raf = 0;
        refreshHighlightSegments();
      });
    };

    scheduleRefresh();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(scheduleRefresh) : null;
    if (observer && contentRef.current) {
      observer.observe(contentRef.current);
    }
    window.addEventListener("resize", scheduleRefresh);

    return () => {
      if (raf) {
        window.cancelAnimationFrame(raf);
      }
      observer?.disconnect();
      window.removeEventListener("resize", scheduleRefresh);
    };
  }, [highlights.length, markdownContent, refreshHighlightSegments, viewMode]);

  /* ========== Text selection & floating toolbar ========== */
  const [selectionToolbar, setSelectionToolbar] = useState<{
    visible: boolean;
    top: number;
    left: number;
    selectedText: string;
  }>({ visible: false, top: 0, left: 0, selectedText: "" });

  const selectionToolbarRef = useRef<HTMLDivElement>(null);

  const handleMarkdownPointerDown = useCallback((event: ReactMouseEvent<HTMLDivElement>) => {
    selectionDragStartRef.current = { x: event.clientX, y: event.clientY };
    selectedViewportBandRef.current = null;
  }, []);

  // Detect text selection on mouseup (rendered mode only)
  useEffect(() => {
    if (viewMode !== "rendered") return;

    const handleMouseUp = (event: MouseEvent) => {
      // Small delay so selection is settled
      requestAnimationFrame(() => {
        const sel = window.getSelection();
        const text = sel?.toString().trim();
        if (!text || text.length === 0) {
          setSelectionToolbar((prev) => (prev.visible ? { ...prev, visible: false } : prev));
          selectedRangeRef.current = null;
          selectedTextRef.current = "";
          return;
        }

        // Only show toolbar if selection is inside the content area
        const anchorNode = sel?.anchorNode;
        const markdownBody = markdownBodyRef.current;
        if (!anchorNode || !markdownBody?.contains(anchorNode)) {
          return;
        }

        const range = sel?.getRangeAt(0);
        if (!range) return;
        selectedRangeRef.current = range.cloneRange();
        selectedTextRef.current = text;
        const dragStart = selectionDragStartRef.current;
        const rangeRect = range.getBoundingClientRect();
        const minY = dragStart ? Math.min(dragStart.y, event.clientY, rangeRect.top) : rangeRect.top;
        const maxY = dragStart ? Math.max(dragStart.y, event.clientY, rangeRect.bottom) : rangeRect.bottom;
        selectedViewportBandRef.current = {
          top: Math.max(0, minY - 36),
          bottom: Math.min(window.innerHeight, maxY + 36),
        };

        const rect = range.getBoundingClientRect();
        const top = Math.max(8, rect.top - 52); // above selection
        const left = rect.left + rect.width / 2; // centered

        setSelectionToolbar({ visible: true, top, left, selectedText: text });
      });
    };

    document.addEventListener("mouseup", handleMouseUp);
    return () => document.removeEventListener("mouseup", handleMouseUp);
  }, [viewMode]);

  // Dismiss toolbar on click outside
  useEffect(() => {
    if (!selectionToolbar.visible) return;
    const handleClick = (e: MouseEvent) => {
      if (selectionToolbarRef.current && !selectionToolbarRef.current.contains(e.target as Node)) {
        setSelectionToolbar((prev) => ({ ...prev, visible: false }));
      }
    };
    // Delay to avoid catching the same click that opened the toolbar
    const timer = setTimeout(() => {
      document.addEventListener("mousedown", handleClick);
    }, 0);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("mousedown", handleClick);
    };
  }, [selectionToolbar.visible]);

  const hideSelectionToolbar = useCallback(() => {
    setSelectionToolbar((prev) => ({ ...prev, visible: false }));
  }, []);

  const closeHighlightMenu = useCallback(() => {
    setActiveHighlightMenu((prev) => ({ ...prev, visible: false }));
  }, []);

  const resetInteractiveModal = useCallback(() => {
    setInteractiveModal({
      visible: false,
      highlightId: null,
      selectedText: "",
      selectionSegments: [],
      description: "",
      improvePrompt: "",
      improveFormOpen: false,
      loading: false,
      resultHtml: null,
      error: null,
      expanded: false,
      mode: "create",
    });
  }, []);

  const closeInteractiveModal = useCallback(() => {
    resetInteractiveModal();
  }, [resetInteractiveModal]);

  const openInteractiveHighlight = useCallback((highlight: LibraryHighlight) => {
    const status = getInteractiveHighlightStatus(highlight);
    if (!status) return;
    closeHighlightMenu();
    setInteractiveModal({
      visible: true,
      highlightId: highlight.id,
      selectedText: highlight.selected_text,
      selectionSegments: highlight.segments?.length
        ? highlight.segments
        : highlightSegmentsById[highlight.id] ?? [],
      description: highlight.description ?? "",
      improvePrompt: "",
      improveFormOpen: false,
      loading: status === "generating",
      resultHtml: status === "ready" ? highlight.interactive_html ?? "" : null,
      error: status === "failed" ? highlight.interactive_error || "生成交互失败，请重新划选后再试。" : null,
      expanded: false,
      mode: "view",
    });
  }, [closeHighlightMenu, highlightSegmentsById]);

  useEffect(() => {
    if (!activeHighlightMenu.visible) return;
    const handlePointerDown = (event: MouseEvent) => {
      if (highlightMenuRef.current?.contains(event.target as Node)) {
        return;
      }
      setActiveHighlightMenu((prev) => ({ ...prev, visible: false }));
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [activeHighlightMenu.visible]);

  const handleHighlightClick = useCallback((highlight: LibraryHighlight, event: ReactMouseEvent<HTMLElement>) => {
    if (isInteractiveHighlight(highlight)) {
      openInteractiveHighlight(highlight);
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    hideSelectionToolbar();
    setActiveHighlightMenu({
      visible: true,
      top: Math.max(8, rect.bottom + 8),
      left: Math.max(8, Math.min(rect.left + rect.width / 2, window.innerWidth - 8)),
      highlight,
    });
  }, [hideSelectionToolbar, openInteractiveHighlight]);

  /* ========== Highlight actions ========== */
  const handleHighlight = useCallback(async () => {
    const text = selectionToolbar.selectedText;
    if (!text || !decodedFileId) return;
    const capturedSegments =
      selectedTextRef.current === text && selectedRangeRef.current
        ? captureRangeSegments(selectedRangeRef.current, selectedViewportBandRef.current)
        : [];
    const liveSegments = highlightSegmentsSpanTooLarge(capturedSegments, text) ? [] : capturedSegments;
    hideSelectionToolbar();
    try {
      const created = await createHighlight(decodedFileId, {
        selected_text: text,
        color: "amber",
        segments: liveSegments,
      });
      setHighlights((prev) => [...prev, created]);
      setHighlightSegmentsById((prev) => ({
        ...prev,
        [created.id]: created.segments?.length
          ? created.segments
          : liveSegments.length > 0
            ? liveSegments
            : buildHighlightSegmentsFromText(created.selected_text),
      }));
      toast({ title: "已高亮", description: "选中文本已高亮标记。" });
    } catch {
      toast({ title: "高亮失败", description: "请稍后重试。", variant: "error" });
    }
  }, [buildHighlightSegmentsFromText, captureRangeSegments, selectionToolbar.selectedText, decodedFileId, hideSelectionToolbar, toast]);

  const handleDeleteHighlight = useCallback(
    async (highlightId: number) => {
      if (!decodedFileId) return;
      if (highlightId < 0) {
        setHighlights((prev) => prev.filter((h) => h.id !== highlightId));
        setHighlightSegmentsById((prev) => {
          const next = { ...prev };
          delete next[highlightId];
          return next;
        });
        setActiveHighlightMenu((prev) => (
          prev.highlight?.id === highlightId ? { visible: false, top: 0, left: 0, highlight: null } : prev
        ));
        return;
      }
      try {
        await deleteHighlight(decodedFileId, highlightId);
        setHighlights((prev) => prev.filter((h) => h.id !== highlightId));
        setHighlightSegmentsById((prev) => {
          const next = { ...prev };
          delete next[highlightId];
          return next;
        });
        setActiveHighlightMenu((prev) => (
          prev.highlight?.id === highlightId ? { visible: false, top: 0, left: 0, highlight: null } : prev
        ));
      } catch {
        /* ignore */
      }
    },
    [decodedFileId],
  );

  /* ========== Ask AI ========== */
  const handleAskAi = useCallback(() => {
    const text = selectionToolbar.selectedText.trim();
    if (!text || !decodedFileId) return;
    const source = getLibrarySelectionSource(decodedFileId);
    hideSelectionToolbar();
    window.getSelection()?.removeAllRanges();
    openAiInteraction({
      scope: { type: "library", fileId: decodedFileId },
      scene: AI_SCENE_LIBRARY_SELECTION,
      source,
      selectedText: text,
      newSession: true,
    });
  }, [selectionToolbar.selectedText, decodedFileId, hideSelectionToolbar, openAiInteraction]);

  const openInteractiveModal = useCallback(() => {
    const text = selectionToolbar.selectedText;
    if (!text) return;
    if (selectedRangeRef.current && selectedTextRef.current !== text) {
      selectedRangeRef.current = null;
    }
    const capturedSegments =
      selectedTextRef.current === text && selectedRangeRef.current
        ? captureRangeSegments(selectedRangeRef.current, selectedViewportBandRef.current)
        : [];
    const selectionSegments = highlightSegmentsSpanTooLarge(capturedSegments, text) ? [] : capturedSegments;
    if (selectionSegments.length === 0) {
      toast({ title: "选区定位失败", description: "请重新划选内容后再生成交互。", variant: "error" });
      return;
    }
    hideSelectionToolbar();
    setInteractiveModal({
      visible: true,
      highlightId: null,
      selectedText: text,
      selectionSegments,
      description: "",
      improvePrompt: "",
      improveFormOpen: false,
      loading: false,
      resultHtml: null,
      error: null,
      expanded: false,
      mode: "create",
    });
  }, [captureRangeSegments, selectionToolbar.selectedText, hideSelectionToolbar, toast]);

  const handleGenerateInteractive = useCallback(async () => {
    if (!decodedFileId || !interactiveModal.selectedText || interactiveModal.loading) return;
    const selectedText = interactiveModal.selectedText;
    const isViewMode = interactiveModal.mode === "view";
    const currentHighlightId = interactiveModal.highlightId;
    const replaceHighlightId = isViewMode && currentHighlightId && currentHighlightId > 0
      ? currentHighlightId
      : undefined;
    const existingTempHighlightId = isViewMode && currentHighlightId && currentHighlightId < 0
      ? currentHighlightId
      : null;
    const shouldKeepModalOpen = isViewMode;
    const prompt = (isViewMode ? interactiveModal.improvePrompt : interactiveModal.description).trim();
    if (isViewMode && !prompt) {
      toast({ title: "请输入改进要求", description: "写下想调整的方向后再生成。", variant: "error" });
      return;
    }
    const description = prompt;
    const selectionSegments = interactiveModal.selectionSegments;
    const previousHtml = interactiveModal.resultHtml;
    const tempHighlightId = replaceHighlightId ? null : (existingTempHighlightId ?? -Date.now());
    if (selectionSegments.length > 0) {
      pendingInteractiveSegmentsRef.current[selectedText] = selectionSegments;
    }
    if (replaceHighlightId) {
      setHighlights((prev) => prev.map((item) => (
        item.id === replaceHighlightId
          ? {
              ...item,
              description: description || item.description,
              interactive_status: "generating",
              interactive_error: null,
            }
          : item
      )));
    } else if (tempHighlightId !== null) {
      const tempHighlight: LibraryHighlight = {
        id: tempHighlightId,
        file_id: decodedFileId,
        selected_text: selectedText,
        anchor_id: null,
        color: "sky",
        description: description || null,
        interactive_html: null,
        interactive_status: "generating",
        interactive_error: null,
        segments: selectionSegments,
        created_at: new Date().toISOString(),
      };
      setHighlights((prev) => (
        existingTempHighlightId
          ? prev.map((item) => (item.id === existingTempHighlightId ? tempHighlight : item))
          : [...prev, tempHighlight]
      ));
      setHighlightSegmentsById((prev) => ({
        ...prev,
        [tempHighlightId]: selectionSegments,
      }));
    }
    if (shouldKeepModalOpen) {
      setInteractiveModal((prev) => ({
        ...prev,
        highlightId: currentHighlightId ?? tempHighlightId,
        description: description || prev.description,
        loading: true,
        resultHtml: null,
        error: null,
        mode: "view",
      }));
      toast({ title: "已按要求开始生成", description: "完成后会更新当前交互内容。", variant: "info" });
    } else {
      resetInteractiveModal();
      toast({ title: "生成已开始", description: "生成完成后会通知，可点击划线内容查看进度。", variant: "info" });
    }
    try {
      const result = await generateInteractive(decodedFileId, {
        selected_text: selectedText,
        description: description || undefined,
        model: toChatRequestModel(interactiveModel),
        replace_highlight_id: replaceHighlightId,
        segments: selectionSegments,
      });
      if (result.highlight) {
        const nextHighlight = result.highlight;
        const savedSegments = nextHighlight.segments?.length
          ? nextHighlight.segments
          : selectionSegments.length > 0
            ? selectionSegments
            : pendingInteractiveSegmentsRef.current[selectedText] ?? [];
        const nextHighlightWithSegments: LibraryHighlight = {
          ...nextHighlight,
          segments: savedSegments,
        };
        setHighlights((prev) => [
          ...prev.filter((item) => item.id !== nextHighlight.id && item.id !== tempHighlightId),
          nextHighlightWithSegments,
        ]);
        delete pendingInteractiveSegmentsRef.current[selectedText];
        setHighlightSegmentsById((prev) => ({
          ...Object.fromEntries(
            Object.entries(prev).filter(([key]) => tempHighlightId === null || Number(key) !== tempHighlightId),
          ),
          [nextHighlight.id]: savedSegments,
        }));
        setInteractiveModal((prev) => (
          prev.visible && prev.selectedText === selectedText
            ? {
                ...prev,
                highlightId: nextHighlight.id,
                selectionSegments: savedSegments,
                description: nextHighlightWithSegments.description ?? description,
                improvePrompt: "",
                loading: false,
                resultHtml: nextHighlightWithSegments.interactive_html ?? result.html,
                error: null,
                mode: "view",
              }
            : prev
        ));
      } else {
        if (tempHighlightId !== null) {
          setHighlights((prev) => prev.map((item) => (
            item.id === tempHighlightId
              ? {
                  ...item,
                  interactive_html: result.html,
                  interactive_status: null,
                  segments: item.segments?.length ? item.segments : selectionSegments,
                }
              : item
          )));
        }
        setInteractiveModal((prev) => (
          prev.visible && prev.selectedText === selectedText
            ? {
                ...prev,
                highlightId: prev.highlightId ?? tempHighlightId,
                description,
                improvePrompt: "",
                loading: false,
                resultHtml: result.html,
                error: null,
                mode: "view",
              }
            : prev
        ));
      }
      toast({ title: "交互已生成", description: "已为选中内容生成交互内容。", variant: "success" });
    } catch (err) {
      delete pendingInteractiveSegmentsRef.current[selectedText];
      const message = getApiErrorMessage(err, "请稍后重试。");
      if (replaceHighlightId) {
        setHighlights((prev) => prev.map((item) => (
          item.id === replaceHighlightId
            ? { ...item, interactive_status: null, interactive_error: message }
            : item
        )));
      } else if (tempHighlightId !== null) {
        setHighlights((prev) => prev.map((item) => (
          item.id === tempHighlightId
            ? { ...item, interactive_status: "failed", interactive_error: message }
            : item
        )));
      }
      setInteractiveModal((prev) => (
        prev.visible && prev.selectedText === selectedText
          ? {
              ...prev,
              loading: false,
              resultHtml: replaceHighlightId ? previousHtml : prev.resultHtml,
              error: message,
              mode: "view",
            }
          : prev
      ));
      toast({ title: "生成交互失败", description: message, variant: "error" });
    }
  }, [
    decodedFileId,
    interactiveModal.highlightId,
    interactiveModal.selectedText,
    interactiveModal.selectionSegments,
    interactiveModal.description,
    interactiveModal.improvePrompt,
    interactiveModal.loading,
    interactiveModal.mode,
    interactiveModal.resultHtml,
    interactiveModel,
    resetInteractiveModal,
    toast,
  ]);

  const patchedInteractiveHtml = useMemo(
    () => (
      interactiveModal.resultHtml
        ? patchLibraryInteractivePreviewHtml(interactiveModal.resultHtml, interactivePreviewScale)
        : ""
    ),
    [interactiveModal.resultHtml, interactivePreviewScale],
  );
  const canImproveInteractive =
    interactiveModal.mode === "view" &&
    Boolean(interactiveModal.resultHtml || interactiveModal.error) &&
    !interactiveModal.loading;
  const canSubmitInteractiveImprove = interactiveModal.improvePrompt.trim().length > 0 && !interactiveModal.loading;

  useEffect(() => {
    if (!interactiveModal.visible || !interactiveModal.resultHtml) {
      setInteractivePreviewRuntimeError(null);
      return;
    }
    setInteractivePreviewRuntimeError(null);
  }, [interactiveModal.resultHtml, interactiveModal.visible]);

  useEffect(() => {
    if (!interactiveModal.visible || !interactiveModal.resultHtml) return;
    const handleMessage = (event: MessageEvent) => {
      if (event.source !== interactivePreviewFrameRef.current?.contentWindow) return;
      const data = event.data as {
        __aiteachmeInteractive?: boolean;
        kind?: string;
        errorKind?: string;
        message?: unknown;
      } | undefined;
      if (!data || data.__aiteachmeInteractive !== true || data.kind !== "runtime-error") return;
      const kind = typeof data.errorKind === "string" ? data.errorKind : "error";
      const message = typeof data.message === "string" ? data.message : String(data.message ?? "");
      setInteractivePreviewRuntimeError(`[${kind}] ${message}`);
    };
    window.addEventListener("message", handleMessage);
    window.setTimeout(() => {
      interactivePreviewFrameRef.current?.contentWindow?.postMessage({ __aiteachmeErrorReplayRequest: true }, "*");
    }, 0);
    return () => window.removeEventListener("message", handleMessage);
  }, [interactiveModal.resultHtml, interactiveModal.visible]);

  const updateInteractivePreviewScale = useCallback(() => {
    if (!interactiveModal.resultHtml) return;
    const nextScale = interactiveModal.expanded ? 0.78 : 0.68;
    setInteractivePreviewScale((prev) => {
      const scale = Number(nextScale.toFixed(3));
      return Math.abs(prev - scale) < 0.01 ? prev : scale;
    });
  }, [interactiveModal.expanded, interactiveModal.resultHtml]);

  useEffect(() => {
    if (!interactiveModal.visible || !interactiveModal.resultHtml || interactiveModal.loading) return;
    updateInteractivePreviewScale();
    const stage = interactivePreviewStageRef.current;
    const observer = typeof ResizeObserver !== "undefined" && stage
      ? new ResizeObserver(updateInteractivePreviewScale)
      : null;
    if (observer && stage) {
      observer.observe(stage);
    }
    const timers = [
      window.setTimeout(updateInteractivePreviewScale, 120),
      window.setTimeout(updateInteractivePreviewScale, 420),
      window.setTimeout(updateInteractivePreviewScale, 900),
      window.setTimeout(updateInteractivePreviewScale, 1600),
    ];
    window.addEventListener("resize", updateInteractivePreviewScale);
    return () => {
      observer?.disconnect();
      timers.forEach((timer) => window.clearTimeout(timer));
      window.removeEventListener("resize", updateInteractivePreviewScale);
    };
  }, [
    interactiveModal.expanded,
    interactiveModal.loading,
    interactiveModal.visible,
    interactiveModal.resultHtml,
    updateInteractivePreviewScale,
  ]);

  return (
    <div className="min-h-full pb-24 sm:pb-12">
      <button
        type="button"
        onClick={() => navigate("/library")}
        className="inline-flex items-center gap-2 rounded-lg px-2 py-2 text-sm font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
      >
        <ArrowLeft className="h-4 w-4" />
        返回资料库
      </button>

      {fileQuery.isLoading ? (
        <div className="mt-10 flex min-h-[260px] items-center justify-center">
          <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在加载资料...
          </div>
        </div>
      ) : null}

      {fileQuery.isError ? (
        <div className="mt-6 rounded-xl border border-red-100 bg-red-50 px-4 py-4 text-sm leading-6 text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
          {getApiErrorMessage(fileQuery.error, "资料加载失败")}
        </div>
      ) : null}

      {!fileQuery.isLoading && !fileQuery.isError && !file ? (
        <div className="mt-10 flex min-h-[260px] flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white/80 px-6 text-center dark:border-slate-800 dark:bg-slate-900/70">
          <FolderOpen className="h-8 w-8 text-slate-400" />
          <h1 className="mt-4 text-lg font-semibold text-slate-900 dark:text-slate-100">没有找到这份资料</h1>
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">它可能已经被删除，或当前资料库还没有同步完成。</p>
        </div>
      ) : null}

      {file && meta ? (
        <div className="mt-4 space-y-5">
          <section className="rounded-xl border border-slate-200 bg-white px-5 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div className="flex min-w-0 items-start gap-3">
                <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-100 dark:bg-slate-800">
                  {fileIcon(file)}
                </div>
                <div className="min-w-0">
                  <h1 className="truncate text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">{file.filename}</h1>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                    <span>{fileExt}</span>
                    <span>{formatFileSize(file.file_size_bytes)}</span>
                    {file.parser_used ? <span>{file.parser_used}</span> : null}
                    <span>更新于 {new Date(file.latest_updated_at || file.created_at).toLocaleString()}</span>
                  </div>
                </div>
              </div>
              <span className={cn("inline-flex w-fit items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1", meta.className)} title={resolveFileProcessingLabel(file)}>
                {meta.icon}
                {meta.label}
              </span>
            </div>

            <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm leading-6 text-slate-600 dark:border-slate-800 dark:bg-slate-950/35 dark:text-slate-300">
              这里展示的是系统解析出来的 Markdown 文档，用于核对入库后的正文内容；它不是原始文件预览。
            </div>

            {file.error_message ? (
              <div className="mt-4 rounded-lg border border-red-100 bg-red-50 px-3 py-3 text-sm leading-6 text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
                {file.error_message}
              </div>
            ) : null}
          </section>

          {/* Highlights list (if any) */}
          {highlights.length > 0 ? (
            <section className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
              <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">高亮标记</h3>
              <div className="mt-3 space-y-2">
                {highlights.map((h) => (
                  <div
                    key={h.id}
                    className={cn(
                      "flex items-start justify-between gap-3 rounded-lg border px-3 py-2 text-sm",
                      h.color === "sky"
                        ? "border-sky-200 bg-sky-50 dark:border-sky-800/60 dark:bg-sky-950/30"
                        : "border-amber-200 bg-amber-50 dark:border-amber-800/60 dark:bg-amber-950/30",
                    )}
                  >
                    <span className="min-w-0 flex-1 truncate text-slate-700 dark:text-slate-300">{h.selected_text}</span>
                    {isInteractiveHighlight(h) ? (
                      <button
                        type="button"
                        onClick={() => openInteractiveHighlight(h)}
                        className="shrink-0 rounded px-2 py-0.5 text-xs font-medium text-sky-700 transition hover:bg-white dark:text-sky-300 dark:hover:bg-slate-800"
                      >
                        {h.interactive_status === "generating" ? "生成中" : h.interactive_status === "failed" ? "失败" : "交互"}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => handleDeleteHighlight(h.id)}
                      className="shrink-0 rounded p-1 text-slate-400 transition hover:bg-white hover:text-red-500 dark:hover:bg-slate-800"
                      title="删除高亮"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          <section className="relative rounded-xl border border-slate-200 bg-white px-5 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-900" ref={contentRef}>
            {markdownContent ? (
              <>
                <div className="mb-4 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setViewMode("rendered")}
                    className={cn(
                      "rounded-lg px-3 py-1.5 text-sm font-medium transition",
                      viewMode === "rendered"
                        ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                        : "text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800",
                    )}
                  >
                    渲染
                  </button>
                  <button
                    type="button"
                    onClick={() => setViewMode("source")}
                    className={cn(
                      "rounded-lg px-3 py-1.5 text-sm font-medium transition",
                      viewMode === "source"
                        ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                        : "text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800",
                    )}
                  >
                    源码
                  </button>
                </div>

                {viewMode === "rendered" ? (
                  <>
                    <div ref={markdownBodyRef} onMouseDown={handleMarkdownPointerDown}>
                      <LibraryMarkdownViewer
                        content={markdownContent}
                        assetBaseUrl={assetBaseUrl ?? undefined}
                      />
                    </div>
                    <div
                      className="pointer-events-none absolute inset-0 z-20"
                      data-library-highlight-layer="true"
                    >
                      {highlights.map((highlight) => (
                        <div key={highlight.id}>
                          {(highlightSegmentsById[highlight.id] ?? []).map((segment, index) => {
                            const interactiveStatus = getInteractiveHighlightStatus(highlight);
                            const isInteractive = Boolean(interactiveStatus);
                            return (
                              <button
                                key={`${highlight.id}-${index}`}
                                type="button"
                                onClick={(event) => handleHighlightClick(highlight, event)}
                                className={cn(
                                  "pointer-events-auto absolute rounded-[2px] transition-shadow duration-150 focus-visible:outline-none focus-visible:ring-2",
                                  isInteractive
                                    ? "bg-sky-100/55 focus-visible:ring-sky-300/50"
                                    : "bg-amber-100/60 focus-visible:ring-amber-300/50",
                                )}
                                style={{
                                  top: segment.top,
                                  left: segment.left,
                                  width: segment.width,
                                  height: segment.height,
                                  backgroundColor: isInteractive
                                    ? "rgba(186, 230, 253, 0.5)"
                                    : "rgba(254, 240, 138, 0.42)",
                                }}
                                title={`${interactiveStatus === "generating" ? "交互生成中" : isInteractive ? "交互片段" : "高亮片段"}：${highlight.selected_text}`}
                                aria-label={isInteractive ? "打开交互内容" : "打开高亮菜单"}
                              >
                                <span
                                  className={cn(
                                    "pointer-events-none absolute inset-x-[1px] bottom-[-3px] h-[1.5px] rounded-full shadow-[0_2px_6px_-5px_rgba(15,23,42,0.7)]",
                                    isInteractive ? "bg-sky-600/90" : "bg-amber-600/90",
                                  )}
                                />
                              </button>
                            );
                          })}
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <pre className="whitespace-pre-wrap break-words rounded-lg border border-slate-200 bg-slate-50 p-4 font-mono text-sm leading-7 text-slate-800 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-200">
                    {markdownContent}
                  </pre>
                )}
              </>
            ) : (
              <div className="flex min-h-[260px] flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50 px-6 text-center dark:border-slate-800 dark:bg-slate-950/30">
                <FileText className="h-8 w-8 text-slate-400" />
                <h2 className="mt-4 text-base font-semibold text-slate-900 dark:text-slate-100">暂无可展示的 Markdown</h2>
                <p className="mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">
                  {getFileStatusKind(file) === "ready" ? "这份资料解析完成了，但暂时没有返回正文内容。" : "解析完成后会在这里展示完整 Markdown 文档。"}
                </p>
              </div>
            )}
          </section>
        </div>
      ) : null}

      {/* ---- Floating selection toolbar (Portal) ---- */}
      {selectionToolbar.visible &&
        createPortal(
          <div
            ref={selectionToolbarRef}
            className="fixed z-[9999] flex items-center gap-1 rounded-xl border border-slate-200 bg-white px-1.5 py-1.5 shadow-lg dark:border-slate-700 dark:bg-slate-900"
            style={{
              top: selectionToolbar.top,
              left: Math.max(8, Math.min(selectionToolbar.left, window.innerWidth - 200)),
              transform: "translateX(-50%)",
            }}
            onMouseDown={(e) => {
              // Prevent the toolbar click from clearing the selection
              e.preventDefault();
            }}
          >
            <button
              type="button"
              onClick={handleHighlight}
              className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-amber-50 hover:text-amber-700 dark:text-slate-200 dark:hover:bg-amber-950/40 dark:hover:text-amber-300"
              title="高亮"
            >
              <Highlighter className="h-3.5 w-3.5" />
              高亮
            </button>
            <button
              type="button"
              onClick={handleAskAi}
              className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-indigo-50 hover:text-indigo-700 dark:text-slate-200 dark:hover:bg-indigo-950/40 dark:hover:text-indigo-300"
              title="问问AI"
            >
              <MessageSquare className="h-3.5 w-3.5" />
              问问AI
            </button>
            <button
              type="button"
              onClick={openInteractiveModal}
              className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-violet-50 hover:text-violet-700 dark:text-slate-200 dark:hover:bg-violet-950/40 dark:hover:text-violet-300"
              title="生成交互"
            >
              <Wand2 className="h-3.5 w-3.5" />
              生成交互
            </button>
          </div>,
          document.body,
        )}

      {activeHighlightMenu.visible && activeHighlightMenu.highlight &&
        createPortal(
          <div
            ref={highlightMenuRef}
            className="fixed z-[9999] flex items-center gap-1 rounded-xl border border-slate-200 bg-white px-1.5 py-1.5 shadow-lg dark:border-slate-700 dark:bg-slate-900"
            style={{
              top: activeHighlightMenu.top,
              left: activeHighlightMenu.left,
              transform: "translateX(-50%)",
            }}
          >
            {isInteractiveHighlight(activeHighlightMenu.highlight) ? (
              <button
                type="button"
                onClick={() => openInteractiveHighlight(activeHighlightMenu.highlight!)}
                className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-sky-50 hover:text-sky-700 dark:text-slate-200 dark:hover:bg-sky-950/40 dark:hover:text-sky-300"
              >
                <Wand2 className="h-3.5 w-3.5" />
                查看交互
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => handleDeleteHighlight(activeHighlightMenu.highlight!.id)}
              className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-red-50 hover:text-red-600 dark:text-slate-200 dark:hover:bg-red-950/30 dark:hover:text-red-300"
            >
              <Trash2 className="h-3.5 w-3.5" />
              删除
            </button>
          </div>,
          document.body,
        )}

      {/* ---- Generate interaction modal (Portal) ---- */}
      {interactiveModal.visible &&
        createPortal(
          <div className={cn(
            "fixed inset-0 z-[10000] flex items-center justify-center",
            interactiveModal.expanded ? "p-0" : "p-4",
          )}>
            {/* Backdrop */}
            <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={closeInteractiveModal} />
            {/* Dialog */}
            <div className={cn(
              "relative z-10 flex min-h-0 w-full flex-col border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900",
              interactiveModal.expanded
                ? "h-screen max-h-screen max-w-none rounded-none"
                : "max-h-[88vh] max-w-5xl rounded-2xl",
            )}>
              {/* Header */}
              <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-6 py-4 dark:border-slate-800">
                <div className="min-w-0">
                  <h2 className="truncate text-base font-semibold text-slate-900 dark:text-slate-100">
                    {interactiveModal.mode === "view" ? "交互内容" : "生成交互"}
                  </h2>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {canImproveInteractive ? (
                    <button
                      type="button"
                      onClick={() => setInteractiveModal((prev) => ({
                        ...prev,
                        improveFormOpen: !prev.improveFormOpen,
                      }))}
                      className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-slate-100"
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                      {interactiveModal.improveFormOpen ? "收起改进" : "提出改进"}
                    </button>
                  ) : null}
                  {interactiveModal.mode === "view" ? (
                    <button
                      type="button"
                      onClick={() => setInteractiveModal((prev) => ({ ...prev, expanded: !prev.expanded }))}
                      className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-slate-100"
                    >
                      {interactiveModal.expanded ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
                      {interactiveModal.expanded ? "还原" : "全屏"}
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={closeInteractiveModal}
                    className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </div>

              {/* Body */}
              <div className={cn(
                "min-h-0 flex-1 overflow-y-auto overscroll-contain px-6 py-5",
                interactiveModal.expanded && "overflow-hidden px-4 py-4",
              )}>
                {interactiveModal.mode === "create" ? (
                  <div className="space-y-4">
                    <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 dark:border-slate-700 dark:bg-slate-950/40">
                      <span className="text-xs font-medium text-slate-500 dark:text-slate-400">生成模型</span>
                      <ChatModelSelect
                        value={interactiveModel}
                        onChange={setInteractiveModel}
                        disabled={interactiveModal.loading}
                      />
                    </div>
                    <label className="block">
                      <span className="text-xs font-medium text-slate-500 dark:text-slate-400">交互形式描述（可选）</span>
                      <textarea
                        value={interactiveModal.description}
                        onChange={(e) => setInteractiveModal((prev) => ({ ...prev, description: e.target.value }))}
                        disabled={interactiveModal.loading}
                        placeholder="例如：做成一个选择题练习"
                        rows={3}
                        className="mt-1.5 w-full resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-slate-300 focus:bg-white focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-slate-600 dark:focus:bg-slate-900 dark:focus:ring-slate-700/60"
                      />
                    </label>
                  </div>
                ) : null}

                {canImproveInteractive && interactiveModal.improveFormOpen ? (
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      void handleGenerateInteractive();
                    }}
                    className={cn(
                      "mt-4 rounded-xl border border-slate-200 bg-white p-3 shadow-sm dark:border-slate-800 dark:bg-slate-950",
                      interactiveModal.expanded && "mt-0",
                    )}
                  >
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
                      <label className="min-w-0 flex-1">
                        <span className="block text-xs font-medium text-slate-600 dark:text-slate-300">输入改进要求后生成</span>
                        <textarea
                          value={interactiveModal.improvePrompt}
                          onChange={(event) => setInteractiveModal((prev) => ({ ...prev, improvePrompt: event.target.value }))}
                          placeholder="例如：更像函数图；少一点文字；增加步骤切换；把对比做得更直观"
                          className="mt-2 min-h-20 w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-indigo-500/60 dark:focus:ring-indigo-500/15"
                          maxLength={1000}
                        />
                      </label>
                      <div className="flex shrink-0 flex-wrap items-center gap-2 lg:justify-end">
                        <ChatModelSelect
                          value={interactiveModel}
                          onChange={setInteractiveModel}
                          disabled={interactiveModal.loading}
                        />
                        <button
                          type="submit"
                          disabled={!canSubmitInteractiveImprove}
                          className="inline-flex h-10 items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-3 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-55"
                        >
                          <RefreshCw className="h-3.5 w-3.5" />
                          按要求生成
                        </button>
                      </div>
                    </div>
                  </form>
                ) : null}

                {/* Result HTML */}
                {interactiveModal.loading ? (
                  <div className={cn(
                    "mt-4 flex min-h-[420px] flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-400",
                    interactiveModal.expanded && "min-h-[calc(100vh-190px)]",
                  )}>
                    <div className="flex items-center">
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      正在生成交互页...
                    </div>
                    <div className="mt-2 text-xs text-slate-400 dark:text-slate-500">
                      正在选择交互类型、生成单文件 HTML 并校验预览安全边界
                    </div>
                  </div>
                ) : patchedInteractiveHtml ? (
                  <div className={cn(
                    "mt-4 overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950",
                    interactiveModal.expanded && "mt-3",
                  )}>
                    <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-3 py-2 text-xs font-medium text-slate-500 dark:border-slate-800 dark:text-slate-400">
                      <span>预览缩放 {Math.round(interactivePreviewScale * 100)}%</span>
                      <button
                        type="button"
                        onClick={() => setInteractiveModal((prev) => ({ ...prev, expanded: !prev.expanded }))}
                        className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-xs font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
                      >
                        {interactiveModal.expanded ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
                        {interactiveModal.expanded ? "还原" : "全屏展示"}
                      </button>
                    </div>
                    {interactivePreviewRuntimeError ? (
                      <div className="border-b border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800 dark:border-amber-500/25 dark:bg-amber-500/10 dark:text-amber-100">
                        交互页运行时报错：{interactivePreviewRuntimeError}
                      </div>
                    ) : null}
                    <div
                      ref={interactivePreviewStageRef}
                      className={cn(
                        "relative overflow-hidden bg-slate-50 dark:bg-slate-950",
                        interactiveModal.expanded
                          ? interactiveModal.improveFormOpen
                            ? "h-[calc(100vh-250px)] min-h-[420px]"
                            : "h-[calc(100vh-96px)] min-h-[520px]"
                          : interactiveModal.improveFormOpen
                            ? "h-[min(560px,52vh)] min-h-[340px]"
                            : "h-[min(720px,72vh)] min-h-[460px]",
                      )}
                      style={{ contain: "layout size paint", isolation: "isolate" }}
                    >
                      <iframe
                        ref={interactivePreviewFrameRef}
                        title="资料库交互预览"
                        srcDoc={patchedInteractiveHtml}
                        sandbox="allow-scripts allow-forms allow-popups"
                        scrolling="auto"
                        onLoad={updateInteractivePreviewScale}
                        className="absolute inset-0 block h-full w-full border-0 bg-white"
                      />
                    </div>
                  </div>
                ) : null}

                {/* Error */}
                {interactiveModal.error ? (
                  <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700 dark:border-red-800/60 dark:bg-red-950/30 dark:text-red-300">
                    {interactiveModal.error}
                  </div>
                ) : null}
              </div>

              {/* Footer */}
              <div className={cn(
                "flex items-center justify-end gap-3 border-t border-slate-100 px-6 py-4 dark:border-slate-800",
                interactiveModal.mode === "view" && "hidden",
              )}>
                <button
                  type="button"
                  onClick={closeInteractiveModal}
                  className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  关闭
                </button>
                {interactiveModal.mode === "create" ? (
                  <button
                    type="button"
                    onClick={handleGenerateInteractive}
                    disabled={interactiveModal.loading}
                    className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
                  >
                    {interactiveModal.loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                    生成
                  </button>
                ) : null}
              </div>
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}
