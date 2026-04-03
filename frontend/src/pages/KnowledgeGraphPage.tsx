import { useState, useMemo, lazy, Suspense } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  Box,
  FolderTree,
  GitBranch,
  Loader2,
  Network,
} from "lucide-react";

import { getApiErrorMessage } from "../api/client";
import { DigestBuildProvider } from "../components/pages/DigestBuildPanel";
import { SubjectVectorNotice } from "../components/pages/SubjectVectorNotice";
import { buildKnowledgeOverviewQueryKey, fetchKnowledgeOverview, OVERVIEW_INCLUDE_PRESETS } from "../lib/knowledgeOverview";

const WordCloud3D = lazy(() => import("../components/pages/WordCloud3D"));
const ThemeTreeView = lazy(() =>
  import("../components/pages/ThemeTreeView").then((module) => ({ default: module.ThemeTreeView })),
);
const PrereqDagView = lazy(() =>
  import("../components/pages/PrereqDagView").then((module) => ({ default: module.PrereqDagView })),
);
const KnowledgeGraphView = lazy(() =>
  import("../components/pages/KnowledgeGraphView").then((module) => ({ default: module.KnowledgeGraphView })),
);

type KnowledgeViewTab = "word-cloud" | "theme-tree" | "prereq-dag" | "knowledge-graph";

const VIEW_TABS: { id: KnowledgeViewTab; label: string; icon: React.ReactNode; desc: string }[] = [
  { id: "knowledge-graph", label: "知识图谱", icon: <Network className="h-4 w-4" />, desc: "展示底层知识节点与连接关系" },
  { id: "word-cloud", label: "知识宇宙", icon: <Box className="h-4 w-4" />, desc: "3D 交互式词云，可视化学科知识版图" },
  { id: "theme-tree", label: "主题树", icon: <FolderTree className="h-4 w-4" />, desc: "按章节与主题组织的课程结构" },
  { id: "prereq-dag", label: "先修图", icon: <GitBranch className="h-4 w-4" />, desc: "展示学习顺序和依赖关系" },
];

function TabFallback({ message }: { message: string }) {
  return (
    <div className="flex h-[420px] items-center justify-center rounded-2xl border border-slate-200 bg-white text-sm text-slate-500">
      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
      {message}
    </div>
  );
}

export function KnowledgeGraphPage() {
  const { subjectId = "" } = useParams();

  const [activeTab, setActiveTab] = useState<KnowledgeViewTab>("knowledge-graph");
  const overviewInclude = useMemo(() => {
    switch (activeTab) {
      case "theme-tree":
        return OVERVIEW_INCLUDE_PRESETS.themeTree;
      case "prereq-dag":
        return OVERVIEW_INCLUDE_PRESETS.prereqDag;
      case "knowledge-graph":
        return OVERVIEW_INCLUDE_PRESETS.knowledgeGraph;
      case "word-cloud":
      default:
        return OVERVIEW_INCLUDE_PRESETS.wordCloud;
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

  // 从 subjectId 提取可读学科名
  const subjectLabel = useMemo(() => {
    // subjectId 如果是 subj_xxx 格式，用默认文字
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

  // 从 overview.graph.nodes 构建 3D 词云数据
  return (
    <DigestBuildProvider subject={subjectId}>
      <div className="mx-auto max-w-7xl space-y-6 px-4 pb-6 pt-20 md:px-6 lg:px-8">
        {/* ---- 页面标题栏 ---- */}
        <div className="flex flex-col gap-2">
          <h1 className="text-3xl font-bold text-slate-900">知识图谱</h1>
          <p className="text-sm text-slate-500">
            这里展示知识宇宙、主题树、先修依赖和知识图谱视图。
          </p>
        </div>

        {/* ---- 加载 / 错误状态 ---- */}
        {overviewLoading ? (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在加载知识概览...
          </div>
        ) : null}

        {overviewIsError ? (
          <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            {getApiErrorMessage(overviewError, "知识概览加载失败")}
          </div>
        ) : null}

        <SubjectVectorNotice status={overview?.vector_status} />

        {/* ---- Tab 切换 ---- */}
        <div className="flex gap-1 rounded-xl bg-slate-100 p-1">
          {VIEW_TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm transition-all ${
                activeTab === tab.id
                  ? "bg-white font-medium text-slate-900 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
              title={tab.desc}
            >
              {tab.icon}
              <span>{tab.label}</span>
            </button>
          ))}
        </div>

        {/* ---- Tab 内容 ---- */}
        {activeTab === "word-cloud" ? (
          <Suspense
            fallback={
              <div className="flex items-center justify-center rounded-xl" style={{ height: "calc(100vh - 16rem)", background: "radial-gradient(ellipse at 50% 45%, #0f0b2e 0%, #030108 100%)" }}>
                <div className="flex items-center gap-2 text-slate-500">
                  <Loader2 className="h-5 w-5 animate-spin" />
                  <span className="text-sm">加载知识宇宙...</span>
                </div>
              </div>
            }
          >
            <WordCloud3D
              subjectLabel={subjectLabel}
              nodes={wordCloudNodes}
              height="calc(100vh - 16rem)"
            />
          </Suspense>
        ) : null}

        {activeTab === "theme-tree" ? (
          <Suspense fallback={<TabFallback message="正在加载主题树视图..." />}>
            <ThemeTreeView overviewData={overview?.theme_tree ?? null} />
          </Suspense>
        ) : null}

        {activeTab === "prereq-dag" ? (
          <Suspense fallback={<TabFallback message="正在加载先修依赖视图..." />}>
            <PrereqDagView overviewDag={overview?.prereq_dag ?? null} overviewUnits={overview?.units ?? []} />
          </Suspense>
        ) : null}

        {activeTab === "knowledge-graph" ? (
          <Suspense fallback={<TabFallback message="正在加载知识图谱视图..." />}>
            <KnowledgeGraphView subject={subjectId} overviewGraph={overview?.graph ?? null} />
          </Suspense>
        ) : null}


      </div>
    </DigestBuildProvider>
  );
}
