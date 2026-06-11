import { useMemo, useState } from "react";

import { cn } from "../../../lib/utils";
import { relationTone } from "../knowledgeGraphVisual";
import type { GraphInsightModel, NodeInsight } from "./insightsCore";
import { nodeStyle, nodeTypeLabel, relationLabel } from "./insightsCore";

type MapNode = NodeInsight & {
  type: string;
  color: string;
};

type MapEdge = {
  id: number;
  source: MapNode;
  target: MapNode;
  relationType: string;
  color: string;
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
      };
    })
    .sort((left, right) => left.layer - right.layer || right.impactScore - left.impactScore || left.id - right.id);

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
        score: edgeScore(relationType, source, target, confidence),
      };
    })
    .filter((edge): edge is MapEdge => Boolean(edge))
    .sort((left, right) => right.score - left.score);

  return { nodes, edges };
}

function connectedEdges(node: MapNode | null, edges: MapEdge[]): MapEdge[] {
  if (!node) return [];
  return edges
    .filter((edge) => edge.source.id === node.id || edge.target.id === node.id)
    .sort((left, right) => right.score - left.score)
    .slice(0, 7);
}

export function ReadableMapView({ model }: { model: GraphInsightModel }) {
  const layout = useMemo(() => buildReadableMap(model), [model]);
  const primaryNodes = useMemo(() => layout.nodes.slice(0, 36), [layout.nodes]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const activeNode = selectedId
    ? layout.nodes.find((node) => node.id === selectedId) ?? primaryNodes[0] ?? null
    : primaryNodes[0] ?? null;
  const relations = connectedEdges(activeNode, layout.edges);
  const gapNodes = model.gapNodes.slice(0, 5);

  if (layout.nodes.length === 0) {
    return (
      <section className="flex h-full items-center justify-center bg-white px-6 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">
        暂无知识地图。
      </section>
    );
  }

  return (
    <section className="grid h-full min-h-0 bg-white dark:bg-slate-950 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-h-0 overflow-y-auto px-5 py-5">
        <div className="mx-auto max-w-[900px]">
          <div className="mb-5">
            <h3 className="text-base font-semibold text-slate-950 dark:text-slate-50">学习地图</h3>
          </div>

          <ol className="space-y-1.5">
            {primaryNodes.map((node, index) => {
              const active = activeNode?.id === node.id;
              return (
                <li key={node.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(node.id)}
                    className={cn(
                      "group flex w-full items-start gap-3 rounded-md px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
                      active
                        ? "bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300"
                        : "text-slate-700 hover:bg-slate-50 hover:text-slate-950 dark:text-slate-300 dark:hover:bg-slate-900 dark:hover:text-slate-50",
                    )}
                    aria-pressed={active}
                  >
                    <span className="mt-0.5 w-8 shrink-0 text-right text-sm font-semibold tabular-nums text-blue-600 dark:text-blue-300">
                      {index + 1}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold leading-5">{node.canonical_name}</span>
                      <span className="mt-0.5 flex items-center gap-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                        <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: node.color }} />
                        {nodeTypeLabel(node.type)}
                        {node.issueReasons.length ? <span className="truncate">· {node.issueReasons[0]}</span> : null}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
      </div>

      <aside className="min-h-0 overflow-y-auto border-t border-slate-200 bg-slate-50/60 px-5 py-5 dark:border-slate-800 dark:bg-slate-900/30 lg:border-l lg:border-t-0">
        {activeNode ? (
          <div className="space-y-6">
            <div>
              <p className="text-base font-semibold leading-6 text-slate-950 dark:text-slate-50">{activeNode.canonical_name}</p>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{nodeTypeLabel(activeNode.type)}</p>
              {activeNode.issueReasons.length ? (
                <p className="mt-3 border-l-2 border-amber-300 pl-3 text-sm leading-6 text-amber-700 dark:border-amber-400 dark:text-amber-200">
                  {activeNode.issueReasons[0]}
                </p>
              ) : null}
            </div>

            <div>
              <p className="mb-2 text-sm font-semibold text-slate-900 dark:text-slate-100">相关关系</p>
              <div className="divide-y divide-slate-200 dark:divide-slate-800">
                {relations.length ? (
                  relations.map((edge) => {
                    const next = edge.source.id === activeNode.id ? edge.target : edge.source;
                    return (
                      <button
                        key={edge.id}
                        type="button"
                        onClick={() => setSelectedId(next.id)}
                        className="flex w-full items-center gap-3 py-2.5 text-left transition-colors hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:hover:text-white"
                      >
                        <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: edge.color }} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium text-slate-800 dark:text-slate-100">{next.canonical_name}</span>
                          <span className="text-xs text-slate-500 dark:text-slate-400">{relationLabel(edge.relationType)}</span>
                        </span>
                      </button>
                    );
                  })
                ) : (
                  <p className="py-4 text-sm text-slate-500 dark:text-slate-400">暂无直接关系。</p>
                )}
              </div>
            </div>

            {gapNodes.length ? (
              <div>
                <p className="mb-2 text-sm font-semibold text-slate-900 dark:text-slate-100">建议补齐</p>
                <div className="divide-y divide-slate-200 dark:divide-slate-800">
                  {gapNodes.map((node) => (
                    <button
                      key={node.id}
                      type="button"
                      onClick={() => setSelectedId(node.id)}
                      className="block w-full py-2 text-left transition-colors hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:hover:text-white"
                    >
                      <span className="block truncate text-sm font-medium text-slate-800 dark:text-slate-100">{node.canonical_name}</span>
                      <span className="text-xs text-slate-500 dark:text-slate-400">{node.issueReasons[0] || "待复核"}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </aside>
    </section>
  );
}
