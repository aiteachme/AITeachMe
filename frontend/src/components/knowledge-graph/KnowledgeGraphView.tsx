import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Loader2,
  Network,
  ChevronRight,
  X,
  Link2,
  Tag,
  FileText,
  List,
  Share2,
  ExternalLink,
} from "lucide-react";
import {
  graphKnowledgeUnitDetailApiV1SubjectsSubjectIdKnowledgeGraphKnowledgeUnitsDetailPost,
} from "../../api/generated/knowledge";
import type { FullGraphResponse, KnowledgeUnitResponse } from "../../api/generated/model";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { Card, CardContent } from "../ui/Card";
import { Button } from "../ui/Button";
import { MarkdownViewer } from "../ui/MarkdownViewer";
import { ForceGraphView } from "./ForceGraphView";
import { EvidenceContextModal } from "./EvidenceContextModal";

const NODE_TYPE_STYLE: Record<string, { label: string; color: string }> = {
  concept: { label: "概念", color: "bg-purple-50 text-purple-600" },
  definition: { label: "定义", color: "bg-emerald-50 text-emerald-600" },
  theorem: { label: "定理", color: "bg-indigo-50 text-indigo-600" },
  formula: { label: "公式", color: "bg-cyan-50 text-cyan-600" },
  example: { label: "示例", color: "bg-pink-50 text-pink-600" },
  exercise: { label: "练习", color: "bg-rose-50 text-rose-600" },
  method: { label: "方法", color: "bg-amber-50 text-amber-600" },
  proof_step: { label: "证明步骤", color: "bg-violet-50 text-violet-600" },
  remark: { label: "备注", color: "bg-slate-100 text-slate-600" },
};

function NodeDetailPanel({
  subject,
  nodeId,
  onClose,
  onNavigate,
  onEvidenceClick,
}: {
  subject: string;
  nodeId: number;
  onClose: () => void;
  onNavigate: (id: number) => void;
  onEvidenceClick: (chunkId: number, quoteText: string) => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["graph-node-detail", subject, nodeId],
    queryFn: async () =>
      unwrapOrvalResponse(
        await graphKnowledgeUnitDetailApiV1SubjectsSubjectIdKnowledgeGraphKnowledgeUnitsDetailPost(subject, {
          knowledge_unit_id: nodeId,
        }),
      ) ?? null,
    enabled: !!nodeId,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8 text-slate-400">
        <Loader2 className="w-4 h-4 animate-spin mr-2" />加载中...
      </div>
    );
  }

  if (!data) return null;

  const typeStyle = NODE_TYPE_STYLE[data.knowledge_unit_type] ?? {
    label: data.knowledge_unit_type,
    color: "bg-slate-100 text-slate-600",
  };

  const aliases = data.aliases ?? [];
  const incidentEdges = data.incident_edges ?? [];
  const evidenceList = data.evidence ?? [];
  const sourceRefs = data.source_refs ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-100">
              <MarkdownViewer content={data.canonical_name} />
            </h3>
            <span className={`text-xs px-1.5 py-0.5 rounded ${typeStyle.color}`}>{typeStyle.label}</span>
          </div>
          <p className="text-xs text-slate-400">置信度：{Math.round(data.confidence * 100)}%</p>
        </div>
        <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-200">
          <X className="w-4 h-4" />
        </button>
      </div>

      {data.current_revision && (
        <div className="space-y-2">
          {data.current_revision.summary && (
            <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600 dark:bg-slate-900 dark:text-slate-300">
              <MarkdownViewer content={data.current_revision.summary} />
            </div>
          )}
          {data.current_revision.body && (
            <div className="max-h-48 overflow-y-auto rounded-lg border border-slate-100 p-3 text-sm dark:border-slate-800 dark:text-slate-300">
              <MarkdownViewer content={data.current_revision.body} />
            </div>
          )}
        </div>
      )}

      {aliases.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500 mb-2">
            <Tag className="w-3 h-3" />别名
          </div>
          <div className="flex flex-wrap gap-1.5">
            {aliases.map((alias: { id: number; is_primary: boolean; alias: string }) => (
              <span
                key={alias.id}
                className={`text-xs px-2 py-0.5 rounded-full ${
                  alias.is_primary ? "bg-slate-800 text-white dark:bg-slate-100 dark:text-slate-900" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                }`}
              >
                {alias.alias}
              </span>
            ))}
          </div>
        </div>
      )}

      {incidentEdges.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500 mb-2">
            <Link2 className="w-3 h-3" />关联知识 ({incidentEdges.length})
          </div>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {incidentEdges.map((edge: { id: number; other_node_id: number; direction: string; other_node_name: string; edge_type: string }) => (
              <button
                key={edge.id}
                onClick={() => onNavigate(edge.other_node_id)}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/70"
              >
                <span className="text-slate-400">{edge.direction === "outgoing" ? "->" : "<-"}</span>
                <span className="flex-1 truncate text-slate-700 dark:text-slate-300">{edge.other_node_name}</span>
                <span className="text-[10px] text-slate-400">{edge.edge_type}</span>
                <ChevronRight className="w-3 h-3 text-slate-300" />
              </button>
            ))}
          </div>
        </div>
      )}

      {sourceRefs.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500 mb-2">
            <FileText className="w-3 h-3" />图谱来源 ({sourceRefs.length})
          </div>
          <div className="space-y-1.5 max-h-40 overflow-y-auto">
            {sourceRefs.map((ref: { id: number; chapter_index?: number; chapter_title?: string | null; doc_version_no?: number; source_kind?: string; source_file_ids?: string[]; quote_text?: string }) => (
              <div key={ref.id} className="rounded border border-slate-100 bg-slate-50 p-2 text-xs text-slate-600 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-300">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-medium text-slate-700 dark:text-slate-200">
                    {ref.chapter_title || (ref.chapter_index ? `第 ${ref.chapter_index} 章` : "知识文档")}
                  </span>
                  {ref.doc_version_no ? <span className="shrink-0 text-[10px] text-slate-400">v{ref.doc_version_no}</span> : null}
                </div>
                <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-slate-400">
                  {ref.source_kind ? <span>{ref.source_kind}</span> : null}
                  {ref.source_file_ids?.length ? <span>资料 {ref.source_file_ids.join(", ")}</span> : null}
                </div>
                {ref.quote_text ? <p className="mt-1 line-clamp-2 text-slate-500 dark:text-slate-400">{ref.quote_text}</p> : null}
              </div>
            ))}
          </div>
        </div>
      )}

      {evidenceList.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500 mb-2">
            <FileText className="w-3 h-3" />来源证据 ({evidenceList.length})
          </div>
          <div className="space-y-1.5 max-h-40 overflow-y-auto">
            {evidenceList.map((ev: { id: number; chunk_id: number; quote_text: string; evidence_role: string; confidence: number }) => (
              <button
                key={ev.id}
                onClick={() => onEvidenceClick(ev.chunk_id, ev.quote_text)}
                className="group w-full cursor-pointer rounded border-l-2 border-slate-300 bg-slate-50 p-2 text-left text-xs text-slate-600 transition-colors hover:border-amber-400 hover:bg-amber-50/50 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:border-amber-400/70 dark:hover:bg-amber-500/10"
              >
                <p className="line-clamp-3">{ev.quote_text}</p>
                <div className="flex items-center justify-between mt-1">
                  <p className="text-[10px] text-slate-400">
                    {ev.evidence_role} 路 {Math.round(ev.confidence * 100)}%
                  </p>
                  <ExternalLink className="w-3 h-3 text-slate-300 group-hover:text-amber-500 transition-colors" />
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

const NODE_TYPES = [
  { value: undefined, label: "全部" },
  { value: "concept", label: "概念" },
  { value: "definition", label: "定义" },
  { value: "theorem", label: "定理" },
  { value: "formula", label: "公式" },
  { value: "example", label: "示例" },
  { value: "exercise", label: "练习" },
  { value: "method", label: "方法" },
  { value: "proof_step", label: "推导" },
  { value: "remark", label: "补充" },
];

type ViewMode = "list" | "graph";

export function KnowledgeGraphView({
  subject,
  overviewGraph,
}: {
  subject: string;
  overviewGraph: FullGraphResponse | null;
}) {
  const [viewMode, setViewMode] = useState<ViewMode>("graph");
  const [nodeType, setNodeType] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [evidenceModalState, setEvidenceModalState] = useState<{ chunkId: number; quoteText: string } | null>(null);
  const pageSize = 30;

  const localListData = useMemo(() => {
    if (!overviewGraph) return null;

    const allNodes = overviewGraph?.nodes ?? [];
    const filtered = nodeType
      ? allNodes.filter((node) => node.knowledge_unit_type.toLowerCase() === nodeType.toLowerCase())
      : allNodes;

    const total = filtered.length;
    const pages = Math.max(1, Math.ceil(total / pageSize));
    const safePage = Math.min(page, pages);
    const start = (safePage - 1) * pageSize;

    return {
      items: filtered.slice(start, start + pageSize),
      total,
      pages,
      page: safePage,
    };
  }, [overviewGraph, nodeType, page]);

  const nodes = localListData?.items ?? [];
  const total = localListData?.total ?? 0;
  const totalPages = localListData?.pages ?? Math.max(1, Math.ceil(total / pageSize));
  const displayPage = localListData?.page ?? page;

  const viewToggle = (
    <div className="flex shrink-0 items-center gap-1 rounded-lg bg-slate-100 p-0.5 dark:bg-slate-900">
      <button
        onClick={() => setViewMode("graph")}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-all ${
          viewMode === "graph"
            ? "bg-white text-slate-900 shadow-sm font-medium dark:bg-slate-800 dark:text-slate-100"
            : "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
        }`}
      >
        <Share2 className="w-3.5 h-3.5" />图谱
      </button>
      <button
        onClick={() => setViewMode("list")}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-all ${
          viewMode === "list"
            ? "bg-white text-slate-900 shadow-sm font-medium dark:bg-slate-800 dark:text-slate-100"
            : "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
        }`}
      >
        <List className="w-3.5 h-3.5" />节点列表
      </button>
    </div>
  );

  if (total === 0 && !nodeType) {
    return (
      <div className="knowledge-graph-view flex h-full min-h-0 flex-col bg-white dark:bg-slate-950">
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-3 py-2 dark:border-slate-800">
          {viewToggle}
          <span className="shrink-0 text-xs text-slate-400">0 节点 · 0 关系</span>
        </div>
        <div className="flex min-h-0 flex-1 items-center justify-center p-6">
          <div className="flex max-w-sm flex-col items-center text-center text-slate-500">
            <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-slate-100 text-slate-400 dark:bg-slate-900 dark:text-slate-500">
              <Network className="h-5 w-5" />
            </span>
            <p className="mt-3 text-sm font-medium text-slate-700 dark:text-slate-200">暂无知识节点</p>
            <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">构建完成后会在这里展示知识点与关系。</p>
          </div>
        </div>
        <EvidenceContextModal
          open={!!evidenceModalState}
          onClose={() => setEvidenceModalState(null)}
          subject={subject}
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
          subject={subject}
          toolbar={viewToggle}
          onEvidenceClick={(chunkId, quoteText) => setEvidenceModalState({ chunkId, quoteText })}
          fullGraphData={overviewGraph}
        />
      )}

      {viewMode === "list" && (
        <div className="flex h-full gap-4 overflow-auto p-3">
          <div className={`${selectedNodeId ? "w-1/2" : "w-full"} space-y-4 transition-all`}>
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
                <span className="text-xs text-slate-400 ml-2">共 {total} 个节点</span>
              </div>
            </div>

            {nodes.length > 0 ? (
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
                      <div className="mt-1 text-[10px] text-slate-400">置信度：{Math.round(node.confidence * 100)}%</div>
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
            <div className="w-1/2">
              <Card>
                <CardContent className="pt-6">
                  <NodeDetailPanel
                    subject={subject}
                    nodeId={selectedNodeId}
                    onClose={() => setSelectedNodeId(null)}
                    onNavigate={(id) => setSelectedNodeId(id)}
                    onEvidenceClick={(chunkId, quoteText) => setEvidenceModalState({ chunkId, quoteText })}
                  />
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      )}

      <EvidenceContextModal
        open={!!evidenceModalState}
        onClose={() => setEvidenceModalState(null)}
        subject={subject}
        chunkId={evidenceModalState?.chunkId ?? null}
        quoteText={evidenceModalState?.quoteText}
      />
    </div>
  );
}
