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
import { CategoryBar } from "./sharedPrimitives";

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

const MAP_WIDTH = 1500;
const MAP_HEIGHT = 560;
const MAP_TOP = 82;
const MAP_BOTTOM = 498;
const LAYER_X = [160, 455, 750, 1045, 1340];
const LABEL_BUDGET_BY_LAYER = [3, 6, 4, 5, 3];
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
    const rowCount = Math.min(sorted.length, 14);
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
      const compactYOffset = 12 + (compactRow % 12) * 20;
      const rankRatio = rowCount > 1 ? index / (rowCount - 1) : 0.5;
      const y = isCompact
        ? MAP_TOP + compactYOffset + ((compactIndex * 17) % 15)
        : MAP_TOP + rankRatio * laneHeight;
      const xOffset = isCompact ? side * (54 + compactColumn * 13) : (index % 3 - 1) * 8;
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
    <div className="max-h-[360px] overflow-y-auto rounded-lg border border-slate-200/80 bg-white/96 p-3 shadow-lg shadow-slate-900/5 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
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
          已接入主干。
        </div>
      )}
      <div className="mt-4">
        <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">关系</p>
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
                  className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-left transition-colors hover:border-slate-300 hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:border-slate-800 dark:bg-slate-900/70 dark:hover:border-slate-700 dark:hover:bg-slate-900"
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

function MapMetric({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string | number;
  tone?: "good" | "warn" | "bad" | "neutral";
}) {
  const toneClass =
    tone === "good"
      ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200"
      : tone === "warn"
        ? "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200"
        : tone === "bad"
          ? "border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200"
          : "border-slate-200 bg-white text-slate-700 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200";

  return (
    <div className={`min-w-0 rounded-md border px-3 py-2 shadow-sm ${toneClass}`}>
      <p className="truncate text-[11px] opacity-75">{label}</p>
      <p className="mt-1 truncate text-base font-bold tabular-nums">{value}</p>
    </div>
  );
}

function OverviewPanel({
  model,
  onSelect,
}: {
  model: GraphInsightModel;
  onSelect: (id: number) => void;
}) {
  const mainIssue = model.issues[0];
  const issueIsGood = mainIssue?.tone === "good";
  const gapNodes = model.gapNodes.slice(0, 4);
  const hubNodes = model.bottleneckNodes.slice(0, 4);
  const mainlineTone = model.largestComponentPct >= 0.72 ? "good" : "warn";
  const practiceTone = model.practiceCoveragePct >= 0.64 ? "good" : "warn";
  const gapTone = model.gapNodes.length ? "warn" : "good";

  return (
    <div className="rounded-lg border border-slate-200/80 bg-white/96 p-3 shadow-lg shadow-slate-900/5 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
      <div className="mb-3 flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-slate-950 dark:text-slate-50">概览</p>
        <span className="text-[11px] tabular-nums text-slate-500">{model.nodeCount} 点</span>
      </div>
      <div className="grid gap-3">
        <div
          className={`rounded-md border px-3 py-2 ${
            issueIsGood
              ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200"
              : "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200"
          }`}
        >
          <p className="truncate text-xs font-semibold">
            {issueIsGood ? <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" /> : <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />}
            {mainIssue?.title ?? "图谱结构可用"}
          </p>
        </div>

        <div className="grid grid-cols-3 gap-2">
          <MapMetric label="主干覆盖" value={percentText(model.largestComponentPct)} tone={mainlineTone} />
          <MapMetric label="练习闭环" value={percentText(model.practiceCoveragePct)} tone={practiceTone} />
          <MapMetric label="待补断点" value={model.gapNodes.length} tone={gapTone} />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-md bg-slate-50 px-3 py-2 ring-1 ring-slate-200 dark:bg-slate-900/70 dark:ring-slate-800">
            <p className="text-[11px] text-slate-500 dark:text-slate-400">主干</p>
            <p className="mt-1 text-base font-bold tabular-nums text-slate-900 dark:text-slate-100">
              {percentText(model.largestComponentPct)}
            </p>
          </div>
          <div className="rounded-md bg-slate-50 px-3 py-2 ring-1 ring-slate-200 dark:bg-slate-900/70 dark:ring-slate-800">
            <p className="text-[11px] text-slate-500 dark:text-slate-400">练习</p>
            <p className="mt-1 text-base font-bold tabular-nums text-slate-900 dark:text-slate-100">
              {percentText(model.practiceCoveragePct)}
            </p>
          </div>
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between gap-2">
            <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">补齐</p>
            <span className="text-[11px] tabular-nums text-slate-400">{gapNodes.length} 项</span>
          </div>
          <div className="grid gap-2">
            {gapNodes.length ? (
              gapNodes.map((node) => {
                const style = nodeStyle(String(node.knowledge_unit_type || "other"));
                return (
                  <button
                    key={node.id}
                    type="button"
                    onClick={() => onSelect(node.id)}
                    className="flex items-center justify-between gap-3 rounded-md bg-slate-50 px-3 py-2 text-left ring-1 ring-slate-200 transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:bg-slate-900/70 dark:ring-slate-800 dark:hover:bg-slate-900"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-xs font-semibold text-slate-800 dark:text-slate-100">
                        {node.canonical_name}
                      </span>
                      <span className="mt-0.5 flex items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400">
                        <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: style.fill }} />
                        {node.issueReasons[0] || "待复核"}
                      </span>
                    </span>
                    <span className="shrink-0 rounded-full bg-white px-2 py-0.5 text-[11px] font-semibold tabular-nums text-slate-500 ring-1 ring-slate-200 dark:bg-slate-950 dark:ring-slate-800">
                      {node.degree}
                    </span>
                  </button>
                );
              })
            ) : (
              <div className="rounded-lg border border-dashed border-slate-200 px-3 py-4 text-center text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
                暂无明显断点。
              </div>
            )}
          </div>
        </div>

        <div>
          <p className="mb-2 text-xs font-semibold text-slate-500 dark:text-slate-400">入口</p>
          <div className="grid gap-2">
            {hubNodes.map((node, index) => (
              <button
                key={node.id}
                type="button"
                onClick={() => onSelect(node.id)}
                className="flex items-center gap-2 rounded-md bg-slate-50 px-3 py-2 text-left ring-1 ring-slate-200 transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:bg-slate-900/70 dark:ring-slate-800 dark:hover:bg-slate-900"
              >
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-white text-[11px] font-semibold tabular-nums text-slate-500 ring-1 ring-slate-200 dark:bg-slate-950 dark:ring-slate-800">
                  {index + 1}
                </span>
                <span className="min-w-0 truncate text-xs font-semibold text-slate-800 dark:text-slate-100">
                  {node.canonical_name}
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function LegendPanel({
  model,
  layout,
  relationSegments,
  onSelect,
}: {
  model: GraphInsightModel;
  layout: { nodes: MapNode[]; edges: MapEdge[] };
  relationSegments: Array<{ key: string; label: string; color: string; count: number }>;
  onSelect: (id: number) => void;
}) {
  return (
    <div className="rounded-lg border border-slate-200/80 bg-white/96 p-3 shadow-lg shadow-slate-900/5 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
      <p className="mb-2 text-sm font-semibold text-slate-950 dark:text-slate-50">图例</p>
      <div className="flex flex-wrap gap-1.5">
        {model.typeItems.slice(0, 7).map((item) => (
          <button
            key={item.type}
            type="button"
            className="flex items-center gap-1.5 rounded-full bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-600 ring-1 ring-slate-200 transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:bg-slate-900/70 dark:text-slate-300 dark:ring-slate-800 dark:hover:bg-slate-900"
            onClick={() => {
              const first = layout.nodes.find((node) => node.type === item.type);
              if (first) onSelect(first.id);
            }}
          >
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />
            {item.label}
            <span className="tabular-nums text-slate-400">{item.count}</span>
          </button>
        ))}
      </div>
      <div className="mt-3">
        <CategoryBar segments={relationSegments} height={7} showLegend={false} />
      </div>
    </div>
  );
}

export function ReadableMapView({ model }: { model: GraphInsightModel }) {
  const layout = useMemo(() => buildReadableMap(model), [model]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const activeId = hoveredId ?? selectedId;
  const activeNode = activeId ? layout.nodes.find((node) => node.id === activeId) ?? null : null;
  const baseEdgeIds = useMemo(() => {
    const budget = Math.min(layout.edges.length, Math.max(12, Math.min(34, Math.round(model.nodeCount * 0.32))));
    return new Set(layout.edges.slice(0, budget).map((edge) => edge.id));
  }, [layout.edges, model.nodeCount]);

  const visibleEdges = useMemo(() => {
    if (!activeId) return layout.edges.filter((edge) => baseEdgeIds.has(edge.id));
    const activeEdgeIds = new Set(
      layout.edges
        .filter((edge) => edge.source.id === activeId || edge.target.id === activeId)
        .slice(0, 10)
        .map((edge) => edge.id),
    );
    return layout.edges.filter(
      (edge) => baseEdgeIds.has(edge.id) || activeEdgeIds.has(edge.id),
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
  const mainIssue = model.issues[0];
  const issueIsGood = mainIssue?.tone === "good";
  const mapHealthTone = issueIsGood ? "good" : model.issues.length ? "warn" : "neutral";
  const mapSummary = [
    {
      label: "主干覆盖",
      value: percentText(model.largestComponentPct),
      tone: model.largestComponentPct >= 0.72 ? "good" : "warn",
    },
    {
      label: "练习闭环",
      value: percentText(model.practiceCoveragePct),
      tone: model.practiceCoveragePct >= 0.64 ? "good" : "warn",
    },
    {
      label: "断点",
      value: model.gapNodes.length,
      tone: model.gapNodes.length ? "warn" : "good",
    },
  ] as const;

  const toggleSelected = (nodeId: number) => {
    setSelectedId((current) => (current === nodeId ? null : nodeId));
  };

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-slate-200/80 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)] dark:border-slate-800 dark:bg-slate-950">
      <div className="shrink-0 border-b border-slate-100 px-4 py-3 dark:border-slate-800">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-950 dark:text-slate-50">学习地图</p>
            <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
              按“组织 → 知识 → 原理 → 方法 → 训练”阅读课程结构，优先看高亮断点和主干路径。
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            {mapSummary.map((item) => (
              <MapMetric key={item.label} label={item.label} value={item.value} tone={item.tone} />
            ))}
          </div>
        </div>
        <div
          className={`mt-3 rounded-md border px-3 py-2 text-xs font-medium ${
            mapHealthTone === "good"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200"
              : "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200"
          }`}
        >
          {issueIsGood ? <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" /> : <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />}
          {mainIssue?.title ?? "图谱结构可用"}
          {mainIssue?.hint ? <span className="ml-2 font-normal opacity-80">{mainIssue.hint}</span> : null}
        </div>
      </div>

      <div className="grid min-h-0 flex-1 bg-[#f8fafc] dark:bg-slate-950 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div className="relative min-h-0 overflow-hidden">
          <div className="absolute inset-0 overflow-x-auto overflow-y-hidden">
            <svg
              viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`}
              className="h-full min-w-[1120px] w-full"
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
                      x={x - 82}
                      y={54}
                      width={164}
                      height={466}
                      rx={24}
                      fill={layer.color}
                      opacity={0.055}
                      stroke={layer.color}
                      strokeDasharray="4 8"
                      strokeOpacity={0.18}
                    />
                    <text x={x} y={36} textAnchor="middle" className="select-none text-[13px] font-bold" fill="#0f172a">
                      {layer.label}
                    </text>
                    <text x={x} y={52} textAnchor="middle" className="select-none text-[10px] font-medium" fill="#64748b">
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

          {activeNode ? (
            <div className="pointer-events-auto absolute bottom-3 left-3 right-3 z-10 max-h-[44%] overflow-y-auto xl:hidden">
              <NodeDetail node={activeNode} edges={layout.edges} onSelect={setSelectedId} />
            </div>
          ) : (
            <div className="pointer-events-auto absolute bottom-3 left-3 right-3 z-10 rounded-lg border border-slate-200/80 bg-white/92 p-3 shadow-lg shadow-slate-900/5 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90 xl:hidden">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-xs font-semibold text-slate-900 dark:text-slate-100">
                    {mainIssue?.title ?? "图谱结构可用"}
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
                    点击节点查看直接关系，黄色标记表示优先复核点。
                  </p>
                </div>
                <div className="flex shrink-0 gap-1.5">
                  {mapSummary.map((item) => (
                    <span
                      key={item.label}
                      className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-semibold tabular-nums text-slate-600 dark:bg-slate-900 dark:text-slate-300"
                    >
                      {item.label} {item.value}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}

          <div className="pointer-events-none absolute right-4 top-3 rounded-full border border-slate-200/80 bg-white/90 px-3 py-1.5 text-[11px] text-slate-500 shadow-sm backdrop-blur dark:border-slate-800 dark:bg-slate-950/80 dark:text-slate-400">
            点击节点查看关系
          </div>
        </div>

        <aside className="hidden min-h-0 overflow-y-auto border-l border-slate-200/80 bg-white/95 p-3 dark:border-slate-800 dark:bg-slate-950/95 xl:block">
          <div className="grid gap-3">
            {activeNode ? (
              <NodeDetail node={activeNode} edges={layout.edges} onSelect={setSelectedId} />
            ) : (
              <OverviewPanel model={model} onSelect={setSelectedId} />
            )}
            <LegendPanel
              model={model}
              layout={layout}
              relationSegments={relationSegments}
              onSelect={setSelectedId}
            />
          </div>
        </aside>
      </div>
    </section>
  );
}
