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
  RefreshCw,
  Sparkles,
  Paperclip,
  FileUp,
  X,
} from "lucide-react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";

import { apiClient } from "../api/client";
import {
  deleteFilesApiApiV1SubjectsSubjectFilesDeletePost,
  getFileApiApiV1SubjectsSubjectFilesGetPost,
  listFilesApiApiV1SubjectsSubjectFilesListPost,
  retryUploadedFileApiV1SubjectsSubjectFilesRetryPost,
  uploadFilesApiV1SubjectsSubjectFilesUploadPost,
} from "../api/generated/files";
import type { FileGetData, FileItem, FilesUploadData } from "../api/generated/model";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { Button } from "../components/ui/Button";
import { MarkdownViewer } from "../components/ui/MarkdownViewer";
import { Modal } from "../components/ui/Modal";
import { cn } from "../lib/utils";

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

// API functions
async function fetchFiles(subject: string): Promise<FileItem[]> {
  const response = await listFilesApiApiV1SubjectsSubjectFilesListPost(subject, {
    page: 1,
    size: 100,
  });
  return unwrapOrvalResponse<{ items?: FileItem[] }>(response)?.items ?? [];
}

async function fetchFileResult(subject: string, fileId: number): Promise<FileGetData> {
  const response = await getFileApiApiV1SubjectsSubjectFilesGetPost(subject, {
    file_id: fileId,
  });
  const data = unwrapOrvalResponse<FileGetData>(response);
  if (!data) throw new Error("加载文件解析结果失败");
  return data;
}

async function uploadFiles(subject: string, files: File[]): Promise<FilesUploadData> {
  const response = await uploadFilesApiV1SubjectsSubjectFilesUploadPost(subject, { files });
  const data = unwrapOrvalResponse<FilesUploadData>(response);
  if (!data) throw new Error("上传文件失败");
  return data;
}

async function retryFile(subject: string, fileId: number): Promise<void> {
  await retryUploadedFileApiV1SubjectsSubjectFilesRetryPost(subject, { file_id: fileId });
}

async function deleteFile(subject: string, fileId: number): Promise<void> {
  await deleteFilesApiApiV1SubjectsSubjectFilesDeletePost(subject, { file_id: fileId });
}

async function triggerDocGenBuild(subject: string, prompt?: string): Promise<DocGenBuildData> {
  const res = await apiClient<ApiResponse<DocGenBuildData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/docgen/build`,
    data: { prompt },
  });
  return res.data;
}

const ACTIVE_FILE_STATUSES = new Set(["pending", "processing", "running"]);
const ACCEPT_TEXT = ".pdf,.docx,.doc,.md,.markdown,.txt,.png,.jpg,.jpeg";

function getFileStatusMeta(file: FileItem) {
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
    icon: <RefreshCw className="h-4 w-4 text-amber-500 animate-spin-slow" />,
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
  const [previewFile, setPreviewFile] = useState<FileGetData | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [hasAutoUploaded, setHasAutoUploaded] = useState(false);

  const { data: files = [], isLoading } = useQuery({
    queryKey: ["files", subjectId],
    queryFn: () => fetchFiles(subjectId),
    enabled: !!subjectId,
    refetchInterval: (query) => {
      const items = query.state.data ?? [];
      return items.some((item) => !item.markdown_ready && item.status !== "failed") ? 2500 : false;
    },
  });

  const readyFiles = useMemo(() => files.filter((f) => f.markdown_ready), [files]);

  const uploadMutation = useMutation({
    mutationFn: (selectedFiles: File[]) => uploadFiles(subjectId, selectedFiles),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["files", subjectId] }),
  });

  const retryMutation = useMutation({
    mutationFn: (fileId: number) => retryFile(subjectId, fileId),
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
      if (!selectedFiles.length) return;
      await uploadMutation.mutateAsync(selectedFiles);
    },
    [uploadMutation]
  );

  // Auto upload initial files from state
  useEffect(() => {
    if (state?.initialFiles?.length && !hasAutoUploaded && subjectId) {
      setHasAutoUploaded(true);
      void handleUpload(state.initialFiles);
      navigate(location.pathname, { replace: true, state: {} }); // Clear state
    }
  }, [state, subjectId, hasAutoUploaded, handleUpload, navigate, location.pathname]);

  const handleFileInputChange = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const selectedFiles = Array.from(event.target.files ?? []);
      event.target.value = "";
      await handleUpload(selectedFiles);
    },
    [handleUpload]
  );

  const handleDrop = useCallback(
    async (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      const droppedFiles = Array.from(event.dataTransfer.files ?? []);
      await handleUpload(droppedFiles);
    },
    [handleUpload]
  );

  const handlePreview = useCallback(
    async (fileId: number) => {
      setPreviewLoading(true);
      try {
        const data = await fetchFileResult(subjectId, fileId);
        setPreviewFile(data);
      } finally {
        setPreviewLoading(false);
      }
    },
    [subjectId]
  );

  return (
    <div className="min-h-full w-full bg-gradient-to-b from-slate-50 to-slate-200/40 flex flex-col items-center px-4 pt-10 md:pt-16 pb-16 relative overflow-x-hidden">
      {/* Background Decor */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-10 left-1/4 w-[400px] h-[400px] bg-sky-400/10 rounded-full blur-3xl animate-pulse" style={{ animationDuration: '6s' }} />
        <div className="absolute bottom-10 right-1/4 w-[400px] h-[400px] bg-indigo-500/10 rounded-full blur-3xl animate-pulse" style={{ animationDuration: '8s' }} />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
        className="relative z-10 w-full max-w-4xl"
      >
        <div className="text-center mb-10">
          <div className="inline-flex items-center gap-2 rounded-full border border-sky-200/60 bg-white/60 px-3 py-1 text-xs font-medium text-sky-700 backdrop-blur shadow-sm mb-4">
            <Sparkles className="h-3.5 w-3.5" />
            上传资料 自动解析 构建知识文档
          </div>
          <h1 className="text-3xl md:text-4xl font-extrabold text-slate-900 tracking-tight mb-3">为专属学习构建语料</h1>
          <p className="text-slate-500 text-sm md:text-base max-w-2xl mx-auto">
            补充更多材料或完善要求。当至少有一份文件解析就绪后，即可一键生成知识文档。
          </p>
        </div>

        {/* Central Hub Area */}
        <div
          className="bg-white/80 backdrop-blur-xl border border-slate-200/80 rounded-3xl shadow-xl shadow-indigo-100 p-2 focus-within:shadow-2xl focus-within:shadow-indigo-500/10 transition-shadow transition-colors"
          onDrop={handleDrop}
          onDragOver={(e) => e.preventDefault()}
        >
          {/* Main Request Input */}
          <textarea
            value={docPrompt}
            onChange={(e) => setDocPrompt(e.target.value)}
            disabled={buildMutation.isPending}
            placeholder="知识文档生成要求（例如：整理成适合期末复习的文档，重点提炼常见题型...）"
            className="w-full resize-none border-0 bg-transparent px-5 pt-4 pb-2 text-[15px] leading-relaxed text-slate-800 placeholder:text-slate-400 focus:outline-none min-h-[120px] max-h-[250px] transition-all"
          />

          {/* Files List Inline inside the box */}
          <div className="px-4 pb-2 flex flex-col gap-2">
            <AnimatePresence>
              {files.length > 0 && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  className="flex flex-wrap gap-2 py-2 border-t border-slate-100"
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
                          "flex items-center gap-1.5 border px-2.5 py-1.5 rounded-lg transition-colors group text-sm font-medium",
                          meta.tone
                        )}
                        title={meta.label}
                      >
                        {meta.icon}
                        <span className="max-w-[120px] truncate">{file.filename}</span>
                        {file.markdown_ready ? (
                          <button
                            onClick={(e) => { e.stopPropagation(); void handlePreview(file.id); }}
                            className="ml-1 opacity-60 hover:opacity-100 hover:text-indigo-600 transition-opacity p-0.5"
                            title="预览"
                          >
                            <Eye className="w-3.5 h-3.5" />
                          </button>
                        ) : null}
                        {file.status === "failed" ? (
                          <button
                            onClick={(e) => { e.stopPropagation(); retryMutation.mutate(file.id); }}
                            className="ml-1 opacity-60 hover:opacity-100 hover:text-indigo-600 transition-opacity p-0.5"
                            title="重试解析"
                            disabled={retryMutation.isPending}
                          >
                            <RefreshCw className={cn("w-3.5 h-3.5", retryMutation.isPending && "animate-spin")} />
                          </button>
                        ) : null}
                        <button
                          onClick={(e) => { e.stopPropagation(); deleteMutation.mutate(file.id); }}
                          className="ml-0.5 opacity-60 hover:opacity-100 hover:text-red-500 transition-opacity p-0.5"
                          title="删除"
                          disabled={deleteMutation.isPending}
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </motion.div>
                    );
                  })}
                </motion.div>
              )}
            </AnimatePresence>

            {/* Bottom Actions Row */}
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
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-800 transition-colors"
                >
                  <Paperclip className="w-4 h-4" />
                  上传文件资料
                </button>
                {uploadMutation.isPending && (
                  <span className="text-xs text-indigo-500 font-medium flex items-center">
                    <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> 上传中...
                  </span>
                )}
                {buildMutation.isError && (
                  <span className="text-xs text-red-500 font-medium flex items-center">
                    <AlertCircle className="w-3.5 h-3.5 mr-1" /> 构建失败，请重试
                  </span>
                )}
              </div>

              <Button
                size="lg"
                onClick={() => buildMutation.mutate()}
                disabled={readyFiles.length === 0 || buildMutation.isPending}
                className={cn(
                  "rounded-full px-6 transition-all duration-300 shadow-md",
                  readyFiles.length > 0 && !buildMutation.isPending
                    ? "bg-indigo-600 text-white hover:bg-indigo-500 hover:-translate-y-0.5 hover:shadow-lg shadow-indigo-500/20"
                    : "bg-slate-100 text-slate-400"
                )}
              >
                {buildMutation.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    正在生成文档...
                  </>
                ) : (
                  <>
                    开始生成知识文档
                    <ArrowRight className="w-4 h-4 ml-1.5" />
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>

        {/* Info Text below */}
        <div className="mt-6 flex flex-col items-center justify-center gap-2">
          {isLoading && files.length === 0 ? (
            <div className="text-sm text-slate-400 flex items-center gap-1.5">
              <Loader2 className="w-4 h-4 animate-spin" /> 加载资料中...
            </div>
          ) : files.length === 0 ? (
            <div className="text-sm text-slate-400 flex items-center gap-1.5">
              提示：您可以直接拖拽文件到上面的输入框内
            </div>
          ) : (
            <div className="text-sm text-slate-400">
              已上传 <span className="font-semibold text-slate-700">{files.length}</span> 份文件，就绪 <span className="font-semibold text-emerald-600">{readyFiles.length}</span> 份
            </div>
          )}
        </div>
      </motion.div>

      {previewLoading && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
          <div className="flex items-center gap-3 rounded-2xl bg-white px-5 py-4 shadow-xl">
            <Loader2 className="h-5 w-5 animate-spin text-slate-500" />
            <span className="text-sm text-slate-600">正在加载解析结果...</span>
          </div>
        </div>
      )}

      {/* File Preview Modal */}
      <Modal
        open={previewFile !== null}
        onClose={() => setPreviewFile(null)}
        title={previewFile?.filename ?? "文件预览"}
        className="max-w-4xl"
      >
        <div className="space-y-4">
          {previewFile && (
            <div className="flex flex-wrap gap-2 text-xs text-slate-500">
              <span className="rounded-full bg-slate-100 px-2.5 py-1">
                类型：{previewFile.filetype.toUpperCase()}
              </span>
              <span className="rounded-full bg-slate-100 px-2.5 py-1">
                状态：{previewFile.markdown_ready ? "可预览" : previewFile.status}
              </span>
            </div>
          )}

          {previewFile?.markdown_content ? (
            <article className="prose prose-slate max-w-none">
              <MarkdownViewer content={previewFile.markdown_content} />
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
