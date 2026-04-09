import { Children, useMemo, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

import { cn } from "../../lib/utils";
import { MermaidBlock } from "./MermaidBlock";

type MarkdownViewerVariant = "default" | "document";
type CalloutKind = "note" | "tip" | "important" | "warning" | "caution";

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
      shell: "my-4 rounded-2xl border border-sky-200 bg-sky-50/80 px-4 py-3 text-slate-700",
      badge: "bg-sky-100 text-sky-700",
    },
    tip: {
      shell: "my-4 rounded-2xl border border-emerald-200 bg-emerald-50/80 px-4 py-3 text-slate-700",
      badge: "bg-emerald-100 text-emerald-700",
    },
    important: {
      shell: "my-4 rounded-2xl border border-violet-200 bg-violet-50/80 px-4 py-3 text-slate-700",
      badge: "bg-violet-100 text-violet-700",
    },
    warning: {
      shell: "my-4 rounded-2xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-slate-700",
      badge: "bg-amber-100 text-amber-700",
    },
    caution: {
      shell: "my-4 rounded-2xl border border-rose-200 bg-rose-50/80 px-4 py-3 text-slate-700",
      badge: "bg-rose-100 text-rose-700",
    },
  },
  document: {
    note: {
      shell: "my-6 rounded-[24px] border border-sky-200 bg-[linear-gradient(135deg,rgba(224,242,254,0.8),rgba(255,255,255,0.98))] px-5 py-4 text-slate-700 shadow-[0_18px_48px_-38px_rgba(14,165,233,0.8)]",
      badge: "bg-sky-100 text-sky-700",
    },
    tip: {
      shell: "my-6 rounded-[24px] border border-emerald-200 bg-[linear-gradient(135deg,rgba(220,252,231,0.78),rgba(255,255,255,0.98))] px-5 py-4 text-slate-700 shadow-[0_18px_48px_-38px_rgba(16,185,129,0.8)]",
      badge: "bg-emerald-100 text-emerald-700",
    },
    important: {
      shell: "my-6 rounded-[24px] border border-fuchsia-200 bg-[linear-gradient(135deg,rgba(250,232,255,0.78),rgba(255,255,255,0.98))] px-5 py-4 text-slate-700 shadow-[0_18px_48px_-38px_rgba(217,70,239,0.72)]",
      badge: "bg-fuchsia-100 text-fuchsia-700",
    },
    warning: {
      shell: "my-6 rounded-[24px] border border-amber-200 bg-[linear-gradient(135deg,rgba(254,243,199,0.82),rgba(255,255,255,0.98))] px-5 py-4 text-slate-700 shadow-[0_18px_48px_-38px_rgba(245,158,11,0.82)]",
      badge: "bg-amber-100 text-amber-700",
    },
    caution: {
      shell: "my-6 rounded-[24px] border border-rose-200 bg-[linear-gradient(135deg,rgba(255,228,230,0.82),rgba(255,255,255,0.98))] px-5 py-4 text-slate-700 shadow-[0_18px_48px_-38px_rgba(244,63,94,0.78)]",
      badge: "bg-rose-100 text-rose-700",
    },
  },
};

const VIEWER_STYLES: Record<MarkdownViewerVariant, ViewerStyles> = {
  default: {
    heading: {
      1: "mb-3 mt-6 border-b border-slate-200 pb-2 text-2xl font-bold text-slate-900",
      2: "mb-2 mt-5 text-xl font-semibold text-slate-800",
      3: "mb-2 mt-4 text-lg font-semibold text-slate-800",
      4: "mb-1 mt-3 text-base font-semibold text-slate-700",
      5: "mb-1 mt-3 text-sm font-semibold text-slate-700",
      6: "mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500",
    },
    paragraph: "mb-3 text-sm leading-relaxed text-slate-700",
    list: "mb-3 list-inside list-disc space-y-1 pl-2 text-sm text-slate-700",
    orderedList: "mb-3 list-inside list-decimal space-y-1 pl-2 text-sm text-slate-700",
    listItem: "leading-relaxed [&>p]:mb-0 [&>p]:inline",
    blockquote: "my-3 rounded-r-xl border-l-4 border-slate-300 bg-slate-50/70 pl-4 pr-3 py-2.5 italic text-slate-600",
    codeInline: "rounded bg-slate-100 px-1.5 py-0.5 text-sm font-mono text-slate-800",
    codeShell: "my-4 overflow-hidden rounded-2xl border border-slate-200 bg-slate-950 shadow-sm",
    codeLanguageBadge: "border-b border-slate-800/80 bg-slate-900/95 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400",
    codePre: "overflow-x-auto p-4 text-sm leading-6 text-slate-100",
    tableShell: "my-4 overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm",
    table: "min-w-full text-sm",
    thead: "border-b border-slate-200 bg-slate-50",
    th: "px-3 py-2 text-left font-semibold text-slate-700",
    td: "border-t border-slate-100 px-3 py-2 text-slate-600",
    hr: "my-5 border-slate-200",
    link: "text-blue-600 transition-colors hover:text-blue-700 hover:underline",
    strong: "font-semibold text-slate-900",
    em: "italic text-slate-600",
    imageShell: "my-5",
    imageFrame: "overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm",
    image: "max-h-[32rem] w-full object-contain bg-white",
    imageCaption: "mt-2 px-1 text-center text-xs text-slate-500",
  },
  document: {
    heading: {
      1: "mt-10 mb-5 border-b border-stone-200/80 pb-3.5 font-serif text-[2rem] font-semibold tracking-[-0.02em] text-stone-900",
      2: "mt-9 mb-4 font-serif text-[1.65rem] font-semibold tracking-[-0.02em] text-stone-900",
      3: "mt-7 mb-3 font-serif text-[1.3rem] font-semibold tracking-[-0.015em] text-stone-800",
      4: "mt-5 mb-2.5 text-[1.02rem] font-semibold text-stone-800",
      5: "mt-4 mb-2 text-sm font-semibold uppercase tracking-[0.16em] text-stone-500",
      6: "mt-3.5 mb-1.5 text-xs font-semibold uppercase tracking-[0.2em] text-stone-400",
    },
    paragraph: "mb-4 text-[15px] leading-[2] text-stone-700",
    list: "mb-5 list-disc space-y-2 pl-6 text-[15px] leading-[1.95] text-stone-700",
    orderedList: "mb-5 list-decimal space-y-2 pl-6 text-[15px] leading-[1.95] text-stone-700",
    listItem: "leading-[1.95] [&>p]:mb-0 [&>p]:inline",
    blockquote: "my-5 rounded-r-[20px] border-l-[3px] border-sky-300/80 bg-sky-50/55 px-4 py-3 text-stone-600",
    codeInline: "rounded-lg bg-stone-100 px-1.5 py-0.5 font-mono text-[0.92em] text-stone-800",
    codeShell: "my-6 overflow-hidden rounded-[24px] border border-slate-200/80 bg-slate-950 shadow-[0_24px_60px_-48px_rgba(15,23,42,0.88)]",
    codeLanguageBadge: "border-b border-slate-800/90 bg-slate-900/95 px-4 py-2.5 text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400",
    codePre: "overflow-x-auto p-5 text-[13px] leading-7 text-slate-100",
    tableShell: "my-6 overflow-x-auto rounded-[24px] border border-stone-200/90 bg-white shadow-[0_24px_60px_-48px_rgba(41,37,36,0.4)]",
    table: "min-w-full text-sm",
    thead: "border-b border-stone-200 bg-stone-50/90",
    th: "px-4 py-3 text-left text-[13px] font-semibold uppercase tracking-[0.12em] text-stone-500",
    td: "border-t border-stone-100 px-4 py-3 text-stone-700",
    hr: "my-8 border-stone-200/70",
    link: "text-sky-700 underline decoration-sky-200 underline-offset-4 transition-colors hover:text-sky-800 hover:decoration-sky-400",
    strong: "font-semibold text-stone-900",
    em: "italic text-stone-600",
    imageShell: "my-8",
    imageFrame: "overflow-hidden rounded-[28px] border border-stone-200/90 bg-[radial-gradient(circle_at_top_left,#fef3c7_0%,#fff_36%,#f8fafc_100%)] shadow-[0_30px_80px_-58px_rgba(120,113,108,0.58)]",
    image: "max-h-[36rem] w-full object-contain bg-transparent p-3",
    imageCaption: "mt-3 px-1 text-center text-sm text-stone-500",
  },
};

export function preprocessLaTeX(content: string): string {
  if (!content) return content;
  let processed = typeof content === "string" ? content : String(content);
  processed = processed.replace(/\\\[([\s\S]*?)\\\]/g, "$$$$$1$$$$");
  processed = processed.replace(/\\\(([\s\S]*?)\\\)/g, "$$$1$$");
  return processed;
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
  if (!normalized || isAbsoluteAssetUrl(normalized)) {
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

function parseCallout(children: ReactNode): { kind: CalloutKind; body: ReactNode[] } | null {
  const nodes = Children.toArray(children).filter((item) => item !== "\n");
  if (nodes.length === 0) {
    return null;
  }

  const firstText = extractText(nodes[0]).trim();
  const match = firstText.match(/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]$/i);
  if (!match) {
    return null;
  }

  return {
    kind: match[1].toLowerCase() as CalloutKind,
    body: nodes.slice(1),
  };
}

export function MarkdownViewer({
  content,
  assetBaseUrl,
  assetSubject,
  variant = "default",
  headingAnchors = false,
}: MarkdownViewerProps) {
  const processedContent = preprocessLaTeX(content);
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
          const language = className?.replace(/^language-/, "").trim().toLowerCase() ?? "";
          const isBlock = Boolean(className) || codeText.includes("\n");

          if (language === "mermaid") {
            return <MermaidBlock chart={codeText} variant={variant} />;
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
            <figure className={styles.imageShell}>
              <div className={styles.imageFrame}>
                <img
                  src={resolvedSrc}
                  alt={alt ?? ""}
                  className={styles.image}
                  loading="lazy"
                />
              </div>
              {alt ? <figcaption className={styles.imageCaption}>{alt}</figcaption> : null}
            </figure>
          );
        },
      }}
    >
      {processedContent}
    </ReactMarkdown>
  );
}

export type { MarkdownViewerProps, MarkdownViewerVariant };
