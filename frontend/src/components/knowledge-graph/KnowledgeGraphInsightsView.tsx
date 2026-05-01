import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, GitBranch, Loader2, Network, PieChart, Route } from "lucide-react";

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
    .slice(0, 18);
  const topNodes = nodes
    .map((node) => ({ ...node, degree: degreeByNode.get(node.id) ?? 0 }))
    .sort((left, right) => right.degree - left.degree || right.confidence - left.confidence)
    .slice(0, 6);
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

function buildConicGradient(items: TypeInsight[]): string {
  if (!items.length) return "conic-gradient(#e2e8f0 0deg 360deg)";
  let cursor = 0;
  const stops = items.map((item) => {
    const start = cursor;
    const end = cursor + item.percent * 360;
    cursor = end;
    return `${item.color} ${start.toFixed(1)}deg ${Math.max(end, start + 2).toFixed(1)}deg`;
  });
  return `conic-gradient(${stops.join(", ")})`;
}

function FlowMap({ model }: { model: GraphInsightModel }) {
  const width = 820;
  const height = 320;
  const left = 76;
  const right = 76;
  const top = 58;
  const bottom = 58;
  const step = (width - left - right) / Math.max(1, GRAPH_LAYERS.length - 1);
  const maxFlow = Math.max(1, ...model.flowItems.map((item) => item.count));

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[320px] w-full">
        <defs>
          <filter id="flow-shadow" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="8" stdDeviation="8" floodColor="#0f172a" floodOpacity="0.08" />
          </filter>
        </defs>
        {model.flowItems.map((flow, index) => {
          const sx = left + step * flow.sourceLayer;
          const tx = left + step * flow.targetLayer;
          const direction = tx >= sx ? 1 : -1;
          const sourceOffset = ((index % 7) - 3) * 9;
          const targetOffset = (((index * 3) % 7) - 3) * 9;
          const sy = height / 2 + sourceOffset;
          const ty = height / 2 + targetOffset;
          const handle = Math.max(70, Math.abs(tx - sx) * 0.46);
          const strokeWidth = 2.2 + (flow.count / maxFlow) * 12;
          return (
            <path
              key={`${flow.sourceLayer}:${flow.targetLayer}:${flow.relationType}`}
              d={`M${sx},${sy} C${sx + handle * direction},${sy} ${tx - handle * direction},${ty} ${tx},${ty}`}
              fill="none"
              stroke={RELATION_COLORS[flow.relationType] ?? "#94a3b8"}
              strokeLinecap="round"
              strokeWidth={strokeWidth}
              opacity={0.18 + (flow.count / maxFlow) * 0.5}
            />
          );
        })}
        {model.layerItems.map((layer) => {
          const x = left + step * layer.index;
          const barHeight = 34 + (layer.count / model.maxLayerCount) * (height - top - bottom - 74);
          const y = height / 2 - barHeight / 2;
          return (
            <g key={layer.index} filter="url(#flow-shadow)">
              <line x1={x} x2={x} y1={top - 16} y2={height - bottom + 16} stroke="rgba(203,213,225,0.55)" strokeDasharray="4 12" />
              <rect x={x - 15} y={y} width={30} height={barHeight} rx={15} fill="#0f172a" />
              <text x={x} y={height - 32} textAnchor="middle" fontSize="12" fontWeight="700" fill="#0f172a">
                {layer.label}
              </text>
              <text x={x} y={height - 14} textAnchor="middle" fontSize="11" fontWeight="600" fill="#64748b">
                {layer.count}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function RelationMatrix({ model }: { model: GraphInsightModel }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950">
      <div className="grid grid-cols-[72px_repeat(5,minmax(0,1fr))] gap-1 text-xs">
        <div />
        {model.layerItems.map((layer) => (
          <div key={layer.index} className="truncate px-1 text-center font-semibold text-slate-500 dark:text-slate-400">
            {layer.label}
          </div>
        ))}
        {model.layerItems.map((row) => (
          <div key={row.index} className="contents">
            <div className="flex h-12 items-center truncate pr-2 font-semibold text-slate-500 dark:text-slate-400">{row.label}</div>
            {model.layerItems.map((column) => {
              const count = model.matrix[row.index][column.index] ?? 0;
              const intensity = count / model.maxMatrixCount;
              return (
                <div
                  key={`${row.index}:${column.index}`}
                  className="flex h-12 items-center justify-center rounded-md border border-white text-xs font-semibold tabular-nums text-slate-700 dark:border-slate-950 dark:text-slate-100"
                  style={{
                    backgroundColor: count ? `rgba(37,99,235,${0.1 + intensity * 0.52})` : "rgba(241,245,249,0.72)",
                  }}
                  title={`${row.label} 到 ${column.label}: ${count} 条关系`}
                >
                  {count || ""}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
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
  const conicGradient = useMemo(() => buildConicGradient(model.typeItems), [model.typeItems]);

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
          <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
            <section className="rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-950">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold">知识构成</p>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{model.nodes.length} 节点 · {model.edges.length} 关系</p>
                </div>
                <Network className="h-5 w-5 text-slate-400" />
              </div>
              <div className="mt-5 flex items-center justify-center">
                <div className="relative h-48 w-48 rounded-full p-5" style={{ background: conicGradient }}>
                  <div className="flex h-full w-full flex-col items-center justify-center rounded-full bg-white text-center shadow-inner dark:bg-slate-950">
                    <span className="text-3xl font-semibold tabular-nums">{model.nodes.length}</span>
                    <span className="mt-1 text-xs font-medium text-slate-500 dark:text-slate-400">知识节点</span>
                  </div>
                </div>
              </div>
              <div className="mt-5 space-y-2">
                {model.typeItems.slice(0, 7).map((item) => (
                  <div key={item.type} className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                    <span className="w-16 text-xs font-medium text-slate-600 dark:text-slate-300">{item.label}</span>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                      <div className="h-full rounded-full" style={{ width: `${item.percent * 100}%`, backgroundColor: item.color }} />
                    </div>
                    <span className="w-8 text-right text-xs tabular-nums text-slate-500">{item.count}</span>
                  </div>
                ))}
              </div>
            </section>

            <section className="grid gap-4 lg:grid-cols-3">
              {[
                { label: "平均连接度", value: model.avgDegree.toFixed(1), icon: GitBranch },
                { label: "图谱密度", value: `${model.densityPct.toFixed(2)}%`, icon: BarChart3 },
                { label: "关系类型", value: model.relationItems.length, icon: Route },
              ].map((item) => {
                const Icon = item.icon;
                return (
                  <div key={item.label} className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950">
                    <div className="flex items-center justify-between">
                      <p className="text-xs font-medium text-slate-500 dark:text-slate-400">{item.label}</p>
                      <Icon className="h-4 w-4 text-slate-400" />
                    </div>
                    <p className="mt-3 text-2xl font-semibold tabular-nums">{item.value}</p>
                  </div>
                );
              })}
              <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950 lg:col-span-3">
                <p className="mb-3 text-sm font-semibold">核心节点排行</p>
                <div className="grid gap-2 md:grid-cols-2">
                  {model.topNodes.map((node) => {
                    const style = NODE_COLORS[node.knowledge_unit_type] ?? DEFAULT_COLOR;
                    return (
                      <div key={node.id} className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900/60">
                        <div className="flex items-center justify-between gap-3">
                          <p className="truncate text-sm font-semibold text-slate-800 dark:text-slate-100">{node.canonical_name}</p>
                          <span className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold text-white" style={{ backgroundColor: style.fill }}>
                            {style.label}
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">连接度 {node.degree} · 置信度 {Math.round(node.confidence * 100)}%</p>
                      </div>
                    );
                  })}
                </div>
              </div>
            </section>
          </div>
        ) : null}

        {mode === "flow" ? (
          <div className="space-y-4">
            <FlowMap model={model} />
            <div className="grid gap-4 lg:grid-cols-2">
              <section className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950">
                <p className="mb-3 text-sm font-semibold">学习层级分布</p>
                <div className="space-y-3">
                  {model.layerItems.map((layer) => (
                    <div key={layer.index} className="grid grid-cols-[56px_minmax(0,1fr)_40px] items-center gap-3">
                      <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">{layer.label}</span>
                      <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                        <div className="h-full rounded-full bg-slate-900 dark:bg-slate-100" style={{ width: `${(layer.count / model.maxLayerCount) * 100}%` }} />
                      </div>
                      <span className="text-right text-xs tabular-nums text-slate-500">{layer.count}</span>
                    </div>
                  ))}
                </div>
              </section>
              <section className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950">
                <p className="mb-3 text-sm font-semibold">关系构成</p>
                <div className="flex flex-wrap gap-2">
                  {model.relationItems.map((item) => (
                    <span
                      key={item.type}
                      className="inline-flex h-8 items-center gap-2 rounded-full border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300"
                    >
                      <span className="h-1.5 w-5 rounded-full" style={{ backgroundColor: item.color }} />
                      {item.label}
                      <span className="text-slate-400">{item.count}</span>
                    </span>
                  ))}
                </div>
              </section>
            </div>
          </div>
        ) : null}

        {mode === "matrix" ? (
          <div className="space-y-4">
            <RelationMatrix model={model} />
            <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950">
              <p className="mb-3 text-sm font-semibold">矩阵读法</p>
              <div className="grid gap-3 text-xs leading-5 text-slate-600 dark:text-slate-300 md:grid-cols-3">
                <p>横轴是关系指向的目标层级，纵轴是关系来源层级。</p>
                <p>颜色越深，说明该层级之间的知识迁移越密集。</p>
                <p>适合快速判断课程内容是否过度集中在某几个层级。</p>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
