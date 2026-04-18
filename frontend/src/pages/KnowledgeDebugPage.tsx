import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import {
  BookOpen,
  Database,
  FileSearch,
  GitBranch,
  Loader2,
  Network,
  RefreshCw,
} from "lucide-react";

import { apiClient, getApiErrorMessage } from "../api/client";
import {
  graphFullApiV1SubjectsSubjectKnowledgeGraphFullPost,
  graphKnowledgeUnitsApiV1SubjectsSubjectKnowledgeGraphKnowledgeUnitsPost,
} from "../api/generated/knowledge";
import type {
  DocGenGetResponse,
  FullGraphResponse,
  KnowledgeUnitResponse,
  PaginatedDataKnowledgeUnitResponse,
  SubjectVectorStatusResponse,
} from "../api/generated/model";
import type { ApiResponse, PaginatedData } from "../api/types";
import { ACTIVE_DOC_BUILD_STATUSES, DOC_BUILD_STAGE_TEXT } from "../components/knowledge-docs/utils";
import { KnowledgeGraphView } from "../components/pages/KnowledgeGraphView";
import { SubjectVectorNotice } from "../components/pages/SubjectVectorNotice";
import { Button } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";
import { buildKnowledgeDocStateQueryKey, fetchKnowledgeDocState } from "../lib/knowledgeDocs";
import {
  OVERVIEW_INCLUDE_PRESETS,
  buildKnowledgeOverviewQueryKey,
  fetchKnowledgeOverview,
} from "../lib/knowledgeOverview";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import type { FileRecord, FilesData } from "../types/files";

type DebugTab = "units" | "graph";

interface KnowledgeDebugTriggerResponse {
  action: "kg_docs_sync" | "kg_file_ingest";
  requested_at: string;
  accepted_file_uids: string[];
  message: string;
}

interface ClearKnowledgeResponse {
  subject: string;
  deleted_counts: Record<string, number>;
}

const NODE_TYPE_LABELS: Record<string, string> = {
  concept: "概念",
  definition: "定义",
  theorem: "定理",
  formula: "公式",
  example: "例题",
  exercise: "练习",
  method: "方法",
  proof_step: "推导",
  remark: "备注",
};

const NODE_TYPE_TONE: Record<string, string> = {
  concept: "bg-violet-50 text-violet-700",
  definition: "bg-emerald-50 text-emerald-700",
  theorem: "bg-indigo-50 text-indigo-700",
  formula: "bg-cyan-50 text-cyan-700",
  example: "bg-pink-50 text-pink-700",
  exercise: "bg-rose-50 text-rose-700",
  method: "bg-amber-50 text-amber-700",
  proof_step: "bg-fuchsia-50 text-fuchsia-700",
  remark: "bg-slate-100 text-slate-700",
};

async function fetchFiles(subject: string): Promise<FileRecord[]> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "GET",
    url: `/api/v1/subjects/${subject}/files`,
  });
  return response.data?.items ?? [];
}

async function fetchGraph(subject: string): Promise<FullGraphResponse | null> {
  return (
    unwrapOrvalResponse<FullGraphResponse>(
      await graphFullApiV1SubjectsSubjectKnowledgeGraphFullPost(subject),
    ) ?? null
  );
}

async function fetchUnits(
  subject: string,
  page: number,
  knowledgeUnitType?: string,
): Promise<PaginatedDataKnowledgeUnitResponse> {
  return (
    unwrapOrvalResponse<PaginatedDataKnowledgeUnitResponse>(
      await graphKnowledgeUnitsApiV1SubjectsSubjectKnowledgeGraphKnowledgeUnitsPost(subject, {
        page,
        size: 30,
        knowledge_unit_type: knowledgeUnitType ?? null,
      }),
    ) ?? {
      items: [],
      page,
      size: 30,
      total: 0,
      pages: 0,
    }
  );
}

function formatRelativeTime(value?: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function resolveBuildStatusLabel(
  build:
    | {
        status?: string | null;
        stage?: string | null;
        current_stage_description?: string | null;
      }
    | null
    | undefined,
): string {
  if (!build) return "空闲";

  const status = (build.status ?? "").trim();
  const stage = (build.stage ?? "").trim();
  const description = build.current_stage_description?.trim();

  if (ACTIVE_DOC_BUILD_STATUSES.has(status)) {
    if (description) return `进行中: ${description}`;
    if (stage && DOC_BUILD_STAGE_TEXT[stage]) return `进行中: ${DOC_BUILD_STAGE_TEXT[stage]}`;
    return "进行中";
  }

  if (status === "completed") return "已完成";
  if (status === "failed") return "失败";
  if (status === "cancelled") return "已取消";

  return description || stage || "空闲";
}

export function KnowledgeDebugPage() {
  const { subjectId } = useParams<{ subjectId: string }>();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [activeTab, setActiveTab] = useState<DebugTab>("units");
  const [page, setPage] = useState(1);
  const [knowledgeUnitType, setKnowledgeUnitType] = useState<string>("");
  const [lastTrigger, setLastTrigger] = useState<KnowledgeDebugTriggerResponse | null>(null);

  const overviewInclude = useMemo(() => OVERVIEW_INCLUDE_PRESETS.knowledgeGraph, []);

  const docsStateQuery = useQuery({
    queryKey: subjectId ? buildKnowledgeDocStateQueryKey(subjectId) : ["knowledge-doc-state-empty"],
    queryFn: () => fetchKnowledgeDocState(subjectId ?? ""),
    enabled: Boolean(subjectId),
    refetchInterval: (query) => {
      const build = (query.state.data as DocGenGetResponse | undefined)?.build;
      return ACTIVE_DOC_BUILD_STATUSES.has((build?.status ?? "").trim()) ? 3000 : false;
    },
  });

  const buildStatus = (docsStateQuery.data as DocGenGetResponse | undefined)?.build ?? null;
  const isBuildActive = ACTIVE_DOC_BUILD_STATUSES.has((buildStatus?.status ?? "").trim());

  const overviewQuery = useQuery({
    queryKey: subjectId ? buildKnowledgeOverviewQueryKey(subjectId, overviewInclude) : ["knowledge-overview-empty"],
    queryFn: () => fetchKnowledgeOverview(subjectId ?? "", overviewInclude),
    enabled: Boolean(subjectId),
    refetchInterval: isBuildActive ? 5000 : false,
  });

  const graphQuery = useQuery({
    queryKey: ["knowledge-debug-graph", subjectId],
    queryFn: () => fetchGraph(subjectId ?? ""),
    enabled: Boolean(subjectId),
    refetchInterval: isBuildActive ? 5000 : false,
  });

  const unitsQuery = useQuery({
    queryKey: ["knowledge-debug-units", subjectId, page, knowledgeUnitType],
    queryFn: () => fetchUnits(subjectId ?? "", page, knowledgeUnitType || undefined),
    enabled: Boolean(subjectId),
    refetchInterval: isBuildActive ? 5000 : false,
  });

  const filesQuery = useQuery({
    queryKey: ["knowledge-debug-files", subjectId],
    queryFn: () => fetchFiles(subjectId ?? ""),
    enabled: Boolean(subjectId),
    refetchInterval: isBuildActive ? 5000 : false,
  });

  const readyFiles = useMemo(
    () => (filesQuery.data ?? []).filter((file) => file.markdown_ready),
    [filesQuery.data],
  );
  const digestReadyFiles = useMemo(
    () =>
      readyFiles.filter(
        (file) => file.status === "completed" && file.ingest_status === "ready_for_digest",
      ),
    [readyFiles],
  );

  const unitPage = (unitsQuery.data as PaginatedData<KnowledgeUnitResponse> | undefined) ?? null;
  const units = unitPage?.items ?? [];
  const totalPages = Math.max(1, unitPage?.pages ?? 1);
  const totalUnits = unitPage?.total ?? 0;
  const vectorStatus =
    overviewQuery.data?.vector_status ??
    docsStateQuery.data?.vector_status ??
    ({
      mode: "enabled",
      notice: null,
      embedding_model: null,
      vector_table: null,
    } satisfies SubjectVectorStatusResponse);

  const nodeTypeOptions = useMemo(() => {
    const graphNodes = graphQuery.data?.nodes ?? [];
    return Array.from(new Set(graphNodes.map((node) => node.knowledge_unit_type))).sort();
  }, [graphQuery.data]);

  const refreshKnowledgeViews = () => {
    if (!subjectId) return;
    void queryClient.invalidateQueries({ queryKey: ["knowledge-overview", subjectId] });
    void queryClient.invalidateQueries({ queryKey: ["knowledge-debug-graph", subjectId] });
    void queryClient.invalidateQueries({ queryKey: ["knowledge-debug-units", subjectId] });
    void queryClient.invalidateQueries({ queryKey: ["knowledge-debug-files", subjectId] });
    void queryClient.invalidateQueries({ queryKey: buildKnowledgeDocStateQueryKey(subjectId) });
    void queryClient.invalidateQueries({ queryKey: ["graph-node-detail", subjectId] });
  };

  const kgDocsSyncMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient<ApiResponse<KnowledgeDebugTriggerResponse>>({
        method: "POST",
        url: `/api/v1/subjects/${subjectId}/knowledge/debug/kg-docs-sync`,
        data: {},
      });
      return response.data ?? null;
    },
    onSuccess: (data) => {
      if (!data) return;
      setLastTrigger(data);
      refreshKnowledgeViews();
      toast({
        title: "已触发 kg_docs_sync",
        description: data.message,
        variant: "success",
      });
    },
  });

  const kgFileIngestMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient<ApiResponse<KnowledgeDebugTriggerResponse>>({
        method: "POST",
        url: `/api/v1/subjects/${subjectId}/knowledge/debug/kg-file-ingest`,
        data: { file_uids: digestReadyFiles.map((file) => file.uid) },
      });
      return response.data ?? null;
    },
    onSuccess: (data) => {
      if (!data) return;
      setLastTrigger(data);
      refreshKnowledgeViews();
      toast({
        title: "已触发 kg_file_ingest",
        description: data.message,
        variant: "success",
      });
    },
  });

  const clearGraphMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient<ApiResponse<ClearKnowledgeResponse>>({
        method: "POST",
        url: `/api/v1/subjects/${subjectId}/knowledge/debug/clear-graph`,
      });
      return response.data ?? null;
    },
    onSuccess: (data) => {
      if (!data) return;
      setLastTrigger(null);
      refreshKnowledgeViews();
      toast({
        title: "已清空知识图谱数据",
        description: `已删除 ${data.deleted_counts.knowledge_unit ?? 0} 个知识单元，${data.deleted_counts.knowledge_edge ?? 0} 条知识边。`,
        variant: "success",
      });
    },
  });

  if (!subjectId) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-sm text-slate-500">
        未找到学科。
      </div>
    );
  }

  return (
    <div className="min-h-full bg-slate-50">
      <div className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 pb-6 pt-20 md:px-6 lg:px-8">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-2">
              <div className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-3 py-1 text-xs font-medium text-white">
                <Database className="h-3.5 w-3.5" />
                知识调试
              </div>
              <div>
                <h1 className="text-2xl font-semibold text-slate-900">知识单元与知识图谱</h1>
                <p className="mt-1 text-sm text-slate-500">
                  这里可以单独查看知识单元、知识图谱，并直接触发 `kg_docs_sync` 和 `kg_file_ingest`。
                </p>
              </div>
              <Button
                variant="outline"
                className="border-rose-300 text-rose-700 hover:bg-rose-50"
                onClick={() => {
                  if (!window.confirm("确认清空当前学科的所有知识单元和知识图谱边吗？这不会删除原始文件和知识文档。")) {
                    return;
                  }
                  void clearGraphMutation.mutateAsync();
                }}
                disabled={clearGraphMutation.isPending || isBuildActive}
              >
                {clearGraphMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Database className="h-4 w-4" />
                )}
                清空知识图谱
              </Button>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                onClick={() => void Promise.all([
                  docsStateQuery.refetch(),
                  overviewQuery.refetch(),
                  graphQuery.refetch(),
                  unitsQuery.refetch(),
                  filesQuery.refetch(),
                ])}
                disabled={
                  docsStateQuery.isFetching ||
                  overviewQuery.isFetching ||
                  graphQuery.isFetching ||
                  unitsQuery.isFetching ||
                  filesQuery.isFetching
                }
              >
                <RefreshCw
                  className={`h-4 w-4 ${
                    docsStateQuery.isFetching ||
                    overviewQuery.isFetching ||
                    graphQuery.isFetching ||
                    unitsQuery.isFetching ||
                    filesQuery.isFetching
                      ? "animate-spin"
                      : ""
                  }`}
                />
                刷新状态
              </Button>
              <Button
                variant="outline"
                onClick={() => void kgDocsSyncMutation.mutateAsync()}
                disabled={kgDocsSyncMutation.isPending || !docsStateQuery.data?.exists || isBuildActive}
              >
                {kgDocsSyncMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <BookOpen className="h-4 w-4" />
                )}
                调试 kg_docs_sync
              </Button>
              <Button
                onClick={() => void kgFileIngestMutation.mutateAsync()}
                disabled={kgFileIngestMutation.isPending || digestReadyFiles.length === 0 || isBuildActive}
              >
                {kgFileIngestMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <GitBranch className="h-4 w-4" />
                )}
                调试 kg_file_ingest
              </Button>
              <Button
                variant="outline"
                className="border-rose-300 text-rose-700 hover:bg-rose-50"
                onClick={() => {
                  if (!window.confirm("确认清空当前学科的所有知识单元和知识图谱边吗？这不会删除原始文件和知识文档。")) {
                    return;
                  }
                  void clearGraphMutation.mutateAsync();
                }}
                disabled={clearGraphMutation.isPending || isBuildActive}
              >
                {clearGraphMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Database className="h-4 w-4" />
                )}
                清空知识图谱
              </Button>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-4">
            <div className="border border-slate-200 bg-white px-4 py-3">
              <div className="text-xs text-slate-500">知识单元</div>
              <div className="mt-1 text-2xl font-semibold text-slate-900">
                {overviewQuery.data?.stats?.node_count ?? 0}
              </div>
            </div>
            <div className="border border-slate-200 bg-white px-4 py-3">
              <div className="text-xs text-slate-500">知识边</div>
              <div className="mt-1 text-2xl font-semibold text-slate-900">
                {overviewQuery.data?.stats?.edge_count ?? 0}
              </div>
            </div>
            <div className="border border-slate-200 bg-white px-4 py-3">
              <div className="text-xs text-slate-500">可摄取文件</div>
              <div className="mt-1 text-2xl font-semibold text-slate-900">{digestReadyFiles.length}</div>
            </div>
            <div className="border border-slate-200 bg-white px-4 py-3">
              <div className="text-xs text-slate-500">当前构建阶段</div>
              <div className="mt-1 text-sm font-medium text-slate-900">
                {resolveBuildStatusLabel(buildStatus)}
              </div>
            </div>
          </div>

          <SubjectVectorNotice status={vectorStatus} />

          {lastTrigger ? (
            <div className="border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
              <div className="font-medium">{lastTrigger.message}</div>
              <div className="mt-1 text-xs text-emerald-600">
                {lastTrigger.action} · {formatRelativeTime(lastTrigger.requested_at) ?? lastTrigger.requested_at}
              </div>
            </div>
          ) : null}

          {(kgDocsSyncMutation.isError || kgFileIngestMutation.isError || clearGraphMutation.isError) ? (
            <div className="border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {getApiErrorMessage(
                kgDocsSyncMutation.error ?? kgFileIngestMutation.error ?? clearGraphMutation.error,
                "调试触发失败",
              )}
            </div>
          ) : null}
        </div>
      </div>

      <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-4 px-4 py-6 md:px-6 lg:px-8">
        <div className="flex items-center gap-2 border-b border-slate-200">
          {[
            { id: "units" as const, label: "知识单元", icon: FileSearch },
            { id: "graph" as const, label: "知识图谱", icon: Network },
          ].map((tab) => {
            const Icon = tab.icon;
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`inline-flex items-center gap-2 border-b-2 px-3 py-3 text-sm transition-colors ${
                  active
                    ? "border-slate-900 text-slate-900"
                    : "border-transparent text-slate-500 hover:text-slate-700"
                }`}
              >
                <Icon className="h-4 w-4" />
                {tab.label}
              </button>
            );
          })}
        </div>

        {activeTab === "units" ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  setKnowledgeUnitType("");
                  setPage(1);
                }}
                className={`rounded-md px-3 py-1.5 text-xs transition-colors ${
                  knowledgeUnitType === ""
                    ? "bg-slate-900 text-white"
                    : "border border-slate-200 bg-white text-slate-600"
                }`}
              >
                全部
              </button>
              {nodeTypeOptions.map((type) => (
                <button
                  key={type}
                  type="button"
                  onClick={() => {
                    setKnowledgeUnitType(type);
                    setPage(1);
                  }}
                  className={`rounded-md px-3 py-1.5 text-xs transition-colors ${
                    knowledgeUnitType === type
                      ? "bg-slate-900 text-white"
                      : "border border-slate-200 bg-white text-slate-600"
                  }`}
                >
                  {NODE_TYPE_LABELS[type] ?? type}
                </button>
              ))}
            </div>

            {unitsQuery.isLoading ? (
              <div className="flex items-center justify-center py-20 text-slate-500">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                正在加载知识单元...
              </div>
            ) : unitsQuery.isError ? (
              <div className="border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {getApiErrorMessage(unitsQuery.error, "加载知识单元失败")}
              </div>
            ) : (
              <>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {units.map((unit) => {
                    const typeTone = NODE_TYPE_TONE[unit.knowledge_unit_type] ?? "bg-slate-100 text-slate-700";
                    return (
                      <div key={unit.id} className="border border-slate-200 bg-white p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-sm font-medium text-slate-900">{unit.canonical_name}</div>
                            <div className="mt-1 text-xs text-slate-500">ID {unit.id}</div>
                          </div>
                          <span className={`rounded-md px-2 py-1 text-[11px] ${typeTone}`}>
                            {NODE_TYPE_LABELS[unit.knowledge_unit_type] ?? unit.knowledge_unit_type}
                          </span>
                        </div>
                        <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
                          <span>状态: {unit.status}</span>
                          <span>置信度: {Math.round(unit.confidence * 100)}%</span>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {units.length === 0 ? (
                  <div className="border border-slate-200 bg-white px-4 py-10 text-center text-sm text-slate-500">
                    当前还没有知识单元。
                  </div>
                ) : null}

                <div className="flex items-center justify-between border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
                  <span>共 {totalUnits} 个知识单元</span>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPage((value) => Math.max(1, value - 1))}
                      disabled={page <= 1}
                    >
                      上一页
                    </Button>
                    <span>
                      第 {page} / {totalPages} 页
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
                      disabled={page >= totalPages}
                    >
                      下一页
                    </Button>
                  </div>
                </div>
              </>
            )}
          </div>
        ) : (
          <div className="min-h-[70vh] border border-slate-200 bg-white p-4">
            {graphQuery.isLoading ? (
              <div className="flex h-[60vh] items-center justify-center text-slate-500">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                正在加载知识图谱...
              </div>
            ) : graphQuery.isError ? (
              <div className="border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {getApiErrorMessage(graphQuery.error, "加载知识图谱失败")}
              </div>
            ) : (
              <KnowledgeGraphView subject={subjectId} overviewGraph={graphQuery.data ?? null} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
