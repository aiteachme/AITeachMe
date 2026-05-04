import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

import { relationTone, truncateGraphLabel } from "../knowledgeGraphVisual";
import type { GraphInsightModel, NodeInsight } from "./insightsCore";
import {
  LEARNING_LAYERS,
  nodeStyle,
  nodeTypeLabel,
  percentText,
  relationLabel,
} from "./insightsCore";
import { CategoryBar, ChartPanel } from "./sharedPrimitives";

type MapNode = NodeInsight & {
  type: string;
  x: number;
  y: number;
  r: number;
  color: string;
  soft: string;
  dark: string;
  labelSide: 1 | -1;
  labelVisible: boolean;
  rankInLayer: number;
};

type MapEdge = {
  id: number;
  source: MapNode;
  target: MapNode;
  relationType: string;
  color: string;
  confidence: number;
  width: number;
  score: number;
};

const MAP_WIDTH = 1180;
const MAP_HEIGHT = 680;
const MAP_TOP = 92;
const MAP_BOTTOM = 565;
const LAYER_X = [86, 330, 574, 818, 1062];
const LABEL_BUDGET_BY_LAYER = [7, 11, 9, 9, 8];
const BACKBONE_RELATIONS = new Set(["prerequisite", "contains", "reasoning", "application", "training"]);

function labelWidth(text: string): number {
  let width = 0;
  for (const char of text) {
    width += /[\u4e00-\u9fff]/.test(char) ? 12 : 7;
  }
  return Math.min(188, Math.max(58, width + 22));
}

function edgeScore(relationType: string, source: NodeInsight, target: NodeInsight, confidence: number): number {
  return (
    confidence * 2.4 +
    Math.sqrt(source.degree + target.degree + 1) * 0.45 +
    (BACKBONE_RELATIONS.has(relationType) ? 1.1 : 0) +
    (source.layer !== target.layer ? 0.45 : 0)
  );
}

function buildReadableMap(model: GraphInsightModel): { nodes: MapNode[]; edges: MapEdge[] } {
  const buckets = LEARNING_LAYERS.map(() => [] as NodeInsight[]);
  for (const node of model.nodes) {
    buckets[Math.max(0, Math.min(LEARNING_LAYERS.length - 1, node.layer))]?.push(node);
  }

  const nodes: MapNode[] = [];
  buckets.forEach((bucket, layer) => {
    const sorted = [...bucket].sort((left, right) => {
      return right.impactScore - left.impactScore || right.degree - left.degree || left.id - right.id;
    });
    const rowCount = Math.min(sorted.length, 18);
    const laneHeight = MAP_BOTTOM - MAP_TOP;
    const x = LAYER_X[layer] ?? LAYER_X[2];
    const side: 1 | -1 = layer >= 3 ? -1 : 1;
    const labelBudget = LABEL_BUDGET_BY_LAYER[layer] ?? 8;

    sorted.forEach((node, index) => {
      const type = String(node.knowledge_unit_type || "other");
      const style = nodeStyle(type);
      const isCompact = index >= rowCount;
      const compactIndex = Math.max(0, index - rowCount);
      const compactColumn = compactIndex % 4;
      const compactRow = Math.floor(compactIndex / 4);
      const compactYOffset = 18 + (compactRow % 10) * 22;
      const rankRatio = rowCount > 1 ? index / (rowCount - 1) : 0.5;
      const y = isCompact
        ? MAP_TOP + compactYOffset + ((compactIndex * 17) % 15)
        : MAP_TOP + rankRatio * laneHeight;
      const xOffset = isCompact ? side * (58 + compactColumn * 15) : (index % 3 - 1) * 8;
      const degreeRadius = Math.sqrt(Math.max(1, node.degree)) * 1.5;
      const isHighSignal = index < labelBudget || node.degree >= 5 || node.issueScore >= 2.8;

      nodes.push({
        ...node,
        type,
        x: x + xOffset,
        y,
        r: Math.min(13.5, isCompact ? 4.5 + degreeRadius * 0.45 : 6.8 + degreeRadius),
        color: style.fill,
        soft: style.soft,
        dark: style.dark,
        labelSide: side,
        labelVisible: !isCompact && isHighSignal,
        rankInLayer: index,
      });
    });
  });

  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const edges = model.edges
    .map((edge) => {
      const source = nodeMap.get(edge.source_node_id);
      const target = nodeMap.get(edge.target_node_id);
      if (!source || !target) return null;
      const relationType = String(edge.edge_type || "related");
      const confidence = Math.max(0, Math.min(1, Number(edge.confidence || 0)));
      const score = edgeScore(relationType, source, target, confidence);
      return {
        id: edge.id,
        source,
        target,
        relationType,
        color: relationTone(relationType),
        confidence,
        width: Math.max(0.9, 0.7 + confidence * 1.3 + (BACKBONE_RELATIONS.has(relationType) ? 0.4 : 0)),
        score,
      };
    })
    .filter((edge): edge is MapEdge => Boolean(edge))
    .sort((left, right) => right.score - left.score);

  return { nodes, edges };
}

function mapEdgePath(edge: MapEdge): string {
  const { source, target } = edge;
  if (source.layer === target.layer) {
    const direction = source.y <= target.y ? -1 : 1;
    const bend = Math.min(92, Math.max(42, Math.abs(target.y - source.y) * 0.42));
    const controlX = source.x + source.labelSide * (58 + bend * 0.25);
    const controlY = (source.y + target.y) / 2 + direction * 34;
    return `M ${source.x.toFixed(1)} ${source.y.toFixed(1)} Q ${controlX.toFixed(1)} ${controlY.toFixed(1)} ${target.x.toFixed(1)} ${target.y.toFixed(1)}`;
  }
  const dx = target.x - source.x;
  const bend = Math.min(120, Math.max(64, Math.abs(dx) * 0.34));
  const verticalShift = ((edge.id % 7) - 3) * 8;
  return `M ${source.x.toFixed(1)} ${source.y.toFixed(1)} C ${(source.x + Math.sign(dx || 1) * bend).toFixed(1)} ${(source.y + verticalShift).toFixed(1)} ${(target.x - Math.sign(dx || 1) * bend).toFixed(1)} ${(target.y - verticalShift).toFixed(1)} ${target.x.toFixed(1)} ${target.y.toFixed(1)}`;
}

function NodeLabel({ node, active }: { node: MapNode; active: boolean }) {
  const text = truncateGraphLabel(node.canonical_name, active ? 22 : 14);
  const width = labelWidth(text);
  const x = node.x + node.labelSide * (node.r + 7);
  const rectX = node.labelSide === 1 ? x : x - width;
  const textX = node.labelSide === 1 ? x + 10 : x - 10;
  return (
    <g>
      <rect
        x={rectX}
        y={node.y - 13}
        width={width}
        height={26}
        rx={7}
        fill={active ? "#0f172a" : "#ffffff"}
        stroke={active ? "#0f172a" : "#dbe3ef"}
        strokeWidth={1}
        opacity={active ? 0.96 : 0.9}
      />
      <text
        x={textX}
        y={node.y + 4}
        textAnchor={node.labelSide === 1 ? "start" : "end"}
        className="select-none text-[11px] font-semibold"
        fill={active ? "#ffffff" : "#1e293b"}
      >
        {text}
      </text>
    </g>
  );
}

function NodeDetail({
  node,
  edges,
  onSelect,
}: {
  node: MapNode | null;
  edges: MapEdge[];
  onSelect: (id: number) => void;
}) {
  if (!node) return null;
  const connected = edges
    .filter((edge) => edge.source.id === node.id || edge.target.id === node.id)
    .sort((left, right) => right.score - left.score)
    .slice(0, 8);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-950">
      <div className="flex items-start gap-3">
        <span className="mt-1 h-3 w-3 shrink-0 rounded-full" style={{ backgroundColor: node.color }} />
        <div className="min-w-0">
          <p className="text-sm font-semibold leading-5 text-slate-950 dark:text-slate-50">{node.canonical_name}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <span className="rounded-full px-2 py-0.5 text-[11px] font-medium" style={{ backgroundColor: node.soft, color: node.dark }}>
              {nodeTypeLabel(node.type)}
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              连接 {node.degree}
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              置信 {percentText(Number(node.confidence || 0))}
            </span>
          </div>
        </div>
      </div>
      {node.issueReasons.length ? (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
          <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />
          {node.issueReasons.join(" / ")}
        </div>
      ) : (
        <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs leading-5 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200">
          <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" />
          这个知识点已经接入当前图谱主干。
        </div>
      )}
      <div className="mt-4">
        <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">直接关系</p>
        <div className="mt-2 grid gap-2">
          {connected.length ? (
            connected.map((edge) => {
              const next = edge.source.id === node.id ? edge.target : edge.source;
              const outgoing = edge.source.id === node.id;
              return (
                <button
                  key={edge.id}
                  type="button"
                  onClick={() => onSelect(next.id)}
                  className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-left transition-colors hover:border-slate-300 hover:bg-white dark:border-slate-800 dark:bg-slate-900/70 dark:hover:border-slate-700 dark:hover:bg-slate-900"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="min-w-0 truncate text-xs font-semibold text-slate-800 dark:text-slate-100">
                      {outgoing ? "指向" : "来自"}：{truncateGraphLabel(next.canonical_name, 18)}
                    </span>
                    <span className="h-2 w-8 shrink-0 rounded-full" style={{ backgroundColor: edge.color }} />
                  </div>
                  <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                    {relationLabel(edge.relationType)} · 置信 {percentText(edge.confidence)}
                  </p>
                </button>
              );
            })
          ) : (
            <div className="rounded-lg border border-dashed border-slate-200 px-3 py-6 text-center text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
              暂无直接关系。
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function ReadableMapView({ model }: { model: GraphInsightModel }) {
  const layout = useMemo(() => buildReadableMap(model), [model]);
  const [selectedId, setSelectedId] = useState<number | null>(model.bottleneckNodes[0]?.id ?? null);
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const activeId = hoveredId ?? selectedId;
  const activeNode = activeId ? layout.nodes.find((node) => node.id === activeId) ?? null : null;
  const baseEdgeIds = useMemo(() => {
    const budget = Math.min(layout.edges.length, Math.max(18, Math.min(62, Math.round(model.nodeCount * 0.58))));
    return new Set(layout.edges.slice(0, budget).map((edge) => edge.id));
  }, [layout.edges, model.nodeCount]);

  const visibleEdges = useMemo(() => {
    if (!activeId) return layout.edges.filter((edge) => baseEdgeIds.has(edge.id));
    return layout.edges.filter(
      (edge) => baseEdgeIds.has(edge.id) || edge.source.id === activeId || edge.target.id === activeId,
    );
  }, [activeId, baseEdgeIds, layout.edges]);

  const connectedIds = useMemo(() => {
    if (!activeId) return new Set<number>();
    const ids = new Set<number>([activeId]);
    for (const edge of layout.edges) {
      if (edge.source.id === activeId) ids.add(edge.target.id);
      if (edge.target.id === activeId) ids.add(edge.source.id);
    }
    return ids;
  }, [activeId, layout.edges]);

  const relationSegments = model.relationItems.slice(0, 7).map((relation) => ({
    key: relation.type,
    label: relation.label,
    color: relation.color,
    count: relation.count,
  }));

  const toggleSelected = (nodeId: number) => {
    setSelectedId((current) => (current === nodeId ? null : nodeId));
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
      <ChartPanel
        title="学习路径地图"
        meta={`${model.nodeCount} 节点 · 显示 ${visibleEdges.length}/${model.edgeCount} 关系`}
        description="按组织、知识、原理、方法、训练展开；节点越大连接越多，默认先呈现主干关系。"
        className="min-h-[740px]"
      >
        <div className="relative overflow-x-auto bg-[#f8fafc] dark:bg-slate-950">
          <svg
            viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`}
            className="h-[720px] min-w-[1080px] w-full"
            role="img"
            aria-label="可读知识图谱地图"
          >
            <defs>
              <marker id="kg-readable-arrow" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" opacity="0.72" />
              </marker>
              <filter id="kg-readable-shadow" x="-30%" y="-30%" width="160%" height="160%">
                <feDropShadow dx="0" dy="4" stdDeviation="5" floodColor="#64748b" floodOpacity="0.16" />
              </filter>
            </defs>
            <rect width={MAP_WIDTH} height={MAP_HEIGHT} fill="transparent" />
            {LEARNING_LAYERS.map((layer, index) => {
              const x = LAYER_X[index] ?? 0;
              return (
                <g key={layer.label}>
                  <rect
                    x={x - 72}
                    y={44}
                    width={144}
                    height={560}
                    rx={22}
                    fill={layer.color}
                    opacity={0.055}
                    stroke={layer.color}
                    strokeDasharray="4 8"
                    strokeOpacity={0.18}
                  />
                  <text x={x} y={34} textAnchor="middle" className="select-none text-[13px] font-bold" fill="#0f172a">
                    {layer.label}
                  </text>
                  <text x={x} y={54} textAnchor="middle" className="select-none text-[10px]" fill="#64748b">
                    {layer.description}
                  </text>
                </g>
              );
            })}

            <g>
              {visibleEdges.map((edge) => {
                const active = activeId && (edge.source.id === activeId || edge.target.id === activeId);
                const related = activeId ? active : true;
                const isBackbone = baseEdgeIds.has(edge.id);
                return (
                  <path
                    key={edge.id}
                    d={mapEdgePath(edge)}
                    fill="none"
                    stroke={edge.color}
                    strokeWidth={active ? edge.width + 1.2 : edge.width}
                    strokeOpacity={active ? 0.88 : related && isBackbone ? 0.3 + edge.confidence * 0.34 : 0.075}
                    markerEnd={edge.source.layer === edge.target.layer ? undefined : "url(#kg-readable-arrow)"}
                  />
                );
              })}
            </g>

            <g>
              {layout.nodes.map((node) => {
                const active = activeId === node.id;
                const related = activeId ? connectedIds.has(node.id) : true;
                const showLabel = active || node.labelVisible || (activeId && related && node.degree >= 2);
                return (
                  <g
                    key={node.id}
                    role="button"
                    tabIndex={0}
                    aria-label={node.canonical_name}
                    className="cursor-pointer outline-none"
                    onMouseEnter={() => setHoveredId(node.id)}
                    onMouseLeave={() => setHoveredId(null)}
                    onClick={() => toggleSelected(node.id)}
                    onKeyDown={(event) => {
                      if (event.key !== "Enter" && event.key !== " ") return;
                      event.preventDefault();
                      toggleSelected(node.id);
                    }}
                  >
                    {showLabel ? <NodeLabel node={node} active={active} /> : null}
                    <circle
                      cx={node.x}
                      cy={node.y}
                      r={node.r + (active ? 4 : 0)}
                      fill={active ? "#ffffff" : node.soft}
                      stroke={active ? "#0f172a" : "#ffffff"}
                      strokeWidth={active ? 3 : 2}
                      opacity={related ? 1 : 0.2}
                      filter={active ? "url(#kg-readable-shadow)" : undefined}
                    />
                    <circle
                      cx={node.x}
                      cy={node.y}
                      r={node.r}
                      fill={node.color}
                      opacity={related ? 0.95 : 0.2}
                    />
                    {node.issueReasons.length ? (
                      <circle cx={node.x + node.r * 0.6} cy={node.y - node.r * 0.65} r="3.2" fill="#f59e0b" stroke="#fff" />
                    ) : null}
                    <title>
                      {node.canonical_name} · {nodeTypeLabel(node.type)} · 连接 {node.degree}
                    </title>
                  </g>
                );
              })}
            </g>
          </svg>
        </div>
      </ChartPanel>

      <div className="grid content-start gap-4">
        <NodeDetail node={activeNode} edges={layout.edges} onSelect={setSelectedId} />
        <ChartPanel title="知识类型">
          <div className="grid gap-2 p-4">
            {model.typeItems.map((item) => (
              <button
                key={item.type}
                type="button"
                className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-left text-xs dark:bg-slate-900/70"
                onClick={() => {
                  const first = layout.nodes.find((node) => node.type === item.type);
                  if (first) setSelectedId(first.id);
                }}
              >
                <span className="flex items-center gap-2 font-medium text-slate-700 dark:text-slate-200">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                  {item.label}
                </span>
                <span className="font-semibold tabular-nums text-slate-500 dark:text-slate-400">{item.count}</span>
              </button>
            ))}
          </div>
        </ChartPanel>
        <ChartPanel title="关系类型">
          <div className="p-4">
            <CategoryBar segments={relationSegments} height={10} />
          </div>
        </ChartPanel>
        <ChartPanel title="主干入口">
          <div className="grid gap-2 p-4">
            {model.bottleneckNodes.slice(0, 5).map((node, index) => {
              const style = nodeStyle(String(node.knowledge_unit_type || "other"));
              return (
                <button
                  key={node.id}
                  type="button"
                  onClick={() => setSelectedId(node.id)}
                  className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-left transition-colors hover:border-slate-300 hover:bg-white dark:border-slate-800 dark:bg-slate-900/70 dark:hover:border-slate-700"
                >
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-white text-[11px] font-semibold tabular-nums text-slate-500 ring-1 ring-slate-200 dark:bg-slate-950 dark:ring-slate-800">
                    {index + 1}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-semibold text-slate-800 dark:text-slate-100">
                      {node.canonical_name}
                    </span>
                    <span className="mt-0.5 flex items-center gap-1 text-[11px] text-slate-500 dark:text-slate-400">
                      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: style.fill }} />
                      连接 {node.degree}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </ChartPanel>
      </div>
    </div>
  );
}
