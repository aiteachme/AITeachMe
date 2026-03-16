import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, ChevronRight, ChevronDown, Loader2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { apiClient } from "../api/client";

interface OutlineNode {
  id: number;
  title: string;
  level: number;
  children: OutlineNode[];
}

interface DocumentTreeItem {
  document_id: number;
  title: string;
  nodes: OutlineNode[];
}

interface KnowledgeTreeData {
  docset_id: number;
  title: string;
  documents: DocumentTreeItem[];
}

interface DocSetItem {
  id: number;
  title: string;
  description: string;
  status: string | null;
  documents_count: number;
  created_at: string;
}

interface ApiResponse<T> { code: number; data: T; }
interface PaginatedData<T> { items: T[]; total: number; }

async function fetchDocsets(subject: string): Promise<DocSetItem[]> {
  const res = await apiClient<ApiResponse<PaginatedData<DocSetItem>>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/list`,
    data: { page: 1, size: 50 },
  });
  return res.data.items;
}

async function fetchTree(subject: string, docsetId: number): Promise<KnowledgeTreeData> {
  const res = await apiClient<ApiResponse<KnowledgeTreeData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/tree`,
    data: { docset_id: docsetId },
  });
  return res.data;
}

function OutlineTree({ nodes }: { nodes: OutlineNode[] }) {
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());

  const toggle = (id: number) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  return (
    <ul className="space-y-1">
      {nodes.map((node) => {
        const hasChildren = node.children && node.children.length > 0;
        const isCollapsed = collapsed.has(node.id);
        return (
          <li key={node.id}>
            <div
              className={`flex items-center gap-2 py-1 cursor-pointer select-none ${node.level === 1 ? "font-medium text-slate-800" : "text-slate-600 pl-4 text-sm"}`}
              onClick={() => hasChildren && toggle(node.id)}
            >
              {hasChildren
                ? isCollapsed
                  ? <ChevronRight className="w-3 h-3 text-slate-400 flex-shrink-0" />
                  : <ChevronDown className="w-3 h-3 text-slate-400 flex-shrink-0" />
                : <ChevronRight className="w-3 h-3 text-transparent flex-shrink-0" />}
              {node.title}
            </div>
            {hasChildren && !isCollapsed && <OutlineTree nodes={node.children} />}
          </li>
        );
      })}
    </ul>
  );
}

function DocsetCard({ subject, docset }: { subject: string; docset: DocSetItem }) {
  const [expanded, setExpanded] = useState(false);

  const { data: tree, isLoading } = useQuery({
    queryKey: ["knowledge-tree", subject, docset.id],
    queryFn: () => fetchTree(subject, docset.id),
    enabled: expanded,
  });

  return (
    <Card className="hover:shadow-md transition-shadow">
      <CardHeader
        className="cursor-pointer"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex items-start justify-between">
          <BookOpen className="w-8 h-8 text-slate-400" />
          {expanded
            ? <ChevronDown className="w-5 h-5 text-slate-400" />
            : <ChevronRight className="w-5 h-5 text-slate-400" />}
        </div>
        <CardTitle className="text-lg mt-4">{docset.title}</CardTitle>
        <CardDescription>{docset.documents_count} 个文档</CardDescription>
      </CardHeader>

      {expanded && (
        <CardContent>
          {isLoading && (
            <div className="flex items-center text-slate-400 text-sm py-2">
              <Loader2 className="w-4 h-4 animate-spin mr-2" />加载大纲...
            </div>
          )}
          {tree?.documents.map((doc) => (
            <div key={doc.document_id} className="mb-4">
              <p className="text-xs text-slate-400 mb-2 font-medium uppercase tracking-wide">{doc.title}</p>
              <OutlineTree nodes={doc.nodes} />
            </div>
          ))}
        </CardContent>
      )}
    </Card>
  );
}

export function SummaryPage() {
  const { subjectId = "" } = useParams();

  const { data: docsets = [], isLoading, isError } = useQuery({
    queryKey: ["knowledge-list", subjectId],
    queryFn: () => fetchDocsets(subjectId),
    enabled: !!subjectId,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">知识总结</h1>
        <p className="text-slate-500 mt-2">AI 生成的知识点总结和思维导图</p>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-16 text-slate-400">
          <Loader2 className="w-5 h-5 animate-spin mr-2" />加载中...
        </div>
      )}
      {isError && <p className="text-center py-16 text-red-500 text-sm">加载失败，请刷新重试</p>}
      {!isLoading && !isError && docsets.length === 0 && (
        <p className="text-center py-16 text-slate-400 text-sm">暂无知识集合，请先上传资料并构建知识库</p>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        {docsets.map((docset) => (
          <DocsetCard key={docset.id} subject={subjectId} docset={docset} />
        ))}
      </div>
    </div>
  );
}
