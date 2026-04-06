import {
  type ChangeEvent,
  type DragEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Eye,
  FileText,
  FileImage,
  FileCode,
  FileType,
  Loader2,
  Network,
  Paperclip,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";

import { apiClient, getApiErrorMessage } from "../api/client";
import type { ApiResponse } from "../api/types";
import { KnowledgeBuildResolutionModal } from "../components/pages/KnowledgeBuildResolutionModal";
import { SubjectVectorNotice } from "../components/pages/SubjectVectorNotice";
import { Button } from "../components/ui/Button";
import { FullPageDropOverlay } from "../components/ui/FullPageDropOverlay";
import { MarkdownViewer } from "../components/ui/MarkdownViewer";
import { Modal } from "../components/ui/Modal";
import { useKnowledgeBuildFlow } from "../hooks/useKnowledgeBuildFlow";
import { useSettings } from "../hooks/useSettings";
import { fetchKnowledgeDocState, buildKnowledgeDocStateQueryKey } from "../lib/knowledgeDocs";
import { cn } from "../lib/utils";
import type { FileRecord, FilesData, FilesUploadData } from "../types/files";
import { useToast } from "../components/ui/Toast";

const ACTIVE_FILE_STATUSES = new Set(["pending", "processing", "running"]);
const ACCEPT_TEXT = ".pdf,.docx,.doc,.ppt,.pptx,.md,.markdown,.txt,.png,.jpg,.jpeg,.webp";
const PAPER_CARD = "rounded-2xl border border-zinc-200/80 bg-white shadow-[0_2px_8px_rgba(0,0,0,0.04)] transition-all hover:border-zinc-300 hover:shadow-[0_8px_24px_rgba(0,0,0,0.08)]";

/* ── API helpers ── */

async function fetchFiles(subject: string): Promise<FilesData> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "GET",
    url: `/api/v1/subjects/${subject}/files`,
  });
  return response.data ?? { subject, total: 0, ready_count: 0, processing_count: 0, failed_count: 0, items: [] };
}

async function uploadFiles(subject: string, files: File[]): Promise<FilesUploadData> {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }

  const response = await apiClient<ApiResponse<FilesUploadData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/files/upload`,
    data: formData,
  });
  return response.data ?? { subject, filenames: [], uploaded_items: [], started_parse_count: 0 };
}

async function deleteFile(subject: string, fileUid: string): Promise<void> {
  await apiClient<ApiResponse<{ deleted_file_uids: string[] }>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/files/delete`,
    data: { file_uid: fileUid },
  });
}

/* ── 工具函数 ── */

function getFileStatusMeta(file: FileRecord) {
  if (file.markdown_ready) {
    return {
      label: "已完成",
      tone: "text-emerald-600 bg-emerald-50 border-emerald-200",
      dotColor: "bg-emerald-500",
      icon: <CheckCircle2 className="h-4 w-4 text-emerald-500" />,
    };
  }

  if (file.status === "failed") {
    return {
      label: "解析失败",
      tone: "text-red-600 bg-red-50 border-red-200",
      dotColor: "bg-red-500",
      icon: <AlertCircle className="h-4 w-4 text-red-500" />,
    };
  }

  if (ACTIVE_FILE_STATUSES.has(file.status) || file.ingest_status !== "pending") {
    const stageLabels: Record<string, string> = {
      classifying: "分类中…",
      fast_parsing: "解析中…",
      fast_parsed: "已解析",
      enhancing: "优化中…",
      ready_for_digest: "就绪",
    };
    const label = stageLabels[file.ingest_status] ?? "处理中…";
    return {
      label,
      tone: "text-slate-700 bg-slate-50 border-slate-200",
      dotColor: "bg-sky-500 animate-pulse",
      icon: <Loader2 className="h-4 w-4 animate-spin text-slate-500" />,
    };
  }

  return {
    label: "等待处理",
    tone: "text-amber-600 bg-amber-50 border-amber-200",
    dotColor: "bg-amber-500 animate-pulse",
    icon: <Loader2 className="h-4 w-4 animate-spin text-amber-500" />,
  };
}

function getFileIcon(file: FileRecord) {
  const ext = file.filetype?.toLowerCase();
  if (ext === "pdf") return <FileText className="h-5 w-5 text-red-400" />;
  if (["png", "jpg", "jpeg", "webp"].includes(ext ?? "")) return <FileImage className="h-5 w-5 text-emerald-400" />;
  if (["md", "markdown"].includes(ext ?? "")) return <FileCode className="h-5 w-5 text-violet-400" />;
  if (["docx", "doc"].includes(ext ?? "")) return <FileText className="h-5 w-5 text-blue-400" />;
  if (["ppt", "pptx"].includes(ext ?? "")) return <FileType className="h-5 w-5 text-orange-400" />;
  return <FileText className="h-5 w-5 text-slate-400" />;
}

function formatFileType(file: FileRecord): string {
  return file.filetype ? file.filetype.toUpperCase() : "未知格式";
}

function formatFileSize(bytes?: number | null): string {
  if (bytes == null || !Number.isFinite(bytes)) return "未知";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value >= 10 || unitIndex === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unitIndex]}`;
}

function formatDateTime(value?: string | null): string {
  if (!value) return "未记录";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatLanguage(language?: string | null): string {
  if (!language) return "自动识别中";
  if (language === "zh") return "中文";
  if (language === "en") return "英文";
  return language.toUpperCase();
}

function getParserSummary(file: FileRecord): string {
  if (file.parser_used) {
    return `本文件已使用 ${file.parser_used} 完成解析，系统会优先产出 Markdown 文档，并保留可直接展示的图片等资源文件。`;
  }
  if (file.status === "failed") {
    return "本次解析未成功完成，请查看错误信息，必要时重新上传更清晰或更完整的资料。";
  }
  return "文件已进入自动解析流程，系统会根据格式选择合适的解析链路并持续更新结果。";
}

/* ── 页面外壳 ── */

function PageWrapper({
  children,
  title,
  subtitle,
  badgeText,
}: {
  children: React.ReactNode;
  title: React.ReactNode;
  subtitle?: string;
  badgeText?: string;
}) {
  return (
    <div className="relative flex min-h-[100dvh] w-full flex-col items-center overflow-x-hidden bg-zinc-50 p-4 pt-16 md:p-8 md:pt-24 selection:bg-zinc-200">
      <div className="pointer-events-none absolute inset-0 z-0 flex justify-center overflow-hidden">
        <div className="h-full w-full bg-[linear-gradient(to_right,#e4e4e7_1px,transparent_1px),linear-gradient(to_bottom,#e4e4e7_1px,transparent_1px)] bg-[size:32px_32px] [mask-image:radial-gradient(ellipse_120%_100%_at_50%_0%,#000_50%,transparent_100%)]"></div>
      </div>
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
        className="relative z-10 w-full max-w-5xl space-y-6"
      >
        <div className="mb-10 text-center">
          {badgeText ? (
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-zinc-200/80 bg-white px-3 py-1.5 text-[11px] font-semibold uppercase tracking-widest text-zinc-500 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
              <Sparkles className="h-3 w-3" />
              {badgeText}
            </div>
          ) : null}
          <h1 className="mb-3 text-3xl font-semibold tracking-tight text-zinc-900 md:text-4xl">{title}</h1>
          {subtitle ? <p className="mx-auto max-w-2xl text-[15px] leading-relaxed text-zinc-500">{subtitle}</p> : null}
        </div>
        {children}
      </motion.div>
    </div>
  );
}

/* ── 精简模式文件卡片 ── */

function FileCard({
  file,
  onDelete,
  isDeleting,
}: {
  file: FileRecord;
  onDelete: () => void;
  isDeleting: boolean;
}) {
  const meta = getFileStatusMeta(file);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: -20 }}
      className="group flex items-center gap-3 rounded-xl border border-zinc-200/80 bg-white px-4 py-3 shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition-all hover:border-zinc-300 hover:shadow-[0_4px_12px_rgba(0,0,0,0.04)]"
    >
      {/* 文件类型图标 */}
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-zinc-50 border border-zinc-100">
        {getFileIcon(file)}
      </div>

      {/* 文件信息 */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-medium text-zinc-900">{file.filename}</p>
          <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium leading-none", meta.tone)}>
            <span className={cn("h-1.5 w-1.5 rounded-full", meta.dotColor)} />
            {meta.label}
          </span>
        </div>
        <div className="mt-0.5 flex items-center gap-3 text-xs text-zinc-400">
          <span>{formatFileType(file)}</span>
          <span>·</span>
          <span>{formatFileSize(file.file_size_bytes)}</span>
          {file.estimated_pages != null && (
            <>
              <span>·</span>
              <span>{file.estimated_pages} 页</span>
            </>
          )}
          {file.detected_language && (
            <>
              <span>·</span>
              <span>{formatLanguage(file.detected_language)}</span>
            </>
          )}
        </div>
      </div>

      {/* 删除按钮 */}
      <button
        type="button"
        onClick={onDelete}
        disabled={isDeleting}
        className="shrink-0 rounded-lg p-1.5 text-slate-300 opacity-0 transition-all hover:bg-red-50 hover:text-red-500 group-hover:opacity-100 disabled:opacity-30"
        title="删除文件"
      >
        <Trash2 className="h-4 w-4" />
      </button>
    </motion.div>
  );
}

/* ── 主页面组件 ── */

export function FilesPage() {
  const { subjectId = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { settings } = useSettings();
  const { toast } = useToast();

  const state = location.state as { initialFiles?: File[]; initialPrompt?: string } | null;

  const [docPrompt, setDocPrompt] = useState(state?.initialPrompt ?? "");
  const [selectedFileUid, setSelectedFileUid] = useState<string | null>(null);
  const [previewFileUid, setPreviewFileUid] = useState<string | null>(null);
  const [hasAutoUploaded, setHasAutoUploaded] = useState(false);

  const debugMode = settings.debugMode;

  const { data: filesData, isLoading } = useQuery({
    queryKey: ["files", subjectId],
    queryFn: () => fetchFiles(subjectId),
    enabled: Boolean(subjectId),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      return items.some((item) => !item.markdown_ready && item.status !== "failed") ? 1500 : false;
    },
  });

  const { data: knowledgeDocState } = useQuery({
    queryKey: buildKnowledgeDocStateQueryKey(subjectId),
    queryFn: () => fetchKnowledgeDocState(subjectId),
    enabled: Boolean(subjectId),
    retry: false,
  });

  const files = filesData?.items ?? [];
  const readyFiles = useMemo(() => files.filter((file) => file.markdown_ready), [files]);
  const selectedFile = useMemo(
    () => files.find((file) => file.uid === selectedFileUid) ?? files[0] ?? null,
    [files, selectedFileUid],
  );
  const previewFile = useMemo(
    () => files.find((file) => file.uid === previewFileUid) ?? null,
    [files, previewFileUid],
  );

  const uploadMutation = useMutation({
    mutationFn: (selectedFiles: File[]) => uploadFiles(subjectId, selectedFiles),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["files", subjectId] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (fileUid: string) => deleteFile(subjectId, fileUid),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["files", subjectId] }),
  });

  const knowledgeDocsBuild = useKnowledgeBuildFlow({
    subjectId,
    buildType: "docs",
    buildRequest: () => ({
      prompt: docPrompt.trim() || undefined,
    }),
    fallbackErrorMessage: "知识文档构建失败",
    onSuccess: (data) => {
      const rawData = data as unknown as Record<string, unknown>;
      const vectorStatus = rawData?.vector_status as
        | { notice?: string }
        | undefined;
      if (vectorStatus?.notice) {
        toast({
          title: "向量索引已自动更新",
          description: vectorStatus.notice,
          variant: "info",
          duration: 6000,
        });
      }
      navigate(`/subject/${subjectId}/knowledge-docs?requested_at=${encodeURIComponent(data.requested_at)}`);
    },
  });

  const knowledgeGraphBuild = useKnowledgeBuildFlow({
    subjectId,
    buildType: "graph",
    buildRequest: () => ({
      prompt: docPrompt.trim() || undefined,
    }),
    fallbackErrorMessage: "知识图谱构建失败",
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-overview", subjectId] });
      toast({
        title: "知识图谱构建已启动",
        description: `本轮纳入 ${(data.accepted_file_uids ?? []).length} 份资料，图谱和课程结构会自动刷新。`,
        variant: "info",
        duration: 5000,
      });
    },
  });

  const isAnyBuildPending = knowledgeDocsBuild.isPending || knowledgeGraphBuild.isPending;
  const activeBuildError = knowledgeDocsBuild.errorMessage || knowledgeGraphBuild.errorMessage;

  const handleUpload = useCallback(
    async (selectedFiles: File[]) => {
      if (!selectedFiles.length) return;
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
  }, [handleUpload, hasAutoUploaded, location.pathname, navigate, state, subjectId]);

  useEffect(() => {
    if (!files.length) {
      if (selectedFileUid !== null) setSelectedFileUid(null);
      if (previewFileUid !== null) setPreviewFileUid(null);
      return;
    }
    if (selectedFileUid === null || !files.some((file) => file.uid === selectedFileUid)) {
      setSelectedFileUid(files[0].uid);
    }
    if (previewFileUid !== null && !files.some((file) => file.uid === previewFileUid)) {
      setPreviewFileUid(null);
    }
  }, [files, previewFileUid, selectedFileUid]);

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

  const fileStats = [
    { label: "已上传文件", value: filesData?.total ?? files.length, tone: "text-slate-900" },
    { label: "已完成解析", value: filesData?.ready_count ?? readyFiles.length, tone: "text-emerald-600" },
    {
      label: "处理中",
      value: filesData?.processing_count ?? Math.max(files.length - readyFiles.length, 0),
      tone: "text-sky-600",
    },
    {
      label: "解析失败",
      value: filesData?.failed_count ?? files.filter((file) => file.status === "failed").length,
      tone: "text-rose-600",
    },
  ];

  const selectedStatus = selectedFile ? getFileStatusMeta(selectedFile) : null;
  const selectedAssetCount = selectedFile?.assets?.length ?? 0;

  const parseFacts = selectedFile
    ? [
        { label: "解析方法", value: selectedFile.parser_used ?? "自动选择中" },
        { label: "文件格式", value: formatFileType(selectedFile) },
        { label: "文件大小", value: formatFileSize(selectedFile.file_size_bytes) },
        { label: "检测语言", value: formatLanguage(selectedFile.detected_language) },
        {
          label: "估计页数",
          value: selectedFile.estimated_pages != null ? String(selectedFile.estimated_pages) : "未识别",
        },
        { label: "图片资源", value: `${selectedFile.image_count ?? 0} 张` },
        { label: "资源文件", value: `${selectedAssetCount} 个` },
        { label: "最近更新", value: formatDateTime(selectedFile.latest_updated_at) },
      ]
    : [];

  return (
    <>
      <FullPageDropOverlay
        onDrop={(droppedFiles) => void handleUpload(droppedFiles)}
        disabled={uploadMutation.isPending}
      />
      <PageWrapper
        title="文件工作台"
        subtitle="统一管理学科资料、查看解析进度、预览 Markdown 结果，并在解析完成后继续构建知识文档与知识图谱。"
        badgeText="Files"
      >
        {/* ── 输入区域（始终显示） ── */}
        <div
          className={cn(PAPER_CARD, "p-2 focus-within:border-zinc-300 focus-within:shadow-[0_8px_24px_rgba(0,0,0,0.08)]")}
          onDrop={handleDrop}
          onDragOver={(event) => event.preventDefault()}
        >
          <textarea
            value={docPrompt}
            onChange={(event) => setDocPrompt(event.target.value)}
            disabled={isAnyBuildPending}
            placeholder="可选：补充一句本次知识构建的目标，例如更偏向考前冲刺、知识梳理或错题回顾。"
            className="min-h-[120px] max-h-[250px] w-full resize-none border-0 bg-transparent px-5 pb-2 pt-4 text-[15px] leading-relaxed text-slate-800 placeholder:text-slate-400 focus:outline-none"
          />

          <div className="flex flex-col gap-2 px-4 pb-2">
            <SubjectVectorNotice
              status={knowledgeDocsBuild.latestVectorStatus ?? knowledgeGraphBuild.latestVectorStatus ?? knowledgeDocState?.vector_status}
            />

            {/* 调试模式下的小标签 */}
            {debugMode && (
              <AnimatePresence>
                {files.length > 0 ? (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    className="flex flex-wrap gap-2 border-t border-slate-100 py-2"
                  >
                    {files.map((file) => {
                      const meta = getFileStatusMeta(file);
                      const isSelected = selectedFile?.uid === file.uid;
                      return (
                        <motion.div
                          key={file.uid}
                          layout
                          initial={{ opacity: 0, scale: 0.9 }}
                          animate={{ opacity: 1, scale: 1 }}
                          onClick={() => setSelectedFileUid(file.uid)}
                          className={cn(
                            "group flex cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-sm font-medium transition-colors",
                            meta.tone,
                            isSelected && "ring-2 ring-zinc-300 ring-offset-1",
                          )}
                          title={meta.label}
                        >
                          {meta.icon}
                          <span className="max-w-[180px] truncate">{file.filename}</span>
                          {file.markdown_ready ? (
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                setPreviewFileUid(file.uid);
                              }}
                              className="ml-1 p-0.5 opacity-60 transition-opacity hover:text-indigo-600 hover:opacity-100"
                              title="预览解析结果"
                            >
                              <Eye className="h-3.5 w-3.5" />
                            </button>
                          ) : null}
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              deleteMutation.mutate(file.uid);
                            }}
                            className="ml-0.5 p-0.5 opacity-60 transition-opacity hover:text-red-500 hover:opacity-100"
                            title="删除文件"
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
            )}

            <div className="flex flex-col gap-3 pt-1 md:flex-row md:items-center md:justify-between">
              <div className="flex flex-wrap items-center gap-3">
                <input
                  type="file"
                  title="选择文件"
                  multiple
                  accept={ACCEPT_TEXT}
                  className="hidden"
                  ref={fileInputRef}
                  onChange={handleFileInputChange}
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-800"
                >
                  <Paperclip className="h-4 w-4" />
                  添加文件
                </button>

                {uploadMutation.isPending ? (
                  <span className="flex items-center text-xs font-medium text-zinc-500">
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    正在上传并启动解析...
                  </span>
                ) : null}

                {uploadMutation.isError ? (
                  <span className="flex items-center text-xs font-medium text-red-500">
                    <AlertCircle className="mr-1 h-3.5 w-3.5" />
                    {getApiErrorMessage(uploadMutation.error, "上传失败")}
                  </span>
                ) : null}

                {activeBuildError ? (
                  <span className="flex items-center text-xs font-medium text-red-500">
                    <AlertCircle className="mr-1 h-3.5 w-3.5" />
                    {activeBuildError}
                  </span>
                ) : null}
              </div>

              <div className="flex items-center gap-2">
                <Button
                  size="lg"
                  onClick={knowledgeDocsBuild.submitBuild}
                  disabled={readyFiles.length === 0 || isAnyBuildPending}
                  className={cn(
                    "rounded-full px-5 shadow-sm transition-all duration-300",
                    readyFiles.length > 0 && !isAnyBuildPending
                      ? "bg-zinc-900 text-white shadow-md hover:-translate-y-0.5 hover:bg-zinc-800"
                      : "bg-zinc-100 text-zinc-400",
                  )}
                >
                  {knowledgeDocsBuild.isPending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      构建文档中...
                    </>
                  ) : (
                    <>
                      <FileText className="mr-1.5 h-4 w-4" />
                      构建知识文档
                    </>
                  )}
                </Button>

                <Button
                  size="lg"
                  onClick={knowledgeGraphBuild.submitBuild}
                  disabled={readyFiles.length === 0 || isAnyBuildPending}
                  className={cn(
                    "rounded-full px-5 shadow-sm transition-all duration-300",
                    readyFiles.length > 0 && !isAnyBuildPending
                      ? "border border-zinc-300 bg-white text-zinc-700 shadow-md hover:-translate-y-0.5 hover:bg-zinc-50"
                      : "bg-zinc-100 text-zinc-400",
                  )}
                  variant="outline"
                >
                  {knowledgeGraphBuild.isPending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      构建图谱中...
                    </>
                  ) : (
                    <>
                      <Network className="mr-1.5 h-4 w-4" />
                      构建知识图谱
                    </>
                  )}
                </Button>
              </div>
            </div>
          </div>
        </div>

        {/* ── 精简模式：美观的文件列表 ── */}
        {!debugMode && files.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="w-full"
          >
            <details className={cn("group overflow-hidden rounded-[1.25rem] border border-zinc-200 bg-white/70 shadow-sm transition-all hover:shadow-md open:bg-white", PAPER_CARD)}>
              <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-4 outline-none [&::-webkit-details-marker]:hidden border-b border-transparent group-open:border-zinc-100">
                <div className="flex flex-wrap items-center gap-3">
                  <h2 className="text-sm font-semibold text-zinc-700">已上传资料</h2>
                  <span className="rounded-full bg-zinc-100 px-2.5 py-0.5 text-xs font-medium text-zinc-600">
                    {files.length} 份
                  </span>
                  {readyFiles.length > 0 && (
                    <span className="rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-600">
                      {readyFiles.length} 份已就绪
                    </span>
                  )}
                  {files.some((f) => !f.markdown_ready && f.status !== "failed") && (
                    <span className="flex items-center gap-1.5 rounded-full bg-sky-50 px-2.5 py-0.5 text-xs font-medium text-sky-600">
                      <Loader2 className="h-3 w-3 animate-spin" />
                      解析中
                    </span>
                  )}
                </div>
                <ChevronDown className="h-4 w-4 text-zinc-400 transition-transform duration-200 group-open:rotate-180" />
              </summary>

              <div className="max-h-[420px] overflow-y-auto p-3 space-y-2 toc-scroll bg-zinc-50/50">
                <AnimatePresence>
                  {files.map((file) => (
                    <FileCard
                      key={file.uid}
                      file={file}
                      onDelete={() => deleteMutation.mutate(file.uid)}
                      isDeleting={deleteMutation.isPending}
                    />
                  ))}
                </AnimatePresence>
              </div>
            </details>
          </motion.div>
        )}

        {/* ── 精简模式：空状态 ── */}
        {!debugMode && files.length === 0 && !isLoading && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-zinc-200 bg-white/60 px-8 py-14 text-center"
          >
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-zinc-100 mb-4">
              <Paperclip className="h-7 w-7 text-zinc-400" />
            </div>
            <p className="text-sm font-medium text-zinc-600">还没有上传任何文件</p>
            <p className="mt-1 text-xs text-zinc-400">
              拖拽文件到页面任意位置，或点击上方"添加文件"开始上传
            </p>
          </motion.div>
        )}

        {/* ── 调试模式：统计卡片 ── */}
        {debugMode && (
          <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {fileStats.map((item) => (
              <div key={item.label} className={cn(PAPER_CARD, "px-4 py-4")}>
                <p className="text-xs font-medium tracking-[0.12em] text-zinc-400">{item.label}</p>
                <p className={cn("mt-2 text-2xl font-bold", item.tone)}>{item.value}</p>
              </div>
            ))}
          </div>
        )}

        {/* ── 调试模式：解析详情 + Markdown 双栏 ── */}
        {debugMode && (
          <div className="mt-8 grid gap-6 lg:grid-cols-[1.05fr,1.35fr]">
            <section className={cn(PAPER_CARD, "p-5")}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold tracking-[0.16em] text-zinc-400">解析信息</p>
                  <h2 className="mt-1 text-xl font-semibold text-zinc-900">文件解析信息</h2>
                </div>
                {selectedStatus ? (
                  <span className={cn("inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium", selectedStatus.tone)}>
                    {selectedStatus.icon}
                    {selectedStatus.label}
                  </span>
                ) : null}
              </div>

              {!selectedFile ? (
                <div className="mt-5 rounded-2xl border border-dashed border-zinc-200 bg-zinc-50 px-4 py-10 text-center text-sm text-zinc-500">
                  还没有文件。先上传资料后，这里会展示解析方法、解析时间和文件元信息。
                </div>
              ) : (
                <div className="mt-5 space-y-5">
                  <div className="rounded-2xl bg-zinc-50 px-4 py-4">
                    <p className="text-sm font-semibold text-zinc-900">{selectedFile.filename}</p>
                    <p className="mt-1 text-sm leading-6 text-zinc-600">{getParserSummary(selectedFile)}</p>
                  </div>

                  <dl className="grid gap-3 sm:grid-cols-2">
                    {parseFacts.map((item) => (
                      <div key={item.label} className="rounded-xl border border-zinc-200 px-3 py-3">
                        <dt className="text-xs font-medium tracking-[0.12em] text-zinc-400">{item.label}</dt>
                        <dd className="mt-1 text-sm font-medium text-zinc-800">{item.value}</dd>
                      </div>
                    ))}
                  </dl>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="rounded-xl border border-zinc-200 px-3 py-3">
                      <p className="text-xs font-medium tracking-[0.12em] text-zinc-400">创建时间</p>
                      <p className="mt-1 text-sm font-medium text-zinc-800">{formatDateTime(selectedFile.created_at)}</p>
                    </div>
                    <div className="rounded-xl border border-zinc-200 px-3 py-3">
                      <p className="text-xs font-medium tracking-[0.12em] text-zinc-400">流程状态</p>
                      <p className="mt-1 text-sm font-medium text-zinc-800">{selectedFile.ingest_status || selectedFile.status}</p>
                    </div>
                  </div>

                  {selectedFile.error_message ? (
                    <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                      <p className="font-medium">错误信息</p>
                      <p className="mt-1 leading-6">{selectedFile.error_message}</p>
                    </div>
                  ) : null}

                  {selectedAssetCount > 0 ? (
                    <div className="rounded-xl border border-zinc-200 px-4 py-3">
                      <p className="text-xs font-medium tracking-[0.12em] text-zinc-400">提取资源</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {selectedFile.assets?.map((asset) => (
                          <a
                            key={asset.url}
                            href={asset.url}
                            target="_blank"
                            rel="noreferrer"
                            className="rounded-full bg-zinc-100 px-2.5 py-1 text-xs font-medium text-zinc-600 transition hover:bg-zinc-200"
                          >
                            {asset.name}
                          </a>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              )}
            </section>

            <section className={cn(PAPER_CARD, "p-5")}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold tracking-[0.16em] text-zinc-400">结果预览</p>
                  <h2 className="mt-1 text-xl font-semibold text-zinc-900">解析内容预览</h2>
                </div>
                {selectedFile?.markdown_ready ? (
                  <Button variant="outline" size="sm" onClick={() => setPreviewFileUid(selectedFile.uid)}>
                    <Eye className="mr-1 h-4 w-4" />
                    放大查看
                  </Button>
                ) : null}
              </div>

              <div className="mt-5 rounded-2xl border border-zinc-200 bg-zinc-50/60 p-4">
                {selectedFile?.markdown_content ? (
                  <article className="prose prose-zinc max-w-none">
                    <MarkdownViewer
                      content={selectedFile.markdown_content}
                      assetBaseUrl={selectedFile.asset_base_url ?? undefined}
                    />
                  </article>
                ) : (
                  <div className="flex min-h-[320px] items-center justify-center rounded-xl border border-dashed border-zinc-200 bg-white px-4 py-10 text-center text-sm text-zinc-500">
                    {selectedFile
                      ? "当前文件的 Markdown 结果还没有准备好，等解析完成后这里会直接显示解析产物。"
                      : "选择文件后，这里会展示对应的 Markdown 解析内容和图片引用效果。"}
                  </div>
                )}
              </div>
            </section>
          </div>
        )}

        {/* ── 底部统计 ── */}
        <div className="mt-6 flex flex-col items-center justify-center gap-2">
          {isLoading && files.length === 0 ? (
            <div className="flex items-center gap-1.5 text-sm text-slate-400">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在加载文件...
            </div>
          ) : files.length > 0 ? (
            <div className="text-sm text-slate-400">
              共 <span className="font-semibold text-slate-700">{filesData?.total ?? files.length}</span> 份文件，
              已完成 <span className="font-semibold text-emerald-600">{filesData?.ready_count ?? readyFiles.length}</span> 份。
            </div>
          ) : null}
        </div>
      </PageWrapper>

      <Modal
        open={previewFile !== null}
        onClose={() => setPreviewFileUid(null)}
        title={previewFile?.filename ?? "文件预览"}
        className="max-w-4xl"
      >
        <div className="space-y-4">
          {previewFile ? (
            <div className="flex flex-wrap gap-2 text-xs text-slate-500">
              <span className="rounded-full bg-slate-100 px-2.5 py-1">格式：{formatFileType(previewFile)}</span>
              <span className="rounded-full bg-slate-100 px-2.5 py-1">
                状态：{previewFile.markdown_ready ? "解析结果已就绪" : previewFile.status}
              </span>
              {previewFile.parser_used ? (
                <span className="rounded-full bg-slate-100 px-2.5 py-1">解析器：{previewFile.parser_used}</span>
              ) : null}
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
              解析内容尚未准备好，请稍后再看。
            </div>
          )}
        </div>
      </Modal>

      <KnowledgeBuildResolutionModal
        open={knowledgeDocsBuild.precheckConflict !== null || knowledgeGraphBuild.precheckConflict !== null}
        conflict={knowledgeDocsBuild.precheckConflict ?? knowledgeGraphBuild.precheckConflict}
        isSubmitting={isAnyBuildPending}
        onClose={() => { knowledgeDocsBuild.closePrecheckConflict(); knowledgeGraphBuild.closePrecheckConflict(); }}
        onResolve={knowledgeDocsBuild.precheckConflict ? knowledgeDocsBuild.resolvePrecheckConflict : knowledgeGraphBuild.resolvePrecheckConflict}
      />
    </>
  );
}
