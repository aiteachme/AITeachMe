import {
  type ChangeEvent,
  type DragEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Eye,
  Loader2,
  Paperclip,
  Sparkles,
  X,
} from "lucide-react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";

import { apiClient } from "../api/client";
import { Button } from "../components/ui/Button";
import { MarkdownViewer } from "../components/ui/MarkdownViewer";
import { Modal } from "../components/ui/Modal";
import { cn } from "../lib/utils";
import type { FileRecord, FilesData, FilesUploadData } from "../types/files";

interface ApiResponse<T> {
  code: number;
  data: T;
}

interface DocGenBuildData {
  job_id: number;
  accepted_file_ids: number[];
  prompt: string | null;
  ready_file_count: number;
}

async function fetchFiles(subject: string): Promise<FilesData> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "GET",
    url: `/api/v1/subjects/${subject}/files`,
  });
  return response.data;
}

async function uploadFiles(subject: string, files: File[]): Promise<FilesUploadData> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  const response = await apiClient<ApiResponse<FilesUploadData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/files/upload`,
    data: formData,
    headers: { "Content-Type": "multipart/form-data" },
  });
  return response.data;
}

async function deleteFile(subject: string, fileId: number): Promise<void> {
  await apiClient<ApiResponse<{ deleted_file_ids: number[] }>>({
    method: "DELETE",
    url: `/api/v1/subjects/${subject}/files/${fileId}`,
  });
}

async function triggerDocGenBuild(subject: string, prompt?: string): Promise<DocGenBuildData> {
  const response = await apiClient<ApiResponse<DocGenBuildData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/docgen/build`,
    data: { prompt },
  });
  return response.data;
}

const ACTIVE_FILE_STATUSES = new Set(["pending", "processing", "running"]);
const ACCEPT_TEXT = ".pdf,.docx,.doc,.md,.markdown,.txt,.png,.jpg,.jpeg";

function getFileStatusMeta(file: FileRecord) {
  if (file.markdown_ready) {
    return {
      label: "已就绪",
      tone: "text-emerald-600 bg-emerald-50 border-emerald-200",
      icon: <CheckCircle2 className="h-4 w-4 text-emerald-500" />,
    };
  }

  if (file.status === "failed") {
    return {
      label: "解析失败",
      tone: "text-red-600 bg-red-50 border-red-200",
      icon: <AlertCircle className="h-4 w-4 text-red-500" />,
    };
  }

  if (ACTIVE_FILE_STATUSES.has(file.status) || file.ingest_status !== "pending") {
    return {
      label: "解析中",
      tone: "text-indigo-600 bg-indigo-50 border-indigo-200",
      icon: <Loader2 className="h-4 w-4 animate-spin text-indigo-500" />,
    };
  }

  return {
    label: "等待处理",
    tone: "text-amber-600 bg-amber-50 border-amber-200",
    icon: <Loader2 className="h-4 w-4 animate-spin text-amber-500" />,
  };
}

export function UploadPage() {
  const { subjectId = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const state = location.state as { initialFiles?: File[]; initialPrompt?: string } | null;

  const [docPrompt, setDocPrompt] = useState(state?.initialPrompt || "");
  const [previewFile, setPreviewFile] = useState<FileRecord | null>(null);
  const [hasAutoUploaded, setHasAutoUploaded] = useState(false);

  const { data: filesData, isLoading } = useQuery({
    queryKey: ["files", subjectId],
    queryFn: () => fetchFiles(subjectId),
    enabled: !!subjectId,
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      return items.some((item) => !item.markdown_ready && item.status !== "failed") ? 2500 : false;
    },
  });

  const files = filesData?.items ?? [];
  const readyFiles = useMemo(() => files.filter((file) => file.markdown_ready), [files]);

  const uploadMutation = useMutation({
    mutationFn: (selectedFiles: File[]) => uploadFiles(subjectId, selectedFiles),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["files", subjectId] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (fileId: number) => deleteFile(subjectId, fileId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["files", subjectId] }),
  });

  const buildMutation = useMutation({
    mutationFn: () => triggerDocGenBuild(subjectId, docPrompt.trim() || undefined),
    onSuccess: (data) => navigate(`/subject/${subjectId}/doc?job_id=${data.job_id}`),
  });

  const handleUpload = useCallback(
    async (selectedFiles: File[]) => {
      if (!selectedFiles.length) {
        return;
      }
      await uploadMutation.mutateAsync(selectedFiles);
    },
    [uploadMutation],
  );

  useEffect(() => {
    if (state?.initialFiles?.length && !hasAutoUploaded && subjectId) {
      setHasAutoUploaded(true);
      void handleUpload(state.initialFiles);
      navigate(location.pathname, { replace: true, state: {} });
    }
  }, [state, subjectId, hasAutoUploaded, handleUpload, navigate, location.pathname]);

  const handleFileInputChange = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const selectedFiles = Array.from(event.target.files ?? []);
      event.target.value = "";
      await handleUpload(selectedFiles);
    },
    [handleUpload],
  );

  const handleDrop = useCallback(
    async (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      const droppedFiles = Array.from(event.dataTransfer.files ?? []);
      await handleUpload(droppedFiles);
    },
    [handleUpload],
  );

  const handlePreview = useCallback(
    (fileId: number) => {
      setPreviewFile(files.find((file) => file.id === fileId) ?? null);
    },
    [files],
  );

  return (
    <div className="relative flex min-h-full w-full flex-col items-center overflow-x-hidden bg-gradient-to-b from-slate-50 to-slate-200/40 px-4 pb-16 pt-10 md:pt-16">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div
          className="absolute left-1/4 top-10 h-[400px] w-[400px] animate-pulse rounded-full bg-sky-400/10 blur-3xl"
          style={{ animationDuration: "6s" }}
        />
        <div
          className="absolute bottom-10 right-1/4 h-[400px] w-[400px] animate-pulse rounded-full bg-indigo-500/10 blur-3xl"
          style={{ animationDuration: "8s" }}
        />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
        className="relative z-10 w-full max-w-4xl"
      >
        <div className="mb-10 text-center">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-sky-200/60 bg-white/60 px-3 py-1 text-xs font-medium text-sky-700 shadow-sm backdrop-blur">
            <Sparkles className="h-3.5 w-3.5" />
            上传资料，自动解析，直接进入知识构建
          </div>
          <h1 className="mb-3 text-3xl font-extrabold tracking-tight text-slate-900 md:text-4xl">
            为专属学习系统补充材料
          </h1>
          <p className="mx-auto max-w-2xl text-sm text-slate-500 md:text-base">
            文件上传后会自动进入解析流程。只要有至少一份资料完成解析，就可以直接开始生成知识文档。
          </p>
        </div>

        <div
          className="rounded-3xl border border-slate-200/80 bg-white/80 p-2 shadow-xl shadow-indigo-100 backdrop-blur-xl transition-shadow transition-colors focus-within:shadow-2xl focus-within:shadow-indigo-500/10"
          onDrop={handleDrop}
          onDragOver={(event) => event.preventDefault()}
        >
          <textarea
            value={docPrompt}
            onChange={(event) => setDocPrompt(event.target.value)}
            disabled={buildMutation.isPending}
            placeholder="知识文档生成要求，例如：整理成适合期末复习的文档，重点提炼概念、公式和典型题型。"
            className="min-h-[120px] max-h-[250px] w-full resize-none border-0 bg-transparent px-5 pb-2 pt-4 text-[15px] leading-relaxed text-slate-800 placeholder:text-slate-400 focus:outline-none"
          />

          <div className="flex flex-col gap-2 px-4 pb-2">
            <AnimatePresence>
              {files.length > 0 ? (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  className="flex flex-wrap gap-2 border-t border-slate-100 py-2"
                >
                  {files.map((file) => {
                    const meta = getFileStatusMeta(file);
                    return (
                      <motion.div
                        key={file.id}
                        layout
                        initial={{ opacity: 0, scale: 0.9 }}
                        animate={{ opacity: 1, scale: 1 }}
                        className={cn(
                          "group flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-sm font-medium transition-colors",
                          meta.tone,
                        )}
                        title={meta.label}
                      >
                        {meta.icon}
                        <span className="max-w-[140px] truncate">{file.filename}</span>
                        {file.markdown_ready ? (
                          <button
                            onClick={(event) => {
                              event.stopPropagation();
                              handlePreview(file.id);
                            }}
                            className="ml-1 p-0.5 opacity-60 transition-opacity hover:text-indigo-600 hover:opacity-100"
                            title="预览"
                          >
                            <Eye className="h-3.5 w-3.5" />
                          </button>
                        ) : null}
                        <button
                          onClick={(event) => {
                            event.stopPropagation();
                            deleteMutation.mutate(file.id);
                          }}
                          className="ml-0.5 p-0.5 opacity-60 transition-opacity hover:text-red-500 hover:opacity-100"
                          title="删除"
                          disabled={deleteMutation.isPending}
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </motion.div>
                    );
                  })}
                </motion.div>
              ) : null}
            </AnimatePresence>

            <div className="flex items-center justify-between pt-1">
              <div className="flex items-center gap-3">
                <input
                  type="file"
                  title="选择资料文件"
                  multiple
                  accept={ACCEPT_TEXT}
                  className="hidden"
                  ref={fileInputRef}
                  onChange={handleFileInputChange}
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800"
                >
                  <Paperclip className="h-4 w-4" />
                  上传文件资料
                </button>
                {uploadMutation.isPending ? (
                  <span className="flex items-center text-xs font-medium text-indigo-500">
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    上传中...
                  </span>
                ) : null}
                {buildMutation.isError ? (
                  <span className="flex items-center text-xs font-medium text-red-500">
                    <AlertCircle className="mr-1 h-3.5 w-3.5" />
                    构建失败，请重试
                  </span>
                ) : null}
              </div>

              <Button
                size="lg"
                onClick={() => buildMutation.mutate()}
                disabled={readyFiles.length === 0 || buildMutation.isPending}
                className={cn(
                  "rounded-full px-6 shadow-md transition-all duration-300",
                  readyFiles.length > 0 && !buildMutation.isPending
                    ? "bg-indigo-600 text-white shadow-indigo-500/20 hover:-translate-y-0.5 hover:bg-indigo-500 hover:shadow-lg"
                    : "bg-slate-100 text-slate-400",
                )}
              >
                {buildMutation.isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    正在生成文档...
                  </>
                ) : (
                  <>
                    开始生成知识文档
                    <ArrowRight className="ml-1.5 h-4 w-4" />
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>

        <div className="mt-6 flex flex-col items-center justify-center gap-2">
          {isLoading && files.length === 0 ? (
            <div className="flex items-center gap-1.5 text-sm text-slate-400">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载资料中...
            </div>
          ) : files.length === 0 ? (
            <div className="flex items-center gap-1.5 text-sm text-slate-400">
              提示：你可以直接把文件拖到上面的输入区域中
            </div>
          ) : (
            <div className="text-sm text-slate-400">
              已上传 <span className="font-semibold text-slate-700">{filesData?.total ?? files.length}</span> 份文件，就绪{" "}
              <span className="font-semibold text-emerald-600">{filesData?.ready_count ?? readyFiles.length}</span> 份
            </div>
          )}
        </div>
      </motion.div>

      <Modal
        open={previewFile !== null}
        onClose={() => setPreviewFile(null)}
        title={previewFile?.filename ?? "文件预览"}
        className="max-w-4xl"
      >
        <div className="space-y-4">
          {previewFile ? (
            <div className="flex flex-wrap gap-2 text-xs text-slate-500">
              <span className="rounded-full bg-slate-100 px-2.5 py-1">
                类型：{previewFile.filetype.toUpperCase()}
              </span>
              <span className="rounded-full bg-slate-100 px-2.5 py-1">
                状态：{previewFile.markdown_ready ? "可预览" : previewFile.status}
              </span>
            </div>
          ) : null}

          {previewFile?.markdown_content ? (
            <article className="prose prose-slate max-w-none">
              <MarkdownViewer
                content={previewFile.markdown_content}
                assetBaseUrl={previewFile.asset_base_url ?? undefined}
              />
            </article>
          ) : (
            <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-10 text-center text-sm text-slate-500">
              当前还没有可预览的 Markdown 内容。
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}
