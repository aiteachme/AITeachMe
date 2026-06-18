import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as d3 from "d3";
import katex from "katex";
import {
  Activity,
  Loader2,
  Maximize2,
  Network as NetworkIcon,
  RefreshCw,
  Search,
  SlidersHorizontal,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";

import {
  graphFocusSubgraphApiV1CoursesCourseIdKnowledgeGraphSubgraphPost,
  graphFullApiV1CoursesCourseIdKnowledgeGraphFullPost,
} from "../../api/generated/knowledge";
import type { FullGraphResponse, GraphEdgeResponse, KnowledgeSubgraphResponse, KnowledgeUnitResponse } from "../../api/generated/model";
import { useBuildEventStream } from "../../hooks/useBuildEventStream";
import { fetchKnowledgeBuildRuntime, type KnowledgeBuildLaneRuntime } from "../../lib/knowledgeBuildRuntime";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { KnowledgeGraphNodeDetailPanel, type KnowledgeGraphSourceRefNavigationTarget } from "./KnowledgeGraphNodeDetailPanel";
import {
  EDGE_TYPE_PRIORITY,
  GRAPH_LAYERS,
  RELATION_COLORS,
  clampGraphLayer,
  deterministicEdgeBend,
  edgePriority,
  estimateGraphLabelWidth,
  estimateRelationLabelWidth,
  getLearningEdgeDirection,
  graphNodeLabelLimit,
  graphNodePriority,
  isSuppressedGraphNodeType,
  isAssessmentCoreNode,
  isBackboneEdge,
  nodeBaseLayer,
  nodeStyle,
  normalizeGraphTextLabel,
  relationLabel,
  relationTone,
  shouldShowSmartEdgeLabel,
  shouldShowSmartNodeLabel,
  truncateGraphLabel,
  type GraphLink,
  type GraphNode,
  type RelationFilterItem,
} from "./knowledgeGraphVisual";

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

function readableSvgTextSize(basePx: number, zoomScale: number): string {
  const scale = Math.max(0.34, Math.min(5, Number.isFinite(zoomScale) ? zoomScale : 1));
  const compensated = basePx / Math.pow(scale, scale >= 1 ? 0.46 : 0.34);
  return `${Math.min(30, Math.max(6.6, compensated))}px`;
}

function readableSvgStrokeWidth(basePx: number, zoomScale: number): number {
  const scale = Math.max(0.34, Math.min(5, Number.isFinite(zoomScale) ? zoomScale : 1));
  return Math.min(7, Math.max(0.9, basePx / Math.pow(scale, 0.86)));
}

function graphNodeLabelLimitForZoom(node: GraphNode, selectedNodeId: number | null, zoomScale: number): number {
  const base = graphNodeLabelLimit(node, selectedNodeId);
  const scale = Number.isFinite(zoomScale) ? zoomScale : 1;
  if (scale >= 2.2) return Math.max(base, 34);
  if (scale >= 1.55) return Math.max(base, 28);
  if (scale >= 1.28) return Math.max(base, 24);
  return base;
}

function escapeGraphHtml(value: string): string {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function stripInlineMathDelimiters(value: string): string {
  const text = String(value || "").trim();
  return text
    .replace(/^\\\(([\s\S]*)\\\)$/g, "$1")
    .replace(/^\\\[([\s\S]*)\\\]$/g, "$1")
    .replace(/^\$\$([\s\S]*)\$\$$/g, "$1")
    .replace(/^\$([^$]*)\$$/g, "$1")
    .trim();
}

function isFormulaLikeGraphLabel(node: GraphNode): boolean {
  const label = String(node.canonical_name || "");
  if (node.knowledge_unit_type === "formula_model") return true;
  return /\\(?:frac|sqrt|sum|int|left|right|cdot|times|leq|geq)|[$^_=<>≤≥+\-*/]/.test(label) && label.length <= 90;
}

function graphFormulaLabelHtml(node: GraphNode): string {
  const rawLabel = String(node.canonical_name || "").trim();
  const formula = stripInlineMathDelimiters(rawLabel);
  if (!formula) return escapeGraphHtml(normalizeGraphTextLabel(rawLabel));
  try {
    return katex.renderToString(formula, {
      displayMode: false,
      output: "html",
      strict: false,
      throwOnError: false,
      trust: false,
    });
  } catch {
    return escapeGraphHtml(normalizeGraphTextLabel(rawLabel));
  }
}

function graphFormulaLabelWidth(node: GraphNode): number {
  const units = Math.max(4, normalizeGraphTextLabel(node.canonical_name).length || String(node.canonical_name || "").length);
  return Math.min(230, Math.max(76, units * 9 + 34));
}

function applyGraphInteractiveStyles(
  svg: SVGSVGElement,
  links: GraphLink[],
  selectedNodeId: number | null,
  showEdgeLabels: boolean,
  showAllEdges: boolean,
  highlightCoreUnits: boolean,
  showAllNodeLabels: boolean,
  graphZoomScale = 1,
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
  const isVisibleLink = (link: GraphLink) =>
    showAllEdges || link.is_backbone || (selectedNodeId !== null && isConnectedToSelected(link));

  const root = d3.select(svg);
  const visibleNodeCount = root.selectAll<SVGGElement, GraphNode>("g.graph-node").data().length;
  const visibleEdgeCount = links.length;
  root.selectAll<SVGPathElement, GraphLink>("path.graph-link")
    .classed("is-selected-link", (d) => selectedNodeId !== null && isConnectedToSelected(d))
    .attr("display", (d) => (isVisibleLink(d) ? null : "none"))
    .attr("stroke-width", (d) => (isConnectedToSelected(d) ? (d.is_backbone ? 1.65 : 1.08) : 0.8))
    .attr("stroke-opacity", (d) => (
      selectedNodeId === null ? (d.is_backbone ? 0.46 : 0.22) : isConnectedToSelected(d) ? 0.8 : 0.04
    ));
  root.selectAll<SVGPathElement, GraphLink>("path.hit-area")
    .attr("display", (d) => (isVisibleLink(d) ? null : "none"));

  root.selectAll<SVGTextElement, GraphLink>("text.graph-link-label")
    .attr("display", (d) => (isVisibleLink(d) ? null : "none"))
    .attr("font-size", readableSvgTextSize(10, graphZoomScale))
    .attr("stroke-width", readableSvgStrokeWidth(5, graphZoomScale))
    .attr("opacity", (d) => (shouldShowSmartEdgeLabel(d, selectedNodeId, showEdgeLabels, graphZoomScale, visibleEdgeCount) ? 1 : 0));
  root.selectAll<SVGRectElement, GraphLink>("rect.graph-link-label-bg")
    .attr("display", (d) => (isVisibleLink(d) ? null : "none"))
    .attr("opacity", (d) => (shouldShowSmartEdgeLabel(d, selectedNodeId, showEdgeLabels, graphZoomScale, visibleEdgeCount) ? 0.92 : 0));

  const nodeG = root.selectAll<SVGGElement, GraphNode>("g.graph-node");
  nodeG
    .classed("is-selected-node", (d) => d.id === selectedNodeId)
    .classed("is-selected-neighbor", (d) => selectedNeighbors.has(d.id))
    .classed("is-muted-node", (d) => selectedNodeId !== null && d.id !== selectedNodeId && !selectedNeighbors.has(d.id));
  nodeG.select<SVGCircleElement>("circle.node-halo")
    .attr("opacity", (d) => (d.id === selectedNodeId ? 0.18 : 0));
  nodeG.select<SVGCircleElement>("circle.node-priority-ring")
    .attr("opacity", (d) => {
      if (d.id === selectedNodeId) return 0.72;
      if (isAssessmentCoreNode(d) && highlightCoreUnits && d.label_rank <= 10) return 0.12;
      return 0;
    });
  nodeG.select<SVGCircleElement>("circle.node-circle")
    .attr("stroke", (d) => (d.id === selectedNodeId ? "#1d4ed8" : "#ffffff"))
    .attr("stroke-width", (d) => (d.id === selectedNodeId ? 3 : isAssessmentCoreNode(d) ? 2.35 : 2))
    .attr("opacity", (d) => {
      if (selectedNodeId !== null) return d.id === selectedNodeId || selectedNeighbors.has(d.id) ? 1 : 0.34;
      if (highlightCoreUnits && !isAssessmentCoreNode(d)) return 0.92;
      return 1;
    });
  nodeG.select<SVGTextElement>("text.node-label")
    .attr("font-size", (d) => readableSvgTextSize(isAssessmentCoreNode(d) || d.id === selectedNodeId ? 12.5 : 11.5, graphZoomScale))
    .attr("font-weight", (d) => (isAssessmentCoreNode(d) || d.id === selectedNodeId ? "700" : "600"))
    .attr("fill", (d) => (d.id === selectedNodeId ? "#0f172a" : nodeStyle(d.knowledge_unit_type).dark))
    .attr("stroke-width", readableSvgStrokeWidth(3.2, graphZoomScale))
    .attr("opacity", (d) => {
      if (!shouldShowSmartNodeLabel(d, selectedNodeId, selectedNeighbors, showAllNodeLabels, graphZoomScale, visibleNodeCount)) return 0;
      if (selectedNodeId !== null) return d.id === selectedNodeId || selectedNeighbors.has(d.id) ? 1 : 0.3;
      return 0.96;
    })
    .text((d) => (
      isFormulaLikeGraphLabel(d)
        ? ""
        : truncateGraphLabel(d.canonical_name, graphNodeLabelLimitForZoom(d, selectedNodeId, graphZoomScale))
    ));
  nodeG.select<SVGForeignObjectElement>("foreignObject.node-formula-label")
    .attr("width", (d) => graphFormulaLabelWidth(d))
    .attr("height", (d) => (d.id === selectedNodeId ? 34 : 30))
    .attr("opacity", (d) => {
      if (!shouldShowSmartNodeLabel(d, selectedNodeId, selectedNeighbors, showAllNodeLabels, graphZoomScale, visibleNodeCount)) return 0;
      if (selectedNodeId !== null) return d.id === selectedNodeId || selectedNeighbors.has(d.id) ? 1 : 0.3;
      return 0.98;
    })
    .style("font-size", (d) => readableSvgTextSize(isAssessmentCoreNode(d) || d.id === selectedNodeId ? 12.5 : 11.5, graphZoomScale))
    .style("color", (d) => (d.id === selectedNodeId ? "#0f172a" : nodeStyle(d.knowledge_unit_type).dark));
}

type LoadedGraphData = {
  nodes: KnowledgeUnitResponse[];
  edges: GraphEdgeResponse[];
};

const DETAIL_NODE_TYPES = new Set(["misconception", "application_case"]);
const BACKBONE_RELATION_TYPES = new Set(["prerequisite_for", "part_of", "derives_to", "applies_to", "uses_method", "assesses"]);
const TYPE_CLUSTER_LAYOUT: Record<string, { xBias: number; yRatio: number; maxColumns: number }> = {
  topic: { xBias: -0.42, yRatio: 0.38, maxColumns: 3 },
  concept: { xBias: -0.24, yRatio: 0.48, maxColumns: 4 },
  formula_model: { xBias: -0.12, yRatio: 0.54, maxColumns: 4 },
  principle: { xBias: -0.02, yRatio: 0.34, maxColumns: 4 },
  procedure: { xBias: 0.18, yRatio: 0.64, maxColumns: 5 },
  skill: { xBias: 0.3, yRatio: 0.72, maxColumns: 4 },
  misconception: { xBias: 0.36, yRatio: 0.42, maxColumns: 4 },
  application_case: { xBias: 0.42, yRatio: 0.56, maxColumns: 4 },
};
const GRAPH_LAYOUT_VERSION = 15;
const NODE_HIT_RADIUS = 24;
const INITIAL_FOCUSED_GRAPH_THRESHOLD = 180;
const INITIAL_FOCUSED_GRAPH_EDGE_THRESHOLD = 520;
const INITIAL_FOCUSED_GRAPH_LIMIT = 140;

function isDetailGraphNode(node: Pick<GraphNode, "knowledge_unit_type">): boolean {
  return DETAIL_NODE_TYPES.has(node.knowledge_unit_type);
}

function selectBackboneEdgeIds(links: GraphLink[], visibleNodeCount: number, showDetailNodes: boolean): Set<number> {
  const selected = new Set<number>();
  const nodeUseCount = new Map<number, number>();
  const maxEdges = Math.max(
    14,
    Math.min(showDetailNodes ? 18 : 16, Math.round(visibleNodeCount * (showDetailNodes ? 0.34 : 0.36))),
  );
  const add = (link: GraphLink, relaxed = false) => {
    if (selected.has(link.id) || selected.size >= maxEdges) return;
    const sourceUse = nodeUseCount.get(link.source_node_id) ?? 0;
    const targetUse = nodeUseCount.get(link.target_node_id) ?? 0;
    if (!relaxed && (sourceUse >= 1 || targetUse >= 1)) return;
    if (relaxed && (sourceUse >= 3 || targetUse >= 3)) return;
    selected.add(link.id);
    nodeUseCount.set(link.source_node_id, sourceUse + 1);
    nodeUseCount.set(link.target_node_id, targetUse + 1);
  };

  const learningLinks = [...links]
    .filter((link) => BACKBONE_RELATION_TYPES.has(link.edge_type))
    .sort((left, right) => edgePriority(right) - edgePriority(left) || left.id - right.id);

  for (const link of learningLinks.filter((item) => item.edge_type === "prerequisite_for")) add(link, true);
  for (const link of learningLinks.filter((item) => item.edge_type !== "prerequisite_for")) add(link);
  for (const link of learningLinks) add(link, true);

  return selected;
}

function graphDataSignature(data: LoadedGraphData): string {
  const nodes = [...data.nodes]
    .sort((a, b) => a.id - b.id)
    .map((node) => [
      node.id,
      node.knowledge_unit_type,
      node.canonical_name,
      node.status,
      node.confidence,
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

function buildStructuredNodePositions(nodes: GraphNode[], width: number, height: number): Map<number, { x: number; y: number }> {
  const positions = new Map<number, { x: number; y: number }>();
  if (!nodes.length) return positions;

  const typeOrder = new Map(Object.keys(TYPE_CLUSTER_LAYOUT).map((type, index) => [type, index]));
  const centerX = width / 2;
  const centerY = height / 2;
  const baseRadius = Math.max(120, Math.min(width, height) * 0.28);
  const sorted = [...nodes].sort((left, right) =>
    left.component_rank - right.component_rank ||
    (typeOrder.get(left.knowledge_unit_type) ?? 99) - (typeOrder.get(right.knowledge_unit_type) ?? 99) ||
    graphNodePriority(right) - graphNodePriority(left) ||
    left.id - right.id,
  );
  sorted.forEach((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(1, sorted.length);
    const typeBias = ((typeOrder.get(node.knowledge_unit_type) ?? 0) % 5) * 0.34;
    const componentBias = Math.min(5, node.component_rank) * 0.18;
    const radius = baseRadius * (0.55 + (index % 5) * 0.14 + componentBias);
    positions.set(node.id, {
      x: centerX + Math.cos(angle + typeBias) * radius,
      y: centerY + Math.sin(angle + typeBias) * radius * 0.72,
    });
  });

  return positions;
}

type GraphSettingsSidebarProps = {
  presentRelationTypes: RelationFilterItem[];
  showDetailNodes: boolean;
  showAllEdges: boolean;
  showAllNodeLabels: boolean;
  showEdgeLabels: boolean;
  highlightCoreUnits: boolean;
  hiddenRelationTypes: Set<string>;
  initialFetching: boolean;
  onToggleDetailNodes: () => void;
  onToggleAllEdges: () => void;
  onToggleAllNodeLabels: () => void;
  onToggleEdgeLabels: () => void;
  onToggleCoreUnits: () => void;
  onToggleRelationType: (type: string) => void;
  onClearRelationFilters: () => void;
  onResetGraph: () => void;
  onFitGraph: () => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
};

function GraphSettingsSidebar({
  presentRelationTypes,
  showDetailNodes,
  showAllEdges,
  showAllNodeLabels,
  showEdgeLabels,
  highlightCoreUnits,
  hiddenRelationTypes,
  initialFetching,
  onToggleDetailNodes,
  onToggleAllEdges,
  onToggleAllNodeLabels,
  onToggleEdgeLabels,
  onToggleCoreUnits,
  onToggleRelationType,
  onClearRelationFilters,
  onResetGraph,
  onFitGraph,
  onZoomIn,
  onZoomOut,
}: GraphSettingsSidebarProps) {
  const segmentClass = (active: boolean) =>
    `flex min-h-10 flex-1 items-center justify-center rounded-md px-3 py-2 text-xs font-semibold transition-colors ${
      active
        ? "bg-slate-950 text-white shadow-sm dark:bg-slate-100 dark:text-slate-950"
        : "text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
    }`;
  const switchClass = (active: boolean) =>
    `relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${
      active ? "bg-blue-600" : "bg-slate-300 dark:bg-slate-700"
    }`;

  return (
    <aside className="flex h-full w-full flex-col bg-white text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <div className="border-b border-slate-200 px-4 py-4 dark:border-slate-800">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-semibold">图谱</p>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <section className="border-b border-slate-200 px-4 py-4 dark:border-slate-800">
          <p className="mb-2 text-xs font-semibold text-slate-700 dark:text-slate-200">节点</p>
          <div className="flex rounded-lg bg-slate-100 p-1 dark:bg-slate-900">
            <button
              type="button"
              aria-pressed={showDetailNodes}
              onClick={() => {
                if (!showDetailNodes) onToggleDetailNodes();
              }}
              className={segmentClass(showDetailNodes)}
            >
              <span>完整</span>
            </button>
            <button
              type="button"
              aria-pressed={!showDetailNodes}
              onClick={() => {
                if (showDetailNodes) onToggleDetailNodes();
              }}
              className={segmentClass(!showDetailNodes)}
            >
              <span>精简</span>
            </button>
          </div>
        </section>

        <section className="border-b border-slate-200 px-4 py-4 dark:border-slate-800">
          <p className="mb-2 text-xs font-semibold text-slate-700 dark:text-slate-200">关系</p>
          <div className="flex rounded-lg bg-slate-100 p-1 dark:bg-slate-900">
            <button
              type="button"
              aria-pressed={!showAllEdges}
              onClick={() => {
                if (showAllEdges) onToggleAllEdges();
              }}
              className={segmentClass(!showAllEdges)}
            >
              <span>主干</span>
            </button>
            <button
              type="button"
              aria-pressed={showAllEdges}
              onClick={() => {
                if (!showAllEdges) onToggleAllEdges();
              }}
              className={segmentClass(showAllEdges)}
            >
              <span>全部</span>
            </button>
          </div>
        </section>

        <section className="border-b border-slate-200 px-4 py-4 dark:border-slate-800">
          <p className="mb-3 text-xs font-semibold text-slate-700 dark:text-slate-200">显示</p>
          <div className="space-y-3">
            {[
              { label: "全部节点标签", active: showAllNodeLabels, onClick: onToggleAllNodeLabels },
              { label: "关系名称", active: showEdgeLabels, onClick: onToggleEdgeLabels },
              { label: "考点高亮", active: highlightCoreUnits, onClick: onToggleCoreUnits },
            ].map((item) => (
              <button
                key={item.label}
                type="button"
                aria-pressed={item.active}
                onClick={item.onClick}
                className="flex min-h-10 w-full items-center justify-between rounded-md px-2 text-left text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-900"
              >
                <span>{item.label}</span>
                <span className={switchClass(item.active)}>
                  <span
                    className="h-4 w-4 rounded-full bg-white shadow transition-transform"
                    style={{ transform: item.active ? "translateX(18px)" : "translateX(2px)" }}
                  />
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="px-4 py-4">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-xs font-semibold text-slate-700 dark:text-slate-200">筛选</p>
            {hiddenRelationTypes.size ? (
              <button
                type="button"
                onClick={onClearRelationFilters}
                className="text-[11px] font-medium text-blue-600 hover:text-blue-700 dark:text-blue-300"
              >
                重置
              </button>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {presentRelationTypes.map((relation) => (
              <button
                key={relation.type}
                type="button"
                aria-pressed={relation.active}
                onClick={() => onToggleRelationType(relation.type)}
                className={`inline-flex h-8 items-center gap-1.5 rounded-full border px-2.5 text-[11px] font-semibold transition-colors ${
                  relation.active
                    ? "border-slate-200 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                    : "border-slate-200 bg-slate-100 text-slate-400 opacity-75 hover:opacity-100 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-500"
                }`}
                title={relation.label}
              >
                <span className="h-1.5 w-4 rounded-full" style={{ backgroundColor: relation.active ? relation.color : "#cbd5e1" }} />
                <span>{relation.label}</span>
              </button>
            ))}
          </div>
        </section>
      </div>

      <div className="border-t border-slate-200 p-3 dark:border-slate-800">
        <div className="grid grid-cols-4 gap-2">
          <button
            type="button"
            onClick={onResetGraph}
            disabled={initialFetching}
            className="flex h-10 items-center justify-center rounded-lg border border-slate-200 text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-800 dark:text-slate-300 dark:hover:bg-slate-900 dark:hover:text-slate-100"
            title="刷新图谱"
            aria-label="刷新图谱"
          >
            {initialFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </button>
          <button
            type="button"
            onClick={onFitGraph}
            className="flex h-10 items-center justify-center rounded-lg border border-slate-200 text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-900 dark:border-slate-800 dark:text-slate-300 dark:hover:bg-slate-900 dark:hover:text-slate-100"
            title="适配视图"
            aria-label="适配视图"
          >
            <Maximize2 className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onZoomIn}
            className="flex h-10 items-center justify-center rounded-lg border border-slate-200 text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-900 dark:border-slate-800 dark:text-slate-300 dark:hover:bg-slate-900 dark:hover:text-slate-100"
            title="放大"
            aria-label="放大"
          >
            <ZoomIn className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onZoomOut}
            className="flex h-10 items-center justify-center rounded-lg border border-slate-200 text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-900 dark:border-slate-800 dark:text-slate-300 dark:hover:bg-slate-900 dark:hover:text-slate-100"
            title="缩小"
            aria-label="缩小"
          >
            <ZoomOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}

export function ForceGraphView({
  course,
  toolbar,
  onEvidenceClick,
  onSourceRefClick,
  totalNodeCount,
  totalEdgeCount,
}: {
  course: string;
  toolbar?: React.ReactNode;
  onEvidenceClick?: (chunkId: number, quoteText: string) => void;
  onSourceRefClick?: (ref: KnowledgeGraphSourceRefNavigationTarget) => void;
  totalNodeCount?: number;
  totalEdgeCount?: number;
}) {
  const queryClient = useQueryClient();
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [showSettingsPanel, setShowSettingsPanel] = useState(false);
  const [nodeSearchQuery, setNodeSearchQuery] = useState("");
  const [showEdgeLabels, setShowEdgeLabels] = useState(false);
  const [showAllEdges, setShowAllEdges] = useState(true);
  const [highlightCoreUnits, setHighlightCoreUnits] = useState(true);
  const [showAllNodeLabels, setShowAllNodeLabels] = useState(false);
  const [showDetailNodes, setShowDetailNodes] = useState(true);
  const [hiddenRelationTypes, setHiddenRelationTypes] = useState<Set<string>>(() => new Set());
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [graphData, setGraphData] = useState<LoadedGraphData | null>(null);
  const [expandedNodeIds, setExpandedNodeIds] = useState<Set<number>>(new Set());
  const [expandingNodeId, setExpandingNodeId] = useState<number | null>(null);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const zoomTransformRef = useRef<d3.ZoomTransform | null>(null);
  const fitGraphToViewRef = useRef<((duration?: number) => void) | null>(null);
  const hasAutoFittedGraphRef = useRef(false);
  const graphRefetchTimerRef = useRef<number | null>(null);
  const nodePositionRef = useRef<Map<number, GraphNodePosition>>(new Map());
  const lastLayoutScopeRef = useRef<string | null>(null);
  const lastGraphSignatureRef = useRef<string | null>(null);
  const lastGraphCountsRef = useRef<{ nodes: number; edges: number } | null>(null);
  const selectedNodeIdRef = useRef<number | null>(null);
  const showEdgeLabelsRef = useRef(false);
  const showAllEdgesRef = useRef(true);
  const highlightCoreUnitsRef = useRef(true);
  const showAllNodeLabelsRef = useRef(false);
  const graphZoomScaleRef = useRef(1);
  const zoomStyleFrameRef = useRef<number | null>(null);
  const expandedNodeIdsRef = useRef<Set<number>>(new Set());
  const [graphDelta, setGraphDelta] = useState<GraphDeltaState>(null);
  const graphStatsKnown = totalNodeCount !== undefined || totalEdgeCount !== undefined;
  const reportedNodeCount = Number(totalNodeCount ?? 0);
  const reportedEdgeCount = Number(totalEdgeCount ?? 0);
  const shouldUseFocusedInitialGraph =
    !graphStatsKnown ||
    reportedNodeCount > INITIAL_FOCUSED_GRAPH_THRESHOLD ||
    reportedEdgeCount > INITIAL_FOCUSED_GRAPH_EDGE_THRESHOLD;
  const initialFocusedGraphLimit = Math.max(
    80,
    Math.min(
      INITIAL_FOCUSED_GRAPH_THRESHOLD,
      Math.max(
        INITIAL_FOCUSED_GRAPH_LIMIT,
        Math.round(Math.sqrt(Math.max(1, reportedNodeCount)) * 12),
      ),
    ),
  );

  const {
    data: initialGraph,
    isLoading: initialLoading,
    isFetching: initialFetching,
    refetch: refetchInitialGraph,
  } = useQuery<FullGraphResponse | KnowledgeSubgraphResponse | null>({
    queryKey: [
      "graph-initial",
      course,
      reportedNodeCount,
      reportedEdgeCount,
      shouldUseFocusedInitialGraph ? "focused" : "full",
      initialFocusedGraphLimit,
    ],
    queryFn: async () => {
      if (shouldUseFocusedInitialGraph) {
        return unwrapOrvalResponse(
          await graphFocusSubgraphApiV1CoursesCourseIdKnowledgeGraphSubgraphPost(course, {
            center_knowledge_unit_id: null,
            topic: null,
            edge_type: null,
            hops: 1,
            limit: initialFocusedGraphLimit,
          }),
        ) ?? null;
      }
      return unwrapOrvalResponse(
        await graphFullApiV1CoursesCourseIdKnowledgeGraphFullPost(course),
      ) ?? null;
    },
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
  }, [initialGraph, course]);

  useEffect(() => {
    nodePositionRef.current.clear();
    zoomTransformRef.current = null;
    graphZoomScaleRef.current = 1;
    hasAutoFittedGraphRef.current = false;
    lastGraphSignatureRef.current = null;
    lastGraphCountsRef.current = null;
    setHiddenRelationTypes(new Set());
    setShowAllEdges(true);
    setShowDetailNodes(true);
    setShowAllNodeLabels(false);
    setShowEdgeLabels(false);
    setShowSettingsPanel(false);
    setNodeSearchQuery("");
    setGraphDelta(null);
  }, [course]);

  useEffect(() => {
    nodePositionRef.current.clear();
    zoomTransformRef.current = null;
    graphZoomScaleRef.current = 1;
    hasAutoFittedGraphRef.current = false;
  }, [showDetailNodes, hiddenRelationTypes]);

  useEffect(() => {
    if (!graphDelta) return;
    const timer = window.setTimeout(() => setGraphDelta(null), 4200);
    return () => window.clearTimeout(timer);
  }, [graphDelta]);

  const scheduleGraphRefresh = useCallback(() => {
    if (graphRefetchTimerRef.current !== null) return;
    graphRefetchTimerRef.current = window.setTimeout(() => {
      graphRefetchTimerRef.current = null;
      void refetchInitialGraph();
      void refetchBuildRuntime();
      void queryClient.invalidateQueries({ queryKey: ["knowledge-overview", course] });
      void queryClient.invalidateQueries({ queryKey: ["graph-node-list", course] });
      void queryClient.invalidateQueries({ queryKey: ["graph-initial", course] });
      void queryClient.invalidateQueries({ queryKey: ["graph-subgraph", course] });
    }, 900);
  }, [course, queryClient, refetchBuildRuntime, refetchInitialGraph]);

  useEffect(() => {
    return () => {
      if (graphRefetchTimerRef.current !== null) {
        window.clearTimeout(graphRefetchTimerRef.current);
        graphRefetchTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!graphIsLive) return;
    void refetchInitialGraph();
    const timer = window.setInterval(() => {
      void refetchInitialGraph();
    }, 4800);
    return () => window.clearInterval(timer);
  }, [graphIsLive, refetchInitialGraph]);

  useEffect(() => {
    if (!latestGraphStreamDelta) return;
    scheduleGraphRefresh();
  }, [latestGraphStreamDelta, scheduleGraphRefresh]);

  useEffect(() => {
    selectedNodeIdRef.current = selectedNodeId;
  }, [selectedNodeId]);

  useEffect(() => {
    showEdgeLabelsRef.current = showEdgeLabels;
  }, [showEdgeLabels]);

  useEffect(() => {
    showAllEdgesRef.current = showAllEdges;
  }, [showAllEdges]);

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
    setShowSettingsPanel(false);
    setNodeSearchQuery("");
    setHiddenRelationTypes(new Set());
    setShowAllEdges(true);
    setShowAllNodeLabels(false);
    setShowEdgeLabels(false);
    nodePositionRef.current.clear();
    zoomTransformRef.current = null;
    graphZoomScaleRef.current = 1;
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

  const focusNodeInView = useCallback((nodeId: number) => {
    const svg = svgRef.current;
    const zoom = zoomRef.current;
    const position = nodePositionRef.current.get(nodeId);
    if (!svg || !zoom || !position) return;
    const currentScale = zoomTransformRef.current?.k ?? 0.86;
    const nextScale = Math.max(0.72, Math.min(1.18, currentScale < 0.68 ? 0.82 : currentScale));
    const tx = dimensions.width / 2 - position.x * nextScale;
    const ty = dimensions.height / 2 - position.y * nextScale;
    d3.select(svg)
      .transition()
      .duration(260)
      .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(nextScale));
  }, [dimensions.height, dimensions.width]);

  const toggleRelationType = useCallback((type: string) => {
    setHiddenRelationTypes((current) => {
      const next = new Set(current);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  }, []);

  const rawData = graphData;

  // Parse graph data
  const {
    nodes,
    links,
    presentRelationTypes,
  } = useMemo(() => {
    if (!rawData) return { nodes: [] as GraphNode[], links: [] as GraphLink[], presentRelationTypes: [] as RelationFilterItem[] };

    const rawNodes = (rawData.nodes ?? []).filter((node: any) => !isSuppressedGraphNodeType(node.knowledge_unit_type));
    const nodeIdSet = new Set(rawNodes.map((n: any) => n.id));
    const relationCountByType = new Map<string, number>();

    const validEdges = (rawData.edges ?? [])
      .filter((e: any) => nodeIdSet.has(e.source_node_id) && nodeIdSet.has(e.target_node_id));
    for (const edge of validEdges) {
      relationCountByType.set(edge.edge_type, (relationCountByType.get(edge.edge_type) ?? 0) + 1);
    }
    const activeEdges = validEdges.filter((edge: any) => !hiddenRelationTypes.has(edge.edge_type));
    const pairTotals = new Map<string, number>();
    const pairIndexes = new Map<string, number>();
    const pairKeyOf = (e: any) => [e.source_node_id, e.target_node_id].sort((a, b) => Number(a) - Number(b)).join(":");
    for (const edge of activeEdges) {
      const key = pairKeyOf(edge);
      pairTotals.set(key, (pairTotals.get(key) ?? 0) + 1);
    }

    const baseLinks = activeEdges
      .map((e: any) => {
        const pairKey = pairKeyOf(e);
        const pairTotal = pairTotals.get(pairKey) ?? 1;
        const pairIndex = pairIndexes.get(pairKey) ?? 0;
        pairIndexes.set(pairKey, pairIndex + 1);
        const centeredIndex = pairIndex - (pairTotal - 1) / 2;
        const direction = Number(e.source_node_id) > Number(e.target_node_id) ? -1 : 1;
        const baseBend = deterministicEdgeBend(e);
        return {
          id: e.id,
          source: e.source_node_id,
          target: e.target_node_id,
          edge_type: e.edge_type,
          relation_label: relationLabel(e.edge_type),
          label_width: estimateRelationLabelWidth(relationLabel(e.edge_type)),
          source_node_id: e.source_node_id,
          target_node_id: e.target_node_id,
          weight: Number(e.weight ?? 1),
          confidence: Number(e.confidence ?? 0),
          pair_index: pairIndex,
          pair_total: pairTotal,
          curvature: pairTotal > 1
            ? (centeredIndex * 0.34 + baseBend * 0.35) * direction
            : baseBend * direction,
        };
      });
    const degreeByNodeId = new Map<number, number>();
    for (const link of baseLinks) {
      degreeByNodeId.set(link.source_node_id, (degreeByNodeId.get(link.source_node_id) ?? 0) + 1);
      degreeByNodeId.set(link.target_node_id, (degreeByNodeId.get(link.target_node_id) ?? 0) + 1);
    }
    const incidentLinksByNodeId = new Map<number, typeof baseLinks>();
    for (const link of baseLinks) {
      const sourceList = incidentLinksByNodeId.get(link.source_node_id) ?? [];
      sourceList.push(link);
      incidentLinksByNodeId.set(link.source_node_id, sourceList);
      const targetList = incidentLinksByNodeId.get(link.target_node_id) ?? [];
      targetList.push(link);
      incidentLinksByNodeId.set(link.target_node_id, targetList);
    }
    const strongestIncidentEdgeIds = new Set<number>();
    for (const [nodeId, incidentLinks] of incidentLinksByNodeId.entries()) {
      const allowance = Math.max(2, Math.min(5, Math.ceil(Math.sqrt(degreeByNodeId.get(nodeId) ?? 1)) + 1));
      [...incidentLinks]
        .sort((left, right) => edgePriority(right) - edgePriority(left))
        .slice(0, allowance)
        .forEach((link) => strongestIncidentEdgeIds.add(link.id));
    }
    const allLinks: GraphLink[] = baseLinks.map((link) => {
      const sourceDegree = degreeByNodeId.get(link.source_node_id) ?? 0;
      const targetDegree = degreeByNodeId.get(link.target_node_id) ?? 0;
      const linkWithDegree = {
        ...link,
        source_degree: sourceDegree,
        target_degree: targetDegree,
      };
      return {
        ...linkWithDegree,
        is_backbone: strongestIncidentEdgeIds.has(link.id) && isBackboneEdge(linkWithDegree),
      };
    });

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
    for (const link of allLinks) unionComponents(link.source_node_id, link.target_node_id);
    const componentSizeByRoot = new Map<number, number>();
    for (const id of nodeIdSet) {
      const root = findComponentRoot(Number(id));
      componentSizeByRoot.set(root, (componentSizeByRoot.get(root) ?? 0) + 1);
    }
    const componentRankByRoot = new Map<number, number>();
    Array.from(componentSizeByRoot.entries())
      .sort((a, b) => b[1] - a[1] || a[0] - b[0])
      .forEach(([root], index) => componentRankByRoot.set(root, index));

    const baseLayerByNodeId = new Map<number, number>();
    const layerByNodeId = new Map<number, number>();
    for (const n of rawNodes) {
      const baseLayer = nodeBaseLayer(String(n.knowledge_unit_type || ""));
      baseLayerByNodeId.set(Number(n.id), baseLayer);
      layerByNodeId.set(Number(n.id), baseLayer);
    }
    for (let iteration = 0; iteration < Math.min(24, Math.max(4, allLinks.length)); iteration += 1) {
      let changed = false;
      for (const edge of allLinks) {
        const direction = getLearningEdgeDirection(edge);
        if (!direction) continue;
        const fromLayer = layerByNodeId.get(direction.from);
        const toLayer = layerByNodeId.get(direction.to);
        if (fromLayer == null || toLayer == null) continue;
        const baseToLayer = baseLayerByNodeId.get(direction.to) ?? toLayer;
        const promotionAllowance = edge.edge_type === "prerequisite_for" ? 2 : 1;
        const maxPromotedLayer = clampGraphLayer(baseToLayer + promotionAllowance);
        const nextLayer = Math.min(maxPromotedLayer, clampGraphLayer(fromLayer + 1));
        if (nextLayer > toLayer) {
          layerByNodeId.set(direction.to, nextLayer);
          changed = true;
        }
      }
      if (!changed) break;
    }

    const baseNodes: Omit<GraphNode, "label_rank" | "layout_rank">[] = rawNodes.map((n: any) => {
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
        layout_layer: clampGraphLayer(layerByNodeId.get(Number(n.id)) ?? nodeBaseLayer(String(n.knowledge_unit_type || ""))),
      };
    });
    const labelRankByNodeId = new Map<number, number>();
    [...baseNodes]
      .sort((a, b) => graphNodePriority(b) - graphNodePriority(a))
      .forEach((node, index) => labelRankByNodeId.set(node.id, index + 1));
    const layoutRankByNodeId = new Map<number, number>();
    [...baseNodes]
      .sort((a, b) => a.layout_layer - b.layout_layer || a.component_rank - b.component_rank || graphNodePriority(b) - graphNodePriority(a) || a.id - b.id)
      .forEach((node, index) => layoutRankByNodeId.set(node.id, index));
    const nodes: GraphNode[] = baseNodes
      .map((node) => ({
        ...node,
        label_rank: labelRankByNodeId.get(node.id) ?? 999,
        layout_rank: layoutRankByNodeId.get(node.id) ?? 999,
      }))
      .sort((a, b) => graphNodePriority(a) - graphNodePriority(b));

    const visibleNodeIds = showDetailNodes
      ? new Set(nodes.map((node) => node.id))
      : new Set(
          [...nodes]
            .filter((node) => !isDetailGraphNode(node))
            .sort((left, right) => graphNodePriority(right) - graphNodePriority(left) || left.layout_rank - right.layout_rank)
            .map((node) => node.id),
        );
    if (selectedNodeId !== null) {
      visibleNodeIds.add(selectedNodeId);
      for (const link of allLinks) {
        if (link.source_node_id === selectedNodeId) visibleNodeIds.add(link.target_node_id);
        if (link.target_node_id === selectedNodeId) visibleNodeIds.add(link.source_node_id);
      }
    }
    const visibleNodes = nodes
      .filter((node) => visibleNodeIds.has(node.id))
      .sort((left, right) => left.layout_layer - right.layout_layer || left.layout_rank - right.layout_rank);
    const visibleLinks = allLinks.filter((link) => (
      visibleNodeIds.has(link.source_node_id) && visibleNodeIds.has(link.target_node_id)
    ));
    const backboneEdgeIds = selectBackboneEdgeIds(visibleLinks, visibleNodes.length, showDetailNodes);
    const links = visibleLinks.map((link) => ({
      ...link,
      is_backbone: backboneEdgeIds.has(link.id),
    }));

    const relationTypes = Array.from(relationCountByType.entries())
      .map(([type, count]) => ({
        type,
        count,
        label: relationLabel(type),
        color: relationTone(type),
        active: !hiddenRelationTypes.has(type),
      }))
      .sort((left, right) => (EDGE_TYPE_PRIORITY[right.type] ?? 0) - (EDGE_TYPE_PRIORITY[left.type] ?? 0) || left.label.localeCompare(right.label));
    return { nodes: visibleNodes, links, presentRelationTypes: relationTypes };
  }, [hiddenRelationTypes, rawData, selectedNodeId, showDetailNodes]);

  const nodeSearchResults = useMemo(() => {
    const query = nodeSearchQuery.trim().toLocaleLowerCase();
    if (!query) return [];
    return [...nodes]
      .filter((node) =>
        node.canonical_name.toLocaleLowerCase().includes(query) ||
        nodeStyle(node.knowledge_unit_type).label.toLocaleLowerCase().includes(query),
      )
      .sort((left, right) =>
        graphNodePriority(right) - graphNodePriority(left) ||
        left.layout_layer - right.layout_layer ||
        left.canonical_name.localeCompare(right.canonical_name),
      )
      .slice(0, 7);
  }, [nodeSearchQuery, nodes]);
  const desktopSidePanelOpen = selectedNodeId !== null || showSettingsPanel;
  const graphLayoutScope = useMemo(() => (
    `${GRAPH_LAYOUT_VERSION}:${dimensions.width}x${dimensions.height}:` +
    nodes.map((node) => `${node.id}:${node.layout_layer}:${node.knowledge_unit_type}`).join("|")
  ), [dimensions.height, dimensions.width, nodes]);

  useEffect(() => {
    if (lastLayoutScopeRef.current === graphLayoutScope) return;
    lastLayoutScopeRef.current = graphLayoutScope;
    nodePositionRef.current.clear();
    zoomTransformRef.current = null;
    graphZoomScaleRef.current = 1;
    hasAutoFittedGraphRef.current = false;
  }, [graphLayoutScope]);

  useEffect(() => {
    if (!rawData || nodes.length === 0) return;
    const timer = window.setTimeout(() => fitGraphToView(), 180);
    return () => window.clearTimeout(timer);
  }, [desktopSidePanelOpen, fitGraphToView, nodes.length, rawData]);

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
  }, [nodes.length]);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || nodes.length === 0) return;

    const containerRect = containerRef.current?.getBoundingClientRect();
    const width = Math.max(320, Math.round(containerRect?.width || dimensions.width));
    const height = Math.max(320, Math.round(containerRect?.height || dimensions.height));

    // Clear previous
    d3.select(svg).selectAll("*").remove();

    const structuredPositions = buildStructuredNodePositions(nodes, width, height);
    const workspaceHeight = height;

    // Deep copy nodes/links so D3 can mutate them. Preserve positions across live graph refreshes.
    const simNodes: GraphNode[] = nodes.map((node) => {
      const saved = nodePositionRef.current.get(node.id);
      const center = structuredPositions.get(node.id) ?? { x: width / 2, y: height / 2 };
      if (saved && saved.fx != null && saved.fy != null) {
        return { ...node, x: saved.x, y: saved.y, fx: saved.fx, fy: saved.fy };
      }
      return {
        ...node,
        x: saved?.x ?? center.x,
        y: saved?.y ?? center.y,
        fx: saved?.fx ?? undefined,
        fy: saved?.fy ?? undefined,
      };
    });
    const nodeById = new Map(simNodes.map((node) => [node.id, node]));
    const simLinks: GraphLink[] = links.flatMap((link) => {
      const source = nodeById.get(link.source_node_id);
      const target = nodeById.get(link.target_node_id);
      if (!source || !target) return [];
      return [{ ...link, source, target }];
    });
    const nodeZoneBounds = new Map<number, { left: number; top: number; right: number; bottom: number }>();
    const nodeLabelTextDx = (node: GraphNode) => nodeDotRadius(node) + 9;
    const nodeLabelAnchor = (_node?: GraphNode) => "start";
    const nodeDotRadius = (node: GraphNode) => (isAssessmentCoreNode(node) ? 8.4 : 7.1);
    const nodeDotCx = (_node: GraphNode) => 0;
    const nodeCollisionRadius = (node: GraphNode) => {
      const labelWidth = estimateGraphLabelWidth(node.canonical_name, graphNodeLabelLimit(node, null));
      const labelBoost =
        nodes.length <= 40
          ? Math.min(92, labelWidth * 0.38)
          : nodes.length <= 100
            ? Math.min(62, labelWidth * 0.26)
            : 20;
      return nodeDotRadius(node) + (showAllNodeLabels ? Math.max(50, labelBoost) : labelBoost);
    };
    const compactGraphSpread = nodes.length <= 24 ? 1.28 : nodes.length <= 80 ? 1.12 : 1;

    // SVG structure
    const svgSel = d3.select(svg)
      .attr("width", width)
      .attr("height", height)
      .attr("viewBox", [0, 0, width, height].join(" "));

    svgSel.append("style").text(`
      @keyframes graphHaloPulse {
        0%, 100% { opacity: 0.14; }
        50% { opacity: 0.34; }
      }
      .graph-link,
      .graph-node .node-circle,
      .graph-node .node-halo,
      .graph-node .node-priority-ring,
      .graph-node .node-label,
      .graph-node .node-formula-label {
        transition: opacity 160ms ease, stroke-width 160ms ease, stroke 160ms ease;
      }
      .graph-node .node-formula-label {
        overflow: visible;
        pointer-events: none;
      }
      .graph-node .node-formula-label-inner {
        display: inline-flex;
        align-items: center;
        min-height: 24px;
        max-width: 230px;
        border-radius: 8px;
        background: rgba(255,255,255,0.88);
        padding: 2px 6px;
        box-shadow: 0 0 0 1px rgba(226,232,240,0.78);
        white-space: nowrap;
      }
      .graph-node .node-formula-label-inner .katex {
        font-size: 1em;
        line-height: 1.15;
      }
      .graph-node {
        opacity: 1;
      }
      .graph-node .node-hit-area {
        pointer-events: all;
      }
      .graph-link {
        opacity: 1;
      }
      .graph-node.is-selected-node .node-halo,
      .graph-node.is-hover-focus .node-halo {
        animation: graphHaloPulse 1.8s ease-in-out infinite;
      }
      @media (prefers-reduced-motion: reduce) {
        .graph-node,
        .graph-link,
        .graph-node .node-halo,
        .graph-node .node-priority-ring,
        .graph-link.is-neighbor-link,
        .graph-link.is-selected-link {
          animation: none !important;
        }
        .graph-node,
        .graph-link {
          opacity: 1 !important;
        }
      }
    `);

    svgSel.append("rect")
      .attr("width", width)
      .attr("height", workspaceHeight)
      .attr("fill", "#fbfbfa");

    // Container for zoom/pan
    const g = svgSel.append("g");

    // Zoom behavior
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.15, 5])
      .on("zoom", (event) => {
        zoomTransformRef.current = event.transform;
        graphZoomScaleRef.current = event.transform.k;
        g.attr("transform", event.transform);
        if (zoomStyleFrameRef.current === null) {
          zoomStyleFrameRef.current = window.requestAnimationFrame(() => {
            zoomStyleFrameRef.current = null;
            applyGraphInteractiveStyles(
              svg,
              simLinks,
              selectedNodeIdRef.current,
              showEdgeLabelsRef.current,
              showAllEdgesRef.current,
              highlightCoreUnitsRef.current,
              showAllNodeLabelsRef.current,
              graphZoomScaleRef.current,
            );
          });
        }
      });
    svgSel.call(zoom);
    zoomRef.current = zoom;
    if (zoomTransformRef.current) {
      svgSel.call(zoom.transform, zoomTransformRef.current);
    }

    // Links group
    const linkGroup = g.append("g").attr("class", "links");

    const linkLine = linkGroup.selectAll<SVGPathElement, GraphLink>("path")
      .data(simLinks)
      .join("path")
      .attr("class", (d) => `graph-link${d.is_backbone ? " is-backbone-link" : ""}`)
      .attr("fill", "none")
      .attr("stroke", (d) => RELATION_COLORS[d.edge_type] ?? "#94a3b8")
      .attr("stroke-linecap", "round")
      .attr("stroke-linejoin", "round")
      .attr("stroke-width", (d) => (d.is_backbone ? 1.6 : 1.05))
      .attr("stroke-opacity", (d) => (d.is_backbone ? 0.46 : 0.22))
      .style("animation-delay", (_d, index) => `${Math.min(420, index * 16)}ms`);

    const hitLine = linkGroup.selectAll<SVGPathElement, GraphLink>("path.hit-area")
      .data(simLinks)
      .join("path")
      .attr("class", "hit-area")
      .attr("fill", "none")
      .attr("stroke", "transparent")
      .attr("stroke-width", 12);

    const labelLinks = showEdgeLabels ? simLinks : [];

    const linkLabelBg = linkGroup.selectAll<SVGRectElement, GraphLink>("rect")
      .data(labelLinks)
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
      .data(labelLinks)
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
    let simulation: d3.Simulation<GraphNode, GraphLink> | null = null;

    // Node containers
    const nodeG = nodeGroup.selectAll<SVGGElement, GraphNode>("g")
      .data(simNodes)
      .join("g")
      .attr("class", (d) => `graph-node${isAssessmentCoreNode(d) && d.label_rank <= 14 ? " is-core-pulse" : ""}`)
      .attr("cursor", "pointer")
      .call(
        d3.drag<SVGGElement, GraphNode>()
          .on("start", (event, d) => {
            simulation?.alphaTarget(0.18).restart();
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
            }
            d.x = event.x;
            d.y = event.y;
            d.fx = event.x;
            d.fy = event.y;
            if (dragNode.__hasDragged) renderTick(false);
          })
          .on("end", (event, d) => {
            const dragNode = d as DraggableGraphNode;
            if (dragNode.__hasDragged) {
              d.x = event.x;
              d.y = event.y;
              d.fx = event.x;
              d.fy = event.y;
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
            simulation?.alphaTarget(0);
            renderTick();
          })
      );

    // Node click handler
    nodeG.on("click", (event, d) => {
      event.stopPropagation();
      setSelectedNodeId((prev) => {
        const next = prev === d.id ? null : d.id;
        if (next !== null) setShowSettingsPanel(false);
        return next;
      });
    });

    nodeG.append("circle")
      .attr("class", "node-hit-area")
      .attr("cx", (d) => nodeDotCx(d))
      .attr("cy", 0)
      .attr("r", NODE_HIT_RADIUS)
      .attr("fill", "rgba(255,255,255,0.001)")
      .attr("stroke", "none");

    nodeG.append("circle")
      .attr("class", "node-halo")
      .attr("cx", (d) => nodeDotCx(d))
      .attr("cy", 0)
      .attr("r", (d) => nodeDotRadius(d) + 7)
      .attr("fill", (d) => nodeStyle(d.knowledge_unit_type).fill)
      .attr("opacity", 0);

    nodeG.append("circle")
      .attr("class", "node-priority-ring")
      .attr("cx", (d) => nodeDotCx(d))
      .attr("cy", 0)
      .attr("r", (d) => nodeDotRadius(d) + (isAssessmentCoreNode(d) ? 4.5 : 3.4))
      .attr("fill", "none")
      .attr("stroke", (d) => nodeStyle(d.knowledge_unit_type).fill)
      .attr("stroke-width", (d) => (isAssessmentCoreNode(d) ? 1.4 : 1))
      .attr("stroke-dasharray", (d) => (isAssessmentCoreNode(d) ? "0" : "2 4"))
      .attr("opacity", 0);

    nodeG.append("circle")
      .attr("class", "node-circle")
      .attr("cx", (d) => nodeDotCx(d))
      .attr("cy", 0)
      .attr("r", (d) => nodeDotRadius(d))
      .attr("fill", (d) => nodeStyle(d.knowledge_unit_type).fill)
      .attr("stroke", "#ffffff")
      .attr("stroke-width", 2)
      .attr("opacity", 1);

    nodeG.select<SVGCircleElement>("circle.node-halo").raise();
    nodeG.select<SVGCircleElement>("circle.node-priority-ring").raise();
    nodeG.select<SVGCircleElement>("circle.node-circle").raise();

    nodeG.append("text")
      .attr("class", "node-label")
      .attr("dx", (d) => nodeLabelTextDx(d))
      .attr("dy", 4)
      .attr("text-anchor", (d) => nodeLabelAnchor(d))
      .attr("font-size", (d) => (isAssessmentCoreNode(d) ? "12px" : "11.5px"))
      .attr("font-family", "system-ui, sans-serif")
      .attr("font-weight", (d) => (isAssessmentCoreNode(d) ? "720" : "620"))
      .attr("fill", "#1f2937")
      .attr("stroke", "rgba(255,255,255,0.92)")
      .attr("stroke-width", 3)
      .attr("paint-order", "stroke")
      .attr("opacity", 1)
      .style("pointer-events", "none")
      .text((d) => (isFormulaLikeGraphLabel(d) ? "" : truncateGraphLabel(d.canonical_name, graphNodeLabelLimit(d, null))));

    nodeG.filter((d) => isFormulaLikeGraphLabel(d))
      .append("foreignObject")
      .attr("class", "node-formula-label")
      .attr("x", (d) => nodeLabelTextDx(d) - 4)
      .attr("y", -15)
      .attr("width", (d) => graphFormulaLabelWidth(d))
      .attr("height", 30)
      .attr("opacity", 1)
      .html((d) => (
        `<div xmlns="http://www.w3.org/1999/xhtml" class="node-formula-label-inner">` +
        `${graphFormulaLabelHtml(d)}</div>`
      ));

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
        nodeG.select<SVGTextElement>("text.node-label")
          .attr("opacity", (node) => (connectedIds.has(node.id) ? 1 : 0));
        nodeG.select<SVGForeignObjectElement>("foreignObject.node-formula-label")
          .attr("opacity", (node) => (connectedIds.has(node.id) ? 1 : 0));
        linkLine
          .classed("is-neighbor-link", (link) => link.source_node_id === d.id || link.target_node_id === d.id)
          .attr("display", (link) => (
            showAllEdgesRef.current || link.is_backbone || link.source_node_id === d.id || link.target_node_id === d.id ? null : "none"
          ))
          .attr("stroke-opacity", (link) => (
            link.source_node_id === d.id || link.target_node_id === d.id ? 0.78 : 0.05
          ))
          .attr("stroke-width", (link) => (
            link.source_node_id === d.id || link.target_node_id === d.id ? 2.1 : 0.9
          ));
        linkGroup.selectAll<SVGPathElement, GraphLink>("path.hit-area")
          .attr("display", (link) => (
            showAllEdgesRef.current || link.is_backbone || link.source_node_id === d.id || link.target_node_id === d.id ? null : "none"
          ));
        linkLabel
          .attr("display", (link) => (
            showAllEdgesRef.current || link.is_backbone || link.source_node_id === d.id || link.target_node_id === d.id ? null : "none"
          ))
          .attr("opacity", (link) => (
            shouldShowSmartEdgeLabel(link, d.id, showEdgeLabelsRef.current, graphZoomScaleRef.current, simLinks.length) ? 1 : 0
          ));
        linkLabelBg
          .attr("display", (link) => (
            showAllEdgesRef.current || link.is_backbone || link.source_node_id === d.id || link.target_node_id === d.id ? null : "none"
          ))
          .attr("opacity", (link) => (
            shouldShowSmartEdgeLabel(link, d.id, showEdgeLabelsRef.current, graphZoomScaleRef.current, simLinks.length) ? 0.92 : 0
          ));
        d3.select(this).select("circle.node-halo").attr("opacity", 0.2);
        d3.select(this).select("circle.node-priority-ring").attr("opacity", 0.92);
        d3.select(this).select("circle.node-circle").attr("stroke", "#1d4ed8").attr("stroke-width", 3);
        d3.select(this).classed("is-hover-focus", true);
      })
      .on("mouseleave", function () {
        linkLine.classed("is-neighbor-link", false);
        nodeG.classed("is-hover-focus", false);
        applyGraphInteractiveStyles(
          svg,
          simLinks,
          selectedNodeIdRef.current,
          showEdgeLabelsRef.current,
          showAllEdgesRef.current,
          highlightCoreUnitsRef.current,
          showAllNodeLabelsRef.current,
          graphZoomScaleRef.current,
        );
      });

    applyGraphInteractiveStyles(
      svg,
      simLinks,
      selectedNodeIdRef.current,
      showEdgeLabelsRef.current,
      showAllEdgesRef.current,
      highlightCoreUnitsRef.current,
      showAllNodeLabelsRef.current,
      graphZoomScaleRef.current,
    );

    const displayPoint = (node: GraphNode) => ({
      x: Number(node.x ?? 0),
      y: Number(node.y ?? 0),
    });
    const buildCurvedLinkRoute = (d: any) => {
      const sourcePoint = displayPoint(d.source);
      const targetPoint = displayPoint(d.target);
      const rawSx = sourcePoint.x;
      const rawSy = sourcePoint.y;
      const rawTx = targetPoint.x;
      const rawTy = targetPoint.y;
      const rawDx = rawTx - rawSx;
      const rawDy = rawTy - rawSy;
      const rawDistance = Math.max(1, Math.sqrt(rawDx * rawDx + rawDy * rawDy));
      const edgeInset = (node: GraphNode, extra: number) => {
        return nodeDotRadius(node) + extra;
      };
      const sourceInset = edgeInset(d.source, 4);
      const targetInset = edgeInset(d.target, 4);
      const sx = rawSx + (rawDx / rawDistance) * sourceInset;
      const sy = rawSy + (rawDy / rawDistance) * sourceInset;
      const tx = rawTx - (rawDx / rawDistance) * targetInset;
      const ty = rawTy - (rawDy / rawDistance) * targetInset;
      const dx = tx - sx;
      const dy = ty - sy;
      const distance = Math.max(1, Math.sqrt(dx * dx + dy * dy));
      const sourceLayer = d.source.layout_layer ?? 2;
      const targetLayer = d.target.layout_layer ?? 2;
      const relationLane = ((EDGE_TYPE_PRIORITY[d.edge_type] ?? 3) - 3.5) * 10;
      const pairLane = (d.pair_index - (d.pair_total - 1) / 2) * 20;

      if (sourceLayer === targetLayer) {
        const side = sourceLayer >= GRAPH_LAYERS.length - 1 ? -1 : 1;
        const sideBend = side * (Math.min(168, Math.max(72, distance * 0.42)) + Math.abs(pairLane) * 0.34);
        return {
          sx,
          sy,
          tx,
          ty,
          c1x: sx + sideBend,
          c1y: sy + dy * 0.18 + relationLane,
          c2x: tx + sideBend,
          c2y: ty - dy * 0.18 + relationLane,
        };
      }
      const lane = relationLane + pairLane * 0.38 + d.curvature * 24;
      return {
        sx,
        sy,
        tx,
        ty,
        c1x: sx + dx * 0.42,
        c1y: sy + dy * 0.08 + lane,
        c2x: sx + dx * 0.58,
        c2y: ty - dy * 0.08 + lane,
      };
    };

    const linkPath = (d: any) => {
      const route = buildCurvedLinkRoute(d);
      return `M${route.sx},${route.sy} C${route.c1x},${route.c1y} ${route.c2x},${route.c2y} ${route.tx},${route.ty}`;
    };

    const linkMidpoint = (d: any) => {
      const route = buildCurvedLinkRoute(d);
      const t = 0.5;
      const mt = 1 - t;
      return {
        x: mt * mt * mt * route.sx + 3 * mt * mt * t * route.c1x + 3 * mt * t * t * route.c2x + t * t * t * route.tx,
        y: mt * mt * mt * route.sy + 3 * mt * mt * t * route.c1y + 3 * mt * t * t * route.c2y + t * t * t * route.ty,
      };
    };
    let positionSnapshotTick = 0;
    const saveNodePositions = () => {
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
    const renderTick = (persistPositions = true) => {
      for (const node of simNodes) {
        const bounds = nodeZoneBounds.get(node.id);
        if (!bounds) continue;
        const x = Number(node.x);
        const y = Number(node.y);
        const padding = NODE_HIT_RADIUS;
        if (Number.isFinite(x)) node.x = Math.min(bounds.right - padding, Math.max(bounds.left + padding, x));
        if (Number.isFinite(y)) {
          node.y = Math.min(
            bounds.bottom - padding,
            Math.max(bounds.top + padding, y),
          );
        }
      }
      linkLine.attr("d", (d: any) => linkPath(d));
      hitLine.attr("d", (d: any) => linkPath(d));

      linkLabel
        .attr("x", (d: any) => linkMidpoint(d).x)
        .attr("y", (d: any) => linkMidpoint(d).y - 6)
        .attr("transform", ""); // Explicitly avoid rotation for legibility
      linkLabelBg
        .attr("x", (d: any) => linkMidpoint(d).x - d.label_width / 2)
        .attr("y", (d: any) => linkMidpoint(d).y - 15);

      nodeG.attr("transform", (d: any) => {
        const point = displayPoint(d);
        return `translate(${point.x},${point.y})`;
      });
      if (persistPositions) {
        positionSnapshotTick += 1;
        if (positionSnapshotTick % 5 === 0) saveNodePositions();
      }
    };

    simulation = d3.forceSimulation<GraphNode>(simNodes)
      .force(
        "link",
        d3.forceLink<GraphNode, GraphLink>(simLinks)
          .id((d) => String(d.id))
          .distance((d) => ((d.is_backbone ? 92 : 118) + Math.min(34, (d.source_degree + d.target_degree) * 2)) * compactGraphSpread)
          .strength((d) => (d.is_backbone ? 0.28 : 0.13)),
      )
      .force("charge", d3.forceManyBody<GraphNode>().strength((d) => (-150 - Math.min(8, d.degree) * 18) * compactGraphSpread))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("x", d3.forceX<GraphNode>(width / 2).strength(0.025))
      .force("y", d3.forceY<GraphNode>(height / 2).strength(0.032))
      .force("collide", d3.forceCollide<GraphNode>().radius(nodeCollisionRadius).strength(nodes.length <= 80 ? 0.82 : 0.72))
      .alpha(0.92)
      .alphaDecay(nodes.length > 160 ? 0.07 : 0.045)
      .on("tick", () => renderTick());
    if (nodes.length > 180) {
      simulation.tick(80);
      simulation.alpha(nodes.length > 320 ? 0.08 : 0.14);
      renderTick();
    }
    const settleSimulationTimer = window.setTimeout(
      () => {
        if (nodes.length <= 180) return;
        simulation?.alphaTarget(0);
        simulation?.stop();
        renderTick();
      },
      nodes.length > 320 ? 760 : 1280,
    );

    const fitCurrentGraphToView = (duration = 600) => {
      const xExtent = d3.extent(simNodes, (d) => d.x) as [number, number];
      const yExtent = d3.extent(simNodes, (d) => d.y) as [number, number];
      if (xExtent[0] == null) return;
      const pad = showAllNodeLabels ? 34 : 44;
      const labelPad = showAllNodeLabels ? 136 : 96;
      const visualXMin = xExtent[0] - labelPad;
      const visualXMax = xExtent[1] + labelPad;
      const visualYMin = yExtent[0] - 74;
      const visualYMax = yExtent[1] + 76;
      const gw = visualXMax - visualXMin + pad * 2;
      const gh = visualYMax - visualYMin + pad * 2;
      const isMobileViewport = width < 640;
      const topReserve = isMobileViewport ? 24 : 68;
      const bottomReserve = isMobileViewport ? 24 : 52;
      const availableWidth = Math.max(isMobileViewport ? 280 : 320, width - (isMobileViewport ? 16 : 24));
      const availableHeight = Math.max(isMobileViewport ? 280 : 320, height - topReserve - bottomReserve);
      const fittedScale = Math.min(availableWidth / gw, availableHeight / gh, isMobileViewport ? 1.72 : 1.62);
      const readableScaleFloor = width < 520 ? 0.66 : width < 900 ? 0.5 : 0.48;
      const scale = Math.max(readableScaleFloor, fittedScale);
      const graphWidth = (visualXMax - visualXMin) * scale;
      const graphHeight = (visualYMax - visualYMin) * scale;
      const leftInset = Math.max(18, (availableWidth - graphWidth) * 0.5);
      const tx = leftInset - visualXMin * scale;
      const ty = topReserve + Math.max(0, availableHeight - graphHeight) * 0.12 - visualYMin * scale;
      hasAutoFittedGraphRef.current = true;
      svgSel.transition().duration(duration)
        .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
    };
    fitGraphToViewRef.current = fitCurrentGraphToView;
    renderTick(false);

    // Fit to view only for the first layout. Live refreshes preserve the user's viewport.
    let hasAutoFitted = false;
    const autoFitTimer = window.setTimeout(() => {
      if (hasAutoFitted || hasAutoFittedGraphRef.current) return;
      hasAutoFitted = true;
      fitCurrentGraphToView(520);
    }, 520);
    const settleFitTimer = window.setTimeout(() => {
      if (!hasAutoFitted || nodes.length > 140 || selectedNodeIdRef.current !== null) return;
      fitCurrentGraphToView(360);
    }, nodes.length > 80 ? 1800 : 1350);

    return () => {
      window.clearTimeout(autoFitTimer);
      window.clearTimeout(settleFitTimer);
      window.clearTimeout(settleSimulationTimer);
      if (zoomStyleFrameRef.current !== null) {
        window.cancelAnimationFrame(zoomStyleFrameRef.current);
        zoomStyleFrameRef.current = null;
      }
      simulation?.stop();
      saveNodePositions();
      if (fitGraphToViewRef.current === fitCurrentGraphToView) fitGraphToViewRef.current = null;
    };
  }, [nodes, links, dimensions, showAllEdges, showAllNodeLabels, showEdgeLabels]);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || nodes.length === 0) return;
    applyGraphInteractiveStyles(svg, links, selectedNodeId, showEdgeLabels, showAllEdges, highlightCoreUnits, showAllNodeLabels, graphZoomScaleRef.current);
  }, [links, nodes.length, selectedNodeId, showEdgeLabels, showAllEdges, highlightCoreUnits, showAllNodeLabels]);

  const graphIsLoading = !rawData && (initialLoading || initialFetching);
  const graphTotalKnown = reportedNodeCount > 0;
  const graphIsComplete = Boolean(rawData) && (
    graphTotalKnown
      ? (rawData?.nodes?.length ?? 0) >= reportedNodeCount
      : !shouldUseFocusedInitialGraph
  );
  const graphWindowed = Boolean(rawData && reportedNodeCount > 0 && (rawData.nodes?.length ?? 0) < reportedNodeCount);
  const graphStatusText = graphWindowed
    ? `主干 ${rawData?.nodes?.length ?? 0}/${reportedNodeCount}`
    : `${nodes.length} 节点`;
  const selectedNodeExpanded = selectedNodeId !== null && (graphIsComplete || expandedNodeIds.has(selectedNodeId));
  const graphProgressPct = typeof graphLane?.progress_pct === "number"
    ? Math.max(0, Math.min(100, Math.round(graphLane.progress_pct)))
    : null;
  const graphLiveMessage = graphIsLive
    ? `图谱实时更新中${graphProgressPct !== null ? ` · ${graphProgressPct}%` : ""}`
    : graphDelta
      ? "图谱已更新"
      : latestGraphStreamDelta
        ? "正在写入图谱"
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
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden bg-slate-50/60 dark:bg-slate-950 lg:block">
      <div className="shrink-0 space-y-2 border-b border-slate-200/70 bg-slate-50/95 px-3 py-2 dark:border-slate-800 dark:bg-slate-950/95 lg:hidden">
        <div className="flex flex-wrap items-center justify-between gap-2">
          {toolbar}
          <div className="flex shrink-0 items-center gap-1 rounded-lg bg-white/95 p-1 shadow-sm ring-1 ring-slate-200/70 dark:bg-slate-950/90 dark:ring-slate-700/80">
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
        </div>
      </div>
      {/* Graph panel */}
      <div className={`relative min-h-0 min-w-0 flex-1 lg:absolute lg:inset-0 ${desktopSidePanelOpen ? "lg:right-[320px]" : "lg:right-0"}`}>
        <div ref={containerRef} className="absolute inset-0">
          <svg ref={svgRef} className="h-full w-full" />
        </div>

        {/* Top-left: mode switch + compact status */}
        <div className="pointer-events-auto absolute left-3 top-3 z-10 hidden max-w-[calc(100%-1.5rem)] flex-wrap items-center gap-2 pr-24 sm:pr-28 lg:right-44 lg:flex lg:max-w-none lg:pr-0">
          {toolbar}
          <span
            className="inline-flex h-8 items-center rounded-lg bg-white/95 px-2.5 text-[11px] font-semibold text-slate-500 shadow-sm ring-1 ring-slate-200/70 dark:bg-slate-950/90 dark:text-slate-300 dark:ring-slate-700/80"
            title={graphWindowed ? "当前显示高连接主干子图" : "当前显示完整图谱"}
          >
            {graphStatusText}
          </span>
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
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-white/95 px-2.5 text-[11px] font-medium text-slate-500 shadow-sm ring-1 ring-slate-200/70 transition-colors hover:bg-white disabled:cursor-not-allowed disabled:opacity-60 dark:bg-slate-950/90 dark:text-slate-300 dark:ring-slate-700/80 dark:hover:bg-slate-900 lg:hidden"
              title={selectedNodeExpanded ? "当前节点已展开" : "展开当前节点的一跳邻居"}
            >
              {expandingNodeId === selectedNodeId ? <Loader2 className="h-3 w-3 animate-spin" /> : <NetworkIcon className="h-3 w-3" />}
              {selectedNodeExpanded ? "已展开" : "展开邻居"}
            </button>
          ) : null}
        </div>

        <div className="pointer-events-auto absolute right-3 top-3 z-10 hidden items-center gap-1 rounded-lg bg-white/95 p-1 shadow-sm ring-1 ring-slate-200/70 dark:bg-slate-950/90 dark:ring-slate-700/80 lg:flex">
          <button
            type="button"
            onClick={() => {
              setSelectedNodeId(null);
              setShowSettingsPanel((value) => !value);
            }}
            className={`flex h-8 w-8 items-center justify-center rounded-md transition-colors ${
              showSettingsPanel && !selectedNodeId
                ? "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-200"
                : "text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100"
            }`}
            title={showSettingsPanel && !selectedNodeId ? "收起图谱设置" : "打开图谱设置"}
            aria-label={showSettingsPanel && !selectedNodeId ? "收起图谱设置" : "打开图谱设置"}
          >
            <SlidersHorizontal className="h-4 w-4" />
          </button>
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

        <div className={`pointer-events-auto absolute bottom-3 left-3 z-10 w-80 max-w-[calc(100%-1.5rem)] ${selectedNodeId ? "hidden lg:block" : ""}`}>
          <div className="overflow-hidden rounded-lg border border-slate-200/80 bg-white/95 shadow-[0_18px_48px_rgba(15,23,42,0.12)] backdrop-blur dark:border-slate-700/80 dark:bg-slate-950/92">
            <div className="flex h-10 items-center gap-2 px-3">
              <Search className="h-4 w-4 text-slate-400" />
              <input
                value={nodeSearchQuery}
                onChange={(event) => setNodeSearchQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== "Enter" || nodeSearchResults.length === 0) return;
                  const node = nodeSearchResults[0];
                  setSelectedNodeId(node.id);
                  setShowSettingsPanel(false);
                  window.requestAnimationFrame(() => focusNodeInView(node.id));
                }}
                className="min-w-0 flex-1 bg-transparent text-sm font-medium text-slate-700 outline-none placeholder:text-slate-400 dark:text-slate-100 dark:placeholder:text-slate-500"
                placeholder="搜索知识点"
                aria-label="搜索知识点"
              />
              {nodeSearchQuery ? (
                <button
                  type="button"
                  onClick={() => setNodeSearchQuery("")}
                  className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-100"
                  title="清空搜索"
                  aria-label="清空搜索"
                >
                  <X className="h-4 w-4" />
                </button>
              ) : null}
            </div>
            {nodeSearchQuery.trim() ? (
              <div className="max-h-60 overflow-y-auto border-t border-slate-100 py-1 dark:border-slate-800">
                {nodeSearchResults.length ? nodeSearchResults.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    onClick={() => {
                      setSelectedNodeId(node.id);
                      setShowSettingsPanel(false);
                      window.requestAnimationFrame(() => focusNodeInView(node.id));
                    }}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-blue-50/80 dark:hover:bg-blue-950/30"
                  >
                    <span
                      className="h-2.5 w-2.5 flex-none rounded-full"
                      style={{ backgroundColor: nodeStyle(node.knowledge_unit_type).fill }}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs font-semibold text-slate-700 dark:text-slate-100">
                        {normalizeGraphTextLabel(node.canonical_name) || node.canonical_name}
                      </span>
                      <span className="block truncate text-[10px] font-medium text-slate-400 dark:text-slate-500">
                        {GRAPH_LAYERS[clampGraphLayer(node.layout_layer)]?.label ?? "图谱"} · {nodeStyle(node.knowledge_unit_type).label}
                      </span>
                    </span>
                  </button>
                )) : (
                  <div className="px-3 py-3 text-xs font-medium text-slate-400 dark:text-slate-500">没有匹配节点</div>
                )}
              </div>
            ) : null}
          </div>
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

      </div>

      <div className={`absolute bottom-0 right-0 top-0 z-20 hidden w-[320px] border-l border-slate-200 bg-white shadow-[-18px_0_44px_rgba(15,23,42,0.08)] dark:border-slate-800 dark:bg-slate-950 ${desktopSidePanelOpen ? "lg:flex" : "lg:hidden"}`}>
        {selectedNodeId ? (
          <div className="flex h-full w-full flex-col">
            {!graphIsComplete ? (
              <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-800">
                <button
                  type="button"
                  onClick={() => void expandNode(selectedNodeId)}
                  disabled={selectedNodeExpanded || expandingNodeId === selectedNodeId}
                  className="flex h-9 w-full items-center justify-center gap-2 rounded-lg border border-slate-200 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-800 dark:text-slate-300 dark:hover:bg-slate-900"
                >
                  {expandingNodeId === selectedNodeId ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <NetworkIcon className="h-3.5 w-3.5" />}
                  {selectedNodeExpanded ? "已展开邻居" : "展开邻居"}
                </button>
              </div>
            ) : null}
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              <KnowledgeGraphNodeDetailPanel
                course={course}
                nodeId={selectedNodeId}
                onClose={() => setSelectedNodeId(null)}
                onNavigate={(id) => setSelectedNodeId(id)}
                onEvidenceClick={onEvidenceClick}
                onSourceRefClick={onSourceRefClick}
              />
            </div>
          </div>
        ) : (
          <GraphSettingsSidebar
            presentRelationTypes={presentRelationTypes}
            showDetailNodes={showDetailNodes}
            showAllEdges={showAllEdges}
            showAllNodeLabels={showAllNodeLabels}
            showEdgeLabels={showEdgeLabels}
            highlightCoreUnits={highlightCoreUnits}
            hiddenRelationTypes={hiddenRelationTypes}
            initialFetching={initialFetching}
            onToggleDetailNodes={() => setShowDetailNodes((v) => !v)}
            onToggleAllEdges={() => setShowAllEdges((v) => !v)}
            onToggleAllNodeLabels={() => setShowAllNodeLabels((v) => !v)}
            onToggleEdgeLabels={() => setShowEdgeLabels((v) => !v)}
            onToggleCoreUnits={() => setHighlightCoreUnits((v) => !v)}
            onToggleRelationType={toggleRelationType}
            onClearRelationFilters={() => setHiddenRelationTypes(new Set())}
            onResetGraph={resetGraph}
            onFitGraph={fitGraphToView}
            onZoomIn={() => zoomGraphBy(1.22)}
            onZoomOut={() => zoomGraphBy(0.82)}
          />
        )}
      </div>

      {selectedNodeId && (
        <div className="absolute inset-x-3 bottom-3 z-20 max-h-[45dvh] overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-2xl shadow-slate-900/12 dark:border-slate-800 dark:bg-slate-950 lg:hidden">
          <div className="p-4">
            <KnowledgeGraphNodeDetailPanel
              course={course}
              nodeId={selectedNodeId}
              onClose={() => setSelectedNodeId(null)}
              onNavigate={(id) => setSelectedNodeId(id)}
              onEvidenceClick={onEvidenceClick}
              onSourceRefClick={onSourceRefClick}
            />
          </div>
        </div>
      )}
    </div>
  );
}
