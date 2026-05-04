import { lazy, Suspense, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, GitBranch, Loader2, Route, Sparkles, type LucideIcon } from "lucide-react";

import { graphFullApiV1CoursesCourseIdKnowledgeGraphFullPost } from "../../api/generated/knowledge";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { FlowSankeyView } from "./insights/FlowSankeyView";
import { buildInsightModel, percentText } from "./insights/insightsCore";
import { PeerArcView } from "./insights/PeerArcView";
import { StructureMatrixView } from "./insights/StructureMatrixView";

type InsightMode = "atlas" | "peer" | "flow" | "matrix";

const AtlasGalaxyView = lazy(async () => {
  const module = await import("./insights/AtlasGalaxyView");
  return { default: module.AtlasGalaxyView };
});

const TABS: Array<{ id: InsightMode; label: string; icon: LucideIcon }> = [
  { id: "atlas", label: "3D 星云", icon: Sparkles },
  { id: "peer", label: "同级弧线", icon: GitBranch },
  { id: "flow", label: "学习流", icon: Route },
  { id: "matrix", label: "结构矩阵", icon: BarChart3 },
];

function LoadingState({ toolbar }: { toolbar?: ReactNode }) {
  return (
    <div className="flex h-full flex-col bg-slate-50 dark:bg-slate-950">
      <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-950">
        {toolbar}
      </div>
      <div className="flex flex-1 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        正在生成图谱洞察...
      </div>
    </div>
  );
}

function EmptyState({ toolbar }: { toolbar?: ReactNode }) {
  return (
    <div className="flex h-full flex-col bg-slate-50 dark:bg-slate-950">
      <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-950">
        {toolbar}
      </div>
      <div className="flex flex-1 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
        暂无可绘制的图谱数据
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
  const [mode, setMode] = useState<InsightMode>("atlas");
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

  if (isLoading) return <LoadingState toolbar={toolbar} />;
  if (!model.nodeCount) return <EmptyState toolbar={toolbar} />;

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-950">
        {toolbar}
        <div className="flex items-center gap-3">
          <div className="hidden items-center gap-2 text-xs text-slate-500 dark:text-slate-400 lg:flex">
            <span className="font-semibold tabular-nums text-slate-700 dark:text-slate-200">
              {model.nodeCount}
            </span>
            节点
            <span className="font-semibold tabular-nums text-slate-700 dark:text-slate-200">
              {model.edgeCount}
            </span>
            关系
            <span className="font-semibold tabular-nums text-slate-700 dark:text-slate-200">
              {percentText(model.loopCoveragePct)}
            </span>
            闭环
          </div>
          <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-0.5 dark:bg-slate-900">
            {TABS.map((item) => {
              const Icon = item.icon;
              const active = mode === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setMode(item.id)}
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
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {mode === "atlas" ? (
          <Suspense
            fallback={
              <div className="flex h-[680px] items-center justify-center rounded-xl border border-slate-200 bg-white text-sm text-slate-500 shadow-sm dark:border-slate-800 dark:bg-slate-950 dark:text-slate-400">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                正在加载 3D 星云...
              </div>
            }
          >
            <AtlasGalaxyView model={model} />
          </Suspense>
        ) : null}
        {mode === "peer" ? <PeerArcView model={model} /> : null}
        {mode === "flow" ? <FlowSankeyView model={model} /> : null}
        {mode === "matrix" ? <StructureMatrixView model={model} /> : null}
      </div>
    </div>
  );
}
