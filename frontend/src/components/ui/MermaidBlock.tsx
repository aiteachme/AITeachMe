import { useEffect, useId, useMemo, useState } from "react";
import { Loader2, Sparkles, TriangleAlert } from "lucide-react";

import { cn } from "../../lib/utils";

type MermaidApi = typeof import("mermaid").default;
type MermaidBlockVariant = "default" | "document";

interface MermaidBlockProps {
  chart: string;
  variant?: MermaidBlockVariant;
}

let mermaidConfigured = false;
let mermaidModulePromise: Promise<MermaidApi> | null = null;
const MINDMAP_ROOT_RE = /^root\(\((.+)\)\)$/i;
const MINDMAP_MIXED_SYNTAX_RE =
  /-->|==>|\b(?:graph|flowchart|sequencediagram|classdiagram|statediagram|erdiagram|gantt)\b/i;
const FLOWCHART_HEADER_RE = /^(?:flowchart|graph)\b/i;
const FLOWCHART_NODE_LABEL_RE = /(^|[^\w"'])([A-Za-z_][\w-]*)\s*\[([^\]\n]+)\]/g;
const FLOWCHART_EDGE_LABEL_RE = /\|([^|\n]+)\|/g;

function loadMermaid() {
  mermaidModulePromise ??= import("mermaid").then((module) => module.default);
  return mermaidModulePromise;
}

function ensureMermaidConfigured(mermaid: MermaidApi) {
  if (mermaidConfigured) {
    return;
  }

  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: "base",
    suppressErrorRendering: true,
    themeVariables: {
      primaryColor: "#ede9fe",
      primaryTextColor: "#0f172a",
      primaryBorderColor: "#7dd3fc",
      lineColor: "#0f766e",
      secondaryColor: "#fef3c7",
      tertiaryColor: "#f8fafc",
      background: "#ffffff",
      mainBkg: "#f8fafc",
      nodeBorder: "#bae6fd",
      clusterBkg: "#f0f9ff",
      clusterBorder: "#cbd5e1",
      edgeLabelBackground: "#ffffff",
      fontFamily: "ui-serif, Georgia, Cambria, 'Times New Roman', serif",
    },
    flowchart: {
      htmlLabels: false,
      curve: "basis",
      useMaxWidth: true,
    },
    mindmap: {
      padding: 18,
      maxNodeWidth: 220,
    },
  });

  mermaidConfigured = true;
}

function hashChart(chart: string): string {
  let hash = 0;
  for (let index = 0; index < chart.length; index += 1) {
    hash = (hash * 31 + chart.charCodeAt(index)) | 0;
  }
  return Math.abs(hash).toString(36);
}

function normalizeMermaidSource(chart: string): string {
  return String(chart ?? "").replace(/\uFEFF/g, "").replace(/\r\n?/g, "\n").trim();
}

function sanitizeMindmapLabel(label: string): string {
  return label
    .normalize("NFKC")
    .replace(/[`$]/g, " ")
    .replace(/[<>{}\[\]]/g, " ")
    .replace(
      /\b(?:mindmap|root|graph|flowchart|subgraph|classDef|class|style|click|section|title|LR|RL|TB|BT)\b/gi,
      " ",
    )
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 32);
}

function sanitizeFlowchartLabel(label: string): string {
  const normalized = String(label ?? "")
    .normalize("NFKC")
    .replace(/^["']|["']$/g, "")
    .replace(/\\n/g, " ")
    .replace(/[`$#]/g, " ")
    .replace(/[{}]/g, " ")
    .replace(/[|]/g, " ")
    .replace(/>/g, "大于")
    .replace(/</g, "小于")
    .replace(/=/g, "等于")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 44)
    .trim();
  return normalized || "节点";
}

function quoteFlowchartLabels(line: string): string {
  if (/^\s*(?:classDef|class|style|linkStyle|click)\b/i.test(line)) {
    return line;
  }

  return line.replace(FLOWCHART_NODE_LABEL_RE, (_match, prefix: string, nodeId: string, label: string) => {
    const cleaned = sanitizeFlowchartLabel(label).replace(/"/g, "'");
    return `${prefix}${nodeId}["${cleaned}"]`;
  }).replace(FLOWCHART_EDGE_LABEL_RE, (_match, label: string) => {
    const cleaned = sanitizeFlowchartLabel(label).replace(/"/g, "'").slice(0, 32);
    return `|${cleaned}|`;
  });
}

function normalizeFlowchartChart(chart: string): string {
  const normalized = normalizeMermaidSource(chart);
  const rawLines = normalized.split("\n").filter((line) => line.trim().length > 0);
  if (rawLines.length === 0) {
    return normalized;
  }

  const output = [...rawLines];
  if (!FLOWCHART_HEADER_RE.test(output[0]?.trim() ?? "") && output.some((line) => /-->|==>/.test(line))) {
    output.unshift("flowchart TD");
  }

  return output.map(quoteFlowchartLabels).join("\n");
}

function extractMindmapLabels(chart: string, maxCount = 6): string[] {
  const candidates: string[] = [];
  const seen = new Set<string>();
  const push = (value: string) => {
    const cleaned = sanitizeMindmapLabel(value);
    if (!cleaned) {
      return;
    }
    const key = cleaned.toLowerCase();
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    candidates.push(cleaned);
  };

  for (const match of chart.matchAll(/root\(\((.+?)\)\)/gi)) {
    push(match[1] ?? "");
  }
  for (const match of chart.matchAll(/\[([^\]]+)\]/g)) {
    push(match[1] ?? "");
  }

  for (const rawLine of chart.split("\n")) {
    const line = rawLine.trim();
    if (!line || /^mindmap$/i.test(line) || /^```/.test(line)) {
      continue;
    }
    if (MINDMAP_ROOT_RE.test(line)) {
      push(line.replace(MINDMAP_ROOT_RE, "$1"));
      continue;
    }
    if (MINDMAP_MIXED_SYNTAX_RE.test(line)) {
      const arrowLabel = line.match(/\[([^\]]+)\]/)?.[1] ?? line.split(/-->|==>/).pop() ?? "";
      push(arrowLabel);
      continue;
    }
    push(line.replace(/^[-*+]\s+/, ""));
  }

  return candidates.slice(0, maxCount);
}

function buildSimplifiedMindmap(chart: string): string {
  const labels = extractMindmapLabels(chart, 6);
  const root = labels[0] ?? "核心主题";
  const children = labels.slice(1);
  const lines = ["mindmap", `  root((${root}))`];
  for (const child of children) {
    lines.push(`    ${child}`);
  }
  return lines.join("\n");
}

function normalizeMindmapChart(chart: string): string {
  const normalized = normalizeMermaidSource(chart);
  if (!normalized.toLowerCase().startsWith("mindmap")) {
    return normalized;
  }

  const rawLines = normalized.split("\n");
  const bodyLines = rawLines.slice(1).filter((line) => line.trim().length > 0);
  if (bodyLines.some((line) => MINDMAP_MIXED_SYNTAX_RE.test(line))) {
    return buildSimplifiedMindmap(normalized);
  }

  const output = ["mindmap"];
  let hasRoot = false;

  for (const rawLine of bodyLines) {
    const expanded = rawLine.replace(/\t/g, "  ");
    const indentChars = expanded.match(/^\s*/)?.[0].length ?? 0;
    const indentLevel = Math.max(1, Math.floor(indentChars / 2));
    const stripped = expanded.trim().replace(/^[-*+]\s+/, "");
    if (!stripped) {
      continue;
    }

    const rootMatch = stripped.match(MINDMAP_ROOT_RE);
    if (rootMatch) {
      const rootLabel = sanitizeMindmapLabel(rootMatch[1] ?? "");
      if (rootLabel) {
        output.push(`  root((${rootLabel}))`);
        hasRoot = true;
      }
      continue;
    }

    const label = sanitizeMindmapLabel(stripped);
    if (!label) {
      continue;
    }
    if (!hasRoot && indentLevel <= 1) {
      output.push(`  root((${label}))`);
      hasRoot = true;
      continue;
    }
    output.push(`${"  ".repeat(Math.max(2, indentLevel))}${label}`);
  }

  if (!hasRoot) {
    return buildSimplifiedMindmap(normalized);
  }

  return output.join("\n");
}

function buildChartCandidates(chart: string): string[] {
  const normalized = normalizeMermaidSource(chart);
  if (!normalized) {
    return [normalized];
  }
  if (!normalized.toLowerCase().startsWith("mindmap")) {
    const flowchartCandidate = normalizeFlowchartChart(normalized);
    return [normalized, flowchartCandidate].filter(
      (candidate, index, candidates) => candidate && candidates.indexOf(candidate) === index,
    );
  }

  const candidates = [
    normalized,
    normalizeMindmapChart(normalized),
    buildSimplifiedMindmap(normalized),
  ];
  return candidates.filter(
    (candidate, index) => candidate && candidates.indexOf(candidate) === index,
  );
}

async function renderMermaidChart(diagramId: string, chart: string) {
  const mermaid = await loadMermaid();
  ensureMermaidConfigured(mermaid);
  const candidates = buildChartCandidates(chart);
  let lastError: unknown = null;
  for (let index = 0; index < candidates.length; index += 1) {
    try {
      return await mermaid.render(`${diagramId}-${index}`, candidates[index]);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError instanceof Error ? lastError : new Error("Mermaid 渲染失败");
}

function resolveDiagramLabel(chart: string): string {
  const normalized = chart.trim().toLowerCase();
  if (normalized.startsWith("mindmap")) {
    return "思维导图";
  }
  if (normalized.startsWith("flowchart") || normalized.startsWith("graph")) {
    return "关系图";
  }
  if (normalized.startsWith("sequencediagram")) {
    return "时序图";
  }
  if (normalized.startsWith("classdiagram")) {
    return "类图";
  }
  return "知识图示";
}

export function MermaidBlock({ chart, variant = "default" }: MermaidBlockProps) {
  const rawId = useId();
  const diagramId = useMemo(
    () => `atm-mermaid-${rawId.replace(/[:]/g, "-")}-${hashChart(chart)}`,
    [chart, rawId],
  );
  const [svgMarkup, setSvgMarkup] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;

    async function renderDiagram() {
      setSvgMarkup("");
      setErrorMessage(null);

      try {
        const rendered = await renderMermaidChart(diagramId, chart);
        if (!disposed) {
          setSvgMarkup(rendered.svg);
        }
      } catch (error) {
        if (!disposed) {
          setErrorMessage(error instanceof Error ? error.message : "Mermaid 渲染失败");
        }
      }
    }

    void renderDiagram();

    return () => {
      disposed = true;
    };
  }, [chart, diagramId]);

  const diagramLabel = resolveDiagramLabel(chart);
  const isDocument = variant === "document";

  return (
    <figure
      className={cn(
        "my-6 overflow-hidden border",
        isDocument
          ? "rounded-[28px] border-indigo-100 bg-[radial-gradient(circle_at_top_left,#ede9fe_0%,#ffffff_38%,#f8fafc_100%)] shadow-[0_28px_80px_-56px_rgba(109,40,217,0.55)] dark:border-indigo-500/20 dark:bg-[radial-gradient(circle_at_top_left,rgba(99,102,241,0.16)_0%,rgba(15,23,42,0.96)_42%,rgba(2,6,23,0.98)_100%)] dark:shadow-[0_32px_72px_-56px_rgba(99,102,241,0.45)]"
          : "rounded-2xl border-indigo-100 bg-indigo-50/70 shadow-sm dark:border-indigo-500/20 dark:bg-slate-950/80 dark:shadow-[0_18px_40px_-28px_rgba(0,0,0,0.72)]",
      )}
    >
      <div
        className={cn(
          "flex items-center justify-between gap-3 border-b px-4 py-3",
          isDocument
            ? "border-indigo-100/80 bg-white/70 dark:border-indigo-500/20 dark:bg-slate-950/70"
            : "border-indigo-100/80 bg-white/80 dark:border-indigo-500/20 dark:bg-slate-950/80",
        )}
      >
        <div className="flex items-center gap-2">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-2xl bg-indigo-100 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300">
            <Sparkles className="h-4 w-4" />
          </span>
          <div>
            <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {diagramLabel}
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">Mermaid 实时渲染</p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
          {svgMarkup ? null : errorMessage ? (
            <>
              <TriangleAlert className="h-3.5 w-3.5 text-amber-500" />
              <span>已回退到源码视图</span>
            </>
          ) : (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span>渲染中</span>
            </>
          )}
        </div>
      </div>

      {svgMarkup ? (
        <div
          className={cn(
            "overflow-x-auto px-4 py-5 [&_svg]:mx-auto [&_svg]:h-auto [&_svg]:max-w-full",
            isDocument ? "bg-transparent" : "bg-white/60 dark:bg-slate-950/30",
          )}
          dangerouslySetInnerHTML={{ __html: svgMarkup }}
        />
      ) : (
        <div className="px-4 py-5">
          <pre className="overflow-x-auto rounded-2xl bg-slate-950 p-4 text-[13px] leading-6 text-slate-100 dark:border dark:border-slate-800">
            <code>{chart}</code>
          </pre>
          {errorMessage ? (
            <p className="mt-3 text-xs leading-5 text-amber-700 dark:text-amber-300">
              Mermaid 渲染失败：{errorMessage}
            </p>
          ) : null}
        </div>
      )}
    </figure>
  );
}

export type { MermaidBlockVariant };
