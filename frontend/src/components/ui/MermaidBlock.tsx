import { useEffect, useId, useMemo, useState } from "react";
import { Download, Loader2, Maximize2, Minus, Plus, Sparkles, TriangleAlert, X } from "lucide-react";

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
const FLOWCHART_INLINE_HEADER_RE = /^\s*((?:flowchart|graph)\s+(?:TD|TB|BT|LR|RL))\s+(.+)$/i;
const FLOWCHART_NODE_LABEL_RE = /(^|[^\w"'])([A-Za-z_][\w-]*)\s*\[([^\]\n]+)\]/g;
const FLOWCHART_EDGE_LABEL_RE = /\|([^|\n]+)\|/g;
const FLOWCHART_CLASS_LINE_RE = /^(\s*class\s+)([^;\n]+?)(;?\s*)$/i;
const FLOWCHART_CONTROL_LINE_RE = /^\s*(?:%%|flowchart|graph|subgraph|end\b|direction\b|classDef\b|class\b|style\b|linkStyle\b|click\b|accTitle\b|accDescr\b|title\b)/i;
const FLOWCHART_EDGE_LINE_RE = /^\s*[A-Za-z_][\w-]*\s*(?:-->|---|==>|-.->|==|--|~~~|o--|x--)/;
const FLOWCHART_NODE_LINE_RE = /^\s*[A-Za-z_][\w-]*\s*(?:\[|\(|\{|\>)/;

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

function normalizeFlowchartControlLine(line: string): string {
  const classMatch = line.match(FLOWCHART_CLASS_LINE_RE);
  if (!classMatch || /^\s*classDef\b/i.test(line)) {
    return line;
  }

  const prefix = classMatch[1] ?? "";
  const body = (classMatch[2] ?? "").trim();
  const suffix = classMatch[3] ?? "";
  const parts = body.split(/\s+/).filter(Boolean);
  if (parts.length < 2) {
    return line;
  }

  const className = parts.pop() ?? "";
  const nodeList = parts
    .join(" ")
    .split(",")
    .map((nodeId) => nodeId.trim())
    .filter(Boolean)
    .join(",");
  if (!nodeList || !className) {
    return line;
  }

  return `${prefix}${nodeList} ${className}${suffix}`;
}

function quoteFlowchartLabels(line: string): string {
  if (/^\s*(?:classDef|class|style|linkStyle|click)\b/i.test(line)) {
    return normalizeFlowchartControlLine(line);
  }

  return line.replace(FLOWCHART_NODE_LABEL_RE, (_match, prefix: string, nodeId: string, label: string) => {
    const cleaned = sanitizeFlowchartLabel(label).replace(/"/g, "'");
    return `${prefix}${nodeId}["${cleaned}"]`;
  }).replace(FLOWCHART_EDGE_LABEL_RE, (_match, label: string) => {
    const cleaned = sanitizeFlowchartLabel(label).replace(/"/g, "'").slice(0, 32);
    return `|${cleaned}|`;
  });
}

function splitInlineFlowchartHeader(line: string): string[] {
  const match = line.match(FLOWCHART_INLINE_HEADER_RE);
  if (!match) {
    return [line];
  }

  const header = match[1]?.trim() ?? "";
  const body = match[2]?.trim() ?? "";
  if (!header || !body) {
    return [line];
  }
  return [header, body];
}

function normalizeFlowchartLine(line: string, index: number): string {
  const quoted = quoteFlowchartLabels(line);
  const trimmed = quoted.trim();
  if (!trimmed) {
    return quoted;
  }
  if (
    FLOWCHART_CONTROL_LINE_RE.test(trimmed) ||
    FLOWCHART_EDGE_LINE_RE.test(trimmed) ||
    FLOWCHART_NODE_LINE_RE.test(trimmed)
  ) {
    return quoted;
  }

  const cleaned = sanitizeFlowchartLabel(trimmed).replace(/"/g, "'");
  return `ATM_AUTO_${index}["${cleaned}"]`;
}

function normalizeFlowchartChart(chart: string): string {
  const normalized = normalizeMermaidSource(chart);
  const rawLines = normalized
    .split("\n")
    .flatMap(splitInlineFlowchartHeader)
    .filter((line) => line.trim().length > 0);
  if (rawLines.length === 0) {
    return normalized;
  }

  const output = [...rawLines];
  if (!FLOWCHART_HEADER_RE.test(output[0]?.trim() ?? "") && output.some((line) => /-->|==>/.test(line))) {
    output.unshift("flowchart TD");
  }

  return output.map(normalizeFlowchartLine).join("\n");
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

function sanitizeDownloadName(value: string): string {
  const cleaned = value
    .normalize("NFKC")
    .replace(/[\\/:*?"<>|]+/g, "-")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80);
  return cleaned || "aiteachme-diagram";
}

function getSvgSize(svgMarkup: string): { width: number; height: number } {
  try {
    const doc = new DOMParser().parseFromString(svgMarkup, "image/svg+xml");
    const svg = doc.documentElement;
    const viewBox = svg.getAttribute("viewBox")?.split(/\s+/).map(Number).filter(Number.isFinite) ?? [];
    const width = Number(svg.getAttribute("width")) || viewBox[2] || 1400;
    const height = Number(svg.getAttribute("height")) || viewBox[3] || 800;
    return {
      width: Math.max(320, Math.min(6000, width)),
      height: Math.max(180, Math.min(6000, height)),
    };
  } catch {
    return { width: 1400, height: 800 };
  }
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function downloadSvgAsPng(svgMarkup: string, filename: string) {
  const { width, height } = getSvgSize(svgMarkup);
  const svgBlob = new Blob([svgMarkup], { type: "image/svg+xml;charset=utf-8" });
  const svgUrl = URL.createObjectURL(svgBlob);

  try {
    const image = new Image();
    image.decoding = "async";
    const imageLoaded = new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error("图片导出失败"));
    });
    image.src = svgUrl;
    await imageLoaded;

    const scale = Math.max(1, Math.min(3, 2200 / Math.max(width, height)));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    const context = canvas.getContext("2d");
    if (!context) {
      throw new Error("Canvas 不可用");
    }
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);

    const pngBlob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((blob) => {
        if (blob) {
          resolve(blob);
        } else {
          reject(new Error("图片导出失败"));
        }
      }, "image/png");
    });
    downloadBlob(pngBlob, filename);
  } finally {
    URL.revokeObjectURL(svgUrl);
  }
}

export function MermaidBlock({ chart, variant = "default" }: MermaidBlockProps) {
  const rawId = useId();
  const diagramId = useMemo(
    () => `atm-mermaid-${rawId.replace(/[:]/g, "-")}-${hashChart(chart)}`,
    [chart, rawId],
  );
  const [svgMarkup, setSvgMarkup] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [viewerZoom, setViewerZoom] = useState(1);
  const [downloadBusy, setDownloadBusy] = useState(false);

  useEffect(() => {
    let disposed = false;

    async function renderDiagram() {
      setSvgMarkup("");
      setErrorMessage(null);

      try {
        const rendered = await renderMermaidChart(diagramId, chart);
        if (!disposed) {
          setSvgMarkup(rendered.svg);
          setViewerOpen(false);
          setViewerZoom(1);
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
  const canUseRenderedDiagram = Boolean(svgMarkup);
  const viewerSvgSize = useMemo(
    () => (svgMarkup ? getSvgSize(svgMarkup) : { width: 1400, height: 800 }),
    [svgMarkup],
  );
  const downloadFilename = `${sanitizeDownloadName(diagramLabel)}-${hashChart(chart)}.png`;
  const handleDownload = async () => {
    if (!svgMarkup || downloadBusy) {
      return;
    }
    setDownloadBusy(true);
    try {
      await downloadSvgAsPng(svgMarkup, downloadFilename);
    } catch {
      downloadBlob(new Blob([svgMarkup], { type: "image/svg+xml;charset=utf-8" }), downloadFilename.replace(/\.png$/i, ".svg"));
    } finally {
      setDownloadBusy(false);
    }
  };

  return (
    <figure
      className={cn(
        "my-6 overflow-hidden border",
        isDocument
          ? "rounded-md border-[#D7DDE5] bg-white dark:border-slate-800 dark:bg-slate-950/80"
          : "rounded-2xl border-indigo-100 bg-indigo-50/70 shadow-sm dark:border-indigo-500/20 dark:bg-slate-950/80 dark:shadow-[0_18px_40px_-28px_rgba(0,0,0,0.72)]",
      )}
    >
      <div
        className={cn(
          "flex items-center justify-between gap-3 border-b px-4 py-3",
          isDocument
            ? "border-[#E4E7EC] bg-[#F7F8FA] dark:border-slate-800 dark:bg-slate-900/80"
            : "border-indigo-100/80 bg-white/80 dark:border-indigo-500/20 dark:bg-slate-950/80",
        )}
      >
        <div className="flex items-center gap-2">
          {!isDocument ? (
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-2xl bg-indigo-100 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300">
              <Sparkles className="h-4 w-4" />
            </span>
          ) : null}
          <p className={cn(
            "font-semibold text-slate-900 dark:text-slate-100",
            isDocument ? "text-[13px]" : "text-sm",
          )}>
            {diagramLabel}
          </p>
        </div>

        <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
          {canUseRenderedDiagram ? (
            <>
              <button
                type="button"
                onClick={() => setViewerOpen(true)}
                className="inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-slate-500 transition-colors hover:bg-white hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
                aria-label={`放大查看${diagramLabel}`}
                title={`放大查看${diagramLabel}`}
              >
                <Maximize2 className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">查看</span>
              </button>
              <button
                type="button"
                onClick={() => void handleDownload()}
                disabled={downloadBusy}
                className="inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-slate-500 transition-colors hover:bg-white hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
                aria-label={`下载${diagramLabel}图片`}
                title={`下载${diagramLabel}图片`}
              >
                {downloadBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                <span className="hidden sm:inline">下载</span>
              </button>
            </>
          ) : errorMessage ? (
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
      {viewerOpen && svgMarkup ? (
        <div
          className="fixed inset-0 z-[1000] flex bg-slate-950/70 p-3 backdrop-blur-sm sm:p-6"
          role="dialog"
          aria-modal="true"
          aria-label={`${diagramLabel}大图查看`}
          onClick={() => setViewerOpen(false)}
        >
          <div
            className="flex min-h-0 w-full flex-col overflow-hidden rounded-lg bg-white shadow-2xl ring-1 ring-black/10 dark:bg-slate-950 dark:ring-white/10"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-slate-200 px-3 dark:border-slate-800">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-950 dark:text-slate-50">{diagramLabel}</p>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  onClick={() => setViewerZoom((value) => Math.max(0.5, Number((value - 0.25).toFixed(2))))}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
                  aria-label="缩小"
                  title="缩小"
                >
                  <Minus className="h-4 w-4" />
                </button>
                <span className="w-12 text-center text-xs tabular-nums text-slate-500 dark:text-slate-400">
                  {Math.round(viewerZoom * 100)}%
                </span>
                <button
                  type="button"
                  onClick={() => setViewerZoom((value) => Math.min(3, Number((value + 0.25).toFixed(2))))}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
                  aria-label="放大"
                  title="放大"
                >
                  <Plus className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  onClick={() => void handleDownload()}
                  disabled={downloadBusy}
                  className="ml-1 inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-950 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
                  aria-label={`下载${diagramLabel}图片`}
                  title={`下载${diagramLabel}图片`}
                >
                  {downloadBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                  PNG
                </button>
                <button
                  type="button"
                  onClick={() => setViewerOpen(false)}
                  className="ml-1 inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
                  aria-label="关闭大图"
                  title="关闭"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-auto bg-slate-50 p-6 dark:bg-slate-900/60">
              <div
                className="relative mx-auto"
                style={{
                  width: Math.ceil((viewerSvgSize.width + 48) * viewerZoom),
                  height: Math.ceil((viewerSvgSize.height + 48) * viewerZoom),
                }}
              >
                <div
                  className="absolute left-0 top-0 inline-block origin-top-left rounded-md bg-white p-6 shadow-sm ring-1 ring-slate-200 dark:bg-slate-950 dark:ring-slate-800 [&_svg]:h-auto [&_svg]:max-w-none"
                  style={{ transform: `scale(${viewerZoom})`, transformOrigin: "top left" }}
                  dangerouslySetInnerHTML={{ __html: svgMarkup }}
                />
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </figure>
  );
}

export type { MermaidBlockVariant };
