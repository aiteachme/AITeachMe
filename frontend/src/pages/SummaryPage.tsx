import { useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen,
  ChevronRight,
  ChevronDown,
  Loader2,
  Plus,
  Trash2,
  RefreshCw,
  FileText,
  CheckCircle,
  FolderTree,
  GitBranch,
  Network,
  AlertTriangle,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Modal";
import { MarkdownViewer } from "../components/ui/MarkdownViewer";
import { apiClient } from "../api/client";
import { ThemeTreeView } from "../components/pages/ThemeTreeView";
import { PrereqDagView } from "../components/pages/PrereqDagView";
import { KnowledgeGraphView } from "../components/pages/KnowledgeGraphView";
import { DigestBuildPanel } from "../components/pages/DigestBuildPanel";
import { clearSubjectKnowledge } from "../api/graphApi";

/* ---------- types ---------- */

interface FileItem {
  id: number;
  filename: string;
  filetype: string;
  status: string;
  markdown_ready: boolean;
  created_at: string;
}

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

interface DocumentItem {
  id: number;
  source_file_id: number;
  title: string;
  markdown_content: string;
  current_step: string | null;
}

interface KnowledgeTreeData {
  docset_id: number;
  title: string;
  documents: DocumentTreeItem[];
}

interface KnowledgeGetData {
  docset_id: number;
  title: string;
  description: string;
  status: string | null;
  documents: DocumentItem[];
}

interface KnowledgeStatusData {
  docset_id: number;
  build_job_id: number | null;
  status: string;
  current_step: string | null;
  progress: number;
  message: string;
  docs_count: number;
  chunks_count: number;
  error_message: string | null;
}

interface DocSetItem {
  id: number;
  title: string;
  description: string;
  status: string | null;
  documents_count: number;
  created_at: string;
  updated_at: string;
}

interface ApiResponse<T> { code: number; data: T; }
interface PaginatedData<T> { items: T[]; total: number; }

/* ---------- api ---------- */

async function fetchFiles(subject: string): Promise<FileItem[]> {
  const res = await apiClient<ApiResponse<PaginatedData<FileItem>>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/files/list`,
    data: { page: 1, size: 100, status: "completed" },
  });
  return res.data.items;
}

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

async function fetchDetail(subject: string, docsetId: number): Promise<KnowledgeGetData> {
  const res = await apiClient<ApiResponse<KnowledgeGetData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/get`,
    data: { docset_id: docsetId },
  });
  return res.data;
}

async function fetchStatus(subject: string, docsetId: number): Promise<KnowledgeStatusData> {
  const res = await apiClient<ApiResponse<KnowledgeStatusData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/status`,
    data: { docset_id: docsetId },
  });
  return res.data;
}

async function buildKnowledge(
  subject: string,
  fileIds: number[],
  title: string,
): Promise<{ docset_id: number; build_job_id: number }> {
  const res = await apiClient<ApiResponse<{ docset_id: number; build_job_id: number }>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/build`,
    data: { file_ids: fileIds, title, desc: "" },
  });
  return res.data;
}

async function retryKnowledge(subject: string, docsetId: number): Promise<void> {
  await apiClient({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/retry`,
    data: { docset_id: docsetId },
  });
}

async function deleteKnowledge(subject: string, docsetId: number): Promise<void> {
  await apiClient({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/delete`,
    data: { docset_id: docsetId },
  });
}

/* ---------- sub-components ---------- */

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
              className={`flex items-center gap-2 py-1 cursor-pointer select-none ${
                node.level === 1 ? "font-medium text-slate-800" : "text-slate-600 pl-4 text-sm"
              }`}
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

const STATUS_BADGE: Record<string, { label: string; color: string }> = {
  completed: { label: "已完成", color: "bg-green-100 text-green-700" },
  processing: { label: "构建中", color: "bg-blue-100 text-blue-700" },
  failed: { label: "失败", color: "bg-red-100 text-red-700" },
  pending: { label: "等待中", color: "bg-yellow-100 text-yellow-700" },
};

function DocsetCard({
  subject,
  docset,
  onDelete,
  onRetry,
}: {
  subject: string;
  docset: DocSetItem;
  onDelete: () => void;
  onRetry: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [showContent, setShowContent] = useState(false);

  const isProcessing = docset.status === "processing";
  const isFailed = docset.status === "failed";
  const isCompleted = docset.status === "completed";

  const { data: tree, isLoading: treeLoading } = useQuery({
    queryKey: ["knowledge-tree", subject, docset.id],
    queryFn: () => fetchTree(subject, docset.id),
    enabled: expanded && isCompleted,
  });

  const { data: statusData } = useQuery({
    queryKey: ["knowledge-status", subject, docset.id],
    queryFn: () => fetchStatus(subject, docset.id),
    enabled: isProcessing,
    refetchInterval: isProcessing ? 3000 : false,
  });

  const { data: detail, isLoading: detailLoading } = useQuery({
    queryKey: ["knowledge-detail", subject, docset.id],
    queryFn: () => fetchDetail(subject, docset.id),
    enabled: showContent,
  });

  const badge = STATUS_BADGE[docset.status ?? ""] ?? { label: docset.status ?? "未知", color: "bg-slate-100 text-slate-600" };

  return (
    <>
      <Card className="hover:shadow-md transition-shadow">
        <CardHeader className="cursor-pointer" onClick={() => setExpanded((v) => !v)}>
          <div className="flex items-start justify-between">
            <BookOpen className="w-8 h-8 text-slate-400" />
            <div className="flex items-center gap-2">
              <span className={`text-xs px-2 py-0.5 rounded-full ${badge.color}`}>{badge.label}</span>
              {expanded
                ? <ChevronDown className="w-5 h-5 text-slate-400" />
                : <ChevronRight className="w-5 h-5 text-slate-400" />}
            </div>
          </div>
          <CardTitle className="text-lg mt-4">{docset.title}</CardTitle>
          <CardDescription>
            {docset.documents_count} 个文档 · {new Date(docset.created_at).toLocaleDateString("zh-CN")}
          </CardDescription>
        </CardHeader>

        {expanded && (
          <CardContent className="space-y-3">
            {isProcessing && statusData && (
              <div className="flex items-center gap-2 text-sm text-blue-600">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>{statusData.message} ({statusData.progress}%)</span>
              </div>
            )}

            {isFailed && (
              <div className="flex items-center justify-between">
                <span className="text-sm text-red-500">构建失败</span>
                <Button variant="outline" size="sm" onClick={(e) => { e.stopPropagation(); onRetry(); }}>
                  <RefreshCw className="w-3 h-3 mr-1" />重试
                </Button>
              </div>
            )}

            {isCompleted && treeLoading && (
              <div className="flex items-center text-slate-400 text-sm py-2">
                <Loader2 className="w-4 h-4 animate-spin mr-2" />加载大纲...
              </div>
            )}

            {isCompleted && tree?.documents.map((doc) => (
              <div key={doc.document_id} className="mb-4">
                <p className="text-xs text-slate-400 mb-2 font-medium uppercase tracking-wide">{doc.title}</p>
                <OutlineTree nodes={doc.nodes} />
              </div>
            ))}

            <div className="flex gap-2 pt-2 border-t border-slate-100">
              {isCompleted && (
                <Button variant="outline" size="sm" onClick={(e) => { e.stopPropagation(); setShowContent(true); }}>
                  <FileText className="w-3 h-3 mr-1" />查看内容
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={(e) => { e.stopPropagation(); onDelete(); }}
                className="text-red-500 hover:text-red-600 hover:bg-red-50"
              >
                <Trash2 className="w-3 h-3 mr-1" />删除
              </Button>
            </div>
          </CardContent>
        )}
      </Card>

      <Modal open={showContent} onClose={() => setShowContent(false)} title={docset.title}>
        {detailLoading && (
          <div className="flex items-center justify-center py-8 text-slate-400">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />加载中...
          </div>
        )}
        {detail?.documents.map((doc) => (
          <div key={doc.id} className="mb-6">
            <h3 className="text-base font-semibold text-slate-800 mb-3 pb-2 border-b border-slate-200">
              {doc.title}
            </h3>
            <MarkdownViewer content={doc.markdown_content} />
          </div>
        ))}
      </Modal>
    </>
  );
}

/* ---------- 知识视图 Tab ---------- */

type KnowledgeViewTab = "docsets" | "theme-tree" | "prereq-dag" | "knowledge-graph";

const VIEW_TABS: { id: KnowledgeViewTab; label: string; icon: React.ReactNode; desc: string }[] = [
  { id: "docsets", label: "知识集合", icon: <BookOpen className="w-4 h-4" />, desc: "文档知识集合" },
  { id: "theme-tree", label: "主题树", icon: <FolderTree className="w-4 h-4" />, desc: "层次化主题结构" },
  { id: "prereq-dag", label: "先修图", icon: <GitBranch className="w-4 h-4" />, desc: "学习路径依赖" },
  { id: "knowledge-graph", label: "知识图谱", icon: <Network className="w-4 h-4" />, desc: "底层知识节点" },
];

/* ---------- main page ---------- */

export function SummaryPage() {
  const { subjectId = "" } = useParams();
  const queryClient = useQueryClient();
  const [showBuild, setShowBuild] = useState(false);
  const [selectedFileIds, setSelectedFileIds] = useState<Set<number>>(new Set());
  const [buildTitle, setBuildTitle] = useState("");
  const [activeTab, setActiveTab] = useState<KnowledgeViewTab>("docsets");
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  const { data: docsets = [], isLoading, isError } = useQuery({
    queryKey: ["knowledge-list", subjectId],
    queryFn: () => fetchDocsets(subjectId),
    enabled: !!subjectId,
    refetchInterval: (query) => {
      const items = query.state.data ?? [];
      return items.some((d) => d.status === "processing") ? 3000 : false;
    },
  });

  const { data: completedFiles = [], isLoading: filesLoading } = useQuery({
    queryKey: ["completed-files", subjectId],
    queryFn: () => fetchFiles(subjectId),
    enabled: showBuild && !!subjectId,
  });

  const buildMutation = useMutation({
    mutationFn: () => buildKnowledge(subjectId, Array.from(selectedFileIds), buildTitle),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-list", subjectId] });
      setShowBuild(false);
      setSelectedFileIds(new Set());
      setBuildTitle("");
    },
  });

  const clearMutation = useMutation({
    mutationFn: () => clearSubjectKnowledge(subjectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-list", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["theme-tree", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["prereq-dag", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["graph-nodes", subjectId] });
      setShowClearConfirm(false);
    },
  });

  const retryMutation = useMutation({
    mutationFn: (docsetId: number) => retryKnowledge(subjectId, docsetId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["knowledge-list", subjectId] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (docsetId: number) => deleteKnowledge(subjectId, docsetId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["knowledge-list", subjectId] }),
  });

  const toggleFile = useCallback((id: number) => {
    setSelectedFileIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">知识总结</h1>
          <p className="text-slate-500 mt-2">AI 生成的知识点总结和思维导图</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setShowBuild(true)}>
            <Plus className="w-4 h-4 mr-1" />构建知识集合
          </Button>
          <DigestBuildPanel subject={subjectId} />
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowClearConfirm(true)}
            className="text-red-500 hover:text-red-600 hover:bg-red-50"
          >
            <Trash2 className="w-4 h-4 mr-1" />清空知识
          </Button>
        </div>
      </div>

      {/* 视图切换 Tab */}
      <div className="flex gap-1 p-1 bg-slate-100 rounded-xl">
        {VIEW_TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-all flex-1 justify-center ${
              activeTab === tab.id
                ? "bg-white text-slate-900 shadow-sm font-medium"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {tab.icon}
            <span>{tab.label}</span>
          </button>
        ))}
      </div>

      {/* 知识集合视图（原有） */}
      {activeTab === "docsets" && (
        <>
          {isLoading && (
            <div className="flex items-center justify-center py-16 text-slate-400">
              <Loader2 className="w-5 h-5 animate-spin mr-2" />加载中...
            </div>
          )}
          {isError && <p className="text-center py-16 text-red-500 text-sm">加载失败，请刷新重试</p>}
          {!isLoading && !isError && docsets.length === 0 && (
            <p className="text-center py-16 text-slate-400 text-sm">暂无知识集合，点击右上角「构建知识集合」开始</p>
          )}

          <div className="grid gap-6 md:grid-cols-2">
            {docsets.map((docset) => (
              <DocsetCard
                key={docset.id}
                subject={subjectId}
                docset={docset}
                onDelete={() => deleteMutation.mutate(docset.id)}
                onRetry={() => retryMutation.mutate(docset.id)}
              />
            ))}
          </div>
        </>
      )}

      {/* 主题树视图 */}
      {activeTab === "theme-tree" && <ThemeTreeView subject={subjectId} />}

      {/* 先修图视图 */}
      {activeTab === "prereq-dag" && <PrereqDagView subject={subjectId} />}

      {/* 知识图谱视图 */}
      {activeTab === "knowledge-graph" && <KnowledgeGraphView subject={subjectId} />}

      {/* 构建知识集合弹窗 */}
      <Modal open={showBuild} onClose={() => setShowBuild(false)} title="构建知识集合">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">标题</label>
            <input
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-300"
              placeholder="如：概率论期中复习"
              value={buildTitle}
              onChange={(e) => setBuildTitle(e.target.value)}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">
              选择已解析的文件 ({selectedFileIds.size} 已选)
            </label>
            {filesLoading && (
              <div className="flex items-center text-slate-400 text-sm py-4">
                <Loader2 className="w-4 h-4 animate-spin mr-2" />加载文件列表...
              </div>
            )}
            {!filesLoading && completedFiles.length === 0 && (
              <p className="text-sm text-slate-400 py-4">没有已解析完成的文件，请先上传并解析资料</p>
            )}
            <div className="space-y-2 max-h-60 overflow-y-auto">
              {completedFiles.map((file) => (
                <label
                  key={file.id}
                  className={`flex items-center gap-3 p-3 border rounded-lg cursor-pointer transition-colors ${
                    selectedFileIds.has(file.id)
                      ? "border-slate-400 bg-slate-50"
                      : "border-slate-200 hover:bg-slate-50"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedFileIds.has(file.id)}
                    onChange={() => toggleFile(file.id)}
                    className="rounded border-slate-300"
                  />
                  <FileText className="w-4 h-4 text-slate-400" />
                  <span className="text-sm text-slate-700 flex-1">{file.filename}</span>
                  <CheckCircle className="w-4 h-4 text-green-500" />
                </label>
              ))}
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowBuild(false)}>取消</Button>
            <Button
              onClick={() => buildMutation.mutate()}
              disabled={selectedFileIds.size === 0 || !buildTitle.trim() || buildMutation.isPending}
            >
              {buildMutation.isPending
                ? <><Loader2 className="w-4 h-4 animate-spin mr-1" />构建中...</>
                : <>开始构建</>}
            </Button>
          </div>
        </div>
      </Modal>

      {/* 清空知识确认弹窗 */}
      <Modal open={showClearConfirm} onClose={() => setShowClearConfirm(false)} title="确认清空知识数据">
        <div className="space-y-4">
          <div className="flex items-start gap-3 p-3 bg-red-50 rounded-lg">
            <AlertTriangle className="w-5 h-5 text-red-500 shrink-0 mt-0.5" />
            <div className="text-sm text-red-700">
              <p>此操作将清空该学科的所有知识数据，包括：</p>
              <ul className="list-disc list-inside mt-2 space-y-1 text-red-600">
                <li>知识图谱（节点、边、证据）</li>
                <li>教学单元及修订</li>
                <li>主题树、先修图、课程快照</li>
                <li>构建任务记录</li>
              </ul>
              <p className="mt-2 font-medium">此操作不可撤销，已上传的文件不受影响。</p>
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowClearConfirm(false)}>取消</Button>
            <Button
              onClick={() => clearMutation.mutate()}
              disabled={clearMutation.isPending}
              className="bg-red-500 hover:bg-red-600 text-white"
            >
              {clearMutation.isPending
                ? <><Loader2 className="w-4 h-4 animate-spin mr-1" />清空中...</>
                : <><Trash2 className="w-4 h-4 mr-1" />确认清空</>}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
