import { useRef, useState, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import * as d3 from "d3";
import {
  Loader2,
  Network as NetworkIcon,
  X,
  Tag,
  Link2,
  FileText,
  ChevronRight,
  ExternalLink,
} from "lucide-react";

import { graphKnowledgeUnitDetailApiV1CoursesCourseIdKnowledgeGraphKnowledgeUnitsDetailPost } from "../../api/generated/knowledge";
import type { FullGraphResponse } from "../../api/generated/model";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { MarkdownViewer } from "../ui/MarkdownViewer";

// 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ MiroFish Color Palette 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

const NODE_COLORS: Record<string, { fill: string; dark: string; label: string }> = {
  concept:    { fill: "#5dade2", dark: "#2e86c1", label: "概念" },
  definition: { fill: "#58d68d", dark: "#28b463", label: "定义" },
  theorem:    { fill: "#48c9b0", dark: "#17a589", label: "定理" },
  formula:    { fill: "#5d6d7e", dark: "#2c3e50", label: "公式" },
  example:    { fill: "#af7ac5", dark: "#7d3c98", label: "示例" },
  exercise:   { fill: "#e74c3c", dark: "#c0392b", label: "练习" },
  method:     { fill: "#ec7063", dark: "#cb4335", label: "方法" },
  proof_step: { fill: "#8e44ad", dark: "#6c3483", label: "证明步骤" },
  remark:     { fill: "#7f8c8d", dark: "#566573", label: "备注" },
};

const DEFAULT_COLOR = { fill: "#aab7b8", dark: "#717d7e", label: "其他" };

// 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ Interfaces 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

interface GraphNode extends d3.SimulationNodeDatum {
  id: number;
  canonical_name: string;
  knowledge_unit_type: string;
  confidence: number;
}

interface GraphLink extends d3.SimulationLinkDatum<GraphNode> {
  edge_type: string;
  source_node_id: number;
  target_node_id: number;
}

// 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ Node Detail Sidebar (unchanged) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

function NodeDetailSidebar({
  course,
  nodeId,
  onClose,
  onNavigate,
  onEvidenceClick,
}: {
  course: string;
  nodeId: number;
  onClose: () => void;
  onNavigate: (id: number) => void;
  onEvidenceClick?: (chunkId: number, quoteText: string) => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["graph-node-detail", course, nodeId],
    queryFn: async () =>
      unwrapOrvalResponse(
        await graphKnowledgeUnitDetailApiV1CoursesCourseIdKnowledgeGraphKnowledgeUnitsDetailPost(course, {
          knowledge_unit_id: nodeId,
        }),
      ) ?? null,
    enabled: !!nodeId,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8 text-slate-400">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />加载中...
      </div>
    );
  }

  if (!data) return null;

  const color = NODE_COLORS[data.knowledge_unit_type] ?? DEFAULT_COLOR;
  const aliases = data.aliases ?? [];
  const incidentEdges = data.incident_edges ?? [];
  const evidenceList = data.evidence ?? [];
  const sourceRefs = data.source_refs ?? [];

  return (
    <div className="animate-in slide-in-from-right-4 space-y-4 duration-200">
      <div className="flex items-start justify-between">
        <div>
          <div className="mb-1 flex items-center gap-2">
            <h3 className="text-lg font-semibold text-slate-800">
              <MarkdownViewer content={data.canonical_name} />
            </h3>
            <span
              className="rounded-full px-2 py-0.5 text-xs font-medium text-white"
              style={{ backgroundColor: color.fill }}
            >
              {color.label}
            </span>
          </div>
          <p className="text-xs text-slate-400">置信度：{Math.round(data.confidence * 100)}%</p>
        </div>
        <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600">
          <X className="h-4 w-4" />
        </button>
      </div>

      {data.current_revision && (
        <div className="space-y-2">
          {data.current_revision.summary && (
            <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">
              <MarkdownViewer content={data.current_revision.summary} />
            </div>
          )}
          {data.current_revision.body && (
            <div className="max-h-48 overflow-y-auto rounded-lg border border-slate-100 p-3 text-sm">
              <MarkdownViewer content={data.current_revision.body} />
            </div>
          )}
        </div>
      )}

      {aliases.length > 0 && (
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-500">
            <Tag className="h-3 w-3" />别名
          </div>
          <div className="flex flex-wrap gap-1.5">
            {aliases.map((a: { id: number; is_primary: boolean; alias: string }) => (
              <span key={a.id} className={`rounded-full px-2 py-0.5 text-xs ${a.is_primary ? "bg-slate-800 text-white" : "bg-slate-100 text-slate-600"}`}>
                {a.alias}
              </span>
            ))}
          </div>
        </div>
      )}

      {incidentEdges.length > 0 && (
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-500">
            <Link2 className="h-3 w-3" />关联边 ({incidentEdges.length})
          </div>
          <div className="max-h-40 space-y-1 overflow-y-auto">
            {incidentEdges.map((edge: { id: number; other_node_id: number; direction: string; other_node_name: string; edge_type: string }) => (
              <button key={edge.id} onClick={() => onNavigate(edge.other_node_id)}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors hover:bg-slate-50">
                <span className="text-slate-400">{edge.direction === "outgoing" ? "->" : "<-"}</span>
                <span className="flex-1 truncate text-slate-700">{edge.other_node_name}</span>
                <span className="text-[10px] text-slate-400">{edge.edge_type}</span>
                <ChevronRight className="h-3 w-3 text-slate-300" />
              </button>
            ))}
          </div>
        </div>
      )}

      {sourceRefs.length > 0 && (
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-500">
            <FileText className="h-3 w-3" />图谱来源 ({sourceRefs.length})
          </div>
          <div className="max-h-40 space-y-1.5 overflow-y-auto">
            {sourceRefs.map((ref: { id: number; chapter_index?: number; chapter_title?: string | null; doc_version_no?: number; source_kind?: string; source_file_ids?: string[]; quote_text?: string }) => (
              <div key={ref.id} className="rounded border border-slate-100 bg-slate-50 p-2 text-xs text-slate-600">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-medium text-slate-700">
                    {ref.chapter_title || (ref.chapter_index ? `第 ${ref.chapter_index} 章` : "知识文档")}
                  </span>
                  {ref.doc_version_no ? <span className="shrink-0 text-[10px] text-slate-400">v{ref.doc_version_no}</span> : null}
                </div>
                <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-slate-400">
                  {ref.source_kind ? <span>{ref.source_kind}</span> : null}
                  {ref.source_file_ids?.length ? <span>资料 {ref.source_file_ids.join(", ")}</span> : null}
                </div>
                {ref.quote_text ? <p className="mt-1 line-clamp-2 text-slate-500">{ref.quote_text}</p> : null}
              </div>
            ))}
          </div>
        </div>
      )}

      {evidenceList.length > 0 && (
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-500">
            <FileText className="h-3 w-3" />来源证据 ({evidenceList.length})
          </div>
          <div className="max-h-40 space-y-1.5 overflow-y-auto">
            {evidenceList.map((ev: { id: number; chunk_id: number; quote_text: string; evidence_role: string; confidence: number }) => (
              <button key={ev.id} onClick={() => onEvidenceClick?.(ev.chunk_id, ev.quote_text)}
                className="group w-full cursor-pointer rounded border-l-2 border-slate-300 bg-slate-50 p-2 text-left text-xs text-slate-600 transition-colors hover:border-amber-400 hover:bg-amber-50/50">
                <p className="line-clamp-3">{ev.quote_text}</p>
                <div className="mt-1 flex items-center justify-between">
                  <p className="text-[10px] text-slate-400">{ev.evidence_role} 路 {Math.round(ev.confidence * 100)}%</p>
                  <ExternalLink className="h-3 w-3 text-slate-300 transition-colors group-hover:text-amber-500" />
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ D3 SVG Force Graph (MiroFish approach) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

export function ForceGraphView({
  course,
  toolbar,
  onEvidenceClick,
  fullGraphData,
}: {
  course: string;
  toolbar?: React.ReactNode;
  onEvidenceClick?: (chunkId: number, quoteText: string) => void;
  fullGraphData: FullGraphResponse | null;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [showEdgeLabels, setShowEdgeLabels] = useState(true);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const simulationRef = useRef<d3.Simulation<GraphNode, GraphLink> | null>(null);

  const rawData = fullGraphData;

  // Parse graph data
  const { nodes, links, presentTypes, nodeCount, edgeCount } = useMemo(() => {
    if (!rawData) return { nodes: [] as GraphNode[], links: [] as GraphLink[], presentTypes: [] as { type: string; fill: string; label: string }[], nodeCount: 0, edgeCount: 0 };

    const nodeIdSet = new Set((rawData.nodes ?? []).map((n: any) => n.id));
    const typeSet = new Set<string>();

    const nodes: GraphNode[] = (rawData.nodes ?? []).map((n: any) => {
      typeSet.add(n.knowledge_unit_type);
      return { id: n.id, canonical_name: n.canonical_name, knowledge_unit_type: n.knowledge_unit_type, confidence: n.confidence };
    });

    const links: GraphLink[] = (rawData.edges ?? [])
      .filter((e: any) => nodeIdSet.has(e.source_node_id) && nodeIdSet.has(e.target_node_id))
      .map((e: any) => ({
        source: e.source_node_id,
        target: e.target_node_id,
        edge_type: e.edge_type,
        source_node_id: e.source_node_id,
        target_node_id: e.target_node_id,
      }));

    const types = Array.from(typeSet)
      .map((t) => ({ type: t, ...(NODE_COLORS[t] ?? DEFAULT_COLOR) }))
      .sort((a, b) => a.label.localeCompare(b.label));

    return { nodes, links, presentTypes: types, nodeCount: nodes.length, edgeCount: links.length };
  }, [rawData]);

  // Measure container
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => {
      const rect = el.getBoundingClientRect();
      const w = Math.round(rect.width || el.clientWidth || 0);
      const h = Math.round(rect.height || el.clientHeight || 0);
      if (w > 0 && h > 0) {
        setDimensions((prev) => (prev.width === w && prev.height === h ? prev : { width: w, height: h }));
      }
    };
    measure();
    const obs = new ResizeObserver(measure);
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  // 鈹€鈹€ D3 Force Simulation + SVG Rendering 鈹€鈹€
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || nodes.length === 0) return;

    const { width, height } = dimensions;

    // Clear previous
    d3.select(svg).selectAll("*").remove();

    // Deep copy nodes/links so D3 can mutate them
    const simNodes: GraphNode[] = nodes.map((n) => ({ ...n }));
    const simLinks: GraphLink[] = links.map((l) => ({ ...l, source: l.source_node_id, target: l.target_node_id }));

    // SVG structure
    const svgSel = d3.select(svg)
      .attr("width", width)
      .attr("height", height)
      .attr("viewBox", [0, 0, width, height].join(" "));

    // Background: clean minimalist flat color
    svgSel.append("rect")
      .attr("width", width)
      .attr("height", height)
      .attr("fill", "#fafaf9");

    // Container for zoom/pan
    const g = svgSel.append("g");

    // Zoom behavior
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.15, 5])
      .on("zoom", (event) => {
        g.attr("transform", event.transform);
      });
    svgSel.call(zoom);

    // 鈹€鈹€ SVG Defs: simple marker 鈹€鈹€
    const defs = svgSel.append("defs");

    // Glow filter for hover (simplified)
    const glowFilter = defs.append("filter")
      .attr("id", "node-glow")
      .attr("x", "-20%").attr("y", "-20%")
      .attr("width", "140%").attr("height", "140%");
    glowFilter.append("feGaussianBlur")
      .attr("stdDeviation", "2")
      .attr("result", "blur");
    glowFilter.append("feMerge")
      .selectAll("feMergeNode")
      .data(["blur", "SourceGraphic"])
      .join("feMergeNode")
      .attr("in", (d) => d);

    // Arrow marker
    defs.append("marker")
      .attr("id", "arrowhead")
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 28)
      .attr("refY", 0)
      .attr("markerWidth", 8)
      .attr("markerHeight", 8)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-4L8,0L0,4")
      .attr("fill", "#aaa");

    // Links group
    const linkGroup = g.append("g").attr("class", "links");

    // Link lines (straight, clean)
    const linkLine = linkGroup.selectAll<SVGPathElement, GraphLink>("path")
      .data(simLinks)
      .join("path")
      .attr("fill", "none")
      .attr("stroke", "#C0C0C0")
      .attr("stroke-width", 1.5)
      .attr("marker-end", "url(#arrowhead)");

    // Link labels (clean white background effect using stroke)
    const linkLabel = linkGroup.selectAll<SVGTextElement, GraphLink>("text")
      .data(simLinks)
      .join("text")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .attr("font-size", "9px")
      .attr("fill", "#666")
      .attr("stroke", "rgba(255,255,255,0.95)")
      .attr("stroke-width", 4)
      .attr("paint-order", "stroke")
      .attr("font-family", "system-ui, sans-serif")
      .attr("pointer-events", "none")
      .attr("display", showEdgeLabels ? null : "none")
      .text((d) => d.edge_type.toUpperCase());

    // Node group
    const nodeGroup = g.append("g").attr("class", "nodes");

    // Node containers
    const nodeG = nodeGroup.selectAll<SVGGElement, GraphNode>("g")
      .data(simNodes)
      .join("g")
      .attr("cursor", "pointer")
      .call(
        d3.drag<SVGGElement, GraphNode>()
          .on("start", (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on("end", (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
      );

    // Node click handler
    nodeG.on("click", (_event, d) => {
      setSelectedNodeId((prev) => (prev === d.id ? null : d.id));
    });

    // Node circles 鈥?clean, flat design
    nodeG.append("circle")
      .attr("r", 10)
      .attr("fill", (d) => (NODE_COLORS[d.knowledge_unit_type] ?? DEFAULT_COLOR).fill)
      .attr("stroke", "#fff")
      .attr("stroke-width", 2.5);

    // Node labels 鈥?clean, no shadows for extreme minimalist clarity
    nodeG.append("text")
      .attr("dx", 14)
      .attr("dy", 4)
      .attr("font-size", "11px")
      .attr("font-family", "system-ui, sans-serif")
      .attr("font-weight", "500")
      .attr("fill", "#333")
      .style("pointer-events", "none")
      .text((d) => d.canonical_name.length > 8 ? `${d.canonical_name.slice(0, 8)}...` : d.canonical_name);

    // Hover effects
    nodeG
      .on("mouseenter", function (_event, d) {
        // Highlight logic
        if (!selectedNodeId || selectedNodeId !== d.id) {
          d3.select(this).select("circle").attr("stroke", "#333").attr("stroke-width", 3);
        }
      })
      .on("mouseleave", function (_event, d) {
        if (!selectedNodeId || selectedNodeId !== d.id) {
          d3.select(this).select("circle").attr("stroke", "#fff").attr("stroke-width", 2.5);
        }
      });

    // Force simulation 鈥?simple and robust
    const simulation = d3.forceSimulation<GraphNode>(simNodes)
      .force("link", d3.forceLink<GraphNode, GraphLink>(simLinks).id((d) => d.id).distance(150))
      .force("charge", d3.forceManyBody().strength(-400))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(50))
      .force("x", d3.forceX(width / 2).strength(0.04))
      .force("y", d3.forceY(height / 2).strength(0.04));

    simulationRef.current = simulation;

    simulation.on("tick", () => {
      // Straight lines
      linkLine.attr("d", (d: any) => `M${d.source.x},${d.source.y} L${d.target.x},${d.target.y}`);

      linkLabel
        .attr("x", (d: any) => (d.source.x + d.target.x) / 2)
        .attr("y", (d: any) => (d.source.y + d.target.y) / 2)
        .attr("transform", ""); // Explicitly avoid rotation for legibility

      nodeG.attr("transform", (d: any) => `translate(${d.x},${d.y})`);
    });

    // Fit to view after stabilization
    simulation.on("end", () => {
      const xExtent = d3.extent(simNodes, (d) => d.x) as [number, number];
      const yExtent = d3.extent(simNodes, (d) => d.y) as [number, number];
      if (xExtent[0] == null) return;
      const pad = 60;
      const gw = xExtent[1] - xExtent[0] + pad * 2;
      const gh = yExtent[1] - yExtent[0] + pad * 2;
      const scale = Math.min(width / gw, height / gh, 1.5);
      const tx = width / 2 - ((xExtent[0] + xExtent[1]) / 2) * scale;
      const ty = height / 2 - ((yExtent[0] + yExtent[1]) / 2) * scale;
      svgSel.transition().duration(600)
        .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
    });

    return () => {
      simulation.stop();
    };
  }, [nodes, links, dimensions, showEdgeLabels]);

  // 鈹€鈹€ Empty state 鈹€鈹€
  if (!rawData || (rawData.nodes ?? []).length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-slate-400">
        <NetworkIcon className="mb-2 h-8 w-8 text-slate-300" />
        <p className="text-sm">暂无可展示的图谱数据</p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-[520px] flex-col gap-0 lg:min-h-[640px] lg:flex-row">
      {/* Graph panel */}
      <div className="relative min-h-[420px] min-w-0 flex-1 lg:min-h-[640px]">
        <div ref={containerRef} className="absolute inset-0">
          <svg ref={svgRef} className="h-full w-full" />
        </div>

        {/* Top-left: toolbar + stats + edge label toggle */}
        <div className="pointer-events-auto absolute left-3 top-3 z-10 flex max-w-[calc(100%-1.5rem)] flex-wrap items-center gap-2">
          {toolbar}
          <span className="rounded-full bg-white/90 px-2.5 py-1 text-[10px] font-medium text-slate-500 shadow-sm ring-1 ring-slate-200/60">
            {nodeCount} 节点 · {edgeCount} 边
          </span>
          <button
            onClick={() => setShowEdgeLabels((v) => !v)}
            className="flex items-center gap-1.5 rounded-full bg-white/90 px-2.5 py-1 text-[10px] font-medium text-slate-500 shadow-sm ring-1 ring-slate-200/60 transition-colors hover:bg-white"
          >
            <span className="inline-block h-3.5 w-7 rounded-full p-0.5 transition-colors" style={{ backgroundColor: showEdgeLabels ? "#8b5cf6" : "#d1d5db" }}>
              <span className="block h-2.5 w-2.5 rounded-full bg-white shadow transition-transform" style={{ transform: showEdgeLabels ? "translateX(14px)" : "translateX(0)" }} />
            </span>
            边标签
          </button>
        </div>

        {/* Bottom-left: Legend */}
        <div className="pointer-events-none absolute bottom-3 left-3 right-3 z-10">
          <div className="inline-flex max-w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-white/80 px-3 py-1.5 ring-1 ring-slate-200/40">
            {presentTypes.map(({ type, fill, label }) => (
              <div key={type} className="flex items-center gap-1">
                <span className="inline-block h-3 w-3 rounded-full" style={{ backgroundColor: fill }} />
                <span className="text-[10px] font-medium text-slate-500">{label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 鈹€鈹€ Detail Sidebar 鈹€鈹€ */}
      {selectedNodeId && (
        <div className="max-h-[45dvh] w-full shrink-0 overflow-y-auto border-t border-slate-200 bg-white lg:max-h-none lg:w-[320px] lg:border-l lg:border-t-0">
          <div className="p-4">
            <NodeDetailSidebar
              course={course}
              nodeId={selectedNodeId}
              onClose={() => setSelectedNodeId(null)}
              onNavigate={(id) => setSelectedNodeId(id)}
              onEvidenceClick={onEvidenceClick}
            />
          </div>
        </div>
      )}
    </div>
  );
}

