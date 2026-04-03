import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle, FileText, Loader2, Play, Sparkles } from "lucide-react";

import { apiClient } from "../../api/client";
import type { ApiResponse } from "../../api/types";
import { useKnowledgeBuildFlow } from "../../hooks/useKnowledgeBuildFlow";
import type { FileRecord } from "../../types/files";
import { KnowledgeBuildResolutionModal } from "./KnowledgeBuildResolutionModal";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";

interface DigestBuildContextValue {
  subject: string;
}

interface FilesData {
  items: FileRecord[];
}

const DigestBuildContext = createContext<DigestBuildContextValue | null>(null);

async function fetchCompletedFiles(subject: string): Promise<FileRecord[]> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "GET",
    url: `/api/v1/subjects/${subject}/files`,
  });
  return (response.data?.items ?? []).filter((file) => file.markdown_ready);
}

export function DigestBuildProvider({
  subject,
  children,
}: {
  subject: string;
  children: ReactNode;
}) {
  return <DigestBuildContext.Provider value={{ subject }}>{children}</DigestBuildContext.Provider>;
}

function useDigestBuild() {
  const context = useContext(DigestBuildContext);
  if (!context) {
    throw new Error("useDigestBuild must be used inside DigestBuildProvider");
  }
  return context;
}

export function DigestBuildProgress() {
  return null;
}

export function DigestBuildButton() {
  const { subject } = useDigestBuild();
  const queryClient = useQueryClient();

  const [showFileSelect, setShowFileSelect] = useState(false);
  const [selectedFileUids, setSelectedFileUids] = useState<Set<string>>(new Set());
  const [lastBuildError, setLastBuildError] = useState("");
  const [lastBuildMessage, setLastBuildMessage] = useState("");

  const { data: readyFiles = [], isLoading: filesLoading } = useQuery({
    queryKey: ["digest-files", subject],
    queryFn: () => fetchCompletedFiles(subject),
    enabled: showFileSelect && Boolean(subject),
  });

  useEffect(() => {
    if (!showFileSelect || readyFiles.length === 0 || selectedFileUids.size > 0) {
      return;
    }
    setSelectedFileUids(new Set(readyFiles.map((file) => file.uid)));
  }, [readyFiles, selectedFileUids.size, showFileSelect]);

  const selectedCount = selectedFileUids.size;
  const hasReadyFiles = readyFiles.length > 0;

  const selectedFiles = useMemo(
    () => readyFiles.filter((file) => selectedFileUids.has(file.uid)),
    [readyFiles, selectedFileUids],
  );

  const knowledgeBuild = useKnowledgeBuildFlow({
    subjectId: subject,
    buildRequest: () => ({
      file_uids: Array.from(selectedFileUids),
    }),
    fallbackErrorMessage: "触发知识构建失败。",
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-overview", subject] });
      queryClient.invalidateQueries({ queryKey: ["docgen-content", subject] });
      setShowFileSelect(false);
      setSelectedFileUids(new Set());
      setLastBuildError("");
      setLastBuildMessage(
        `已触发构建，系统会同时更新知识文档和知识图谱。本次纳入 ${(data.accepted_file_uids ?? []).length} 份文件。`,
      );
    },
  });

  useEffect(() => {
    if (!knowledgeBuild.errorMessage) {
      return;
    }
    setLastBuildMessage("");
    setLastBuildError(knowledgeBuild.errorMessage);
  }, [knowledgeBuild.errorMessage]);

  const isBuilding = knowledgeBuild.isPending;

  const toggleFile = (fileUid: string) => {
    setSelectedFileUids((previous) => {
      const next = new Set(previous);
      if (next.has(fileUid)) {
        next.delete(fileUid);
      } else {
        next.add(fileUid);
      }
      return next;
    });
  };

  const openModal = () => {
    setLastBuildError("");
    setShowFileSelect(true);
  };

  const closeModal = () => {
    if (isBuilding) {
      return;
    }
    setShowFileSelect(false);
  };

  return (
    <>
      <Button onClick={openModal} variant="outline" size="sm" disabled={isBuilding}>
        {isBuilding ? (
          <>
            <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            构建中
          </>
        ) : (
          <>
            <Sparkles className="mr-1 h-4 w-4" />
            开始知识构建
          </>
        )}
      </Button>

      {lastBuildMessage ? <p className="mt-2 text-xs text-emerald-600">{lastBuildMessage}</p> : null}
      {lastBuildError ? <p className="mt-2 text-xs text-red-500">{lastBuildError}</p> : null}

      <Modal open={showFileSelect} onClose={closeModal} title="选择要纳入本次构建的文件">
        <div className="space-y-4">
          <p className="text-sm text-slate-500">
            这里选择的是本次知识构建要读取的已解析文件。提交后，知识文档和知识图谱页会一起更新。
          </p>

          {filesLoading ? (
            <div className="flex items-center py-4 text-sm text-slate-400">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              正在加载可用文件...
            </div>
          ) : null}

          {!filesLoading && !hasReadyFiles ? (
            <p className="py-4 text-sm text-slate-400">当前还没有可用于构建的已解析文件，请先上传并等待解析完成。</p>
          ) : null}

          {hasReadyFiles ? (
            <>
              <div className="max-h-60 space-y-2 overflow-y-auto">
                {readyFiles.map((file) => {
                  const checked = selectedFileUids.has(file.uid);
                  return (
                    <label
                      key={file.uid}
                      className={`flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition-colors ${
                        checked ? "border-slate-400 bg-slate-50" : "border-slate-200 hover:bg-slate-50"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleFile(file.uid)}
                        className="rounded border-slate-300"
                      />
                      <FileText className="h-4 w-4 text-slate-400" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm text-slate-700">{file.filename}</p>
                        <p className="text-xs text-slate-400">
                          {file.filetype.toUpperCase()} · {file.status}
                        </p>
                      </div>
                      <CheckCircle className="h-4 w-4 text-green-500" />
                    </label>
                  );
                })}
              </div>

              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
                已选择 {selectedCount} 份文件
                {selectedFiles.length > 0 ? "，将用于本次知识构建。" : "。"}
              </div>
            </>
          ) : null}

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={closeModal} disabled={isBuilding}>
              取消
            </Button>
            <Button onClick={knowledgeBuild.submitBuild} disabled={!selectedCount || isBuilding}>
              {isBuilding ? (
                <>
                  <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                  提交中...
                </>
              ) : (
                <>
                  <Play className="mr-1 h-4 w-4" />
                  开始构建
                </>
              )}
            </Button>
          </div>
        </div>
      </Modal>

      <KnowledgeBuildResolutionModal
        open={knowledgeBuild.precheckConflict !== null}
        conflict={knowledgeBuild.precheckConflict}
        isSubmitting={knowledgeBuild.isPending}
        onClose={knowledgeBuild.closePrecheckConflict}
        onResolve={knowledgeBuild.resolvePrecheckConflict}
      />
    </>
  );
}

