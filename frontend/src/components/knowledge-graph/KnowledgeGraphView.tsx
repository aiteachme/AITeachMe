import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  Loader2,
  Network,
  List,
  Share2,
  RefreshCw,
} from "lucide-react";
import {
  graphKnowledgeUnitsApiV1CoursesCourseIdKnowledgeGraphKnowledgeUnitsPost,
} from "../../api/generated/knowledge";
import type { KnowledgeOverviewStats, KnowledgeUnitResponse } from "../../api/generated/model";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { Card, CardContent } from "../ui/Card";
import { Button } from "../ui/Button";
import { MarkdownViewer } from "../ui/MarkdownViewer";
import { ForceGraphView } from "./ForceGraphView";
import { EvidenceContextModal } from "./EvidenceContextModal";
import { KnowledgeGraphNodeDetailPanel, type KnowledgeGraphSourceRefNavigationTarget } from "./KnowledgeGraphNodeDetailPanel";
import { KnowledgeGraphInsightsView } from "./KnowledgeGraphInsightsView";

const NODE_TYPE_STYLE: Record<string, { label: string; color: string }> = {
  topic: { label: "主题模块", color: "bg-indigo-50 text-indigo-600" },
  concept: { label: "概念术语", color: "bg-blue-50 text-blue-600" },
  principle: { label: "原理性质", color: "bg-teal-50 text-teal-600" },
  formula_model: { label: "公式模型", color: "bg-cyan-50 text-cyan-700" },
  procedure: { label: "方法步骤", color: "bg-amber-50 text-amber-600" },
  skill: { label: "解题技能", color: "bg-rose-50 text-rose-600" },
  misconception: { label: "易错辨析", color: "bg-red-50 text-red-600" },
  application_case: { label: "应用案例", color: "bg-pink-50 text-pink-600" },
  resource: { label: "学习资源", color: "bg-slate-100 text-slate-600" },
};

const NODE_TYPES = [
  { value: undefined, label: "全部" },
  { value: "topic", label: "主题模块" },
  { value: "concept", label: "概念术语" },
  { value: "principle", label: "原理性质" },
  { value: "formula_model", label: "公式模型" },
  { value: "procedure", label: "方法步骤" },
  { value: "skill", label: "解题技能" },
  { value: "misconception", label: "易错辨析" },
  { value: "application_case", label: "应用案例" },
  { value: "resource", label: "学习资源" },
];

type ViewMode = "list" | "graph" | "insights";

export function KnowledgeGraphView({
  course,
  stats,
  onBuildGraph,
  buildGraphPending = false,
  canBuildGraph = false,
  onSourceRefClick,
}: {
  course: string;
  stats: KnowledgeOverviewStats | null;
  onBuildGraph?: () => void;
  buildGraphPending?: boolean;
  canBuildGraph?: boolean;
  onSourceRefClick?: (ref: KnowledgeGraphSourceRefNavigationTarget) => void;
}) {
  const [viewMode, setViewMode] = useState<ViewMode>("insights");
  const [nodeType, setNodeType] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [evidenceModalState, setEvidenceModalState] = useState<{ chunkId: number; quoteText: string } | null>(null);
  const pageSize = 30;

  const graphNodeCount = Number(stats?.node_count ?? 0);
  const graphEdgeCount = Number(stats?.edge_count ?? 0);

  const { data: listData, isLoading: listLoading } = useQuery({
    queryKey: ["graph-node-list", course, nodeType ?? "all", page, pageSize],
    queryFn: async () =>
      unwrapOrvalResponse(
        await graphKnowledgeUnitsApiV1CoursesCourseIdKnowledgeGraphKnowledgeUnitsPost(course, {
          page,
          size: pageSize,
          knowledge_unit_type: nodeType ?? null,
        }),
      ) ?? null,
    enabled: viewMode === "list" && Boolean(course),
    retry: false,
  });

  const nodes = listData?.items ?? [];
  const total = listData?.total ?? (nodeType ? 0 : graphNodeCount);
  const totalPages = listData?.pages ?? Math.max(1, Math.ceil(total / pageSize));
  const displayPage = listData?.page ?? page;

  const viewButtonClass = (active: boolean) =>
    `flex h-8 items-center gap-1.5 rounded-md px-2 text-xs transition-all sm:px-3 ${
      active
        ? "bg-white text-slate-900 shadow-sm font-semibold dark:bg-slate-800 dark:text-slate-100"
        : "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
    }`;

  const viewToggle = (
    <div className="flex min-w-0 flex-wrap items-center gap-1 rounded-lg bg-slate-100 p-0.5 dark:bg-slate-900">
      <button
        type="button"
        aria-pressed={viewMode === "insights"}
        title="按学习路径阅读课程结构"
        onClick={() => setViewMode("insights")}
        className={viewButtonClass(viewMode === "insights")}
      >
        <BarChart3 className="h-3.5 w-3.5" />
        学习地图
      </button>
      <button
        type="button"
        aria-pressed={viewMode === "graph"}
        title="探索节点之间的直接关系"
        onClick={() => setViewMode("graph")}
        className={viewButtonClass(viewMode === "graph")}
      >
        <Share2 className="h-3.5 w-3.5" />
        关系网络
      </button>
      <button
        type="button"
        aria-pressed={viewMode === "list"}
        title="按类型查找全部知识点"
        onClick={() => setViewMode("list")}
        className={viewButtonClass(viewMode === "list")}
      >
        <List className="h-3.5 w-3.5" />
        节点列表
      </button>
    </div>
  );

  if (graphNodeCount === 0 && !nodeType) {
    return (
      <div className="knowledge-graph-view flex h-full min-h-0 flex-col bg-white dark:bg-slate-950">
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-3 py-2 dark:border-slate-800">
          {viewToggle}
          <span className="shrink-0 text-xs text-slate-400">等待构建</span>
        </div>
        <div className="flex min-h-0 flex-1 items-center justify-center p-6">
          <div className="flex max-w-sm flex-col items-center text-center text-slate-500">
            <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-slate-100 text-slate-400 dark:bg-slate-900 dark:text-slate-500">
              <Network className="h-5 w-5" />
            </span>
            <p className="mt-3 text-sm font-medium text-slate-700 dark:text-slate-200">暂无知识节点</p>
            <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">构建完成后会在这里展示知识点与关系。</p>
            {onBuildGraph && canBuildGraph ? (
              <Button
                type="button"
                variant="outline"
                onClick={onBuildGraph}
                disabled={buildGraphPending}
                className="mt-4 h-8 gap-1.5 px-3 text-xs"
              >
                {buildGraphPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                构建图谱
              </Button>
            ) : null}
          </div>
        </div>
        <EvidenceContextModal
          open={!!evidenceModalState}
          onClose={() => setEvidenceModalState(null)}
          course={course}
          chunkId={evidenceModalState?.chunkId ?? null}
          quoteText={evidenceModalState?.quoteText}
        />
      </div>
    );
  }

  return (
    <div className="knowledge-graph-view flex h-full min-h-0 flex-col bg-white dark:bg-slate-950">
      {viewMode === "graph" && (
        <ForceGraphView
          course={course}
          toolbar={viewToggle}
          onEvidenceClick={(chunkId, quoteText) => setEvidenceModalState({ chunkId, quoteText })}
          onSourceRefClick={onSourceRefClick}
          totalNodeCount={graphNodeCount}
          totalEdgeCount={graphEdgeCount}
        />
      )}

      {viewMode === "list" && (
        <div className="flex h-full flex-col gap-4 overflow-auto p-3 lg:flex-row">
          <div className={`${selectedNodeId ? "lg:w-1/2" : "w-full"} min-w-0 space-y-4 transition-all`}>
            <div className="flex items-center gap-3 flex-wrap">
              {viewToggle}
              <div className="flex flex-wrap gap-1.5 items-center">
                {NODE_TYPES.map((t) => (
                  <button
                    key={t.label}
                    onClick={() => {
                      setNodeType(t.value);
                      setPage(1);
                    }}
                    className={`text-xs px-2.5 py-1 rounded-full transition-colors ${
                      nodeType === t.value
                        ? "bg-slate-800 text-white dark:bg-slate-100 dark:text-slate-900"
                        : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>

            {listLoading ? (
              <div className="flex items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                加载节点...
              </div>
            ) : nodes.length > 0 ? (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {nodes.map((node: KnowledgeUnitResponse) => {
                  const typeStyle = NODE_TYPE_STYLE[node.knowledge_unit_type] ?? {
                    label: node.knowledge_unit_type,
                    color: "bg-slate-100 text-slate-600",
                  };
                  const isSelected = selectedNodeId === node.id;
                  return (
                    <button
                      key={node.id}
                      onClick={() => setSelectedNodeId(isSelected ? null : node.id)}
                      className={`text-left px-3 py-2.5 rounded-lg border transition-all ${
                        isSelected
                          ? "border-slate-400 bg-slate-50 shadow-sm dark:border-slate-600 dark:bg-slate-900"
                          : "border-slate-200 hover:border-slate-300 hover:shadow-sm dark:border-slate-800 dark:hover:border-slate-700"
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="flex-1 truncate text-sm text-slate-800 dark:text-slate-200 [&_p]:mb-0 [&_p]:inline">
                          <MarkdownViewer content={node.canonical_name} />
                        </span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded shrink-0 ${typeStyle.color}`}>
                          {typeStyle.label}
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
                当前筛选下暂无节点
              </div>
            )}

            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-2 pt-2">
                <Button variant="outline" size="sm" disabled={displayPage <= 1} onClick={() => setPage((p) => p - 1)}>
                  上一页
                </Button>
                <span className="text-xs text-slate-500">
                  {displayPage} / {totalPages}
                </span>
                <Button variant="outline" size="sm" disabled={displayPage >= totalPages} onClick={() => setPage((p) => p + 1)}>
                  下一页
                </Button>
              </div>
            )}
          </div>

          {selectedNodeId && (
            <div className="min-w-0 lg:w-1/2">
              <Card>
                <CardContent className="pt-6">
                  <KnowledgeGraphNodeDetailPanel
                    course={course}
                    nodeId={selectedNodeId}
                    onClose={() => setSelectedNodeId(null)}
                    onNavigate={(id) => setSelectedNodeId(id)}
                    onEvidenceClick={(chunkId, quoteText) => setEvidenceModalState({ chunkId, quoteText })}
                    onSourceRefClick={onSourceRefClick}
                    showTeachingRole={false}
                  />
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      )}

      {viewMode === "insights" && (
        <KnowledgeGraphInsightsView
          course={course}
          toolbar={viewToggle}
        />
      )}

      <EvidenceContextModal
        open={!!evidenceModalState}
        onClose={() => setEvidenceModalState(null)}
        course={course}
        chunkId={evidenceModalState?.chunkId ?? null}
        quoteText={evidenceModalState?.quoteText}
      />
    </div>
  );
}
