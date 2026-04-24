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
  graphKnowledgeUnitDetailApiV1SubjectsSubjectKnowledgeGraphKnowledgeUnitsDetailPost,
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
        await graphKnowledgeUnitDetailApiV1SubjectsSubjectKnowledgeGraphKnowledgeUnitsDetailPost(subject, {
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

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-lg font-semibold text-slate-800">
              <MarkdownViewer content={data.canonical_name} />
            </h3>
            <span className={`text-xs px-1.5 py-0.5 rounded ${typeStyle.color}`}>{typeStyle.label}</span>
          </div>
          <p className="text-xs text-slate-400">置信度：{Math.round(data.confidence * 100)}%</p>
        </div>
        <button onClick={onClose} className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100">
          <X className="w-4 h-4" />
        </button>
      </div>

      {data.current_revision && (
        <div className="space-y-2">
          {data.current_revision.summary && (
            <div className="text-sm text-slate-600 bg-slate-50 rounded-lg p-3">
              <MarkdownViewer content={data.current_revision.summary} />
            </div>
          )}
          {data.current_revision.body && (
            <div className="text-sm border border-slate-100 rounded-lg p-3 max-h-48 overflow-y-auto">
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
                  alias.is_primary ? "bg-slate-800 text-white" : "bg-slate-100 text-slate-600"
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
                className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-left hover:bg-slate-50 transition-colors"
              >
                <span className="text-slate-400">{edge.direction === "outgoing" ? "->" : "<-"}</span>
                <span className="text-slate-700 truncate flex-1">{edge.other_node_name}</span>
                <span className="text-[10px] text-slate-400">{edge.edge_type}</span>
                <ChevronRight className="w-3 h-3 text-slate-300" />
              </button>
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
                className="w-full text-left text-xs text-slate-600 bg-slate-50 rounded p-2 border-l-2 border-slate-300 hover:border-amber-400 hover:bg-amber-50/50 transition-colors cursor-pointer group"
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

  if (total === 0 && !nodeType) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-slate-400">
        <Network className="w-8 h-8 mb-2 text-slate-300" />
        <p className="text-sm">暂无知识节点</p>
        <p className="text-xs mt-1">构建完成后将自动抽取知识节点</p>
      </div>
    );
  }

  const viewToggle = (
    <div className="flex items-center gap-1 p-0.5 bg-slate-100 rounded-lg shrink-0">
      <button
        onClick={() => setViewMode("list")}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-all ${
          viewMode === "list"
            ? "bg-white text-slate-900 shadow-sm font-medium"
            : "text-slate-500 hover:text-slate-700"
        }`}
      >
        <List className="w-3.5 h-3.5" />列表视图
      </button>
      <button
        onClick={() => setViewMode("graph")}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-all ${
          viewMode === "graph"
            ? "bg-white text-slate-900 shadow-sm font-medium"
            : "text-slate-500 hover:text-slate-700"
        }`}
      >
        <Share2 className="w-3.5 h-3.5" />力导向图
      </button>
    </div>
  );

  return (
    <div className="knowledge-graph-view flex flex-col h-full min-h-0 gap-4">
      {viewMode === "graph" && (
        <ForceGraphView
          subject={subject}
          toolbar={viewToggle}
          onEvidenceClick={(chunkId, quoteText) => setEvidenceModalState({ chunkId, quoteText })}
          fullGraphData={overviewGraph}
        />
      )}

      {viewMode === "list" && (
        <div className="flex gap-4">
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
                        ? "bg-slate-800 text-white"
                        : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
                <span className="text-xs text-slate-400 ml-2">共 {total} 个节点</span>
              </div>
            </div>

            <div className="grid gap-2 grid-cols-1 sm:grid-cols-2">
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
                        ? "border-slate-400 bg-slate-50 shadow-sm"
                        : "border-slate-200 hover:border-slate-300 hover:shadow-sm"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-slate-800 truncate flex-1 [&_p]:mb-0 [&_p]:inline">
                        <MarkdownViewer content={node.canonical_name} />
                      </span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded shrink-0 ${typeStyle.color}`}>
                        {typeStyle.label}
                      </span>
                    </div>
                    <div className="text-[10px] text-slate-400 mt-1">置信度：{Math.round(node.confidence * 100)}%</div>
                  </button>
                );
              })}
            </div>

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

