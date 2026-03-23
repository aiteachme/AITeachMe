import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

import { cn } from "../../lib/utils";

interface MarkdownViewerProps {
  content: string;
  assetBaseUrl?: string;
}

function isAbsoluteAssetUrl(value: string): boolean {
  return /^(https?:)?\/\//i.test(value) || value.startsWith("/") || value.startsWith("data:");
}

function resolveMarkdownImageSrc(src: string | undefined, assetBaseUrl?: string): string | undefined {
  if (!src) {
    return src;
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

export function MarkdownViewer({ content, assetBaseUrl }: MarkdownViewerProps) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex, rehypeHighlight]}
      components={{
        h1: ({ children }) => (
          <h1 className="mb-3 mt-6 border-b border-slate-200 pb-2 text-2xl font-bold text-slate-900">
            {children}
          </h1>
        ),
        h2: ({ children }) => (
          <h2 className="mb-2 mt-5 text-xl font-semibold text-slate-800">{children}</h2>
        ),
        h3: ({ children }) => (
          <h3 className="mb-2 mt-4 text-lg font-semibold text-slate-800">{children}</h3>
        ),
        h4: ({ children }) => (
          <h4 className="mb-1 mt-3 text-base font-semibold text-slate-700">{children}</h4>
        ),
        p: ({ children }) => <p className="mb-3 text-sm leading-relaxed text-slate-700">{children}</p>,
        ul: ({ children }) => (
          <ul className="mb-3 list-inside list-disc space-y-1 pl-2 text-sm text-slate-700">
            {children}
          </ul>
        ),
        ol: ({ children }) => (
          <ol className="mb-3 list-inside list-decimal space-y-1 pl-2 text-sm text-slate-700">
            {children}
          </ol>
        ),
        li: ({ children }) => <li className="leading-relaxed [&>p]:mb-0 [&>p]:inline">{children}</li>,
        blockquote: ({ children }) => (
          <blockquote className="my-3 border-l-4 border-slate-300 pl-4 italic text-slate-600">
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
            <code
              className={cn(
                "rounded bg-slate-100 px-1.5 py-0.5 text-sm font-mono text-slate-800",
                className,
              )}
            >
              {children}
            </code>
          );
        },
        pre: ({ children }) => (
          <pre className="my-3 overflow-x-auto rounded-lg bg-slate-900 p-4 text-sm text-slate-100">
            {children}
          </pre>
        ),
        table: ({ children }) => (
          <div className="my-3 overflow-x-auto">
            <table className="min-w-full rounded-lg border border-slate-200 text-sm">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead className="border-b border-slate-200 bg-slate-50">{children}</thead>,
        th: ({ children }) => <th className="px-3 py-2 text-left font-semibold text-slate-700">{children}</th>,
        td: ({ children }) => <td className="border-t border-slate-100 px-3 py-2 text-slate-600">{children}</td>,
        hr: () => <hr className="my-4 border-slate-200" />,
        a: ({ href, children }) => (
          <a href={href} className="text-blue-600 hover:underline" target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        ),
        strong: ({ children }) => <strong className="font-semibold text-slate-900">{children}</strong>,
        em: ({ children }) => <em className="italic text-slate-600">{children}</em>,
        img: ({ src, alt }) => {
          const resolvedSrc = resolveMarkdownImageSrc(src, assetBaseUrl);
          return (
            <img
              src={resolvedSrc}
              alt={alt ?? ""}
              className="my-4 max-h-[32rem] w-auto max-w-full rounded-xl border border-slate-200 bg-white shadow-sm"
              loading="lazy"
            />
          );
        },
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
