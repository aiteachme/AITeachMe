import { useRef, useState, useCallback, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";
import {
  Loader2,
  Network,
  X,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Tag,
  Link2,
  FileText,
  ChevronRight,
  ExternalLink,
} from "lucide-react";

import { graphNodeDetailApiV1SubjectsSubjectKnowledgeGraphNodesDetailPost } from "../../api/generated/knowledge";
import type { FullGraphResponse } from "../../api/generated/model";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { Card, CardContent } from "../ui/Card";
import { MarkdownViewer } from "../ui/MarkdownViewer";

const NODE_COLORS: Record<string, { fill: string; label: string }> = {
  Topic: { fill: "#3b82f6", label: "主题" },
  topic: { fill: "#3b82f6", label: "主题" },
  Concept: { fill: "#8b5cf6", label: "概念" },
  concept: { fill: "#8b5cf6", label: "概念" },
  Method: { fill: "#f59e0b", label: "方法" },
  method: { fill: "#f59e0b", label: "方法" },
  Definition: { fill: "#10b981", label: "定义" },
  definition: { fill: "#10b981", label: "定义" },
  Example: { fill: "#ec4899", label: "示例" },
  example: { fill: "#ec4899", label: "示例" },
  Theorem: { fill: "#6366f1", label: "定理" },
  theorem: { fill: "#6366f1", label: "定理" },
  Formula: { fill: "#06b6d4", label: "公式" },
  formula: { fill: "#06b6d4", label: "公式" },
};

const DEFAULT_COLOR = { fill: "#64748b", label: "其他" };

const EDGE_COLORS: Record<string, string> = {
  prerequisite: "#ef4444",
  relates_to: "#818cf8",
  contains: "#34d399",
  derives_from: "#fbbf24",
  example_of: "#f472b6",
  part_of: "#60a5fa",
};

const DEFAULT_EDGE_COLOR = "#94a3b8";

interface GraphNode {
  id: number;
  canonical_name: string;
  node_type: string;
  confidence: number;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

interface GraphLink {
  source: number | GraphNode;
  target: number | GraphNode;
  edge_type: string;
  confidence: number;
  weight: number;
}

interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

function NodeDetailSidebar({
  subject,
  nodeId,
  onClose,
  onNavigate,
  onEvidenceClick,
}: {
  subject: string;
  nodeId: number;
  onClose: () => void;
  onNavigate: (id: number) => void;
  onEvidenceClick?: (chunkId: number, quoteText: string) => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["graph-node-detail", subject, nodeId],
    queryFn: async () =>
      unwrapOrvalResponse(
        await graphNodeDetailApiV1SubjectsSubjectKnowledgeGraphNodesDetailPost(subject, {
          node_id: nodeId,
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

  const color = NODE_COLORS[data.node_type] ?? DEFAULT_COLOR;
  const colorStyle = { backgroundColor: `${color.fill}18`, color: color.fill };
  const aliases = data.aliases ?? [];
  const incidentEdges = data.incident_edges ?? [];
  const evidenceList = data.evidence ?? [];

  return (
    <div className="animate-in slide-in-from-right-4 space-y-4 duration-200">
      <div className="flex items-start justify-between">
        <div>
          <div className="mb-1 flex items-center gap-2">
            <h3 className="text-lg font-semibold text-slate-800">
              <MarkdownViewer content={data.canonical_name} />
            </h3>
            <span className="rounded px-1.5 py-0.5 text-xs" style={colorStyle}>
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
              <span
                key={a.id}
                className={`rounded-full px-2 py-0.5 text-xs ${
                  a.is_primary ? "bg-slate-800 text-white" : "bg-slate-100 text-slate-600"
                }`}
              >
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
            {incidentEdges.map(
              (edge: {
                id: number;
                other_node_id: number;
                direction: string;
                other_node_name: string;
                edge_type: string;
              }) => (
                <button
                  key={edge.id}
                  onClick={() => onNavigate(edge.other_node_id)}
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors hover:bg-slate-50"
                >
                  <span className="text-slate-400">{edge.direction === "outgoing" ? "→" : "←"}</span>
                  <span className="flex-1 truncate text-slate-700">{edge.other_node_name}</span>
                  <span className="text-[10px] text-slate-400">{edge.edge_type}</span>
                  <ChevronRight className="h-3 w-3 text-slate-300" />
                </button>
              ),
            )}
          </div>
        </div>
      )}

      {evidenceList.length > 0 && (
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-500">
            <FileText className="h-3 w-3" />来源证据 ({evidenceList.length})
          </div>
          <div className="max-h-40 space-y-1.5 overflow-y-auto">
            {evidenceList.map(
              (ev: {
                id: number;
                chunk_id: number;
                quote_text: string;
                evidence_role: string;
                confidence: number;
              }) => (
                <button
                  key={ev.id}
                  onClick={() => onEvidenceClick?.(ev.chunk_id, ev.quote_text)}
                  className="group w-full cursor-pointer rounded border-l-2 border-slate-300 bg-slate-50 p-2 text-left text-xs text-slate-600 transition-colors hover:border-amber-400 hover:bg-amber-50/50"
                >
                  <p className="line-clamp-3">{ev.quote_text}</p>
                  <div className="mt-1 flex items-center justify-between">
                    <p className="text-[10px] text-slate-400">
                      {ev.evidence_role} · {Math.round(ev.confidence * 100)}%
                    </p>
                    <ExternalLink className="h-3 w-3 text-slate-300 transition-colors group-hover:text-amber-500" />
                  </div>
                </button>
              ),
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function ForceGraphView({
  subject,
  toolbar,
  onEvidenceClick,
  fullGraphData,
}: {
  subject: string;
  toolbar?: React.ReactNode;
  onEvidenceClick?: (chunkId: number, quoteText: string) => void;
  fullGraphData: FullGraphResponse | null;
}) {
  const fgRef = useRef<ForceGraphMethods | undefined>();
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<number | null>(null);
  const [filterType, setFilterType] = useState<string | undefined>(undefined);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (w > 0 && h > 0) {
        setDimensions({ width: w, height: h });
      }
    };

    measure();
    const obs = new ResizeObserver(() => measure());
    obs.observe(el);
    return () => obs.disconnect();
  }, [selectedNodeId]);

  const rawData = fullGraphData;

  const neighborMap = useMemo(() => {
    const map = new Map<number, Set<number>>();
    if (!rawData) return map;

    for (const e of rawData.edges ?? []) {
      if (!map.has(e.source_node_id)) map.set(e.source_node_id, new Set());
      if (!map.has(e.target_node_id)) map.set(e.target_node_id, new Set());
      map.get(e.source_node_id)?.add(e.target_node_id);
      map.get(e.target_node_id)?.add(e.source_node_id);
    }

    return map;
  }, [rawData]);

  const graphData: GraphData = useMemo(() => {
    if (!rawData) return { nodes: [], links: [] };

    const nodeIdSet = new Set<number>();
    let filteredNodes = rawData.nodes ?? [];

    if (filterType) {
      filteredNodes = (rawData.nodes ?? []).filter(
        (n: GraphNode) => n.node_type.toLowerCase() === filterType.toLowerCase(),
      );
    }

    const nodes: GraphNode[] = filteredNodes.map((n: GraphNode) => {
      nodeIdSet.add(n.id);
      return {
        id: n.id,
        canonical_name: n.canonical_name,
        node_type: n.node_type,
        confidence: n.confidence,
      };
    });

    const links: GraphLink[] = (rawData.edges ?? [])
      .filter(
        (e: { source_node_id: number; target_node_id: number }) =>
          nodeIdSet.has(e.source_node_id) && nodeIdSet.has(e.target_node_id),
      )
      .map(
        (e: {
          source_node_id: number;
          target_node_id: number;
          edge_type: string;
          confidence: number;
          weight: number;
        }) => ({
          source: e.source_node_id,
          target: e.target_node_id,
          edge_type: e.edge_type,
          confidence: e.confidence,
          weight: e.weight,
        }),
      );

    return { nodes, links };
  }, [rawData, filterType]);

  const paintNode = useCallback(
    (node: GraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const color = NODE_COLORS[node.node_type] ?? DEFAULT_COLOR;
      const isHovered = hoveredNodeId === node.id;
      const isSelected = selectedNodeId === node.id;
      const isNeighbor = hoveredNodeId !== null && neighborMap.get(hoveredNodeId)?.has(node.id);
      const isDimmed = hoveredNodeId !== null && !isHovered && !isNeighbor;

      const baseRadius = 8 + node.confidence * 8;
      const radius = isHovered || isSelected ? baseRadius * 1.2 : baseRadius;
      const alpha = isDimmed ? 0.12 : 1;

      ctx.save();
      ctx.globalAlpha = alpha;

      // Outer glow for hovered/selected
      if (isHovered || isSelected) {
        ctx.shadowColor = color.fill;
        ctx.shadowBlur = 18;
      }

      // Solid filled circle
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, 2 * Math.PI);
      ctx.fillStyle = color.fill;
      ctx.fill();

      // White border
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = isHovered || isSelected ? 3 : 2;
      ctx.stroke();

      ctx.shadowBlur = 0;

      // Label
      const showLabel = globalScale > 0.8 || isHovered || isSelected || isNeighbor;
      if (showLabel) {
        const label = node.canonical_name;
        const fontSize = Math.max(11 / globalScale, 3);
        ctx.font = `${isHovered || isSelected ? "600 " : "500 "}${fontSize}px system-ui, -apple-system, sans-serif`;
        ctx.textAlign = "center";

        // Short labels go inside the node, long labels below
        const fitsInside = label.length <= 4 && globalScale > 1.5;
        if (fitsInside) {
          ctx.textBaseline = "middle";
          ctx.fillStyle = "#ffffff";
          ctx.fillText(label, x, y);
        } else {
          ctx.textBaseline = "top";
          // Text shadow for readability
          ctx.fillStyle = "#ffffff";
          ctx.fillText(label, x + 0.5, y + radius + 3.5);
          ctx.fillStyle = isDimmed ? "#94a3b8" : "#1e293b";
          ctx.fillText(label, x, y + radius + 3);
        }
      }

      ctx.restore();
    },
    [hoveredNodeId, selectedNodeId, neighborMap],
  );

  const paintLink = useCallback(
    (link: GraphLink, ctx: CanvasRenderingContext2D) => {
      const source = link.source as GraphNode;
      const target = link.target as GraphNode;
      if (source.x == null || source.y == null || target.x == null || target.y == null) return;

      const isHighlighted =
        hoveredNodeId !== null && (source.id === hoveredNodeId || target.id === hoveredNodeId);
      const isDimmed = hoveredNodeId !== null && !isHighlighted;

      const edgeColor = EDGE_COLORS[link.edge_type] ?? DEFAULT_EDGE_COLOR;

      ctx.save();
      ctx.globalAlpha = isDimmed ? 0.04 : isHighlighted ? 1 : 0.25;
      ctx.strokeStyle = edgeColor;
      ctx.lineWidth = isHighlighted ? 2 : 0.8;

      // Slight curve for visual appeal
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const len = Math.sqrt(dx * dx + dy * dy);
      const curvature = 0.15;
      const mx = (source.x + target.x) / 2 - dy * curvature;
      const my = (source.y + target.y) / 2 + dx * curvature;

      ctx.beginPath();
      ctx.moveTo(source.x, source.y);
      ctx.quadraticCurveTo(mx, my, target.x, target.y);
      ctx.stroke();

      // Arrow at target
      if (len > 0) {
        const ux = dx / len;
        const uy = dy / len;
        const targetRadius = 8 + (target.confidence ?? 0.5) * 8 + 3;
        const ax = target.x - ux * targetRadius;
        const ay = target.y - uy * targetRadius;
        const arrowSize = isHighlighted ? 5 : 3.5;
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(ax - arrowSize * ux + arrowSize * 0.5 * uy, ay - arrowSize * uy - arrowSize * 0.5 * ux);
        ctx.lineTo(ax - arrowSize * ux - arrowSize * 0.5 * uy, ay - arrowSize * uy + arrowSize * 0.5 * ux);
        ctx.closePath();
        ctx.fillStyle = edgeColor;
        ctx.fill();
      }

      // Edge type label on hover
      if (isHighlighted && len > 40) {
        const labelX = mx;
        const labelY = my;
        ctx.globalAlpha = 0.85;
        ctx.font = "500 9px system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(labelX - 20, labelY - 6, 40, 12);
        ctx.fillStyle = edgeColor;
        ctx.fillText(link.edge_type, labelX, labelY);
      }

      ctx.restore();
    },
    [hoveredNodeId],
  );

  const handleNodeClick = useCallback((node: GraphNode) => {
    setSelectedNodeId((prev) => (prev === node.id ? null : node.id));
    if (fgRef.current) {
      fgRef.current.centerAt(node.x, node.y, 400);
      fgRef.current.zoom(3, 400);
    }
  }, []);

  const handleNodeHover = useCallback((node: GraphNode | null) => {
    setHoveredNodeId(node?.id ?? null);
    if (containerRef.current) {
      containerRef.current.style.cursor = node ? "pointer" : "default";
    }
  }, []);

  const handleZoomIn = () => fgRef.current?.zoom(fgRef.current.zoom() * 1.5, 300);
  const handleZoomOut = () => fgRef.current?.zoom(fgRef.current.zoom() / 1.5, 300);
  const handleFit = () => fgRef.current?.zoomToFit(400, 40);

  useEffect(() => {
    if (graphData.nodes.length > 0) {
      const timer = setTimeout(() => fgRef.current?.zoomToFit(600, 60), 500);
      return () => clearTimeout(timer);
    }
  }, [graphData.nodes.length]);

  const NODE_TYPES = [
    { value: undefined, label: "全部" },
    { value: "Topic", label: "主题" },
    { value: "Concept", label: "概念" },
    { value: "Method", label: "方法" },
    { value: "Definition", label: "定义" },
    { value: "Example", label: "示例" },
    { value: "Theorem", label: "定理" },
    { value: "Formula", label: "公式" },
  ];

  if (graphData.nodes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-slate-400">
        <Network className="mb-2 h-8 w-8 text-slate-300" />
        <p className="text-sm">暂无可展示的图谱数据</p>
      </div>
    );
  }

  const graphWidth = dimensions.width;

  return (
    <div className="flex gap-4" style={{ height: 600 }}>
      <div
        className={`${selectedNodeId ? "w-3/5" : "w-full"} min-w-0 flex flex-col transition-all duration-300`}
      >
        <div className="mb-3 flex flex-wrap items-center gap-3">
          {toolbar}
          <div className="flex flex-wrap items-center gap-1.5">
            {NODE_TYPES.map((t) => (
              <button
                key={t.label}
                onClick={() => setFilterType(t.value)}
                className={`rounded-full px-2.5 py-1 text-xs transition-colors ${
                  filterType === t.value
                    ? "bg-slate-800 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {t.label}
              </button>
            ))}
            <span className="ml-2 text-xs text-slate-400">
              {graphData.nodes.length} 节点 · {graphData.links.length} 边
            </span>
          </div>
        </div>

        <div
          ref={containerRef}
          className="relative flex-1 overflow-hidden rounded-xl border border-slate-200 bg-white"
          style={{ minHeight: 500 }}
        >
          <ForceGraph2D
            ref={fgRef as any}
            graphData={graphData}
            width={graphWidth}
            height={dimensions.height || 500}
            nodeId="id"
            nodeCanvasObject={paintNode as any}
            nodePointerAreaPaint={(node: any, color: string, ctx: CanvasRenderingContext2D) => {
              const r = 8 + (node.confidence ?? 0.5) * 8 + 3;
              ctx.beginPath();
              ctx.arc(node.x ?? 0, node.y ?? 0, r, 0, 2 * Math.PI);
              ctx.fillStyle = color;
              ctx.fill();
            }}
            linkCanvasObject={paintLink as any}
            onNodeClick={handleNodeClick as any}
            onNodeHover={handleNodeHover as any}
            onBackgroundClick={() => setSelectedNodeId(null)}
            cooldownTicks={120}
            d3AlphaDecay={0.02}
            d3VelocityDecay={0.3}
            enableNodeDrag={true}
            enableZoomInteraction={true}
            enablePanInteraction={true}
          />

          <div className="absolute bottom-3 left-3 rounded-lg border border-slate-200 bg-white/95 px-3 py-2 shadow-sm backdrop-blur-sm">
            <p className="mb-1.5 text-[10px] font-medium text-slate-400">节点类型</p>
            <div className="flex flex-wrap gap-x-3 gap-y-1">
              {Object.entries(NODE_COLORS)
                .filter(([k]) => k[0] === k[0].toUpperCase())
                .map(([key, val]) => (
                  <div key={key} className="flex items-center gap-1.5">
                    <span
                      className="h-3 w-3 rounded-full border-2 border-white shadow-sm"
                      style={{ backgroundColor: val.fill }}
                    />
                    <span className="text-[10px] text-slate-600">{val.label}</span>
                  </div>
                ))}
            </div>
          </div>

          <div className="absolute bottom-3 left-[180px] flex gap-1 rounded-lg border border-slate-200 bg-white/95 p-1 shadow-sm backdrop-blur-sm">
            <button
              onClick={handleZoomIn}
              className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100"
              title="放大"
            >
              <ZoomIn className="h-4 w-4" />
            </button>
            <button
              onClick={handleZoomOut}
              className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100"
              title="缩小"
            >
              <ZoomOut className="h-4 w-4" />
            </button>
            <button
              onClick={handleFit}
              className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100"
              title="适配画布"
            >
              <Maximize2 className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      {selectedNodeId && (
        <div className="w-2/5">
          <Card>
            <CardContent className="pt-6">
              <NodeDetailSidebar
                subject={subject}
                nodeId={selectedNodeId}
                onClose={() => setSelectedNodeId(null)}
                onNavigate={(id) => {
                  setSelectedNodeId(id);
                  const node = graphData.nodes.find((n) => n.id === id);
                  if (node && fgRef.current) {
                    fgRef.current.centerAt(node.x, node.y, 400);
                    fgRef.current.zoom(3, 400);
                  }
                }}
                onEvidenceClick={onEvidenceClick}
              />
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
