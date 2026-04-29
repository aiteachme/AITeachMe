import { lazy, Suspense, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  ChevronRight,
  Loader2,
  Network,
  Orbit,
  RefreshCw,
  Square,
  Trash2,
} from "lucide-react";

import { knowledgeClearApiV1SubjectsSubjectIdKnowledgeClearPost } from "../../api/generated/knowledge";
import { getApiErrorMessage } from "../../api/client";
import {
  OVERVIEW_INCLUDE_PRESETS,
  buildKnowledgeOverviewQueryKey,
  fetchKnowledgeOverview,
} from "../../lib/knowledgeOverview";
import {
  buildKnowledgeBuildRuntimeQueryKey,
  cancelKnowledgeBuild,
  triggerKnowledgeGraphBuild,
} from "../../lib/knowledgeBuildRuntime";
import { DigestBuildProgress, useKnowledgeDocsBuildState } from "../build-plan/DigestBuildPanel";
import { SubjectVectorNotice } from "./SubjectVectorNotice";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";

const SemanticUniverse = lazy(() =>
  import("../pages/SemanticUniverse").then((module) => ({ default: module.SemanticUniverse })),
);
const KnowledgeGraphView = lazy(() =>
  import("./KnowledgeGraphView").then((module) => ({ default: module.KnowledgeGraphView })),
);

type KnowledgeViewTab = "semantic-universe" | "knowledge-graph";

const ACTIVE_BUILD_STATUSES = new Set(["accepted", "running", "publishing"]);

const VIEW_TABS: Array<{
  id: KnowledgeViewTab;
  label: string;
  icon: ReactNode;
  desc: string;
}> = [
  {
    id: "semantic-universe",
    label: "语义星图",
    icon: <Orbit className="h-4 w-4" />,
    desc: "按语义距离聚合的可视化星图。",
  },
  {
    id: "knowledge-graph",
    label: "知识图谱",
    icon: <Network className="h-4 w-4" />,
    desc: "可追溯的知识点与关系图谱。",
  },
];

function TabFallback({ message }: { message: string }) {
  return (
    <div className="flex h-[360px] items-center justify-center rounded-2xl border border-slate-200 bg-white text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-400">
      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
      {message}
    </div>
  );
}

export function KnowledgeGraphSidePanel({
  subjectId,
  onClose,
}: {
  subjectId: string;
  onClose?: () => void;
}) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<KnowledgeViewTab>("knowledge-graph");
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  const overviewInclude = useMemo(() => OVERVIEW_INCLUDE_PRESETS.wordCloud, []);

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
    mutationFn: () => knowledgeClearApiV1SubjectsSubjectIdKnowledgeClearPost(subjectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-overview", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["graph-node-detail", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["docgen-content", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["knowledge-doc-build", subjectId] });
      setShowClearConfirm(false);
    },
  });

  const { data: buildRuntime } = useKnowledgeDocsBuildState(subjectId);
  const graphStatus = String(buildRuntime?.graph?.status ?? "").trim();
  const graphIsActive = ACTIVE_BUILD_STATUSES.has(graphStatus);

  const graphBuildMutation = useMutation({
    mutationFn: () => triggerKnowledgeGraphBuild(subjectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: buildKnowledgeBuildRuntimeQueryKey(subjectId) });
      queryClient.invalidateQueries({ queryKey: buildKnowledgeOverviewQueryKey(subjectId, overviewInclude) });
      queryClient.invalidateQueries({ queryKey: ["knowledge-overview", subjectId] });
    },
  });

  const cancelBuildMutation = useMutation({
    mutationFn: () => cancelKnowledgeBuild(subjectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: buildKnowledgeBuildRuntimeQueryKey(subjectId) });
      queryClient.invalidateQueries({ queryKey: ["knowledge-doc-build", subjectId] });
    },
  });

  const subjectLabel = useMemo(() => {
    if (/^subj_[a-z0-9]+$/i.test(subjectId)) {
      return "语义星图";
    }
    return subjectId || "语义星图";
  }, [subjectId]);

  return (
    <div className="flex h-full w-full flex-col bg-white dark:bg-slate-950">
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-950">
          <div className="flex items-center gap-1">
            {onClose && (
              <>
                <button
                  type="button"
                  onClick={onClose}
                  className="flex items-center justify-center gap-1 rounded-md px-2 py-1.5 text-[13px] font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
                >
                  <ChevronRight className="h-4 w-4 shrink-0" />
                  <span className="hidden lg:inline">收起</span>
                </button>
                <div className="mx-1 h-4 w-px bg-slate-200 dark:bg-slate-800" />
              </>
            )}
            <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-900">
            {VIEW_TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-all ${
                  activeTab === tab.id
                    ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-200/70 dark:bg-slate-800 dark:text-slate-100 dark:ring-slate-700"
                    : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
                }`}
                title={tab.desc}
              >
                {tab.icon}
                <span className="hidden lg:inline">{tab.label}</span>
              </button>
            ))}
          </div>
          </div>

          <div className="flex items-center gap-1.5">
            {graphIsActive ? (
              <button
                type="button"
                onClick={() => cancelBuildMutation.mutate()}
                disabled={cancelBuildMutation.isPending}
                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-2.5 text-[12px] font-medium text-amber-700 transition-colors hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200 dark:hover:bg-amber-500/15"
                title="停止当前图谱构建"
              >
                {cancelBuildMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Square className="h-3.5 w-3.5" />
                )}
                <span className="hidden xl:inline">停止构建</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={() => graphBuildMutation.mutate()}
                disabled={graphBuildMutation.isPending}
                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 text-[12px] font-medium text-slate-700 shadow-sm transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                title="从当前已发布知识文档重建知识图谱"
              >
                {graphBuildMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                <span className="hidden xl:inline">构建图谱</span>
              </button>
            )}
            <button
              type="button"
              onClick={() => setShowClearConfirm(true)}
              className="rounded-md p-1.5 text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-500 dark:text-slate-500 dark:hover:bg-rose-500/10 dark:hover:text-rose-300"
              title="清空当前学科知识结构"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        </div>

      <div className="grid gap-3 border-b border-slate-200 bg-slate-50/70 p-3 dark:border-slate-800 dark:bg-slate-900/60">
          <DigestBuildProgress subject={subjectId} compact focus="graph" />
          {graphBuildMutation.isError ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
              {getApiErrorMessage(graphBuildMutation.error, "图谱构建启动失败。")}
            </div>
          ) : null}
          {cancelBuildMutation.isError ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
              {getApiErrorMessage(cancelBuildMutation.error, "停止构建失败。")}
            </div>
          ) : null}
          <SubjectVectorNotice status={overview?.vector_status} />
        </div>

      <div className="flex-1 overflow-auto bg-white p-3 dark:bg-slate-950">
          {overviewLoading ? (
            <div className="flex min-h-full items-center justify-center px-6 py-10 text-sm text-slate-500 dark:text-slate-400">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
              正在加载知识结构...
            </div>
          ) : null}

          {overviewIsError ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
              <div className="flex items-start gap-2">
                <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
                <div>
                  <p className="mb-1 font-semibold">加载失败</p>
                  <p>{getApiErrorMessage(overviewError, "获取知识概览时发生错误。")}</p>
                </div>
              </div>
            </div>
          ) : null}

          {!overviewLoading && !overviewIsError ? (
            <>
              {activeTab === "semantic-universe" ? (
                <Suspense fallback={<TabFallback message="正在加载语义星图..." />}>
                  <SemanticUniverse
                    subjectLabel={subjectLabel}
                    overviewGraph={overview?.graph ?? null}
                    height="calc(100dvh - 20rem)"
                  />
                </Suspense>
              ) : null}

              {activeTab === "knowledge-graph" ? (
                <Suspense fallback={<TabFallback message="正在加载知识图谱..." />}>
                  <KnowledgeGraphView subject={subjectId} overviewGraph={overview?.graph ?? null} />
                </Suspense>
              ) : null}
            </>
          ) : null}
        </div>

      <Modal open={showClearConfirm} onClose={() => setShowClearConfirm(false)} title="确认清空知识数据">
          <div className="space-y-4">
            <div className="flex items-start gap-3 rounded-lg bg-rose-50 p-3 dark:bg-rose-500/10">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-rose-500" />
              <div className="text-sm text-rose-700 dark:text-rose-300">
                <p>这会删除当前学科已发布的知识文档和知识图谱相关结构。</p>
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
  );
}
