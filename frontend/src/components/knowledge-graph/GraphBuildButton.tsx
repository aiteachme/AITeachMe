import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  FileText,
  Loader2,
  Play,
  Sparkles,
} from "lucide-react";

import { apiClient } from "../../api/client";
import type { ApiResponse } from "../../api/types";
import { useKnowledgeBuildFlow } from "../../hooks/useKnowledgeBuildFlow";
import type { FileRecord } from "../../types/files";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";
import { useToast } from "../ui/Toast";
import { KnowledgeBuildResolutionModal } from "../build-plan/KnowledgeBuildResolutionModal";

interface FilesData {
  items: FileRecord[];
}

export interface GraphBuildAutoLaunch {
  requestKey: string;
  fileUids?: string[];
  autoStart?: boolean;
  sourceLabel?: string;
}

async function fetchCompletedFiles(subject: string): Promise<FileRecord[]> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "GET",
    url: `/api/v1/subjects/${subject}/files`,
  });
  return (response.data?.items ?? []).filter((file) => file.markdown_ready);
}

export function GraphBuildButton({
  subject,
  autoLaunch = null,
}: {
  subject: string;
  autoLaunch?: GraphBuildAutoLaunch | null;
}) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const autoLaunchHandledRef = useRef("");

  const [showFileSelect, setShowFileSelect] = useState(false);
  const [selectedFileUids, setSelectedFileUids] = useState<Set<string>>(new Set());
  const [lastBuildError, setLastBuildError] = useState("");
  const [lastBuildMessage, setLastBuildMessage] = useState("");

  const normalizedAutoLaunch = useMemo(() => {
    if (!autoLaunch?.requestKey?.trim()) {
      return null;
    }

    return {
      requestKey: autoLaunch.requestKey.trim(),
      fileUids: Array.from(new Set((autoLaunch.fileUids ?? []).map((item) => item.trim()).filter(Boolean))),
      autoStart: Boolean(autoLaunch.autoStart),
      sourceLabel: autoLaunch.sourceLabel?.trim() || "",
    };
  }, [autoLaunch]);

  const { data: readyFiles = [], isLoading: filesLoading } = useQuery({
    queryKey: ["graph-build-files", subject],
    queryFn: () => fetchCompletedFiles(subject),
    enabled: Boolean(subject) && (showFileSelect || normalizedAutoLaunch !== null),
  });

  useEffect(() => {
    if (!showFileSelect || readyFiles.length === 0 || selectedFileUids.size > 0) {
      return;
    }
    setSelectedFileUids(new Set(readyFiles.map((file) => file.uid)));
  }, [readyFiles, selectedFileUids.size, showFileSelect]);

  const selectedFiles = useMemo(
    () => readyFiles.filter((file) => selectedFileUids.has(file.uid)),
    [readyFiles, selectedFileUids],
  );

  const knowledgeBuild = useKnowledgeBuildFlow({
    subjectId: subject,
    buildType: "graph",
    buildRequest: () => ({
      file_uids: Array.from(selectedFileUids),
    }),
    fallbackErrorMessage: "触发知识图谱构建失败。",
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-doc-build", subject] });
      queryClient.invalidateQueries({ queryKey: ["knowledge-overview", subject] });
      queryClient.invalidateQueries({ queryKey: ["graph-node-detail", subject] });
      queryClient.invalidateQueries({ queryKey: ["docgen-content", subject] });
      setShowFileSelect(false);
      setSelectedFileUids(new Set());
      setLastBuildError("");
      setLastBuildMessage(
        `已触发知识图谱构建，本轮纳入 ${(data.accepted_file_uids ?? []).length} 份已解析资料，图谱和课程结构会同步刷新。`,
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

  useEffect(() => {
    if (!normalizedAutoLaunch || autoLaunchHandledRef.current === normalizedAutoLaunch.requestKey) {
      return;
    }
    setLastBuildError("");
    setLastBuildMessage("");
    setShowFileSelect(true);
    setSelectedFileUids(new Set(normalizedAutoLaunch.fileUids));
  }, [normalizedAutoLaunch]);

  useEffect(() => {
    if (!normalizedAutoLaunch?.autoStart || autoLaunchHandledRef.current === normalizedAutoLaunch.requestKey) {
      return;
    }
    if (filesLoading || knowledgeBuild.isPending) {
      return;
    }

    const readyUidSet = new Set(readyFiles.map((file) => file.uid));
    const targetFileUids = normalizedAutoLaunch.fileUids.filter((uid) => readyUidSet.has(uid));
    if (targetFileUids.length === 0) {
      autoLaunchHandledRef.current = normalizedAutoLaunch.requestKey;
      setLastBuildMessage("");
      setLastBuildError("当前还没有可用于图谱构建的已解析文件，请先上传并等待解析完成。");
      if (normalizedAutoLaunch.fileUids.length > 0) {
        toast({
          title: "暂时无法开始图谱构建",
          description: normalizedAutoLaunch.sourceLabel
            ? `${normalizedAutoLaunch.sourceLabel}带来的文件还没有解析完成。`
            : "当前还没有可用于图谱构建的已解析文件。",
          variant: "warning",
        });
      }
      return;
    }

    autoLaunchHandledRef.current = normalizedAutoLaunch.requestKey;
    setSelectedFileUids(new Set(targetFileUids));
    knowledgeBuild.submitBuild({ file_uids: targetFileUids });
  }, [filesLoading, knowledgeBuild, normalizedAutoLaunch, readyFiles, toast]);

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
    setLastBuildMessage("");
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
      <div className="flex flex-col items-end gap-2">
        <Button onClick={openModal} variant="outline" size="sm" disabled={isBuilding}>
          {isBuilding ? (
            <>
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              图谱构建中...
            </>
          ) : (
            <>
              <Sparkles className="mr-1 h-4 w-4" />
              构建图谱
            </>
          )}
        </Button>

        {lastBuildMessage ? <p className="max-w-xs text-right text-xs leading-5 text-emerald-600">{lastBuildMessage}</p> : null}
        {lastBuildError ? <p className="max-w-xs text-right text-xs leading-5 text-rose-500">{lastBuildError}</p> : null}
      </div>

      <Modal open={showFileSelect} onClose={closeModal} title="选择本轮知识图谱构建使用的文件">
        <div className="space-y-4">
          <p className="text-sm leading-6 text-slate-500">
            这里选中的已解析文件会以 parsed markdown 作为输入，刷新知识图谱、教学单元、主题树和先修关系，方便单独调试 graph lane。
          </p>

          {filesLoading ? (
            <div className="flex items-center py-4 text-sm text-slate-400">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              正在加载可用文件...
            </div>
          ) : null}

          {!filesLoading && readyFiles.length === 0 ? (
            <p className="py-4 text-sm text-slate-400">
              当前还没有可用于图谱构建的已解析文件，请先上传并等待解析完成。
            </p>
          ) : null}

          {readyFiles.length > 0 ? (
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
                      {checked ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : null}
                    </label>
                  );
                })}
              </div>

              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
                已选择 {selectedFiles.length} 份文件进入本轮知识图谱构建。
              </div>
            </>
          ) : null}

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={closeModal} disabled={isBuilding}>
              取消
            </Button>
            <Button onClick={() => knowledgeBuild.submitBuild()} disabled={selectedFileUids.size === 0 || isBuilding}>
              {isBuilding ? (
                <>
                  <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                  提交中...
                </>
              ) : (
                <>
                  <Play className="mr-1 h-4 w-4" />
                  开始构建图谱
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
