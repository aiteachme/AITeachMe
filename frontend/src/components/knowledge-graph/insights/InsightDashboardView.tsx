import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { useMemo } from "react";

import { relationTone, truncateGraphLabel } from "../knowledgeGraphVisual";
import type { GraphInsightModel, NodeInsight } from "./insightsCore";
import { LEARNING_LAYERS, nodeStyle, percentText, relationLabel } from "./insightsCore";
import { CategoryBar, ChartPanel } from "./sharedPrimitives";

type PeerFocusPair = {
  id: number;
  source: NodeInsight;
  target: NodeInsight;
  relationLabel: string;
  color: string;
  confidence: number;
  score: number;
};

type ConfidenceBin = {
  label: string;
  count: number;
  color: string;
};

const PEER_FOCUS_RELATIONS = new Set(["contrast", "similar", "explanation", "training"]);

function buildPeerPairs(model: GraphInsightModel): PeerFocusPair[] {
  const nodeMap = new Map(model.nodes.map((node) => [node.id, node]));
  return model.edges
    .map((edge) => {
      const source = nodeMap.get(edge.source_node_id);
      const target = nodeMap.get(edge.target_node_id);
      if (!source || !target || source.layer !== target.layer) return null;
      const relationType = String(edge.edge_type || "related");
      const confidence = Math.max(0, Math.min(1, Number(edge.confidence || 0)));
      return {
        id: edge.id,
        source,
        target,
        relationLabel: relationLabel(relationType),
        color: relationTone(relationType),
        confidence,
        score:
          confidence * 2 +
          Math.sqrt(source.degree + target.degree + 1) * 0.3 +
          (PEER_FOCUS_RELATIONS.has(relationType) ? 1.2 : 0),
      };
    })
    .filter((pair): pair is PeerFocusPair => Boolean(pair))
    .sort((left, right) => right.score - left.score || left.id - right.id)
    .slice(0, 6);
}

function MetricTile({
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
      ? "bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-200 dark:ring-emerald-500/30"
      : tone === "warn"
        ? "bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-200 dark:ring-amber-500/30"
        : tone === "bad"
          ? "bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-500/10 dark:text-rose-200 dark:ring-rose-500/30"
          : "bg-slate-50 text-slate-700 ring-slate-200 dark:bg-slate-900/70 dark:text-slate-200 dark:ring-slate-800";

  return (
    <div className={`rounded-md px-3 py-2 ring-1 ${toneClass}`}>
      <p className="text-[11px] opacity-75">{label}</p>
      <p className="mt-1 text-base font-bold tabular-nums">{value}</p>
    </div>
  );
}

function buildConfidenceBins(values: number[]): ConfidenceBin[] {
  return [
    {
      label: "高",
      count: values.filter((value) => value >= 0.86).length,
      color: "#10b981",
    },
    {
      label: "中",
      count: values.filter((value) => value >= 0.72 && value < 0.86).length,
      color: "#f59e0b",
    },
    {
      label: "低",
      count: values.filter((value) => value < 0.72).length,
      color: "#f43f5e",
    },
  ];
}

function MiniDistribution({ bins, total }: { bins: ConfidenceBin[]; total: number }) {
  return (
    <div className="grid gap-2">
      <div className="flex h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-900">
        {bins.map((bin) => {
          const width = total ? (bin.count / total) * 100 : 0;
          if (width <= 0) return null;
          return (
            <div
              key={bin.label}
              title={`${bin.label} · ${bin.count}`}
              style={{ width: `${width}%`, backgroundColor: bin.color }}
            />
          );
        })}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {bins.map((bin) => (
          <span key={bin.label} className="inline-flex items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400">
            <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: bin.color }} />
            {bin.label}
            <span className="font-semibold tabular-nums">{bin.count}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function RelationMatrix({ model }: { model: GraphInsightModel }) {
  const max = Math.max(1, model.matrixMax);
  const topPairs = model.typePairFlows.slice(0, 5);
  return (
    <ChartPanel
      title="关系矩阵"
      meta={`${model.edgeCount} 条边`}
      description="行是关系起点，列是关系终点；颜色越深，表示这段学习流越密。"
    >
      <div className="grid gap-3 p-3 sm:p-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="overflow-x-auto">
          <div
            className="grid min-w-[520px] gap-1.5"
            style={{ gridTemplateColumns: `72px repeat(${LEARNING_LAYERS.length}, minmax(64px, 1fr))` }}
          >
            <div />
            {LEARNING_LAYERS.map((layer) => (
              <div key={layer.label} className="text-center text-[11px] font-semibold text-slate-500 dark:text-slate-400">
                {layer.label}
              </div>
            ))}
            {LEARNING_LAYERS.map((source, rowIndex) => (
              <div key={source.label} className="contents">
                <div className="flex items-center gap-1.5 pr-1 text-[11px] font-semibold" style={{ color: source.color }}>
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: source.color }} />
                  {source.label}
                </div>
                {LEARNING_LAYERS.map((target, columnIndex) => {
                  const count = model.matrix[rowIndex]?.[columnIndex] ?? 0;
                  const value = count / max;
                  const isBackbone = columnIndex === rowIndex + 1;
                  return (
                    <div
                      key={`${source.label}-${target.label}`}
                      title={`${source.label} → ${target.label}: ${count} 条`}
                      className={`flex h-12 items-center justify-center rounded-md border text-xs font-semibold tabular-nums ${
                        isBackbone
                          ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200"
                          : "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-300"
                      }`}
                      style={{
                        boxShadow: count ? `inset 0 0 0 999px rgba(37, 99, 235, ${0.05 + value * 0.2})` : undefined,
                      }}
                    >
                      {count || ""}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>

        <div className="grid content-start gap-2">
          <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">高频类型流</p>
          {topPairs.map((pair) => {
            const sourceStyle = nodeStyle(pair.sourceType);
            const targetStyle = nodeStyle(pair.targetType);
            return (
              <div
                key={`${pair.sourceType}-${pair.targetType}-${pair.relationType}`}
                className="rounded-md bg-slate-50 px-3 py-2 ring-1 ring-slate-200 dark:bg-slate-900/70 dark:ring-slate-800"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-xs font-semibold text-slate-800 dark:text-slate-100">
                    <span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ backgroundColor: sourceStyle.fill }} />
                    {sourceStyle.label}
                    <span className="mx-1 text-slate-400">→</span>
                    <span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ backgroundColor: targetStyle.fill }} />
                    {targetStyle.label}
                  </span>
                  <span className="text-xs font-semibold tabular-nums text-slate-500">{pair.count}</span>
                </div>
                <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">{pair.relationLabel}</p>
              </div>
            );
          })}
        </div>
      </div>
    </ChartPanel>
  );
}

export function InsightDashboardView({ model }: { model: GraphInsightModel }) {
  const pathPresence = useMemo(
    () =>
      LEARNING_LAYERS.slice(0, -1).map((_, index) =>
        model.flowItems.some(
          (flow) => flow.sourceLayer === index && flow.targetLayer === index + 1 && flow.count > 0,
        ),
      ),
    [model.flowItems],
  );
  const pathCompletedCount = pathPresence.filter(Boolean).length;
  const backwardCount = useMemo(
    () =>
      model.flowItems.reduce(
        (sum, flow) => sum + (flow.targetLayer < flow.sourceLayer ? flow.count : 0),
        0,
      ),
    [model.flowItems],
  );
  const peerPairs = useMemo(() => buildPeerPairs(model), [model]);
  const relationSegments = model.relationItems.slice(0, 7).map((relation) => ({
    key: relation.type,
    label: relation.label,
    color: relation.color,
    count: relation.count,
  }));
  const mainIssue = model.issues[0];
  const issueIsGood = mainIssue?.tone === "good";
  const nodeConfidenceBins = useMemo(
    () => buildConfidenceBins(model.nodes.map((node) => Math.max(0, Math.min(1, Number(node.confidence || 0))))),
    [model.nodes],
  );
  const edgeConfidenceBins = useMemo(
    () => buildConfidenceBins(model.edges.map((edge) => Math.max(0, Math.min(1, Number(edge.confidence || 0))))),
    [model.edges],
  );
  const weightAvg = model.edgeCount
    ? model.edges.reduce((sum, edge) => sum + Math.max(0, Number(edge.weight || 0)), 0) / model.edgeCount
    : 0;
  const typeSourceItems = useMemo(() => {
    const counts = new Map<string, number>();
    for (const node of model.nodes) {
      const key = String(node.type_source || "未知");
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return Array.from(counts.entries())
      .map(([label, count]) => ({ label, count }))
      .sort((left, right) => right.count - left.count)
      .slice(0, 4);
  }, [model.nodes]);

  return (
    <div className="h-full min-h-0 overflow-y-auto pr-1">
      <div className="grid min-h-full gap-3 xl:grid-cols-[minmax(0,1.28fr)_minmax(320px,0.72fr)]">
        <div className="grid gap-3">
          <ChartPanel
            title="学习闭环"
            meta={`路径 ${pathCompletedCount}/4 · 回流 ${backwardCount}`}
          >
            <div className="grid gap-3 p-3 sm:p-4 lg:grid-cols-[minmax(0,1fr)_280px]">
              <div>
                <div className="grid grid-cols-5 gap-2">
                  {LEARNING_LAYERS.map((layer, index) => (
                    <div key={layer.label} className="min-w-0">
                      <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-900">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${Math.max(6, (model.layerItems[index]?.percent ?? 0) * 100)}%`,
                            backgroundColor: layer.color,
                          }}
                        />
                      </div>
                      <p className="mt-2 truncate text-xs font-semibold" style={{ color: layer.color }}>
                        {layer.label}
                      </p>
                      <p className="mt-0.5 text-[11px] tabular-nums text-slate-500 dark:text-slate-400">
                        {model.layerItems[index]?.count ?? 0} 点
                      </p>
                    </div>
                  ))}
                </div>

                <div className="mt-5 flex items-center gap-2">
                  {pathPresence.map((present, index) => (
                    <div key={index} className="flex flex-1 items-center gap-2">
                      <div
                        className={`h-2 flex-1 rounded-full ${
                          present ? "bg-emerald-500" : "bg-rose-400"
                        }`}
                      />
                      {index < pathPresence.length - 1 ? (
                        <span className="text-[11px] text-slate-300 dark:text-slate-700">→</span>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <MetricTile label="主干" value={percentText(model.largestComponentPct)} tone={model.largestComponentPct >= 0.72 ? "good" : "warn"} />
                <MetricTile label="闭环" value={percentText(model.loopCoveragePct)} tone={model.loopCoveragePct >= 0.56 ? "good" : "warn"} />
                <MetricTile label="练习" value={percentText(model.practiceCoveragePct)} tone={model.practiceCoveragePct >= 0.64 ? "good" : "warn"} />
                <MetricTile label="孤立" value={model.isolatedCount} tone={model.isolatedCount ? "bad" : "good"} />
              </div>
            </div>
          </ChartPanel>

          <RelationMatrix model={model} />

          <ChartPanel title="同级辨析" meta={`${peerPairs.length} 组`}>
            <div className="grid gap-2.5 p-3 sm:p-4 md:grid-cols-2 xl:grid-cols-3">
              {peerPairs.length ? (
                peerPairs.map((pair) => {
                  const sourceStyle = nodeStyle(String(pair.source.knowledge_unit_type || ""));
                  const targetStyle = nodeStyle(String(pair.target.knowledge_unit_type || ""));
                  return (
                    <div
                      key={pair.id}
                      className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2.5 dark:border-slate-800 dark:bg-slate-900/60"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span
                          className="rounded-full px-2 py-0.5 text-[10px] font-semibold text-white"
                          style={{ backgroundColor: pair.color }}
                        >
                          {pair.relationLabel}
                        </span>
                        <span className="text-[10px] tabular-nums text-slate-400">{percentText(pair.confidence)}</span>
                      </div>
                      <p className="mt-2 truncate text-xs font-semibold text-slate-900 dark:text-slate-100">
                        <span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ backgroundColor: sourceStyle.fill }} />
                        {truncateGraphLabel(pair.source.canonical_name, 16)}
                      </p>
                      <p className="mt-1 truncate text-xs text-slate-600 dark:text-slate-300">
                        <span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ backgroundColor: targetStyle.fill }} />
                        {truncateGraphLabel(pair.target.canonical_name, 16)}
                      </p>
                    </div>
                  );
                })
              ) : (
                <div className="rounded-lg border border-dashed border-slate-200 px-3 py-8 text-center text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400 md:col-span-2 xl:col-span-3">
                  暂无同级辨析关系。
                </div>
              )}
            </div>
          </ChartPanel>
        </div>

        <div className="grid content-start gap-3">
          <ChartPanel title="优先处理">
            <div className="grid gap-2.5 p-3 sm:p-4">
              <div
                className={`rounded-md border px-3 py-2 ${
                  issueIsGood
                    ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200"
                    : "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200"
                }`}
              >
                <p className="truncate text-sm font-semibold">
                  {issueIsGood ? <CheckCircle2 className="mr-1 inline h-4 w-4" /> : <AlertTriangle className="mr-1 inline h-4 w-4" />}
                  {mainIssue?.title ?? "图谱结构可用"}
                </p>
              </div>

              <div className="grid gap-2">
                {model.gapNodes.slice(0, 5).map((node) => {
                  const style = nodeStyle(String(node.knowledge_unit_type || "other"));
                  return (
                    <div
                      key={node.id}
                      className="flex items-center justify-between gap-3 rounded-md bg-slate-50 px-3 py-2 ring-1 ring-slate-200 dark:bg-slate-900/70 dark:ring-slate-800"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-xs font-semibold text-slate-800 dark:text-slate-100">
                          {truncateGraphLabel(node.canonical_name, 18)}
                        </span>
                        <span className="mt-0.5 flex items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400">
                          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: style.fill }} />
                          {node.issueReasons[0] || "待复核"}
                        </span>
                      </span>
                      <span className="shrink-0 text-xs font-semibold tabular-nums text-slate-500">
                        {node.degree}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </ChartPanel>

          <ChartPanel title="结构分布" meta={`${model.componentCount} 岛`}>
            <div className="grid gap-3 p-3 sm:p-4">
              <CategoryBar segments={relationSegments} height={8} />
              <div className="flex flex-wrap gap-2">
                {model.typeItems.slice(0, 7).map((type) => (
                  <span
                    key={type.type}
                    className="inline-flex items-center gap-1.5 rounded-full bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-600 ring-1 ring-slate-200 dark:bg-slate-900/70 dark:text-slate-300 dark:ring-slate-800"
                  >
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: type.color }} />
                    {type.label}
                    <span className="tabular-nums text-slate-400">{type.count}</span>
                  </span>
                ))}
              </div>
            </div>
          </ChartPanel>

          <ChartPanel title="数据质量" meta={`均权 ${weightAvg.toFixed(2)}`}>
            <div className="grid gap-3 p-3 sm:p-4">
              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">节点置信度</p>
                  <span className="text-[11px] tabular-nums text-slate-400">{model.nodeCount} 点</span>
                </div>
                <MiniDistribution bins={nodeConfidenceBins} total={model.nodeCount} />
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">关系置信度</p>
                  <span className="text-[11px] tabular-nums text-slate-400">{model.edgeCount} 线</span>
                </div>
                <MiniDistribution bins={edgeConfidenceBins} total={model.edgeCount} />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <MetricTile label="平均度" value={model.avgDegree.toFixed(1)} />
                <MetricTile label="密度" value={`${model.densityPct.toFixed(2)}%`} />
                <MetricTile label="低置信边" value={model.lowConfidenceRelationCount} tone={model.lowConfidenceRelationCount ? "warn" : "good"} />
                <MetricTile label="结构分" value={model.diagnosisScore} tone={model.diagnosisTone} />
              </div>

              {typeSourceItems.length ? (
                <div>
                  <p className="mb-2 text-xs font-semibold text-slate-500 dark:text-slate-400">类型来源</p>
                  <div className="flex flex-wrap gap-2">
                    {typeSourceItems.map((item) => (
                      <span
                        key={item.label}
                        className="rounded-full bg-slate-50 px-2.5 py-1 text-[11px] text-slate-600 ring-1 ring-slate-200 dark:bg-slate-900/70 dark:text-slate-300 dark:ring-slate-800"
                      >
                        {item.label} <span className="font-semibold tabular-nums">{item.count}</span>
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </ChartPanel>
        </div>
      </div>
    </div>
  );
}
