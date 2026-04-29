import { useEffect, useMemo, useState } from "react";
import {
  Filter,
  Focus,
  Loader2,
  Orbit,
  Sparkles,
  Waypoints,
} from "lucide-react";

interface GraphNode {
  id: number;
  canonical_name: string;
  knowledge_unit_type: string;
  confidence: number;
}

interface GraphEdge {
  id: number;
  source_node_id: number;
  target_node_id: number;
  edge_type: string;
  confidence: number;
}

interface GraphPayload {
  nodes?: GraphNode[];
  edges?: GraphEdge[];
}

interface SemanticUniverseProps {
  subjectLabel: string;
  overviewGraph: GraphPayload | null | undefined;
  height?: string | number;
  onNodeClick?: (nodeId: number) => void;
}

interface PositionedNode extends GraphNode {
  x: number;
  y: number;
  degree: number;
  clusterId: string;
  clusterLabel: string;
}

const TYPE_ORDER = ["concept", "definition", "theorem", "formula", "example", "exercise", "method", "proof_step", "remark"] as const;
const TYPE_COLORS: Record<string, string> = {
  concept: "#2563eb",
  definition: "#7c3aed",
  theorem: "#0f766e",
  formula: "#0891b2",
  example: "#dc2626",
  exercise: "#e11d48",
  method: "#d97706",
  proof_step: "#9333ea",
  remark: "#475569",
};

function hashString(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return Math.abs(hash >>> 0);
}

function priorityOf(type: string): number {
  const index = TYPE_ORDER.indexOf(type.toLowerCase() as (typeof TYPE_ORDER)[number]);
  return index >= 0 ? index : TYPE_ORDER.length + 1;
}

function clusterColor(type: string): string {
  return TYPE_COLORS[type.toLowerCase()] ?? "#475569";
}

function radiusFor(type: string): number {
  const normalized = type.toLowerCase();
  if (normalized === "concept") {
    return 16;
  }
  if (normalized === "method" || normalized === "theorem") {
    return 13;
  }
  return 11;
}

function buildAdjacency(nodes: GraphNode[], edges: GraphEdge[]) {
  const adjacency = new Map<number, Set<number>>();
  for (const node of nodes) {
    adjacency.set(node.id, new Set());
  }
  for (const edge of edges) {
    adjacency.get(edge.source_node_id)?.add(edge.target_node_id);
    adjacency.get(edge.target_node_id)?.add(edge.source_node_id);
  }
  return adjacency;
}

function chooseClusterLabel(clusterNodes: GraphNode[], degreeByNode: Map<number, number>) {
  const sorted = [...clusterNodes].sort((left, right) => {
    const priorityDelta = priorityOf(left.knowledge_unit_type) - priorityOf(right.knowledge_unit_type);
    if (priorityDelta !== 0) {
      return priorityDelta;
    }
    const degreeDelta = (degreeByNode.get(right.id) ?? 0) - (degreeByNode.get(left.id) ?? 0);
    if (degreeDelta !== 0) {
      return degreeDelta;
    }
    const confidenceDelta = right.confidence - left.confidence;
    if (confidenceDelta !== 0) {
      return confidenceDelta;
    }
    return left.canonical_name.localeCompare(right.canonical_name, "zh-CN");
  });
  return sorted[0]?.canonical_name ?? "Knowledge Cluster";
}

function layoutUniverse(
  width: number,
  height: number,
  nodes: GraphNode[],
  edges: GraphEdge[],
): {
  positionedNodes: PositionedNode[];
  adjacency: Map<number, Set<number>>;
} {
  const adjacency = buildAdjacency(nodes, edges);
  const degreeByNode = new Map<number, number>(
    nodes.map((node) => [node.id, adjacency.get(node.id)?.size ?? 0]),
  );

  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const visited = new Set<number>();
  const clusters: Array<{ id: string; label: string; nodes: GraphNode[] }> = [];

  for (const node of nodes) {
    if (visited.has(node.id)) {
      continue;
    }
    const queue = [node.id];
    const clusterNodeIds: number[] = [];
    visited.add(node.id);
    while (queue.length > 0) {
      const current = queue.shift()!;
      clusterNodeIds.push(current);
      for (const neighbor of adjacency.get(current) ?? []) {
        if (visited.has(neighbor)) {
          continue;
        }
        visited.add(neighbor);
        queue.push(neighbor);
      }
    }
    const clusterNodes = clusterNodeIds
      .map((clusterNodeId) => nodeById.get(clusterNodeId))
      .filter((value): value is GraphNode => Boolean(value));
    const label = chooseClusterLabel(clusterNodes, degreeByNode);
    clusters.push({
      id: `cluster-${hashString(label)}-${clusterNodes.length}`,
      label,
      nodes: clusterNodes,
    });
  }

  const sortedClusters = clusters.sort((left, right) => left.label.localeCompare(right.label, "zh-CN"));
  const centerX = width / 2;
  const centerY = height / 2;
  const ringRadius = Math.max(140, Math.min(width, height) * 0.28);

  const positionedNodes: PositionedNode[] = [];
  for (let clusterIndex = 0; clusterIndex < sortedClusters.length; clusterIndex += 1) {
    const cluster = sortedClusters[clusterIndex];
    const clusterAngle = (Math.PI * 2 * clusterIndex) / Math.max(sortedClusters.length, 1) - Math.PI / 2;
    const clusterDistance = sortedClusters.length === 1 ? 0 : ringRadius;
    const clusterCenterX = centerX + Math.cos(clusterAngle) * clusterDistance;
    const clusterCenterY = centerY + Math.sin(clusterAngle) * clusterDistance;
    const orderedNodes = [...cluster.nodes].sort((left, right) => {
      const priorityDelta = priorityOf(left.knowledge_unit_type) - priorityOf(right.knowledge_unit_type);
      if (priorityDelta !== 0) {
        return priorityDelta;
      }
      const degreeDelta = (degreeByNode.get(right.id) ?? 0) - (degreeByNode.get(left.id) ?? 0);
      if (degreeDelta !== 0) {
        return degreeDelta;
      }
      return left.canonical_name.localeCompare(right.canonical_name, "zh-CN");
    });

    for (let index = 0; index < orderedNodes.length; index += 1) {
      const node = orderedNodes[index];
      const orbitLevel = Math.floor(index / 6);
      const withinOrbitIndex = index % 6;
      const orbitCount = Math.min(6, orderedNodes.length - orbitLevel * 6);
      const orbitRadius = 34 + orbitLevel * 26;
      const angleOffset = (hashString(node.canonical_name) % 360) * (Math.PI / 180) * 0.08;
      const angle = (Math.PI * 2 * withinOrbitIndex) / Math.max(orbitCount, 1) + angleOffset;
      positionedNodes.push({
        ...node,
        x: clusterCenterX + Math.cos(angle) * orbitRadius,
        y: clusterCenterY + Math.sin(angle) * orbitRadius,
        degree: degreeByNode.get(node.id) ?? 0,
        clusterId: cluster.id,
        clusterLabel: cluster.label,
      });
    }
  }

  return { positionedNodes, adjacency };
}

export function SemanticUniverse({
  subjectLabel,
  overviewGraph,
  height = "calc(100vh - 16rem)",
  onNodeClick,
}: SemanticUniverseProps) {
  const [viewport, setViewport] = useState({ width: 1200, height: 720 });
  const [selectedTypes, setSelectedTypes] = useState<Set<string>>(new Set(TYPE_ORDER));
  const [hoveredNodeId, setHoveredNodeId] = useState<number | null>(null);
  const [focusedNodeId, setFocusedNodeId] = useState<number | null>(null);

  useEffect(() => {
    const updateViewport = () => {
      const width = Math.max(window.innerWidth * 0.72, 900);
      const heightValue = typeof height === "number" ? height : Math.max(window.innerHeight - 240, 560);
      setViewport({ width, height: heightValue });
    };
    updateViewport();
    window.addEventListener("resize", updateViewport);
    return () => window.removeEventListener("resize", updateViewport);
  }, [height]);

  const nodes = overviewGraph?.nodes ?? [];
  const edges = overviewGraph?.edges ?? [];
  const availableTypes = useMemo(
    () => Array.from(new Set(nodes.map((node) => node.knowledge_unit_type))).sort((left, right) => priorityOf(left) - priorityOf(right)),
    [nodes],
  );

  const visibleNodes = useMemo(
    () => nodes.filter((node) => selectedTypes.has(node.knowledge_unit_type)),
    [nodes, selectedTypes],
  );
  const visibleNodeIds = useMemo(() => new Set(visibleNodes.map((node) => node.id)), [visibleNodes]);
  const visibleEdges = useMemo(
    () =>
      edges.filter(
        (edge) => visibleNodeIds.has(edge.source_node_id) && visibleNodeIds.has(edge.target_node_id),
      ),
    [edges, visibleNodeIds],
  );

  const { positionedNodes, adjacency } = useMemo(
    () => layoutUniverse(viewport.width, viewport.height, visibleNodes, visibleEdges),
    [viewport.height, viewport.width, visibleEdges, visibleNodes],
  );
  const activeNodeId = focusedNodeId ?? hoveredNodeId;
  const activeNeighborSet = useMemo(() => {
    if (activeNodeId === null) {
      return new Set<number>();
    }
    return new Set([activeNodeId, ...(adjacency.get(activeNodeId) ?? [])]);
  }, [activeNodeId, adjacency]);
  const activeNode = positionedNodes.find((node) => node.id === activeNodeId) ?? null;

  if (!overviewGraph) {
    return (
      <div className="flex h-[520px] items-center justify-center rounded-2xl border border-slate-200 bg-white text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-400">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        正在等待知识图谱数据...
      </div>
    );
  }

  if (nodes.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-6 py-10 text-center dark:border-slate-800 dark:bg-slate-950">
        <Orbit className="mx-auto h-8 w-8 text-slate-400" />
        <p className="mt-3 text-sm font-medium text-slate-700 dark:text-slate-200">还没有可展示的知识宇宙</p>
        <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">开始一次 digest 构建后，这里会展示稳定的主题团簇和相邻知识关系。</p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-[radial-gradient(circle_at_top,#eff6ff_0%,#f8fafc_40%,#ffffff_100%)] shadow-sm dark:border-slate-800 dark:bg-[radial-gradient(circle_at_top,rgba(14,165,233,0.13)_0%,rgba(15,23,42,0.96)_42%,#020617_100%)]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <div>
          <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
            <Orbit className="h-4 w-4 text-sky-600" />
            <p className="text-sm font-semibold">{subjectLabel} 的语义星图</p>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-400">
            稳定聚类展示主题骨架、核心概念与相邻方法，点击节点可以锁定焦点。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setFocusedNodeId(null)}
            className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:text-slate-900 dark:border-slate-700 dark:bg-slate-950/80 dark:text-slate-300 dark:hover:text-slate-100"
          >
            <Focus className="h-3.5 w-3.5" />
            重置焦点
          </button>
        </div>
      </div>

      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <div className="mb-2 flex items-center gap-2 text-xs font-medium text-slate-600 dark:text-slate-400">
          <Filter className="h-3.5 w-3.5" />
          类型筛选
        </div>
        <div className="flex flex-wrap gap-2">
          {availableTypes.map((type) => {
            const selected = selectedTypes.has(type);
            return (
              <button
                key={type}
                type="button"
                onClick={() =>
                  setSelectedTypes((previous) => {
                    const next = new Set(previous);
                    if (next.has(type)) {
                      next.delete(type);
                    } else {
                      next.add(type);
                    }
                    return next.size === 0 ? new Set(previous) : next;
                  })
                }
                className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                  selected
                    ? "border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900"
                    : "border-slate-200 bg-white text-slate-600 hover:text-slate-900 dark:border-slate-700 dark:bg-slate-950/80 dark:text-slate-300 dark:hover:text-slate-100"
                }`}
              >
                {type}
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid gap-0 xl:grid-cols-[1fr_320px]">
        <div className="relative overflow-hidden" style={{ height }}>
          <svg viewBox={`0 0 ${viewport.width} ${viewport.height}`} className="h-full w-full">
            {visibleEdges.map((edge) => {
              const source = positionedNodes.find((node) => node.id === edge.source_node_id);
              const target = positionedNodes.find((node) => node.id === edge.target_node_id);
              if (!source || !target) {
                return null;
              }
              const active = activeNeighborSet.size === 0 || (activeNeighborSet.has(source.id) && activeNeighborSet.has(target.id));
              return (
                <line
                  key={edge.id}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  stroke={active ? "#94a3b8" : "#cbd5e1"}
                  strokeOpacity={active ? 0.35 : 0.12}
                  strokeWidth={active ? 1.6 : 1}
                />
              );
            })}

            {positionedNodes.map((node) => {
              const color = clusterColor(node.knowledge_unit_type);
              const active = activeNeighborSet.size === 0 || activeNeighborSet.has(node.id);
              const isFocused = focusedNodeId === node.id;
              const radius = radiusFor(node.knowledge_unit_type);
              return (
                <g
                  key={node.id}
                  transform={`translate(${node.x},${node.y})`}
                  onMouseEnter={() => setHoveredNodeId(node.id)}
                  onMouseLeave={() => setHoveredNodeId((current) => (current === node.id ? null : current))}
                  onClick={() => {
                    setFocusedNodeId(node.id);
                    onNodeClick?.(node.id);
                  }}
                  className="cursor-pointer"
                >
                  <circle
                    r={radius + (isFocused ? 6 : 0)}
                    fill={color}
                    fillOpacity={active ? 0.92 : 0.3}
                    stroke={isFocused ? "#0f172a" : "#ffffff"}
                    strokeWidth={isFocused ? 3 : 2}
                  />
                  <text
                    y={radius + 18}
                    textAnchor="middle"
                    className="select-none fill-slate-700 text-[11px] font-medium"
                    style={{ opacity: active ? 1 : 0.45 }}
                  >
                    {node.canonical_name.length > 10 ? `${node.canonical_name.slice(0, 10)}…` : node.canonical_name}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>

        <aside className="border-t border-slate-200 bg-white/90 px-4 py-4 dark:border-slate-800 dark:bg-slate-950/88 xl:border-l xl:border-t-0">
          <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
            <Waypoints className="h-4 w-4 text-sky-600" />
            <p className="text-sm font-semibold">焦点详情</p>
          </div>

          {activeNode ? (
            <div className="mt-4 space-y-3">
              <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3 dark:border-slate-800 dark:bg-slate-900/70">
                <p className="text-sm font-medium text-slate-900 dark:text-slate-100">{activeNode.canonical_name}</p>
                <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-400">
                  {activeNode.clusterLabel} · {activeNode.knowledge_unit_type} · 连接 {activeNode.degree} 个邻居
                </p>
              </div>

              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
                <div className="rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900/70">
                  <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">Cluster</p>
                  <p className="mt-1 text-sm text-slate-800 dark:text-slate-200">{activeNode.clusterLabel}</p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900/70">
                  <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">Confidence</p>
                  <p className="mt-1 text-sm text-slate-800 dark:text-slate-200">{Math.round(activeNode.confidence * 100)}%</p>
                </div>
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900/70">
                <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
                  <Sparkles className="h-3.5 w-3.5 text-sky-600" />
                  <p className="text-sm font-medium">邻域说明</p>
                </div>
                <p className="mt-2 text-xs leading-6 text-slate-600 dark:text-slate-400">
                  当前高亮了与这个节点直接相连的知识点，方便快速判断它是主题骨架、概念补充还是方法支点。
                </p>
              </div>
            </div>
          ) : (
            <div className="mt-4 rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-center dark:border-slate-800 dark:bg-slate-900/70">
              <p className="text-sm font-medium text-slate-700 dark:text-slate-200">点击任意节点开始聚焦</p>
              <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">这里会显示节点所属团簇、连接度和学习提示。</p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

export default SemanticUniverse;
