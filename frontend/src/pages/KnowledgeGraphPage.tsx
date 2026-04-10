import { Suspense, lazy, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  FolderTree,
  GitBranch,
  Loader2,
  Network,
  Orbit,
  Trash2,
} from "lucide-react";

import { knowledgeClearApiV1SubjectsSubjectKnowledgeClearPost } from "../api/generated/knowledge";
import { getApiErrorMessage } from "../api/client";
import {
  DigestBuildProgress,
  DigestBuildProvider,
} from "../components/pages/DigestBuildPanel";
import { GraphBuildButton } from "../components/pages/GraphBuildButton";
import { StudyPlanPanel } from "../components/pages/StudyPlanPanel";
import { SubjectVectorNotice } from "../components/pages/SubjectVectorNotice";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Modal";
import { useToast } from "../components/ui/Toast";
import {
  OVERVIEW_INCLUDE_PRESETS,
  buildKnowledgeOverviewQueryKey,
  fetchKnowledgeOverview,
} from "../lib/knowledgeOverview";
import { readGraphDebugBuildIntent } from "../lib/knowledgeBuildNavigation";

const SemanticUniverse = lazy(() =>
  import("../components/pages/SemanticUniverse").then((module) => ({ default: module.SemanticUniverse })),
);
const ThemeTreeView = lazy(() =>
  import("../components/pages/ThemeTreeView").then((module) => ({ default: module.ThemeTreeView })),
);
const PrereqDagView = lazy(() =>
  import("../components/pages/PrereqDagView").then((module) => ({ default: module.PrereqDagView })),
);
const KnowledgeGraphView = lazy(() =>
  import("../components/pages/KnowledgeGraphView").then((module) => ({ default: module.KnowledgeGraphView })),
);

type KnowledgeViewTab = "semantic-universe" | "theme-tree" | "prereq-dag" | "knowledge-graph";

const VIEW_TABS: Array<{ id: KnowledgeViewTab; label: string; icon: ReactNode; desc: string }> = [
  {
    id: "semantic-universe",
    label: "知识宇宙",
    icon: <Orbit className="h-4 w-4" />,
    desc: "稳定的语义星图视角，用来浏览主题团簇和邻居关系。",
  },
  {
    id: "theme-tree",
    label: "主题树",
    icon: <FolderTree className="h-4 w-4" />,
    desc: "从课程目录视角浏览主题层级。",
  },
  {
    id: "prereq-dag",
    label: "先修图",
    icon: <GitBranch className="h-4 w-4" />,
    desc: "查看学习依赖和推荐顺序。",
  },
  {
    id: "knowledge-graph",
    label: "专家图谱",
    icon: <Network className="h-4 w-4" />,
    desc: "底层知识图谱视角。",
  },
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
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const graphDebugIntentRef = useRef(readGraphDebugBuildIntent(location.state));
  const graphDebugIntent = graphDebugIntentRef.current;
  const [activeTab, setActiveTab] = useState<KnowledgeViewTab>(
    graphDebugIntent ? "knowledge-graph" : "semantic-universe",
  );
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  useEffect(() => {
    if (!graphDebugIntent) {
      return;
    }

    navigate(location.pathname, { replace: true, state: null });
    toast({
      title: "已进入知识图谱调试模式",
      description:
        graphDebugIntent.fileUids.length > 0
          ? `将使用 ${graphDebugIntent.fileUids.length} 份已解析资料直接触发 graph build。`
          : "当前没有已解析完成的资料，你可以先查看图谱页，待解析完成后再手动触发构建。",
      variant: graphDebugIntent.fileUids.length > 0 ? "info" : "warning",
    });
  }, [graphDebugIntent, location.pathname, navigate, toast]);

  const overviewInclude = useMemo(() => {
    switch (activeTab) {
      case "theme-tree":
        return OVERVIEW_INCLUDE_PRESETS.themeTree;
      case "prereq-dag":
        return OVERVIEW_INCLUDE_PRESETS.prereqDag;
      case "knowledge-graph":
      case "semantic-universe":
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

  const clearMutation = useMutation({
    mutationFn: () => knowledgeClearApiV1SubjectsSubjectKnowledgeClearPost(subjectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-overview", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["graph-node-detail", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["docgen-content", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["knowledge-doc-build", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["study-plan", subjectId] });
      setShowClearConfirm(false);
    },
  });

  const subjectLabel = useMemo(() => {
    if (/^subj_[a-z0-9]+$/i.test(subjectId)) {
      return "知识宇宙";
    }
    return subjectId || "知识宇宙";
  }, [subjectId]);

  return (
    <DigestBuildProvider subject={subjectId}>
      <div className="mx-auto max-w-7xl space-y-6 px-4 pb-6 pt-20 md:px-6 lg:px-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-3xl font-bold text-slate-900">知识图谱</h1>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              这里同时提供学习者视角的语义星图、课程视角的主题树和先修图，以及专家视角的底层知识图谱。
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <GraphBuildButton
              subject={subjectId}
              autoLaunch={
                graphDebugIntent
                  ? {
                      requestKey: graphDebugIntent.requestKey,
                      fileUids: graphDebugIntent.fileUids,
                      autoStart: true,
                      sourceLabel: "上传页",
                    }
                  : null
              }
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowClearConfirm(true)}
              className="text-rose-500 hover:bg-rose-50 hover:text-rose-600"
            >
              <Trash2 className="mr-1 h-4 w-4" />
              清空知识
            </Button>
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
          <DigestBuildProgress />
          <StudyPlanPanel subject={subjectId} compact />
        </div>
        <SubjectVectorNotice status={overview?.vector_status} />

        {overviewLoading ? (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在加载知识概览...
          </div>
        ) : null}

        {overviewIsError ? (
          <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            {getApiErrorMessage(overviewError, "知识概览加载失败。")}
          </div>
        ) : null}

        <div className="flex gap-1 rounded-xl bg-slate-100 p-1">
          {VIEW_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
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

        {activeTab === "semantic-universe" ? (
          <Suspense fallback={<TabFallback message="正在加载知识宇宙..." />}>
            <SemanticUniverse
              subjectLabel={subjectLabel}
              overviewGraph={overview?.graph ?? null}
              height="calc(100vh - 19rem)"
            />
          </Suspense>
        ) : null}

        {activeTab === "theme-tree" ? (
          <Suspense fallback={<TabFallback message="正在加载主题树..." />}>
            <ThemeTreeView overviewData={overview?.theme_tree ?? null} />
          </Suspense>
        ) : null}

        {activeTab === "prereq-dag" ? (
          <Suspense fallback={<TabFallback message="正在加载先修图..." />}>
            <PrereqDagView overviewDag={overview?.prereq_dag ?? null} overviewUnits={overview?.units ?? []} />
          </Suspense>
        ) : null}

        {activeTab === "knowledge-graph" ? (
          <Suspense fallback={<TabFallback message="正在加载知识图谱..." />}>
            <KnowledgeGraphView subject={subjectId} overviewGraph={overview?.graph ?? null} />
          </Suspense>
        ) : null}

        <Modal open={showClearConfirm} onClose={() => setShowClearConfirm(false)} title="确认清空知识数据">
          <div className="space-y-4">
            <div className="flex items-start gap-3 rounded-lg bg-rose-50 p-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-rose-500" />
              <div className="text-sm text-rose-700">
                <p>这会删除当前学科已经发布的知识图谱、教学单元、主题树、先修图以及相关快照。</p>
                <p className="mt-2 font-medium">原始上传文件不会被删除。</p>
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setShowClearConfirm(false)}>
                取消
              </Button>
              <Button
                onClick={() => clearMutation.mutate()}
                disabled={clearMutation.isPending}
                className="bg-rose-500 text-white hover:bg-rose-600"
              >
                {clearMutation.isPending ? (
                  <>
                    <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                    清空中...
                  </>
                ) : (
                  <>
                    <Trash2 className="mr-1 h-4 w-4" />
                    确认清空
                  </>
                )}
              </Button>
            </div>
          </div>
        </Modal>
      </div>
    </DigestBuildProvider>
  );
}
