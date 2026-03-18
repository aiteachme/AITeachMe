import { useState, useEffect, useCallback, createContext, useContext } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2,
  Play,
  CheckCircle,
  XCircle,
  FileText,
  Zap,
} from "lucide-react";
import { Button } from "../ui/Button";
import { Card, CardContent } from "../ui/Card";
import { Modal } from "../ui/Modal";
import { apiClient } from "../../api/client";
import {
  triggerDigestBuild,
  fetchDigestStatus,
} from "../../api/graphApi";

/* ---------- types ---------- */

interface FileItem {
  id: number;
  filename: string;
  filetype: string;
  status: string;
  markdown_ready: boolean;
  created_at: string;
}

interface ApiResponse<T> { code: number; data: T; }
interface PaginatedData<T> { items: T[]; total: number; }

async function fetchCompletedFiles(subject: string): Promise<FileItem[]> {
  const res = await apiClient<ApiResponse<PaginatedData<FileItem>>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/files/list`,
    data: { page: 1, size: 100, status: "completed" },
  });
  return res.data.items;
}

/* ---------- 构建状态步骤映射 ---------- */

const STEP_LABELS: Record<string, string> = {
  acquire_lock: "获取构建锁",
  prepare: "准备数据",
  extract: "抽取知识节点",
  cluster: "聚类候选节点",
  resolve_nodes: "对齐知识节点",
  resolve_edges: "对齐知识边",
  analyze_impact: "分析影响集",
  finalize_graph: "完成图谱构建",
  derive_units: "生成教学单元",
  derive_theme_tree: "派生主题树",
  derive_prereq_dag: "派生先修图",
  finalize_curriculum: "完成课程结构",
};

/* ---------- Context：共享 job 状态 ---------- */

interface DigestJobContext {
  activeJobId: number | null;
  setAndPersistJobId: (jobId: number | null) => void;
  subject: string;
}

const DigestCtx = createContext<DigestJobContext | null>(null);

/**
 * Provider：管理当前学科的构建任务状态，包裹 Button 和 Progress 两个子组件。
 */
export function DigestBuildProvider({
  subject,
  children,
}: {
  subject: string;
  children: React.ReactNode;
}) {
  const storageKey = `digest-job-${subject}`;
  const [activeJobId, setActiveJobId] = useState<number | null>(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      return saved ? Number(saved) : null;
    } catch {
      return null;
    }
  });

  const setAndPersistJobId = useCallback(
    (jobId: number | null) => {
      setActiveJobId(jobId);
      try {
        if (jobId !== null) {
          localStorage.setItem(storageKey, String(jobId));
        } else {
          localStorage.removeItem(storageKey);
        }
      } catch {
        /* ignore */
      }
    },
    [storageKey],
  );

  return (
    <DigestCtx.Provider value={{ activeJobId, setAndPersistJobId, subject }}>
      {children}
    </DigestCtx.Provider>
  );
}

function useDigestJob() {
  const ctx = useContext(DigestCtx);
  if (!ctx) throw new Error("useDigestJob must be used inside DigestBuildProvider");
  return ctx;
}

/* ---------- 构建进度条（独立组件，可放在页面任意位置） ---------- */

export function DigestBuildProgress() {
  const { activeJobId, setAndPersistJobId, subject } = useDigestJob();
  const queryClient = useQueryClient();

  const handleComplete = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["theme-tree", subject] });
    queryClient.invalidateQueries({ queryKey: ["prereq-dag", subject] });
    queryClient.invalidateQueries({ queryKey: ["graph-nodes", subject] });
    setAndPersistJobId(null);
  }, [queryClient, subject, setAndPersistJobId]);

  if (!activeJobId) return null;

  return (
    <BuildProgress subject={subject} jobId={activeJobId} onComplete={handleComplete} />
  );
}

/* ---------- 内部进度条渲染 ---------- */

function BuildProgress({
  subject,
  jobId,
  onComplete,
}: {
  subject: string;
  jobId: number;
  onComplete: () => void;
}) {
  const { data } = useQuery({
    queryKey: ["digest-status", subject, jobId],
    queryFn: () => fetchDigestStatus(subject, jobId),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const d = query.state.data;
      if (!d) return 3000;
      const graphDone = d.graph_job.status === "completed" || d.graph_job.status === "failed";
      const currDone = !d.curriculum_job || d.curriculum_job.status === "completed" || d.curriculum_job.status === "failed";
      return graphDone && currDone ? false : 3000;
    },
  });

  useEffect(() => {
    if (!data) return;
    const graphDone = data.graph_job.status === "completed";
    const currDone = data.curriculum_job?.status === "completed";
    if (graphDone && currDone) {
      onComplete();
    }
  }, [data, onComplete]);

  if (!data) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-400 py-2">
        <Loader2 className="w-4 h-4 animate-spin" />查询构建状态...
      </div>
    );
  }

  const { graph_job, curriculum_job } = data;
  const isFailed = graph_job.status === "failed" || curriculum_job?.status === "failed";
  const errorMsg = graph_job.error_message || curriculum_job?.error_message;

  const graphProgress = graph_job.progress;
  const currProgress = curriculum_job?.progress ?? 0;
  const totalProgress = Math.round(graphProgress * 0.5 + currProgress * 0.5);

  const currentStep = curriculum_job?.current_step || graph_job.current_step;
  const stepLabel = currentStep ? (STEP_LABELS[currentStep] ?? currentStep) : "准备中";

  return (
    <Card>
      <CardContent className="pt-4 pb-4">
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            {isFailed ? (
              <XCircle className="w-5 h-5 text-red-500 shrink-0" />
            ) : totalProgress >= 100 ? (
              <CheckCircle className="w-5 h-5 text-green-500 shrink-0" />
            ) : (
              <Loader2 className="w-5 h-5 animate-spin text-blue-500 shrink-0" />
            )}
            <div className="flex-1">
              <div className="flex items-center justify-between text-sm mb-1">
                <span className="text-slate-700">{stepLabel}</span>
                <span className="text-slate-400">{totalProgress}%</span>
              </div>
              <div className="w-full bg-slate-100 rounded-full h-2">
                <div
                  className={`h-2 rounded-full transition-all duration-500 ${
                    isFailed ? "bg-red-400" : "bg-blue-500"
                  }`}
                  style={{ width: `${Math.min(totalProgress, 100)}%` }}
                />
              </div>
            </div>
          </div>

          <div className="flex gap-4 text-xs text-slate-500">
            <span>节点 +{graph_job.nodes_added} / 更新 {graph_job.nodes_updated} / 合并 {graph_job.nodes_merged}</span>
            <span>边 +{graph_job.edges_added} / 更新 {graph_job.edges_updated}</span>
            {curriculum_job && (
              <span>教学单元 +{curriculum_job.units_added} / 更新 {curriculum_job.units_updated}</span>
            )}
          </div>

          <div className="flex gap-3 text-xs">
            <span className={`px-2 py-0.5 rounded ${
              graph_job.status === "completed" ? "bg-green-50 text-green-600" :
              graph_job.status === "failed" ? "bg-red-50 text-red-600" :
              "bg-blue-50 text-blue-600"
            }`}>
              图谱: {graph_job.status === "completed" ? "完成" : graph_job.status === "failed" ? "失败" : "构建中"}
            </span>
            {curriculum_job && (
              <span className={`px-2 py-0.5 rounded ${
                curriculum_job.status === "completed" ? "bg-green-50 text-green-600" :
                curriculum_job.status === "failed" ? "bg-red-50 text-red-600" :
                "bg-blue-50 text-blue-600"
              }`}>
                课程: {curriculum_job.status === "completed" ? "完成" : curriculum_job.status === "failed" ? "失败" : "派生中"}
              </span>
            )}
          </div>

          {isFailed && errorMsg && (
            <div className="text-xs text-red-500 bg-red-50 rounded p-2 mt-2">
              {errorMsg}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

/* ---------- 触发按钮 + 文件选择弹窗 ---------- */

export function DigestBuildButton() {
  const { setAndPersistJobId, subject } = useDigestJob();
  const [showFileSelect, setShowFileSelect] = useState(false);
  const [selectedFileIds, setSelectedFileIds] = useState<Set<number>>(new Set());

  const { data: files = [], isLoading: filesLoading } = useQuery({
    queryKey: ["completed-files-digest", subject],
    queryFn: () => fetchCompletedFiles(subject),
    enabled: showFileSelect && !!subject,
  });

  const buildMutation = useMutation({
    mutationFn: () => triggerDigestBuild(subject, Array.from(selectedFileIds)),
    onSuccess: (data) => {
      setAndPersistJobId(data.job_id);
      setShowFileSelect(false);
      setSelectedFileIds(new Set());
    },
  });

  const toggleFile = (id: number) => {
    setSelectedFileIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  return (
    <>
      <Button onClick={() => setShowFileSelect(true)} variant="outline" size="sm">
        <Zap className="w-4 h-4 mr-1" />构建知识图谱
      </Button>

      <Modal
        open={showFileSelect}
        onClose={() => setShowFileSelect(false)}
        title="选择文件构建知识图谱"
      >
        <div className="space-y-4">
          <p className="text-sm text-slate-500">
            选择已解析完成的文件，系统将增量构建知识图谱并自动派生课程结构。
          </p>

          {filesLoading && (
            <div className="flex items-center text-slate-400 text-sm py-4">
              <Loader2 className="w-4 h-4 animate-spin mr-2" />加载文件列表...
            </div>
          )}

          {!filesLoading && files.length === 0 && (
            <p className="text-sm text-slate-400 py-4">
              没有已解析完成的文件，请先上传并解析资料
            </p>
          )}

          <div className="space-y-2 max-h-60 overflow-y-auto">
            {files.map((file) => (
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

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowFileSelect(false)}>
              取消
            </Button>
            <Button
              onClick={() => buildMutation.mutate()}
              disabled={selectedFileIds.size === 0 || buildMutation.isPending}
            >
              {buildMutation.isPending ? (
                <><Loader2 className="w-4 h-4 animate-spin mr-1" />提交中...</>
              ) : (
                <><Play className="w-4 h-4 mr-1" />开始构建</>
              )}
            </Button>
          </div>

          {buildMutation.isError && (
            <p className="text-xs text-red-500">
              {(buildMutation.error as any)?.response?.data?.detail ?? "构建请求失败"}
            </p>
          )}
        </div>
      </Modal>
    </>
  );
}
