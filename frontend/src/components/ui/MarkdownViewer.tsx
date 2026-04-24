import { Children, useEffect, useMemo, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

import { cn } from "../../lib/utils";
import { MermaidBlock } from "./MermaidBlock";

type MarkdownViewerVariant = "default" | "document" | "planner";
type CalloutKind = "note" | "tip" | "important" | "warning" | "caution";
const CALLOUT_PATTERN = "note|tip|important|warning|caution";
const MERMAID_LANGUAGE_ALIASES = new Set(["mermaid", "maymaid", "mermaind", "mermaide"]);

interface MarkdownViewerProps {
  content: string;
  assetBaseUrl?: string;
  assetSubject?: string;
  variant?: MarkdownViewerVariant;
  headingAnchors?: boolean;
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
  imageShell: string;
  imageFrame: string;
  image: string;
  imageCaption: string;
}

const CALLOUT_LABELS: Record<CalloutKind, string> = {
  note: "提示",
  tip: "诀窍",
  important: "重点",
  warning: "注意",
  caution: "警告",
};

const CALLOUT_STYLES: Record<MarkdownViewerVariant, Record<CalloutKind, { shell: string; badge: string }>> = {
  default: {
    note: {
      shell: "my-4 rounded-2xl border border-sky-200 bg-sky-50/80 px-4 py-3 text-slate-700 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-slate-200",
      badge: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
    },
    tip: {
      shell: "my-4 rounded-2xl border border-emerald-200 bg-emerald-50/80 px-4 py-3 text-slate-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-slate-200",
      badge: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    },
    important: {
      shell: "my-4 rounded-2xl border border-violet-200 bg-violet-50/80 px-4 py-3 text-slate-700 dark:border-violet-500/30 dark:bg-violet-500/10 dark:text-slate-200",
      badge: "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300",
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
      shell: "my-5 rounded-lg border border-sky-200 bg-sky-50/70 px-4 py-3 text-[#1F2329] dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-slate-200",
      badge: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
    },
    tip: {
      shell: "my-5 rounded-lg border border-emerald-200 bg-emerald-50/70 px-4 py-3 text-[#1F2329] dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-slate-200",
      badge: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    },
    important: {
      shell: "my-5 rounded-lg border border-violet-200 bg-violet-50/70 px-4 py-3 text-[#1F2329] dark:border-violet-500/30 dark:bg-violet-500/10 dark:text-slate-200",
      badge: "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300",
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
      shell: "my-4 rounded-xl border border-sky-200 bg-sky-50/70 px-4 py-3 text-zinc-700 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-slate-200",
      badge: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
    },
    tip: {
      shell: "my-4 rounded-xl border border-emerald-200 bg-emerald-50/70 px-4 py-3 text-zinc-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-slate-200",
      badge: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    },
    important: {
      shell: "my-4 rounded-xl border border-violet-200 bg-violet-50/70 px-4 py-3 text-zinc-700 dark:border-violet-500/30 dark:bg-violet-500/10 dark:text-slate-200",
      badge: "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300",
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
    link: "text-blue-600 transition-colors hover:text-blue-700 hover:underline dark:text-sky-400 dark:hover:text-sky-300",
    strong: "font-semibold text-slate-900 dark:text-slate-100",
    em: "italic text-slate-600 dark:text-slate-300",
    imageShell: "my-5",
    imageFrame: "overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950/60",
    image: "max-h-[32rem] w-full object-contain bg-white dark:bg-slate-950/60",
    imageCaption: "mt-2 px-1 text-center text-xs text-slate-500 dark:text-slate-400",
  },
  document: {
    heading: {
      1: "mt-8 mb-4 pb-3 border-b border-[#DEE0E3] text-[30px] font-semibold leading-[1.3] tracking-[-0.02em] text-[#1F2329] dark:border-slate-700 dark:text-slate-100",
      2: "mt-7 mb-3 text-[24px] font-semibold leading-[1.4] tracking-[-0.015em] text-[#1F2329] dark:text-slate-100",
      3: "mt-6 mb-2.5 text-[20px] font-semibold leading-[1.5] text-[#1F2329] dark:text-slate-100",
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
    codeShell: "my-6 overflow-hidden rounded-2xl border border-[#D7DCE2] bg-[linear-gradient(180deg,#0f172a_0%,#111827_100%)] shadow-[0_22px_48px_-30px_rgba(15,23,42,0.58)] dark:border-slate-800",
    codeLanguageBadge: "border-b border-white/10 bg-[linear-gradient(180deg,rgba(255,255,255,0.08),rgba(255,255,255,0.02))] px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-300/90",
    codePre: "overflow-x-auto bg-[radial-gradient(circle_at_top_left,rgba(56,189,248,0.14),transparent_38%),linear-gradient(180deg,rgba(2,6,23,0.14),rgba(2,6,23,0))] px-4 py-4 text-[13px] leading-6 text-slate-100 font-mono",
    tableShell: "my-5 overflow-x-auto rounded-lg border border-[#DEE0E3] bg-white dark:border-slate-800 dark:bg-slate-950/60",
    table: "min-w-full text-[14px]",
    thead: "border-b border-[#DEE0E3] bg-[#F5F6F7] dark:border-slate-800 dark:bg-slate-900/80",
    th: "px-3 py-2 text-left text-[13px] font-semibold text-[#1F2329] dark:text-slate-100",
    td: "border-t border-[#F0F0F0] px-3 py-2.5 text-[#1F2329] dark:border-slate-800 dark:text-slate-300",
    hr: "my-7 border-[#DEE0E3] dark:border-slate-800",
    link: "text-[#3370FF] transition-colors hover:text-[#245BDB] hover:underline underline-offset-2 dark:text-sky-400 dark:hover:text-sky-300",
    strong: "font-semibold text-[#1F2329] dark:text-slate-100",
    em: "italic text-[#646A73] dark:text-slate-400",
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
    blockquote: "my-3 rounded-xl border border-violet-100 bg-violet-50/60 px-3 py-2.5 text-sm leading-6 text-zinc-700 dark:border-violet-500/30 dark:bg-violet-500/10 dark:text-slate-300",
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
    link: "text-blue-600 transition-colors hover:text-blue-700 hover:underline dark:text-sky-400 dark:hover:text-sky-300",
    strong: "font-semibold text-zinc-900 dark:text-slate-100",
    em: "italic text-zinc-600 dark:text-slate-300",
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
  return processed;
}

function trimBlankLines(lines: string[]): string[] {
  const next = [...lines];
  while (next.length > 0 && !next[0].trim()) next.shift();
  while (next.length > 0 && !next[next.length - 1].trim()) next.pop();
  return next;
}

function pushCanonicalCallout(target: string[], kind: string, bodyLines: string[]) {
  const body = trimBlankLines(bodyLines);
  target.push(`> [!${kind.toUpperCase()}]`);
  if (body.length === 0) {
    return;
  }
  for (const line of body) {
    target.push(line.trim() ? `> ${line}` : ">");
  }
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

function repairMalformedMermaidFencesForRender(markdown: string): string {
  if (!markdown.includes("```")) return markdown;

  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
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

function preprocessMarkdownContent(content: string): string {
  return repairMalformedMermaidFencesForRender(preprocessLaTeX(preprocessCalloutSyntax(content)));
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

function extractSubjectAssetPath(src: string): string | null {
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
    assetSubject,
  }: {
  assetBaseUrl?: string;
  assetSubject?: string;
}): string | undefined {
  if (!src) {
    return src;
  }

  if (assetSubject) {
    const assetPath = extractSubjectAssetPath(src);
    if (assetPath) {
      return `/api/v1/subjects/${encodeURIComponent(assetSubject)}/files/assets/${encodePathSegments(assetPath)}`;
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
  return typeof src === "string" && src.startsWith("/api/v1/subjects/") && src.includes("/files/assets/");
}

function isDocgenCoverAsset(src: string | undefined): boolean {
  return typeof src === "string" && /\/files\/assets\/docgen\/docgen_cover_/i.test(src);
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
    fetch(src, {
      credentials: "include",
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`asset fetch failed: ${response.status}`);
        }
        return response.blob();
      })
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setBlobSrc(objectUrl);
      })
      .catch(() => {
        setBlobSrc("");
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
  assetSubject,
  variant = "default",
  headingAnchors = false,
}: MarkdownViewerProps) {
  const processedContent = preprocessMarkdownContent(content);
  const styles = VIEWER_STYLES[variant];
  const nextHeadingId = useMemo(() => createHeadingIdFactory(), [processedContent]);

  const makeHeading = (level: 1 | 2 | 3 | 4 | 5 | 6) => {
    const Tag = `h${level}` as const;
    return ({ children }: { children?: ReactNode }) => {
      const text = extractText(children);
      const id = headingAnchors ? nextHeadingId(text) : undefined;
      return (
        <Tag
          id={id}
          data-heading-id={id}
          className={styles.heading[level]}
        >
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
        p: ({ children }) => <p className={styles.paragraph}>{children}</p>,
        ul: ({ children }) => <ul className={styles.list}>{children}</ul>,
        ol: ({ children }) => <ol className={styles.orderedList}>{children}</ol>,
        li: ({ children }) => <li className={styles.listItem}>{children}</li>,
        blockquote: ({ children }) => {
          const callout = parseCallout(children);
          if (!callout) {
            return <blockquote className={styles.blockquote}>{children}</blockquote>;
          }

          const tone = CALLOUT_STYLES[variant][callout.kind];
          return (
            <aside className={tone.shell}>
              <div className="mb-3 flex items-center gap-2">
                <span className={cn("rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em]", tone.badge)}>
                  {CALLOUT_LABELS[callout.kind]}
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
            return (
              <div className={styles.codeShell}>
                {language ? (
                  <div className={styles.codeLanguageBadge}>{language}</div>
                ) : null}
                <pre className={styles.codePre}>
                  <code className={cn("font-mono", className)}>{children}</code>
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
        img: ({ src, alt }) => {
          const resolvedSrc = resolveMarkdownImageSrc(src, {
            assetBaseUrl,
            assetSubject,
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
