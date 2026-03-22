import { useState, createContext, useContext } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play, CheckCircle, FileText, Zap } from "lucide-react";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";
import { getApiErrorMessage } from "../../api/client";
import { digestBuildApiV1SubjectsSubjectKnowledgeDigestBuildPost } from "../../api/generated/knowledge";
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

interface DigestBuildContext {
  subject: string;
}

const DigestCtx = createContext<DigestBuildContext | null>(null);

export function DigestBuildProvider({
  subject,
  children,
}: {
  subject: string;
  children: React.ReactNode;
}) {
  return <DigestCtx.Provider value={{ subject }}>{children}</DigestCtx.Provider>;
}

function useDigestBuild() {
  const ctx = useContext(DigestCtx);
  if (!ctx) throw new Error("useDigestBuild must be used inside DigestBuildProvider");
  return ctx;
}

export function DigestBuildProgress() {
  return null;
}

export function DigestBuildButton() {
  const { subject } = useDigestBuild();
  const queryClient = useQueryClient();

  const [showFileSelect, setShowFileSelect] = useState(false);
  const [selectedFileIds, setSelectedFileIds] = useState<Set<number>>(new Set());
  const [lastBuildError, setLastBuildError] = useState<string>("");
  const [lastBuildMessage, setLastBuildMessage] = useState<string>("");

  const { data: files = [], isLoading: filesLoading } = useQuery({
    queryKey: ["completed-files-digest", subject],
    queryFn: () => fetchCompletedFiles(subject),
    enabled: showFileSelect && !!subject,
  });

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
      queryClient.invalidateQueries({ queryKey: ["knowledge-overview", subject] });
      queryClient.invalidateQueries({ queryKey: ["graph-node-detail", subject] });
      setShowFileSelect(false);
      setSelectedFileIds(new Set());
      setLastBuildError("");
      setLastBuildMessage((data as { message?: string }).message ?? "构建已触发，稍后可刷新查看结果");
    },
  });

  const isJobRunning = buildMutation.isPending;

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

      {!!lastBuildMessage && <p className="mt-2 text-xs text-emerald-600">{lastBuildMessage}</p>}
      {!!lastBuildError && <p className="mt-2 text-xs text-red-500">{lastBuildError}</p>}

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
              disabled={selectedFileIds.size === 0 || buildMutation.isPending}
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
