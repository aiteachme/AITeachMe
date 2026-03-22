import { useState, useEffect, useCallback, createContext, useContext } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2,
  Play,
  CheckCircle,
  XCircle,
  FileText,
  FileEdit,
} from "lucide-react";
import { Button } from "../ui/Button";
import { Card, CardContent } from "../ui/Card";
import { Modal } from "../ui/Modal";
import { getApiErrorMessage } from "../../api/client";
import {
  docgenBuildApiV1SubjectsSubjectKnowledgeDocgenBuildPost,
  docgenStatusApiV1SubjectsSubjectKnowledgeDocgenStatusPost,
} from "../../api/generated/knowledge";
import { listFilesApiApiV1SubjectsSubjectFilesListPost } from "../../api/generated/files";
import type { FileItem } from "../../api/generated/model";
import { unwrapOrvalResponse } from "../../api/generated/utils";

async function fetchCompletedFiles(subject: string): Promise<FileItem[]> {
  return unwrapOrvalResponse(
    await listFilesApiApiV1SubjectsSubjectFilesListPost(subject, {
      page: 1,
      size: 100,
      status: "completed",
    }),
  )?.items ?? [];
}

/* ---------- 构建状态步骤映射 ---------- */

const STEP_LABELS: Record<string, string> = {
  cleansing: "数据清洗与自愈",
  outlining: "构建全局目录树",
  drafting: "并发撰写章节",
  finalizing: "元数据提取与合并落库",
  done: "构建完成",
};

/* ---------- Context：共享 job 状态 ---------- */

interface DocGenJobContext {
  activeJobId: number | null;
  setAndPersistJobId: (jobId: number | null) => void;
  subject: string;
}

const DocGenCtx = createContext<DocGenJobContext | null>(null);

export function DocGenBuildProvider({
  subject,
  children,
}: {
  subject: string;
  children: React.ReactNode;
}) {
  const storageKey = `docgen-job-${subject}`;
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
    <DocGenCtx.Provider value={{ activeJobId, setAndPersistJobId, subject }}>
      {children}
    </DocGenCtx.Provider>
  );
}

function useDocGenJob() {
  const ctx = useContext(DocGenCtx);
  if (!ctx) throw new Error("useDocGenJob must be used inside DocGenBuildProvider");
  return ctx;
}

/* ---------- 构建进度条 ---------- */

export function DocGenBuildProgress() {
  const { activeJobId, setAndPersistJobId, subject } = useDocGenJob();
  const queryClient = useQueryClient();

  const handleComplete = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["docgen-content", subject] });
    setAndPersistJobId(null);
  }, [queryClient, subject, setAndPersistJobId]);

  if (!activeJobId) return null;

  return (
    <BuildProgress subject={subject} jobId={activeJobId} onComplete={handleComplete} />
  );
}

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
    queryKey: ["docgen-status", subject, jobId],
    queryFn: async () => {
      const status = unwrapOrvalResponse(
        await docgenStatusApiV1SubjectsSubjectKnowledgeDocgenStatusPost(subject, {
          job_id: jobId,
        }),
      );

      if (!status) {
        throw new Error("查询文档生成状态失败");
      }

      return status;
    },
    enabled: !!jobId,
    refetchInterval: (query) => {
      const d = query.state.data;
      if (!d) return 3000;
      const done = d.job.status === "completed" || d.job.status === "failed";
      return done ? false : 3000;
    },
  });

  useEffect(() => {
    if (!data) return;
    if (data.job.status === "completed") {
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

  const { job } = data;
  const isFailed = job.status === "failed";
  const errorMsg = job.error_message;
  const progress = job.progress;
  const currentStep = job.current_step;
  const stepLabel = currentStep ? (STEP_LABELS[currentStep] ?? currentStep) : "准备中";

  return (
    <Card className="mb-6 border-blue-100 bg-blue-50/30 shadow-none">
      <CardContent className="pt-4 pb-4">
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            {isFailed ? (
              <XCircle className="w-5 h-5 text-red-500 shrink-0" />
            ) : progress >= 100 ? (
              <CheckCircle className="w-5 h-5 text-green-500 shrink-0" />
            ) : (
              <Loader2 className="w-5 h-5 animate-spin text-blue-500 shrink-0" />
            )}
            <div className="flex-1">
              <div className="flex items-center justify-between text-sm mb-1">
                <span className="text-slate-700 font-medium">知识文档生成: {stepLabel}</span>
                <div className="flex items-center gap-2">
                  <span className={`px-2 py-0.5 rounded text-xs ${
                    job.status === "completed" ? "bg-green-100 text-green-700" :
                    job.status === "failed" ? "bg-red-100 text-red-700" :
                    "bg-blue-100 text-blue-700"
                  }`}>
                    {job.status === "completed" ? "完成" : job.status === "failed" ? "失败" : "生成中"}
                  </span>
                  <span className="text-slate-500 font-medium">{progress}%</span>
                </div>
              </div>
              <div className="w-full bg-slate-200/50 rounded-full h-2 overflow-hidden">
                <div
                  className={`h-2 rounded-full transition-all duration-500 ${
                    isFailed ? "bg-red-400" : "bg-blue-500"
                  }`}
                  style={{ width: `${Math.min(progress, 100)}%` }}
                />
              </div>
            </div>
          </div>

          {((job.total_chapters ?? 0) > 0 || (job.completed_chapters ?? 0) > 0) && (
            <div className="flex gap-4 text-xs text-slate-500">
              <span>已撰写章节: {job.completed_chapters ?? 0} / {job.total_chapters || "?"}</span>
            </div>
          )}

          {isFailed && errorMsg && (
            <div className="text-xs text-red-500 bg-red-50 rounded p-2 mt-2 break-all">
              {errorMsg}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

/* ---------- 触发按钮 + 文件选择弹窗 ---------- */

export function DocGenBuildButton() {
  const { setAndPersistJobId, subject } = useDocGenJob();
  const [showFileSelect, setShowFileSelect] = useState(false);
  const [selectedFileIds, setSelectedFileIds] = useState<Set<number>>(new Set());

  const { data: files = [], isLoading: filesLoading } = useQuery({
    queryKey: ["completed-files-docgen", subject],
    queryFn: () => fetchCompletedFiles(subject),
    enabled: showFileSelect && !!subject,
  });

  const buildMutation = useMutation({
    mutationFn: async () => {
      const result = unwrapOrvalResponse(
        await docgenBuildApiV1SubjectsSubjectKnowledgeDocgenBuildPost(subject, {
          file_ids: Array.from(selectedFileIds),
        }),
      );

      if (!result) {
        throw new Error("提交文档生成任务失败");
      }

      return result;
    },
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
      <Button onClick={() => setShowFileSelect(true)} variant="default" size="sm" className="bg-blue-600 hover:bg-blue-700 text-white shadow-sm">
        <FileEdit className="w-4 h-4 mr-1.5" />构建知识文档
      </Button>

      <Modal
        open={showFileSelect}
        onClose={() => setShowFileSelect(false)}
        title="选择文件构建知识文档"
      >
        <div className="space-y-4">
          <p className="text-sm text-slate-500">
            选择已解析完成的文件，系统将进行自清洗并由多个智能体并发撰写结构化的知识归纳报告。
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
                    ? "border-blue-400 bg-blue-50/50"
                    : "border-slate-200 hover:bg-slate-50"
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedFileIds.has(file.id)}
                  onChange={() => toggleFile(file.id)}
                  className="rounded border-slate-300 text-blue-600 focus:ring-blue-500"
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
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              {buildMutation.isPending ? (
                <><Loader2 className="w-4 h-4 animate-spin mr-1.5" />生成中...</>
              ) : (
                <><Play className="w-4 h-4 mr-1.5" />开始生成</>
              )}
            </Button>
          </div>

          {buildMutation.isError && (
            <p className="text-xs text-red-500">
              {getApiErrorMessage(buildMutation.error, "构建请求失败")}
            </p>
          )}
        </div>
      </Modal>
    </>
  );
}
