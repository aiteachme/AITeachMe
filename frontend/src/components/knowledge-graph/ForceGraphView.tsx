import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import * as d3 from "d3";
import {
  Loader2,
  Network as NetworkIcon,
  RefreshCw,
  X,
  Tag,
  Link2,
  FileText,
  ChevronRight,
  ExternalLink,
} from "lucide-react";

import {
  graphFocusSubgraphApiV1CoursesCourseIdKnowledgeGraphSubgraphPost,
  graphKnowledgeUnitDetailApiV1CoursesCourseIdKnowledgeGraphKnowledgeUnitsDetailPost,
} from "../../api/generated/knowledge";
import type { KnowledgeRelationResponse, KnowledgeSubgraphResponse, KnowledgeUnitResponse } from "../../api/generated/model";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { MarkdownViewer } from "../ui/MarkdownViewer";

const NODE_COLORS: Record<string, { fill: string; dark: string; label: string }> = {
  concept: { fill: "#2563eb", dark: "#1d4ed8", label: "概念" },
  definition: { fill: "#059669", dark: "#047857", label: "定义" },
  theorem: { fill: "#7c3aed", dark: "#6d28d9", label: "定理" },
  formula: { fill: "#475569", dark: "#334155", label: "公式" },
  example: { fill: "#a855f7", dark: "#9333ea", label: "示例" },
  exercise: { fill: "#ef4444", dark: "#dc2626", label: "练习" },
  method: { fill: "#f97316", dark: "#ea580c", label: "方法" },
  proof_step: { fill: "#0f766e", dark: "#115e59", label: "证明步骤" },
  remark: { fill: "#64748b", dark: "#475569", label: "备注" },
};

const DEFAULT_COLOR = { fill: "#94a3b8", dark: "#64748b", label: "其他" };

const RELATION_LABELS: Record<string, string> = {
  prerequisite: "前置",
  derivation: "推导",
  application: "应用",
  example_of: "例子",
  similar: "相似",
  contrast: "对比",
};

const RELATION_COLORS: Record<string, string> = {
  prerequisite: "#64748b",
  derivation: "#94a3b8",
  application: "#60a5fa",
  example_of: "#a78bfa",
  similar: "#14b8a6",
  contrast: "#f97316",
};

function truncateGraphLabel(value: string, maxChars = 12): string {
  const text = String(value || "").trim();
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars - 1)}…`;
}

function relationLabel(edgeType: string): string {
  return RELATION_LABELS[edgeType] ?? edgeType.replace(/_/g, " ");
}

interface GraphNode extends d3.SimulationNodeDatum {
  id: number;
  canonical_name: string;
  knowledge_unit_type: string;
  confidence: number;
  degree: number;
}

interface GraphLink extends d3.SimulationLinkDatum<GraphNode> {
  id: number;
  edge_type: string;
  relation_label: string;
  source_node_id: number;
  target_node_id: number;
}

type LoadedGraphData = {
  nodes: KnowledgeUnitResponse[];
  edges: KnowledgeRelationResponse[];
};

function compactSubgraph(payload: KnowledgeSubgraphResponse | null | undefined): LoadedGraphData {
  return {
    nodes: payload?.nodes ?? [],
    edges: payload?.edges ?? [],
  };
}

function mergeGraphData(current: LoadedGraphData | null, incoming: KnowledgeSubgraphResponse | null | undefined): LoadedGraphData {
  const next = compactSubgraph(incoming);
  const nodeById = new Map<number, KnowledgeUnitResponse>();
  const edgeByKey = new Map<string, KnowledgeRelationResponse>();

  for (const node of current?.nodes ?? []) {
    nodeById.set(node.id, node);
  }
  for (const node of next.nodes) {
    nodeById.set(node.id, node);
  }

  const appendEdge = (edge: KnowledgeRelationResponse) => {
    const key = edge.id ? `id:${edge.id}` : `${edge.source_node_id}:${edge.target_node_id}:${edge.edge_type}`;
    edgeByKey.set(key, edge);
  };
  for (const edge of current?.edges ?? []) appendEdge(edge);
  for (const edge of next.edges) appendEdge(edge);

  return {
    nodes: Array.from(nodeById.values()),
    edges: Array.from(edgeByKey.values()),
  };
}

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
        <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-200">
          <X className="h-4 w-4" />
        </button>
      </div>

      {data.current_revision && (
        <div className="space-y-2">
          {data.current_revision.summary && (
            <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600 dark:bg-slate-900 dark:text-slate-300">
              <MarkdownViewer content={data.current_revision.summary} />
            </div>
          )}
          {data.current_revision.body && (
            <div className="max-h-48 overflow-y-auto rounded-lg border border-slate-100 p-3 text-sm dark:border-slate-800 dark:text-slate-300">
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
              <span key={a.id} className={`rounded-full px-2 py-0.5 text-xs ${a.is_primary ? "bg-slate-800 text-white dark:bg-slate-100 dark:text-slate-900" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"}`}>
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
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/70">
                <span className="text-slate-400">{edge.direction === "outgoing" ? "->" : "<-"}</span>
                <span className="flex-1 truncate text-slate-700 dark:text-slate-300">{edge.other_node_name}</span>
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
              <div key={ref.id} className="rounded border border-slate-100 bg-slate-50 p-2 text-xs text-slate-600 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-300">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-medium text-slate-700 dark:text-slate-200">
                    {ref.chapter_title || (ref.chapter_index ? `第 ${ref.chapter_index} 章` : "知识文档")}
                  </span>
                  {ref.doc_version_no ? <span className="shrink-0 text-[10px] text-slate-400">v{ref.doc_version_no}</span> : null}
                </div>
                <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-slate-400">
                  {ref.source_kind ? <span>{ref.source_kind}</span> : null}
                  {ref.source_file_ids?.length ? <span>资料 {ref.source_file_ids.join(", ")}</span> : null}
                </div>
                {ref.quote_text ? <p className="mt-1 line-clamp-2 text-slate-500 dark:text-slate-400">{ref.quote_text}</p> : null}
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
                className="group w-full cursor-pointer rounded border-l-2 border-slate-300 bg-slate-50 p-2 text-left text-xs text-slate-600 transition-colors hover:border-amber-400 hover:bg-amber-50/50 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:border-amber-400/70 dark:hover:bg-amber-500/10">
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


export function ForceGraphView({
  course,
  toolbar,
  onEvidenceClick,
  totalNodeCount,
  totalEdgeCount,
}: {
  course: string;
  toolbar?: React.ReactNode;
  onEvidenceClick?: (chunkId: number, quoteText: string) => void;
  totalNodeCount?: number;
  totalEdgeCount?: number;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [showEdgeLabels, setShowEdgeLabels] = useState(false);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [graphData, setGraphData] = useState<LoadedGraphData | null>(null);
  const [expandedNodeIds, setExpandedNodeIds] = useState<Set<number>>(new Set());
  const [expandingNodeId, setExpandingNodeId] = useState<number | null>(null);
  const simulationRef = useRef<d3.Simulation<GraphNode, GraphLink> | null>(null);

  const {
    data: initialSubgraph,
    isLoading: initialLoading,
    isFetching: initialFetching,
    refetch: refetchInitialSubgraph,
  } = useQuery({
    queryKey: ["graph-subgraph", course, "initial", totalNodeCount ?? 0, totalEdgeCount ?? 0],
    queryFn: async () =>
      unwrapOrvalResponse(
        await graphFocusSubgraphApiV1CoursesCourseIdKnowledgeGraphSubgraphPost(course, {
          hops: 1,
          limit: 80,
        }),
      ) ?? null,
    enabled: Boolean(course),
    retry: false,
  });

  useEffect(() => {
    if (!initialSubgraph) return;
    setGraphData(compactSubgraph(initialSubgraph));
    setExpandedNodeIds(new Set());
    setSelectedNodeId(null);
  }, [initialSubgraph, course]);

  const expandNode = useCallback(
    async (nodeId: number) => {
      if (!course || expandedNodeIds.has(nodeId)) return;
      setExpandingNodeId(nodeId);
      try {
        const payload =
          unwrapOrvalResponse(
            await graphFocusSubgraphApiV1CoursesCourseIdKnowledgeGraphSubgraphPost(course, {
              center_knowledge_unit_id: nodeId,
              hops: 1,
              limit: 80,
            }),
          ) ?? null;
        setGraphData((current) => mergeGraphData(current, payload));
        setExpandedNodeIds((current) => {
          const next = new Set(current);
          next.add(nodeId);
          return next;
        });
      } catch {
        // Keep the currently loaded graph visible if expansion fails.
      } finally {
        setExpandingNodeId(null);
      }
    },
    [expandedNodeIds, course],
  );

  const resetGraph = useCallback(() => {
    setGraphData(null);
    setExpandedNodeIds(new Set());
    setSelectedNodeId(null);
    void refetchInitialSubgraph();
  }, [refetchInitialSubgraph]);

  const rawData = graphData;

  // Parse graph data
  const { nodes, links, presentTypes, nodeCount, edgeCount } = useMemo(() => {
    if (!rawData) return { nodes: [] as GraphNode[], links: [] as GraphLink[], presentTypes: [] as { type: string; fill: string; label: string }[], nodeCount: 0, edgeCount: 0 };

    const nodeIdSet = new Set((rawData.nodes ?? []).map((n: any) => n.id));
    const typeSet = new Set<string>();

    const links: GraphLink[] = (rawData.edges ?? [])
      .filter((e: any) => nodeIdSet.has(e.source_node_id) && nodeIdSet.has(e.target_node_id))
      .map((e: any) => ({
        id: e.id,
        source: e.source_node_id,
        target: e.target_node_id,
        edge_type: e.edge_type,
        relation_label: relationLabel(e.edge_type),
        source_node_id: e.source_node_id,
        target_node_id: e.target_node_id,
      }));
    const degreeByNodeId = new Map<number, number>();
    for (const link of links) {
      degreeByNodeId.set(link.source_node_id, (degreeByNodeId.get(link.source_node_id) ?? 0) + 1);
      degreeByNodeId.set(link.target_node_id, (degreeByNodeId.get(link.target_node_id) ?? 0) + 1);
    }

    const nodes: GraphNode[] = (rawData.nodes ?? []).map((n: any) => {
      typeSet.add(n.knowledge_unit_type);
      return {
        id: n.id,
        canonical_name: n.canonical_name,
        knowledge_unit_type: n.knowledge_unit_type,
        confidence: n.confidence,
        degree: degreeByNodeId.get(n.id) ?? 0,
      };
    });

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

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || nodes.length === 0) return;

    const { width, height } = dimensions;

    // Clear previous
    d3.select(svg).selectAll("*").remove();

    const selectedNeighbors = new Set<number>();
    if (selectedNodeId !== null) {
      for (const link of links) {
        if (link.source_node_id === selectedNodeId) selectedNeighbors.add(link.target_node_id);
        if (link.target_node_id === selectedNodeId) selectedNeighbors.add(link.source_node_id);
      }
    }
    const isConnectedToSelected = (link: GraphLink) =>
      selectedNodeId === null || link.source_node_id === selectedNodeId || link.target_node_id === selectedNodeId;
    const nodeRadius = (node: GraphNode) => Math.min(18, 8 + Math.sqrt(Math.max(1, node.degree)) * 2.2);

    // Deep copy nodes/links so D3 can mutate them
    const simNodes: GraphNode[] = nodes.map((n) => ({ ...n }));
    const simLinks: GraphLink[] = links.map((l) => ({ ...l, source: l.source_node_id, target: l.target_node_id }));

    // SVG structure
    const svgSel = d3.select(svg)
      .attr("width", width)
      .attr("height", height)
      .attr("viewBox", [0, 0, width, height].join(" "));

    const defs = svgSel.append("defs");

    const grid = defs.append("pattern")
      .attr("id", "knowledge-graph-grid")
      .attr("width", 32)
      .attr("height", 32)
      .attr("patternUnits", "userSpaceOnUse");
    grid.append("path")
      .attr("d", "M 32 0 L 0 0 0 32")
      .attr("fill", "none")
      .attr("stroke", "#e2e8f0")
      .attr("stroke-width", 0.8)
      .attr("opacity", 0.45);

    // Background: subtle workspace grid, borrowed from diagram tools without making the graph noisy.
    svgSel.append("rect")
      .attr("width", width)
      .attr("height", height)
      .attr("fill", "#f8fafc");
    svgSel.append("rect")
      .attr("width", width)
      .attr("height", height)
      .attr("fill", "url(#knowledge-graph-grid)");

    // Container for zoom/pan
    const g = svgSel.append("g");

    // Zoom behavior
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.15, 5])
      .on("zoom", (event) => {
        g.attr("transform", event.transform);
      });
    svgSel.call(zoom);

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
      .attr("refX", 24)
      .attr("refY", 0)
      .attr("markerWidth", 8)
      .attr("markerHeight", 8)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-4L8,0L0,4")
      .attr("fill", "#94a3b8");

    // Links group
    const linkGroup = g.append("g").attr("class", "links");

    const linkLine = linkGroup.selectAll<SVGPathElement, GraphLink>("path")
      .data(simLinks)
      .join("path")
      .attr("fill", "none")
      .attr("stroke", (d) => RELATION_COLORS[d.edge_type] ?? "#94a3b8")
      .attr("stroke-linecap", "round")
      .attr("stroke-width", (d) => (isConnectedToSelected(d) ? 1.8 : 1.1))
      .attr("stroke-opacity", (d) => (selectedNodeId === null ? 0.32 : isConnectedToSelected(d) ? 0.74 : 0.1))
      .attr("marker-end", "url(#arrowhead)");

    linkGroup.selectAll<SVGPathElement, GraphLink>("path.hit-area")
      .data(simLinks)
      .join("path")
      .attr("class", "hit-area")
      .attr("fill", "none")
      .attr("stroke", "transparent")
      .attr("stroke-width", 12);

    // Link labels (clean white background effect using stroke)
    const linkLabel = linkGroup.selectAll<SVGTextElement, GraphLink>("text")
      .data(simLinks)
      .join("text")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .attr("font-size", "10px")
      .attr("fill", "#64748b")
      .attr("stroke", "rgba(248,250,252,0.96)")
      .attr("stroke-width", 5)
      .attr("paint-order", "stroke")
      .attr("font-family", "system-ui, sans-serif")
      .attr("pointer-events", "none")
      .attr("opacity", (d) => (showEdgeLabels && (selectedNodeId === null || isConnectedToSelected(d)) ? 1 : 0))
      .text((d) => d.relation_label);

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
      void expandNode(d.id);
    });

    nodeG.append("circle")
      .attr("class", "node-halo")
      .attr("r", (d) => nodeRadius(d) + 6)
      .attr("fill", (d) => (NODE_COLORS[d.knowledge_unit_type] ?? DEFAULT_COLOR).fill)
      .attr("opacity", (d) => (d.id === selectedNodeId ? 0.18 : 0));

    nodeG.append("circle")
      .attr("class", "node-circle")
      .attr("r", (d) => nodeRadius(d))
      .attr("fill", (d) => (NODE_COLORS[d.knowledge_unit_type] ?? DEFAULT_COLOR).fill)
      .attr("stroke", (d) => (d.id === selectedNodeId ? "#0f172a" : "#ffffff"))
      .attr("stroke-width", (d) => (d.id === selectedNodeId ? 3 : 2.5))
      .attr("opacity", (d) => (
        selectedNodeId === null || d.id === selectedNodeId || selectedNeighbors.has(d.id) ? 1 : 0.42
      ));

    nodeG.append("text")
      .attr("dx", (d) => nodeRadius(d) + 6)
      .attr("dy", 4)
      .attr("font-size", (d) => (d.degree >= 4 || d.id === selectedNodeId ? "12px" : "11px"))
      .attr("font-family", "system-ui, sans-serif")
      .attr("font-weight", (d) => (d.degree >= 4 || d.id === selectedNodeId ? "650" : "500"))
      .attr("fill", (d) => (d.id === selectedNodeId ? "#0f172a" : "#334155"))
      .attr("stroke", "rgba(248,250,252,0.95)")
      .attr("stroke-width", 4)
      .attr("paint-order", "stroke")
      .attr("opacity", (d) => (
        selectedNodeId === null || d.id === selectedNodeId || selectedNeighbors.has(d.id) ? 1 : 0.5
      ))
      .style("pointer-events", "none")
      .text((d) => truncateGraphLabel(d.canonical_name, d.degree >= 4 || d.id === selectedNodeId ? 16 : 12));

    // Hover effects
    nodeG
      .on("mouseenter", function (_event, d) {
        const connectedIds = new Set<number>([d.id]);
        for (const link of simLinks) {
          if (link.source_node_id === d.id) connectedIds.add(link.target_node_id);
          if (link.target_node_id === d.id) connectedIds.add(link.source_node_id);
        }
        nodeG.select<SVGCircleElement>("circle.node-circle")
          .attr("opacity", (node) => (connectedIds.has(node.id) ? 1 : 0.28));
        linkLine
          .attr("stroke-opacity", (link) => (
            link.source_node_id === d.id || link.target_node_id === d.id ? 0.86 : 0.08
          ))
          .attr("stroke-width", (link) => (
            link.source_node_id === d.id || link.target_node_id === d.id ? 2.3 : 1
          ));
        linkLabel.attr("opacity", (link) => (
          showEdgeLabels && (link.source_node_id === d.id || link.target_node_id === d.id) ? 1 : 0
        ));
        d3.select(this).select("circle.node-halo").attr("opacity", 0.2);
        d3.select(this).select("circle.node-circle").attr("stroke", "#0f172a").attr("stroke-width", 3);
      })
      .on("mouseleave", function (_event, d) {
        nodeG.select<SVGCircleElement>("circle.node-circle")
          .attr("opacity", (node) => (
            selectedNodeId === null || node.id === selectedNodeId || selectedNeighbors.has(node.id) ? 1 : 0.42
          ));
        linkLine
          .attr("stroke-opacity", (link) => (
            selectedNodeId === null ? 0.32 : isConnectedToSelected(link) ? 0.74 : 0.1
          ))
          .attr("stroke-width", (link) => (isConnectedToSelected(link) ? 1.8 : 1.1));
        linkLabel.attr("opacity", (link) => (
          showEdgeLabels && (selectedNodeId === null || isConnectedToSelected(link)) ? 1 : 0
        ));
        d3.select(this).select("circle.node-halo").attr("opacity", d.id === selectedNodeId ? 0.18 : 0);
        d3.select(this).select("circle.node-circle")
          .attr("stroke", d.id === selectedNodeId ? "#0f172a" : "#ffffff")
          .attr("stroke-width", d.id === selectedNodeId ? 3 : 2.5);
      });

    const simulation = d3.forceSimulation<GraphNode>(simNodes)
      .force("link", d3.forceLink<GraphNode, GraphLink>(simLinks).id((d) => d.id).distance((d) => {
        const sourceDegree = typeof d.source === "object" ? d.source.degree : 1;
        const targetDegree = typeof d.target === "object" ? d.target.degree : 1;
        return Math.max(90, 150 - Math.min(sourceDegree + targetDegree, 10) * 4);
      }).strength(0.38))
      .force("charge", d3.forceManyBody<GraphNode>().strength((d) => -260 - Math.min(d.degree, 8) * 34))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide<GraphNode>().radius((d) => nodeRadius(d) + 34))
      .force("x", d3.forceX(width / 2).strength(0.035))
      .force("y", d3.forceY(height / 2).strength(0.035));

    simulationRef.current = simulation;

    simulation.on("tick", () => {
      const linkPath = (d: any) => {
        const sx = d.source.x;
        const sy = d.source.y;
        const tx = d.target.x;
        const ty = d.target.y;
        const dx = tx - sx;
        const dy = ty - sy;
        const distance = Math.max(1, Math.sqrt(dx * dx + dy * dy));
        const curve = Math.min(28, distance * 0.12) * ((d.id % 2 === 0) ? 1 : -1);
        const mx = (sx + tx) / 2 - (dy / distance) * curve;
        const my = (sy + ty) / 2 + (dx / distance) * curve;
        return `M${sx},${sy} Q${mx},${my} ${tx},${ty}`;
      };
      linkLine.attr("d", linkPath);
      linkGroup.selectAll<SVGPathElement, GraphLink>("path.hit-area").attr("d", linkPath);

      linkLabel
        .attr("x", (d: any) => (d.source.x + d.target.x) / 2)
        .attr("y", (d: any) => (d.source.y + d.target.y) / 2 - 6)
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
  }, [nodes, links, dimensions, showEdgeLabels, selectedNodeId, expandNode]);

  const graphIsLoading = initialLoading || (initialFetching && !rawData);

  if (graphIsLoading) {
    return (
      <div className="relative flex h-full flex-col items-center justify-center text-slate-400">
        <div className="absolute left-3 top-3 z-10">{toolbar}</div>
        <Loader2 className="mb-2 h-6 w-6 animate-spin text-slate-300" />
        <p className="text-sm">加载图谱...</p>
      </div>
    );
  }

  if (!rawData || (rawData.nodes ?? []).length === 0) {
    return (
      <div className="relative flex h-full flex-col items-center justify-center text-slate-400">
        <div className="absolute left-3 top-3 z-10">{toolbar}</div>
        <NetworkIcon className="mb-2 h-8 w-8 text-slate-300" />
        <p className="text-sm">暂无可展示的图谱数据</p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-0 lg:flex-row">
      {/* Graph panel */}
      <div className="relative min-h-0 min-w-0 flex-1">
        <div ref={containerRef} className="absolute inset-0">
          <svg ref={svgRef} className="h-full w-full" />
        </div>

        {/* Top-left: toolbar + stats + edge label toggle */}
        <div className="pointer-events-auto absolute left-3 top-3 z-10 flex max-w-[calc(100%-1.5rem)] flex-wrap items-center gap-2">
          {toolbar}
          <span className="rounded-full bg-white/90 px-2.5 py-1 text-[10px] font-medium text-slate-500 shadow-sm ring-1 ring-slate-200/60 dark:bg-slate-950/90 dark:text-slate-300 dark:ring-slate-700/80">
            {nodeCount}{totalNodeCount ? `/${totalNodeCount}` : ""} 节点 · {edgeCount}{totalEdgeCount ? `/${totalEdgeCount}` : ""} 边
          </span>
          <button
            onClick={resetGraph}
            disabled={initialFetching}
            className="flex items-center gap-1.5 rounded-full bg-white/90 px-2.5 py-1 text-[10px] font-medium text-slate-500 shadow-sm ring-1 ring-slate-200/60 transition-colors hover:bg-white disabled:cursor-not-allowed disabled:opacity-60 dark:bg-slate-950/90 dark:text-slate-300 dark:ring-slate-700/80 dark:hover:bg-slate-900"
            title="重新加载初始子图"
          >
            {initialFetching ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
            刷新
          </button>
          {expandingNodeId ? (
            <span className="flex items-center gap-1.5 rounded-full bg-white/90 px-2.5 py-1 text-[10px] font-medium text-slate-500 shadow-sm ring-1 ring-slate-200/60 dark:bg-slate-950/90 dark:text-slate-300 dark:ring-slate-700/80">
              <Loader2 className="h-3 w-3 animate-spin" />
              展开中
            </span>
          ) : null}
          <button
            onClick={() => setShowEdgeLabels((v) => !v)}
            aria-pressed={showEdgeLabels}
            title="切换关系标签显示"
            className="flex items-center gap-1.5 rounded-full bg-white/90 px-2.5 py-1 text-[10px] font-medium text-slate-500 shadow-sm ring-1 ring-slate-200/60 transition-colors hover:bg-white dark:bg-slate-950/90 dark:text-slate-300 dark:ring-slate-700/80 dark:hover:bg-slate-900"
          >
            <span className="inline-block h-3.5 w-7 rounded-full p-0.5 transition-colors" style={{ backgroundColor: showEdgeLabels ? "#2563eb" : "#cbd5e1" }}>
              <span className="block h-2.5 w-2.5 rounded-full bg-white shadow transition-transform" style={{ transform: showEdgeLabels ? "translateX(14px)" : "translateX(0)" }} />
            </span>
            关系标签
          </button>
        </div>

        {/* Bottom-left: Legend */}
        <div className="pointer-events-none absolute bottom-3 left-3 right-3 z-10">
          <div className="inline-flex max-w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-white/80 px-3 py-1.5 ring-1 ring-slate-200/40 dark:bg-slate-950/82 dark:ring-slate-700/70">
            {presentTypes.map(({ type, fill, label }) => (
              <div key={type} className="flex items-center gap-1">
                <span className="inline-block h-3 w-3 rounded-full" style={{ backgroundColor: fill }} />
                <span className="text-[10px] font-medium text-slate-500 dark:text-slate-300">{label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {selectedNodeId && (
        <div className="max-h-[45dvh] w-full shrink-0 overflow-y-auto border-t border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950 lg:max-h-none lg:w-[320px] lg:border-l lg:border-t-0">
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
