import { useMemo, useState } from "react";

import type { GraphInsightModel, NodeInsight } from "./insightsCore";
import {
  LEARNING_LAYERS,
  nodeStyle,
  percentText,
  relationLabel,
} from "./insightsCore";
import { ChartPanel, CategoryBar } from "./sharedPrimitives";
import { relationTone, truncateGraphLabel } from "../knowledgeGraphVisual";

type ArcNode = NodeInsight & {
  x: number;
  layerIndex: number;
  insideLayerOrder: number;
};

type ArcEdge = {
  id: number;
  source: ArcNode;
  target: ArcNode;
  edgeType: string;
  color: string;
  isPeer: boolean;
  width: number;
  opacity: number;
};

type LayerSummary = {
  index: number;
  label: string;
  description: string;
  color: string;
  nodeCount: number;
  edgeCount: number;
  density: number;
  startX: number;
  endX: number;
  topRelations: Array<{ type: string; label: string; color: string; count: number }>;
};

function buildArcLayout(model: GraphInsightModel, width: number, padding: number): {
  nodes: ArcNode[];
  edges: ArcEdge[];
  layers: LayerSummary[];
} {
  const layerBuckets = LEARNING_LAYERS.map(() => [] as NodeInsight[]);
  for (const node of model.nodes) {
    layerBuckets[node.layer]?.push(node);
  }

  // Sort each layer by degree desc, then impactScore.
  for (const bucket of layerBuckets) {
    bucket.sort((left, right) => right.degree - left.degree || right.impactScore - left.impactScore || left.id - right.id);
  }

  const totalNodes = layerBuckets.reduce((sum, bucket) => sum + bucket.length, 0);
  const innerWidth = width - padding * 2;
  const layerGap = 18;
  const totalGapWidth = layerGap * (LEARNING_LAYERS.length - 1);
  const usableWidth = Math.max(1, innerWidth - totalGapWidth);
  const xPerNode = usableWidth / Math.max(1, totalNodes);

  const arcNodes: ArcNode[] = [];
  const layers: LayerSummary[] = [];
  let cursorX = padding;

  layerBuckets.forEach((bucket, layerIndex) => {
    const layerInfo = LEARNING_LAYERS[layerIndex];
    const startX = cursorX;
    if (bucket.length === 0) {
      layers.push({
        index: layerIndex,
        label: layerInfo.label,
        description: layerInfo.description,
        color: layerInfo.color,
        nodeCount: 0,
        edgeCount: 0,
        density: 0,
        startX,
        endX: startX,
        topRelations: [],
      });
      return;
    }
    bucket.forEach((node, insideIndex) => {
      const x = cursorX + insideIndex * xPerNode + xPerNode / 2;
      arcNodes.push({
        ...node,
        x,
        layerIndex,
        insideLayerOrder: insideIndex,
      });
    });
    const layerWidth = bucket.length * xPerNode;
    cursorX += layerWidth + layerGap;
    layers.push({
      index: layerIndex,
      label: layerInfo.label,
      description: layerInfo.description,
      color: layerInfo.color,
      nodeCount: bucket.length,
      edgeCount: 0,
      density: 0,
      startX,
      endX: cursorX - layerGap,
      topRelations: [],
    });
  });

  const nodeMap = new Map<number, ArcNode>(arcNodes.map((node) => [node.id, node]));
  const layerRelationCounts = LEARNING_LAYERS.map(() => new Map<string, number>());
  const arcEdges: ArcEdge[] = [];

  for (const edge of model.edges) {
    const source = nodeMap.get(edge.source_node_id);
    const target = nodeMap.get(edge.target_node_id);
    if (!source || !target) continue;
    const isPeer = source.layerIndex === target.layerIndex;
    const edgeType = String(edge.edge_type || "related");
    if (isPeer) {
      const layerMap = layerRelationCounts[source.layerIndex];
      layerMap.set(edgeType, (layerMap.get(edgeType) ?? 0) + 1);
      const summary = layers[source.layerIndex];
      summary.edgeCount += 1;
    }
    const confidence = Math.max(0, Math.min(1, Number(edge.confidence || 0)));
    arcEdges.push({
      id: edge.id,
      source,
      target,
      edgeType,
      color: relationTone(edgeType),
      isPeer,
      width: Math.max(0.7, 0.7 + confidence * 1.6 + Math.max(0, Number(edge.weight || 0)) * 0.4),
      opacity: isPeer ? 0.32 + confidence * 0.42 : 0.12 + confidence * 0.18,
    });
  }

  for (const layer of layers) {
    const possible = layer.nodeCount > 1 ? (layer.nodeCount * (layer.nodeCount - 1)) / 2 : 0;
    layer.density = possible ? Math.min(1, layer.edgeCount / possible) : 0;
    layer.topRelations = Array.from(layerRelationCounts[layer.index].entries())
      .map(([type, count]) => ({ type, label: relationLabel(type), color: relationTone(type), count }))
      .sort((left, right) => right.count - left.count)
      .slice(0, 4);
  }

  // Sort edges: cross-layer first (drawn lighter underneath), peer last (highlighted).
  arcEdges.sort((left, right) => {
    if (left.isPeer === right.isPeer) return left.opacity - right.opacity;
    return left.isPeer ? 1 : -1;
  });

  return { nodes: arcNodes, edges: arcEdges, layers };
}

function arcPath(source: ArcNode, target: ArcNode, baseY: number, isPeer: boolean): string {
  const distance = Math.abs(target.x - source.x);
  const radius = Math.max(12, distance / 2);
  const sweepUp = isPeer;
  const arcHeight = sweepUp ? Math.min(220, radius * 0.9) : Math.min(80, radius * 0.45);
  const cy = sweepUp ? baseY - arcHeight : baseY + arcHeight;
  const midX = (source.x + target.x) / 2;
  return `M ${source.x.toFixed(1)} ${baseY} Q ${midX.toFixed(1)} ${cy.toFixed(1)} ${target.x.toFixed(1)} ${baseY}`;
}

export function PeerArcView({ model }: { model: GraphInsightModel }) {
  const width = 1180;
  const padding = 30;
  const baseY = 280;
  const layout = useMemo(() => buildArcLayout(model, width, padding), [model]);
  const [hovered, setHovered] = useState<ArcNode | null>(null);
  const peerEdgeCount = useMemo(() => layout.edges.filter((edge) => edge.isPeer).length, [layout.edges]);
  const crossEdgeCount = layout.edges.length - peerEdgeCount;

  const adjacency = useMemo(() => {
    const map = new Map<number, Set<number>>();
    for (const edge of layout.edges) {
      const sourceSet = map.get(edge.source.id) ?? new Set<number>();
      sourceSet.add(edge.target.id);
      map.set(edge.source.id, sourceSet);
      const targetSet = map.get(edge.target.id) ?? new Set<number>();
      targetSet.add(edge.source.id);
      map.set(edge.target.id, targetSet);
    }
    return map;
  }, [layout.edges]);

  const highlightSet = useMemo(() => {
    if (!hovered) return new Set<number>();
    const set = new Set<number>([hovered.id]);
    for (const id of adjacency.get(hovered.id) ?? []) set.add(id);
    return set;
  }, [adjacency, hovered]);

  const peerRelationLegend = useMemo(() => {
    const map = new Map<string, { type: string; label: string; color: string; count: number }>();
    for (const edge of layout.edges) {
      if (!edge.isPeer) continue;
      const existing = map.get(edge.edgeType) ?? {
        type: edge.edgeType,
        label: relationLabel(edge.edgeType),
        color: edge.color,
        count: 0,
      };
      existing.count += 1;
      map.set(edge.edgeType, existing);
    }
    return Array.from(map.values()).sort((left, right) => right.count - left.count);
  }, [layout.edges]);

  const denseLayer = useMemo(() => {
    return layout.layers
      .filter((layer) => layer.nodeCount > 1)
      .sort((left, right) => right.density - left.density)[0] ?? null;
  }, [layout.layers]);
  const sparseLayer = useMemo(() => {
    return layout.layers
      .filter((layer) => layer.nodeCount > 1)
      .sort((left, right) => left.density - right.density)[0] ?? null;
  }, [layout.layers]);

  return (
    <div className="grid gap-4">
      <ChartPanel
        title="阶段弧线网络"
        meta={`${peerEdgeCount} 条同级 · ${crossEdgeCount} 条跨层`}
        description="所有节点按学习阶段一字排开，弧线连接同层关系；弧高代表连接跨度，颜色代表关系类型。一眼看清哪一层内部讨论得更密。"
      >
        <div className="relative h-[580px] bg-gradient-to-b from-slate-50 via-white to-slate-50 dark:from-slate-950 dark:via-slate-950 dark:to-slate-900">
          <svg
            viewBox={`0 0 ${width} 580`}
            className="h-full w-full"
            role="img"
            aria-label="阶段弧线网络图"
          >
            <defs>
              <linearGradient id="peer-bg-gradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#ffffff" stopOpacity="0" />
                <stop offset="60%" stopColor="#e2e8f0" stopOpacity="0.4" />
                <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
              </linearGradient>
              <filter id="peer-glow" x="-30%" y="-30%" width="160%" height="160%">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>

            {/* Layer bands */}
            {layout.layers.map((layer) => (
              <g key={`band-${layer.index}`}>
                <rect
                  x={layer.startX - 6}
                  y={baseY - 4}
                  width={Math.max(20, layer.endX - layer.startX + 12)}
                  height={20}
                  fill={layer.color}
                  opacity="0.18"
                  rx="6"
                />
                <text
                  x={(layer.startX + layer.endX) / 2}
                  y={baseY + 60}
                  textAnchor="middle"
                  fontSize="13"
                  fontWeight="700"
                  fill={layer.color}
                >
                  {layer.label}
                </text>
                <text
                  x={(layer.startX + layer.endX) / 2}
                  y={baseY + 78}
                  textAnchor="middle"
                  fontSize="10.5"
                  fill="#64748b"
                >
                  {layer.nodeCount} 节点 · 同级 {layer.edgeCount} · 密度 {percentText(layer.density)}
                </text>
              </g>
            ))}

            {/* Density bar per layer */}
            {layout.layers.map((layer) => {
              const maxDensity = Math.max(0.001, ...layout.layers.map((item) => item.density));
              const barHeight = Math.max(2, Math.min(50, (layer.density / maxDensity) * 50));
              return (
                <g key={`density-${layer.index}`}>
                  <rect
                    x={(layer.startX + layer.endX) / 2 - 18}
                    y={baseY + 100 - barHeight}
                    width="36"
                    height={barHeight}
                    rx="3"
                    fill={layer.color}
                    opacity="0.78"
                  />
                </g>
              );
            })}

            {/* Cross-layer arcs (below baseline) */}
            <g>
              {layout.edges
                .filter((edge) => !edge.isPeer)
                .map((edge) => {
                  const isHighlighted =
                    hovered &&
                    (edge.source.id === hovered.id || edge.target.id === hovered.id);
                  const dimmed = hovered && !isHighlighted;
                  return (
                    <path
                      key={`cross-${edge.id}`}
                      d={arcPath(edge.source, edge.target, baseY, false)}
                      fill="none"
                      stroke={edge.color}
                      strokeWidth={isHighlighted ? edge.width * 1.4 : edge.width}
                      strokeOpacity={dimmed ? 0.04 : isHighlighted ? 0.7 : edge.opacity}
                      strokeLinecap="round"
                    />
                  );
                })}
            </g>

            {/* Peer arcs (above baseline) — Gephi classic */}
            <g>
              {layout.edges
                .filter((edge) => edge.isPeer)
                .map((edge) => {
                  const isHighlighted =
                    hovered &&
                    (edge.source.id === hovered.id || edge.target.id === hovered.id);
                  const dimmed = hovered && !isHighlighted;
                  return (
                    <path
                      key={`peer-${edge.id}`}
                      d={arcPath(edge.source, edge.target, baseY, true)}
                      fill="none"
                      stroke={edge.color}
                      strokeWidth={isHighlighted ? edge.width * 1.6 + 0.5 : edge.width}
                      strokeOpacity={dimmed ? 0.06 : isHighlighted ? 0.9 : edge.opacity}
                      strokeLinecap="round"
                      filter={isHighlighted ? "url(#peer-glow)" : undefined}
                    />
                  );
                })}
            </g>

            {/* Nodes */}
            <g>
              {layout.nodes.map((node) => {
                const style = nodeStyle(String(node.knowledge_unit_type || ""));
                const isHovered = hovered?.id === node.id;
                const isAdj = highlightSet.has(node.id);
                const dimmed = hovered && !isAdj;
                const radius = 3.5 + Math.min(7.5, Math.sqrt(node.degree) * 1.3);
                return (
                  <g
                    key={`node-${node.id}`}
                    onMouseEnter={() => setHovered(node)}
                    onMouseLeave={() => setHovered(null)}
                    style={{ cursor: "pointer" }}
                  >
                    <circle
                      cx={node.x}
                      cy={baseY + 6}
                      r={radius}
                      fill={style.fill}
                      stroke={isHovered ? "#0f172a" : "#ffffff"}
                      strokeWidth={isHovered ? 2 : 1.5}
                      opacity={dimmed ? 0.25 : 1}
                    />
                    {node.degree >= 4 || isHovered ? (
                      <circle cx={node.x} cy={baseY + 6} r={radius + 3} fill={style.fill} opacity={dimmed ? 0 : 0.18} />
                    ) : null}
                  </g>
                );
              })}
            </g>

            {/* Top node labels: top-3 by degree per layer */}
            <g>
              {layout.layers.flatMap((layer) => {
                const layerNodes = layout.nodes.filter((node) => node.layerIndex === layer.index).slice(0, 3);
                return layerNodes.map((node, idx) => (
                  <g key={`label-${node.id}`}>
                    <line
                      x1={node.x}
                      x2={node.x}
                      y1={baseY - 8}
                      y2={baseY - 24 - idx * 16}
                      stroke="#94a3b8"
                      strokeWidth="0.5"
                      strokeDasharray="2 3"
                    />
                    <text
                      x={node.x}
                      y={baseY - 28 - idx * 16}
                      textAnchor="middle"
                      fontSize="10.5"
                      fontWeight="600"
                      fill="#1e293b"
                      className="dark:fill-slate-100"
                    >
                      {truncateGraphLabel(node.canonical_name, 8)}
                    </text>
                  </g>
                ));
              })}
            </g>

            {/* Hovered label box */}
            {hovered ? (
              <g pointerEvents="none">
                <rect
                  x={Math.max(8, Math.min(width - 220, hovered.x - 100))}
                  y={baseY + 16}
                  width="200"
                  height="42"
                  rx="6"
                  fill="rgba(15, 23, 42, 0.92)"
                />
                <text
                  x={Math.max(108, Math.min(width - 120, hovered.x))}
                  y={baseY + 32}
                  textAnchor="middle"
                  fontSize="11"
                  fontWeight="700"
                  fill="#ffffff"
                >
                  {truncateGraphLabel(hovered.canonical_name, 18)}
                </text>
                <text
                  x={Math.max(108, Math.min(width - 120, hovered.x))}
                  y={baseY + 49}
                  textAnchor="middle"
                  fontSize="10"
                  fill="#cbd5e1"
                >
                  连接 {hovered.degree} · 置信 {percentText(Number(hovered.confidence || 0))}
                </text>
              </g>
            ) : null}
          </svg>
        </div>
      </ChartPanel>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <ChartPanel
          title="同级密度对比"
          description="每层内部「知识—知识」互联强度。密度高的层更适合做对比、辨析；密度低的层往往是讲完概念就走。"
        >
          <div className="grid gap-3 p-4">
            {layout.layers.map((layer) => {
              const maxDensity = Math.max(0.001, ...layout.layers.map((item) => item.density));
              return (
                <div key={`density-row-${layer.index}`}>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="flex items-center gap-2 text-slate-700 dark:text-slate-200">
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: layer.color }} />
                      <strong>{layer.label}</strong>
                      <span className="text-slate-400">{layer.nodeCount} 节点</span>
                    </span>
                    <span className="font-semibold tabular-nums text-slate-500 dark:text-slate-400">
                      {layer.edgeCount} · {percentText(layer.density)}
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                    <div
                      className="h-full"
                      style={{
                        width: `${Math.max(2, (layer.density / maxDensity) * 100)}%`,
                        backgroundColor: layer.color,
                      }}
                    />
                  </div>
                </div>
              );
            })}
            <p className="mt-1 text-[11px] leading-4 text-slate-500 dark:text-slate-400">
              {denseLayer ? (
                <>
                  最密集是 <strong className="text-slate-700 dark:text-slate-200">{denseLayer.label}</strong>
                  （密度 {percentText(denseLayer.density)}），适合做对比训练。
                </>
              ) : null}
              {sparseLayer && denseLayer && sparseLayer.index !== denseLayer.index ? (
                <>
                  {" "}最稀的是 <strong className="text-slate-700 dark:text-slate-200">{sparseLayer.label}</strong>
                  （{percentText(sparseLayer.density)}），可能缺少同级解释或练习。
                </>
              ) : null}
            </p>
          </div>
        </ChartPanel>

        <ChartPanel
          title="同级关系成分"
          description="同一阶段的连接主要是「说明 / 应用 / 训练」还是「对比 / 相似」——决定了这层适合用什么学习方式。"
        >
          <div className="p-4">
            <CategoryBar
              segments={peerRelationLegend.map((relation) => ({
                key: relation.type,
                label: relation.label,
                color: relation.color,
                count: relation.count,
              }))}
            />
            <div className="mt-3 grid gap-2">
              {peerRelationLegend.slice(0, 4).map((relation) => (
                <div key={relation.type} className="flex items-center justify-between rounded-md bg-slate-50 px-2.5 py-1.5 text-xs dark:bg-slate-900/60">
                  <span className="flex items-center gap-2 text-slate-700 dark:text-slate-200">
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: relation.color }} />
                    {relation.label}
                  </span>
                  <span className="font-semibold tabular-nums text-slate-500 dark:text-slate-400">
                    {relation.count}
                  </span>
                </div>
              ))}
              {peerRelationLegend.length === 0 ? (
                <p className="rounded-md border border-dashed border-slate-200 px-3 py-3 text-center text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
                  当前没有同级关系。建议在文档中补充对比、相似、说明等横向关系。
                </p>
              ) : null}
            </div>
          </div>
        </ChartPanel>

        <ChartPanel
          title="跨层 vs 同级"
          description="跨层关系搭路径，同级关系搭辨析；两者都需要。"
        >
          <div className="p-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-center dark:border-slate-800 dark:bg-slate-900/60">
                <p className="text-[11px] text-slate-500 dark:text-slate-400">跨层关系</p>
                <p className="mt-1 text-2xl font-bold tabular-nums text-slate-900 dark:text-slate-100">{crossEdgeCount}</p>
                <p className="mt-1 text-[10.5px] text-slate-500 dark:text-slate-400">学习路径主干</p>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-center dark:border-slate-800 dark:bg-slate-900/60">
                <p className="text-[11px] text-slate-500 dark:text-slate-400">同级关系</p>
                <p className="mt-1 text-2xl font-bold tabular-nums text-slate-900 dark:text-slate-100">{peerEdgeCount}</p>
                <p className="mt-1 text-[10.5px] text-slate-500 dark:text-slate-400">辨析与对比</p>
              </div>
            </div>
            <div className="mt-3 flex h-3 overflow-hidden rounded-full">
              <div
                className="bg-blue-500"
                style={{ width: `${Math.round((crossEdgeCount / Math.max(1, layout.edges.length)) * 100)}%` }}
                title={`跨层 ${crossEdgeCount}`}
              />
              <div
                className="bg-emerald-500"
                style={{ width: `${Math.round((peerEdgeCount / Math.max(1, layout.edges.length)) * 100)}%` }}
                title={`同级 ${peerEdgeCount}`}
              />
            </div>
            <p className="mt-3 text-[11px] leading-4 text-slate-500 dark:text-slate-400">
              {peerEdgeCount === 0
                ? "几乎没有同级关系，说明图谱只在搭路径，没有横向网络。"
                : crossEdgeCount === 0
                  ? "缺少跨层路径，建议在前置/包含/应用上补连接。"
                  : crossEdgeCount > peerEdgeCount * 3
                    ? "跨层路径很丰富，同级辨析较少，可补一些对比/相似关系做辨析训练。"
                    : "跨层与同级比例较均衡，可同时做学习路径与对比辨析。"}
            </p>
          </div>
        </ChartPanel>
      </div>
    </div>
  );
}
