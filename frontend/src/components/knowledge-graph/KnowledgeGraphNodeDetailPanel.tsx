import { useQuery } from "@tanstack/react-query";
import {
  ChevronRight,
  ExternalLink,
  Eye,
  FileText,
  Link2,
  Loader2,
  Tag,
  Target,
  X,
} from "lucide-react";

import { graphKnowledgeUnitDetailApiV1CoursesCourseIdKnowledgeGraphKnowledgeUnitsDetailPost } from "../../api/generated/knowledge";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { MarkdownViewer } from "../ui/MarkdownViewer";
import { DEFAULT_COLOR, NODE_COLORS, relationLabel, relationTone } from "./knowledgeGraphVisual";

export type KnowledgeGraphSourceRefNavigationTarget = {
  id: number;
  chapter_index?: number;
  chapter_title?: string | null;
  doc_version_no?: number;
  source_kind?: string;
  source_file_ids?: string[];
  quote_text?: string;
  anchor?: string;
  knowledge_document_id?: number | null;
};

type KnowledgeGraphNodeDetailPanelProps = {
  course: string;
  nodeId: number;
  onClose: () => void;
  onNavigate: (id: number) => void;
  onEvidenceClick?: (chunkId: number, quoteText: string) => void;
  onSourceRefClick?: (ref: KnowledgeGraphSourceRefNavigationTarget) => void;
  showTeachingRole?: boolean;
};

export function KnowledgeGraphNodeDetailPanel({
  course,
  nodeId,
  onClose,
  onNavigate,
  onEvidenceClick,
  onSourceRefClick,
  showTeachingRole = true,
}: KnowledgeGraphNodeDetailPanelProps) {
  const { data, isLoading } = useQuery({
    queryKey: ["graph-node-detail", course, nodeId],
    queryFn: async () =>
      unwrapOrvalResponse(
        await graphKnowledgeUnitDetailApiV1CoursesCourseIdKnowledgeGraphKnowledgeUnitsDetailPost(course, {
          knowledge_unit_id: nodeId,
        }),
      ) ?? null,
    enabled: !!nodeId,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8 text-slate-400">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />加载中...
      </div>
    );
  }

  if (!data) return null;

  const color = NODE_COLORS[data.knowledge_unit_type] ?? DEFAULT_COLOR;
  const isCoreNode = color.role === "assessment_core";
  const aliases = data.aliases ?? [];
  const incidentEdges = data.incident_edges ?? [];
  const evidenceList = data.evidence ?? [];
  const sourceRefs = data.source_refs ?? [];

  return (
    <div className="animate-in slide-in-from-right-4 space-y-4 duration-200">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <h3 className="min-w-0 break-words text-lg font-semibold text-slate-800 dark:text-slate-100">
              <MarkdownViewer content={data.canonical_name} />
            </h3>
            <span
              className="rounded-full px-2 py-0.5 text-xs font-medium text-white"
              style={{ backgroundColor: color.fill }}
            >
              {color.label}
            </span>
          </div>
          <p className="text-xs text-slate-400">置信度：{Math.round(data.confidence * 100)}%</p>
        </div>
        <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-200">
          <X className="h-4 w-4" />
        </button>
      </div>

      {showTeachingRole ? (
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900/70">
            <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-slate-500 dark:text-slate-400">
              <Target className="h-3.5 w-3.5" />
              教学角色
            </div>
            <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">{color.roleLabel}</p>
          </div>
          <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900/70">
            <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-slate-500 dark:text-slate-400">
              <Eye className="h-3.5 w-3.5" />
              出题权重
            </div>
            <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">{isCoreNode ? "优先锚点" : "辅助材料"}</p>
          </div>
        </div>
      ) : null}

      {data.current_revision ? (
        <div className="space-y-2">
          {data.current_revision.summary ? (
            <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600 dark:bg-slate-900 dark:text-slate-300">
              <MarkdownViewer content={data.current_revision.summary} />
            </div>
          ) : null}
          {data.current_revision.body ? (
            <div className="max-h-48 overflow-y-auto rounded-lg border border-slate-100 p-3 text-sm dark:border-slate-800 dark:text-slate-300">
              <MarkdownViewer content={data.current_revision.body} />
            </div>
          ) : null}
        </div>
      ) : null}

      {aliases.length > 0 ? (
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-500">
            <Tag className="h-3 w-3" />别名
          </div>
          <div className="flex flex-wrap gap-1.5">
            {aliases.map((alias: { id: number; is_primary: boolean; alias: string }) => (
              <span key={alias.id} className={`rounded-full px-2 py-0.5 text-xs ${alias.is_primary ? "bg-slate-800 text-white dark:bg-slate-100 dark:text-slate-900" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"}`}>
                {alias.alias}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {incidentEdges.length > 0 ? (
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-500">
            <Link2 className="h-3 w-3" />关联知识 ({incidentEdges.length})
          </div>
          <div className="max-h-40 space-y-1 overflow-y-auto">
            {incidentEdges.map((edge: { id: number; other_node_id: number; direction: string; other_node_name: string; edge_type: string }) => (
              <button key={edge.id} onClick={() => onNavigate(edge.other_node_id)}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/70">
                <span
                  className="rounded-full px-1.5 py-0.5 text-[10px] font-semibold text-white"
                  style={{ backgroundColor: relationTone(edge.edge_type) }}
                >
                  {edge.direction === "outgoing" ? "出" : "入"}
                </span>
                <span className="flex-1 truncate text-slate-700 dark:text-slate-300">{edge.other_node_name}</span>
                <span className="text-[10px] text-slate-400">{relationLabel(edge.edge_type)}</span>
                <ChevronRight className="h-3 w-3 text-slate-300" />
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {sourceRefs.length > 0 ? (
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-500">
            <FileText className="h-3 w-3" />图谱来源 ({sourceRefs.length})
          </div>
          <div className="max-h-40 space-y-1.5 overflow-y-auto">
            {sourceRefs.map((ref: KnowledgeGraphSourceRefNavigationTarget) => (
              <button
                key={ref.id}
                type="button"
                disabled={!onSourceRefClick}
                onClick={() => onSourceRefClick?.(ref)}
                title="跳转到知识文档对应位置"
                className="group w-full rounded border border-slate-100 bg-slate-50 p-2 text-left text-xs text-slate-600 transition-colors hover:border-blue-200 hover:bg-blue-50/70 disabled:cursor-default disabled:hover:border-slate-100 disabled:hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:border-blue-500/30 dark:hover:bg-blue-500/10 dark:disabled:hover:border-slate-800 dark:disabled:hover:bg-slate-900/70"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-medium text-slate-700 dark:text-slate-200">
                    {ref.chapter_title || (ref.chapter_index ? `第 ${ref.chapter_index} 章` : "知识文档")}
                  </span>
                  <span className="flex shrink-0 items-center gap-1">
                    {ref.doc_version_no ? <span className="text-[10px] text-slate-400">v{ref.doc_version_no}</span> : null}
                    {onSourceRefClick ? <ExternalLink className="h-3 w-3 text-slate-300 transition-colors group-hover:text-blue-500" /> : null}
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-slate-400">
                  {ref.source_kind ? <span>{ref.source_kind}</span> : null}
                  {ref.source_file_ids?.length ? <span>资料 {ref.source_file_ids.join(", ")}</span> : null}
                </div>
                {ref.quote_text ? <p className="mt-1 line-clamp-2 text-slate-500 dark:text-slate-400">{ref.quote_text}</p> : null}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {evidenceList.length > 0 ? (
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-500">
            <FileText className="h-3 w-3" />来源证据 ({evidenceList.length})
          </div>
          <div className="max-h-40 space-y-1.5 overflow-y-auto">
            {evidenceList.map((ev: { id: number; chunk_id: number; quote_text: string; evidence_role: string; confidence: number }) => (
              <button key={ev.id} onClick={() => onEvidenceClick?.(ev.chunk_id, ev.quote_text)}
                className="group w-full cursor-pointer rounded border-l-2 border-slate-300 bg-slate-50 p-2 text-left text-xs text-slate-600 transition-colors hover:border-amber-400 hover:bg-amber-50/50 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:border-amber-400/70 dark:hover:bg-amber-500/10">
                <p className="line-clamp-3">{ev.quote_text}</p>
                <div className="mt-1 flex items-center justify-between">
                  <p className="text-[10px] text-slate-400">{ev.evidence_role} 路 {Math.round(ev.confidence * 100)}%</p>
                  <ExternalLink className="h-3 w-3 text-slate-300 transition-colors group-hover:text-amber-500" />
                </div>
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
