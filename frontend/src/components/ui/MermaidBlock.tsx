import { useEffect, useId, useMemo, useState } from "react";
import mermaid from "mermaid";
import { Loader2, Sparkles, TriangleAlert } from "lucide-react";

import { cn } from "../../lib/utils";

type MermaidBlockVariant = "default" | "document";

interface MermaidBlockProps {
  chart: string;
  variant?: MermaidBlockVariant;
}

let mermaidConfigured = false;

function ensureMermaidConfigured() {
  if (mermaidConfigured) {
    return;
  }

  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: "base",
    suppressErrorRendering: true,
    themeVariables: {
      primaryColor: "#e0f2fe",
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
        ensureMermaidConfigured();
        const rendered = await mermaid.render(diagramId, chart);
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
          ? "rounded-[28px] border-sky-100 bg-[radial-gradient(circle_at_top_left,#e0f2fe_0%,#ffffff_38%,#f8fafc_100%)] shadow-[0_28px_80px_-56px_rgba(14,116,144,0.55)]"
          : "rounded-2xl border-sky-100 bg-sky-50/70 shadow-sm",
      )}
    >
      <div
        className={cn(
          "flex items-center justify-between gap-3 border-b px-4 py-3",
          isDocument ? "border-sky-100/80 bg-white/70" : "border-sky-100/80 bg-white/80",
        )}
      >
        <div className="flex items-center gap-2">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-2xl bg-sky-100 text-sky-700">
            <Sparkles className="h-4 w-4" />
          </span>
          <div>
            <p className="text-sm font-semibold text-slate-900">{diagramLabel}</p>
            <p className="text-xs text-slate-500">Mermaid 实时渲染</p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500">
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
            isDocument ? "bg-transparent" : "bg-white/60",
          )}
          dangerouslySetInnerHTML={{ __html: svgMarkup }}
        />
      ) : (
        <div className="px-4 py-5">
          <pre className="overflow-x-auto rounded-2xl bg-slate-950 p-4 text-[13px] leading-6 text-slate-100">
            <code>{chart}</code>
          </pre>
          {errorMessage ? (
            <p className="mt-3 text-xs leading-5 text-amber-700">
              Mermaid 渲染失败：{errorMessage}
            </p>
          ) : null}
        </div>
      )}
    </figure>
  );
}

export type { MermaidBlockVariant };
