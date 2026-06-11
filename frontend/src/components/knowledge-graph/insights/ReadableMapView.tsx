import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

import { relationTone, truncateGraphLabel } from "../knowledgeGraphVisual";
import type { GraphInsightModel, NodeInsight } from "./insightsCore";
import {
  LEARNING_LAYERS,
  nodeStyle,
  nodeTypeLabel,
  relationLabel,
} from "./insightsCore";

type MapNode = NodeInsight & {
  type: string;
  color: string;
  soft: string;
  dark: string;
};

type MapEdge = {
  id: number;
  source: MapNode;
  target: MapNode;
  relationType: string;
  color: string;
  confidence: number;
  score: number;
};

const BACKBONE_RELATIONS = new Set(["prerequisite_for", "part_of", "derives_to", "applies_to", "uses_method", "assesses"]);

function edgeScore(relationType: string, source: NodeInsight, target: NodeInsight, confidence: number): number {
  return (
    confidence * 2.4 +
    Math.sqrt(source.degree + target.degree + 1) * 0.45 +
    (BACKBONE_RELATIONS.has(relationType) ? 1.1 : 0) +
    (source.layer !== target.layer ? 0.45 : 0)
  );
}

function buildReadableMap(model: GraphInsightModel): { nodes: MapNode[]; edges: MapEdge[] } {
  const nodes = model.nodes
    .map((node) => {
      const type = String(node.knowledge_unit_type || "other");
      const style = nodeStyle(type);
      return {
        ...node,
        type,
        color: style.fill,
        soft: style.soft,
        dark: style.dark,
      };
    })
    .sort((left, right) => right.impactScore - left.impactScore || right.degree - left.degree || left.id - right.id);

  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const edges = model.edges
    .map((edge) => {
      const source = nodeMap.get(edge.source_node_id);
      const target = nodeMap.get(edge.target_node_id);
      if (!source || !target) return null;
      const relationType = String(edge.edge_type || "related");
      const confidence = Math.max(0, Math.min(1, Number(edge.confidence || 0)));
      return {
        id: edge.id,
        source,
        target,
        relationType,
        color: relationTone(relationType),
        confidence,
        score: edgeScore(relationType, source, target, confidence),
      };
    })
    .filter((edge): edge is MapEdge => Boolean(edge))
    .sort((left, right) => right.score - left.score);

  return { nodes, edges };
}

function NodeRow({
  node,
  active,
  onSelect,
}: {
  node: MapNode;
  active: boolean;
  onSelect: (id: number) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(node.id)}
      className={`group flex w-full items-start gap-2.5 rounded-md px-2.5 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
        active
          ? "bg-slate-950 text-white dark:bg-slate-100 dark:text-slate-950"
          : "hover:bg-slate-100 dark:hover:bg-slate-900"
      }`}
    >
      <span
        className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ring-2 ${
          active ? "ring-white/40 dark:ring-slate-950/30" : "ring-white dark:ring-slate-950"
        }`}
        style={{ backgroundColor: node.color }}
      />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold leading-5">
          {node.canonical_name}
        </span>
        <span className={`mt-0.5 block truncate text-xs ${active ? "text-white/70 dark:text-slate-600" : "text-slate-500 dark:text-slate-400"}`}>
          {nodeTypeLabel(node.type)}
          {node.issueReasons.length ? ` · ${node.issueReasons[0]}` : ""}
        </span>
      </span>
    </button>
  );
}

function LayerColumn({
  index,
  nodes,
  activeId,
  onSelect,
}: {
  index: number;
  nodes: MapNode[];
  activeId: number | null;
  onSelect: (id: number) => void;
}) {
  const layer = LEARNING_LAYERS[index];
  const visibleNodes = nodes.slice(0, 6);
  return (
    <section className="min-w-0 border-slate-200 py-3 first:border-l-0 md:border-l md:px-3 dark:border-slate-800">
      <div className="mb-2 flex items-center gap-2 px-2.5">
        <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: layer.color }} />
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-950 dark:text-slate-50">{layer.label}</p>
          <p className="truncate text-xs text-slate-500 dark:text-slate-400">{layer.description}</p>
        </div>
      </div>
      <div className="space-y-1">
        {visibleNodes.length ? (
          visibleNodes.map((node) => (
            <NodeRow
              key={node.id}
              node={node}
              active={activeId === node.id}
              onSelect={onSelect}
            />
          ))
        ) : (
          <div className="px-2.5 py-6 text-xs text-slate-400 dark:text-slate-500">暂无内容</div>
        )}
      </div>
      {nodes.length > visibleNodes.length ? (
        <p className="px-2.5 pt-2 text-[11px] text-slate-400 dark:text-slate-500">更多内容可在节点列表中查看</p>
      ) : null}
    </section>
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
    <div className="space-y-4">
      <div>
        <div className="flex items-start gap-3">
          <span className="mt-1 h-3 w-3 shrink-0 rounded-full" style={{ backgroundColor: node.color }} />
          <div className="min-w-0">
            <p className="text-sm font-semibold leading-5 text-slate-950 dark:text-slate-50">{node.canonical_name}</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <span className="rounded-full px-2 py-0.5 text-[11px] font-medium" style={{ backgroundColor: node.soft, color: node.dark }}>
                {nodeTypeLabel(node.type)}
              </span>
              {node.issueReasons.length ? (
                <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700 dark:bg-amber-500/10 dark:text-amber-200">
                  待补齐
                </span>
              ) : (
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200">
                  主干
                </span>
              )}
            </div>
          </div>
        </div>
        {node.issueReasons.length ? (
          <div className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800 ring-1 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-200 dark:ring-amber-500/30">
            <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />
            {node.issueReasons.join(" / ")}
          </div>
        ) : (
          <div className="mt-3 rounded-md bg-emerald-50 px-3 py-2 text-xs leading-5 text-emerald-800 ring-1 ring-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-200 dark:ring-emerald-500/30">
            <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" />
            已接入主干。
          </div>
        )}
      </div>

      <div>
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
                  className="rounded-md bg-slate-50 px-3 py-2 text-left ring-1 ring-slate-200 transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:bg-slate-900/70 dark:ring-slate-800 dark:hover:bg-slate-900"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="min-w-0 truncate text-xs font-semibold text-slate-800 dark:text-slate-100">
                      {outgoing ? "指向" : "来自"}：{truncateGraphLabel(next.canonical_name, 18)}
                    </span>
                    <span className="h-2 w-8 shrink-0 rounded-full" style={{ backgroundColor: edge.color }} />
                  </div>
                  <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                    {relationLabel(edge.relationType)}
                  </p>
                </button>
              );
            })
          ) : (
            <div className="rounded-md border border-dashed border-slate-200 px-3 py-6 text-center text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
              暂无直接关系。
            </div>
          )}
        </div>
      </div>
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
  const gapNodes = model.gapNodes.slice(0, 4);
  const hubNodes = model.bottleneckNodes.slice(0, 4);

  return (
    <div className="space-y-4">
      <div>
        <p className="text-sm font-semibold text-slate-950 dark:text-slate-50">学习入口</p>
        <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
          {mainIssue?.title ?? "图谱结构可用"}。点击左侧知识点查看它的前置、方法、例题和易错关系。
        </p>
      </div>

      <div>
        <p className="mb-2 text-xs font-semibold text-slate-500 dark:text-slate-400">建议补齐</p>
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
                </button>
              );
            })
          ) : (
            <div className="rounded-md border border-dashed border-slate-200 px-3 py-4 text-center text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
              暂无明显断点。
            </div>
          )}
        </div>
      </div>

      <div>
        <p className="mb-2 text-xs font-semibold text-slate-500 dark:text-slate-400">主干入口</p>
        <div className="grid gap-2">
          {hubNodes.map((node) => (
            <button
              key={node.id}
              type="button"
              onClick={() => onSelect(node.id)}
              className="flex items-center gap-2 rounded-md bg-slate-50 px-3 py-2 text-left ring-1 ring-slate-200 transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:bg-slate-900/70 dark:ring-slate-800 dark:hover:bg-slate-900"
            >
              <span className="h-2 w-2 shrink-0 rounded-full bg-slate-400 dark:bg-slate-500" />
              <span className="min-w-0 truncate text-xs font-semibold text-slate-800 dark:text-slate-100">
                {node.canonical_name}
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export function ReadableMapView({ model }: { model: GraphInsightModel }) {
  const layout = useMemo(() => buildReadableMap(model), [model]);
  const nodesByLayer = useMemo(
    () => LEARNING_LAYERS.map((_, index) => layout.nodes.filter((node) => node.layer === index)),
    [layout.nodes],
  );
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const activeNode = selectedId ? layout.nodes.find((node) => node.id === selectedId) ?? null : null;

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-slate-200/80 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)] dark:border-slate-800 dark:bg-slate-950">
      <div className="shrink-0 border-b border-slate-100 px-4 py-3 dark:border-slate-800">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-950 dark:text-slate-50">学习地图</p>
            <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
              按“组织、知识、原理、方法、应用”阅读课程主线。
            </p>
          </div>
          <div className="flex shrink-0 items-center rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
            点击知识点查看关系
          </div>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 bg-[#fbfcfe] dark:bg-slate-950 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-h-0 overflow-auto p-3">
          <div className="grid min-w-[880px] grid-cols-5 overflow-hidden rounded-lg bg-white ring-1 ring-slate-200/80 dark:bg-slate-950 dark:ring-slate-800">
            {LEARNING_LAYERS.map((_, index) => (
              <LayerColumn
                key={index}
                index={index}
                nodes={nodesByLayer[index] ?? []}
                activeId={selectedId}
                onSelect={setSelectedId}
              />
            ))}
          </div>
        </div>

        <aside className="min-h-0 overflow-y-auto border-t border-slate-200/80 bg-white/96 p-4 dark:border-slate-800 dark:bg-slate-950/96 xl:border-l xl:border-t-0">
          {activeNode ? (
            <NodeDetail node={activeNode} edges={layout.edges} onSelect={setSelectedId} />
          ) : (
            <OverviewPanel model={model} onSelect={setSelectedId} />
          )}
        </aside>
      </div>
    </section>
  );
}
