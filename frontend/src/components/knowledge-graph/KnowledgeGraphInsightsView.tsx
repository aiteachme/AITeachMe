import { lazy, Suspense, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, Loader2, Network, Sparkles, type LucideIcon } from "lucide-react";

import { graphFullApiV1CoursesCourseIdKnowledgeGraphFullPost } from "../../api/generated/knowledge";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { InsightDashboardView } from "./insights/InsightDashboardView";
import { buildInsightModel } from "./insights/insightsCore";
import { ReadableMapView } from "./insights/ReadableMapView";

type InsightMode = "map" | "galaxy" | "analysis";

const AtlasGalaxyView = lazy(async () => {
  const module = await import("./insights/AtlasGalaxyView");
  return { default: module.AtlasGalaxyView };
});

const TABS: Array<{ id: InsightMode; label: string; icon: LucideIcon }> = [
  { id: "map", label: "地图", icon: Network },
  { id: "galaxy", label: "3D", icon: Sparkles },
  { id: "analysis", label: "数据分析", icon: BarChart3 },
];

function LoadingState({ toolbar }: { toolbar?: ReactNode }) {
  return (
    <div className="flex h-full min-h-0 flex-1 flex-col bg-slate-50 dark:bg-slate-950">
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
    <div className="flex h-full min-h-0 flex-1 flex-col bg-slate-50 dark:bg-slate-950">
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
  const [mode, setMode] = useState<InsightMode>("map");
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
    <div className="flex h-full min-h-0 flex-1 flex-col bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white/95 px-3 py-2 backdrop-blur dark:border-slate-800 dark:bg-slate-950/95">
        {toolbar}
        <div className="ml-auto flex min-w-0 items-center">
          <div className="flex max-w-full items-center gap-1 overflow-x-auto rounded-full bg-slate-100 p-1 dark:bg-slate-900">
            {TABS.map((item) => {
              const Icon = item.icon;
              const active = mode === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setMode(item.id)}
                  title={item.label}
                  aria-label={item.label}
                  className={`flex h-8 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-50 dark:focus-visible:ring-offset-slate-950 ${
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

      <div className="min-h-0 flex-1 overflow-hidden p-2 sm:p-3">
        {mode === "map" ? <ReadableMapView model={model} /> : null}
        {mode === "galaxy" ? (
          <Suspense
            fallback={
              <div className="flex h-full min-h-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-sm text-slate-500 shadow-sm dark:border-slate-800 dark:bg-slate-950 dark:text-slate-400">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                正在加载 3D 展示...
              </div>
            }
          >
            <AtlasGalaxyView model={model} />
          </Suspense>
        ) : null}
        {mode === "analysis" ? <InsightDashboardView model={model} /> : null}
      </div>
    </div>
  );
}
