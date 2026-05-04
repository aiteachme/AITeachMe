import { useMemo } from "react";

import { truncateGraphLabel } from "../knowledgeGraphVisual";
import type { GraphInsightModel } from "./insightsCore";
import { buildTreemap, nodeTypeLabel, percentText, relationLabel } from "./insightsCore";
import { ChartPanel } from "./sharedPrimitives";

type TypeCell = {
  sourceType: string;
  targetType: string;
  count: number;
  dominantRelation: string;
  dominantRelationCount: number;
};

function buildTypeMatrix(model: GraphInsightModel) {
  const types = model.typeItems.slice(0, 7);
  const typeSet = new Set(types.map((item) => item.type));
  const nodeType = new Map(model.nodes.map((node) => [node.id, String(node.knowledge_unit_type || "other")]));
  const cells = new Map<string, { count: number; relationCounts: Map<string, number> }>();

  for (const edge of model.edges) {
    const sourceType = nodeType.get(edge.source_node_id);
    const targetType = nodeType.get(edge.target_node_id);
    if (!sourceType || !targetType || !typeSet.has(sourceType) || !typeSet.has(targetType)) continue;
    const key = `${sourceType}->${targetType}`;
    const cell = cells.get(key) ?? { count: 0, relationCounts: new Map<string, number>() };
    const relationType = String(edge.edge_type || "related");
    cell.count += 1;
    cell.relationCounts.set(relationType, (cell.relationCounts.get(relationType) ?? 0) + 1);
    cells.set(key, cell);
  }

  const matrix = types.map((source) =>
    types.map((target): TypeCell => {
      const cell = cells.get(`${source.type}->${target.type}`);
      const dominant = cell
        ? [...cell.relationCounts.entries()].sort((left, right) => right[1] - left[1])[0]
        : null;
      return {
        sourceType: source.type,
        targetType: target.type,
        count: cell?.count ?? 0,
        dominantRelation: dominant?.[0] ?? "",
        dominantRelationCount: dominant?.[1] ?? 0,
      };
    }),
  );
  const max = Math.max(1, ...matrix.flat().map((cell) => cell.count));
  return { types, matrix, max };
}

function TypeMatrix({ model }: { model: GraphInsightModel }) {
  const data = useMemo(() => buildTypeMatrix(model), [model]);

  return (
    <ChartPanel
      title="类型关系矩阵"
      meta={`${data.types.length} 类知识`}
      description="行是关系起点，列是关系终点；圆越大，说明两类知识之间连接越多。"
    >
      <div className="overflow-x-auto p-4">
        <div
          className="grid min-w-[760px] gap-1.5"
          style={{ gridTemplateColumns: `112px repeat(${data.types.length}, minmax(72px, 1fr))` }}
        >
          <div />
          {data.types.map((type) => (
            <div key={type.type} className="px-1 text-center text-[11px] font-semibold text-slate-500 dark:text-slate-400">
              {type.label}
            </div>
          ))}
          {data.types.map((source, rowIndex) => (
            <div key={`row-${source.type}`} className="contents">
              <div className="flex items-center gap-2 pr-2 text-[11px] font-semibold text-slate-600 dark:text-slate-300">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: source.color }} />
                {source.label}
              </div>
              {data.matrix[rowIndex].map((cell, columnIndex) => {
                const target = data.types[columnIndex];
                const value = cell.count / data.max;
                return (
                  <div
                    key={`${cell.sourceType}-${cell.targetType}`}
                    className="flex h-16 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-900/70"
                    title={
                      cell.count
                        ? `${source.label} → ${target.label}: ${cell.count} 条，主导 ${relationLabel(cell.dominantRelation)}`
                        : `${source.label} → ${target.label}: 暂无关系`
                    }
                  >
                    {cell.count ? (
                      <div
                        className="flex items-center justify-center rounded-full text-[11px] font-bold tabular-nums text-white"
                        style={{
                          width: 18 + value * 34,
                          height: 18 + value * 34,
                          backgroundColor: source.type === target.type ? source.color : target.color,
                          opacity: 0.55 + value * 0.4,
                        }}
                      >
                        {cell.count}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </ChartPanel>
  );
}

function ComponentTreemap({ model }: { model: GraphInsightModel }) {
  const width = 560;
  const height = 300;
  const rects = useMemo(() => buildTreemap(model.components, model.nodeCount, width, height), [model]);

  return (
    <ChartPanel
      title="知识岛分布"
      meta={`${model.componentCount} 个知识岛`}
      description="每块是一个连通分量。最大块越大，用户越容易沿着主干学习。"
    >
      <div className="p-4">
        <svg viewBox={`0 0 ${width} ${height}`} className="h-[320px] w-full" role="img" aria-label="知识岛分布图">
          {rects.map((rect) => (
            <g key={rect.id}>
              <rect
                x={rect.x + 2}
                y={rect.y + 2}
                width={Math.max(0, rect.width - 4)}
                height={Math.max(0, rect.height - 4)}
                rx="8"
                fill={rect.color}
                opacity={rect.isMainline ? 0.82 : 0.46}
              />
              {rect.width > 78 && rect.height > 42 ? (
                <>
                  <text x={rect.x + 12} y={rect.y + 24} fontSize="12" fontWeight="800" fill="#ffffff">
                    {rect.isMainline ? "主干" : `岛 ${rect.id + 1}`}
                  </text>
                  <text x={rect.x + 12} y={rect.y + 42} fontSize="10.5" fill="#ffffff" opacity="0.86">
                    {rect.size} 节点 · {truncateGraphLabel(rect.dominantTypeLabel, 8)}
                  </text>
                </>
              ) : null}
            </g>
          ))}
        </svg>
        <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
          主干覆盖 {percentText(model.largestComponentPct)}。如果小知识岛很多，说明部分知识点没有接回学习路径。
        </p>
      </div>
    </ChartPanel>
  );
}

function DegreeHistogram({ model }: { model: GraphInsightModel }) {
  const buckets = useMemo(() => {
    const ranges = [
      { label: "0", min: 0, max: 0 },
      { label: "1", min: 1, max: 1 },
      { label: "2-3", min: 2, max: 3 },
      { label: "4-6", min: 4, max: 6 },
      { label: "7+", min: 7, max: Infinity },
    ];
    return ranges.map((range) => ({
      ...range,
      count: model.nodes.filter((node) => node.degree >= range.min && node.degree <= range.max).length,
    }));
  }, [model.nodes]);
  const max = Math.max(1, ...buckets.map((bucket) => bucket.count));

  return (
    <ChartPanel title="连接度分布" description="低连接节点容易变成碎片，高连接节点通常是复习入口。">
      <div className="flex h-[320px] items-end gap-4 p-4">
        {buckets.map((bucket) => (
          <div key={bucket.label} className="flex flex-1 flex-col items-center gap-2">
            <div className="flex h-52 w-full items-end justify-center rounded-lg bg-slate-50 px-2 dark:bg-slate-900/70">
              <div
                className="w-full max-w-[56px] rounded-t-lg bg-blue-500"
                style={{ height: `${Math.max(5, (bucket.count / max) * 100)}%` }}
              />
            </div>
            <span className="text-xs font-semibold tabular-nums text-slate-900 dark:text-slate-100">{bucket.count}</span>
            <span className="text-[11px] text-slate-500 dark:text-slate-400">连接 {bucket.label}</span>
          </div>
        ))}
      </div>
    </ChartPanel>
  );
}

function NodeRank({ model }: { model: GraphInsightModel }) {
  const nodes = model.bottleneckNodes.slice(0, 6);
  return (
    <ChartPanel title="关键枢纽" description="最适合作为复习入口的节点，不是随机榜单。">
      <div className="grid gap-2 p-4">
        {nodes.map((node, index) => (
          <div key={node.id} className="flex items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-900/70">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
                {index + 1}. {truncateGraphLabel(node.canonical_name, 18)}
              </p>
              <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
                {nodeTypeLabel(String(node.knowledge_unit_type || "other"))}
              </p>
            </div>
            <span className="shrink-0 rounded-full bg-slate-200 px-2 py-1 text-xs font-semibold tabular-nums text-slate-700 dark:bg-slate-800 dark:text-slate-200">
              {node.degree}
            </span>
          </div>
        ))}
      </div>
    </ChartPanel>
  );
}

export function StructureMatrixView({ model }: { model: GraphInsightModel }) {
  return (
    <div className="grid gap-4">
      <TypeMatrix model={model} />
      <div className="grid gap-4 xl:grid-cols-2">
        <ComponentTreemap model={model} />
        <DegreeHistogram model={model} />
      </div>
      <NodeRank model={model} />
    </div>
  );
}
