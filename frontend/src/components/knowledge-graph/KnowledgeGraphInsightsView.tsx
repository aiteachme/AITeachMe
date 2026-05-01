import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, Loader2, PieChart, Route } from "lucide-react";

import { graphFullApiV1CoursesCourseIdKnowledgeGraphFullPost } from "../../api/generated/knowledge";
import type { FullGraphResponse, GraphEdgeResponse, KnowledgeUnitResponse } from "../../api/generated/model";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import {
  DEFAULT_COLOR,
  GRAPH_LAYERS,
  NODE_COLORS,
  RELATION_COLORS,
  nodeBaseLayer,
  relationLabel,
  relationTone,
  truncateGraphLabel,
} from "./knowledgeGraphVisual";

type InsightMode = "overview" | "flow" | "matrix";

type LayerInsight = {
  index: number;
  label: string;
  description: string;
  count: number;
};

type TypeInsight = {
  type: string;
  label: string;
  color: string;
  soft: string;
  count: number;
  percent: number;
};

type RelationInsight = {
  type: string;
  label: string;
  color: string;
  count: number;
  percent: number;
};

type FlowInsight = {
  sourceLayer: number;
  targetLayer: number;
  relationType: string;
  count: number;
};

type GraphInsightModel = {
  nodes: KnowledgeUnitResponse[];
  edges: GraphEdgeResponse[];
  layerItems: LayerInsight[];
  typeItems: TypeInsight[];
  relationItems: RelationInsight[];
  flowItems: FlowInsight[];
  matrix: number[][];
  avgDegree: number;
  densityPct: number;
  maxLayerCount: number;
  maxMatrixCount: number;
  topNodes: Array<KnowledgeUnitResponse & { degree: number }>;
};

const LAYER_COLORS = ["#2563eb", "#7c3aed", "#f97316", "#059669", "#64748b"];

function buildInsightModel(payload: FullGraphResponse | null | undefined): GraphInsightModel {
  const nodes = payload?.nodes ?? [];
  const edges = payload?.edges ?? [];
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const typeCounts = new Map<string, number>();
  const relationCounts = new Map<string, number>();
  const layerCounts = new Map<number, number>();
  const degreeByNode = new Map<number, number>();
  const matrix = GRAPH_LAYERS.map(() => GRAPH_LAYERS.map(() => 0));
  const flowCounts = new Map<string, FlowInsight>();

  for (const node of nodes) {
    const type = String(node.knowledge_unit_type || "other");
    const layer = nodeBaseLayer(type);
    typeCounts.set(type, (typeCounts.get(type) ?? 0) + 1);
    layerCounts.set(layer, (layerCounts.get(layer) ?? 0) + 1);
    degreeByNode.set(node.id, 0);
  }

  for (const edge of edges) {
    const source = nodeById.get(edge.source_node_id);
    const target = nodeById.get(edge.target_node_id);
    if (!source || !target) continue;
    const sourceLayer = nodeBaseLayer(String(source.knowledge_unit_type || ""));
    const targetLayer = nodeBaseLayer(String(target.knowledge_unit_type || ""));
    relationCounts.set(edge.edge_type, (relationCounts.get(edge.edge_type) ?? 0) + 1);
    matrix[sourceLayer][targetLayer] += 1;
    degreeByNode.set(edge.source_node_id, (degreeByNode.get(edge.source_node_id) ?? 0) + 1);
    degreeByNode.set(edge.target_node_id, (degreeByNode.get(edge.target_node_id) ?? 0) + 1);
    const key = `${sourceLayer}:${targetLayer}:${edge.edge_type}`;
    const current = flowCounts.get(key);
    flowCounts.set(key, {
      sourceLayer,
      targetLayer,
      relationType: edge.edge_type,
      count: (current?.count ?? 0) + 1,
    });
  }

  const layerItems = GRAPH_LAYERS.map((layer, index) => ({
    index,
    label: layer.label,
    description: layer.description,
    count: layerCounts.get(index) ?? 0,
  }));
  const typeItems = Array.from(typeCounts.entries())
    .map(([type, count]) => {
      const style = NODE_COLORS[type] ?? DEFAULT_COLOR;
      return {
        type,
        count,
        label: style.label,
        color: style.fill,
        soft: style.soft,
        percent: nodes.length ? count / nodes.length : 0,
      };
    })
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label));
  const relationItems = Array.from(relationCounts.entries())
    .map(([type, count]) => ({
      type,
      count,
      label: relationLabel(type),
      color: relationTone(type),
      percent: edges.length ? count / edges.length : 0,
    }))
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label));
  const flowItems = Array.from(flowCounts.values())
    .sort((left, right) => right.count - left.count)
    .slice(0, 28);
  const topNodes = nodes
    .map((node) => ({ ...node, degree: degreeByNode.get(node.id) ?? 0 }))
    .sort((left, right) => right.degree - left.degree || right.confidence - left.confidence)
    .slice(0, 12);
  const maxLayerCount = Math.max(1, ...layerItems.map((item) => item.count));
  const maxMatrixCount = Math.max(1, ...matrix.flat());
  const avgDegree = nodes.length ? (edges.length * 2) / nodes.length : 0;
  const densityPct = nodes.length > 1 ? (edges.length / (nodes.length * (nodes.length - 1))) * 100 : 0;

  return {
    nodes,
    edges,
    layerItems,
    typeItems,
    relationItems,
    flowItems,
    matrix,
    avgDegree,
    densityPct,
    maxLayerCount,
    maxMatrixCount,
    topNodes,
  };
}

function polarPoint(cx: number, cy: number, radius: number, angle: number) {
  const radians = (angle - 90) * Math.PI / 180;
  return {
    x: cx + Math.cos(radians) * radius,
    y: cy + Math.sin(radians) * radius,
  };
}

function ChartPanel({
  title,
  meta,
  className = "",
  children,
}: {
  title: string;
  meta?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950 ${className}`}>
      <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3 dark:border-slate-800">
        <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</p>
        {meta ? <div className="text-xs font-medium tabular-nums text-slate-500 dark:text-slate-400">{meta}</div> : null}
      </div>
      {children}
    </section>
  );
}

function CompositionOrbit({ model }: { model: GraphInsightModel }) {
  const width = 940;
  const height = 360;
  const maxCount = Math.max(1, ...model.typeItems.map((item) => item.count));
  const items = model.typeItems.slice(0, 9).map((item, index) => {
    const column = index % 3;
    const row = Math.floor(index / 3);
    return {
      ...item,
      cx: 160 + column * 310,
      cy: 92 + row * 112,
    };
  });

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-[330px] w-full">
      <defs>
        <filter id="insight-bubble-shadow" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="8" stdDeviation="8" floodColor="#0f172a" floodOpacity="0.10" />
        </filter>
      </defs>
      <rect width={width} height={height} fill="#ffffff" />
      {items.map((item) => {
        const nodes = model.nodes.filter((node) => node.knowledge_unit_type === item.type).slice(0, 42);
        const groupRadius = 42 + Math.sqrt(item.count / maxCount) * 42;
        return (
          <g key={item.type}>
            <circle cx={item.cx} cy={item.cy} r={groupRadius} fill={item.soft} opacity="0.76" />
            <circle cx={item.cx} cy={item.cy} r={groupRadius + 8} fill="none" stroke={item.color} strokeOpacity="0.16" strokeWidth="2" />
            {nodes.map((node, nodeIndex) => {
              const angle = nodeIndex * 2.399963229728653;
              const radius = nodeIndex === 0 ? 0 : 8 + Math.sqrt(nodeIndex) * 8.3;
              const x = item.cx + Math.cos(angle) * radius;
              const y = item.cy + Math.sin(angle) * radius * 0.78;
              return (
                <circle
                  key={node.id}
                  cx={x}
                  cy={y}
                  r={nodeIndex === 0 ? 8 : 5.2}
                  fill={item.color}
                  opacity={nodeIndex === 0 ? 0.96 : 0.72}
                  filter={nodeIndex === 0 ? "url(#insight-bubble-shadow)" : undefined}
                />
              );
            })}
            <text x={item.cx + groupRadius + 18} y={item.cy - 6} fontSize="13" fontWeight="850" fill="#0f172a">{item.label}</text>
            <text x={item.cx + groupRadius + 18} y={item.cy + 14} fontSize="12" fontWeight="750" fill="#64748b">{item.count} · {Math.round(item.percent * 100)}%</text>
          </g>
        );
      })}
    </svg>
  );
}

function RelationRose({ model }: { model: GraphInsightModel }) {
  const width = 620;
  const height = 240;
  const items = model.relationItems.slice(0, 8);
  const max = Math.max(1, ...items.map((item) => item.count));

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-[220px] w-full">
      <rect width={width} height={height} fill="#ffffff" />
      {items.map((item, index) => {
        const y = 30 + index * 25;
        const barWidth = 92 + (item.count / max) * 390;
        return (
          <g key={item.type}>
            <text x="28" y={y + 8} fontSize="12" fontWeight="800" fill="#475569">{item.label}</text>
            <rect x="96" y={y - 5} width={barWidth} height="18" rx="9" fill={item.color} opacity="0.18" />
            <rect x="96" y={y - 5} width={barWidth} height="18" rx="9" fill={item.color} opacity="0.78" />
            <circle cx={96 + barWidth} cy={y + 4} r="15" fill="#ffffff" stroke={item.color} strokeWidth="5" />
            <text x={96 + barWidth} y={y + 8} textAnchor="middle" fontSize="10" fontWeight="850" fill="#0f172a">{item.count}</text>
          </g>
        );
      })}
    </svg>
  );
}

function LayerRibbonMap({ model, compact = false }: { model: GraphInsightModel; compact?: boolean }) {
  const width = 1040;
  const height = compact ? 330 : 420;
  const left = 88;
  const right = 88;
  const top = compact ? 56 : 72;
  const bottom = compact ? 58 : 78;
  const step = (width - left - right) / Math.max(1, GRAPH_LAYERS.length - 1);
  const maxFlow = Math.max(1, ...model.flowItems.map((item) => item.count));
  const maxLayer = Math.max(1, ...model.layerItems.map((item) => item.count));

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className={`${compact ? "h-[300px]" : "h-[390px]"} w-full`}>
      <defs>
        <filter id="insight-ribbon-shadow" x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="0" dy="10" stdDeviation="10" floodColor="#0f172a" floodOpacity="0.09" />
        </filter>
      </defs>
      <rect width={width} height={height} fill="#ffffff" />
      {model.flowItems.map((flow, index) => {
        const sx = left + step * flow.sourceLayer;
        const tx = left + step * flow.targetLayer;
        const direction = tx >= sx ? 1 : -1;
        const sourceOffset = ((index % 9) - 4) * (compact ? 8 : 11);
        const targetOffset = (((index * 5) % 9) - 4) * (compact ? 8 : 11);
        const sy = height / 2 + sourceOffset;
        const ty = height / 2 + targetOffset;
        const handle = Math.max(78, Math.abs(tx - sx) * 0.48);
        const strokeWidth = 3 + (flow.count / maxFlow) * (compact ? 13 : 18);
        return (
          <path
            key={`${flow.sourceLayer}:${flow.targetLayer}:${flow.relationType}`}
            d={`M${sx},${sy} C${sx + handle * direction},${sy - 34} ${tx - handle * direction},${ty + 34} ${tx},${ty}`}
            fill="none"
            stroke={RELATION_COLORS[flow.relationType] ?? "#94a3b8"}
            strokeLinecap="round"
            strokeWidth={strokeWidth}
            opacity={0.2 + (flow.count / maxFlow) * 0.55}
          />
        );
      })}
      {model.layerItems.map((layer) => {
        const x = left + step * layer.index;
        const color = LAYER_COLORS[layer.index] ?? "#64748b";
        const pillarHeight = 74 + (layer.count / maxLayer) * (height - top - bottom - 92);
        const y = height / 2 - pillarHeight / 2;
        return (
          <g key={layer.index} filter="url(#insight-ribbon-shadow)">
            <line x1={x} x2={x} y1={top - 20} y2={height - bottom + 22} stroke="#e2e8f0" strokeDasharray="4 12" />
            <rect x={x - 26} y={y} width={52} height={pillarHeight} rx={26} fill={color} />
            <circle cx={x} cy={y + 30} r="19" fill="#ffffff" opacity="0.95" />
            <text x={x} y={y + 36} textAnchor="middle" fontSize="13" fontWeight="850" fill={color}>{layer.count}</text>
            <text x={x} y={height - 34} textAnchor="middle" fontSize="13" fontWeight="850" fill="#0f172a">{layer.label}</text>
            <text x={x} y={height - 15} textAnchor="middle" fontSize="11" fontWeight="650" fill="#64748b">{layer.description}</text>
          </g>
        );
      })}
    </svg>
  );
}

function MatrixHeatmap({ model }: { model: GraphInsightModel }) {
  const width = 620;
  const height = 510;
  const cell = 74;
  const gap = 8;
  const left = 124;
  const top = 86;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-[460px] w-full">
      <rect width={width} height={height} fill="#ffffff" />
      {model.layerItems.map((layer, index) => (
        <g key={`x-${layer.index}`}>
          <text x={left + index * (cell + gap) + cell / 2} y={top - 22} textAnchor="middle" fontSize="12" fontWeight="800" fill="#475569">{layer.label}</text>
          <text x={left - 20} y={top + index * (cell + gap) + cell / 2 + 4} textAnchor="end" fontSize="12" fontWeight="800" fill="#475569">{layer.label}</text>
        </g>
      ))}
      {model.layerItems.map((row) => (
        model.layerItems.map((column) => {
          const count = model.matrix[row.index][column.index] ?? 0;
          const intensity = count / model.maxMatrixCount;
          const x = left + column.index * (cell + gap);
          const y = top + row.index * (cell + gap);
          const radius = count ? 9 + intensity * 21 : 0;
          return (
            <g key={`${row.index}:${column.index}`}>
              <rect x={x} y={y} width={cell} height={cell} rx="16" fill={count ? `rgba(37,99,235,${0.1 + intensity * 0.42})` : "#f8fafc"} stroke="#e2e8f0" />
              {count ? <circle cx={x + cell / 2} cy={y + cell / 2} r={radius} fill="#2563eb" opacity={0.78} /> : null}
              <text x={x + cell / 2} y={y + cell / 2 + 5} textAnchor="middle" fontSize="13" fontWeight="850" fill={count ? "#ffffff" : "#cbd5e1"}>{count || ""}</text>
            </g>
          );
        })
      ))}
      <text x={left + (cell + gap) * 2 + cell / 2} y={34} textAnchor="middle" fontSize="12" fontWeight="800" fill="#94a3b8">目标层级</text>
      <text x={28} y={top + (cell + gap) * 2 + cell / 2} textAnchor="middle" fontSize="12" fontWeight="800" fill="#94a3b8" transform={`rotate(-90 28 ${top + (cell + gap) * 2 + cell / 2})`}>来源层级</text>
    </svg>
  );
}

function NodeConstellation({ model }: { model: GraphInsightModel }) {
  const width = 620;
  const height = 390;
  const cx = width / 2;
  const cy = height / 2 + 8;
  const maxDegree = Math.max(1, ...model.topNodes.map((node) => node.degree));

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-[330px] w-full">
      <defs>
        <filter id="insight-node-shadow" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="8" stdDeviation="8" floodColor="#0f172a" floodOpacity="0.10" />
        </filter>
      </defs>
      <rect width={width} height={height} fill="#ffffff" />
      {[86, 138, 190].map((radius) => (
        <circle key={radius} cx={cx} cy={cy} r={radius} fill="none" stroke="#eef2f7" strokeDasharray="4 12" />
      ))}
      {model.topNodes.map((node, index) => {
        const angle = -96 + (360 / Math.max(1, model.topNodes.length)) * index;
        const orbit = 108 + (index % 3) * 42;
        const point = polarPoint(cx, cy, orbit, angle);
        const style = NODE_COLORS[node.knowledge_unit_type] ?? DEFAULT_COLOR;
        const radius = 10 + (node.degree / maxDegree) * 17;
        const labelAnchor = point.x > cx ? "start" : "end";
        const labelX = point.x + (point.x > cx ? radius + 8 : -radius - 8);
        return (
          <g key={node.id}>
            <line x1={cx} y1={cy} x2={point.x} y2={point.y} stroke={style.fill} strokeOpacity="0.18" strokeWidth={1 + (node.degree / maxDegree) * 3} />
            <circle cx={point.x} cy={point.y} r={radius + 7} fill={style.soft} />
            <circle cx={point.x} cy={point.y} r={radius} fill={style.fill} filter="url(#insight-node-shadow)" />
            <text x={labelX} y={point.y + 4} textAnchor={labelAnchor} fontSize="11" fontWeight="750" fill="#334155">
              {truncateGraphLabel(node.canonical_name, 13)}
            </text>
          </g>
        );
      })}
      <circle cx={cx} cy={cy} r="54" fill="#0f172a" />
      <text x={cx} y={cy - 5} textAnchor="middle" fontSize="24" fontWeight="850" fill="#ffffff">{model.avgDegree.toFixed(1)}</text>
      <text x={cx} y={cy + 18} textAnchor="middle" fontSize="11" fontWeight="800" fill="#cbd5e1">平均连接</text>
    </svg>
  );
}

function LayerRidge({ model }: { model: GraphInsightModel }) {
  const width = 620;
  const height = 220;
  const left = 64;
  const max = Math.max(1, model.maxLayerCount);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-[210px] w-full">
      <rect width={width} height={height} fill="#ffffff" />
      {model.layerItems.map((layer, index) => {
        const y = 28 + index * 36;
        const length = 130 + (layer.count / max) * 330;
        const color = LAYER_COLORS[index] ?? "#64748b";
        return (
          <g key={layer.index}>
            <text x={left - 16} y={y + 10} textAnchor="end" fontSize="12" fontWeight="800" fill="#475569">{layer.label}</text>
            <rect x={left} y={y - 3} width={length} height="22" rx="11" fill={color} opacity="0.86" />
            <circle cx={left + length} cy={y + 8} r="17" fill="#ffffff" stroke={color} strokeWidth="5" />
            <text x={left + length} y={y + 12} textAnchor="middle" fontSize="11" fontWeight="850" fill="#0f172a">{layer.count}</text>
          </g>
        );
      })}
    </svg>
  );
}

export function KnowledgeGraphInsightsView({
  course,
  toolbar,
}: {
  course: string;
  toolbar?: ReactNode;
}) {
  const [mode, setMode] = useState<InsightMode>("overview");
  const { data, isLoading } = useQuery({
    queryKey: ["graph-insights-full", course],
    queryFn: async () =>
      unwrapOrvalResponse(
        await graphFullApiV1CoursesCourseIdKnowledgeGraphFullPost(course),
      ) ?? null,
    enabled: Boolean(course),
    retry: false,
  });
  const model = useMemo(() => buildInsightModel(data), [data]);

  if (isLoading) {
    return (
      <div className="flex h-full flex-col bg-slate-50 dark:bg-slate-950">
        <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-950">
          {toolbar}
        </div>
        <div className="flex flex-1 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          正在生成洞察视图...
        </div>
      </div>
    );
  }

  if (!model.nodes.length) {
    return (
      <div className="flex h-full flex-col bg-slate-50 dark:bg-slate-950">
        <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-950">
          {toolbar}
        </div>
        <div className="flex flex-1 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
          暂无可分析的图谱数据
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-950">
        {toolbar}
        <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-0.5 dark:bg-slate-900">
          {[
            { id: "overview", label: "总览", icon: PieChart },
            { id: "flow", label: "流向", icon: Route },
            { id: "matrix", label: "矩阵", icon: BarChart3 },
          ].map((item) => {
            const Icon = item.icon;
            const active = mode === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setMode(item.id as InsightMode)}
                className={`flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors ${
                  active
                    ? "bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-slate-100"
                    : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {item.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {mode === "overview" ? (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.12fr)_minmax(380px,0.88fr)]">
            <ChartPanel title="知识类型点阵" meta={`${model.nodes.length} 节点`}>
              <CompositionOrbit model={model} />
            </ChartPanel>
            <div className="grid gap-4">
              <ChartPanel title="关系分布条带" meta={`${model.edges.length} 关系`}>
                <RelationRose model={model} />
              </ChartPanel>
              <ChartPanel title="核心节点星座" meta={`${model.topNodes.length} 个枢纽`}>
                <NodeConstellation model={model} />
              </ChartPanel>
            </div>
            <ChartPanel
              title="层级流向图"
              meta={`密度 ${model.densityPct.toFixed(2)}%`}
              className="xl:col-span-2"
            >
              <LayerRibbonMap model={model} compact />
            </ChartPanel>
          </div>
        ) : null}

        {mode === "flow" ? (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(360px,0.65fr)]">
            <ChartPanel title="知识迁移 ribbon" meta={`${model.flowItems.length} 条主流向`} className="xl:row-span-2">
              <LayerRibbonMap model={model} />
            </ChartPanel>
            <ChartPanel title="层级山脊" meta={`${model.layerItems.length} 层`}>
              <LayerRidge model={model} />
            </ChartPanel>
            <ChartPanel title="关系分布条带" meta={`${model.relationItems.length} 类`}>
              <RelationRose model={model} />
            </ChartPanel>
          </div>
        ) : null}

        {mode === "matrix" ? (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(420px,1.05fr)]">
            <ChartPanel title="层级关系热力矩阵" meta={`峰值 ${model.maxMatrixCount}`}>
              <MatrixHeatmap model={model} />
            </ChartPanel>
            <div className="grid gap-4">
              <ChartPanel title="类型点阵" meta={`${model.typeItems.length} 类`}>
                <CompositionOrbit model={model} />
              </ChartPanel>
              <ChartPanel title="核心节点星座" meta={`${model.avgDegree.toFixed(1)} 平均连接`}>
                <NodeConstellation model={model} />
              </ChartPanel>
              <ChartPanel title="关系分布条带" meta={`${model.edges.length} 关系`}>
                <RelationRose model={model} />
              </ChartPanel>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
