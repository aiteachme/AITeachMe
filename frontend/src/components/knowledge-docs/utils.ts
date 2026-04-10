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

export const DOC_BUILD_STAGE_PROGRESS: Record<string, number> = {
  build_accepted: 8,
  prepare_shared: 24,
  doc_lane_staged: 62,
  graph_ready: 74,
  curriculum_deriving: 86,
  publishing: 94,
  completed: 100,
};

export const DOC_BUILD_STAGE_CAP: Record<string, number> = {
  build_accepted: 20,
  prepare_shared: 48,
  doc_lane_staged: 76,
  graph_ready: 86,
  curriculum_deriving: 93,
  publishing: 97,
};

export const DOC_BUILD_STAGE_TEXT: Record<string, string> = {
  build_accepted: "已接收知识构建请求",
  prepare_shared: "正在分析材料结构与内容画像",
  doc_lane_staged: "文档草稿已生成，正在等待统一发布",
  graph_ready: "知识图谱已就绪，正在推导课程结构",
  curriculum_deriving: "正在生成教学单元、主题树与先修关系",
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
  if (build.status === "failed") {
    return build.error_message?.trim() ? `构建失败：${build.error_message}` : "知识构建失败，请稍后重试";
  }
  if (build.status === "cancelled") return "本轮知识构建已取消";
  if (build.status === "completed") {
    return hasLiveVersion ? "最新知识文档已发布" : "构建已完成";
  }
  const stage = build.stage?.trim();
  if (stage && DOC_BUILD_STAGE_TEXT[stage]) return DOC_BUILD_STAGE_TEXT[stage];
  if (hasDraftVersion && !hasLiveVersion) {
    return "本轮草稿已生成，正在等待图谱与课程结构对齐";
  }
  if (hasLiveVersion) return "正在更新知识文档";
  return "正在生成知识文档";
}

export function resolveDocBuildProgressFloor(
  build: DocGenBuildStatus | null | undefined,
  hasDraftVersion: boolean,
): number {
  if (!build || build.status === "idle") return hasDraftVersion ? 62 : 0;
  if (build.status === "completed") return 100;
  const stage = build.stage?.trim();
  if (stage && DOC_BUILD_STAGE_PROGRESS[stage] !== undefined) return DOC_BUILD_STAGE_PROGRESS[stage];
  if (hasDraftVersion || build.draft_available) return 62;
  return 8;
}

export function resolveDocBuildProgressCap(
  build: DocGenBuildStatus | null | undefined,
  hasDraftVersion: boolean,
): number {
  if (!build || build.status === "idle") return hasDraftVersion ? 78 : 45;
  if (build.status === "completed") return 100;
  const stage = build.stage?.trim();
  if (stage && DOC_BUILD_STAGE_CAP[stage] !== undefined) return DOC_BUILD_STAGE_CAP[stage];
  if (hasDraftVersion || build.draft_available) return 78;
  return 45;
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
      case "ready_for_digest": return "已准备进入 digest";
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
    case "drafted":
    case "drafting": return "bg-sky-500";
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
