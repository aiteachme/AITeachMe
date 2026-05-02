/* ------------------------------------------------------------------ */
/*  Knowledge Docs — Shared Utility Functions                          */
/* ------------------------------------------------------------------ */

import type {
  TocItem,
  TocTreeNode,
  CommentThreadView,
  CommentThreadLayout,
  CommentThreadLayoutResult,
  DocGenBuildStatus,
} from "./types";

/* ---- Constants ---- */

export const ACTIVE_DOC_BUILD_STATUSES = new Set(["accepted", "running", "publishing"]);
export const TERMINAL_DOC_BUILD_READY_STATUSES = new Set(["completed", "partial_failed", "skipped"]);

export const DOC_BUILD_STAGE_PROGRESS: Record<string, number> = {
  build_accepted: 8,
  planner_confirmed: 16,
  prepare_shared: 24,
  preparing_docgen_global_seed: 28,
  preparing_docgen_context: 30,
  dispatch_ready: 34,
  backbone_seed_ready: 36,
  building_document_backbone: 38,
  preparing_chapter_execution_briefs: 42,
  generating_chapters: 46,
  enhancing_chapters: 62,
  chapters_enhanced: 72,
  reviewing_content: 76,
  content_reviewed: 80,
  repairing_or_routing: 82,
  repair_routed: 84,
  merge_reviewed: 86,
  titles_finalized: 88,
  doc_lane_staged: 90,
  docgen_finalized: 94,
  graph_ready: 96,
  publishing: 94,
  completed: 100,
};

export const DOC_BUILD_STAGE_TEXT: Record<string, string> = {
  build_accepted: "已接收知识构建请求",
  planner_confirmed: "已读取确认方案",
  prepare_shared: "正在分析材料结构与内容画像",
  preparing_docgen_global_seed: "正在准备全局写作种子与文件摘要",
  preparing_docgen_context: "正在增强大纲、识别写法并摘要材料",
  dispatch_ready: "正在收口章节执行计划",
  backbone_seed_ready: "章节标题与骨架 seed 已确认",
  building_document_backbone: "正在构建整本文档知识骨架",
  preparing_chapter_execution_briefs: "正在并行准备章节执行 brief",
  generating_chapters: "正在并行研究并生成章节",
  enhancing_chapters: "正在增强章节图示、例题和小结",
  chapters_enhanced: "章节增强已完成",
  reviewing_content: "正在复核章节覆盖和证据",
  content_reviewed: "内容复核已完成",
  repairing_or_routing: "正在记录复核回流建议",
  repair_routed: "复核回流建议已记录",
  merge_reviewed: "整本文档检查完成，准备标题收口",
  titles_finalized: "章节标题已收口，准备发布",
  doc_lane_staged: "文档草稿已生成，正在发布正式版",
  docgen_finalized: "知识文档已发布",
  graph_ready: "知识图谱已就绪",
  publishing: "正在发布正式版知识文档",
  completed: "最新知识文档已发布",
};

export const COMPACT_PANEL_BREAKPOINT = 1536;
export const THREAD_HISTORY_PAGE_SIZE = 100;

/* ---- Formatters ---- */

export function formatTime(ts: number): string {
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function parseIsoTimestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

export function formatDocTimestamp(value: string | null | undefined): string | null {
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

export function formatFileSize(value?: number | null): string | null {
  if (!value || value <= 0) return null;
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

export function formatBuildEventTime(value?: string | null): string | null {
  if (!value) return null;
  const time = new Date(value);
  if (Number.isNaN(time.getTime())) return null;
  return time.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function normalizeDomainLabel(input: string): string {
  try {
    const hostname = new URL(input).hostname.replace(/^www\./, "");
    return hostname || input;
  } catch {
    return input.replace(/^https?:\/\//, "").split("/")[0] || input;
  }
}

export function cleanKnowledgeMarkdownForDisplay(markdown: string): string {
  return repairMalformedMermaidFencesForRender(String(markdown ?? ""))
    .replace(/\s*\{#ku_[A-Za-z0-9_-]+\}/g, "")
    .replace(/\s*<!--\s*ATM_KU:\s*ku_[A-Za-z0-9_-]+\s*-->/g, "")
    .replace(/[ \t]+\n/g, "\n");
}

function isMarkdownBoundary(line: string): boolean {
  return /^(#{1,6}\s+\S|[-*+]\s+\S|\d+\.\s+\S|>\s*\S|\|.+\||---\s*$)/.test(line.trim());
}

function isIndentedContextEcho(line: string): boolean {
  if (!/^( {4,}|\t)/.test(line)) return false;
  const trimmed = line.trim();
  return Boolean(trimmed) && (
    trimmed.startsWith("#") ||
    trimmed.startsWith("**") ||
    trimmed.startsWith(">") ||
    trimmed.startsWith("|") ||
    trimmed.length > 18
  );
}

function looksLikeMermaidLine(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed) return true;
  if (/^(mindmap|graph|flowchart|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|gantt|pie|journey|timeline|gitGraph)\b/i.test(trimmed)) return true;
  if (/^\s/.test(line)) return true;
  return /-->|---|==>|\||\[|\]|\(|\)|\{|\}/.test(trimmed);
}

function isMalformedMermaidFence(line: string): boolean {
  const match = line.match(/^\s*```\s*(.+)$/);
  return Boolean(match?.[1] && looksLikeMermaidLine(match[1]));
}

function malformedMermaidFenceBody(line: string): string | null {
  const match = line.match(/^\s*```\s*(.+)$/);
  const body = match?.[1]?.trim() ?? "";
  return body && looksLikeMermaidLine(body) ? body : null;
}

function splitStuckMathFences(markdown: string): string {
  return markdown.replace(/^(\s*)\$\$[ \t]*(```[ \t]*[A-Za-z0-9_-]*[ \t]*)$/gm, (_match, prefix: string, fence: string) => {
    return `${prefix}$$\n${prefix}${String(fence).trimEnd()}`;
  });
}

/**
 * ReactMarkdown parses fenced code before our `code` renderer runs.
 * If DocGen outputs a malformed Mermaid fence, the parser may swallow
 * following headings into one giant code block. This is a frontend-only
 * render guard: it normalizes broken Mermaid fences before Markdown parse.
 */
function repairMalformedMermaidFencesForRender(markdown: string): string {
  const normalizedMarkdown = splitStuckMathFences(markdown);
  if (!normalizedMarkdown.includes("```")) return normalizedMarkdown;

  const lines = normalizedMarkdown.replace(/\r\n?/g, "\n").split("\n");
  const output: string[] = [];
  let inMermaid = false;
  let afterMermaidClose = false;
  let skippingArtifact = false;
  let mermaidLines: string[] = [];

  const flushMermaid = () => {
    while (mermaidLines.length > 0 && !mermaidLines[0].trim()) mermaidLines.shift();
    while (mermaidLines.length > 0 && !mermaidLines[mermaidLines.length - 1].trim()) mermaidLines.pop();
    if (mermaidLines.length > 0) {
      if (
        !/^(mindmap|graph|flowchart|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|gantt|pie|journey|timeline|gitGraph)\b/i.test(mermaidLines[0].trim()) &&
        mermaidLines.some((line) => /-->|==>/.test(line))
      ) {
        mermaidLines.unshift("flowchart TD");
      }
      output.push("```mermaid", ...mermaidLines, "```");
    }
    mermaidLines = [];
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();

    if (skippingArtifact) {
      if (!trimmed) continue;
      if (isIndentedContextEcho(line) || isMalformedMermaidFence(line)) continue;
      if (trimmed.startsWith("```")) {
        skippingArtifact = false;
        afterMermaidClose = false;
        continue;
      }
      if (isMarkdownBoundary(line)) {
        skippingArtifact = false;
        afterMermaidClose = false;
        index -= 1;
        continue;
      }
      continue;
    }

    if (!inMermaid) {
      if (afterMermaidClose) {
        if (isIndentedContextEcho(line) || isMalformedMermaidFence(line)) {
          skippingArtifact = true;
          continue;
        }
        afterMermaidClose = false;
      }

      const start = line.match(/^\s*```\s*(mermaid|mindmap|graph|flowchart|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|gantt|pie|journey|timeline|gitGraph)\s*$/i);
      if (start?.[1]) {
        const lang = start[1];
        inMermaid = true;
        mermaidLines = lang.toLowerCase() === "mermaid" ? [] : [lang];
        continue;
      }

      const malformedBody = malformedMermaidFenceBody(line);
      if (malformedBody) {
        inMermaid = true;
        mermaidLines = [malformedBody];
        continue;
      }

      output.push(line);
      continue;
    }

    if (trimmed.startsWith("```")) {
      flushMermaid();
      inMermaid = false;
      afterMermaidClose = true;
      continue;
    }

    if (mermaidLines.length > 0 && isMarkdownBoundary(line)) {
      flushMermaid();
      inMermaid = false;
      afterMermaidClose = false;
      index -= 1;
      continue;
    }

    if (mermaidLines.length > 0 && !looksLikeMermaidLine(line)) {
      flushMermaid();
      inMermaid = false;
      afterMermaidClose = false;
      index -= 1;
      continue;
    }

    mermaidLines.push(line.replace(/^(>\s*)+/, "").trimEnd());
  }

  if (inMermaid) flushMermaid();
  return output.join("\n");
}

/* ---- Markdown Helpers ---- */

export function extractFirstMarkdownHeading(markdown: string): string | null {
  const lines = markdown.split(/\r?\n/);
  for (const line of lines) {
    const match = line.match(/^#\s+(.+?)\s*$/);
    if (match?.[1]?.trim()) {
      return match[1].trim();
    }
  }
  return null;
}

export function extractFirstMarkdownParagraph(markdown: string): string | null {
  const lines = markdown.split(/\r?\n/);
  let buffer = "";
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      if (buffer) break;
      continue;
    }
    if (line.startsWith("#") || line.startsWith(">") || line.startsWith("```")) {
      if (buffer) break;
      continue;
    }
    buffer = buffer ? `${buffer} ${line}` : line;
    if (buffer.length >= 120) break;
  }
  return buffer.trim() || null;
}

/* ---- TOC Helpers ---- */

export function tocEqual(a: TocItem[], b: TocItem[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i].id !== b[i].id || a[i].text !== b[i].text || a[i].level !== b[i].level) {
      return false;
    }
  }
  return true;
}

export function buildTocTree(items: TocItem[]): TocTreeNode[] {
  const roots: TocTreeNode[] = [];
  const stack: TocTreeNode[] = [];
  for (const item of items) {
    const node: TocTreeNode = { item, children: [] };
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

export function findAncestorIds(roots: TocTreeNode[], targetId: string): string[] {
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

/* ---- Build Status Helpers ---- */

export function resolveDocBuildStatusText(
  build: DocGenBuildStatus | null | undefined,
  hasLiveVersion: boolean,
  hasDraftVersion: boolean,
): string {
  if (!build || build.status === "idle") {
    if (hasLiveVersion) return "当前显示已发布的正式版知识文档";
    return "等待发起新的知识文档构建";
  }
  const status = build.status ?? "";
  if (status === "partial_failed") {
    return build.error_message?.trim() ? `图谱失败：${build.error_message}` : "知识文档已发布，但图谱构建失败";
  }
  if (status === "failed") {
    return build.error_message?.trim() ? `构建失败：${build.error_message}` : "知识构建失败，请稍后重试";
  }
  if (status === "cancelled") return "本轮知识构建已取消";
  if (status === "skipped") return build.current_stage_description?.trim() || "本轮图谱步骤已跳过";
  if (TERMINAL_DOC_BUILD_READY_STATUSES.has(status)) {
    return hasLiveVersion ? "最新知识文档已发布" : "构建已完成，正在同步正式文档";
  }
  const stage = build.stage?.trim();
  if (stage && DOC_BUILD_STAGE_TEXT[stage]) return DOC_BUILD_STAGE_TEXT[stage];
  if (hasDraftVersion && !hasLiveVersion) {
    return "本轮草稿已生成，正在发布正式文档";
  }
  if (hasLiveVersion) return "正在更新知识文档";
  return "正在生成知识文档";
}

export function resolveDocBuildProgressFloor(
  build: DocGenBuildStatus | null | undefined,
  hasDraftVersion: boolean,
  hasLiveVersion = false,
): number {
  if (!build || build.status === "idle") return hasDraftVersion ? 62 : 0;
  const status = build.status ?? "";
  if (TERMINAL_DOC_BUILD_READY_STATUSES.has(status)) return hasLiveVersion ? 100 : 97;
  const stage = build.stage?.trim();
  if (stage && DOC_BUILD_STAGE_PROGRESS[stage] !== undefined) return DOC_BUILD_STAGE_PROGRESS[stage];
  if (hasDraftVersion || build.draft_available) return 62;
  return 8;
}

/* ---- File Helpers ---- */

export function resolveFileProcessingLabel(file: { error_message?: string | null; digest_current_step?: string | null; markdown_ready?: boolean; asset_ready?: boolean; ingest_status?: string | null; status?: string }): string {
  if (file.error_message?.trim()) return "处理失败";
  if (file.digest_current_step?.trim()) return `已进入 ${file.digest_current_step.trim()}`;
  if (file.markdown_ready) return file.asset_ready ? "已完成解析与素材抽取" : "已完成正文解析";
  if (file.ingest_status?.trim()) {
    switch (file.ingest_status.trim()) {
      case "classifying": return "正在识别文档类型";
      case "fast_parsing":
      case "parsing": return "正在提取正文与结构";
      case "enhancing": return "正在做公式、图片和结构增强";
      case "ready_for_digest": return "已准备进入知识构建";
      default: return `处理中：${file.ingest_status.trim()}`;
    }
  }
  if (file.status === "processing") return "上传完成，正在处理";
  return "等待处理";
}

export function resolveFileProgressScore(file: { error_message?: string | null; digest_current_step?: string | null; markdown_ready?: boolean; asset_ready?: boolean; ingest_status?: string | null; status?: string }): number {
  if (file.error_message?.trim()) return 100;
  if (file.digest_current_step?.trim()) return 100;
  if (file.markdown_ready && file.asset_ready) return 92;
  if (file.markdown_ready) return 74;
  switch ((file.ingest_status ?? "").trim()) {
    case "classifying": return 24;
    case "fast_parsing":
    case "parsing": return 46;
    case "enhancing": return 66;
    case "ready_for_digest": return 84;
    default: return file.status === "processing" ? 18 : 8;
  }
}

/* ---- Chapter Status ---- */

export function buildChapterStatusLabel(status: string | undefined): string {
  switch ((status ?? "").trim()) {
    case "planned": return "待执行";
    case "generating": return "写作中";
    case "generated": return "初稿完成";
    case "enhancing": return "增强中";
    case "enhanced": return "增强完成";
    case "reviewing": return "复核中";
    case "reviewed": return "复核完成";
    case "researching": return "检索中";
    case "researched": return "研究完成";
    case "drafting": return "写作中";
    case "drafted": return "草稿完成";
    case "completed": return "已完成";
    default: return status?.trim() || "进行中";
  }
}

export function chapterStatusClasses(status: string | undefined): string {
  switch ((status ?? "").trim()) {
    case "completed": return "bg-emerald-500";
    case "reviewed": return "bg-teal-500";
    case "enhanced":
    case "drafted":
    case "drafting": return "bg-blue-600";
    case "generated":
    case "enhancing":
    case "reviewing":
    case "researched":
    case "researching": return "bg-amber-500";
    default: return "bg-slate-300";
  }
}

/* ---- Comment Thread Layout ---- */

export function buildCommentThreadLayout(
  threads: CommentThreadView[],
  heightByThreadId: Map<string, number>,
  desiredTopByThreadId: Map<string, number>,
  pinnedThreadId: string | null,
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

  return { positions: result, totalHeight: totalHeight + 2 };
}

/* ---- SSE done payload ---- */

export function parseDoneSessionId(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const sessionId = (payload as { session_id?: unknown }).session_id;
  return typeof sessionId === "string" && sessionId.trim() ? sessionId : null;
}

/* ---- Record key move ---- */

export function moveRecordKey<T>(
  record: Record<string, T>,
  fromKey: string,
  toKey: string,
  merge: (incoming: T, existing: T | undefined) => T = (incoming) => incoming,
): Record<string, T> {
  if (fromKey === toKey) return record;
  if (!(fromKey in record)) return record;
  const incoming = record[fromKey];
  const existing = record[toKey];
  const nextValue = merge(incoming, existing);
  const next: Record<string, T> = { ...record, [toKey]: nextValue };
  delete next[fromKey];
  return next;
}
