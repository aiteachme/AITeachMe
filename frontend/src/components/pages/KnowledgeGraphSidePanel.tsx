import { lazy, Suspense, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  Box,
  FolderTree,
  GitBranch,
  Loader2,
  Network
} from "lucide-react";

import { getApiErrorMessage } from "../../api/client";
import { buildKnowledgeOverviewQueryKey, fetchKnowledgeOverview, OVERVIEW_INCLUDE_PRESETS } from "../../lib/knowledgeOverview";

import { DigestBuildProvider } from "./DigestBuildPanel";

const WordCloud3D = lazy(() => import("./WordCloud3D"));
const ThemeTreeView = lazy(() =>
  import("./ThemeTreeView").then((module) => ({ default: module.ThemeTreeView })),
);
const PrereqDagView = lazy(() =>
  import("./PrereqDagView").then((module) => ({ default: module.PrereqDagView })),
);
const KnowledgeGraphView = lazy(() =>
  import("./KnowledgeGraphView").then((module) => ({ default: module.KnowledgeGraphView })),
);

type KnowledgeViewTab = "word-cloud" | "theme-tree" | "prereq-dag" | "knowledge-graph";

const VIEW_TABS: { id: KnowledgeViewTab; label: string; icon: React.ReactNode; desc: string }[] = [
  { id: "word-cloud", label: "词云", icon: <Box className="h-4 w-4" />, desc: "3D 词云展示知识分布" },
  { id: "theme-tree", label: "主题树", icon: <FolderTree className="h-4 w-4" />, desc: "按章节与主题组织" },
  { id: "prereq-dag", label: "先修图", icon: <GitBranch className="h-4 w-4" />, desc: "展示学习顺序" },
  { id: "knowledge-graph", label: "图谱", icon: <Network className="h-4 w-4" />, desc: "展示节点关系" },
];

function TabFallback({ message }: { message: string }) {
  return (
    <div className="flex h-[420px] items-center justify-center rounded-2xl border border-slate-200 bg-white text-sm text-slate-500">
      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
      {message}
    </div>
  );
}

export function KnowledgeGraphSidePanel({ 
  subjectId,
}: { 
  subjectId: string;
}) {
  const [activeTab, setActiveTab] = useState<KnowledgeViewTab>("knowledge-graph");
  const overviewInclude = useMemo(() => {
    switch (activeTab) {
      case "word-cloud":
        return OVERVIEW_INCLUDE_PRESETS.wordCloud;
      case "theme-tree":
        return OVERVIEW_INCLUDE_PRESETS.themeTree;
      case "prereq-dag":
        return OVERVIEW_INCLUDE_PRESETS.prereqDag;
      case "knowledge-graph":
      default:
        return OVERVIEW_INCLUDE_PRESETS.knowledgeGraph;
    }
  }, [activeTab]);

  const {
    data: overview,
    isLoading: overviewLoading,
    isError: overviewIsError,
    error: overviewError,
  } = useQuery({
    queryKey: buildKnowledgeOverviewQueryKey(subjectId, overviewInclude),
    queryFn: () => fetchKnowledgeOverview(subjectId, overviewInclude),
    enabled: Boolean(subjectId), 
    retry: false,
  });

  const subjectLabel = useMemo(() => {
    if (/^subj_[a-z0-9]+$/.test(subjectId)) return "知识";
    return subjectId || "知识";
  }, [subjectId]);

  const wordCloudNodes = useMemo(() => {
    const graphNodes = overview?.graph?.nodes ?? [];
    return graphNodes.map((node: { canonical_name: string; node_type: string; confidence: number }) => ({
      name: node.canonical_name,
      nodeType: node.node_type,
      confidence: node.confidence,
    }));
  }, [overview?.graph?.nodes]);

  return (
    <DigestBuildProvider subject={subjectId}>
      <div className="flex flex-col h-full w-full bg-white relative border-l border-slate-200/60 transition-colors duration-500 pt-16">
        {/* Toolbar: Tabs & Actions */}
        <div className="flex items-center justify-between border-b border-slate-200 bg-white px-3 py-2 shrink-0 gap-4">
          
          {/* Left: View Tabs */}
          <div className="flex items-center gap-1 bg-slate-100/80 p-1 rounded-lg">
            {VIEW_TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-all ${
                  activeTab === tab.id
                    ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-200/50"
                    : "text-slate-500 hover:text-slate-800"
                }`}
                title={tab.desc}
              >
                {tab.icon}
                <span className="hidden lg:inline">{tab.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-auto bg-white transition-colors duration-500 flex flex-col">
          {overviewLoading && (
            <div className="flex min-h-full items-center justify-center px-6 py-10 text-sm text-slate-500">
              <Loader2 className="h-5 w-5 animate-spin mr-2" />
              正在加载知识结构...
            </div>
          )}

          {overviewIsError && (
            <div className="p-6">
              <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
                <div>
                  <p className="font-semibold mb-1">加载失败</p>
                  <p>{getApiErrorMessage(overviewError, "获取知识概览时发生错误")}</p>
                </div>
              </div>
            </div>
          )}

          {!overviewLoading && !overviewIsError && (
            <div className="flex-1 flex flex-col min-h-0">
              {activeTab === "word-cloud" && (
                <div className="flex-1 min-h-0 p-2">
                  <Suspense
                    fallback={
                      <div className="flex h-full items-center justify-center rounded-xl border border-slate-800 bg-slate-950">
                        <div className="flex items-center gap-2 text-sm text-slate-400">
                          <Loader2 className="h-4 w-4 animate-spin" />
                          加载 3D 词云中...
                        </div>
                      </div>
                    }
                  >
                    <WordCloud3D subjectLabel={subjectLabel} nodes={wordCloudNodes} />
                  </Suspense>
                </div>
              )}
              {activeTab === "theme-tree" && (
                <Suspense fallback={<TabFallback message="正在加载主题树视图..." />}>
                  <ThemeTreeView overviewData={overview?.theme_tree ?? null} />
                </Suspense>
              )}
              {activeTab === "prereq-dag" && (
                <Suspense fallback={<TabFallback message="正在加载先修依赖视图..." />}>
                  <PrereqDagView overviewDag={overview?.prereq_dag ?? null} overviewUnits={overview?.units ?? []} />
                </Suspense>
              )}
              {activeTab === "knowledge-graph" && (
                <div className="flex-1 min-h-0">
                  <Suspense fallback={<TabFallback message="正在加载知识图谱视图..." />}>
                    <KnowledgeGraphView subject={subjectId} overviewGraph={overview?.graph ?? null} />
                  </Suspense>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </DigestBuildProvider>
  );
}
