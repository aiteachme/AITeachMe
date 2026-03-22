import { useRef, useState, useCallback, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";
import {
  Loader2,
  AlertCircle,
  Network,
  X,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Tag,
  Link2,
  FileText,
  ChevronRight,
} from "lucide-react";
import {
  fetchFullGraph,
  fetchGraphNodeDetail,
} from "../../api/graphApi";
import { ExternalLink } from "lucide-react";
import { Card, CardContent } from "../ui/Card";
import { MarkdownViewer } from "../ui/MarkdownViewer";

/* ---------- 节点类型配色（Canvas 用 hex） ---------- */

const NODE_COLORS: Record<string, { bg: string; border: string; label: string }> = {
  Topic:      { bg: "#dbeafe", border: "#3b82f6", label: "主题" },
  topic:      { bg: "#dbeafe", border: "#3b82f6", label: "主题" },
  Concept:    { bg: "#f3e8ff", border: "#a855f7", label: "概念" },
  concept:    { bg: "#f3e8ff", border: "#a855f7", label: "概念" },
  Method:     { bg: "#fef3c7", border: "#f59e0b", label: "方法" },
  method:     { bg: "#fef3c7", border: "#f59e0b", label: "方法" },
  Definition: { bg: "#d1fae5", border: "#10b981", label: "定义" },
  definition: { bg: "#d1fae5", border: "#10b981", label: "定义" },
  Example:    { bg: "#fce7f3", border: "#ec4899", label: "示例" },
  example:    { bg: "#fce7f3", border: "#ec4899", label: "示例" },
  Theorem:    { bg: "#e0e7ff", border: "#6366f1", label: "定理" },
  theorem:    { bg: "#e0e7ff", border: "#6366f1", label: "定理" },
  Formula:    { bg: "#cffafe", border: "#06b6d4", label: "公式" },
  formula:    { bg: "#cffafe", border: "#06b6d4", label: "公式" },
};

const DEFAULT_COLOR = { bg: "#f1f5f9", border: "#64748b", label: "其他" };

/* ---------- 边类型颜色 ---------- */

const EDGE_COLORS: Record<string, string> = {
  prerequisite: "#ef4444",
  relates_to: "#6366f1",
  contains: "#10b981",
  derives_from: "#f59e0b",
  example_of: "#ec4899",
  part_of: "#3b82f6",
};

const DEFAULT_EDGE_COLOR = "#cbd5e1";

/* ---------- 图数据类型 ---------- */

interface GraphNode {
  id: number;
  canonical_name: string;
  node_type: string;
  confidence: number;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  // 运行时动画状态
  __hovered?: boolean;
  __selected?: boolean;
  __neighborOf?: boolean;
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

/* ---------- 详情侧边栏 ---------- */

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
  onEvidenceClick?: (evidenceId: number) => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["graph-node-detail", subject, nodeId],
    queryFn: () => fetchGraphNodeDetail(subject, nodeId),
    enabled: !!nodeId,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8 text-slate-400">
        <Loader2 className="w-4 h-4 animate-spin mr-2" />加载中...
      </div>
    );
  }
  if (!data) return null;

  const color = NODE_COLORS[data.node_type] ?? DEFAULT_COLOR;

  return (
    <div className="space-y-4 animate-in slide-in-from-right-4 duration-200">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-lg font-semibold text-slate-800"><MarkdownViewer content={data.canonical_name} /></h3>
            <span
              className="text-xs px-1.5 py-0.5 rounded"
              style={{ backgroundColor: color.bg, color: color.border }}
            >
              {color.label}
            </span>
          </div>
          <p className="text-xs text-slate-400">置信度 {Math.round(data.confidence * 100)}%</p>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {data.current_revision && (
        <div className="space-y-2">
          {data.current_revision.summary && (
            <div className="text-sm text-slate-600 bg-slate-50 rounded-lg p-3">
              <MarkdownViewer content={data.current_revision.summary} />
            </div>
          )}
          {data.current_revision.body && (
            <div className="text-sm border border-slate-100 rounded-lg p-3 max-h-48 overflow-y-auto">
              <MarkdownViewer content={data.current_revision.body} />
            </div>
          )}
        </div>
      )}

      {data.aliases.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500 mb-2">
            <Tag className="w-3 h-3" />别名
          </div>
          <div className="flex flex-wrap gap-1.5">
            {data.aliases.map((a) => (
              <span
                key={a.id}
                className={`text-xs px-2 py-0.5 rounded-full ${
                  a.is_primary ? "bg-slate-800 text-white" : "bg-slate-100 text-slate-600"
                }`}
              >
                {a.alias}
              </span>
            ))}
          </div>
        </div>
      )}

      {data.incident_edges.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500 mb-2">
            <Link2 className="w-3 h-3" />关联知识 ({data.incident_edges.length})
          </div>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {data.incident_edges.map((edge) => (
              <button
                key={edge.id}
                onClick={() => onNavigate(edge.other_node_id)}
                className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-left hover:bg-slate-50 transition-colors"
              >
                <span className="text-slate-400">
                  {edge.direction === "outgoing" ? "→" : "←"}
                </span>
                <span className="text-slate-700 truncate flex-1">{edge.other_node_name}</span>
                <span className="text-[10px] text-slate-400">{edge.edge_type}</span>
                <ChevronRight className="w-3 h-3 text-slate-300" />
              </button>
            ))}
          </div>
        </div>
      )}

      {data.evidence.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500 mb-2">
            <FileText className="w-3 h-3" />来源证据 ({data.evidence.length})
          </div>
          <div className="space-y-1.5 max-h-40 overflow-y-auto">
            {data.evidence.map((ev) => (
              <button
                key={ev.id}
                onClick={() => onEvidenceClick?.(ev.id)}
                className="w-full text-left text-xs text-slate-600 bg-slate-50 rounded p-2 border-l-2 border-slate-300 hover:border-amber-400 hover:bg-amber-50/50 transition-colors cursor-pointer group"
              >
                <p className="line-clamp-3">{ev.quote_text}</p>
                <div className="flex items-center justify-between mt-1">
                  <p className="text-[10px] text-slate-400">
                    {ev.evidence_role} · {Math.round(ev.confidence * 100)}%
                  </p>
                  <ExternalLink className="w-3 h-3 text-slate-300 group-hover:text-amber-500 transition-colors" />
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------- 主组件 ---------- */

export function ForceGraphView({ subject, toolbar, onEvidenceClick }: { subject: string; toolbar?: React.ReactNode; onEvidenceClick?: (evidenceId: number) => void }) {
  const fgRef = useRef<ForceGraphMethods | undefined>();
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<number | null>(null);
  const [filterType, setFilterType] = useState<string | undefined>(undefined);

  // 响应式尺寸 — 使用 border-box 尺寸确保 canvas 填满容器
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

  const { data: rawData, isLoading, isError } = useQuery({
    queryKey: ["full-graph", subject],
    queryFn: () => fetchFullGraph(subject),
    enabled: !!subject,
    retry: false,
  });

  // 构建邻接表用于高亮
  const neighborMap = useMemo(() => {
    const map = new Map<number, Set<number>>();
    if (!rawData) return map;
    for (const e of rawData.edges) {
      if (!map.has(e.source_node_id)) map.set(e.source_node_id, new Set());
      if (!map.has(e.target_node_id)) map.set(e.target_node_id, new Set());
      map.get(e.source_node_id)!.add(e.target_node_id);
      map.get(e.target_node_id)!.add(e.source_node_id);
    }
    return map;
  }, [rawData]);

  // 转换为 force-graph 数据格式
  const graphData: GraphData = useMemo(() => {
    if (!rawData) return { nodes: [], links: [] };

    const nodeIdSet = new Set<number>();
    let filteredNodes = rawData.nodes;
    if (filterType) {
      filteredNodes = rawData.nodes.filter(
        (n) => n.node_type.toLowerCase() === filterType.toLowerCase(),
      );
    }
    const nodes: GraphNode[] = filteredNodes.map((n) => {
      nodeIdSet.add(n.id);
      return {
        id: n.id,
        canonical_name: n.canonical_name,
        node_type: n.node_type,
        confidence: n.confidence,
      };
    });

    const links: GraphLink[] = rawData.edges
      .filter((e) => nodeIdSet.has(e.source_node_id) && nodeIdSet.has(e.target_node_id))
      .map((e) => ({
        source: e.source_node_id,
        target: e.target_node_id,
        edge_type: e.edge_type,
        confidence: e.confidence,
        weight: e.weight,
      }));

    return { nodes, links };
  }, [rawData, filterType]);

  // 节点绘制
  const paintNode = useCallback(
    (node: GraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const color = NODE_COLORS[node.node_type] ?? DEFAULT_COLOR;
      const isHovered = hoveredNodeId === node.id;
      const isSelected = selectedNodeId === node.id;
      const isNeighbor =
        hoveredNodeId !== null &&
        neighborMap.get(hoveredNodeId)?.has(node.id);
      const isDimmed =
        hoveredNodeId !== null && !isHovered && !isNeighbor;

      const baseRadius = 5 + node.confidence * 3;
      const radius = isHovered || isSelected ? baseRadius * 1.3 : baseRadius;
      const alpha = isDimmed ? 0.15 : 1;

      ctx.save();
      ctx.globalAlpha = alpha;

      // 发光效果
      if (isHovered || isSelected) {
        ctx.shadowColor = color.border;
        ctx.shadowBlur = 12;
      }

      // 填充
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, 2 * Math.PI);
      ctx.fillStyle = color.bg;
      ctx.fill();

      // 边框
      ctx.strokeStyle = color.border;
      ctx.lineWidth = isHovered || isSelected ? 2 : 1;
      ctx.stroke();

      ctx.shadowBlur = 0;

      // 标签（缩放足够大时显示）
      if (globalScale > 1.2 || isHovered || isSelected || isNeighbor) {
        const fontSize = Math.max(10 / globalScale, 2.5);
        ctx.font = `${isHovered || isSelected ? "bold " : ""}${fontSize}px sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillStyle = isDimmed ? "#94a3b8" : "#334155";
        ctx.fillText(node.canonical_name, x, y + radius + 2);
      }

      ctx.restore();
    },
    [hoveredNodeId, selectedNodeId, neighborMap],
  );

  // 边绘制
  const paintLink = useCallback(
    (link: GraphLink, ctx: CanvasRenderingContext2D, _globalScale: number) => {
      const source = link.source as GraphNode;
      const target = link.target as GraphNode;
      if (!source.x || !target.x) return;

      const isHighlighted =
        hoveredNodeId !== null &&
        ((source.id === hoveredNodeId) || (target.id === hoveredNodeId));
      const isDimmed = hoveredNodeId !== null && !isHighlighted;

      ctx.save();
      ctx.globalAlpha = isDimmed ? 0.06 : isHighlighted ? 0.9 : 0.3;
      ctx.strokeStyle = EDGE_COLORS[link.edge_type] ?? DEFAULT_EDGE_COLOR;
      ctx.lineWidth = isHighlighted ? 1.5 : 0.5;

      ctx.beginPath();
      ctx.moveTo(source.x, source.y ?? 0);
      ctx.lineTo(target.x, target.y ?? 0);
      ctx.stroke();

      // 箭头
      if (isHighlighted) {
        const dx = target.x - source.x;
        const dy = (target.y ?? 0) - (source.y ?? 0);
        const len = Math.sqrt(dx * dx + dy * dy);
        if (len > 0) {
          const ux = dx / len;
          const uy = dy / len;
          const targetRadius = 5 + (target.confidence ?? 0.5) * 3;
          const ax = target.x - ux * (targetRadius + 3);
          const ay = (target.y ?? 0) - uy * (targetRadius + 3);
          const arrowSize = 3;
          ctx.beginPath();
          ctx.moveTo(ax, ay);
          ctx.lineTo(ax - arrowSize * ux + arrowSize * 0.5 * uy, ay - arrowSize * uy - arrowSize * 0.5 * ux);
          ctx.lineTo(ax - arrowSize * ux - arrowSize * 0.5 * uy, ay - arrowSize * uy + arrowSize * 0.5 * ux);
          ctx.closePath();
          ctx.fillStyle = EDGE_COLORS[link.edge_type] ?? DEFAULT_EDGE_COLOR;
          ctx.fill();
        }
      }

      ctx.restore();
    },
    [hoveredNodeId],
  );

  const handleNodeClick = useCallback((node: GraphNode) => {
    setSelectedNodeId((prev) => (prev === node.id ? null : node.id));
    // 平滑居中
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

  // 初始化后自适应
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
  ];

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16 text-slate-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />加载知识图谱...
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-slate-400">
        <AlertCircle className="w-8 h-8 mb-2 text-slate-300" />
        <p className="text-sm">暂无知识图谱数据</p>
        <p className="text-xs mt-1">请先上传资料并触发知识图谱构建</p>
      </div>
    );
  }

  if (graphData.nodes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-slate-400">
        <Network className="w-8 h-8 mb-2 text-slate-300" />
        <p className="text-sm">暂无知识节点</p>
      </div>
    );
  }

  const graphWidth = dimensions.width;

  return (
    <div className="flex gap-4" style={{ height: 600 }}>
      <div className={`${selectedNodeId ? "w-3/5" : "w-full"} flex flex-col transition-all duration-300 min-w-0`}>
        {/* 工具栏：视图切换 + 类型筛选 */}
        <div className="flex items-center gap-3 mb-3 flex-wrap">
          {toolbar}
          <div className="flex flex-wrap gap-1.5 items-center">
            {NODE_TYPES.map((t) => (
              <button
                key={t.label}
                onClick={() => setFilterType(t.value)}
                className={`text-xs px-2.5 py-1 rounded-full transition-colors ${
                  filterType === t.value
                    ? "bg-slate-800 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {t.label}
              </button>
            ))}
            <span className="text-xs text-slate-400 ml-2">
              {graphData.nodes.length} 节点 · {graphData.links.length} 边
            </span>
          </div>
        </div>

        {/* 画布 */}
        <div
          ref={containerRef}
          className="flex-1 rounded-xl border border-slate-200 bg-white overflow-hidden relative"
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
              const r = 5 + (node.confidence ?? 0.5) * 3 + 2;
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

          {/* 图例 */}
          <div className="absolute bottom-3 left-3 bg-white/90 backdrop-blur-sm rounded-lg border border-slate-200 px-3 py-2 shadow-sm">
            <p className="text-[10px] text-slate-400 mb-1.5 font-medium">节点类型</p>
            <div className="flex flex-wrap gap-x-3 gap-y-1">
              {Object.entries(NODE_COLORS)
                .filter(([k]) => k[0] === k[0].toUpperCase())
                .map(([key, val]) => (
                  <div key={key} className="flex items-center gap-1">
                    <span
                      className="w-2.5 h-2.5 rounded-full border"
                      style={{ backgroundColor: val.bg, borderColor: val.border }}
                    />
                    <span className="text-[10px] text-slate-500">{val.label}</span>
                  </div>
                ))}
            </div>
          </div>

          {/* 缩放控制 */}
          <div className="absolute bottom-3 right-3 flex gap-1 bg-white/90 backdrop-blur-sm rounded-lg border border-slate-200 p-1 shadow-sm">
            <button onClick={handleZoomIn} className="p-1.5 rounded-md hover:bg-slate-100 text-slate-500" title="放大">
              <ZoomIn className="w-4 h-4" />
            </button>
            <button onClick={handleZoomOut} className="p-1.5 rounded-md hover:bg-slate-100 text-slate-500" title="缩小">
              <ZoomOut className="w-4 h-4" />
            </button>
            <button onClick={handleFit} className="p-1.5 rounded-md hover:bg-slate-100 text-slate-500" title="适应画布">
              <Maximize2 className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* 详情侧边栏 */}
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
