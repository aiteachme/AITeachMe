import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import * as d3 from "d3";
import {
  Activity,
  Eye,
  Loader2,
  Maximize2,
  Network as NetworkIcon,
  RefreshCw,
  Target,
  X,
  Tag,
  Link2,
  FileText,
  ChevronRight,
  ExternalLink,
  ZoomIn,
  ZoomOut,
} from "lucide-react";

import {
  graphFocusSubgraphApiV1CoursesCourseIdKnowledgeGraphSubgraphPost,
  graphFullApiV1CoursesCourseIdKnowledgeGraphFullPost,
  graphKnowledgeUnitDetailApiV1CoursesCourseIdKnowledgeGraphKnowledgeUnitsDetailPost,
} from "../../api/generated/knowledge";
import type { FullGraphResponse, GraphEdgeResponse, KnowledgeSubgraphResponse, KnowledgeUnitResponse } from "../../api/generated/model";
import { useBuildEventStream } from "../../hooks/useBuildEventStream";
import { fetchKnowledgeBuildRuntime, type KnowledgeBuildLaneRuntime } from "../../lib/knowledgeBuildRuntime";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { MarkdownViewer } from "../ui/MarkdownViewer";

type NodeVisualRole = "assessment_core" | "support" | "context";

type NodeVisualStyle = {
  fill: string;
  dark: string;
  soft: string;
  label: string;
  role: NodeVisualRole;
  roleLabel: string;
};

const NODE_COLORS: Record<string, NodeVisualStyle> = {
  concept: { fill: "#2563eb", dark: "#1d4ed8", soft: "#dbeafe", label: "概念", role: "assessment_core", roleLabel: "考点主干" },
  definition: { fill: "#059669", dark: "#047857", soft: "#d1fae5", label: "定义", role: "assessment_core", roleLabel: "定义锚点" },
  theorem: { fill: "#7c3aed", dark: "#6d28d9", soft: "#ede9fe", label: "定理", role: "assessment_core", roleLabel: "考点主干" },
  formula: { fill: "#475569", dark: "#334155", soft: "#e2e8f0", label: "公式", role: "assessment_core", roleLabel: "考点主干" },
  example: { fill: "#a855f7", dark: "#9333ea", soft: "#f3e8ff", label: "示例", role: "support", roleLabel: "例题支撑" },
  exercise: { fill: "#ef4444", dark: "#dc2626", soft: "#fee2e2", label: "练习", role: "assessment_core", roleLabel: "训练锚点" },
  method: { fill: "#f97316", dark: "#ea580c", soft: "#ffedd5", label: "方法", role: "assessment_core", roleLabel: "考点主干" },
  proof_step: { fill: "#0f766e", dark: "#115e59", soft: "#ccfbf1", label: "证明步骤", role: "assessment_core", roleLabel: "推导锚点" },
  remark: { fill: "#64748b", dark: "#475569", soft: "#f1f5f9", label: "备注", role: "support", roleLabel: "易错提醒" },
};

const DEFAULT_COLOR: NodeVisualStyle = {
  fill: "#94a3b8",
  dark: "#64748b",
  soft: "#f1f5f9",
  label: "其他",
  role: "context",
  roleLabel: "补充信息",
};

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

function isLiveBuildLane(lane: KnowledgeBuildLaneRuntime | null | undefined): boolean {
  const status = String(lane?.status || "").toLowerCase();
  return status === "accepted" || status === "running";
}

function isAnyLiveBuildLane(runtime: {
  aggregate?: KnowledgeBuildLaneRuntime | null;
  docgen?: KnowledgeBuildLaneRuntime | null;
  graph?: KnowledgeBuildLaneRuntime | null;
} | null | undefined): boolean {
  return isLiveBuildLane(runtime?.aggregate) || isLiveBuildLane(runtime?.docgen) || isLiveBuildLane(runtime?.graph);
}

interface GraphNode extends d3.SimulationNodeDatum {
  id: number;
  canonical_name: string;
  knowledge_unit_type: string;
  confidence: number;
  degree: number;
  label_rank: number;
  component_id: number;
  component_size: number;
  component_rank: number;
}

interface GraphLink extends d3.SimulationLinkDatum<GraphNode> {
  id: number;
  edge_type: string;
  relation_label: string;
  label_width: number;
  source_node_id: number;
  target_node_id: number;
  pair_index: number;
  pair_total: number;
  curvature: number;
}

type DraggableGraphNode = GraphNode & {
  __dragStartX?: number;
  __dragStartY?: number;
  __hasDragged?: boolean;
};

type GraphNodePosition = {
  x: number;
  y: number;
  fx?: number | null;
  fy?: number | null;
};

type GraphDeltaState = {
  nodes: number;
  edges: number;
  at: number;
} | null;

function nodeStyle(unitType: string): NodeVisualStyle {
  return NODE_COLORS[unitType] ?? DEFAULT_COLOR;
}

function isAssessmentCoreNode(node: Pick<GraphNode, "knowledge_unit_type">): boolean {
  return nodeStyle(node.knowledge_unit_type).role === "assessment_core";
}

function graphNodePriority(node: Pick<GraphNode, "knowledge_unit_type" | "degree" | "confidence">): number {
  const roleScore = nodeStyle(node.knowledge_unit_type).role === "assessment_core"
    ? 1.45
    : nodeStyle(node.knowledge_unit_type).role === "support"
      ? 1.08
      : 0.9;
  const degreeScore = Math.min(0.42, Math.sqrt(Math.max(0, node.degree)) * 0.11);
  const confidenceScore = Math.max(0, Math.min(1, node.confidence || 0)) * 0.12;
  return roleScore + degreeScore + confidenceScore;
}

function graphNodeRadius(node: GraphNode): number {
  const style = nodeStyle(node.knowledge_unit_type);
  const roleBase = style.role === "assessment_core" ? 10.5 : style.role === "support" ? 8.2 : 7.4;
  const degreeBoost = Math.sqrt(Math.max(1, node.degree)) * (style.role === "assessment_core" ? 2.15 : 1.65);
  return Math.min(style.role === "assessment_core" ? 20 : 15.5, roleBase + degreeBoost);
}

function graphNodeLabelLimit(node: GraphNode, selectedNodeId: number | null): number {
  if (node.id === selectedNodeId) return 20;
  if (isAssessmentCoreNode(node)) return node.degree >= 3 ? 18 : 15;
  return node.degree >= 4 ? 14 : 10;
}

function estimateGraphLabelWidth(label: string, maxChars: number): number {
  const text = truncateGraphLabel(label, maxChars);
  let width = 0;
  for (const char of text) {
    width += /[\u4e00-\u9fff]/.test(char) ? 12 : 6.8;
  }
  return Math.min(170, Math.max(34, width + 18));
}

function estimateRelationLabelWidth(label: string): number {
  let width = 0;
  for (const char of label) {
    width += /[\u4e00-\u9fff]/.test(char) ? 10 : 6;
  }
  return Math.min(74, Math.max(30, width + 14));
}

function shouldShowSmartNodeLabel(
  node: GraphNode,
  selectedNodeId: number | null,
  selectedNeighbors: Set<number>,
  showAllNodeLabels: boolean,
): boolean {
  if (showAllNodeLabels) return true;
  if (node.id === selectedNodeId || selectedNeighbors.has(node.id)) return true;
  if (!isAssessmentCoreNode(node)) return false;
  if (node.label_rank <= 18) return true;
  return node.degree >= 4 && node.label_rank <= 28;
}

function applyGraphInteractiveStyles(
  svg: SVGSVGElement,
  links: GraphLink[],
  selectedNodeId: number | null,
  showEdgeLabels: boolean,
  highlightCoreUnits: boolean,
  showAllNodeLabels: boolean,
) {
  const selectedNeighbors = new Set<number>();
  if (selectedNodeId !== null) {
    for (const link of links) {
      if (link.source_node_id === selectedNodeId) selectedNeighbors.add(link.target_node_id);
      if (link.target_node_id === selectedNodeId) selectedNeighbors.add(link.source_node_id);
    }
  }
  const isConnectedToSelected = (link: GraphLink) =>
    selectedNodeId === null || link.source_node_id === selectedNodeId || link.target_node_id === selectedNodeId;

  const root = d3.select(svg);
  root.selectAll<SVGPathElement, GraphLink>("path.graph-link")
    .attr("stroke-width", (d) => (isConnectedToSelected(d) ? 1.65 : 1.15))
    .attr("stroke-opacity", (d) => (selectedNodeId === null ? 0.46 : isConnectedToSelected(d) ? 0.84 : 0.12));

  root.selectAll<SVGTextElement, GraphLink>("text.graph-link-label")
    .attr("opacity", (d) => (showEdgeLabels && (selectedNodeId === null || isConnectedToSelected(d)) ? 1 : 0));
  root.selectAll<SVGRectElement, GraphLink>("rect.graph-link-label-bg")
    .attr("opacity", (d) => (showEdgeLabels && (selectedNodeId === null || isConnectedToSelected(d)) ? 0.96 : 0));

  const nodeG = root.selectAll<SVGGElement, GraphNode>("g.graph-node");
  nodeG.select<SVGCircleElement>("circle.node-halo")
    .attr("opacity", (d) => (d.id === selectedNodeId ? 0.18 : 0));
  nodeG.select<SVGCircleElement>("circle.node-priority-ring")
    .attr("opacity", (d) => {
      if (d.id === selectedNodeId) return 0.84;
      if (isAssessmentCoreNode(d) && highlightCoreUnits && d.label_rank <= 10) return 0.14;
      return 0;
    });
  nodeG.select<SVGCircleElement>("circle.node-circle")
    .attr("stroke", (d) => (d.id === selectedNodeId ? "#0f172a" : "#ffffff"))
    .attr("stroke-width", (d) => (d.id === selectedNodeId ? 3.4 : isAssessmentCoreNode(d) ? 3 : 2.3))
    .attr("opacity", (d) => {
      if (selectedNodeId !== null) return d.id === selectedNodeId || selectedNeighbors.has(d.id) ? 1 : 0.34;
      if (highlightCoreUnits && !isAssessmentCoreNode(d)) return 0.68;
      return 1;
    });
  nodeG.select<SVGRectElement>("rect.node-label-bg")
    .attr("opacity", (d) => {
      if (!shouldShowSmartNodeLabel(d, selectedNodeId, selectedNeighbors, showAllNodeLabels)) return 0;
      if (d.id === selectedNodeId) return 0.96;
      if (selectedNodeId !== null && selectedNeighbors.has(d.id)) return 0.86;
      return 0.76;
    })
    .attr("width", (d) => estimateGraphLabelWidth(d.canonical_name, graphNodeLabelLimit(d, selectedNodeId)));
  nodeG.select<SVGTextElement>("text.node-role-label")
    .attr("opacity", (d) => {
      if (d.id === selectedNodeId) return 1;
      return 0;
    });
  nodeG.select<SVGTextElement>("text.node-label")
    .attr("font-size", (d) => (isAssessmentCoreNode(d) || d.id === selectedNodeId ? "12px" : "10.5px"))
    .attr("font-weight", (d) => (isAssessmentCoreNode(d) || d.id === selectedNodeId ? "700" : "520"))
    .attr("fill", (d) => (d.id === selectedNodeId ? "#0f172a" : "#334155"))
    .attr("opacity", (d) => {
      if (!shouldShowSmartNodeLabel(d, selectedNodeId, selectedNeighbors, showAllNodeLabels)) return 0;
      if (selectedNodeId !== null) return d.id === selectedNodeId || selectedNeighbors.has(d.id) ? 1 : 0.36;
      return 0.92;
    })
    .text((d) => truncateGraphLabel(d.canonical_name, graphNodeLabelLimit(d, selectedNodeId)));
}

type LoadedGraphData = {
  nodes: KnowledgeUnitResponse[];
  edges: GraphEdgeResponse[];
};

function graphDataSignature(data: LoadedGraphData): string {
  const nodes = [...data.nodes]
    .sort((a, b) => a.id - b.id)
    .map((node) => [
      node.id,
      node.knowledge_unit_type,
      node.canonical_name,
      node.status,
      node.confidence,
      node.updated_at,
    ].join(":"))
    .join("|");
  const edges = [...data.edges]
    .sort((a, b) => a.id - b.id)
    .map((edge) => [
      edge.id,
      edge.source_node_id,
      edge.target_node_id,
      edge.edge_type,
      edge.weight,
      edge.confidence,
    ].join(":"))
    .join("|");
  return `${data.nodes.length}:${data.edges.length}::${nodes}::${edges}`;
}

function compactGraphPayload(payload: FullGraphResponse | KnowledgeSubgraphResponse | null | undefined): LoadedGraphData {
  return {
    nodes: payload?.nodes ?? [],
    edges: payload?.edges ?? [],
  };
}

function mergeGraphData(current: LoadedGraphData | null, incoming: FullGraphResponse | KnowledgeSubgraphResponse | null | undefined): LoadedGraphData {
  const next = compactGraphPayload(incoming);
  const nodeById = new Map<number, KnowledgeUnitResponse>();
  const edgeByKey = new Map<string, GraphEdgeResponse>();

  for (const node of current?.nodes ?? []) {
    nodeById.set(node.id, node);
  }
  for (const node of next.nodes) {
    nodeById.set(node.id, node);
  }

  const appendEdge = (edge: GraphEdgeResponse) => {
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
  const isCoreNode = color.role === "assessment_core";
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

      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900/70">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-slate-500 dark:text-slate-400">
            <Target className="h-3.5 w-3.5" />
            教学角色
          </div>
          <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">{color.roleLabel}</p>
        </div>
        <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900/70">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-slate-500 dark:text-slate-400">
            <Eye className="h-3.5 w-3.5" />
            出题权重
          </div>
          <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">{isCoreNode ? "优先锚点" : "辅助材料"}</p>
        </div>
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
  const [highlightCoreUnits, setHighlightCoreUnits] = useState(true);
  const [showAllNodeLabels, setShowAllNodeLabels] = useState(false);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [graphData, setGraphData] = useState<LoadedGraphData | null>(null);
  const [expandedNodeIds, setExpandedNodeIds] = useState<Set<number>>(new Set());
  const [expandingNodeId, setExpandingNodeId] = useState<number | null>(null);
  const simulationRef = useRef<d3.Simulation<GraphNode, GraphLink> | null>(null);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const zoomTransformRef = useRef<d3.ZoomTransform | null>(null);
  const fitGraphToViewRef = useRef<((duration?: number) => void) | null>(null);
  const hasAutoFittedGraphRef = useRef(false);
  const nodePositionRef = useRef<Map<number, GraphNodePosition>>(new Map());
  const lastGraphSignatureRef = useRef<string | null>(null);
  const lastGraphCountsRef = useRef<{ nodes: number; edges: number } | null>(null);
  const selectedNodeIdRef = useRef<number | null>(null);
  const showEdgeLabelsRef = useRef(false);
  const highlightCoreUnitsRef = useRef(true);
  const showAllNodeLabelsRef = useRef(false);
  const expandedNodeIdsRef = useRef<Set<number>>(new Set());
  const [graphDelta, setGraphDelta] = useState<GraphDeltaState>(null);

  const {
    data: initialGraph,
    isLoading: initialLoading,
    isFetching: initialFetching,
    refetch: refetchInitialGraph,
  } = useQuery({
    queryKey: ["graph-full", course, totalNodeCount ?? 0, totalEdgeCount ?? 0],
    queryFn: async () =>
      unwrapOrvalResponse(
        await graphFullApiV1CoursesCourseIdKnowledgeGraphFullPost(course),
      ) ?? null,
    enabled: Boolean(course),
    retry: false,
  });

  const {
    data: buildRuntime,
    refetch: refetchBuildRuntime,
  } = useQuery({
    queryKey: ["knowledge-graph-build-runtime", course],
    queryFn: () => fetchKnowledgeBuildRuntime(course),
    enabled: Boolean(course),
    refetchInterval: (query) => (isAnyLiveBuildLane(query.state.data) ? 2500 : 10000),
    retry: false,
  });
  const buildStream = useBuildEventStream({
    courseId: course,
    enabled: Boolean(course) && isAnyLiveBuildLane(buildRuntime),
    onDone: () => {
      void refetchBuildRuntime();
      void refetchInitialGraph();
    },
  });
  const liveBuildRuntime = buildStream.snapshot ?? buildRuntime ?? null;
  const graphLane = liveBuildRuntime?.graph ?? null;
  const graphIsLive = isLiveBuildLane(graphLane);
  const latestGraphStreamDelta = buildStream.graphDeltas[0] ?? null;

  useEffect(() => {
    if (!initialGraph) return;
    const nextGraph = compactGraphPayload(initialGraph);
    const nextSignature = graphDataSignature(nextGraph);
    if (lastGraphSignatureRef.current === nextSignature) return;
    lastGraphSignatureRef.current = nextSignature;
    const previousCounts = lastGraphCountsRef.current;
    if (previousCounts && (nextGraph.nodes.length > previousCounts.nodes || nextGraph.edges.length > previousCounts.edges)) {
      setGraphDelta({
        nodes: Math.max(0, nextGraph.nodes.length - previousCounts.nodes),
        edges: Math.max(0, nextGraph.edges.length - previousCounts.edges),
        at: Date.now(),
      });
    }
    lastGraphCountsRef.current = {
      nodes: nextGraph.nodes.length,
      edges: nextGraph.edges.length,
    };
    setGraphData(nextGraph);
    setExpandedNodeIds(new Set());
    expandedNodeIdsRef.current = new Set();
    setSelectedNodeId(null);
  }, [initialGraph, course]);

  useEffect(() => {
    nodePositionRef.current.clear();
    zoomTransformRef.current = null;
    hasAutoFittedGraphRef.current = false;
    lastGraphSignatureRef.current = null;
    lastGraphCountsRef.current = null;
    setGraphDelta(null);
  }, [course]);

  useEffect(() => {
    if (!graphDelta) return;
    const timer = window.setTimeout(() => setGraphDelta(null), 4200);
    return () => window.clearTimeout(timer);
  }, [graphDelta]);

  useEffect(() => {
    if (!graphIsLive) return;
    void refetchInitialGraph();
    const timer = window.setInterval(() => {
      void refetchInitialGraph();
    }, 2600);
    return () => window.clearInterval(timer);
  }, [graphIsLive, refetchInitialGraph]);

  useEffect(() => {
    if (!latestGraphStreamDelta) return;
    void refetchInitialGraph();
    void refetchBuildRuntime();
  }, [latestGraphStreamDelta, refetchBuildRuntime, refetchInitialGraph]);

  useEffect(() => {
    selectedNodeIdRef.current = selectedNodeId;
  }, [selectedNodeId]);

  useEffect(() => {
    showEdgeLabelsRef.current = showEdgeLabels;
  }, [showEdgeLabels]);

  useEffect(() => {
    highlightCoreUnitsRef.current = highlightCoreUnits;
  }, [highlightCoreUnits]);

  useEffect(() => {
    showAllNodeLabelsRef.current = showAllNodeLabels;
  }, [showAllNodeLabels]);

  useEffect(() => {
    expandedNodeIdsRef.current = expandedNodeIds;
  }, [expandedNodeIds]);

  const expandNode = useCallback(
    async (nodeId: number) => {
      if (!course || expandedNodeIdsRef.current.has(nodeId)) return;
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
          if (current.has(nodeId)) return current;
          const next = new Set(current);
          next.add(nodeId);
          expandedNodeIdsRef.current = next;
          return next;
        });
      } catch {
        // Keep the currently loaded graph visible if expansion fails.
      } finally {
        setExpandingNodeId(null);
      }
    },
    [course],
  );

  const resetGraph = useCallback(() => {
    setGraphData(null);
    setExpandedNodeIds(new Set());
    setSelectedNodeId(null);
    nodePositionRef.current.clear();
    zoomTransformRef.current = null;
    hasAutoFittedGraphRef.current = false;
    lastGraphSignatureRef.current = null;
    lastGraphCountsRef.current = null;
    void refetchInitialGraph();
  }, [refetchInitialGraph]);

  const fitGraphToView = useCallback(() => {
    fitGraphToViewRef.current?.(260);
  }, []);

  const zoomGraphBy = useCallback((scaleFactor: number) => {
    const svg = svgRef.current;
    const zoom = zoomRef.current;
    if (!svg || !zoom) return;
    d3.select(svg)
      .transition()
      .duration(180)
      .call(zoom.scaleBy, scaleFactor);
  }, []);

  const rawData = graphData;

  // Parse graph data
  const { nodes, links, presentTypes, nodeCount, edgeCount, coreNodeCount, visibleSmartLabelCount } = useMemo(() => {
    if (!rawData) return { nodes: [] as GraphNode[], links: [] as GraphLink[], presentTypes: [] as { type: string; fill: string; label: string; role: NodeVisualRole }[], nodeCount: 0, edgeCount: 0, coreNodeCount: 0, visibleSmartLabelCount: 0 };

    const nodeIdSet = new Set((rawData.nodes ?? []).map((n: any) => n.id));
    const typeSet = new Set<string>();

    const validEdges = (rawData.edges ?? [])
      .filter((e: any) => nodeIdSet.has(e.source_node_id) && nodeIdSet.has(e.target_node_id));
    const pairTotals = new Map<string, number>();
    const pairIndexes = new Map<string, number>();
    const pairKeyOf = (e: any) => [e.source_node_id, e.target_node_id].sort((a, b) => Number(a) - Number(b)).join(":");
    for (const edge of validEdges) {
      const key = pairKeyOf(edge);
      pairTotals.set(key, (pairTotals.get(key) ?? 0) + 1);
    }

    const links: GraphLink[] = validEdges
      .map((e: any) => {
        const pairKey = pairKeyOf(e);
        const pairTotal = pairTotals.get(pairKey) ?? 1;
        const pairIndex = pairIndexes.get(pairKey) ?? 0;
        pairIndexes.set(pairKey, pairIndex + 1);
        const centeredIndex = pairIndex - (pairTotal - 1) / 2;
        const direction = Number(e.source_node_id) > Number(e.target_node_id) ? -1 : 1;
        return {
          id: e.id,
          source: e.source_node_id,
          target: e.target_node_id,
          edge_type: e.edge_type,
          relation_label: relationLabel(e.edge_type),
          label_width: estimateRelationLabelWidth(relationLabel(e.edge_type)),
          source_node_id: e.source_node_id,
          target_node_id: e.target_node_id,
          pair_index: pairIndex,
          pair_total: pairTotal,
          curvature: pairTotal > 1 ? centeredIndex * 0.28 * direction : 0,
        };
      });
    const degreeByNodeId = new Map<number, number>();
    for (const link of links) {
      degreeByNodeId.set(link.source_node_id, (degreeByNodeId.get(link.source_node_id) ?? 0) + 1);
      degreeByNodeId.set(link.target_node_id, (degreeByNodeId.get(link.target_node_id) ?? 0) + 1);
    }

    const componentParent = new Map<number, number>();
    for (const id of nodeIdSet) componentParent.set(Number(id), Number(id));
    const findComponentRoot = (id: number): number => {
      const parent = componentParent.get(id);
      if (parent == null || parent === id) return id;
      const root = findComponentRoot(parent);
      componentParent.set(id, root);
      return root;
    };
    const unionComponents = (a: number, b: number) => {
      const rootA = findComponentRoot(a);
      const rootB = findComponentRoot(b);
      if (rootA === rootB) return;
      componentParent.set(Math.max(rootA, rootB), Math.min(rootA, rootB));
    };
    for (const link of links) unionComponents(link.source_node_id, link.target_node_id);
    const componentSizeByRoot = new Map<number, number>();
    for (const id of nodeIdSet) {
      const root = findComponentRoot(Number(id));
      componentSizeByRoot.set(root, (componentSizeByRoot.get(root) ?? 0) + 1);
    }
    const componentRankByRoot = new Map<number, number>();
    Array.from(componentSizeByRoot.entries())
      .sort((a, b) => b[1] - a[1] || a[0] - b[0])
      .forEach(([root], index) => componentRankByRoot.set(root, index));

    const baseNodes: Omit<GraphNode, "label_rank">[] = (rawData.nodes ?? []).map((n: any) => {
      typeSet.add(n.knowledge_unit_type);
      const componentRoot = findComponentRoot(Number(n.id));
      return {
        id: n.id,
        canonical_name: n.canonical_name,
        knowledge_unit_type: n.knowledge_unit_type,
        confidence: n.confidence,
        degree: degreeByNodeId.get(n.id) ?? 0,
        component_id: componentRoot,
        component_size: componentSizeByRoot.get(componentRoot) ?? 1,
        component_rank: componentRankByRoot.get(componentRoot) ?? 0,
      };
    });
    const labelRankByNodeId = new Map<number, number>();
    [...baseNodes]
      .sort((a, b) => graphNodePriority(b) - graphNodePriority(a))
      .forEach((node, index) => labelRankByNodeId.set(node.id, index + 1));
    const nodes: GraphNode[] = baseNodes
      .map((node) => ({ ...node, label_rank: labelRankByNodeId.get(node.id) ?? 999 }))
      .sort((a, b) => graphNodePriority(a) - graphNodePriority(b));

    const types = Array.from(typeSet)
      .map((t) => ({ type: t, ...(NODE_COLORS[t] ?? DEFAULT_COLOR) }))
      .sort((a, b) => {
        if (a.role !== b.role) return a.role === "assessment_core" ? -1 : b.role === "assessment_core" ? 1 : 0;
        return a.label.localeCompare(b.label);
      });
    const coreNodeCount = nodes.filter((node) => isAssessmentCoreNode(node)).length;
    const emptyNeighbors = new Set<number>();
    const visibleSmartLabelCount = nodes.filter((node) => shouldShowSmartNodeLabel(node, null, emptyNeighbors, false)).length;

    return { nodes, links, presentTypes: types, nodeCount: nodes.length, edgeCount: links.length, coreNodeCount, visibleSmartLabelCount };
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

    const componentCount = new Set(nodes.map((node) => node.component_id)).size;
    const componentCenter = (node: GraphNode) => {
      if (componentCount <= 1 || node.component_rank === 0) return { x: width / 2, y: height / 2 };
      const rank = node.component_rank;
      const angle = (rank - 1) * 2.399963229728653;
      const spread = Math.min(width, height);
      const ring = Math.min(spread * 0.42, spread * (0.2 + 0.055 * Math.sqrt(rank)));
      const aspectX = width > height ? 1.32 : 1;
      const aspectY = height > width ? 1.2 : 0.82;
      return {
        x: width / 2 + Math.cos(angle) * ring * aspectX,
        y: height / 2 + Math.sin(angle) * ring * aspectY,
      };
    };

    const savedPositionCount = nodes.reduce((count, node) => (
      nodePositionRef.current.has(node.id) ? count + 1 : count
    ), 0);
    const newNodeCount = Math.max(0, nodes.length - savedPositionCount);

    // Deep copy nodes/links so D3 can mutate them. Preserve positions across live graph refreshes.
    const simNodes: GraphNode[] = nodes.map((node, index) => {
      const saved = nodePositionRef.current.get(node.id);
      if (saved) return { ...node, x: saved.x, y: saved.y, fx: saved.fx ?? undefined, fy: saved.fy ?? undefined };
      const center = componentCenter(node);
      const angle = index * 2.399963229728653;
      const radius = 18 + (index % 7) * 5;
      return {
        ...node,
        x: center.x + Math.cos(angle) * radius,
        y: center.y + Math.sin(angle) * radius,
      };
    });
    const simLinks: GraphLink[] = links.map((l) => ({ ...l, source: l.source_node_id, target: l.target_node_id }));

    // SVG structure
    const svgSel = d3.select(svg)
      .attr("width", width)
      .attr("height", height)
      .attr("viewBox", [0, 0, width, height].join(" "));

    const defs = svgSel.append("defs");

    const grid = defs.append("pattern")
      .attr("id", "knowledge-graph-grid")
      .attr("width", 36)
      .attr("height", 36)
      .attr("patternUnits", "userSpaceOnUse");
    grid.append("circle")
      .attr("cx", 1)
      .attr("cy", 1)
      .attr("r", 0.68)
      .attr("fill", "#94a3b8")
      .attr("opacity", 0.24);

    // Background: subtle workspace grid, borrowed from diagram tools without making the graph noisy.
    svgSel.append("rect")
      .attr("width", width)
      .attr("height", height)
      .attr("fill", "#fbfcff");
    svgSel.append("rect")
      .attr("width", width)
      .attr("height", height)
      .attr("fill", "url(#knowledge-graph-grid)");
    svgSel.append("rect")
      .attr("width", width)
      .attr("height", height)
      .attr("fill", "rgba(255,255,255,0.52)");

    // Container for zoom/pan
    const g = svgSel.append("g");

    // Zoom behavior
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.15, 5])
      .on("zoom", (event) => {
        zoomTransformRef.current = event.transform;
        g.attr("transform", event.transform);
      });
    svgSel.call(zoom);
    zoomRef.current = zoom;
    if (zoomTransformRef.current) {
      svgSel.call(zoom.transform, zoomTransformRef.current);
    }

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
      .attr("class", "graph-link")
      .attr("fill", "none")
      .attr("stroke", (d) => RELATION_COLORS[d.edge_type] ?? "#94a3b8")
      .attr("stroke-linecap", "round")
      .attr("stroke-width", 1.15)
      .attr("stroke-opacity", 0.46)
      .attr("marker-end", "url(#arrowhead)");

    linkGroup.selectAll<SVGPathElement, GraphLink>("path.hit-area")
      .data(simLinks)
      .join("path")
      .attr("class", "hit-area")
      .attr("fill", "none")
      .attr("stroke", "transparent")
      .attr("stroke-width", 12);

    const linkLabelBg = linkGroup.selectAll<SVGRectElement, GraphLink>("rect")
      .data(simLinks)
      .join("rect")
      .attr("class", "graph-link-label-bg")
      .attr("rx", 4)
      .attr("ry", 4)
      .attr("fill", "rgba(255,255,255,0.94)")
      .attr("stroke", "rgba(226,232,240,0.95)")
      .attr("stroke-width", 0.8)
      .attr("width", (d) => d.label_width)
      .attr("height", 17)
      .attr("pointer-events", "none")
      .attr("opacity", 0);

    // Link labels (clean white background effect using stroke)
    const linkLabel = linkGroup.selectAll<SVGTextElement, GraphLink>("text")
      .data(simLinks)
      .join("text")
      .attr("class", "graph-link-label")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .attr("font-size", "10px")
      .attr("fill", "#64748b")
      .attr("stroke", "rgba(248,250,252,0.96)")
      .attr("stroke-width", 5)
      .attr("paint-order", "stroke")
      .attr("font-family", "system-ui, sans-serif")
      .attr("pointer-events", "none")
      .attr("opacity", 0)
      .text((d) => d.relation_label);

    // Node group
    const nodeGroup = g.append("g").attr("class", "nodes");

    // Node containers
    const nodeG = nodeGroup.selectAll<SVGGElement, GraphNode>("g")
      .data(simNodes)
      .join("g")
      .attr("class", "graph-node")
      .attr("cursor", "pointer")
      .call(
        d3.drag<SVGGElement, GraphNode>()
          .on("start", (event, d) => {
            const dragNode = d as DraggableGraphNode;
            dragNode.__dragStartX = event.x;
            dragNode.__dragStartY = event.y;
            dragNode.__hasDragged = false;
            d.fx = d.x ?? event.x;
            d.fy = d.y ?? event.y;
          })
          .on("drag", (event, d) => {
            const dragNode = d as DraggableGraphNode;
            const dx = event.x - (dragNode.__dragStartX ?? event.x);
            const dy = event.y - (dragNode.__dragStartY ?? event.y);
            if (!dragNode.__hasDragged && Math.sqrt(dx * dx + dy * dy) >= 3) {
              dragNode.__hasDragged = true;
              simulation.alphaTarget(0.07).restart();
            }
            d.fx = event.x;
            d.fy = event.y;
          })
          .on("end", (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            const dragNode = d as DraggableGraphNode;
            if (dragNode.__hasDragged) {
              d.fx = d.x ?? event.x;
              d.fy = d.y ?? event.y;
            } else {
              d.fx = null;
              d.fy = null;
            }
            const x = Number(d.x ?? event.x);
            const y = Number(d.y ?? event.y);
            if (Number.isFinite(x) && Number.isFinite(y)) {
              nodePositionRef.current.set(d.id, { x, y, fx: d.fx ?? null, fy: d.fy ?? null });
            }
            dragNode.__dragStartX = undefined;
            dragNode.__dragStartY = undefined;
          })
      );

    // Node click handler
    nodeG.on("click", (event, d) => {
      event.stopPropagation();
      setSelectedNodeId((prev) => (prev === d.id ? null : d.id));
    });

    nodeG.append("circle")
      .attr("class", "node-halo")
      .attr("r", (d) => graphNodeRadius(d) + 6)
      .attr("fill", (d) => nodeStyle(d.knowledge_unit_type).fill)
      .attr("opacity", 0);

    nodeG.append("circle")
      .attr("class", "node-priority-ring")
      .attr("r", (d) => graphNodeRadius(d) + (isAssessmentCoreNode(d) ? 5 : 3))
      .attr("fill", "none")
      .attr("stroke", (d) => nodeStyle(d.knowledge_unit_type).fill)
      .attr("stroke-width", (d) => (isAssessmentCoreNode(d) ? 2 : 1.2))
      .attr("stroke-dasharray", (d) => (isAssessmentCoreNode(d) ? "0" : "3 4"))
      .attr("opacity", 0);

    nodeG.append("circle")
      .attr("class", "node-circle")
      .attr("r", (d) => graphNodeRadius(d))
      .attr("fill", (d) => nodeStyle(d.knowledge_unit_type).fill)
      .attr("stroke", "#ffffff")
      .attr("stroke-width", 2.5)
      .attr("opacity", 1);

    nodeG.append("rect")
      .attr("class", "node-label-bg")
      .attr("x", (d) => graphNodeRadius(d) + 3)
      .attr("y", -12)
      .attr("width", (d) => estimateGraphLabelWidth(d.canonical_name, graphNodeLabelLimit(d, selectedNodeIdRef.current)))
      .attr("height", 22)
      .attr("rx", 6)
      .attr("fill", "rgba(255,255,255,0.93)")
      .attr("stroke", "rgba(226,232,240,0.95)")
      .attr("stroke-width", 1)
      .attr("opacity", 0)
      .style("pointer-events", "none");

    nodeG.append("text")
      .attr("class", "node-label")
      .attr("dx", (d) => graphNodeRadius(d) + 6)
      .attr("dy", 4.2)
      .attr("font-size", (d) => (isAssessmentCoreNode(d) ? "12px" : "10.5px"))
      .attr("font-family", "system-ui, sans-serif")
      .attr("font-weight", (d) => (isAssessmentCoreNode(d) ? "700" : "520"))
      .attr("fill", "#334155")
      .attr("stroke", "rgba(248,250,252,0.9)")
      .attr("stroke-width", 3)
      .attr("paint-order", "stroke")
      .attr("opacity", 1)
      .style("pointer-events", "none")
      .text((d) => truncateGraphLabel(d.canonical_name, graphNodeLabelLimit(d, selectedNodeIdRef.current)));

    nodeG.append("text")
      .attr("class", "node-role-label")
      .attr("dx", (d) => graphNodeRadius(d) + 9)
      .attr("dy", -13)
      .attr("font-size", "9px")
      .attr("font-family", "system-ui, sans-serif")
      .attr("font-weight", "700")
      .attr("fill", (d) => nodeStyle(d.knowledge_unit_type).dark)
      .attr("stroke", "rgba(248,250,252,0.92)")
      .attr("stroke-width", 3)
      .attr("paint-order", "stroke")
      .style("pointer-events", "none")
      .attr("opacity", 0)
      .text((d) => nodeStyle(d.knowledge_unit_type).roleLabel);

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
        nodeG.select<SVGRectElement>("rect.node-label-bg")
          .attr("opacity", (node) => (connectedIds.has(node.id) ? 0.92 : 0));
        nodeG.select<SVGTextElement>("text.node-label")
          .attr("opacity", (node) => (connectedIds.has(node.id) ? 1 : 0));
        linkLine
          .attr("stroke-opacity", (link) => (
            link.source_node_id === d.id || link.target_node_id === d.id ? 0.86 : 0.08
          ))
          .attr("stroke-width", (link) => (
            link.source_node_id === d.id || link.target_node_id === d.id ? 2.3 : 1
          ));
        linkLabel.attr("opacity", (link) => (
          showEdgeLabelsRef.current && (link.source_node_id === d.id || link.target_node_id === d.id) ? 1 : 0
        ));
        linkLabelBg.attr("opacity", (link) => (
          showEdgeLabelsRef.current && (link.source_node_id === d.id || link.target_node_id === d.id) ? 0.96 : 0
        ));
        d3.select(this).select("circle.node-halo").attr("opacity", 0.2);
        d3.select(this).select("circle.node-priority-ring").attr("opacity", 0.92);
        d3.select(this).select("rect.node-label-bg").attr("opacity", 0.96);
        d3.select(this).select("text.node-role-label").attr("opacity", 1);
        d3.select(this).select("circle.node-circle").attr("stroke", "#0f172a").attr("stroke-width", 3);
      })
      .on("mouseleave", function () {
        applyGraphInteractiveStyles(
          svg,
          simLinks,
          selectedNodeIdRef.current,
          showEdgeLabelsRef.current,
          highlightCoreUnitsRef.current,
          showAllNodeLabelsRef.current,
        );
      });

    const simulation = d3.forceSimulation<GraphNode>(simNodes)
      .force("link", d3.forceLink<GraphNode, GraphLink>(simLinks).id((d) => d.id).distance((d) => {
        const sourceDegree = typeof d.source === "object" ? d.source.degree : 1;
        const targetDegree = typeof d.target === "object" ? d.target.degree : 1;
        const sourceIsCore = typeof d.source === "object" ? isAssessmentCoreNode(d.source) : false;
        const targetIsCore = typeof d.target === "object" ? isAssessmentCoreNode(d.target) : false;
        const base = sourceIsCore && targetIsCore ? 138 : sourceIsCore || targetIsCore ? 118 : 150;
        return Math.max(104, base + Math.max(0, d.pair_total - 1) * 34 - Math.min(sourceDegree + targetDegree, 10) * 2);
      }).strength((d) => {
        const sourceIsCore = typeof d.source === "object" ? isAssessmentCoreNode(d.source) : false;
        const targetIsCore = typeof d.target === "object" ? isAssessmentCoreNode(d.target) : false;
        return sourceIsCore || targetIsCore ? 0.46 : 0.32;
      }))
      .force("charge", d3.forceManyBody<GraphNode>().strength((d) => (
        isAssessmentCoreNode(d) ? -360 - Math.min(d.degree, 9) * 42 : -210 - Math.min(d.degree, 7) * 28
      )))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide<GraphNode>().radius((d) => graphNodeRadius(d) + (isAssessmentCoreNode(d) ? 46 : 30)))
      .force("radial", d3.forceRadial<GraphNode>(
        (d) => {
          if (d.component_size <= 2) return Math.min(width, height) * 0.08;
          return isAssessmentCoreNode(d) ? Math.min(width, height) * 0.16 : Math.min(width, height) * 0.28;
        },
        width / 2,
        height / 2,
      ).strength((d) => (d.component_size <= 2 ? 0.01 : isAssessmentCoreNode(d) ? 0.035 : 0.016)))
      .force("componentX", d3.forceX<GraphNode>((d) => componentCenter(d).x).strength((d) => (d.component_size <= 2 ? 0.12 : 0.045)))
      .force("componentY", d3.forceY<GraphNode>((d) => componentCenter(d).y).strength((d) => (d.component_size <= 2 ? 0.12 : 0.045)))
      .force("x", d3.forceX(width / 2).strength(0.006))
      .force("y", d3.forceY(height / 2).strength(0.006))
      .alphaDecay(0.05)
      .velocityDecay(0.5);
    simulation.alpha(savedPositionCount > 0 ? (newNodeCount > 0 ? 0.34 : 0.16) : 1);

    simulationRef.current = simulation;
    applyGraphInteractiveStyles(
      svg,
      simLinks,
      selectedNodeIdRef.current,
      showEdgeLabelsRef.current,
      highlightCoreUnitsRef.current,
      showAllNodeLabelsRef.current,
    );

    const linkPath = (d: any) => {
      const sx = d.source.x;
      const sy = d.source.y;
      const tx = d.target.x;
      const ty = d.target.y;
      if (!d.curvature) return `M${sx},${sy} L${tx},${ty}`;
      const dx = tx - sx;
      const dy = ty - sy;
      const distance = Math.max(1, Math.sqrt(dx * dx + dy * dy));
      const curve = Math.min(70, Math.max(24, distance * 0.22)) * d.curvature;
      const mx = (sx + tx) / 2 - (dy / distance) * curve;
      const my = (sy + ty) / 2 + (dx / distance) * curve;
      return `M${sx},${sy} Q${mx},${my} ${tx},${ty}`;
    };
    const linkMidpoint = (d: any) => {
      const sx = d.source.x;
      const sy = d.source.y;
      const tx = d.target.x;
      const ty = d.target.y;
      if (!d.curvature) return { x: (sx + tx) / 2, y: (sy + ty) / 2 };
      const dx = tx - sx;
      const dy = ty - sy;
      const distance = Math.max(1, Math.sqrt(dx * dx + dy * dy));
      const curve = Math.min(70, Math.max(24, distance * 0.22)) * d.curvature;
      const cx = (sx + tx) / 2 - (dy / distance) * curve;
      const cy = (sy + ty) / 2 + (dx / distance) * curve;
      return {
        x: 0.25 * sx + 0.5 * cx + 0.25 * tx,
        y: 0.25 * sy + 0.5 * cy + 0.25 * ty,
      };
    };
    let tickFrame: number | null = null;
    const renderTick = () => {
      tickFrame = null;
      linkLine.attr("d", linkPath);
      linkGroup.selectAll<SVGPathElement, GraphLink>("path.hit-area").attr("d", linkPath);

      linkLabel
        .attr("x", (d: any) => linkMidpoint(d).x)
        .attr("y", (d: any) => linkMidpoint(d).y - 6)
        .attr("transform", ""); // Explicitly avoid rotation for legibility
      linkLabelBg
        .attr("x", (d: any) => linkMidpoint(d).x - d.label_width / 2)
        .attr("y", (d: any) => linkMidpoint(d).y - 15);

      nodeG.attr("transform", (d: any) => `translate(${d.x},${d.y})`);
      for (const node of simNodes) {
        const x = Number(node.x);
        const y = Number(node.y);
        if (Number.isFinite(x) && Number.isFinite(y)) {
          nodePositionRef.current.set(node.id, {
            x,
            y,
            fx: node.fx ?? null,
            fy: node.fy ?? null,
          });
        }
      }
    };
    simulation.on("tick", () => {
      if (tickFrame !== null) return;
      tickFrame = window.requestAnimationFrame(renderTick);
    });

    const fitCurrentGraphToView = (duration = 600) => {
      const xExtent = d3.extent(simNodes, (d) => d.x) as [number, number];
      const yExtent = d3.extent(simNodes, (d) => d.y) as [number, number];
      if (xExtent[0] == null) return;
      const pad = 96;
      const gw = xExtent[1] - xExtent[0] + pad * 2;
      const gh = yExtent[1] - yExtent[0] + pad * 2;
      const scale = Math.min(width / gw, height / gh, 1.5);
      const tx = width / 2 - ((xExtent[0] + xExtent[1]) / 2) * scale;
      const ty = height / 2 - ((yExtent[0] + yExtent[1]) / 2) * scale;
      hasAutoFittedGraphRef.current = true;
      svgSel.transition().duration(duration)
        .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
    };
    fitGraphToViewRef.current = fitCurrentGraphToView;

    // Fit to view only for the first layout. Live refreshes preserve the user's viewport.
    let hasAutoFitted = false;
    simulation.on("end", () => {
      if (hasAutoFitted || hasAutoFittedGraphRef.current) return;
      hasAutoFitted = true;
      hasAutoFittedGraphRef.current = true;
      fitCurrentGraphToView(600);
    });

    return () => {
      if (tickFrame !== null) window.cancelAnimationFrame(tickFrame);
      simulation.stop();
      if (fitGraphToViewRef.current === fitCurrentGraphToView) fitGraphToViewRef.current = null;
    };
  }, [nodes, links, dimensions]);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || nodes.length === 0) return;
    applyGraphInteractiveStyles(svg, links, selectedNodeId, showEdgeLabels, highlightCoreUnits, showAllNodeLabels);
  }, [links, nodes.length, selectedNodeId, showEdgeLabels, highlightCoreUnits, showAllNodeLabels]);

  const graphIsLoading = initialLoading || (initialFetching && !rawData);
  const graphIsComplete = Boolean(rawData) && (!totalNodeCount || nodeCount >= totalNodeCount);
  const selectedNodeExpanded = selectedNodeId !== null && (graphIsComplete || expandedNodeIds.has(selectedNodeId));
  const graphProgressPct = typeof graphLane?.progress_pct === "number"
    ? Math.max(0, Math.min(100, Math.round(graphLane.progress_pct)))
    : null;
  const latestStreamUnitDelta = Number(
    latestGraphStreamDelta?.created_unit_count ?? latestGraphStreamDelta?.unit_count ?? 0,
  );
  const latestStreamEdgeDelta = Number(
    latestGraphStreamDelta?.created_edge_count ?? latestGraphStreamDelta?.edge_count ?? 0,
  );
  const graphLiveMessage = graphIsLive
    ? `图谱实时更新中${graphProgressPct !== null ? ` · ${graphProgressPct}%` : ""}`
    : graphDelta
      ? `已更新 +${graphDelta.nodes} 节点 +${graphDelta.edges} 边`
      : latestGraphStreamDelta && (latestStreamUnitDelta > 0 || latestStreamEdgeDelta > 0)
        ? `已写入 +${Math.max(0, latestStreamUnitDelta)} 节点 +${Math.max(0, latestStreamEdgeDelta)} 边`
        : initialFetching && rawData
          ? "正在同步最新图谱"
          : "";
  const showGraphLiveBadge = Boolean(graphLiveMessage);

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
    <div className="relative h-full min-h-0 overflow-hidden">
      {/* Graph panel */}
      <div className="absolute inset-0 min-h-0 min-w-0">
        <div ref={containerRef} className="absolute inset-0">
          <svg ref={svgRef} className="h-full w-full" />
        </div>

        {/* Top-left: toolbar + stats + edge label toggle */}
        <div className="pointer-events-auto absolute left-3 top-3 z-10 flex max-w-[calc(100%-1.5rem)] flex-wrap items-center gap-2 pr-24 lg:pr-40">
          {toolbar}
          <span className="inline-flex h-8 items-center rounded-lg bg-white/95 px-2.5 text-[11px] font-medium text-slate-500 shadow-sm ring-1 ring-slate-200/70 dark:bg-slate-950/90 dark:text-slate-300 dark:ring-slate-700/80">
            {nodeCount}{totalNodeCount ? `/${totalNodeCount}` : ""} 节点 · {edgeCount}{totalEdgeCount ? `/${totalEdgeCount}` : ""} 边
          </span>
          <span className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-white/95 px-2.5 text-[11px] font-semibold text-slate-700 shadow-sm ring-1 ring-slate-200/70 dark:bg-slate-950/90 dark:text-slate-200 dark:ring-slate-700/80">
            <Target className="h-3.5 w-3.5 text-blue-600" />
            {coreNodeCount} 个考点锚点
          </span>
          <button
            onClick={resetGraph}
            disabled={initialFetching}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-white/95 px-2.5 text-[11px] font-medium text-slate-500 shadow-sm ring-1 ring-slate-200/70 transition-colors hover:bg-white disabled:cursor-not-allowed disabled:opacity-60 dark:bg-slate-950/90 dark:text-slate-300 dark:ring-slate-700/80 dark:hover:bg-slate-900"
            title="重新加载初始子图"
          >
            {initialFetching ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
            刷新
          </button>
          {expandingNodeId ? (
            <span className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-white/95 px-2.5 text-[11px] font-medium text-slate-500 shadow-sm ring-1 ring-slate-200/70 dark:bg-slate-950/90 dark:text-slate-300 dark:ring-slate-700/80">
              <Loader2 className="h-3 w-3 animate-spin" />
              展开中
            </span>
          ) : null}
          {selectedNodeId && !graphIsComplete ? (
            <button
              onClick={() => void expandNode(selectedNodeId)}
              disabled={selectedNodeExpanded || expandingNodeId === selectedNodeId}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-white/95 px-2.5 text-[11px] font-medium text-slate-500 shadow-sm ring-1 ring-slate-200/70 transition-colors hover:bg-white disabled:cursor-not-allowed disabled:opacity-60 dark:bg-slate-950/90 dark:text-slate-300 dark:ring-slate-700/80 dark:hover:bg-slate-900"
              title={selectedNodeExpanded ? "当前节点已展开" : "展开当前节点的一跳邻居"}
            >
              {expandingNodeId === selectedNodeId ? <Loader2 className="h-3 w-3 animate-spin" /> : <NetworkIcon className="h-3 w-3" />}
              {selectedNodeExpanded ? "已展开" : "展开邻居"}
            </button>
          ) : null}
          <button
            onClick={() => setHighlightCoreUnits((v) => !v)}
            aria-pressed={highlightCoreUnits}
            title="切换考点主干高亮"
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-white/95 px-2.5 text-[11px] font-medium text-slate-500 shadow-sm ring-1 ring-slate-200/70 transition-colors hover:bg-white dark:bg-slate-950/90 dark:text-slate-300 dark:ring-slate-700/80 dark:hover:bg-slate-900"
          >
            <Target className={`h-3.5 w-3.5 ${highlightCoreUnits ? "text-blue-600" : "text-slate-400"}`} />
            考点高亮
          </button>
          <button
            onClick={() => setShowAllNodeLabels((v) => !v)}
            aria-pressed={showAllNodeLabels}
            title={showAllNodeLabels ? "切回智能标签，只保留关键考点标签" : `显示全部节点标签。当前智能显示 ${visibleSmartLabelCount} 个标签`}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-white/95 px-2.5 text-[11px] font-medium text-slate-500 shadow-sm ring-1 ring-slate-200/70 transition-colors hover:bg-white dark:bg-slate-950/90 dark:text-slate-300 dark:ring-slate-700/80 dark:hover:bg-slate-900"
          >
            <Eye className={`h-3.5 w-3.5 ${showAllNodeLabels ? "text-blue-600" : "text-slate-400"}`} />
            {showAllNodeLabels ? "全部标签" : "智能标签"}
          </button>
          <button
            onClick={() => setShowEdgeLabels((v) => !v)}
            aria-pressed={showEdgeLabels}
            title="切换关系标签显示"
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-white/95 px-2.5 text-[11px] font-medium text-slate-500 shadow-sm ring-1 ring-slate-200/70 transition-colors hover:bg-white dark:bg-slate-950/90 dark:text-slate-300 dark:ring-slate-700/80 dark:hover:bg-slate-900"
          >
            <span className="inline-block h-3.5 w-7 rounded-full p-0.5 transition-colors" style={{ backgroundColor: showEdgeLabels ? "#2563eb" : "#cbd5e1" }}>
              <span className="block h-2.5 w-2.5 rounded-full bg-white shadow transition-transform" style={{ transform: showEdgeLabels ? "translateX(14px)" : "translateX(0)" }} />
            </span>
            关系标签
          </button>
        </div>

        <div className={`pointer-events-auto absolute right-3 top-3 z-10 flex items-center gap-1 rounded-lg bg-white/95 p-1 shadow-sm ring-1 ring-slate-200/70 transition-[right] duration-200 dark:bg-slate-950/90 dark:ring-slate-700/80 ${selectedNodeId ? "lg:right-[360px]" : ""}`}>
          <button
            type="button"
            onClick={fitGraphToView}
            className="flex h-8 w-8 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100"
            title="适配视图"
            aria-label="适配视图"
          >
            <Maximize2 className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => zoomGraphBy(1.22)}
            className="flex h-8 w-8 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100"
            title="放大"
            aria-label="放大"
          >
            <ZoomIn className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => zoomGraphBy(0.82)}
            className="flex h-8 w-8 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100"
            title="缩小"
            aria-label="缩小"
          >
            <ZoomOut className="h-4 w-4" />
          </button>
        </div>

        {showGraphLiveBadge ? (
          <div className="pointer-events-none absolute bottom-16 left-1/2 z-20 -translate-x-1/2">
            <div className="inline-flex items-center gap-2 rounded-full border border-emerald-200/70 bg-white/95 px-4 py-2 text-xs font-semibold text-slate-700 shadow-[0_16px_44px_rgba(15,23,42,0.16)] ring-1 ring-white/80 backdrop-blur dark:border-emerald-500/30 dark:bg-slate-950/90 dark:text-slate-100">
              <span className="relative flex h-2.5 w-2.5">
                {graphIsLive ? <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-70" /> : null}
                <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${graphIsLive ? "bg-emerald-500" : "bg-blue-500"}`} />
              </span>
              <Activity className={`h-3.5 w-3.5 ${graphIsLive ? "text-emerald-600" : "text-blue-600"}`} />
              <span>{graphLiveMessage}</span>
              {buildStream.connected && graphIsLive ? (
                <span className="rounded-full bg-emerald-50 px-1.5 py-0.5 text-[10px] font-bold text-emerald-700 ring-1 ring-emerald-100 dark:bg-emerald-950/40 dark:text-emerald-300 dark:ring-emerald-800/60">
                  LIVE
                </span>
              ) : null}
            </div>
          </div>
        ) : null}

        {/* Bottom-left: Legend */}
        <div className="pointer-events-none absolute bottom-3 left-3 right-3 z-10">
          <div className="inline-flex max-w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-white/90 px-3 py-2 shadow-sm ring-1 ring-slate-200/60 dark:bg-slate-950/90 dark:ring-slate-700/70">
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
        <div className="absolute inset-x-3 bottom-3 z-20 max-h-[45dvh] overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-2xl shadow-slate-900/12 dark:border-slate-800 dark:bg-slate-950 lg:inset-x-auto lg:bottom-3 lg:right-3 lg:top-3 lg:w-[340px] lg:max-h-none">
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
