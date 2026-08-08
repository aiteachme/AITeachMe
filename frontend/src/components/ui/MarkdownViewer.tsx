import { Children, isValidElement, useCallback, useEffect, useMemo, useRef, useState, type ComponentPropsWithoutRef, type FormEvent, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import {
  BadgeCheck,
  ChevronRight,
  CircleHelp,
  ExternalLink,
  Info,
  Lightbulb,
  Loader2,
  Maximize2,
  MousePointer2,
  OctagonAlert,
  RefreshCw,
  TriangleAlert,
  X,
  ZoomIn,
  ZoomOut,
  type LucideIcon,
} from "lucide-react";

import { getApiErrorMessage, runAnonymousApiFetch, runTrackedApiFetch } from "../../api/client";
import { parseInteractivePreviewHref, patchHtmlForIframe, type InteractiveHtmlPreview } from "../../lib/interactiveHtml";
import { rehypeMarkdownSanitize } from "../../lib/markdownSanitize";
import { cn } from "../../lib/utils";
import { MermaidBlock } from "./MermaidBlock";

type MarkdownViewerVariant = "default" | "document" | "planner";
type CalloutKind =
  | "note"
  | "tip"
  | "important"
  | "warning"
  | "caution"
  | "example"
  | "practice"
  | "question"
  | "answer";
type CollapsibleHeadings = boolean | readonly number[];
const CALLOUT_PATTERN = "note|tip|important|warning|caution|example|practice|question|answer";
const CALLOUT_FIELD_LABEL_PATTERN =
  "题目\\/任务|解析\\/判定依据|答案\\/结论|判定依据|正确答案|参考答案|题目|题干|任务|案例|例题|选项|解析|解法|思路|步骤|答案|结论|易错点|错因|注意";
const CALLOUT_FIELD_MARKER_RE = new RegExp(
  `(?<!\\*)\\s*(?:\\*\\*(?:${CALLOUT_FIELD_LABEL_PATTERN})\\*\\*|(?:${CALLOUT_FIELD_LABEL_PATTERN}))\\s*[：:]`,
  "g",
);
const CALLOUT_FIELD_SPLIT_RE = new RegExp(
  `(?<!\\*)(?=\\s*(?:\\*\\*(?:${CALLOUT_FIELD_LABEL_PATTERN})\\*\\*|(?:${CALLOUT_FIELD_LABEL_PATTERN}))\\s*[：:])`,
  "g",
);
const MERMAID_LANGUAGE_ALIASES = new Set(["mermaid", "maymaid", "mermaind", "mermaide"]);
const DOCUMENT_HIGHLIGHT_CHAR_LIMIT = 60_000;
const BLANK_TOKEN = "{{blank}}";
const BLANK_NODE_CLASS =
  "mx-1 inline-block h-[0.9em] min-w-16 border-b-2 border-current align-baseline";
const HIGHLIGHT_MARK_CLASS =
  "rounded-[2px] bg-[#FFF1B8] px-0.5 py-[0.08em] text-inherit dark:bg-amber-300/20";
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
const RAW_LATEX_MATH_COMMAND_RE =
  /\\(?:sqrt|frac|lim|sin|cos|tan|cot|ln|log|sum|int|Delta|delta|epsilon|varepsilon|theta|pi|infty|cup|cap|leq?|geq?|neq|to|sim|pm|cdot|times)\b/;
const RAW_LATEX_MATH_FRAGMENT_RE =
  /((?:[A-Za-z0-9_+\-*/=<>≤≥^{}()[\],.，、:：;； \t]|\\[A-Za-z]+|\\[{}])+\\(?:sqrt|frac|lim|sin|cos|tan|cot|ln|log|sum|int|Delta|delta|epsilon|varepsilon|theta|pi|infty|cup|cap|leq?|geq?|neq|to|sim|pm|cdot|times)\b(?:[A-Za-z0-9_+\-*/=<>≤≥^{}()[\],.，、:：;； \t]|\\[A-Za-z]+|\\[{}])*)/g;
const CALLOUT_LEADING_ICON_RE =
  /^[\s\uFE0F]*(?:(?:💡|📌|🎯|🔍|🧩|🚀|✨|✅|🔥|⭐|⚠️|⚠|❗|❌|⛔|🚫|📝|🔗|📚)\s*)+/u;
const INTERACTIVE_MARKER_RE = /<!--\s*ATM_INTERACTIVE_(?:OVERLAY|PLAN):[\s\S]*?-->\s*/g;
const INTERACTIVE_LOADING_STEPS = [
  "正在排队进入统一 LLM 调度器",
  "正在生成单文件 HTML",
  "正在校验 HTML 结构与资源边界",
  "正在加载沙箱预览",
];
const DUPLICATE_ORDERED_LIST_MARKER_RE = /^(\s{0,3}(?:>\s*)*)\d+[\.)\u3001\uff09]\s+(?=\d+[\.)\u3001\uff09]\s+)/;

function noopMarkdownPlugin() {
  return undefined;
}

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
  publicMode?: boolean;
  allowRawHtml?: boolean;
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

type ImagePreviewState = {
  src: string;
  title: string;
};

const CALLOUT_META: Record<CalloutKind, { label: string; Icon: LucideIcon }> = {
  note: { label: "提示", Icon: Info },
  tip: { label: "诀窍", Icon: Lightbulb },
  important: { label: "重点", Icon: BadgeCheck },
  warning: { label: "注意", Icon: TriangleAlert },
  caution: { label: "警告", Icon: OctagonAlert },
  example: { label: "例题", Icon: BadgeCheck },
  practice: { label: "练习", Icon: Lightbulb },
  question: { label: "题目", Icon: CircleHelp },
  answer: { label: "答案", Icon: BadgeCheck },
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
    example: {
      shell: "my-4 rounded-2xl border border-violet-200 bg-violet-50/75 px-4 py-3 text-slate-700 dark:border-violet-500/30 dark:bg-violet-500/10 dark:text-slate-200",
      badge: "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300",
    },
    practice: {
      shell: "my-4 rounded-2xl border border-teal-200 bg-teal-50/75 px-4 py-3 text-slate-700 dark:border-teal-500/30 dark:bg-teal-500/10 dark:text-slate-200",
      badge: "bg-teal-100 text-teal-700 dark:bg-teal-500/15 dark:text-teal-300",
    },
    question: {
      shell: "my-5 rounded-xl border border-slate-200 bg-slate-50 px-4 py-4 text-slate-800 shadow-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100",
      badge: "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900",
    },
    answer: {
      shell: "my-4 rounded-xl border border-slate-200 bg-white px-4 py-3 text-slate-800 shadow-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100",
      badge: "bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300",
    },
  },
  document: {
    note: {
      shell: "my-5 rounded-lg border border-[#E1ECFA] bg-[#F5F9FF] px-4 py-3.5 text-[#1F2329] dark:border-blue-500/20 dark:bg-blue-500/10 dark:text-slate-200",
      badge: "text-[#245FD6] dark:text-blue-300",
    },
    tip: {
      shell: "my-5 rounded-lg border border-[#DFEFE7] bg-[#F4FAF7] px-4 py-3.5 text-[#1F2329] dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-slate-200",
      badge: "text-[#087A4A] dark:text-emerald-300",
    },
    important: {
      shell: "my-5 rounded-lg border border-[#DCEDEF] bg-[#F3FAFB] px-4 py-3.5 text-[#1F2329] dark:border-cyan-500/20 dark:bg-cyan-500/10 dark:text-slate-200",
      badge: "text-[#0891B2] dark:text-cyan-300",
    },
    warning: {
      shell: "my-5 rounded-lg border border-[#F3E8CD] bg-[#FFF9ED] px-4 py-3.5 text-[#1F2329] dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-slate-200",
      badge: "text-[#B45309] dark:text-amber-300",
    },
    caution: {
      shell: "my-5 rounded-lg border border-[#F1DEDE] bg-[#FFF6F6] px-4 py-3.5 text-[#1F2329] dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-slate-200",
      badge: "text-[#C81E1E] dark:text-rose-300",
    },
    example: {
      shell: "my-5 rounded-lg border border-[#E7E1F4] bg-[#F7F5FC] px-4 py-3.5 text-[#1F2329] dark:border-violet-500/20 dark:bg-violet-500/10 dark:text-slate-200",
      badge: "text-[#6D28D9] dark:text-violet-300",
    },
    practice: {
      shell: "my-5 rounded-lg border border-[#DCEDE7] bg-[#F3FAF8] px-4 py-3.5 text-[#1F2329] dark:border-teal-500/20 dark:bg-teal-500/10 dark:text-slate-200",
      badge: "text-[#0F766E] dark:text-teal-300",
    },
    question: {
      shell: "my-6 rounded-lg border border-[#DDE3EC] border-l-[3px] border-l-[#3370FF] bg-[#FBFCFE] px-4 py-4 text-[#1F2329] dark:border-slate-700 dark:border-l-blue-400 dark:bg-slate-950/80 dark:text-slate-100 sm:px-5",
      badge: "text-[#245BDB] dark:text-blue-300",
    },
    answer: {
      shell: "my-4 rounded-lg border border-[#DDE3EC] bg-white px-4 py-4 text-[#1F2329] dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 sm:px-5",
      badge: "text-[#245FD6] dark:text-blue-300",
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
    example: {
      shell: "my-4 rounded-xl border border-violet-200 bg-violet-50/70 px-4 py-3 text-zinc-700 dark:border-violet-500/30 dark:bg-violet-500/10 dark:text-slate-200",
      badge: "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300",
    },
    practice: {
      shell: "my-4 rounded-xl border border-teal-200 bg-teal-50/70 px-4 py-3 text-zinc-700 dark:border-teal-500/30 dark:bg-teal-500/10 dark:text-slate-200",
      badge: "bg-teal-100 text-teal-700 dark:bg-teal-500/15 dark:text-teal-300",
    },
    question: {
      shell: "my-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-zinc-800 shadow-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100",
      badge: "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900",
    },
    answer: {
      shell: "my-4 rounded-xl border border-slate-200 bg-white px-4 py-3 text-zinc-800 shadow-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100",
      badge: "bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300",
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
      1: "mb-7 mt-4 text-[30px] font-semibold leading-[1.28] tracking-[-0.015em] text-[#1F2329] [overflow-wrap:anywhere] dark:text-slate-100 sm:mb-8 sm:mt-5 sm:text-[36px] sm:leading-[1.22]",
      2: "mb-4 mt-10 text-[24px] font-semibold leading-[1.38] tracking-[-0.01em] text-[#1F2329] [overflow-wrap:anywhere] dark:text-slate-100 sm:mt-11 sm:text-[27px]",
      3: "mb-3 mt-8 text-[19px] font-semibold leading-[1.48] text-[#1F2329] [overflow-wrap:anywhere] dark:text-slate-100 sm:text-[21px]",
      4: "mb-2.5 mt-7 text-[17px] font-semibold leading-[1.55] text-[#242933] [overflow-wrap:anywhere] dark:text-slate-100 sm:text-[18px]",
      5: "mt-5 mb-2 text-[16px] font-semibold leading-[1.58] text-[#373C43] [overflow-wrap:anywhere] dark:text-slate-300",
      6: "mt-4 mb-1.5 text-[14px] font-semibold leading-[1.58] text-[#646A73] [overflow-wrap:anywhere] dark:text-slate-400",
    },
    paragraph: "mb-4 text-[16px] leading-[1.76] text-[#2F343D] dark:text-slate-300",
    list: "my-4 list-disc space-y-1.5 pl-[1.5rem] text-[16px] leading-[1.76] text-[#2F343D] marker:text-[#8F959E] dark:text-slate-300 dark:marker:text-slate-500",
    orderedList: "my-4 list-decimal space-y-1.5 pl-[1.5rem] text-[16px] leading-[1.76] text-[#2F343D] marker:font-medium marker:text-[#8F959E] dark:text-slate-300 dark:marker:text-slate-500",
    listItem: "pl-1 leading-[1.76] [&>ol]:mt-2 [&>p]:mb-1 [&>p]:block [&>ul]:mt-2",
    blockquote: "my-6 rounded-r-md border-l-2 border-[#8F959E] bg-[#F7F8FA]/80 px-4 py-3 text-[16px] leading-[1.74] text-[#4E5969] dark:border-slate-500 dark:bg-slate-900/45 dark:text-slate-300",
    codeInline: "whitespace-normal break-words rounded-[3px] bg-[#F2F3F5] px-1.5 py-0.5 font-mono text-[0.86em] text-[#24292F] [overflow-wrap:anywhere] dark:bg-slate-800 dark:text-slate-100",
    codeShell: "relative my-6 overflow-hidden rounded-md border border-[#E1E4E8] bg-[#F6F8FA] dark:border-slate-800 dark:bg-slate-950",
    codeLanguageBadge: "absolute right-3 top-2 z-10 text-[10px] font-medium uppercase tracking-[0.08em] text-[#8F959E] dark:text-slate-500",
    codePre: "overflow-x-auto bg-[#F6F8FA] px-4 py-3.5 font-mono text-[13px] leading-[1.65] text-[#24292F] dark:bg-slate-950 dark:text-slate-100",
    tableShell: "my-6 overflow-x-auto rounded-md border border-[#DDE1E6] bg-white dark:border-slate-800 dark:bg-slate-950/60",
    table: "w-full min-w-[560px] border-collapse text-[14px] sm:text-[15px]",
    thead: "bg-[#F5F6F7] dark:bg-slate-900/80",
    th: "border-r border-[#E1E4E8] px-3 py-2.5 text-left text-[13px] font-semibold leading-6 text-[#1F2329] last:border-r-0 dark:border-slate-800 dark:text-slate-100 sm:px-4 sm:text-[14px]",
    td: "border-t border-[#E1E4E8] px-3 py-2.5 leading-6 text-[#2F343D] dark:border-slate-800 dark:text-slate-300 sm:px-4",
    hr: "my-9 border-[#DEE0E3] dark:border-slate-800",
    link: "text-[#2563EB] transition-colors hover:text-[#1D4ED8] hover:underline underline-offset-2 dark:text-blue-300 dark:hover:text-blue-200",
    strong: "font-semibold text-[#1F2329] dark:text-slate-100",
    em: "italic text-[#646A73] dark:text-slate-400",
    highlight: HIGHLIGHT_MARK_CLASS,
    imageShell: "my-7",
    imageFrame: "overflow-hidden rounded-lg border border-[#DEE0E3] bg-white dark:border-slate-800 dark:bg-slate-950/60",
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
  processed = wrapBareLatexMathFragments(processed);
  return normalizeBareLatexTextCommands(processed);
}

function wrapBareLatexMathInText(text: string): string {
  if (!RAW_LATEX_MATH_COMMAND_RE.test(text)) return text;
  RAW_LATEX_MATH_COMMAND_RE.lastIndex = 0;
  return text.replace(RAW_LATEX_MATH_FRAGMENT_RE, (match: string) => {
    RAW_LATEX_MATH_COMMAND_RE.lastIndex = 0;
    if (!RAW_LATEX_MATH_COMMAND_RE.test(match)) return match;
    if (/[\u4e00-\u9fff]/.test(match)) return match;
    const leadingChoice = match.match(/^(\s*[A-Da-d][.)、:：]\s*)(.+)$/s);
    const prefix = leadingChoice?.[1] ?? "";
    const body = (leadingChoice?.[2] ?? match).trim();
    if (!body || body.startsWith("$") || body.endsWith("$")) return match;
    return `${prefix}$${body}$`;
  });
}

function wrapBareLatexOutsideInlineMathAndCode(markdown: string): string {
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
    output.push(wrapBareLatexMathInText(source.slice(index, next)));
    index = next;
  }

  return output.join("");
}

function wrapBareLatexMathFragments(markdown: string): string {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const output: string[] = [];
  let activeFence: string | null = null;
  let plainChunk: string[] = [];

  const flushPlainChunk = () => {
    if (plainChunk.length === 0) return;
    output.push(wrapBareLatexOutsideInlineMathAndCode(plainChunk.join("\n")));
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

  const normalizeHighlightBody = (body: string) => {
    const text = String(body || "").trim();
    const emphasis = text.match(/^(\*\*|__)\s*([^\n]+?)\s*\1$/);
    return (emphasis?.[2] ?? text).trim();
  };

  const normalizeLine = (line: string) => {
    const parts = line.split(/(`+[^`]*`+)/g);
    return parts
      .map((part) => {
        if (part.startsWith("`") && part.endsWith("`")) return part;
        return part
          .replace(/<mark\b[^>]*>\s*([^<>\n]{1,160}?)\s*<\/mark>/gi, (_match, body: string) => {
            const text = normalizeHighlightBody(body);
            return text ? `==${text}==` : "";
          })
          .replace(/==\s*([^=\n]{1,160}?)\s*==/g, (_match, body: string) => {
            const text = normalizeHighlightBody(body);
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

function splitCalloutLearningFields(line: string): string[] {
  const stripped = String(line || "").trim();
  if (!stripped) return [line];
  if (/^(?:[-*+]|\d+\.)\s+/.test(stripped)) return [line];
  const markerCount = Array.from(stripped.matchAll(CALLOUT_FIELD_MARKER_RE)).length;
  if (markerCount < 2) return [line];
  const parts = stripped.split(CALLOUT_FIELD_SPLIT_RE).map((part) => part.trim()).filter(Boolean);
  return parts.length > 1 ? parts : [line];
}

function normalizeCalloutBodyLines(lines: string[]): string[] {
  const body = trimBlankLines(lines);
  const firstContentIndex = body.findIndex((line) => line.trim().length > 0);
  if (firstContentIndex >= 0) {
    body[firstContentIndex] = stripLeadingCalloutIcon(body[firstContentIndex]);
  }
  const normalized: string[] = [];
  for (const line of body) {
    const parts = splitCalloutLearningFields(line);
    if (parts.length <= 1) {
      normalized.push(line);
      continue;
    }
    if (normalized.length > 0 && normalized[normalized.length - 1].trim()) {
      normalized.push("");
    }
    parts.forEach((part, index) => {
      if (index > 0) normalized.push("");
      normalized.push(part);
    });
  }
  return trimBlankLines(normalized);
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
  if (/^(classDef|class|style|linkStyle|click|subgraph|end|direction|accTitle|accDescr|title)\b/i.test(trimmed)) return true;
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

function inlineMathBodyNeedsDisplayStyle(body: string): boolean {
  const trimmed = body.trim();
  return (
    /\\(?:frac|dfrac|tfrac|lim|sum|prod|int|binom)\b/.test(trimmed) ||
    /\\begin\{(?:cases|matrix|pmatrix|bmatrix|aligned|alignedat)\}/.test(trimmed)
  );
}

function makeInlineMathReadableForRender(body: string): string {
  const trimmed = body.trim();
  if (!trimmed || !inlineMathBodyNeedsDisplayStyle(trimmed)) return body;
  if (/\\(?:displaystyle|textstyle|scriptstyle|scriptscriptstyle)\b/.test(trimmed)) return body;
  if (/^\\dfrac\b/.test(trimmed)) return body;
  return `\\displaystyle ${trimmed}`;
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
    const normalizedBody = body.trim();
    if (inlineMathBodyLooksUnsafe(body)) {
      output.push("\\$", body, "\\$");
      changed = true;
    } else {
      const readableBody = makeInlineMathReadableForRender(normalizedBody);
      if (body !== normalizedBody || readableBody !== normalizedBody) {
        output.push("$", readableBody, "$");
        changed = true;
      } else {
        output.push(working.slice(left, right + 1));
      }
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

function normalizeLegacyNonChoiceUnitTestsForRender(markdown: string): string {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const output: string[] = [];
  let legacyOptions: string[] | null = null;
  let awaitingAnswerValue = false;

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const questionHeader = line.match(
      /^\s*>\s*\[!QUESTION\]\s+\*\*Q\d+\s*[｜|]\s*([^｜|]+)\s*[｜|]/i,
    );
    if (questionHeader) {
      const questionType = questionHeader[1].trim();
      legacyOptions = /^(填空题|短答题)$/.test(questionType) ? [] : null;
      awaitingAnswerValue = false;
      output.push(line);
      continue;
    }

    if (legacyOptions && /^\s*>\s*\*\*选项\*\*\s*$/.test(line)) {
      if (/^\s*>\s*$/.test(output[output.length - 1] ?? "")) output.pop();
      for (index += 1; index < lines.length; index += 1) {
        const optionLine = lines[index];
        if (/^\s*>\s*$/.test(optionLine)) continue;
        const option = optionLine.match(/^\s*>\s*-\s*([A-D])[.、:：]\s*(.+?)\s*$/i);
        if (!option) {
          index -= 1;
          break;
        }
        legacyOptions[option[1].toUpperCase().charCodeAt(0) - 65] = option[2].trim();
      }
      continue;
    }

    if (legacyOptions && /^\s*>\s*\*\*答案\*\*\s*$/.test(line)) {
      awaitingAnswerValue = true;
      output.push(line);
      continue;
    }

    if (legacyOptions && awaitingAnswerValue && !/^\s*>\s*$/.test(line)) {
      const answer = line.match(/^(\s*>\s*)(?:选项\s*)?([A-D])(?:[.、:：])?\s*$/i);
      if (answer) {
        const resolved = legacyOptions[answer[2].toUpperCase().charCodeAt(0) - 65];
        output.push(resolved ? `${answer[1]}${resolved}` : line);
      } else {
        output.push(line);
      }
      awaitingAnswerValue = false;
      continue;
    }

    output.push(line);
  }

  return output.join("\n");
}

export function preprocessMarkdownForRender(content: string): string {
  return repairMalformedMermaidFencesForRender(
    normalizeListEmbeddedHeadingsForRender(
      protectTableInlineMathPipesForRender(
        repairMathDelimitersForRender(
          preprocessLaTeX(
            normalizeHighlightSyntaxForRender(
              preprocessCalloutSyntax(
                normalizeDuplicateOrderedListMarkersForRender(
                  normalizeLegacyNonChoiceUnitTestsForRender(content.replace(INTERACTIVE_MARKER_RE, "")),
                ),
              ),
            ),
          ),
        ),
      ),
    ),
  );
}

function normalizeDuplicateOrderedListMarkersForRender(content: string): string {
  const lines = String(content ?? "").replace(/\r\n?/g, "\n").split("\n");
  let inFence = false;
  return lines
    .map((line) => {
      if (/^\s*```/.test(line)) {
        inFence = !inFence;
        return line;
      }
      if (inFence) {
        return line;
      }
      return line.replace(DUPLICATE_ORDERED_LIST_MARKER_RE, "$1");
    })
    .join("\n");
}

function preprocessMarkdownContent(content: string): string {
  return preprocessMarkdownForRender(content);
}

function hasLikelyMathContent(content: string): boolean {
  return /\\[([]/.test(content) || /\$\$/.test(content) || hasLikelyInlineDollarMath(content);
}

function hasLikelyInlineDollarMath(content: string): boolean {
  const source = String(content || "");
  let start = findNextUnescaped(source, "$", 0);

  while (start >= 0) {
    if (source.startsWith("$$", start)) {
      start = findNextUnescaped(source, "$", start + 2);
      continue;
    }

    const end = findNextUnescaped(source, "$", start + 1);
    if (end < 0) {
      return false;
    }

    const body = source.slice(start + 1, end);
    const nextChar = source[end + 1] ?? "";
    if (
      isLikelyInlineMathBody(body) &&
      !/[A-Za-z0-9_]/.test(nextChar)
    ) {
      return true;
    }

    start = findNextUnescaped(source, "$", end + 1);
  }

  return false;
}

function isLikelyInlineMathBody(body: string): boolean {
  if (!body || body.length > 240 || body.includes("\n") || body.trim() !== body) {
    return false;
  }
  if (body.length === 1) {
    return /[A-Za-z\u0370-\u03ff]/.test(body);
  }
  return true;
}

function hasLikelyHighlightableCode(content: string): boolean {
  return /(^|\n)(```|~~~)/.test(content) || /(^|\n)(?: {4}|\t)\S/.test(content);
}

function hasLikelyRawHtmlContent(content: string): boolean {
  return /<!--/.test(content) || /<\/?[a-z][\w:-]*(?:\s[^>]*)?>/i.test(content);
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
    normalized === "caution" ||
    normalized === "example" ||
    normalized === "practice" ||
    normalized === "question" ||
    normalized === "answer"
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
  const match = String(firstText.value ?? "").match(
    /^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION|EXAMPLE|PRACTICE|QUESTION|ANSWER)\][ \t]*/i,
  );
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

function splitTextNodeBySoftBreaks(node: MarkdownAstNode): MarkdownAstNode[] {
  const value = String(node.value ?? "");
  if (!value.includes("\n")) {
    return [node];
  }

  const parts = value.split("\n");
  const nodes: MarkdownAstNode[] = [];
  parts.forEach((part, index) => {
    if (index > 0) {
      nodes.push({ type: "break" });
    }
    if (part) {
      nodes.push({ ...node, value: part });
    }
  });
  return nodes;
}

function remarkDocumentSoftBreaks() {
  return (tree: MarkdownAstNode) => {
    const visit = (node: MarkdownAstNode) => {
      const children = node.children;
      if (!Array.isArray(children)) {
        return;
      }

      if (node.type === "paragraph") {
        node.children = children.flatMap((child) => (
          child.type === "text" ? splitTextNodeBySoftBreaks(child) : [child]
        ));
        return;
      }

      for (const child of children) {
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
  return parts.map(String).join(".");
}

function escapeRegExpLiteral(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function headingTextAlreadyStartsWithNumber(text: string, headingNumber: string): boolean {
  const normalizedText = text.trim().replace(/\u00a0/g, " ");
  const normalizedNumber = headingNumber.trim().replace(/\.$/, "");
  if (!normalizedText || !normalizedNumber) {
    return false;
  }
  const prefixPattern = new RegExp(`^${escapeRegExpLiteral(normalizedNumber)}(?:\\s+|[、:：\\-]|(?=[^\\d.])|$)`);
  return prefixPattern.test(normalizedText);
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
      const headingNumber = formatHeadingNumber(level, counters);
      const text = extractMarkdownAstText(node);
      if (headingTextAlreadyStartsWithNumber(text, headingNumber)) {
        return;
      }
      const hProperties = {
        ...(node.data?.hProperties ?? {}),
        "data-heading-number": headingNumber,
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
  const normalized = value.trim();
  return /^[a-z][a-z0-9+.-]*:/i.test(normalized) || normalized.startsWith("//") || normalized.startsWith("/");
}

function isSafeRelativeAssetPath(value: string): boolean {
  const segments = value.replace(/\\/g, "/").split("/").filter(Boolean);
  return segments.length > 0 && segments.every((segment) => segment !== "." && segment !== "..");
}

function encodePathSegments(path: string): string {
  return path
    .split("/")
    .filter(Boolean)
    .map((part) => encodeURIComponent(part))
    .join("/");
}

function extractCourseAssetPath(src: string): string | null {
  const normalizedRaw = src.replace(/\\/g, "/").trim();
  if (!normalizedRaw || /^[a-z][a-z0-9+.-]*:/i.test(normalizedRaw) || normalizedRaw.startsWith("//")) {
    return null;
  }
  try {
    const url = new URL(normalizedRaw, "http://localhost");
    const assetParam = url.searchParams.get("asset");
    if (assetParam) {
      return assetParam.replace(/^\/+/, "");
    }
  } catch {
    // Fall through to path-based extraction.
  }

  const normalized = normalizedRaw.split("#")[0]?.split("?")[0]?.trim() ?? "";

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
    publicMode = false,
  }: {
  assetBaseUrl?: string;
  assetCourse?: string;
  publicMode?: boolean;
}): string | undefined {
  if (!src) {
    return src;
  }

  const assetPath = extractCourseAssetPath(src);
  if (publicMode && assetPath && !isSafeRelativeAssetPath(assetPath)) {
    return undefined;
  }
  if (publicMode && !assetBaseUrl) {
    return undefined;
  }
  if (assetCourse && !publicMode) {
    if (assetPath) {
      return `/api/v1/courses/${encodeURIComponent(assetCourse)}/files/assets/${encodePathSegments(assetPath)}`;
    }
  }
  if (assetBaseUrl && assetPath) {
    return `${assetBaseUrl.replace(/\/$/, "")}/${encodePathSegments(assetPath)}`;
  }

  if (publicMode && isAbsoluteAssetUrl(src)) {
    return undefined;
  }

  if (!assetBaseUrl || isAbsoluteAssetUrl(src)) {
    return src;
  }

  const cleanSrc = src.split("#")[0]?.split("?")[0] ?? src;
  const normalized = cleanSrc.replace(/\\/g, "/").trim();
  const pathParts = normalized.split("/").filter(Boolean);
  const filename = pathParts[pathParts.length - 1];

  if (!filename) {
    return publicMode ? undefined : src;
  }

  const looksLikeAssetPath =
    !normalized.includes("/") ||
    normalized.startsWith("images/") ||
    normalized.startsWith("../assets/") ||
    normalized.startsWith("./") ||
    normalized.startsWith("../");

  if (!looksLikeAssetPath) {
    return publicMode ? undefined : src;
  }

  const publicAssetPath = normalized
    .replace(/^(\.\/)+/, "")
    .replace(/^(\.\.\/)+assets\//, "")
    .replace(/^assets\//, "");
  if (publicMode && !isSafeRelativeAssetPath(publicAssetPath)) {
    return undefined;
  }
  const resolvedPath = publicMode ? publicAssetPath : filename;

  return `${assetBaseUrl.replace(/\/$/, "")}/${encodePathSegments(resolvedPath)}`;
}

function resolvePublicMarkdownAssetHref(
  href: string | undefined,
  assetBaseUrl: string | undefined,
): string | undefined {
  if (!href || !assetBaseUrl) {
    return href;
  }
  const assetPath = extractCourseAssetPath(href);
  if (!assetPath) {
    return href;
  }
  if (!isSafeRelativeAssetPath(assetPath)) {
    return undefined;
  }
  return `${assetBaseUrl.replace(/\/$/, "")}/${encodePathSegments(assetPath)}`;
}

function toPublicInteractivePreview(
  preview: InteractiveHtmlPreview,
  assetBaseUrl: string | undefined,
): InteractiveHtmlPreview | null {
  if (!assetBaseUrl || preview.mode !== "asset" || !preview.assetPath) {
    return null;
  }
  const assetUrl = `${assetBaseUrl.replace(/\/$/, "")}/${encodePathSegments(preview.assetPath)}`;
  return {
    ...preview,
    previewUrl: assetUrl,
    assetUrl,
  };
}

function patchPublicHtmlForIframe(html: string): string {
  const sanitized = html
    .replace(/<script\b[\s\S]*?<\/script>/gi, "")
    .replace(/\s+on[a-z]+\s*=\s*(['"])[\s\S]*?\1/gi, "")
    .replace(/\s+srcdoc\s*=\s*(['"])[\s\S]*?\1/gi, "")
    .replace(/\s+(href|src)\s*=\s*(['"])\s*(?:javascript:|data:text\/html)[\s\S]*?\2/gi, ' $1="#"');
  const csp =
    '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data: blob:; style-src \'unsafe-inline\'; font-src data:; base-uri \'none\'; form-action \'none\'">';
  const htmlWithCsp = /<head(?:\s[^>]*)?>/i.test(sanitized)
    ? sanitized.replace(/<head(?:\s[^>]*)?>/i, (match) => `${match}${csp}`)
    : `${csp}${sanitized}`;
  return patchHtmlForIframe(htmlWithCsp);
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
  onOpenPreview,
  publicMode = false,
}: {
  src: string | undefined;
  alt: string | undefined;
  styles: ViewerStyles;
  onOpenPreview: (preview: ImagePreviewState) => void;
  publicMode?: boolean;
}) {
  const [blobSrc, setBlobSrc] = useState("");
  const isCover = isDocgenCoverAsset(src);
  const isPublicShareAsset =
    publicMode && typeof src === "string" && src.startsWith("/api/v1/course-shares/");
  const displaySrc = blobSrc || (publicMode ? "" : src || "");

  useEffect(() => {
    if (publicMode && !isPublicShareAsset) {
      setBlobSrc("");
      return;
    }
    if (!isPublicShareAsset && !shouldFetchAuthorizedAsset(src)) {
      setBlobSrc("");
      return;
    }
    if (!isPublicShareAsset && !getBearerToken()) {
      setBlobSrc("");
      return;
    }

    const controller = new AbortController();
    let objectUrl = "";
    const consumeAsset = async (response: Response) => {
      if (!response.ok) {
        throw new Error(`asset fetch failed: ${response.status}`);
      }
      return response.blob();
    };
    const request = isPublicShareAsset
      ? runAnonymousApiFetch(
          src,
          { method: "GET", signal: controller.signal, cache: "no-store" },
          consumeAsset,
          "public_markdown_asset_disconnect",
        )
      : runTrackedApiFetch(
          src,
          { method: "GET", signal: controller.signal },
          consumeAsset,
          "markdown_asset_disconnect",
        );
    request
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
  }, [isPublicShareAsset, publicMode, src]);

  return (
    <figure className={styles.imageShell}>
      <button
        type="button"
        disabled={!displaySrc}
        onClick={() => {
          if (!displaySrc) return;
          onOpenPreview({ src: displaySrc, title: alt || "图片" });
        }}
        className={cn(
          styles.imageFrame,
          "group relative block w-full text-left outline-none transition focus-visible:ring-2 focus-visible:ring-indigo-500/40",
          displaySrc && "cursor-zoom-in",
          isCover && "rounded-xl",
        )}
      >
        <img
          src={displaySrc || undefined}
          alt={alt ?? ""}
          className={cn(
            styles.image,
            isCover && "aspect-[16/7] max-h-none object-cover",
          )}
          loading="lazy"
          decoding="async"
          referrerPolicy={publicMode ? "no-referrer" : undefined}
        />
        {displaySrc ? (
          <span className="pointer-events-none absolute right-3 top-3 inline-flex h-8 items-center gap-1.5 rounded-full border border-white/70 bg-slate-950/70 px-2.5 text-xs font-medium text-white opacity-0 shadow-sm backdrop-blur transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
            <Maximize2 className="h-3.5 w-3.5" />
            查看
          </span>
        ) : null}
      </button>
      {alt ? <figcaption className={styles.imageCaption}>{alt}</figcaption> : null}
    </figure>
  );
}

function PublicMarkdownAssetLink({
  href,
  className,
  children,
}: {
  href: string;
  className: string;
  children: ReactNode;
}) {
  const [blobHref, setBlobHref] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl = "";
    runAnonymousApiFetch(
      href,
      { method: "GET", signal: controller.signal, cache: "no-store" },
      async (response) => {
        if (!response.ok) {
          throw new Error(`asset fetch failed: ${response.status}`);
        }
        return response.blob();
      },
      "public_markdown_link_asset_disconnect",
    )
      .then((blob) => {
        if (controller.signal.aborted) {
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        setBlobHref(objectUrl);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setBlobHref("");
        }
      });

    return () => {
      controller.abort();
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [href]);

  return (
    <a
      href={blobHref || undefined}
      className={className}
      target="_blank"
      rel="noopener noreferrer"
      referrerPolicy="no-referrer"
      aria-disabled={!blobHref}
      onClick={(event) => {
        if (!blobHref) {
          event.preventDefault();
        }
      }}
    >
      {children}
    </a>
  );
}

function InteractiveHtmlEmbed({
  preview,
  label,
  publicMode = false,
}: {
  preview: InteractiveHtmlPreview;
  label: ReactNode;
  publicMode?: boolean;
}) {
  const isStaticFigure = preview.kind === "figure";
  const [expanded, setExpanded] = useState(true);
  const [generatedPreview, setGeneratedPreview] = useState<InteractiveHtmlPreview | null>(null);
  const [html, setHtml] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingLabel, setLoadingLabel] = useState(isStaticFigure ? "正在加载图示..." : "正在加载交互页...");
  const [loadingStepIndex, setLoadingStepIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const [isRegenerateFormOpen, setIsRegenerateFormOpen] = useState(false);
  const [regeneratePrompt, setRegeneratePrompt] = useState("");
  const regenerateControllerRef = useRef<AbortController | null>(null);
  const activePreview = generatedPreview ?? preview;
  const canRegenerate = !publicMode && !isStaticFigure && Boolean(preview.anchorId && (preview.selectedText || preview.title));
  const loadingStepLabel = isStaticFigure ? "正在读取静态图示资产" : INTERACTIVE_LOADING_STEPS[loadingStepIndex % INTERACTIVE_LOADING_STEPS.length];

  const requestInteractiveAsset = useCallback(
    async (options: {
      signal: AbortSignal;
      prompt?: string;
      clientReferenceId?: string;
      forceRegenerate?: boolean;
      replaceOverlayId?: string;
    }) => {
      const selectedText = preview.selectedText || preview.title;
      const clientReferenceId = options.clientReferenceId || preview.clientReferenceId || preview.planId;
      const generated = await runTrackedApiFetch(
        `/api/v1/courses/${encodeURIComponent(preview.courseId)}/knowledge/docs/interactive-selections`,
        {
          method: "POST",
          signal: options.signal,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            anchor_id: preview.anchorId,
            selected_text: selectedText,
            prompt: options.prompt?.trim() || undefined,
            client_reference_id: clientReferenceId || undefined,
            force_regenerate: options.forceRegenerate || undefined,
            replace_overlay_id: options.replaceOverlayId || undefined,
            selection_context: {
              selected_text: selectedText,
              anchor_id: preview.anchorId,
              anchor_title: preview.title,
              heading_path: [preview.title],
              section_title: preview.title,
              section_excerpt: selectedText,
            },
          }),
        },
        async (response) => {
          const payload = await response.json().catch(() => null) as {
            data?: { preview_url?: string };
            detail?: string;
            message?: string;
          } | null;
          if (!response.ok) {
            throw new Error(payload?.detail || payload?.message || `HTTP ${response.status}`);
          }
          return payload?.data?.preview_url || "";
        },
        "interactive_autoload_disconnect",
      );
      const parsed = parseInteractivePreviewHref(generated, { fallbackCourseId: preview.courseId });
      if (!parsed || parsed.mode !== "asset") {
        throw new Error("生成完成但没有返回可预览的交互页。");
      }
      return parsed;
    },
    [preview.anchorId, preview.clientReferenceId, preview.courseId, preview.planId, preview.selectedText, preview.title],
  );

  useEffect(() => {
    setGeneratedPreview(null);
    setHtml("");
    setError(null);
    setLoading(false);
    setExpanded(true);
    setLoadingStepIndex(0);
    setIsRegenerateFormOpen(false);
  }, [preview.previewUrl]);

  useEffect(() => {
    if (!loading) {
      setLoadingStepIndex(0);
      return;
    }
    const timer = window.setInterval(() => {
      setLoadingStepIndex((value) => value + 1);
    }, 1800);
    return () => window.clearInterval(timer);
  }, [loading]);

  useEffect(() => {
    return () => {
      regenerateControllerRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!expanded || html) return;
    const controller = new AbortController();
    setLoading(true);
    setLoadingLabel(
      isStaticFigure
        ? "正在加载图示..."
        : preview.mode === "auto" && !generatedPreview
          ? "正在生成交互页..."
          : "正在加载交互页..."
    );
    setError(null);

    const loadInteractiveHtml = async () => {
      let resolvedPreview = generatedPreview ?? preview;
      if (preview.mode === "auto" && !generatedPreview) {
        if (publicMode) {
          throw new Error("公开分享不支持自动生成交互页。");
        }
        const parsed = await requestInteractiveAsset({
          signal: controller.signal,
          prompt: preview.prompt,
          clientReferenceId: preview.planId,
        });
        resolvedPreview = parsed;
        setGeneratedPreview(parsed);
        setLoadingLabel("正在加载交互页...");
      }

      const consumeAsset = async (response: Response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.text();
      };
      if (publicMode) {
        return runAnonymousApiFetch(
          resolvedPreview.assetUrl,
          { method: "GET", signal: controller.signal, cache: "no-store" },
          consumeAsset,
          "public_interactive_asset_disconnect",
        );
      }
      return runTrackedApiFetch(
        resolvedPreview.assetUrl,
        { method: "GET", signal: controller.signal },
        consumeAsset,
        "interactive_asset_disconnect",
      );
    };

    loadInteractiveHtml()
      .then((text) => {
        if (controller.signal.aborted) return;
        setHtml(text);
        setLoading(false);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setError(getApiErrorMessage(err, "交互页暂时不可用，可能仍在生成。"));
        setLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [
    expanded,
    html,
    isStaticFigure,
    requestInteractiveAsset,
    preview.anchorId,
    preview.assetUrl,
    preview.courseId,
    preview.mode,
    preview.planId,
    preview.previewUrl,
    preview.prompt,
    preview.selectedText,
    preview.title,
    publicMode,
    retryKey,
  ]);

  const patchedHtml = useMemo(
    () => (html ? (publicMode ? patchPublicHtmlForIframe(html) : patchHtmlForIframe(html)) : ""),
    [html, publicMode],
  );

  const handleRegenerateInteractive = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canRegenerate || loading) return;
    regenerateControllerRef.current?.abort();
    const controller = new AbortController();
    regenerateControllerRef.current = controller;
    const prompt = regeneratePrompt.trim() || "请换一种更清晰、更贴合当前内容的交互形式重新生成。";
    const referenceSeed =
      preview.clientReferenceId ||
      preview.planId ||
      generatedPreview?.clientReferenceId ||
      preview.assetPath ||
      generatedPreview?.assetPath ||
      "interactive";
    const clientReferenceId = referenceSeed.slice(0, 160);
    const replaceOverlayId = preview.overlayId || generatedPreview?.overlayId;
    setHtml("");
    setError(null);
    setLoading(true);
    setLoadingLabel("正在按改进要求重新生成交互页...");
    try {
      const parsed = await requestInteractiveAsset({
        signal: controller.signal,
        prompt,
        clientReferenceId,
        forceRegenerate: true,
        replaceOverlayId,
      });
      setGeneratedPreview(parsed);
      setLoadingLabel("正在加载交互页...");
      const text = await runTrackedApiFetch(
        parsed.assetUrl,
        { method: "GET", signal: controller.signal },
        async (response) => {
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
          }
          return response.text();
        },
        "interactive_asset_disconnect",
      );
      if (!controller.signal.aborted) {
        setHtml(text);
        setRegeneratePrompt("");
        setIsRegenerateFormOpen(false);
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(getApiErrorMessage(err, "交互页重新生成失败，请稍后重试。"));
      }
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
      }
      if (regenerateControllerRef.current === controller) {
        regenerateControllerRef.current = null;
      }
    }
  }, [
    canRegenerate,
    generatedPreview?.assetPath,
    generatedPreview?.clientReferenceId,
    generatedPreview?.overlayId,
    loading,
    preview.assetPath,
    preview.clientReferenceId,
    preview.overlayId,
    preview.planId,
    regeneratePrompt,
    requestInteractiveAsset,
  ]);

  if (isStaticFigure) {
    return (
      <figure
        data-doc-html-figure="true"
        data-doc-interactive-asset={preview.assetPath}
        className="my-5 overflow-hidden rounded-sm border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-950"
      >
        <figcaption className="flex items-center justify-between gap-3 border-b border-slate-100 bg-white px-3 py-2 text-left dark:border-slate-800 dark:bg-slate-950">
          <span className="min-w-0">
            <span className="block truncate text-xs font-medium text-slate-500 dark:text-slate-400">
              {preview.title || label || "静态图示"}
            </span>
          </span>
          {activePreview.mode === "asset" && (
            <button
              type="button"
              onClick={() => window.open(activePreview.previewUrl, "_blank", "noopener,noreferrer")}
              className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-sm border border-slate-200 bg-white px-2 text-xs font-medium text-slate-500 transition hover:border-slate-300 hover:text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-400 dark:hover:border-slate-600 dark:hover:text-slate-100"
            >
              <Maximize2 className="h-3.5 w-3.5" />
              打开
            </button>
          )}
        </figcaption>
        <div className="bg-white p-2 dark:bg-slate-950">
          {loading ? (
            <div className="flex min-h-[320px] flex-col items-center justify-center border border-dashed border-slate-200 bg-white text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-400">
              <div className="flex items-center">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {loadingLabel}
              </div>
              <div className="mt-2 text-xs text-slate-400 dark:text-slate-500">{loadingStepLabel}</div>
            </div>
          ) : error ? (
            <div className="flex min-h-[240px] flex-col items-center justify-center gap-3 border border-dashed border-amber-200 bg-amber-50/60 px-5 text-center dark:border-amber-500/25 dark:bg-amber-500/10">
              <p className="text-sm font-medium text-amber-900 dark:text-amber-100">图示暂时不可预览</p>
              <p className="max-w-md text-xs leading-6 text-amber-800/80 dark:text-amber-200/80">{error}</p>
              <button
                type="button"
                onClick={() => {
                  setHtml("");
                  setError(null);
                  setRetryKey((value) => value + 1);
                }}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-amber-600 px-3 text-xs font-medium text-white transition hover:bg-amber-700"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                重试加载
              </button>
            </div>
          ) : patchedHtml ? (
            <iframe
              title={preview.title || "静态图示"}
              srcDoc={patchedHtml}
              sandbox=""
              loading="lazy"
              referrerPolicy="no-referrer"
              className="h-[min(620px,72vh)] min-h-[360px] w-full border border-slate-200 bg-white dark:border-slate-800"
            />
          ) : (
            <div className="flex min-h-[260px] items-center justify-center border border-dashed border-slate-200 bg-white text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-400">
              正在准备图示
            </div>
          )}
        </div>
      </figure>
    );
  }

  return (
    <details
      data-doc-interactive-embed="true"
      data-doc-interactive-asset={preview.assetPath}
      open={expanded}
      className="group my-5 overflow-hidden rounded-xl border border-indigo-200 bg-white dark:border-indigo-500/25 dark:bg-slate-950"
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-left outline-none transition hover:bg-indigo-50/55 focus-visible:ring-2 focus-visible:ring-indigo-500/35 dark:hover:bg-indigo-500/10 [&::-webkit-details-marker]:hidden">
        <span className="flex min-w-0 items-center gap-3">
          <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-300">
            <MousePointer2 className="h-4 w-4" />
          </span>
          <span className="min-w-0">
            <span className="flex items-center gap-2 text-[13px] font-semibold text-slate-900 dark:text-slate-100">
              <span className="truncate">{preview.title || label || "交互演示"}</span>
              <span className="shrink-0 rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-medium text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300">
                交互网页
              </span>
            </span>
            <span className="mt-0.5 block text-xs text-slate-500 dark:text-slate-400">
              {preview.mode === "auto" && !generatedPreview ? "进入文档后自动生成并加载，不阻塞正文生成。" : "进入文档后自动加载，可折叠保留上下文。"}
            </span>
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {canRegenerate && (
            <button
              type="button"
              onMouseDown={(event) => {
                event.preventDefault();
                event.stopPropagation();
              }}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                setIsRegenerateFormOpen((value) => !value);
              }}
              className="hidden h-8 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-medium text-slate-600 transition hover:border-indigo-200 hover:text-indigo-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-indigo-500/50 dark:hover:text-indigo-200 sm:inline-flex"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              重新生成
            </button>
          )}
          {activePreview.mode === "asset" && (
            <button
              type="button"
              onMouseDown={(event) => {
                event.preventDefault();
                event.stopPropagation();
              }}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                window.open(activePreview.previewUrl, "_blank", "noopener,noreferrer");
              }}
              className="hidden h-8 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-medium text-slate-600 transition hover:border-indigo-200 hover:text-indigo-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-indigo-500/50 dark:hover:text-indigo-200 sm:inline-flex"
            >
              <Maximize2 className="h-3.5 w-3.5" />
              全屏打开
            </button>
          )}
          <ChevronRight className="h-4 w-4 text-slate-400 transition-transform duration-200 group-open:rotate-90" />
        </span>
      </summary>
      <div className="border-t border-indigo-100 bg-slate-50/70 p-3 dark:border-indigo-500/20 dark:bg-slate-900/45">
        {canRegenerate && isRegenerateFormOpen && (
          <form
            onSubmit={handleRegenerateInteractive}
            className="mb-3 rounded-lg border border-indigo-100 bg-white p-3 dark:border-indigo-500/20 dark:bg-slate-950"
          >
            <label className="block text-xs font-medium text-slate-600 dark:text-slate-300" htmlFor={`interactive-regenerate-${preview.assetPath}`}>
              输入改进要求后重新生成
            </label>
            <div className="mt-2 flex flex-col gap-2 sm:flex-row">
              <textarea
                id={`interactive-regenerate-${preview.assetPath}`}
                value={regeneratePrompt}
                onChange={(event) => setRegeneratePrompt(event.target.value)}
                placeholder="例如：更像函数图；少一点文字；增加步骤切换；把对比做得更直观"
                className="min-h-20 flex-1 resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-indigo-500/60 dark:focus:ring-indigo-500/15"
                maxLength={1000}
              />
              <button
                type="submit"
                disabled={loading}
                className="inline-flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-3 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-55 sm:self-end"
              >
                {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                重新生成
              </button>
            </div>
          </form>
        )}
        {loading ? (
          <div className="flex min-h-[360px] flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-white text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-400">
            <div className="flex items-center">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              {loadingLabel}
            </div>
            <div className="mt-2 text-xs text-slate-400 dark:text-slate-500">{loadingStepLabel}</div>
          </div>
        ) : error ? (
          <div className="flex min-h-[260px] flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-amber-200 bg-amber-50/60 px-5 text-center dark:border-amber-500/25 dark:bg-amber-500/10">
            <p className="text-sm font-medium text-amber-900 dark:text-amber-100">交互页还不能预览</p>
            <p className="max-w-md text-xs leading-6 text-amber-800/80 dark:text-amber-200/80">{error}</p>
            <button
              type="button"
              onClick={() => {
                setHtml("");
                setError(null);
                setRetryKey((value) => value + 1);
              }}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-amber-600 px-3 text-xs font-medium text-white transition hover:bg-amber-700"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              重试加载
            </button>
          </div>
        ) : patchedHtml ? (
          <iframe
            title={preview.title || "交互演示"}
            srcDoc={patchedHtml}
            sandbox={publicMode ? "" : "allow-scripts"}
            loading="lazy"
            referrerPolicy={publicMode ? "no-referrer" : undefined}
            className="h-[min(620px,76vh)] min-h-[420px] w-full rounded-lg border border-slate-200 bg-white dark:border-slate-800"
          />
        ) : (
          <div className="flex min-h-[260px] items-center justify-center rounded-lg border border-dashed border-slate-200 bg-white text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-400">
            正在准备交互页
          </div>
        )}
        {activePreview.mode === "asset" && (
          <a
            href={activePreview.previewUrl}
            target="_blank"
            rel="noopener noreferrer"
            referrerPolicy="no-referrer"
            className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-indigo-600 hover:text-indigo-700 hover:underline dark:text-indigo-300 dark:hover:text-indigo-200 sm:hidden"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            全屏打开
          </a>
        )}
        {canRegenerate && (
          <button
            type="button"
            onClick={() => setIsRegenerateFormOpen((value) => !value)}
            className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-indigo-600 hover:text-indigo-700 hover:underline dark:text-indigo-300 dark:hover:text-indigo-200 sm:hidden"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            重新生成
          </button>
        )}
      </div>
    </details>
  );
}

function containsInteractiveEmbed(children: ReactNode, fallbackCourseId?: string): boolean {
  return Children.toArray(children).some((child) => {
    if (!isValidElement(child)) {
      return false;
    }
    if (child.type === InteractiveHtmlEmbed) {
      return true;
    }
    const props = child.props as { children?: ReactNode; href?: string };
    if (typeof props.href === "string" && parseInteractivePreviewHref(props.href, { fallbackCourseId })) {
      return true;
    }
    return containsInteractiveEmbed(props.children, fallbackCourseId);
  });
}

function parseCallout(children: ReactNode): { kind: CalloutKind; body: ReactNode[] } | null {
  const nodes = Children.toArray(children).filter((item) => item !== "\n");
  if (nodes.length === 0) {
    return null;
  }

  const firstText = extractText(nodes[0]).trim();
  const match = firstText.match(
    /^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION|EXAMPLE|PRACTICE|QUESTION|ANSWER)\](?:\s+(.+))?$/i,
  );
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

interface UnitTestQuestionCallout {
  number: string;
  type: string;
  difficulty: string;
  target: string;
  body: ReactNode[];
}

function parseUnitTestQuestionCallout(body: ReactNode[]): UnitTestQuestionCallout | null {
  const nodes = Children.toArray(body).filter((item) => item !== "\n");
  const metadata = extractText(nodes[0]).trim().match(
    /^(Q\d+)\s*[｜|]\s*([^｜|]+)\s*[｜|]\s*([^｜|]+)\s*[｜|]\s*考点\s*[：:]\s*(.+)$/,
  );
  if (!metadata) return null;

  const content = nodes.slice(1).filter((node) => {
    const text = extractText(node).trim();
    return text !== "题目" && text !== "选项";
  });

  return {
    number: metadata[1].trim(),
    type: metadata[2].trim(),
    difficulty: metadata[3].trim(),
    target: metadata[4].trim(),
    body: content,
  };
}

function getDocumentParagraphSemanticClass(children: ReactNode): string | undefined {
  const text = extractText(children).trim();
  if (/^任务\s*\d+\s*[：:]/.test(text)) return "atm-doc-task-heading";
  if (/^(解析|易错边界|易错点|思路)\s*[：:]/.test(text)) return "atm-doc-explanation-line";
  if (/^(题目|选项|答案|解析步骤)$/.test(text)) return "atm-doc-field-label";
  return undefined;
}

export function MarkdownViewer({
  content,
  assetBaseUrl,
  assetCourse,
  publicMode = false,
  allowRawHtml = true,
  variant = "default",
  headingAnchors = false,
  headingNumbering = false,
  collapsibleHeadings,
  collapsedHeadingIds: controlledCollapsedHeadingIds,
  onHeadingCollapseChange,
}: MarkdownViewerProps) {
  const processedContent = useMemo(() => preprocessMarkdownContent(content), [content]);
  const hasMathContent = useMemo(() => hasLikelyMathContent(processedContent), [processedContent]);
  const hasHighlightableCode = useMemo(() => hasLikelyHighlightableCode(processedContent), [processedContent]);
  const hasRawHtmlContent = useMemo(() => hasLikelyRawHtmlContent(processedContent), [processedContent]);
  const shouldHighlightCode = hasHighlightableCode && (
    variant !== "document" || processedContent.length <= DOCUMENT_HIGHLIGHT_CHAR_LIMIT
  );
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
  const [imagePreview, setImagePreview] = useState<ImagePreviewState | null>(null);
  const [imagePreviewZoom, setImagePreviewZoom] = useState(1);

  useEffect(() => {
    collapsedHeadingIdsRef.current = collapsedHeadingIds;
  }, [collapsedHeadingIds]);

  useEffect(() => {
    setImagePreviewZoom(1);
  }, [imagePreview?.src]);

  useEffect(() => {
    if (!imagePreview) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setImagePreview(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [imagePreview]);

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

  const remarkPlugins = useMemo(
    () => [
      remarkGfm,
      hasMathContent ? remarkMath : noopMarkdownPlugin,
      remarkBlankTokens,
      remarkSafeHighlights,
      remarkCallouts,
      variant === "document" ? remarkDocumentSoftBreaks : noopMarkdownPlugin,
      headingStructurePlugin,
    ] as any[],
    [hasMathContent, headingStructurePlugin, variant],
  );

  const rehypePlugins = useMemo(
    () => [
      !publicMode && allowRawHtml && variant === "document" && hasRawHtmlContent ? rehypeRaw : noopMarkdownPlugin,
      variant === "document" ? rehypeMarkdownSanitize : noopMarkdownPlugin,
      hasMathContent ? [rehypeKatex, { throwOnError: false, strict: false, errorColor: "#1F2329", output: "html" }] : noopMarkdownPlugin,
      shouldHighlightCode ? rehypeHighlight : noopMarkdownPlugin,
    ] as any[],
    [allowRawHtml, hasMathContent, hasRawHtmlContent, publicMode, shouldHighlightCode, variant],
  );

  const components = useMemo(() => {
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
                className="mr-1.5 inline-block select-none whitespace-nowrap text-indigo-600 [-webkit-user-select:none] dark:text-indigo-400"
              >
                {headingNumber}&nbsp;
              </span>
            ) : null}
            <span>{children}</span>
          </Tag>
        );
      };
    };

    return {
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
            className={cn(
              isCollapsibleSection && "markdown-collapsible-section",
              className,
            )}
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
      p: ({ children }: ComponentPropsWithoutRef<"p">) => {
        if (containsInteractiveEmbed(children, assetCourse)) {
          return <div className="my-4">{children}</div>;
        }
        return (
          <p className={cn(
            styles.paragraph,
            variant === "document" && getDocumentParagraphSemanticClass(children),
          )}>
            {children}
          </p>
        );
      },
      ul: ({ children }: ComponentPropsWithoutRef<"ul">) => <ul className={styles.list}>{children}</ul>,
      ol: ({ children }: ComponentPropsWithoutRef<"ol">) => <ol className={styles.orderedList}>{children}</ol>,
      li: ({ children }: ComponentPropsWithoutRef<"li">) => <li className={styles.listItem}>{children}</li>,
      blockquote: ({ children, ...props }: MarkdownBlockquoteComponentProps) => {
        const propKind = normalizeCalloutKind(readStringProp(props, "data-callout-kind"));
        const callout = propKind
          ? { kind: propKind, body: Children.toArray(children).filter((item) => item !== "\n") }
          : parseCallout(children);
        if (!callout) {
          return <blockquote className={styles.blockquote}>{children}</blockquote>;
        }
        if (containsInteractiveEmbed(callout.body, assetCourse)) {
          return <div className="my-4">{callout.body}</div>;
        }

        if (callout.kind === "answer") {
          return (
            <details className="atm-unit-test-answer">
              <summary>答案与解析</summary>
              <div className="atm-unit-test-answer__body">
                {callout.body}
              </div>
            </details>
          );
        }

        const unitTestQuestion = callout.kind === "question" && variant === "document"
          ? parseUnitTestQuestionCallout(callout.body)
          : null;
        if (unitTestQuestion) {
          return (
            <section className="atm-unit-test-card" aria-label={`${unitTestQuestion.number} ${unitTestQuestion.type}`}>
              <header className="atm-unit-test-card__head">
                <span className="atm-unit-test-card__number">{unitTestQuestion.number}</span>
                <span className="atm-unit-test-card__type">{unitTestQuestion.type}</span>
                <span className="atm-unit-test-card__difficulty">{unitTestQuestion.difficulty}</span>
                <span className="atm-unit-test-card__target" title={unitTestQuestion.target}>
                  考点 · {unitTestQuestion.target}
                </span>
              </header>
              <div className="atm-unit-test-card__prompt">
                {unitTestQuestion.body}
              </div>
            </section>
          );
        }

        const tone = CALLOUT_STYLES[variant][callout.kind];
        const calloutMeta = CALLOUT_META[callout.kind];
        const CalloutIcon = calloutMeta.Icon;
        const isDocumentCallout = variant === "document";
        return (
          <aside className={tone.shell}>
            <div className={cn("flex items-center gap-2", isDocumentCallout ? "mb-2" : "mb-3")}>
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 font-semibold",
                  isDocumentCallout
                    ? "text-[13px] font-medium leading-5"
                    : "rounded-full px-2.5 py-1 text-[11px] tracking-[0.08em]",
                  tone.badge,
                )}
              >
                <CalloutIcon className="h-3.5 w-3.5" />
                {calloutMeta.label}
              </span>
            </div>
            <div
              className={cn(
                "[&>*:last-child]:mb-0",
                variant === "document" && "[&_ol]:my-2.5 [&_ul]:my-2.5 [&_p]:mb-2.5 [&_strong]:text-current",
              )}
            >
              {callout.body}
            </div>
          </aside>
        );
      },
      code: ({ className, children }: ComponentPropsWithoutRef<"code">) => {
        const codeText = extractText(children).replace(/\n$/, "");
        const language =
          className?.match(/\blanguage-([A-Za-z0-9_-]+)/)?.[1]?.trim().toLowerCase() ??
          className?.trim().toLowerCase().replace(/^language-/, "") ??
          "";
        const isBlock = Boolean(className) || codeText.includes("\n");
        const normalizedCodeText = codeText.trim().replace(/^(maymaid|mermaind|mermaide)\b/i, "mermaid");
        const looksLikeMermaid = /^(mermaid|mindmap|flowchart|graph|sequenceDiagram|classDiagram|stateDiagram|erDiagram|gantt|pie|journey|timeline|gitGraph)\b/i.test(normalizedCodeText);

        if (!publicMode && (MERMAID_LANGUAGE_ALIASES.has(language) || (!language && looksLikeMermaid))) {
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
              <pre className={cn(
                styles.codePre,
                variant === "document" && language && "pt-9",
                shouldRenderConflictBlock ? "px-0 py-3" : "",
              )}>
                <code className={cn("font-mono", className)}>
                  {shouldRenderConflictBlock ? renderGitConflictLines(codeText) : children}
                </code>
              </pre>
            </div>
          );
        }

        return <code className={cn(styles.codeInline, className)}>{children}</code>;
      },
      pre: ({ children }: ComponentPropsWithoutRef<"pre">) => <>{children}</>,
      table: ({ children }: ComponentPropsWithoutRef<"table">) => (
        <div className={styles.tableShell}>
          <table className={styles.table}>{children}</table>
        </div>
      ),
      thead: ({ children }: ComponentPropsWithoutRef<"thead">) => <thead className={styles.thead}>{children}</thead>,
      th: ({ children }: ComponentPropsWithoutRef<"th">) => <th className={styles.th}>{children}</th>,
      td: ({ children }: ComponentPropsWithoutRef<"td">) => <td className={styles.td}>{children}</td>,
      hr: () => <hr className={styles.hr} />,
      a: ({ href, children }: ComponentPropsWithoutRef<"a">) => {
        const parsedPreview = parseInteractivePreviewHref(href, { fallbackCourseId: assetCourse });
        if (parsedPreview) {
          const preview = publicMode
            ? toPublicInteractivePreview(parsedPreview, assetBaseUrl)
            : parsedPreview;
          if (preview) {
            return <InteractiveHtmlEmbed preview={preview} label={children} publicMode={publicMode} />;
          }
          return <span className={styles.link}>{children}</span>;
        }
        const resolvedHref = publicMode
          ? resolvePublicMarkdownAssetHref(href, assetBaseUrl)
          : href;
        if (
          publicMode &&
          resolvedHref?.startsWith("/api/v1/course-shares/")
        ) {
          return (
            <PublicMarkdownAssetLink
              href={resolvedHref}
              className={styles.link}
            >
              {children}
            </PublicMarkdownAssetLink>
          );
        }
        return (
          <a
            href={resolvedHref}
            className={styles.link}
            target="_blank"
            rel="noopener noreferrer"
            referrerPolicy={publicMode ? "no-referrer" : undefined}
          >
            {children}
          </a>
        );
      },
      strong: ({ children }: ComponentPropsWithoutRef<"strong">) => <strong className={styles.strong}>{children}</strong>,
      em: ({ children }: ComponentPropsWithoutRef<"em">) => <em className={styles.em}>{children}</em>,
      mark: ({ children }: ComponentPropsWithoutRef<"mark">) => <mark className={styles.highlight}>{children}</mark>,
      img: ({ src, alt }: ComponentPropsWithoutRef<"img">) => {
        const resolvedSrc = resolveMarkdownImageSrc(src, {
          assetBaseUrl,
          assetCourse,
          publicMode,
        });

        return (
          <MarkdownImage
            src={resolvedSrc}
            alt={alt}
            styles={styles}
            onOpenPreview={setImagePreview}
            publicMode={publicMode}
          />
        );
      },
    };
  }, [
    styles,
    variant,
    headingAnchors,
    collapsibleHeadingLevels,
    collapsedHeadingIds,
    toggleHeadingCollapse,
    assetCourse,
    assetBaseUrl,
    publicMode,
    nextHeadingId,
  ]);

  return (
    <>
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={rehypePlugins}
        components={components}
      >
        {processedContent}
      </ReactMarkdown>
      {imagePreview ? (
        <div
          className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/78 p-3 backdrop-blur-sm sm:p-6"
          role="dialog"
          aria-modal="true"
          aria-label={imagePreview.title}
          onClick={() => setImagePreview(null)}
        >
          <div
            className="flex h-full w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-white/10 bg-slate-950 shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-white/10 px-3 text-white sm:px-4">
              <div className="min-w-0 truncate text-sm font-medium">{imagePreview.title}</div>
              <div className="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  onClick={() => setImagePreviewZoom((value) => Math.max(0.5, value - 0.2))}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-300 transition hover:bg-white/10 hover:text-white"
                  aria-label="缩小图片"
                  title="缩小"
                >
                  <ZoomOut className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  onClick={() => setImagePreviewZoom(1)}
                  className="hidden h-8 min-w-11 items-center justify-center rounded-lg px-2 text-xs font-medium text-slate-300 transition hover:bg-white/10 hover:text-white sm:inline-flex"
                  aria-label="重置图片缩放"
                  title="重置缩放"
                >
                  {Math.round(imagePreviewZoom * 100)}%
                </button>
                <button
                  type="button"
                  onClick={() => setImagePreviewZoom((value) => Math.min(3, value + 0.2))}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-300 transition hover:bg-white/10 hover:text-white"
                  aria-label="放大图片"
                  title="放大"
                >
                  <ZoomIn className="h-4 w-4" />
                </button>
                <a
                  href={imagePreview.src}
                  target="_blank"
                  rel="noopener noreferrer"
                  referrerPolicy={publicMode ? "no-referrer" : undefined}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-300 transition hover:bg-white/10 hover:text-white"
                  aria-label="在新窗口打开图片"
                  title="新窗口打开"
                >
                  <ExternalLink className="h-4 w-4" />
                </a>
                <button
                  type="button"
                  onClick={() => setImagePreview(null)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-300 transition hover:bg-white/10 hover:text-white"
                  aria-label="关闭图片预览"
                  title="关闭"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-auto bg-[radial-gradient(circle_at_center,rgba(30,41,59,0.55),rgba(2,6,23,0.96))] p-3">
              <div className="flex min-h-full items-center justify-center">
                <img
                  src={imagePreview.src}
                  alt={imagePreview.title}
                  className="max-h-full max-w-full select-none rounded-md bg-white object-contain shadow-2xl"
                  style={{
                    width: imagePreviewZoom === 1 ? undefined : `${Math.round(imagePreviewZoom * 100)}%`,
                    maxWidth: imagePreviewZoom === 1 ? "100%" : "none",
                    maxHeight: imagePreviewZoom === 1 ? "100%" : "none",
                  }}
                  decoding="async"
                  referrerPolicy={publicMode ? "no-referrer" : undefined}
                />
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

export type { MarkdownViewerProps, MarkdownViewerVariant };
