import { Children, useCallback, useEffect, useMemo, useRef, useState, type ComponentPropsWithoutRef, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import {
  BadgeCheck,
  ChevronRight,
  Info,
  Lightbulb,
  OctagonAlert,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

import { runTrackedApiFetch } from "../../api/client";
import { cn } from "../../lib/utils";
import { MermaidBlock } from "./MermaidBlock";

type MarkdownViewerVariant = "default" | "document" | "planner";
type CalloutKind = "note" | "tip" | "important" | "warning" | "caution";
type CollapsibleHeadings = boolean | readonly number[];
const CALLOUT_PATTERN = "note|tip|important|warning|caution";
const MERMAID_LANGUAGE_ALIASES = new Set(["mermaid", "maymaid", "mermaind", "mermaide"]);
const BLANK_TOKEN = "{{blank}}";
const BLANK_NODE_CLASS =
  "mx-1 inline-block h-[0.9em] min-w-16 border-b-2 border-current align-baseline";
const HIGHLIGHT_MARK_CLASS =
  "rounded-[3px] bg-amber-100 px-1 py-0.5 text-inherit shadow-[inset_0_-0.35em_rgba(251,191,36,0.22)] dark:bg-amber-300/20 dark:shadow-[inset_0_-0.35em_rgba(251,191,36,0.18)]";
const BARE_LATEX_TEXT_COMMANDS: Record<string, string> = {
  times: "×",
  cdot: "·",
  div: "÷",
  le: "≤",
  leq: "≤",
  ge: "≥",
  geq: "≥",
  neq: "≠",
  approx: "≈",
  pm: "±",
  mp: "∓",
  to: "→",
  rightarrow: "→",
  leftarrow: "←",
};
const CALLOUT_LEADING_ICON_RE =
  /^[\s\uFE0F]*(?:(?:💡|📌|🎯|🔍|🧩|🚀|✨|✅|🔥|⭐|⚠️|⚠|❗|❌|⛔|🚫|📝|🔗|📚)\s*)+/u;

type MarkdownAstNode = {
  type?: string;
  depth?: number;
  value?: string;
  children?: MarkdownAstNode[];
  data?: {
    hName?: string;
    hProperties?: Record<string, unknown>;
  };
};

interface MarkdownViewerProps {
  content: string;
  assetBaseUrl?: string;
  assetCourse?: string;
  variant?: MarkdownViewerVariant;
  headingAnchors?: boolean;
  headingNumbering?: boolean;
  collapsibleHeadings?: CollapsibleHeadings;
  collapsedHeadingIds?: ReadonlySet<string>;
  onHeadingCollapseChange?: (id: string, collapsed: boolean, source?: HTMLElement | null) => boolean | void;
}

interface ViewerStyles {
  heading: Record<number, string>;
  paragraph: string;
  list: string;
  orderedList: string;
  listItem: string;
  blockquote: string;
  codeInline: string;
  codeShell: string;
  codeLanguageBadge: string;
  codePre: string;
  tableShell: string;
  table: string;
  thead: string;
  th: string;
  td: string;
  hr: string;
  link: string;
  strong: string;
  em: string;
  highlight: string;
  imageShell: string;
  imageFrame: string;
  image: string;
  imageCaption: string;
}

type MarkdownHeadingComponentProps = ComponentPropsWithoutRef<"h1"> & {
  node?: unknown;
};

type MarkdownBlockquoteComponentProps = ComponentPropsWithoutRef<"blockquote"> & {
  node?: unknown;
};

type MarkdownSectionComponentProps = ComponentPropsWithoutRef<"section"> & {
  node?: unknown;
};

const CALLOUT_META: Record<CalloutKind, { label: string; Icon: LucideIcon }> = {
  note: { label: "提示", Icon: Info },
  tip: { label: "诀窍", Icon: Lightbulb },
  important: { label: "重点", Icon: BadgeCheck },
  warning: { label: "注意", Icon: TriangleAlert },
  caution: { label: "警告", Icon: OctagonAlert },
};

const CALLOUT_STYLES: Record<MarkdownViewerVariant, Record<CalloutKind, { shell: string; badge: string }>> = {
  default: {
    note: {
      shell: "my-4 rounded-2xl border border-blue-200 bg-blue-50/80 px-4 py-3 text-slate-700 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-slate-200",
      badge: "bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300",
    },
    tip: {
      shell: "my-4 rounded-2xl border border-emerald-200 bg-emerald-50/80 px-4 py-3 text-slate-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-slate-200",
      badge: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    },
    important: {
      shell: "my-4 rounded-2xl border border-blue-200 bg-blue-50/80 px-4 py-3 text-slate-700 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-slate-200",
      badge: "bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300",
    },
    warning: {
      shell: "my-4 rounded-2xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-slate-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-slate-200",
      badge: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
    },
    caution: {
      shell: "my-4 rounded-2xl border border-rose-200 bg-rose-50/80 px-4 py-3 text-slate-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-slate-200",
      badge: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
    },
  },
  document: {
    note: {
      shell: "my-5 rounded-lg border border-blue-200 bg-blue-50/70 px-4 py-3 text-[#1F2329] dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-slate-200",
      badge: "bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300",
    },
    tip: {
      shell: "my-5 rounded-lg border border-emerald-200 bg-emerald-50/70 px-4 py-3 text-[#1F2329] dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-slate-200",
      badge: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    },
    important: {
      shell: "my-5 rounded-lg border border-blue-200 bg-blue-50/70 px-4 py-3 text-[#1F2329] dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-slate-200",
      badge: "bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300",
    },
    warning: {
      shell: "my-5 rounded-lg border border-amber-200 bg-amber-50/70 px-4 py-3 text-[#1F2329] dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-slate-200",
      badge: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
    },
    caution: {
      shell: "my-5 rounded-lg border border-rose-200 bg-rose-50/70 px-4 py-3 text-[#1F2329] dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-slate-200",
      badge: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
    },
  },
  planner: {
    note: {
      shell: "my-4 rounded-xl border border-blue-200 bg-blue-50/70 px-4 py-3 text-zinc-700 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-slate-200",
      badge: "bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300",
    },
    tip: {
      shell: "my-4 rounded-xl border border-emerald-200 bg-emerald-50/70 px-4 py-3 text-zinc-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-slate-200",
      badge: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    },
    important: {
      shell: "my-4 rounded-xl border border-blue-200 bg-blue-50/70 px-4 py-3 text-zinc-700 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-slate-200",
      badge: "bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300",
    },
    warning: {
      shell: "my-4 rounded-xl border border-amber-200 bg-amber-50/70 px-4 py-3 text-zinc-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-slate-200",
      badge: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
    },
    caution: {
      shell: "my-4 rounded-xl border border-rose-200 bg-rose-50/70 px-4 py-3 text-zinc-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-slate-200",
      badge: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
    },
  },
};

const VIEWER_STYLES: Record<MarkdownViewerVariant, ViewerStyles> = {
  default: {
    heading: {
      1: "mb-3 mt-6 border-b border-slate-200 pb-2 text-2xl font-bold text-slate-900 dark:border-slate-700 dark:text-slate-100",
      2: "mb-2 mt-5 text-xl font-semibold text-slate-800 dark:text-slate-100",
      3: "mb-2 mt-4 text-lg font-semibold text-slate-800 dark:text-slate-100",
      4: "mb-1 mt-3 text-base font-semibold text-slate-700 dark:text-slate-200",
      5: "mb-1 mt-3 text-sm font-semibold text-slate-700 dark:text-slate-200",
      6: "mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400",
    },
    paragraph: "mb-3 text-sm leading-relaxed text-slate-700 dark:text-slate-300",
    list: "mb-3 list-inside list-disc space-y-1 pl-2 text-sm text-slate-700 dark:text-slate-300",
    orderedList: "mb-3 list-inside list-decimal space-y-1 pl-2 text-sm text-slate-700 dark:text-slate-300",
    listItem: "leading-relaxed [&>p]:mb-0 [&>p]:inline",
    blockquote: "my-3 rounded-r-xl border-l-4 border-slate-300 bg-slate-50/70 pl-4 pr-3 py-2.5 italic text-slate-600 dark:border-slate-600 dark:bg-slate-900/70 dark:text-slate-300",
    codeInline: "rounded bg-slate-100 px-1.5 py-0.5 text-sm font-mono text-slate-800 dark:bg-slate-800 dark:text-slate-100",
    codeShell: "my-4 overflow-hidden rounded-2xl border border-slate-200 bg-slate-950 shadow-sm dark:border-slate-800",
    codeLanguageBadge: "border-b border-slate-800/80 bg-slate-900/95 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400",
    codePre: "overflow-x-auto p-4 text-sm leading-6 text-slate-100",
    tableShell: "my-4 overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950/60",
    table: "min-w-full text-sm",
    thead: "border-b border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-900/80",
    th: "px-3 py-2 text-left font-semibold text-slate-700 dark:text-slate-200",
    td: "border-t border-slate-100 px-3 py-2 text-slate-600 dark:border-slate-800 dark:text-slate-300",
    hr: "my-5 border-slate-200 dark:border-slate-800",
    link: "text-blue-600 transition-colors hover:text-blue-700 hover:underline dark:text-blue-300 dark:hover:text-blue-200",
    strong: "font-semibold text-blue-800 dark:text-blue-200",
    em: "italic text-slate-600 dark:text-slate-300",
    highlight: HIGHLIGHT_MARK_CLASS,
    imageShell: "my-5",
    imageFrame: "overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950/60",
    image: "max-h-[32rem] w-full object-contain bg-white dark:bg-slate-950/60",
    imageCaption: "mt-2 px-1 text-center text-xs text-slate-500 dark:text-slate-400",
  },
  document: {
    heading: {
      1: "mt-8 mb-4 pb-3 border-b border-[#DEE0E3] text-[30px] font-semibold leading-[1.3] tracking-[-0.02em] text-[#111827] dark:border-slate-700 dark:text-slate-100",
      2: "mt-7 mb-3 text-[24px] font-semibold leading-[1.4] tracking-[-0.015em] text-[#111827] dark:text-slate-100",
      3: "mt-6 mb-2.5 text-[20px] font-semibold leading-[1.5] text-[#1F2329] dark:text-slate-200",
      4: "mt-5 mb-2 text-[16px] font-semibold leading-[1.5] text-[#1F2329] dark:text-slate-200",
      5: "mt-4 mb-1.5 text-[14px] font-semibold text-[#646A73] dark:text-slate-400",
      6: "mt-3 mb-1 text-[13px] font-semibold text-[#646A73] dark:text-slate-400",
    },
    paragraph: "mb-3.5 text-[15px] leading-[1.75] text-[#1F2329] dark:text-slate-300",
    list: "mb-4 list-disc space-y-1.5 pl-6 text-[15px] leading-[1.75] text-[#1F2329] dark:text-slate-300",
    orderedList: "mb-4 list-decimal space-y-1.5 pl-6 text-[15px] leading-[1.75] text-[#1F2329] dark:text-slate-300",
    listItem: "leading-[1.75] [&>p]:mb-0 [&>p]:inline",
    blockquote: "my-2.5 rounded-r-md border-l-[3px] border-[#DEE0E3] bg-[#FAFBFC]/88 pl-3 pr-2.5 py-1.25 text-[14px] leading-[1.68] text-[#646A73] dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-400",
    codeInline: "rounded-md border border-[#E6EAF0] bg-[#F8FAFC] px-1.5 py-0.5 font-mono text-[0.9em] text-[#0F172A] shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100",
    codeShell: "my-6 overflow-hidden rounded-xl border border-[#E5E7EB] bg-white shadow-[0_12px_30px_-26px_rgba(15,23,42,0.35)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_18px_42px_-30px_rgba(0,0,0,0.8)]",
    codeLanguageBadge: "border-b border-[#ECECF1] bg-[#F7F7F8] px-4 py-2.5 text-[11px] font-medium uppercase tracking-[0.16em] text-[#6B7280] dark:border-slate-800 dark:bg-slate-900/95 dark:text-slate-400",
    codePre: "overflow-x-auto bg-white px-4 py-4 text-[13px] leading-6 text-[#111827] font-mono dark:bg-slate-950 dark:text-slate-100",
    tableShell: "my-5 overflow-x-auto rounded-lg border border-[#DEE0E3] bg-white dark:border-slate-800 dark:bg-slate-950/60",
    table: "min-w-full text-[14px]",
    thead: "border-b border-[#DEE0E3] bg-[#F5F6F7] dark:border-slate-800 dark:bg-slate-900/80",
    th: "px-3 py-2 text-left text-[13px] font-semibold text-[#1F2329] dark:text-slate-100",
    td: "border-t border-[#F0F0F0] px-3 py-2.5 text-[#1F2329] dark:border-slate-800 dark:text-slate-300",
    hr: "my-7 border-[#DEE0E3] dark:border-slate-800",
    link: "text-[#2563EB] transition-colors hover:text-[#1D4ED8] hover:underline underline-offset-2 dark:text-blue-300 dark:hover:text-blue-200",
    strong: "font-semibold text-[#1D4ED8] dark:text-blue-200",
    em: "italic text-[#646A73] dark:text-slate-400",
    highlight: HIGHLIGHT_MARK_CLASS,
    imageShell: "my-6",
    imageFrame: "overflow-hidden rounded-lg border border-[#DEE0E3] bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950/60",
    image: "max-h-[32rem] w-full object-contain bg-white dark:bg-slate-950/60",
    imageCaption: "mt-2 px-1 text-center text-[13px] text-[#646A73] dark:text-slate-400",
  },
  planner: {
    heading: {
      1: "mb-3 text-lg font-semibold text-zinc-900 dark:text-slate-100",
      2: "mt-4 mb-2 text-sm font-semibold text-zinc-800 dark:text-slate-100",
      3: "mt-3 mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-slate-400",
      4: "mt-3 mb-1 text-sm font-semibold text-zinc-700 dark:text-slate-200",
      5: "mt-3 mb-1 text-xs font-semibold text-zinc-600 dark:text-slate-300",
      6: "mt-3 mb-1 text-[11px] font-semibold uppercase tracking-wide text-zinc-500 dark:text-slate-400",
    },
    paragraph: "mb-3 text-sm leading-6 text-zinc-700 dark:text-slate-300",
    list: "mb-3 list-disc space-y-1.5 pl-5 text-sm leading-6 text-zinc-700 dark:text-slate-300",
    orderedList: "mb-3 list-decimal space-y-1.5 pl-5 text-sm leading-6 text-zinc-700 dark:text-slate-300",
    listItem: "leading-6 [&>p]:mb-0 [&>p]:inline",
    blockquote: "my-3 rounded-xl border border-blue-100 bg-blue-50/60 px-3 py-2.5 text-sm leading-6 text-zinc-700 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-slate-300",
    codeInline: "rounded bg-zinc-100 px-1.5 py-0.5 text-sm font-mono text-zinc-800 dark:bg-slate-800 dark:text-slate-100",
    codeShell: "my-4 overflow-hidden rounded-xl border border-zinc-200 bg-zinc-950 shadow-sm dark:border-slate-800",
    codeLanguageBadge: "border-b border-zinc-800/80 bg-zinc-900/95 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-400",
    codePre: "overflow-x-auto p-4 text-sm leading-6 text-zinc-100",
    tableShell: "my-4 overflow-x-auto rounded-xl border border-zinc-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950/60",
    table: "min-w-full text-sm",
    thead: "border-b border-zinc-200 bg-zinc-50 dark:border-slate-800 dark:bg-slate-900/80",
    th: "px-3 py-2 text-left font-semibold text-zinc-700 dark:text-slate-200",
    td: "border-t border-zinc-100 px-3 py-2 text-zinc-600 dark:border-slate-800 dark:text-slate-300",
    hr: "my-5 border-zinc-200 dark:border-slate-800",
    link: "text-blue-600 transition-colors hover:text-blue-700 hover:underline dark:text-blue-300 dark:hover:text-blue-200",
    strong: "font-semibold text-blue-800 dark:text-blue-200",
    em: "italic text-zinc-600 dark:text-slate-300",
    highlight: HIGHLIGHT_MARK_CLASS,
    imageShell: "my-5",
    imageFrame: "overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950/60",
    image: "max-h-[28rem] w-full object-contain bg-white dark:bg-slate-950/60",
    imageCaption: "mt-2 px-1 text-center text-xs text-zinc-500 dark:text-slate-400",
  },
};

export function preprocessLaTeX(content: string): string {
  if (!content) return content;
  let processed = typeof content === "string" ? content : String(content);
  processed = processed.replace(/\\\[([\s\S]*?)\\\]/g, "$$$$$1$$$$");
  processed = processed.replace(/\\\(([\s\S]*?)\\\)/g, "$$$1$$");
  processed = processed.replace(/\\text\{(_+)\}/g, (_match, underscores: string) => {
    return `\\text{${"\\_".repeat(underscores.length)}}`;
  });
  return normalizeBareLatexTextCommands(processed);
}

function replaceBareLatexTextCommands(text: string): string {
  return text.replace(/\\([A-Za-z]+)\b/g, (match, command: string) => {
    return BARE_LATEX_TEXT_COMMANDS[command] ?? match;
  });
}

function findNextUnescaped(source: string, token: string, fromIndex: number): number {
  let index = source.indexOf(token, fromIndex);
  while (index >= 0) {
    let slashCount = 0;
    for (let cursor = index - 1; cursor >= 0 && source[cursor] === "\\"; cursor -= 1) {
      slashCount += 1;
    }
    if (slashCount % 2 === 0) {
      return index;
    }
    index = source.indexOf(token, index + token.length);
  }
  return -1;
}

function replaceOutsideInlineMathAndCode(markdown: string): string {
  const source = String(markdown || "");
  const output: string[] = [];
  let index = 0;

  while (index < source.length) {
    const char = source[index];
    if (char === "`") {
      const fence = source.slice(index).match(/^`+/)?.[0] ?? "`";
      const end = source.indexOf(fence, index + fence.length);
      if (end >= 0) {
        output.push(source.slice(index, end + fence.length));
        index = end + fence.length;
        continue;
      }
    }

    if (source.startsWith("$$", index)) {
      const end = findNextUnescaped(source, "$$", index + 2);
      if (end >= 0) {
        output.push(source.slice(index, end + 2));
        index = end + 2;
        continue;
      }
    }

    if (char === "$") {
      const end = findNextUnescaped(source, "$", index + 1);
      if (end >= 0) {
        output.push(source.slice(index, end + 1));
        index = end + 1;
        continue;
      }
    }

    const nextSpecialIndexes = [
      source.indexOf("`", index + 1),
      source.indexOf("$", index + 1),
    ].filter((value) => value >= 0);
    const next = nextSpecialIndexes.length > 0 ? Math.min(...nextSpecialIndexes) : source.length;
    output.push(replaceBareLatexTextCommands(source.slice(index, next)));
    index = next;
  }

  return output.join("");
}

function normalizeBareLatexTextCommands(markdown: string): string {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const output: string[] = [];
  let activeFence: string | null = null;
  let plainChunk: string[] = [];

  const flushPlainChunk = () => {
    if (plainChunk.length === 0) return;
    output.push(replaceOutsideInlineMathAndCode(plainChunk.join("\n")));
    plainChunk = [];
  };

  for (const line of lines) {
    const fenceMatch = line.match(/^(```|~~~)/);
    if (fenceMatch) {
      flushPlainChunk();
      if (activeFence === fenceMatch[1]) {
        activeFence = null;
      } else if (activeFence === null) {
        activeFence = fenceMatch[1];
      }
      output.push(line);
      continue;
    }

    if (activeFence) {
      output.push(line);
      continue;
    }

    plainChunk.push(line);
  }

  flushPlainChunk();
  return output.join("\n");
}

function normalizeHighlightSyntaxForRender(markdown: string): string {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const output: string[] = [];
  let activeFence: string | null = null;
  let inDisplayMath = false;

  const normalizeLine = (line: string) => {
    const parts = line.split(/(`+[^`]*`+)/g);
    return parts
      .map((part) => {
        if (part.startsWith("`") && part.endsWith("`")) return part;
        return part
          .replace(/<mark\b[^>]*>\s*([^<>\n]{1,160}?)\s*<\/mark>/gi, (_match, body: string) => {
            const text = String(body || "").trim();
            return text ? `==${text}==` : "";
          })
          .replace(/==\s*([^=\n]{1,160}?)\s*==/g, (_match, body: string) => {
            const text = String(body || "").trim();
            return text ? `==${text}==` : "";
          });
      })
      .join("");
  };

  for (const line of lines) {
    const fenceMatch = line.match(/^(```|~~~)/);
    if (fenceMatch) {
      if (activeFence === fenceMatch[1]) {
        activeFence = null;
      } else if (!activeFence) {
        activeFence = fenceMatch[1];
      }
      output.push(line);
      continue;
    }
    if (!activeFence && /^\s*\$\$\s*$/.test(line)) {
      inDisplayMath = !inDisplayMath;
      output.push(line);
      continue;
    }
    output.push(activeFence || inDisplayMath ? line : normalizeLine(line));
  }

  return output.join("\n");
}

function createBlankNode(): MarkdownAstNode {
  return {
    type: "blank",
    data: {
      hName: "span",
      hProperties: {
        "aria-hidden": "true",
        className: BLANK_NODE_CLASS,
        "data-blank": "true",
      },
    },
    children: [{ type: "text", value: " " }],
  };
}

function createHighlightNode(value: string): MarkdownAstNode {
  return {
    type: "highlightMark",
    data: {
      hName: "mark",
      hProperties: {
        className: HIGHLIGHT_MARK_CLASS,
        "data-markdown-highlight": "true",
      },
    },
    children: [{ type: "text", value }],
  };
}

function remarkBlankTokens() {
  return (tree: MarkdownAstNode) => {
    const visit = (node: MarkdownAstNode) => {
      const children = node.children;
      if (!Array.isArray(children)) return;

      for (let index = 0; index < children.length; index += 1) {
        const child = children[index];
        if (child.type === "text" && typeof child.value === "string" && child.value.includes(BLANK_TOKEN)) {
          const parts = child.value.split(BLANK_TOKEN);
          const replacement: MarkdownAstNode[] = [];
          parts.forEach((part, partIndex) => {
            if (part) replacement.push({ type: "text", value: part });
            if (partIndex < parts.length - 1) replacement.push(createBlankNode());
          });
          children.splice(index, 1, ...replacement);
          index += replacement.length - 1;
          continue;
        }

        if (child.type !== "math" && child.type !== "inlineMath") {
          visit(child);
        }
      }
    };

    visit(tree);
  };
}

function remarkSafeHighlights() {
  return (tree: MarkdownAstNode) => {
    const visit = (node: MarkdownAstNode) => {
      const children = node.children;
      if (!Array.isArray(children)) return;

      for (let index = 0; index < children.length; index += 1) {
        const child = children[index];
        if (child.type === "text" && typeof child.value === "string" && child.value.includes("==")) {
          const replacement: MarkdownAstNode[] = [];
          const source = child.value;
          const regex = /==([^=\n]{1,160})==/g;
          let cursor = 0;
          let match: RegExpExecArray | null;
          while ((match = regex.exec(source)) !== null) {
            const before = source.slice(cursor, match.index);
            const body = (match[1] ?? "").trim();
            if (before) replacement.push({ type: "text", value: before });
            if (body) {
              replacement.push(createHighlightNode(body));
            } else {
              replacement.push({ type: "text", value: match[0] });
            }
            cursor = match.index + match[0].length;
          }
          const tail = source.slice(cursor);
          if (tail) replacement.push({ type: "text", value: tail });
          if (replacement.length > 0) {
            children.splice(index, 1, ...replacement);
            index += replacement.length - 1;
            continue;
          }
        }

        if (child.type !== "math" && child.type !== "inlineMath") {
          visit(child);
        }
      }
    };

    visit(tree);
  };
}

function trimBlankLines(lines: string[]): string[] {
  const next = [...lines];
  while (next.length > 0 && !next[0].trim()) next.shift();
  while (next.length > 0 && !next[next.length - 1].trim()) next.pop();
  return next;
}

function stripLeadingCalloutIcon(line: string): string {
  return String(line || "").replace(CALLOUT_LEADING_ICON_RE, "").replace(/^\s+/, "");
}

function normalizeCalloutBodyLines(lines: string[]): string[] {
  const body = trimBlankLines(lines);
  const firstContentIndex = body.findIndex((line) => line.trim().length > 0);
  if (firstContentIndex >= 0) {
    body[firstContentIndex] = stripLeadingCalloutIcon(body[firstContentIndex]);
  }
  return body;
}

function pushCanonicalCallout(target: string[], kind: string, bodyLines: string[]) {
  const body = normalizeCalloutBodyLines(bodyLines);
  target.push(`> [!${kind.toUpperCase()}]`);
  if (body.length === 0) {
    target.push("");
    return;
  }
  target.push(">");
  for (const line of body) {
    target.push(line.trim() ? `> ${line}` : ">");
  }
  target.push("");
}

function quotedMarkdownBody(line: string): string | null {
  const match = line.match(/^\s*>\s?(.*)$/);
  return match ? (match[1] ?? "") : null;
}

function isBareDisplayMathDelimiter(line: string): boolean {
  return /^\s*\$\$\s*$/.test(line);
}

function displayMathDelimiterForRender(line: string): string {
  return `${displayMathPrefixForRender(line)}$$`;
}

function displayMathPrefixForRender(line: string): string {
  const match = line.match(/^(\s*>\s*)?\$\$\s*$/);
  return match?.[1] ?? "";
}

function collectLooseDisplayMathBlock(lines: string[], startIndex: number): { body: string[]; nextIndex: number } {
  const body: string[] = ["$$"];
  let cursor = startIndex + 1;

  while (cursor < lines.length) {
    const current = lines[cursor];
    const quoted = quotedMarkdownBody(current);
    const bodyLine = quoted ?? current;
    body.push(bodyLine.trimEnd());
    cursor += 1;
    if (isBareDisplayMathDelimiter(bodyLine)) {
      break;
    }
  }

  return { body, nextIndex: cursor };
}

function isCalloutBoundary(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed) return false;
  return Boolean(
    trimmed.match(new RegExp(`^(?:#{1,6}\\s|>\\s*\\[!|:::|!(${CALLOUT_PATTERN})\\b)`, "i")) ||
    trimmed === "---" ||
    trimmed === "***"
  );
}

function preprocessCalloutSyntax(content: string): string {
  if (!content) return content;
  const lines = String(content).replace(/\r\n?/g, "\n").split("\n");
  const output: string[] = [];
  let activeFence: string | null = null;

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const fenceMatch = line.match(/^(```|~~~)/);
    if (fenceMatch) {
      if (activeFence === fenceMatch[1]) {
        activeFence = null;
      } else if (activeFence === null) {
        activeFence = fenceMatch[1];
      }
      output.push(line);
      continue;
    }

    if (activeFence) {
      output.push(line);
      continue;
    }

    const quotedCallout = line.match(new RegExp(`^\\s*>\\s*\\[!(${CALLOUT_PATTERN})\\]\\s*(.*)$`, "i"));
    if (quotedCallout) {
      const kind = quotedCallout[1];
      const body: string[] = [];
      const inlineBody = quotedCallout[2]?.trim();
      if (inlineBody) {
        body.push(inlineBody);
      }

      let cursor = index + 1;
      while (cursor < lines.length) {
        const current = lines[cursor];
        const bodyLine = quotedMarkdownBody(current);
        if (bodyLine === null) {
          if (isBareDisplayMathDelimiter(current)) {
            const mathBlock = collectLooseDisplayMathBlock(lines, cursor);
            body.push(...mathBlock.body);
            cursor = mathBlock.nextIndex;
            continue;
          }
          if (!current.trim()) {
            const next = lines[cursor + 1] ?? "";
            if (quotedMarkdownBody(next) !== null || isBareDisplayMathDelimiter(next)) {
              body.push("");
              cursor += 1;
              continue;
            }
          }
          break;
        }
        if (bodyLine.trim().match(new RegExp(`^\\[!(${CALLOUT_PATTERN})\\]`, "i"))) {
          break;
        }

        body.push(bodyLine);
        cursor += 1;
      }

      pushCanonicalCallout(output, kind, body);
      index = cursor - 1;
      continue;
    }

    const bareCallout = line.match(new RegExp(`^\\s*\\[!(${CALLOUT_PATTERN})\\]\\s*(.*)$`, "i"));
    if (bareCallout) {
      const kind = bareCallout[1];
      const inlineBody = bareCallout[2]?.trim();
      if (inlineBody) {
        pushCanonicalCallout(output, kind, [inlineBody]);
        continue;
      }

      const body: string[] = [];
      let cursor = index + 1;
      while (cursor < lines.length) {
        const current = lines[cursor];
        const next = lines[cursor + 1] ?? "";

        if (!current.trim() && body.length === 0) {
          cursor += 1;
          continue;
        }

        if (!current.trim() && isCalloutBoundary(next)) {
          break;
        }

        if (body.length > 0 && isCalloutBoundary(current)) {
          break;
        }

        body.push(current);
        cursor += 1;
      }

      pushCanonicalCallout(output, kind, body);
      index = cursor - 1;
      continue;
    }

    const directiveMatch = line.match(new RegExp(`^:::\\s*(${CALLOUT_PATTERN})\\s*$`, "i"));
    if (directiveMatch) {
      const body: string[] = [];
      const kind = directiveMatch[1];
      let cursor = index + 1;
      while (cursor < lines.length && !/^:::\s*$/.test(lines[cursor])) {
        body.push(lines[cursor]);
        cursor += 1;
      }
      if (cursor < lines.length && /^:::\s*$/.test(lines[cursor])) {
        pushCanonicalCallout(output, kind, body);
        index = cursor;
        continue;
      }
    }

    const singleLineBang = line.match(new RegExp(`^!(${CALLOUT_PATTERN})\\s+(.+)$`, "i"));
    if (singleLineBang) {
      pushCanonicalCallout(output, singleLineBang[1], [singleLineBang[2]]);
      continue;
    }

    const blockBang = line.match(new RegExp(`^!(${CALLOUT_PATTERN})\\s*$`, "i"));
    if (blockBang) {
      const kind = blockBang[1];
      const body: string[] = [];
      let cursor = index + 1;

      while (cursor < lines.length) {
        const current = lines[cursor];
        const next = lines[cursor + 1] ?? "";

        if (!current.trim() && body.length === 0) {
          cursor += 1;
          continue;
        }

        if (!current.trim() && isCalloutBoundary(next)) {
          break;
        }

        if (body.length > 0 && isCalloutBoundary(current)) {
          break;
        }

        body.push(current);
        cursor += 1;
      }

      pushCanonicalCallout(output, kind, body);
      index = cursor - 1;
      continue;
    }

    output.push(line);
  }

  return output.join("\n");
}

function isMarkdownBoundary(line: string): boolean {
  return /^(#{1,6}\s+\S|[-*+]\s+\S|\d+\.\s+\S|>\s*\S|\|.+\||---\s*$)/.test(line.trim());
}

function stripQuotePrefix(line: string): string {
  return String(line || "").replace(/^\s*>\s?/, "").trimEnd();
}

function splitMarkdownTableCells(line: string): string[] {
  let stripped = stripQuotePrefix(line).trim();
  if (!stripped.includes("|")) return [];
  if (stripped.startsWith("|")) stripped = stripped.slice(1);
  if (stripped.endsWith("|")) stripped = stripped.slice(0, -1);

  const cells: string[] = [];
  let current = "";
  let escaped = false;
  for (const char of stripped) {
    if (escaped) {
      current += char;
      escaped = false;
      continue;
    }
    if (char === "\\") {
      current += char;
      escaped = true;
      continue;
    }
    if (char === "|") {
      cells.push(current);
      current = "";
      continue;
    }
    current += char;
  }
  cells.push(current);
  return cells;
}

function isTableSeparatorLine(line: string): boolean {
  const cells = splitMarkdownTableCells(line);
  return cells.length >= 2 && cells.every((cell) => /^\s*:?-{3,}:?\s*$/.test(cell));
}

function isProbableTableRow(line: string): boolean {
  const stripped = stripQuotePrefix(line).trim();
  if (!stripped) return false;
  if (!stripped.startsWith("|") && !stripped.endsWith("|")) return false;
  const cells = splitMarkdownTableCells(stripped);
  return cells.length >= 2 && cells.some((cell) => cell.trim());
}

function isGfmTableBoundary(lines: string[], index: number): boolean {
  if (index < 0 || index >= lines.length) return false;
  const line = lines[index] ?? "";
  const previous = index > 0 ? lines[index - 1] ?? "" : "";
  const next = index + 1 < lines.length ? lines[index + 1] ?? "" : "";
  if (isTableSeparatorLine(line)) {
    return isProbableTableRow(previous) || isProbableTableRow(next);
  }
  if (!isProbableTableRow(line)) return false;
  return isTableSeparatorLine(previous) || isTableSeparatorLine(next);
}

function isStructuralMarkdownBoundary(lines: string[], index: number): boolean {
  if (index < 0 || index >= lines.length) return false;
  const stripped = stripQuotePrefix(lines[index] ?? "").trim();
  if (!stripped) return false;
  if (
    new RegExp(
      `^(?:#{1,6}\\s+\\S|[-*+]\\s+(?:\\*\\*|\`|\\[|.{12,})|\\d+\\.\\s+\\S|>\\s*\\S|\\[!(?:${CALLOUT_PATTERN})\\]|\`\`\`|(?:---|\\*\\*\\*|___)\\s*$)`,
      "i",
    ).test(stripped)
  ) {
    return true;
  }
  return isGfmTableBoundary(lines, index);
}

function nextNonemptyLineIndex(lines: string[], startIndex: number): number | null {
  for (let index = startIndex; index < lines.length; index += 1) {
    if ((lines[index] ?? "").trim()) return index;
  }
  return null;
}

function isOrphanDisplayMathOpener(lines: string[], index: number): boolean {
  const nextIndex = nextNonemptyLineIndex(lines, index + 1);
  if (nextIndex === null) return true;
  return isStructuralMarkdownBoundary(lines, nextIndex);
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

function isDisplayMathDelimiterLine(line: string): boolean {
  return /^\s*(?:>\s*)?\$\$\s*$/.test(line);
}

function isMarkdownBoundaryInsideMath(lines: string[], index: number): boolean {
  const stripped = stripQuotePrefix(lines[index] ?? "").trim();
  if (!stripped) return false;
  if (
    new RegExp(
      `^(?:#{1,6}\\s+\\S|[-*+]\\s+(?:\\*\\*|\`|\\[|.{12,})|\\d+\\.\\s+\\S|>\\s*\\S|\\[!(?:${CALLOUT_PATTERN})\\]|\`\`\`)`,
      "i",
    ).test(stripped)
  ) {
    return true;
  }
  return isGfmTableBoundary(lines, index);
}

function repairDisplayMathBoundariesForRender(markdown: string): string {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const output: string[] = [];
  let inDisplayMath = false;
  let displayMathPrefix = "";

  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index] ?? "";
    const line = rawLine.trimEnd();
    if (isDisplayMathDelimiterLine(line)) {
      if (!inDisplayMath && isOrphanDisplayMathOpener(lines, index)) {
        continue;
      }
      const delimiterPrefix = displayMathPrefixForRender(line);
      if (inDisplayMath) {
        output.push(`${delimiterPrefix || displayMathPrefix}$$`);
        inDisplayMath = false;
        displayMathPrefix = "";
      } else {
        displayMathPrefix = delimiterPrefix;
        output.push(`${displayMathPrefix}$$`);
        inDisplayMath = true;
      }
      continue;
    }

    if (inDisplayMath && isMarkdownBoundaryInsideMath(lines, index)) {
      const closingDelimiter = `${displayMathPrefix}$$`;
      if (output[output.length - 1] !== closingDelimiter) {
        output.push(closingDelimiter);
      }
      inDisplayMath = false;
      displayMathPrefix = "";
    }

    output.push(line);
  }

  if (inDisplayMath) {
    output.push(`${displayMathPrefix}$$`);
  }

  return output.join("\n");
}

function isEscapedAt(source: string, index: number): boolean {
  let slashCount = 0;
  for (let cursor = index - 1; cursor >= 0 && source[cursor] === "\\"; cursor -= 1) {
    slashCount += 1;
  }
  return slashCount % 2 === 1;
}

function unescapedSingleDollarPositions(line: string): number[] {
  const positions: number[] = [];
  for (let index = 0; index < line.length; index += 1) {
    if (line[index] === "`") {
      const tickRun = line.slice(index).match(/^`+/)?.[0] ?? "`";
      const closing = line.indexOf(tickRun, index + tickRun.length);
      if (closing >= 0) {
        index = closing + tickRun.length - 1;
        continue;
      }
      index += tickRun.length - 1;
      continue;
    }
    if (line[index] !== "$") continue;
    if (line[index + 1] === "$") {
      index += 1;
      continue;
    }
    if (isEscapedAt(line, index)) continue;
    positions.push(index);
  }
  return positions;
}

function inlineMathBodyHasSignal(body: string): boolean {
  const trimmed = body.trim();
  return (
    /\\(?:frac|dfrac|tfrac|lim|sum|prod|int|sqrt|left|right|to|infty|text|cdot|times|leq?|geq?|neq|approx|alpha|beta|gamma|delta|theta|lambda|mu|pi|sigma|omega)\b/.test(trimmed) ||
    /[_^{}∞∑∫√≤≥≈≠]|[A-Za-z0-9]\s*[=+\-*/<>]\s*[A-Za-z0-9\\]/.test(trimmed)
  );
}

function inlineMathBodyLooksUnsafe(body: string): boolean {
  const trimmed = body.trim();
  if (!trimmed) return true;
  if (trimmed.length > 800 && !inlineMathBodyHasSignal(trimmed)) return true;
  if (/[`]|<\/?[a-z][\s>]/i.test(body)) return true;
  if (body.includes("**") || body.includes("[!") || body.includes("```")) return true;
  return new RegExp(
    `(^|\\n)\\s*(?:#{1,6}\\s+\\S|[-*+]\\s+(?:\\*\\*|\`|\\[|.{12,})|\\d+\\.\\s+\\S|>\\s*\\S|\\[!(?:${CALLOUT_PATTERN})\\])`,
    "i",
  ).test(body);
}

function restoreEscapedInlineMathLineForRender(line: string): string {
  return line.replace(/\\\$([^\n]*?)\\\$/g, (match, body: string) => {
    const trimmed = String(body || "").trim();
    if (!trimmed || !inlineMathBodyHasSignal(trimmed) || inlineMathBodyLooksUnsafe(trimmed)) {
      return match;
    }
    return `$${trimmed}$`;
  });
}

function repairInlineMathLineForRender(line: string): string {
  let working = restoreEscapedInlineMathLineForRender(line);
  let positions = unescapedSingleDollarPositions(working);
  if (positions.length % 2 !== 0) {
    const dangling = positions[positions.length - 1];
    working = `${working.slice(0, dangling)}\\$${working.slice(dangling + 1)}`;
    positions = unescapedSingleDollarPositions(working);
  }

  if (positions.length < 2) return working;

  const output: string[] = [];
  let cursor = 0;
  let changed = false;
  for (let index = 0; index + 1 < positions.length; index += 2) {
    const left = positions[index];
    const right = positions[index + 1];
    const body = working.slice(left + 1, right);
    output.push(working.slice(cursor, left));
    if (inlineMathBodyLooksUnsafe(body)) {
      output.push("\\$", body, "\\$");
      changed = true;
    } else if (body !== body.trim()) {
      output.push("$", body.trim(), "$");
      changed = true;
    } else {
      output.push(working.slice(left, right + 1));
    }
    cursor = right + 1;
  }
  output.push(working.slice(cursor));
  return changed ? output.join("") : working;
}

function repairInlineMathForRender(markdown: string): string {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const output: string[] = [];
  let activeFence: string | null = null;
  let inDisplayMath = false;

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    const fenceMatch = line.match(/^(```|~~~)/);
    if (fenceMatch) {
      if (activeFence === fenceMatch[1]) {
        activeFence = null;
      } else if (activeFence === null) {
        activeFence = fenceMatch[1];
      }
      output.push(line);
      continue;
    }

    if (activeFence) {
      output.push(line);
      continue;
    }

    if (isDisplayMathDelimiterLine(line)) {
      inDisplayMath = !inDisplayMath;
      output.push(displayMathDelimiterForRender(line));
      continue;
    }

    output.push(inDisplayMath ? line : repairInlineMathLineForRender(line));
  }

  return output.join("\n");
}

function repairMathDelimitersForRender(markdown: string): string {
  return repairInlineMathForRender(repairDisplayMathBoundariesForRender(markdown));
}

function findNextUnescapedPipe(source: string, startIndex: number): number {
  for (let index = startIndex; index < source.length; index += 1) {
    if (source[index] === "|" && !isEscapedAt(source, index)) {
      return index;
    }
  }
  return -1;
}

function normalizeVerticalBarsInMathBody(body: string): string {
  let output = "";
  let index = 0;
  let changed = false;

  while (index < body.length) {
    if (body[index] !== "|" || isEscapedAt(body, index)) {
      output += body[index] ?? "";
      index += 1;
      continue;
    }

    const closing = findNextUnescapedPipe(body, index + 1);
    if (closing < 0) {
      output += body[index] ?? "";
      index += 1;
      continue;
    }

    const inner = body.slice(index + 1, closing).trim();
    if (!inner) {
      output += body.slice(index, closing + 1);
    } else {
      output += `\\lvert ${inner}\\rvert`;
      changed = true;
    }
    index = closing + 1;
  }

  return changed ? output : body;
}

function protectInlineMathPipesInTableRow(line: string): string {
  const positions = unescapedSingleDollarPositions(line);
  if (positions.length < 2 || positions.length % 2 !== 0) return line;

  const output: string[] = [];
  let cursor = 0;
  let changed = false;
  for (let index = 0; index + 1 < positions.length; index += 2) {
    const left = positions[index];
    const right = positions[index + 1];
    const body = line.slice(left + 1, right);
    const normalizedBody = normalizeVerticalBarsInMathBody(body.trim());
    output.push(line.slice(cursor, left));
    if (normalizedBody !== body) {
      output.push("$", normalizedBody, "$");
      changed = true;
    } else {
      output.push(line.slice(left, right + 1));
    }
    cursor = right + 1;
  }
  output.push(line.slice(cursor));
  return changed ? output.join("") : line;
}

function protectTableInlineMathPipesForRender(markdown: string): string {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const output: string[] = [];
  let activeFence: string | null = null;
  let inDisplayMath = false;
  let inTable = false;

  for (let index = 0; index < lines.length; index += 1) {
    const line = (lines[index] ?? "").trimEnd();
    const fenceMatch = line.match(/^(```|~~~)/);
    if (fenceMatch) {
      if (activeFence === fenceMatch[1]) {
        activeFence = null;
      } else if (activeFence === null) {
        activeFence = fenceMatch[1];
      }
      inTable = false;
      output.push(line);
      continue;
    }

    if (activeFence) {
      output.push(line);
      continue;
    }

    if (isDisplayMathDelimiterLine(line)) {
      inDisplayMath = !inDisplayMath;
      inTable = false;
      output.push(displayMathDelimiterForRender(line));
      continue;
    }

    if (inDisplayMath) {
      output.push(line);
      continue;
    }

    const nextLine = index + 1 < lines.length ? lines[index + 1] ?? "" : "";
    const startsTable = isProbableTableRow(line) && isTableSeparatorLine(nextLine);
    if (startsTable) {
      inTable = true;
      output.push(protectInlineMathPipesInTableRow(line));
      continue;
    }

    if (inTable && isProbableTableRow(line)) {
      output.push(protectInlineMathPipesInTableRow(line));
      continue;
    }

    inTable = false;
    output.push(line);
  }

  return output.join("\n");
}

function normalizeListEmbeddedHeadingsForRender(markdown: string): string {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const output: string[] = [];
  let activeFence: string | null = null;
  let inDisplayMath = false;

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    const fenceMatch = line.match(/^(```|~~~)/);
    if (fenceMatch) {
      if (activeFence === fenceMatch[1]) {
        activeFence = null;
      } else if (activeFence === null) {
        activeFence = fenceMatch[1];
      }
      output.push(line);
      continue;
    }

    if (activeFence) {
      output.push(line);
      continue;
    }

    if (isDisplayMathDelimiterLine(line)) {
      inDisplayMath = !inDisplayMath;
      output.push(displayMathDelimiterForRender(line));
      continue;
    }

    output.push(
      inDisplayMath ? line : line.replace(/^(\s*(?:[-*+]|\d+[.)])\s+)#{1,6}\s+(.+)$/, "$1$2"),
    );
  }

  return output.join("\n");
}

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
      if (isIndentedContextEcho(line) || malformedMermaidFenceBody(line)) continue;
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
        if (isIndentedContextEcho(line) || malformedMermaidFenceBody(line)) {
          skippingArtifact = true;
          continue;
        }
        afterMermaidClose = false;
      }

      const start = line.match(/^\s*```\s*(mermaid|maymaid|mermaind|mermaide|mindmap|graph|flowchart|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|gantt|pie|journey|timeline|gitGraph)\s*$/i);
      if (start?.[1]) {
        const lang = start[1];
        inMermaid = true;
        mermaidLines = MERMAID_LANGUAGE_ALIASES.has(lang.toLowerCase()) ? [] : [lang];
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

export function preprocessMarkdownForRender(content: string): string {
  return repairMalformedMermaidFencesForRender(
    normalizeListEmbeddedHeadingsForRender(
      protectTableInlineMathPipesForRender(
        repairMathDelimitersForRender(preprocessLaTeX(normalizeHighlightSyntaxForRender(preprocessCalloutSyntax(content)))),
      ),
    ),
  );
}

function preprocessMarkdownContent(content: string): string {
  return preprocessMarkdownForRender(content);
}

function textToId(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\u4e00-\u9fff]+/g, "-")
    .replace(/^-|-$/g, "");
}

function extractText(node: ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (!node) return "";
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (typeof node === "object" && "props" in node) {
    return extractText((node as { props?: { children?: ReactNode } }).props?.children);
  }
  return "";
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

function readStringProp(props: object, key: string): string | undefined {
  const value = (props as Record<string, unknown>)[key];
  return typeof value === "string" && value ? value : undefined;
}

function resolveCollapsibleHeadingLevels(value: CollapsibleHeadings | undefined): Set<number> {
  if (value === true) {
    return new Set([1, 2, 3]);
  }
  if (!Array.isArray(value)) {
    return new Set();
  }
  return new Set(value.filter((level) => Number.isInteger(level) && level >= 1 && level <= 6));
}

function applyHeadingCollapseDomState(id: string, collapsed: boolean, source: HTMLElement | null | undefined): boolean {
  const section = source?.closest<HTMLElement>(".markdown-collapsible-section[data-heading-section-id]");
  if (!section || section.getAttribute("data-heading-section-id") !== id) {
    return false;
  }

  if (collapsed) {
    section.setAttribute("data-collapsed", "true");
  } else {
    section.removeAttribute("data-collapsed");
  }

  const heading = section.firstElementChild instanceof HTMLElement ? section.firstElementChild : null;
  if (heading?.getAttribute("data-heading-id") === id) {
    if (collapsed) {
      heading.setAttribute("data-heading-collapsed", "true");
    } else {
      heading.removeAttribute("data-heading-collapsed");
    }
  }

  const toggle = heading?.querySelector<HTMLButtonElement>('[data-heading-toggle="true"]');
  if (toggle) {
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.setAttribute("aria-label", collapsed ? "展开标题内容" : "折叠标题内容");
    toggle.title = collapsed ? "展开标题内容" : "折叠标题内容";
  }

  return true;
}

function extractMarkdownAstText(node: MarkdownAstNode | undefined): string {
  if (!node) return "";
  if (typeof node.value === "string") return node.value;
  if (!Array.isArray(node.children)) return "";
  return node.children.map(extractMarkdownAstText).join("");
}

function normalizeCalloutKind(value: string | undefined): CalloutKind | null {
  const normalized = value?.toLowerCase();
  if (
    normalized === "note" ||
    normalized === "tip" ||
    normalized === "important" ||
    normalized === "warning" ||
    normalized === "caution"
  ) {
    return normalized;
  }
  return null;
}

function extractCalloutMarker(paragraph: MarkdownAstNode): CalloutKind | null {
  const children = paragraph.children;
  if (!Array.isArray(children) || children.length === 0) {
    return null;
  }

  const firstTextIndex = children.findIndex((child) => child.type === "text" && typeof child.value === "string");
  if (firstTextIndex < 0) {
    return null;
  }

  const firstText = children[firstTextIndex];
  const match = String(firstText.value ?? "").match(/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*/i);
  const kind = normalizeCalloutKind(match?.[1]);
  if (!match || !kind || firstTextIndex > 0) {
    return null;
  }

  const remaining = String(firstText.value ?? "").slice(match[0].length);
  if (remaining) {
    firstText.value = remaining;
  } else {
    children.splice(firstTextIndex, 1);
  }

  if (children.length === 0) {
    paragraph.children = [];
  }

  return kind;
}

function remarkCallouts() {
  return (tree: MarkdownAstNode) => {
    const visit = (node: MarkdownAstNode) => {
      const children = node.children;
      if (!Array.isArray(children)) {
        return;
      }

      for (const child of children) {
        if (child.type === "blockquote") {
          const firstChild = child.children?.[0];
          if (firstChild?.type === "paragraph") {
            const kind = extractCalloutMarker(firstChild);
            if (kind) {
              child.data = {
                ...(child.data ?? {}),
                hProperties: {
                  ...(child.data?.hProperties ?? {}),
                  "data-callout-kind": kind,
                },
              };

              if (!firstChild.children?.length) {
                child.children?.shift();
              }
            }
          }
        }

        if (child.type !== "math" && child.type !== "inlineMath") {
          visit(child);
        }
      }
    };

    visit(tree);
  };
}

function isHeadingNode(node: MarkdownAstNode): node is MarkdownAstNode & { depth: number } {
  return node.type === "heading" && Number.isInteger(node.depth) && (node.depth ?? 0) >= 1 && (node.depth ?? 0) <= 6;
}

function getHeadingAstId(node: MarkdownAstNode): string | undefined {
  const value = node.data?.hProperties?.["data-heading-id"] ?? node.data?.hProperties?.id;
  return typeof value === "string" && value ? value : undefined;
}

function isNestedHeadingContainer(node: MarkdownAstNode): boolean {
  return ["blockquote", "list", "listItem", "table", "tableRow", "tableCell"].includes(node.type ?? "");
}

function formatHeadingNumber(level: number, counters: number[]): string {
  const parts: number[] = [];
  for (let index = 1; index <= level; index += 1) {
    if (counters[index] === 0) {
      counters[index] = 1;
    }
    parts.push(counters[index]);
  }
  return level === 1 ? `${parts[0]}.` : parts.join(".");
}

function annotateHeadingIds(
  node: MarkdownAstNode,
  nextHeadingId: (text: string) => string,
  insideNestedHeadingContext = false,
) {
  if (isHeadingNode(node) && !insideNestedHeadingContext) {
    const id = nextHeadingId(extractMarkdownAstText(node));
    const hProperties = {
      ...(node.data?.hProperties ?? {}),
      id,
      "data-heading-id": id,
      "data-heading-level": String(node.depth),
    };
    node.data = {
      ...(node.data ?? {}),
      hProperties,
    };
  }

  if (Array.isArray(node.children)) {
    const nextNestedHeadingContext = insideNestedHeadingContext || isNestedHeadingContainer(node);
    node.children.forEach((child) => annotateHeadingIds(child, nextHeadingId, nextNestedHeadingContext));
  }
}

function annotateHeadingNumbers(
  node: MarkdownAstNode,
  numberedLevels: Set<number>,
  counters: number[] = Array(7).fill(0),
  insideNestedHeadingContext = false,
) {
  if (isHeadingNode(node) && !insideNestedHeadingContext) {
    const level = node.depth;
    if (numberedLevels.has(level)) {
      counters[level] += 1;
      for (let index = level + 1; index < counters.length; index += 1) {
        counters[index] = 0;
      }
      const hProperties = {
        ...(node.data?.hProperties ?? {}),
        "data-heading-number": formatHeadingNumber(level, counters),
      };
      node.data = {
        ...(node.data ?? {}),
        hProperties,
      };
    }
  }

  if (Array.isArray(node.children)) {
    const nextNestedHeadingContext = insideNestedHeadingContext || isNestedHeadingContainer(node);
    node.children.forEach((child) =>
      annotateHeadingNumbers(child, numberedLevels, counters, nextNestedHeadingContext),
    );
  }
}

function groupHeadingSections(nodes: MarkdownAstNode[], collapsibleLevels: Set<number>): MarkdownAstNode[] {
  const roots: MarkdownAstNode[] = [];
  const stack: Array<{ level: number; children: MarkdownAstNode[] }> = [];

  for (const node of nodes) {
    if (!isHeadingNode(node)) {
      const parent = stack[stack.length - 1];
      if (parent) {
        parent.children.push(node);
      } else {
        roots.push(node);
      }
      continue;
    }

    const level = node.depth;
    const id = getHeadingAstId(node);
    while (stack.length > 0 && stack[stack.length - 1].level >= level) {
      stack.pop();
    }

    const hProperties: Record<string, unknown> = {
      "data-heading-section": "true",
      "data-heading-section-level": String(level),
    };
    if (id) {
      hProperties["data-heading-section-id"] = id;
    }
    if (collapsibleLevels.has(level)) {
      hProperties["data-collapsible-section"] = "true";
    }

    const section: MarkdownAstNode = {
      type: "headingSection",
      data: {
        hName: "section",
        hProperties,
      },
      children: [node],
    };

    const parent = stack[stack.length - 1];
    if (parent) {
      parent.children.push(section);
    } else {
      roots.push(section);
    }
    stack.push({ level, children: section.children ?? [] });
  }

  return roots;
}

function createHeadingStructurePlugin({
  headingAnchors,
  numberedLevels,
  collapsibleLevels,
}: {
  headingAnchors: boolean;
  numberedLevels: Set<number>;
  collapsibleLevels: Set<number>;
}) {
  return () => {
    return (tree: MarkdownAstNode) => {
      const shouldAnnotateHeadings = headingAnchors || collapsibleLevels.size > 0 || numberedLevels.size > 0;
      if (!shouldAnnotateHeadings) {
        return;
      }

      annotateHeadingIds(tree, createHeadingIdFactory());
      if (numberedLevels.size > 0) {
        annotateHeadingNumbers(tree, numberedLevels);
      }

      if (collapsibleLevels.size === 0 || !Array.isArray(tree.children)) {
        return;
      }

      tree.children = groupHeadingSections(tree.children, collapsibleLevels);
    };
  };
}

function looksLikeGitConflictBlock(codeText: string): boolean {
  return /^<<<<<<<[\s\S]*\n=======[\s\S]*\n>>>>>>>/m.test(codeText);
}

function renderGitConflictLines(codeText: string): ReactNode[] {
  let region: "base" | "current" | "incoming" = "base";

  return codeText.split("\n").map((line, index) => {
    let lineClass = "border-transparent text-[#24292F]";

    if (/^<<<<<<<(?:\s|$)/.test(line)) {
      lineClass = "border-rose-300 bg-rose-50 text-rose-700 font-semibold";
      region = "current";
    } else if (/^=======$/.test(line)) {
      lineClass = "border-amber-300 bg-amber-50 text-amber-700 font-semibold";
      region = "incoming";
    } else if (/^>>>>>>>(?:\s|$)/.test(line)) {
      lineClass = "border-emerald-300 bg-emerald-50 text-emerald-700 font-semibold";
      region = "base";
    } else if (region === "current") {
      lineClass = "border-rose-100 bg-rose-50/35 text-[#24292F]";
    } else if (region === "incoming") {
      lineClass = "border-emerald-100 bg-emerald-50/35 text-[#24292F]";
    }

    return (
      <span
        key={`${index}-${line}`}
        className={cn("block min-h-[1.5rem] border-l-4 px-4 whitespace-pre", lineClass)}
      >
        {line || "\u00A0"}
      </span>
    );
  });
}

function isAbsoluteAssetUrl(value: string): boolean {
  return /^(https?:)?\/\//i.test(value) || value.startsWith("/") || value.startsWith("data:");
}

function encodePathSegments(path: string): string {
  return path
    .split("/")
    .filter(Boolean)
    .map((part) => encodeURIComponent(part))
    .join("/");
}

function extractCourseAssetPath(src: string): string | null {
  const normalized = src.split("#")[0]?.split("?")[0]?.replace(/\\/g, "/").trim() ?? "";
  if (!normalized || /^(https?:)?\/\//i.test(normalized) || normalized.startsWith("data:")) {
    return null;
  }

  const assetMatch = normalized.match(/(?:^|\/)assets\/(.+)$/);
  if (!assetMatch?.[1]) {
    return null;
  }

  return assetMatch[1].replace(/^\/+/, "");
}

function resolveMarkdownImageSrc(
  src: string | undefined,
  {
    assetBaseUrl,
    assetCourse,
  }: {
  assetBaseUrl?: string;
  assetCourse?: string;
}): string | undefined {
  if (!src) {
    return src;
  }

  if (assetCourse) {
    const assetPath = extractCourseAssetPath(src);
    if (assetPath) {
      return `/api/v1/courses/${encodeURIComponent(assetCourse)}/files/assets/${encodePathSegments(assetPath)}`;
    }
  }

  if (!assetBaseUrl || isAbsoluteAssetUrl(src)) {
    return src;
  }

  const cleanSrc = src.split("#")[0]?.split("?")[0] ?? src;
  const normalized = cleanSrc.replace(/\\/g, "/").trim();
  const pathParts = normalized.split("/").filter(Boolean);
  const filename = pathParts[pathParts.length - 1];

  if (!filename) {
    return src;
  }

  const looksLikeAssetPath =
    !normalized.includes("/") ||
    normalized.startsWith("images/") ||
    normalized.startsWith("../assets/") ||
    normalized.startsWith("./") ||
    normalized.startsWith("../");

  if (!looksLikeAssetPath) {
    return src;
  }

  return `${assetBaseUrl.replace(/\/$/, "")}/${encodeURIComponent(filename)}`;
}

function shouldFetchAuthorizedAsset(src: string | undefined): src is string {
  return typeof src === "string" && src.startsWith("/api/v1/courses/") && src.includes("/files/assets/");
}

function isDocgenCoverAsset(src: string | undefined): boolean {
  return typeof src === "string" && /\/files\/assets\/docgen\/cover\./i.test(src);
}

function getBearerToken(): string {
  try {
    return window.localStorage.getItem("token") ?? "";
  } catch {
    return "";
  }
}

function MarkdownImage({
  src,
  alt,
  styles,
}: {
  src: string | undefined;
  alt: string | undefined;
  styles: ViewerStyles;
}) {
  const [blobSrc, setBlobSrc] = useState("");
  const isCover = isDocgenCoverAsset(src);

  useEffect(() => {
    if (!shouldFetchAuthorizedAsset(src)) {
      setBlobSrc("");
      return;
    }
    const token = getBearerToken();
    if (!token) {
      setBlobSrc("");
      return;
    }

    const controller = new AbortController();
    let objectUrl = "";
    runTrackedApiFetch(
      src,
      {
        method: "GET",
        signal: controller.signal,
      },
      async (response) => {
        if (!response.ok) {
          throw new Error(`asset fetch failed: ${response.status}`);
        }
        return response.blob();
      },
      "markdown_asset_disconnect",
    )
      .then((blob) => {
        if (controller.signal.aborted) {
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        setBlobSrc(objectUrl);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setBlobSrc("");
        }
      });

    return () => {
      controller.abort();
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [src]);

  return (
    <figure className={styles.imageShell}>
      <div className={cn(styles.imageFrame, isCover && "rounded-xl")}>
        <img
          src={blobSrc || src}
          alt={alt ?? ""}
          className={cn(
            styles.image,
            isCover && "aspect-[16/7] max-h-none object-cover",
          )}
          loading="lazy"
        />
      </div>
      {alt ? <figcaption className={styles.imageCaption}>{alt}</figcaption> : null}
    </figure>
  );
}

function parseCallout(children: ReactNode): { kind: CalloutKind; body: ReactNode[] } | null {
  const nodes = Children.toArray(children).filter((item) => item !== "\n");
  if (nodes.length === 0) {
    return null;
  }

  const firstText = extractText(nodes[0]).trim();
  const match = firstText.match(/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\](?:\s+(.+))?$/i);
  if (!match) {
    return null;
  }

  const inlineTitle = match[2]?.trim();
  const body = inlineTitle ? [inlineTitle, ...nodes.slice(1)] : nodes.slice(1);

  return {
    kind: match[1].toLowerCase() as CalloutKind,
    body,
  };
}

export function MarkdownViewer({
  content,
  assetBaseUrl,
  assetCourse,
  variant = "default",
  headingAnchors = false,
  headingNumbering = false,
  collapsibleHeadings,
  collapsedHeadingIds: controlledCollapsedHeadingIds,
  onHeadingCollapseChange,
}: MarkdownViewerProps) {
  const processedContent = useMemo(() => preprocessMarkdownContent(content), [content]);
  const styles = VIEWER_STYLES[variant];
  const nextHeadingId = useMemo(() => createHeadingIdFactory(), [processedContent]);
  const collapsibleHeadingLevels = useMemo(
    () => resolveCollapsibleHeadingLevels(collapsibleHeadings),
    [collapsibleHeadings],
  );
  const collapsibleHeadingLevelsKey = useMemo(
    () => Array.from(collapsibleHeadingLevels).sort((left, right) => left - right).join(","),
    [collapsibleHeadingLevels],
  );
  const numberedHeadingLevels = useMemo(
    () => (headingNumbering ? new Set([1, 2, 3]) : new Set<number>()),
    [headingNumbering],
  );
  const numberedHeadingLevelsKey = useMemo(
    () => Array.from(numberedHeadingLevels).sort((left, right) => left - right).join(","),
    [numberedHeadingLevels],
  );
  const headingStructurePlugin = useMemo(
    () => createHeadingStructurePlugin({
      headingAnchors,
      numberedLevels: numberedHeadingLevels,
      collapsibleLevels: collapsibleHeadingLevels,
    }),
    [collapsibleHeadingLevelsKey, headingAnchors, numberedHeadingLevelsKey],
  );
  const [internalCollapsedHeadingIds, setInternalCollapsedHeadingIds] = useState<Set<string>>(new Set());
  const collapsedHeadingIds = controlledCollapsedHeadingIds ?? internalCollapsedHeadingIds;
  const collapsedHeadingIdsRef = useRef(collapsedHeadingIds);

  useEffect(() => {
    collapsedHeadingIdsRef.current = collapsedHeadingIds;
  }, [collapsedHeadingIds]);

  useEffect(() => {
    if (!controlledCollapsedHeadingIds) {
      setInternalCollapsedHeadingIds(new Set());
    }
  }, [controlledCollapsedHeadingIds, processedContent]);

  const toggleHeadingCollapse = useCallback((id: string, source?: HTMLElement | null) => {
    const section = source?.closest<HTMLElement>(".markdown-collapsible-section[data-heading-section-id]");
    const nextCollapsed = section
      ? section.getAttribute("data-collapsed") !== "true"
      : !collapsedHeadingIdsRef.current.has(id);

    if (onHeadingCollapseChange?.(id, nextCollapsed, source ?? null) === true) {
      return;
    }

    if (applyHeadingCollapseDomState(id, nextCollapsed, source)) {
      return;
    }

    if (!controlledCollapsedHeadingIds) {
      setInternalCollapsedHeadingIds((prev) => {
        const next = new Set(prev);
        if (nextCollapsed) {
          next.add(id);
        } else {
          next.delete(id);
        }
        return next;
      });
    }
  }, [controlledCollapsedHeadingIds, onHeadingCollapseChange]);

  const makeHeading = (level: 1 | 2 | 3 | 4 | 5 | 6) => {
    const Tag = `h${level}` as const;
    return ({
      children,
      id: incomingId,
      ...props
    }: MarkdownHeadingComponentProps) => {
      const text = extractText(children);
      const dataHeadingId = readStringProp(props, "data-heading-id");
      const headingNumber = readStringProp(props, "data-heading-number");
      const id = incomingId || dataHeadingId || (headingAnchors ? nextHeadingId(text) : undefined);
      const headingId = dataHeadingId || id;
      const isCollapsible = Boolean(headingId) && collapsibleHeadingLevels.has(level);
      const isCollapsed = headingId ? collapsedHeadingIds.has(headingId) : false;
      return (
        <Tag
          id={id}
          data-heading-id={headingId}
          data-collapsible-heading={isCollapsible ? "true" : undefined}
          data-heading-collapsed={isCollapsible && isCollapsed ? "true" : undefined}
          className={cn(styles.heading[level], isCollapsible && "group/heading relative scroll-mt-24")}
        >
          {isCollapsible && headingId ? (
            <button
              type="button"
              data-heading-toggle="true"
              aria-label={isCollapsed ? "展开标题内容" : "折叠标题内容"}
              aria-expanded={!isCollapsed}
              title={isCollapsed ? "展开标题内容" : "折叠标题内容"}
              className={cn(
                "mr-1 inline-flex h-6 w-6 -ml-1 align-middle items-center justify-center rounded-md text-[#8F959E] transition-colors hover:bg-blue-50 hover:text-blue-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/35 sm:absolute sm:right-full sm:top-[0.16em] sm:mr-1.5 sm:ml-0",
                isCollapsed && "text-blue-600",
              )}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                toggleHeadingCollapse(headingId, event.currentTarget);
              }}
            >
              <ChevronRight
                aria-hidden="true"
                className="h-4 w-4 transition-transform duration-200"
              />
            </button>
          ) : null}
          {headingNumber ? (
            <span
              aria-hidden="true"
              data-heading-number={headingNumber}
              className="mr-1.5 inline-block select-none whitespace-nowrap text-[#1F2329] [-webkit-user-select:none] dark:text-slate-200"
            >
              {headingNumber}&nbsp;
            </span>
          ) : null}
          <span>{children}</span>
        </Tag>
      );
    };
  };

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath, remarkBlankTokens, remarkSafeHighlights, remarkCallouts, headingStructurePlugin]}
      rehypePlugins={[
        [rehypeKatex, { throwOnError: false, strict: false, errorColor: "#1F2329", output: "html" }],
        rehypeHighlight,
      ]}
      components={{
        h1: makeHeading(1),
        h2: makeHeading(2),
        h3: makeHeading(3),
        h4: makeHeading(4),
        h5: makeHeading(5),
        h6: makeHeading(6),
        section: ({ children, className, ...props }: MarkdownSectionComponentProps) => {
          const sectionId = readStringProp(props, "data-heading-section-id");
          const sectionLevel = readStringProp(props, "data-heading-section-level");
          const isHeadingSection = readStringProp(props, "data-heading-section") === "true";
          const isCollapsibleSection = readStringProp(props, "data-collapsible-section") === "true";
          const isCollapsed = sectionId ? collapsedHeadingIds.has(sectionId) : false;
          const sectionChildren = isCollapsibleSection ? Children.toArray(children) : [];
          return (
            <section
              data-heading-section={isHeadingSection ? "true" : undefined}
              data-heading-section-level={sectionLevel}
              data-heading-section-id={sectionId}
              data-collapsible-section={isCollapsibleSection ? "true" : undefined}
              data-collapsed={isCollapsibleSection && isCollapsed ? "true" : undefined}
              className={cn(isCollapsibleSection && "markdown-collapsible-section", className)}
            >
              {isCollapsibleSection ? (
                <>
                  {sectionChildren[0] ?? null}
                  {sectionChildren.length > 1 ? (
                    <div data-heading-section-body="true" className="contents">
                      {sectionChildren.slice(1)}
                    </div>
                  ) : null}
                </>
              ) : children}
            </section>
          );
        },
        p: ({ children }) => <p className={styles.paragraph}>{children}</p>,
        ul: ({ children }) => <ul className={styles.list}>{children}</ul>,
        ol: ({ children }) => <ol className={styles.orderedList}>{children}</ol>,
        li: ({ children }) => <li className={styles.listItem}>{children}</li>,
        blockquote: ({ children, ...props }: MarkdownBlockquoteComponentProps) => {
          const propKind = normalizeCalloutKind(readStringProp(props, "data-callout-kind"));
          const callout = propKind
            ? { kind: propKind, body: Children.toArray(children).filter((item) => item !== "\n") }
            : parseCallout(children);
          if (!callout) {
            return <blockquote className={styles.blockquote}>{children}</blockquote>;
          }

          const tone = CALLOUT_STYLES[variant][callout.kind];
          const calloutMeta = CALLOUT_META[callout.kind];
          const CalloutIcon = calloutMeta.Icon;
          return (
            <aside className={tone.shell}>
              <div className="mb-3 flex items-center gap-2">
                <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold tracking-[0.08em]", tone.badge)}>
                  <CalloutIcon className="h-3.5 w-3.5" />
                  {calloutMeta.label}
                </span>
              </div>
              <div className="[&>*:last-child]:mb-0">{callout.body}</div>
            </aside>
          );
        },
        code: ({ className, children }) => {
          const codeText = extractText(children).replace(/\n$/, "");
          const language =
            className?.match(/\blanguage-([A-Za-z0-9_-]+)/)?.[1]?.trim().toLowerCase() ??
            className?.trim().toLowerCase().replace(/^language-/, "") ??
            "";
          const isBlock = Boolean(className) || codeText.includes("\n");
          const normalizedCodeText = codeText.trim().replace(/^(maymaid|mermaind|mermaide)\b/i, "mermaid");
          const looksLikeMermaid = /^(mermaid|mindmap|flowchart|graph|sequenceDiagram|classDiagram|stateDiagram|erDiagram|gantt|pie|journey|timeline|gitGraph)\b/i.test(normalizedCodeText);

          if (MERMAID_LANGUAGE_ALIASES.has(language) || (!language && looksLikeMermaid)) {
            const mermaidChart = normalizedCodeText.replace(/^mermaid\s*/i, "").trimStart() || codeText;
            return <MermaidBlock chart={mermaidChart} variant={variant === "planner" ? "default" : variant} />;
          }

          if (isBlock) {
            const shouldRenderConflictBlock = looksLikeGitConflictBlock(codeText);

            return (
              <div className={styles.codeShell}>
                {language ? (
                  <div className={styles.codeLanguageBadge}>{language}</div>
                ) : null}
                <pre className={cn(styles.codePre, shouldRenderConflictBlock ? "px-0 py-3" : "")}>
                  <code className={cn("font-mono", className)}>
                    {shouldRenderConflictBlock ? renderGitConflictLines(codeText) : children}
                  </code>
                </pre>
              </div>
            );
          }

          return <code className={cn(styles.codeInline, className)}>{children}</code>;
        },
        pre: ({ children }) => <>{children}</>,
        table: ({ children }) => (
          <div className={styles.tableShell}>
            <table className={styles.table}>{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead className={styles.thead}>{children}</thead>,
        th: ({ children }) => <th className={styles.th}>{children}</th>,
        td: ({ children }) => <td className={styles.td}>{children}</td>,
        hr: () => <hr className={styles.hr} />,
        a: ({ href, children }) => (
          <a href={href} className={styles.link} target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        ),
        strong: ({ children }) => <strong className={styles.strong}>{children}</strong>,
        em: ({ children }) => <em className={styles.em}>{children}</em>,
        mark: ({ children }) => <mark className={styles.highlight}>{children}</mark>,
        img: ({ src, alt }) => {
          const resolvedSrc = resolveMarkdownImageSrc(src, {
            assetBaseUrl,
            assetCourse,
          });

          return (
            <MarkdownImage
              src={resolvedSrc}
              alt={alt}
              styles={styles}
            />
          );
        },
      }}
    >
      {processedContent}
    </ReactMarkdown>
  );
}

export type { MarkdownViewerProps, MarkdownViewerVariant };
