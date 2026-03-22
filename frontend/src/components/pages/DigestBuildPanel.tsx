import { useState, useEffect, useCallback, createContext, useContext } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play, CheckCircle, FileText, Zap } from "lucide-react";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";
import { getApiErrorMessage } from "../../api/client";
import {
  digestBuildApiV1SubjectsSubjectKnowledgeDigestBuildPost,
  digestStatusApiV1SubjectsSubjectKnowledgeDigestStatusPost,
} from "../../api/generated/knowledge";
import { listFilesApiApiV1SubjectsSubjectFilesListPost } from "../../api/generated/files";
import type { FileItem } from "../../api/generated/model";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";

async function fetchCompletedFiles(subject: string): Promise<FileItem[]> {
  return (
    unwrapOrvalResponse(
      await listFilesApiApiV1SubjectsSubjectFilesListPost(subject, {
        page: 1,
        size: 100,
        status: "completed",
      }),
    )?.items ?? []
  );
}

interface DigestJobContext {
  activeJobId: number | null;
  setAndPersistJobId: (jobId: number | null) => void;
  subject: string;
}

const DigestCtx = createContext<DigestJobContext | null>(null);

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
        // ignore storage errors
      }
    },
    [storageKey],
  );

  return <DigestCtx.Provider value={{ activeJobId, setAndPersistJobId, subject }}>{children}</DigestCtx.Provider>;
}

function useDigestJob() {
  const ctx = useContext(DigestCtx);
  if (!ctx) throw new Error("useDigestJob must be used inside DigestBuildProvider");
  return ctx;
}

function isTerminalStatus(status?: string | null): boolean {
  return status === "completed" || status === "failed";
}

function isDigestTerminal(data: {
  graph_job: { status: string };
  curriculum_job?: { status: string } | null;
}): boolean {
  const graphDone = isTerminalStatus(data.graph_job.status);
  const curriculumDone = !data.curriculum_job || isTerminalStatus(data.curriculum_job.status);
  return graphDone && curriculumDone;
}

function isDigestSuccess(data: {
  graph_job: { status: string };
  curriculum_job?: { status: string } | null;
}): boolean {
  const graphOk = data.graph_job.status === "completed";
  const curriculumOk = !data.curriculum_job || data.curriculum_job.status === "completed";
  return graphOk && curriculumOk;
}

export function DigestBuildProgress() {
  return null;
}

export function DigestBuildButton() {
  const { activeJobId, setAndPersistJobId, subject } = useDigestJob();
  const queryClient = useQueryClient();

  const [showFileSelect, setShowFileSelect] = useState(false);
  const [selectedFileIds, setSelectedFileIds] = useState<Set<number>>(new Set());
  const [lastJobError, setLastJobError] = useState<string>("");

  const { data: files = [], isLoading: filesLoading } = useQuery({
    queryKey: ["completed-files-digest", subject],
    queryFn: () => fetchCompletedFiles(subject),
    enabled: showFileSelect && !!subject,
  });

  const { data: activeJobStatus } = useQuery({
    queryKey: ["digest-status", subject, activeJobId],
    queryFn: async () => {
      if (!activeJobId) return null;
      const status = unwrapOrvalResponse(
        await digestStatusApiV1SubjectsSubjectKnowledgeDigestStatusPost(subject, {
          job_id: activeJobId,
        }),
      );

      if (!status) {
        throw new Error("查询构建状态失败");
      }

      return status;
    },
    enabled: !!activeJobId,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 3000;
      return isDigestTerminal(data) ? false : 3000;
    },
  });

  useEffect(() => {
    if (!activeJobStatus || !isDigestTerminal(activeJobStatus)) {
      return;
    }

    if (isDigestSuccess(activeJobStatus)) {
      queryClient.invalidateQueries({ queryKey: ["theme-tree", subject] });
      queryClient.invalidateQueries({ queryKey: ["prereq-dag", subject] });
      queryClient.invalidateQueries({ queryKey: ["graph-nodes", subject] });
      queryClient.invalidateQueries({ queryKey: ["knowledge-overview", subject] });
      setLastJobError("");
    } else {
      const message =
        activeJobStatus.graph_job.error_message ??
        activeJobStatus.curriculum_job?.error_message ??
        "知识构建失败，请稍后重试";
      setLastJobError(message);
    }

    setAndPersistJobId(null);
  }, [activeJobStatus, queryClient, setAndPersistJobId, subject]);

  const buildMutation = useMutation({
    mutationFn: async () => {
      const result = unwrapOrvalResponse(
        await digestBuildApiV1SubjectsSubjectKnowledgeDigestBuildPost(subject, {
          file_ids: Array.from(selectedFileIds),
        }),
      );

      if (!result) {
        throw new Error("提交构建任务失败");
      }

      return result;
    },
    onSuccess: (data) => {
      setAndPersistJobId(data.job_id);
      setShowFileSelect(false);
      setSelectedFileIds(new Set());
      setLastJobError("");
    },
  });

  const isJobRunning = !!activeJobId && (!activeJobStatus || !isDigestTerminal(activeJobStatus));

  const toggleFile = (id: number) => {
    setSelectedFileIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  return (
    <>
      <Button onClick={() => setShowFileSelect(true)} variant="outline" size="sm" disabled={isJobRunning}>
        {isJobRunning ? (
          <>
            <Loader2 className="w-4 h-4 mr-1 animate-spin" />构建中
          </>
        ) : (
          <>
            <Zap className="w-4 h-4 mr-1" />构建知识图谱
          </>
        )}
      </Button>

      {!!lastJobError && <p className="mt-2 text-xs text-red-500">{lastJobError}</p>}

      <Modal open={showFileSelect} onClose={() => setShowFileSelect(false)} title="选择文件构建知识图谱">
        <div className="space-y-4">
          <p className="text-sm text-slate-500">选择已解析完成的文件，系统将触发知识图谱构建并自动派生课程结构。</p>

          {filesLoading && (
            <div className="flex items-center text-slate-400 text-sm py-4">
              <Loader2 className="w-4 h-4 animate-spin mr-2" />加载文件列表...
            </div>
          )}

          {!filesLoading && files.length === 0 && (
            <p className="text-sm text-slate-400 py-4">没有已解析完成的文件，请先上传并解析资料</p>
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
              disabled={selectedFileIds.size === 0 || buildMutation.isPending || isJobRunning}
            >
              {buildMutation.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin mr-1" />提交中...
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 mr-1" />开始构建
                </>
              )}
            </Button>
          </div>

          {buildMutation.isError && (
            <p className="text-xs text-red-500">{getApiErrorMessage(buildMutation.error, "构建请求失败")}</p>
          )}
        </div>
      </Modal>
    </>
  );
}
