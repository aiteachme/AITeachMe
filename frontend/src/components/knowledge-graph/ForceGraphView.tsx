import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import * as d3 from "d3";
import {
  Activity,
  Loader2,
  Maximize2,
  Network as NetworkIcon,
  RefreshCw,
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
import { KnowledgeGraphNodeDetailPanel } from "./KnowledgeGraphNodeDetailPanel";
import {
  DEFAULT_COLOR,
  EDGE_TYPE_PRIORITY,
  GRAPH_LAYERS,
  NODE_COLORS,
  RELATION_COLORS,
  clampGraphLayer,
  deterministicEdgeBend,
  edgePriority,
  estimateGraphLabelWidth,
  estimateRelationLabelWidth,
  getLearningEdgeDirection,
  graphNodeLabelLimit,
  graphNodePriority,
  graphNodeRadius,
  isAssessmentCoreNode,
  isBackboneEdge,
  isDirectionalLearningEdge,
  nodeBaseLayer,
  nodeStyle,
  relationLabel,
  relationTone,
  shouldShowSmartNodeLabel,
  truncateGraphLabel,
  type GraphLink,
  type GraphNode,
  type NodeVisualRole,
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

function applyGraphInteractiveStyles(
  svg: SVGSVGElement,
  links: GraphLink[],
  selectedNodeId: number | null,
  showEdgeLabels: boolean,
  showAllEdges: boolean,
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
  const isVisibleLink = (link: GraphLink) =>
    showAllEdges || link.is_backbone || (selectedNodeId !== null && isConnectedToSelected(link));

  const root = d3.select(svg);
  root.selectAll<SVGPathElement, GraphLink>("path.graph-link")
    .attr("display", (d) => (isVisibleLink(d) ? null : "none"))
    .attr("stroke-width", (d) => (isConnectedToSelected(d) ? 1.75 : 1.08))
    .attr("stroke-opacity", (d) => (selectedNodeId === null ? 0.34 : isConnectedToSelected(d) ? 0.82 : 0.1));
  root.selectAll<SVGPathElement, GraphLink>("path.hit-area")
    .attr("display", (d) => (isVisibleLink(d) ? null : "none"));

  root.selectAll<SVGTextElement, GraphLink>("text.graph-link-label")
    .attr("display", (d) => (isVisibleLink(d) ? null : "none"))
    .attr("opacity", (d) => (showEdgeLabels && (selectedNodeId === null || isConnectedToSelected(d)) ? 1 : 0));
  root.selectAll<SVGRectElement, GraphLink>("rect.graph-link-label-bg")
    .attr("display", (d) => (isVisibleLink(d) ? null : "none"))
    .attr("opacity", (d) => (showEdgeLabels && (selectedNodeId === null || isConnectedToSelected(d)) ? 0.96 : 0));

  const nodeG = root.selectAll<SVGGElement, GraphNode>("g.graph-node");
  nodeG.select<SVGCircleElement>("circle.node-halo")
    .attr("opacity", (d) => (d.id === selectedNodeId ? 0.18 : 0));
  nodeG.select<SVGCircleElement>("circle.node-priority-ring")
    .attr("opacity", (d) => {
      if (d.id === selectedNodeId) return 0.72;
      if (isAssessmentCoreNode(d) && highlightCoreUnits && d.label_rank <= 10) return 0.08;
      return 0;
    });
  nodeG.select<SVGCircleElement>("circle.node-circle")
    .attr("stroke", (d) => (d.id === selectedNodeId ? "#0f172a" : "#ffffff"))
    .attr("stroke-width", (d) => (d.id === selectedNodeId ? 3 : isAssessmentCoreNode(d) ? 2.35 : 2))
    .attr("opacity", (d) => {
      if (selectedNodeId !== null) return d.id === selectedNodeId || selectedNeighbors.has(d.id) ? 1 : 0.34;
      if (highlightCoreUnits && !isAssessmentCoreNode(d)) return 0.78;
      return 1;
    });
  nodeG.select<SVGRectElement>("rect.node-label-bg")
    .attr("opacity", (d) => {
      if (!shouldShowSmartNodeLabel(d, selectedNodeId, selectedNeighbors, showAllNodeLabels)) return 0;
      if (d.id === selectedNodeId) return 0.92;
      if (selectedNodeId !== null && selectedNeighbors.has(d.id)) return 0.68;
      return isAssessmentCoreNode(d) ? 0.76 : 0.62;
    })
    .attr("width", (d) => estimateGraphLabelWidth(d.canonical_name, graphNodeLabelLimit(d, selectedNodeId)));
  nodeG.select<SVGTextElement>("text.node-role-label")
    .attr("opacity", (d) => {
      if (d.id === selectedNodeId) return 1;
      return 0;
    });
  nodeG.select<SVGTextElement>("text.node-label")
    .attr("font-size", (d) => (isAssessmentCoreNode(d) || d.id === selectedNodeId ? "11.5px" : "10.5px"))
    .attr("font-weight", (d) => (isAssessmentCoreNode(d) || d.id === selectedNodeId ? "650" : "520"))
    .attr("fill", (d) => (d.id === selectedNodeId ? "#0f172a" : "#334155"))
    .attr("opacity", (d) => {
      if (!shouldShowSmartNodeLabel(d, selectedNodeId, selectedNeighbors, showAllNodeLabels)) return 0;
      if (selectedNodeId !== null) return d.id === selectedNodeId || selectedNeighbors.has(d.id) ? 1 : 0.3;
      return 0.96;
    })
    .text((d) => truncateGraphLabel(d.canonical_name, graphNodeLabelLimit(d, selectedNodeId)));
}

type LoadedGraphData = {
  nodes: KnowledgeUnitResponse[];
  edges: GraphEdgeResponse[];
};

const DETAIL_NODE_TYPES = new Set(["explanation_support", "practice_assessment", "application_extension"]);
const BACKBONE_RELATION_TYPES = new Set(["prerequisite", "contains", "reasoning", "application", "training"]);
const TYPE_CLUSTER_LAYOUT: Record<string, { xBias: number; yRatio: number; maxColumns: number }> = {
  knowledge_organization: { xBias: -0.42, yRatio: 0.38, maxColumns: 3 },
  core_knowledge: { xBias: -0.24, yRatio: 0.48, maxColumns: 4 },
  principle_reasoning: { xBias: -0.02, yRatio: 0.34, maxColumns: 4 },
  method_demo: { xBias: 0.18, yRatio: 0.64, maxColumns: 5 },
  explanation_support: { xBias: 0.36, yRatio: 0.3, maxColumns: 5 },
  practice_assessment: { xBias: 0.38, yRatio: 0.78, maxColumns: 4 },
  application_extension: { xBias: 0.42, yRatio: 0.56, maxColumns: 4 },
};

function isDetailGraphNode(node: Pick<GraphNode, "knowledge_unit_type">): boolean {
  return DETAIL_NODE_TYPES.has(node.knowledge_unit_type);
}

function getStructuredGraphMetrics(nodeCount: number, width: number, height: number) {
  const canvasWidth = Math.max(width, Math.min(2200, Math.max(980, nodeCount * 8.6 + 520)));
  const leftPad = Math.min(112, Math.max(58, canvasWidth * 0.058));
  const rightPad = Math.min(112, Math.max(58, canvasWidth * 0.058));
  const topPad = Math.min(88, Math.max(58, height * 0.072));
  const bottomPad = Math.min(88, Math.max(60, height * 0.072));
  const usableWidth = Math.max(420, canvasWidth - leftPad - rightPad);
  const usableHeight = Math.max(680, height - topPad - bottomPad);
  const layerStep = usableWidth / Math.max(1, GRAPH_LAYERS.length - 1);

  return {
    canvasWidth,
    leftPad,
    rightPad,
    topPad,
    bottomPad,
    usableWidth,
    usableHeight,
    layerStep,
  };
}

function selectBackboneEdgeIds(links: GraphLink[], visibleNodeCount: number, showDetailNodes: boolean): Set<number> {
  const selected = new Set<number>();
  const nodeUseCount = new Map<number, number>();
  const maxEdges = Math.max(
    22,
    Math.min(showDetailNodes ? 66 : 42, Math.round(visibleNodeCount * (showDetailNodes ? 0.5 : 0.54))),
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

  for (const link of learningLinks.filter((item) => item.edge_type === "prerequisite")) add(link, true);
  for (const link of learningLinks.filter((item) => item.edge_type !== "prerequisite")) add(link);
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

  const metrics = getStructuredGraphMetrics(nodes.length, width, height);
  const groupedByType = new Map<string, GraphNode[]>();
  for (const node of nodes) {
    const group = groupedByType.get(node.knowledge_unit_type) ?? [];
    group.push(node);
    groupedByType.set(node.knowledge_unit_type, group);
  }

  const groups = Array.from(groupedByType.entries())
    .map(([type, groupNodes]) => {
      const sortedNodes = groupNodes.sort((left, right) =>
        graphNodePriority(right) - graphNodePriority(left) ||
        left.layout_layer - right.layout_layer ||
        left.component_rank - right.component_rank ||
        left.id - right.id,
      );
      const averageLayer = sortedNodes.reduce((sum, node) => sum + node.layout_layer, 0) / Math.max(1, sortedNodes.length);
      return { type, nodes: sortedNodes, averageLayer };
    })
    .sort((left, right) => left.averageLayer - right.averageLayer || left.type.localeCompare(right.type));

  groups.forEach((group, groupIndex) => {
    const preset = TYPE_CLUSTER_LAYOUT[group.type] ?? {
      xBias: ((groupIndex % 3) - 1) * 0.1,
      yRatio: 0.26 + ((groupIndex * 0.19) % 0.58),
      maxColumns: 4,
    };
    const centerLayer = Math.max(0, Math.min(GRAPH_LAYERS.length - 1, group.averageLayer));
    const centerX = metrics.leftPad + metrics.layerStep * centerLayer + preset.xBias * metrics.layerStep;
    const centerY = metrics.topPad + metrics.usableHeight * preset.yRatio;
    group.nodes.forEach((node, index) => {
      const angle = index * 2.399963229728653 + groupIndex * 0.38;
      const radius = index === 0 ? 0 : 42 + Math.sqrt(index) * 43;
      const layerPull = (node.layout_layer - group.averageLayer) * metrics.layerStep * 0.16;
      const localX = ((node.id % 7) - 3) * 2.6;
      const localY = (((node.id * 3) % 7) - 3) * 2.1;
      positions.set(node.id, {
        x: centerX + Math.cos(angle) * radius * 1.28 + layerPull + localX,
        y: centerY + Math.sin(angle) * radius * 0.86 + localY,
      });
    });
  });

  return positions;
}

type GraphSettingsSidebarProps = {
  nodes: GraphNode[];
  links: GraphLink[];
  presentTypes: { type: string; fill: string; label: string; role: NodeVisualRole }[];
  presentRelationTypes: RelationFilterItem[];
  nodeCount: number;
  edgeCount: number;
  activeEdgeCount: number;
  backboneEdgeCount: number;
  coreNodeCount: number;
  visibleSmartLabelCount: number;
  totalLoadedNodeCount: number;
  totalNodeCount?: number;
  totalEdgeCount?: number;
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
  nodes,
  links,
  presentTypes,
  presentRelationTypes,
  nodeCount,
  edgeCount,
  activeEdgeCount,
  backboneEdgeCount,
  coreNodeCount,
  visibleSmartLabelCount,
  totalLoadedNodeCount,
  totalNodeCount,
  totalEdgeCount,
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
  const layerItems = GRAPH_LAYERS.map((layer, index) => {
    const layerNodes = nodes
      .filter((node) => node.layout_layer === index)
      .sort((left, right) => graphNodePriority(right) - graphNodePriority(left) || left.id - right.id);
    return {
      ...layer,
      count: layerNodes.length,
      nodes: layerNodes.slice(0, 3),
    };
  });
  const directedCount = links.filter((link) => isDirectionalLearningEdge(link.edge_type)).length;
  const lateralCount = Math.max(0, links.length - directedCount);
  const resolvedTotalNodeCount = totalLoadedNodeCount || totalNodeCount || nodeCount;
  const resolvedTotalEdgeCount = totalEdgeCount ?? edgeCount;
  const visibleEdgeCount = showAllEdges ? activeEdgeCount : backboneEdgeCount;
  const segmentClass = (active: boolean) =>
    `flex min-h-10 flex-1 items-center justify-between rounded-md px-3 py-2 text-left text-xs transition-colors ${
      active
        ? "bg-slate-900 text-white shadow-sm dark:bg-slate-100 dark:text-slate-950"
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
            <p className="text-sm font-semibold">图谱视图</p>
            <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
              {showDetailNodes ? "完整图谱" : "精简主图"} · {visibleEdgeCount}/{resolvedTotalEdgeCount} 关系
            </p>
          </div>
          <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700 ring-1 ring-blue-100 dark:bg-blue-500/10 dark:text-blue-300 dark:ring-blue-500/20">
            {nodeCount}/{resolvedTotalNodeCount}
          </span>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-2">
          {[
            ["节点", nodeCount],
            ["关系", visibleEdgeCount],
            ["考点", coreNodeCount],
          ].map(([label, value]) => (
            <div key={label} className="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-2 dark:border-slate-800 dark:bg-slate-900/70">
              <p className="text-[10px] font-medium text-slate-500 dark:text-slate-400">{label}</p>
              <p className="mt-0.5 text-sm font-semibold tabular-nums">{value}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <section className="border-b border-slate-200 px-4 py-4 dark:border-slate-800">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-xs font-semibold text-slate-700 dark:text-slate-200">显示范围</p>
            <span className="text-[11px] text-slate-400">{visibleSmartLabelCount} 个智能标签</span>
          </div>
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
              <span className="font-semibold tabular-nums">{resolvedTotalNodeCount}</span>
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
              <span className="font-semibold tabular-nums">{nodeCount}</span>
            </button>
          </div>
        </section>

        <section className="border-b border-slate-200 px-4 py-4 dark:border-slate-800">
          <p className="mb-2 text-xs font-semibold text-slate-700 dark:text-slate-200">关系密度</p>
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
              <span className="font-semibold tabular-nums">{backboneEdgeCount}</span>
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
              <span className="font-semibold tabular-nums">{activeEdgeCount}</span>
            </button>
          </div>
        </section>

        <section className="border-b border-slate-200 px-4 py-4 dark:border-slate-800">
          <p className="mb-3 text-xs font-semibold text-slate-700 dark:text-slate-200">标签与高亮</p>
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

        <section className="border-b border-slate-200 px-4 py-4 dark:border-slate-800">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-xs font-semibold text-slate-700 dark:text-slate-200">学习层级</p>
            <span className="text-[11px] text-slate-400">{directedCount} 主线 · {lateralCount} 横向</span>
          </div>
          <div className="space-y-2">
            {layerItems.map((layer) => (
              <div key={layer.label} className="flex items-center gap-3">
                <div className="w-12 shrink-0 text-xs font-semibold text-slate-700 dark:text-slate-200">{layer.label}</div>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                  <div
                    className="h-full rounded-full bg-blue-500"
                    style={{ width: `${Math.max(6, Math.min(100, (layer.count / Math.max(1, nodeCount)) * 100))}%` }}
                  />
                </div>
                <div className="w-9 text-right text-xs tabular-nums text-slate-500 dark:text-slate-400">{layer.count}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="border-b border-slate-200 px-4 py-4 dark:border-slate-800">
          <p className="mb-3 text-xs font-semibold text-slate-700 dark:text-slate-200">节点类型</p>
          <div className="flex flex-wrap gap-1.5">
            {presentTypes.map(({ type, fill, label }) => (
              <span
                key={type}
                className="inline-flex h-7 items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2 text-[11px] font-medium text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300"
              >
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: fill }} />
                {label}
              </span>
            ))}
          </div>
        </section>

        <section className="px-4 py-4">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-xs font-semibold text-slate-700 dark:text-slate-200">关系筛选</p>
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
                title={`${relation.label}，${relation.count} 条关系`}
              >
                <span className="h-1.5 w-4 rounded-full" style={{ backgroundColor: relation.active ? relation.color : "#cbd5e1" }} />
                <span>{relation.label}</span>
                <span className="text-slate-400">{relation.count}</span>
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
  const [showAllEdges, setShowAllEdges] = useState(false);
  const [highlightCoreUnits, setHighlightCoreUnits] = useState(true);
  const [showAllNodeLabels, setShowAllNodeLabels] = useState(false);
  const [showDetailNodes, setShowDetailNodes] = useState(true);
  const [hiddenRelationTypes, setHiddenRelationTypes] = useState<Set<string>>(new Set());
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [graphData, setGraphData] = useState<LoadedGraphData | null>(null);
  const [expandedNodeIds, setExpandedNodeIds] = useState<Set<number>>(new Set());
  const [expandingNodeId, setExpandingNodeId] = useState<number | null>(null);
  const simulationRef = useRef<d3.Simulation<GraphNode, GraphLink> | null>(null);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const zoomTransformRef = useRef<d3.ZoomTransform | null>(null);
  const fitGraphToViewRef = useRef<((duration?: number) => void) | null>(null);
  const hasAutoFittedGraphRef = useRef(false);
  const graphRefetchTimerRef = useRef<number | null>(null);
  const nodePositionRef = useRef<Map<number, GraphNodePosition>>(new Map());
  const lastGraphSignatureRef = useRef<string | null>(null);
  const lastGraphCountsRef = useRef<{ nodes: number; edges: number } | null>(null);
  const selectedNodeIdRef = useRef<number | null>(null);
  const showEdgeLabelsRef = useRef(false);
  const showAllEdgesRef = useRef(false);
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
  }, [initialGraph, course]);

  useEffect(() => {
    nodePositionRef.current.clear();
    zoomTransformRef.current = null;
    hasAutoFittedGraphRef.current = false;
    lastGraphSignatureRef.current = null;
    lastGraphCountsRef.current = null;
    setHiddenRelationTypes(new Set());
    setShowDetailNodes(true);
    setGraphDelta(null);
  }, [course]);

  useEffect(() => {
    nodePositionRef.current.clear();
    zoomTransformRef.current = null;
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
    }, 900);
  }, [refetchBuildRuntime, refetchInitialGraph]);

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
    presentTypes,
    presentRelationTypes,
    nodeCount,
    edgeCount,
    activeEdgeCount,
    coreNodeCount,
    backboneEdgeCount,
    visibleSmartLabelCount,
    totalLoadedNodeCount,
  } = useMemo(() => {
    if (!rawData) return { nodes: [] as GraphNode[], links: [] as GraphLink[], presentTypes: [] as { type: string; fill: string; label: string; role: NodeVisualRole }[], presentRelationTypes: [] as RelationFilterItem[], nodeCount: 0, edgeCount: 0, activeEdgeCount: 0, coreNodeCount: 0, backboneEdgeCount: 0, visibleSmartLabelCount: 0, totalLoadedNodeCount: 0 };

    const nodeIdSet = new Set((rawData.nodes ?? []).map((n: any) => n.id));
    const typeSet = new Set<string>();
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
    for (const n of rawData.nodes ?? []) {
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
        const promotionAllowance = edge.edge_type === "prerequisite" ? 2 : 1;
        const maxPromotedLayer = clampGraphLayer(baseToLayer + promotionAllowance);
        const nextLayer = Math.min(maxPromotedLayer, clampGraphLayer(fromLayer + 1));
        if (nextLayer > toLayer) {
          layerByNodeId.set(direction.to, nextLayer);
          changed = true;
        }
      }
      if (!changed) break;
    }

    const baseNodes: Omit<GraphNode, "label_rank" | "layout_rank">[] = (rawData.nodes ?? []).map((n: any) => {
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

    const totalLoadedNodeCount = nodes.length;
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

    const types = Array.from(typeSet)
      .map((t) => ({ type: t, ...(NODE_COLORS[t] ?? DEFAULT_COLOR) }))
      .sort((a, b) => {
        if (a.role !== b.role) return a.role === "assessment_core" ? -1 : b.role === "assessment_core" ? 1 : 0;
        return a.label.localeCompare(b.label);
      });
    const relationTypes = Array.from(relationCountByType.entries())
      .map(([type, count]) => ({
        type,
        count,
        label: relationLabel(type),
        color: relationTone(type),
        active: !hiddenRelationTypes.has(type),
      }))
      .sort((left, right) => (EDGE_TYPE_PRIORITY[right.type] ?? 0) - (EDGE_TYPE_PRIORITY[left.type] ?? 0) || left.label.localeCompare(right.label));
    const coreNodeCount = visibleNodes.filter((node) => isAssessmentCoreNode(node)).length;
    const backboneEdgeCount = links.filter((link) => link.is_backbone).length;
    const emptyNeighbors = new Set<number>();
    const visibleSmartLabelCount = visibleNodes.filter((node) => shouldShowSmartNodeLabel(node, null, emptyNeighbors, false)).length;

    return { nodes: visibleNodes, links, presentTypes: types, presentRelationTypes: relationTypes, nodeCount: visibleNodes.length, edgeCount: validEdges.length, activeEdgeCount: links.length, coreNodeCount, backboneEdgeCount, visibleSmartLabelCount, totalLoadedNodeCount };
  }, [hiddenRelationTypes, rawData, selectedNodeId, showDetailNodes]);

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

    const structuredPositions = buildStructuredNodePositions(nodes, width, height);
    const layoutMetrics = getStructuredGraphMetrics(nodes.length, width, height);

    const savedPositionCount = nodes.reduce((count, node) => (
      nodePositionRef.current.has(node.id) ? count + 1 : count
    ), 0);
    const newNodeCount = Math.max(0, nodes.length - savedPositionCount);

    // Deep copy nodes/links so D3 can mutate them. Preserve positions across live graph refreshes.
    const simNodes: GraphNode[] = nodes.map((node, index) => {
      const saved = nodePositionRef.current.get(node.id);
      if (saved) return { ...node, x: saved.x, y: saved.y, fx: saved.fx ?? undefined, fy: saved.fy ?? undefined };
      const center = structuredPositions.get(node.id) ?? { x: width / 2, y: height / 2 };
      const angle = index * 2.399963229728653;
      const radius = 12 + (index % 5) * 4;
      return {
        ...node,
        x: center.x + Math.cos(angle) * radius,
        y: center.y + Math.sin(angle) * radius,
      };
    });
    const nodeById = new Map(simNodes.map((node) => [node.id, node]));
    const simLinks: GraphLink[] = links.flatMap((link) => {
      const source = nodeById.get(link.source_node_id);
      const target = nodeById.get(link.target_node_id);
      if (!source || !target) return [];
      return [{ ...link, source, target }];
    });
    const forceLinks = simLinks.filter((link) => (
      showAllEdges ||
      link.is_backbone ||
      (selectedNodeIdRef.current !== null &&
        (link.source_node_id === selectedNodeIdRef.current || link.target_node_id === selectedNodeIdRef.current))
    ));

    // SVG structure
    const svgSel = d3.select(svg)
      .attr("width", width)
      .attr("height", height)
      .attr("viewBox", [0, 0, width, height].join(" "));

    const defs = svgSel.append("defs");
    svgSel.append("style").text(`
      @keyframes atm-node-breathe {
        0%, 100% { transform: scale(1); }
        50% { transform: scale(1.065); }
      }
      @keyframes atm-node-halo {
        0%, 100% { transform: scale(0.92); opacity: 0.05; }
        50% { transform: scale(1.28); opacity: 0.18; }
      }
      .graph-node .node-circle {
        transform-box: fill-box;
        transform-origin: center;
        animation: atm-node-breathe 5.8s ease-in-out infinite;
        animation-delay: var(--atm-delay, 0s);
      }
      .graph-node .node-halo {
        transform-box: fill-box;
        transform-origin: center;
        animation: atm-node-halo 6.6s ease-in-out infinite;
        animation-delay: var(--atm-delay, 0s);
      }
      @media (prefers-reduced-motion: reduce) {
        .graph-node .node-circle,
        .graph-node .node-halo {
          animation: none;
        }
      }
    `);

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
      .attr("opacity", 0.12);

    // Background: subtle workspace grid, borrowed from diagram tools without making the graph noisy.
    svgSel.append("rect")
      .attr("width", width)
      .attr("height", height)
      .attr("fill", "#f8fafc");
    svgSel.append("rect")
      .attr("width", width)
      .attr("height", height)
      .attr("fill", "url(#knowledge-graph-grid)");
    svgSel.append("rect")
      .attr("width", width)
      .attr("height", height)
      .attr("fill", "rgba(255,255,255,0.66)");

    // Container for zoom/pan
    const g = svgSel.append("g");

    const layerBand = g.append("g").attr("class", "graph-layer-guides").attr("pointer-events", "none");
    const guideTop = Math.max(24, layoutMetrics.topPad - 56);
    const guideBottom = layoutMetrics.topPad + layoutMetrics.usableHeight + 38;
    GRAPH_LAYERS.forEach((_, index) => {
      const x = layoutMetrics.leftPad + layoutMetrics.layerStep * index;
      layerBand.append("line")
        .attr("x1", x)
        .attr("x2", x)
        .attr("y1", guideTop)
        .attr("y2", guideBottom)
        .attr("stroke", "rgba(203,213,225,0.30)")
        .attr("stroke-width", 1)
        .attr("stroke-dasharray", "4 14");
    });
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
      .attr("stroke-linejoin", "round")
      .attr("stroke-width", 1.08)
      .attr("stroke-opacity", 0.34)
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
      .style("--atm-delay", (d) => `${-(d.id % 17) * 0.19}s`)
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
      .attr("r", (d) => graphNodeRadius(d) + 5)
      .attr("fill", (d) => nodeStyle(d.knowledge_unit_type).fill)
      .attr("opacity", 0);

    nodeG.append("circle")
      .attr("class", "node-priority-ring")
      .attr("r", (d) => graphNodeRadius(d) + (isAssessmentCoreNode(d) ? 3.5 : 2.5))
      .attr("fill", "none")
      .attr("stroke", (d) => nodeStyle(d.knowledge_unit_type).fill)
      .attr("stroke-width", (d) => (isAssessmentCoreNode(d) ? 1.4 : 1))
      .attr("stroke-dasharray", (d) => (isAssessmentCoreNode(d) ? "0" : "2 4"))
      .attr("opacity", 0);

    nodeG.append("circle")
      .attr("class", "node-circle")
      .attr("r", (d) => graphNodeRadius(d))
      .attr("fill", (d) => nodeStyle(d.knowledge_unit_type).fill)
      .attr("stroke", "#ffffff")
      .attr("stroke-width", 2)
      .attr("opacity", 1);

    nodeG.append("rect")
      .attr("class", "node-label-bg")
      .attr("x", (d) => graphNodeRadius(d) + 4)
      .attr("y", -11)
      .attr("width", (d) => estimateGraphLabelWidth(d.canonical_name, graphNodeLabelLimit(d, selectedNodeIdRef.current)))
      .attr("height", 20)
      .attr("rx", 4)
      .attr("fill", "rgba(255,255,255,0.86)")
      .attr("stroke", "rgba(203,213,225,0.8)")
      .attr("stroke-width", 0.8)
      .attr("opacity", 0)
      .style("pointer-events", "none");

    nodeG.append("text")
      .attr("class", "node-label")
      .attr("dx", (d) => graphNodeRadius(d) + 7)
      .attr("dy", 4)
      .attr("font-size", (d) => (isAssessmentCoreNode(d) ? "11.5px" : "10.5px"))
      .attr("font-family", "system-ui, sans-serif")
      .attr("font-weight", (d) => (isAssessmentCoreNode(d) ? "650" : "520"))
      .attr("fill", "#1f2937")
      .attr("stroke", "rgba(255,255,255,0.96)")
      .attr("stroke-width", 3.6)
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
          .attr("display", (link) => (
            showAllEdgesRef.current || link.is_backbone || link.source_node_id === d.id || link.target_node_id === d.id ? null : "none"
          ))
          .attr("stroke-opacity", (link) => (
            link.source_node_id === d.id || link.target_node_id === d.id ? 0.86 : 0.08
          ))
          .attr("stroke-width", (link) => (
            link.source_node_id === d.id || link.target_node_id === d.id ? 2.3 : 1
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
            showEdgeLabelsRef.current && (link.source_node_id === d.id || link.target_node_id === d.id) ? 1 : 0
          ));
        linkLabelBg
          .attr("display", (link) => (
            showAllEdgesRef.current || link.is_backbone || link.source_node_id === d.id || link.target_node_id === d.id ? null : "none"
          ))
          .attr("opacity", (link) => (
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
          showAllEdgesRef.current,
          highlightCoreUnitsRef.current,
          showAllNodeLabelsRef.current,
        );
      });

    const simulation = d3.forceSimulation<GraphNode>(simNodes)
      .force("link", d3.forceLink<GraphNode, GraphLink>(forceLinks).id((d) => d.id).distance((d) => {
        const sourceDegree = typeof d.source === "object" ? d.source.degree : 1;
        const targetDegree = typeof d.target === "object" ? d.target.degree : 1;
        const sourceIsCore = typeof d.source === "object" ? isAssessmentCoreNode(d.source) : false;
        const targetIsCore = typeof d.target === "object" ? isAssessmentCoreNode(d.target) : false;
        const sourceLayer = typeof d.source === "object" ? d.source.layout_layer : 2;
        const targetLayer = typeof d.target === "object" ? d.target.layout_layer : 2;
        const layerGap = Math.abs(sourceLayer - targetLayer);
        const base = layerGap === 0 ? 260 : 232 + layerGap * 64;
        return Math.max(188, base + Math.max(0, d.pair_total - 1) * 44 - Math.min(sourceDegree + targetDegree, 10) * 0.5 + (sourceIsCore || targetIsCore ? 18 : 42));
      }).strength((d) => {
        const sourceIsCore = typeof d.source === "object" ? isAssessmentCoreNode(d.source) : false;
        const targetIsCore = typeof d.target === "object" ? isAssessmentCoreNode(d.target) : false;
        return d.is_backbone ? (sourceIsCore || targetIsCore ? 0.018 : 0.014) : 0.0026;
      }))
      .force("charge", d3.forceManyBody<GraphNode>().strength((d) => (
        isAssessmentCoreNode(d) ? -230 - Math.min(d.degree, 9) * 18 : -162 - Math.min(d.degree, 7) * 14
      )))
      .force("center", d3.forceCenter(layoutMetrics.canvasWidth / 2, height / 2))
      .force("collision", d3.forceCollide<GraphNode>().radius((d) => graphNodeRadius(d) + (showAllNodeLabelsRef.current ? 70 : isAssessmentCoreNode(d) ? 54 : 46)).iterations(4))
      .force("x", d3.forceX<GraphNode>((d) => structuredPositions.get(d.id)?.x ?? layoutMetrics.canvasWidth / 2).strength(1.34))
      .force("y", d3.forceY<GraphNode>((d) => structuredPositions.get(d.id)?.y ?? height / 2).strength(1.28))
      .alphaDecay(0.088)
      .velocityDecay(0.82);
    simulation.alpha(savedPositionCount > 0 ? (newNodeCount > 0 || showAllEdges || showAllNodeLabels ? 0.22 : 0.035) : 1);

    simulationRef.current = simulation;
    applyGraphInteractiveStyles(
      svg,
      simLinks,
      selectedNodeIdRef.current,
      showEdgeLabelsRef.current,
      showAllEdgesRef.current,
      highlightCoreUnitsRef.current,
      showAllNodeLabelsRef.current,
    );

    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const floatingOffset = (node: GraphNode, now: number) => {
      if (prefersReducedMotion || node.fx != null || node.fy != null) return { x: 0, y: 0 };
      const seconds = now / 1000;
      const seed = (node.id % 997) * 0.173;
      const amplitude = isAssessmentCoreNode(node) ? 3.8 : 2.9;
      return {
        x: Math.sin(seconds * 0.48 + seed) * amplitude + Math.sin(seconds * 0.19 + seed * 1.7) * amplitude * 0.42,
        y: Math.cos(seconds * 0.42 + seed * 1.3) * amplitude * 0.78,
      };
    };
    const displayPoint = (node: GraphNode, now: number) => {
      const offset = floatingOffset(node, now);
      return {
        x: Number(node.x ?? 0) + offset.x,
        y: Number(node.y ?? 0) + offset.y,
      };
    };
    const buildCurvedLinkRoute = (d: any, now: number) => {
      const sourcePoint = displayPoint(d.source, now);
      const targetPoint = displayPoint(d.target, now);
      const rawSx = sourcePoint.x;
      const rawSy = sourcePoint.y;
      const rawTx = targetPoint.x;
      const rawTy = targetPoint.y;
      const rawDx = rawTx - rawSx;
      const rawDy = rawTy - rawSy;
      const rawDistance = Math.max(1, Math.sqrt(rawDx * rawDx + rawDy * rawDy));
      const sourceInset = graphNodeRadius(d.source) + 5;
      const targetInset = graphNodeRadius(d.target) + 12;
      const sx = rawSx + (rawDx / rawDistance) * sourceInset;
      const sy = rawSy + (rawDy / rawDistance) * sourceInset;
      const tx = rawTx - (rawDx / rawDistance) * targetInset;
      const ty = rawTy - (rawDy / rawDistance) * targetInset;
      const dx = tx - sx;
      const dy = ty - sy;
      const distance = Math.max(1, Math.sqrt(dx * dx + dy * dy));
      const sourceLayer = d.source.layout_layer ?? 2;
      const targetLayer = d.target.layout_layer ?? 2;
      const sameLayer = sourceLayer === targetLayer;
      const relationLane = ((EDGE_TYPE_PRIORITY[d.edge_type] ?? 3) - 3.5) * 10;
      const pairLane = (d.pair_index - (d.pair_total - 1) / 2) * 20;
      const sign = d.curvature >= 0 ? 1 : -1;
      const baseBend = sameLayer
        ? Math.min(168, Math.max(62, distance * 0.34))
        : Math.min(126, Math.max(42, distance * 0.18));
      let bend = sign * baseBend + relationLane + pairLane;
      const minBend = sameLayer ? 52 : 34;
      if (Math.abs(bend) < minBend) bend = sign * minBend;

      if (sourceLayer === targetLayer) {
        return {
          sx,
          sy,
          tx,
          ty,
          c1x: sx + dx * 0.28 - (dy / distance) * bend,
          c1y: sy + dy * 0.28 + (dx / distance) * bend,
          c2x: sx + dx * 0.72 - (dy / distance) * bend,
          c2y: sy + dy * 0.72 + (dx / distance) * bend,
        };
      }
      const direction = dx >= 0 ? 1 : -1;
      const handle = Math.max(82, Math.min(260, Math.abs(dx) * 0.52));
      return {
        sx,
        sy,
        tx,
        ty,
        c1x: sx + handle * direction,
        c1y: sy + bend,
        c2x: tx - handle * direction,
        c2y: ty + bend,
      };
    };

    const linkPath = (d: any, now: number) => {
      const route = buildCurvedLinkRoute(d, now);
      return `M${route.sx},${route.sy} C${route.c1x},${route.c1y} ${route.c2x},${route.c2y} ${route.tx},${route.ty}`;
    };

    const linkMidpoint = (d: any, now: number) => {
      const route = buildCurvedLinkRoute(d, now);
      const t = 0.5;
      const mt = 1 - t;
      return {
        x: mt * mt * mt * route.sx + 3 * mt * mt * t * route.c1x + 3 * mt * t * t * route.c2x + t * t * t * route.tx,
        y: mt * mt * mt * route.sy + 3 * mt * mt * t * route.c1y + 3 * mt * t * t * route.c2y + t * t * t * route.ty,
      };
    };
    let tickFrame: number | null = null;
    let breathingFrame: number | null = null;
    let lastBreathingRender = 0;
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
    const renderTick = (now = performance.now()) => {
      tickFrame = null;
      linkLine.attr("d", (d: any) => linkPath(d, now));
      linkGroup.selectAll<SVGPathElement, GraphLink>("path.hit-area").attr("d", (d: any) => linkPath(d, now));

      linkLabel
        .attr("x", (d: any) => linkMidpoint(d, now).x)
        .attr("y", (d: any) => linkMidpoint(d, now).y - 6)
        .attr("transform", ""); // Explicitly avoid rotation for legibility
      linkLabelBg
        .attr("x", (d: any) => linkMidpoint(d, now).x - d.label_width / 2)
        .attr("y", (d: any) => linkMidpoint(d, now).y - 15);

      nodeG.attr("transform", (d: any) => {
        const point = displayPoint(d, now);
        return `translate(${point.x},${point.y})`;
      });
      positionSnapshotTick += 1;
      if (positionSnapshotTick % 5 === 0) saveNodePositions();
    };
    const renderBreathingFrame = (now: number) => {
      if (now - lastBreathingRender >= 42) {
        lastBreathingRender = now;
        renderTick(now);
      }
      breathingFrame = window.requestAnimationFrame(renderBreathingFrame);
    };
    simulation.on("tick", () => {
      if (tickFrame !== null) return;
      tickFrame = window.requestAnimationFrame((now) => renderTick(now));
    });
    if (!prefersReducedMotion) {
      breathingFrame = window.requestAnimationFrame(renderBreathingFrame);
    }

    const fitCurrentGraphToView = (duration = 600) => {
      const xExtent = d3.extent(simNodes, (d) => d.x) as [number, number];
      const yExtent = d3.extent(simNodes, (d) => d.y) as [number, number];
      if (xExtent[0] == null) return;
      const pad = showDetailNodes ? 52 : 48;
      const visualXMin = Math.min(xExtent[0], layoutMetrics.leftPad - 96);
      const visualXMax = Math.max(xExtent[1], layoutMetrics.leftPad + layoutMetrics.layerStep * (GRAPH_LAYERS.length - 1) + 96);
      const visualYMin = Math.min(yExtent[0], layoutMetrics.topPad - 104);
      const visualYMax = Math.max(yExtent[1], layoutMetrics.topPad + layoutMetrics.usableHeight + 36);
      const gw = visualXMax - visualXMin + pad * 2;
      const gh = visualYMax - visualYMin + pad * 2;
      const topReserve = 68;
      const bottomReserve = 52;
      const availableWidth = Math.max(320, width - 24);
      const availableHeight = Math.max(320, height - topReserve - bottomReserve);
      const scale = Math.min(availableWidth / gw, availableHeight / gh, 1.28);
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

    // Fit to view only for the first layout. Live refreshes preserve the user's viewport.
    let hasAutoFitted = false;
    simulation.on("end", () => {
      if (hasAutoFitted || hasAutoFittedGraphRef.current) return;
      hasAutoFitted = true;
      hasAutoFittedGraphRef.current = true;
      fitCurrentGraphToView(600);
    });
    const autoFitTimer = window.setTimeout(() => {
      if (hasAutoFitted || hasAutoFittedGraphRef.current) return;
      hasAutoFitted = true;
      fitCurrentGraphToView(520);
    }, 520);

    return () => {
      window.clearTimeout(autoFitTimer);
      if (tickFrame !== null) window.cancelAnimationFrame(tickFrame);
      if (breathingFrame !== null) window.cancelAnimationFrame(breathingFrame);
      saveNodePositions();
      simulation.stop();
      if (fitGraphToViewRef.current === fitCurrentGraphToView) fitGraphToViewRef.current = null;
    };
  }, [nodes, links, dimensions, showAllEdges, showAllNodeLabels]);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || nodes.length === 0) return;
    applyGraphInteractiveStyles(svg, links, selectedNodeId, showEdgeLabels, showAllEdges, highlightCoreUnits, showAllNodeLabels);
  }, [links, nodes.length, selectedNodeId, showEdgeLabels, showAllEdges, highlightCoreUnits, showAllNodeLabels]);

  const graphIsLoading = !rawData && (initialLoading || initialFetching);
  const graphIsComplete = Boolean(rawData) && (!totalNodeCount || (rawData?.nodes?.length ?? 0) >= totalNodeCount);
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
    <div className="relative h-full min-h-0 overflow-hidden bg-slate-50/60 dark:bg-slate-950">
      {/* Graph panel */}
      <div className="absolute inset-0 min-h-0 min-w-0 lg:right-[360px]">
        <div ref={containerRef} className="absolute inset-0">
          <svg ref={svgRef} className="h-full w-full" />
        </div>

        {/* Top-left: mode switch + compact status */}
        <div className="pointer-events-auto absolute left-3 top-3 z-10 flex max-w-[calc(100%-1.5rem)] flex-wrap items-center gap-2 pr-24 lg:right-3 lg:max-w-none lg:pr-0">
          {toolbar}
          <span className="inline-flex h-8 items-center rounded-lg bg-white/95 px-2.5 text-[11px] font-medium text-slate-500 shadow-sm ring-1 ring-slate-200/70 dark:bg-slate-950/90 dark:text-slate-300 dark:ring-slate-700/80">
            {showDetailNodes ? "完整图谱" : "精简主图"} · {nodeCount}{totalLoadedNodeCount ? `/${totalLoadedNodeCount}` : totalNodeCount ? `/${totalNodeCount}` : ""} 节点 · {showAllEdges ? activeEdgeCount : backboneEdgeCount}/{totalEdgeCount ?? edgeCount} 关系
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

        <div className="pointer-events-auto absolute right-3 top-3 z-10 flex items-center gap-1 rounded-lg bg-white/95 p-1 shadow-sm ring-1 ring-slate-200/70 dark:bg-slate-950/90 dark:ring-slate-700/80 lg:hidden">
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

      </div>

      <div className="absolute bottom-0 right-0 top-0 z-20 hidden w-[360px] border-l border-slate-200 bg-white shadow-[-18px_0_44px_rgba(15,23,42,0.08)] dark:border-slate-800 dark:bg-slate-950 lg:flex">
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
              />
            </div>
          </div>
        ) : (
          <GraphSettingsSidebar
            nodes={nodes}
            links={links}
            presentTypes={presentTypes}
            presentRelationTypes={presentRelationTypes}
            nodeCount={nodeCount}
            edgeCount={edgeCount}
            activeEdgeCount={activeEdgeCount}
            backboneEdgeCount={backboneEdgeCount}
            coreNodeCount={coreNodeCount}
            visibleSmartLabelCount={visibleSmartLabelCount}
            totalLoadedNodeCount={totalLoadedNodeCount}
            totalNodeCount={totalNodeCount}
            totalEdgeCount={totalEdgeCount}
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
            />
          </div>
        </div>
      )}
    </div>
  );
}
