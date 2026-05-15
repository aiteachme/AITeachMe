import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  ChevronRight,
  Loader2,
  Network,
  RefreshCw,
  Square,
  Trash2,
} from "lucide-react";

import { knowledgeClearApiV1CoursesCourseIdKnowledgeClearPost } from "../../api/generated/knowledge";
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
import { CourseVectorNotice } from "./CourseVectorNotice";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";
import type { KnowledgeGraphSourceRefNavigationTarget } from "./KnowledgeGraphNodeDetailPanel";

const KnowledgeGraphView = lazy(() =>
  import("./KnowledgeGraphView").then((module) => ({ default: module.KnowledgeGraphView })),
);

const ACTIVE_BUILD_STATUSES = new Set(["accepted", "running", "publishing"]);
const GRAPH_TERMINAL_BUILD_STATUSES = new Set(["completed", "partial_failed", "failed", "cancelled", "skipped"]);
const GRAPH_AUTO_BUILD_STATUSES = new Set(["", "idle", "skipped"]);
const AUTO_GRAPH_BUILD_ATTEMPTS = new Set<string>();

function TabFallback({ message }: { message: string }) {
  return (
    <div className="flex h-full min-h-[360px] items-center justify-center bg-white text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">
      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
      {message}
    </div>
  );
}

export function KnowledgeGraphSidePanel({
  courseId,
  onClose,
  onSourceRefClick,
}: {
  courseId: string;
  onClose?: () => void;
  onSourceRefClick?: (ref: KnowledgeGraphSourceRefNavigationTarget) => void;
}) {
  const queryClient = useQueryClient();
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  const overviewInclude = OVERVIEW_INCLUDE_PRESETS.knowledgeGraph;

  const {
    data: overview,
    isLoading: overviewLoading,
    isError: overviewIsError,
    error: overviewError,
  } = useQuery({
    queryKey: buildKnowledgeOverviewQueryKey(courseId, overviewInclude),
    queryFn: () => fetchKnowledgeOverview(courseId, overviewInclude),
    enabled: Boolean(courseId),
    retry: false,
  });

  const clearMutation = useMutation({
    mutationFn: () => knowledgeClearApiV1CoursesCourseIdKnowledgeClearPost(courseId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-overview", courseId] });
      queryClient.invalidateQueries({ queryKey: ["graph-node-detail", courseId] });
      queryClient.invalidateQueries({ queryKey: ["graph-node-list", courseId] });
      queryClient.invalidateQueries({ queryKey: ["graph-subgraph", courseId] });
      queryClient.invalidateQueries({ queryKey: ["docgen-content", courseId] });
      queryClient.invalidateQueries({ queryKey: ["knowledge-doc-build", courseId] });
      setShowClearConfirm(false);
    },
  });

  const { data: buildRuntime } = useKnowledgeDocsBuildState(courseId);
  const docgenStatus = String(buildRuntime?.docgen?.status ?? "").trim();
  const graphStatus = String(buildRuntime?.graph?.status ?? "").trim();
  const graphIsActive = ACTIVE_BUILD_STATUSES.has(graphStatus);
  const graphCanAutoBuild = GRAPH_AUTO_BUILD_STATUSES.has(graphStatus);
  const graphNodeCount = Number(overview?.stats?.node_count ?? 0);
  const graphEdgeCount = Number(overview?.stats?.edge_count ?? 0);
  const previousGraphStatusRef = useRef(graphStatus);

  useEffect(() => {
    const previousStatus = previousGraphStatusRef.current;
    previousGraphStatusRef.current = graphStatus;
    if (!courseId || !ACTIVE_BUILD_STATUSES.has(previousStatus) || !GRAPH_TERMINAL_BUILD_STATUSES.has(graphStatus)) {
      return;
    }
    queryClient.invalidateQueries({ queryKey: buildKnowledgeOverviewQueryKey(courseId, overviewInclude) });
    queryClient.invalidateQueries({ queryKey: ["knowledge-overview", courseId] });
    queryClient.invalidateQueries({ queryKey: ["graph-node-list", courseId] });
    queryClient.invalidateQueries({ queryKey: ["graph-subgraph", courseId] });
    queryClient.invalidateQueries({ queryKey: ["graph-node-detail", courseId] });
  }, [courseId, graphStatus, overviewInclude, queryClient]);

  const graphBuildMutation = useMutation({
    mutationFn: () => triggerKnowledgeGraphBuild(courseId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: buildKnowledgeBuildRuntimeQueryKey(courseId) });
      queryClient.invalidateQueries({ queryKey: buildKnowledgeOverviewQueryKey(courseId, overviewInclude) });
      queryClient.invalidateQueries({ queryKey: ["knowledge-overview", courseId] });
      queryClient.invalidateQueries({ queryKey: ["graph-node-list", courseId] });
      queryClient.invalidateQueries({ queryKey: ["graph-subgraph", courseId] });
    },
  });

  useEffect(() => {
    const docgenRunKey =
      buildRuntime?.docgen?.build_group_id ??
      buildRuntime?.docgen?.finished_at ??
      buildRuntime?.docgen?.requested_at ??
      "latest";
    const attemptKey = `${courseId}:${docgenRunKey}`;
    if (!courseId || overviewLoading || overviewIsError || graphBuildMutation.isPending) return;
    if (docgenStatus !== "completed" || !graphCanAutoBuild) return;
    if (graphNodeCount > 0 || graphEdgeCount > 0) return;
    if (AUTO_GRAPH_BUILD_ATTEMPTS.has(attemptKey)) return;
    AUTO_GRAPH_BUILD_ATTEMPTS.add(attemptKey);
    graphBuildMutation.mutate();
  }, [
    buildRuntime?.docgen?.build_group_id,
    buildRuntime?.docgen?.finished_at,
    buildRuntime?.docgen?.requested_at,
    courseId,
    docgenStatus,
    graphCanAutoBuild,
    graphBuildMutation,
    graphBuildMutation.isPending,
    graphEdgeCount,
    graphNodeCount,
    overviewIsError,
    overviewLoading,
  ]);

  const cancelBuildMutation = useMutation({
    mutationFn: () => cancelKnowledgeBuild(courseId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: buildKnowledgeBuildRuntimeQueryKey(courseId) });
      queryClient.invalidateQueries({ queryKey: ["knowledge-doc-build", courseId] });
    },
  });
  const showBuildMessages =
    graphBuildMutation.isError || cancelBuildMutation.isError || Boolean(overview?.vector_status?.notice);

  return (
    <div className="flex h-full w-full flex-col bg-white dark:bg-slate-950">
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-3 pb-2 pt-[calc(0.75rem+env(safe-area-inset-top))] dark:border-slate-800 dark:bg-slate-950 lg:py-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {onClose && (
            <>
              <button
                type="button"
                onClick={onClose}
                className="flex h-9 items-center justify-center gap-1.5 rounded-lg px-2.5 text-[13px] font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100 lg:h-auto lg:rounded-md lg:px-2 lg:py-1.5"
              >
                <ChevronRight className="h-4 w-4 shrink-0" />
                <span className="lg:hidden">返回</span>
                <span className="hidden lg:inline">收起</span>
              </button>
              <div className="mx-1 hidden h-4 w-px bg-slate-200 dark:bg-slate-800 lg:block" />
            </>
          )}
          <div className="flex min-w-0 items-center gap-2">
            <span className="hidden h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-950 lg:flex">
              <Network className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">知识图谱</p>
              <p className="hidden truncate text-xs text-slate-500 dark:text-slate-400 lg:block">
                查看知识点、关系和文档来源
              </p>
            </div>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
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
            className="hidden rounded-md p-1.5 text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-500 dark:text-slate-500 dark:hover:bg-rose-500/10 dark:hover:text-rose-300 lg:inline-flex"
            title="清空当前课程知识结构"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="border-b border-slate-200 bg-slate-50/70 px-3 py-1.5 dark:border-slate-800 dark:bg-slate-900/60 lg:py-2">
        <DigestBuildProgress course={courseId} compact focus="graph" />
        {showBuildMessages ? (
          <div className="mt-2 grid gap-2">
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
            <CourseVectorNotice status={overview?.vector_status} className="rounded-lg px-3 py-2" />
          </div>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-hidden bg-white dark:bg-slate-950">
        {overviewLoading ? (
          <div className="flex h-full items-center justify-center px-6 py-10 text-sm text-slate-500 dark:text-slate-400">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            正在加载知识结构...
          </div>
        ) : null}

        {overviewIsError ? (
          <div className="p-3">
            <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
              <div className="flex items-start gap-2">
                <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
                <div>
                  <p className="mb-1 font-semibold">加载失败</p>
                  <p>{getApiErrorMessage(overviewError, "获取知识概览时发生错误。")}</p>
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {!overviewLoading && !overviewIsError ? (
          <Suspense fallback={<TabFallback message="正在加载知识图谱..." />}>
            <KnowledgeGraphView
              course={courseId}
              stats={overview?.stats ?? null}
              canBuildGraph={!graphIsActive && !graphBuildMutation.isPending}
              buildGraphPending={graphBuildMutation.isPending}
              onBuildGraph={() => graphBuildMutation.mutate()}
              onSourceRefClick={onSourceRefClick}
            />
          </Suspense>
        ) : null}
      </div>

      <Modal open={showClearConfirm} onClose={() => setShowClearConfirm(false)} title="确认清空知识数据">
        <div className="space-y-4">
          <div className="flex items-start gap-3 rounded-lg bg-rose-50 p-3 dark:bg-rose-500/10">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-rose-500" />
            <div className="text-sm text-rose-700 dark:text-rose-300">
              <p>这会删除当前课程已发布的知识文档和知识图谱相关结构。</p>
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
