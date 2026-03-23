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
  ArrowRight,
  CheckCircle2,
  Eye,
  Loader2,
  Paperclip,
  Sparkles,
  X,
} from "lucide-react";

import { apiClient, getApiErrorMessage } from "../api/client";
import { Button } from "../components/ui/Button";
import { MarkdownViewer } from "../components/ui/MarkdownViewer";
import { Modal } from "../components/ui/Modal";
import { cn } from "../lib/utils";
import type { FileRecord, FilesData, FilesUploadData } from "../types/files";

interface ApiResponse<T> {
  code: number;
  data: T;
}

interface KnowledgeBuildData {
  accepted_file_uids: string[];
  prompt: string | null;
  ready_file_count: number;
  requested_at: string;
}

const ACTIVE_FILE_STATUSES = new Set(["pending", "processing", "running"]);
const ACCEPT_TEXT = ".pdf,.docx,.doc,.ppt,.pptx,.md,.markdown,.txt,.png,.jpg,.jpeg,.webp";
const PAPER_CARD = "rounded-2xl border border-slate-200 bg-white shadow-sm transition-all";

async function fetchFiles(subject: string): Promise<FilesData> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "GET",
    url: `/api/v1/subjects/${subject}/files`,
  });
  return response.data;
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
    headers: { "Content-Type": "multipart/form-data" },
  });
  return response.data;
}

async function deleteFile(subject: string, fileUid: string): Promise<void> {
  await apiClient<ApiResponse<{ deleted_file_uids: string[] }>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/files/delete`,
    data: { file_uid: fileUid },
  });
}

async function triggerKnowledgeBuild(subject: string, prompt?: string): Promise<KnowledgeBuildData> {
  const response = await apiClient<ApiResponse<KnowledgeBuildData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/build`,
    data: { prompt },
  });
  return response.data;
}

function getFileStatusMeta(file: FileRecord) {
  if (file.markdown_ready) {
    return {
      label: "已完成",
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
      tone: "text-slate-700 bg-slate-50 border-slate-200",
      icon: <Loader2 className="h-4 w-4 animate-spin text-slate-500" />,
    };
  }

  return {
    label: "等待处理",
    tone: "text-amber-600 bg-amber-50 border-amber-200",
    icon: <Loader2 className="h-4 w-4 animate-spin text-amber-500" />,
  };
}

function formatFileType(file: FileRecord): string {
  return file.filetype ? file.filetype.toUpperCase() : "未知格式";
}

function formatFileSize(bytes?: number | null): string {
  if (bytes == null || !Number.isFinite(bytes)) {
    return "未知";
  }

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
  if (!value) {
    return "未记录";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatLanguage(language?: string | null): string {
  if (!language) {
    return "自动识别中";
  }

  if (language === "zh") {
    return "中文";
  }

  if (language === "en") {
    return "英文";
  }

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
    <div className="flex-1 w-full flex flex-col items-center px-4 pt-16 md:pt-20 pb-16 relative overflow-x-hidden min-h-[100dvh] bg-slate-50/50">
      <div className="absolute inset-0 overflow-hidden pointer-events-none block">
        <div
          className="absolute -top-[10%] -left-[10%] h-[500px] w-[500px] animate-pulse rounded-full bg-blue-500/10 blur-3xl"
          style={{ animationDuration: "7s" }}
        />
        <div
          className="absolute bottom-0 -right-[5%] h-[600px] w-[600px] animate-pulse rounded-full bg-slate-800/5 blur-3xl"
          style={{ animationDuration: "11s" }}
        />
      </div>
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
        className="relative z-10 w-full max-w-5xl space-y-6"
      >
        <div className="mb-10 text-center">
          {badgeText ? (
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700 shadow-sm">
              <Sparkles className="h-3.5 w-3.5" />
              {badgeText}
            </div>
          ) : null}
          <h1 className="mb-3 text-3xl font-extrabold tracking-tight text-slate-900 md:text-4xl">{title}</h1>
          {subtitle ? <p className="mx-auto max-w-3xl text-sm text-slate-500 md:text-base">{subtitle}</p> : null}
        </div>
        {children}
      </motion.div>
    </div>
  );
}

export function FilesPage() {
  const { subjectId = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const state = location.state as { initialFiles?: File[]; initialPrompt?: string } | null;

  const [docPrompt, setDocPrompt] = useState(state?.initialPrompt ?? "");
  const [selectedFileUid, setSelectedFileUid] = useState<string | null>(null);
  const [previewFileUid, setPreviewFileUid] = useState<string | null>(null);
  const [hasAutoUploaded, setHasAutoUploaded] = useState(false);

  const { data: filesData, isLoading } = useQuery({
    queryKey: ["files", subjectId],
    queryFn: () => fetchFiles(subjectId),
    enabled: Boolean(subjectId),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      return items.some((item) => !item.markdown_ready && item.status !== "failed") ? 2500 : false;
    },
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

  const buildMutation = useMutation({
    mutationFn: () => triggerKnowledgeBuild(subjectId, docPrompt.trim() || undefined),
    onSuccess: (data) => {
      navigate(`/subject/${subjectId}/knowledge-docs?requested_at=${encodeURIComponent(data.requested_at)}`);
    },
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
  }, [handleUpload, hasAutoUploaded, location.pathname, navigate, state, subjectId]);

  useEffect(() => {
    if (!files.length) {
      if (selectedFileUid !== null) {
        setSelectedFileUid(null);
      }
      if (previewFileUid !== null) {
        setPreviewFileUid(null);
      }
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
      <PageWrapper
        title="文件工作台"
        subtitle="统一管理学科资料、查看解析进度、预览 Markdown 结果，并在解析完成后继续构建知识文档与知识图谱。"
        badgeText="Files"
      >
        <div
          className={cn(PAPER_CARD, "p-2 focus-within:border-slate-300 focus-within:shadow-md")}
          onDrop={handleDrop}
          onDragOver={(event) => event.preventDefault()}
        >
          <textarea
            value={docPrompt}
            onChange={(event) => setDocPrompt(event.target.value)}
            disabled={buildMutation.isPending}
            placeholder="可选：补充一句本次知识构建的目标，例如更偏向考前冲刺、知识梳理或错题回顾。"
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
                          isSelected && "ring-2 ring-slate-300 ring-offset-1",
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
                  className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800"
                >
                  <Paperclip className="h-4 w-4" />
                  添加文件
                </button>

                {uploadMutation.isPending ? (
                  <span className="flex items-center text-xs font-medium text-slate-500">
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

                {buildMutation.isError ? (
                  <span className="flex items-center text-xs font-medium text-red-500">
                    <AlertCircle className="mr-1 h-3.5 w-3.5" />
                    {getApiErrorMessage(buildMutation.error, "知识构建失败")}
                  </span>
                ) : null}
              </div>

              <Button
                size="lg"
                onClick={() => buildMutation.mutate()}
                disabled={readyFiles.length === 0 || buildMutation.isPending}
                className={cn(
                  "rounded-full px-6 shadow-sm transition-all duration-300",
                  readyFiles.length > 0 && !buildMutation.isPending
                    ? "bg-slate-900 text-white shadow-md hover:-translate-y-0.5 hover:bg-slate-800"
                    : "bg-slate-100 text-slate-400",
                )}
              >
                {buildMutation.isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    正在提交构建...
                  </>
                ) : (
                  <>
                    构建知识产物
                    <ArrowRight className="ml-1.5 h-4 w-4" />
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>

        <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {fileStats.map((item) => (
            <div key={item.label} className={cn(PAPER_CARD, "px-4 py-4")}>
              <p className="text-xs font-medium tracking-[0.12em] text-slate-400">{item.label}</p>
              <p className={cn("mt-2 text-2xl font-bold", item.tone)}>{item.value}</p>
            </div>
          ))}
        </div>

        <div className="mt-8 grid gap-6 lg:grid-cols-[1.05fr,1.35fr]">
          <section className={cn(PAPER_CARD, "p-5")}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold tracking-[0.16em] text-slate-400">解析信息</p>
                <h2 className="mt-1 text-xl font-semibold text-slate-900">文件解析信息</h2>
              </div>
              {selectedStatus ? (
                <span className={cn("inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium", selectedStatus.tone)}>
                  {selectedStatus.icon}
                  {selectedStatus.label}
                </span>
              ) : null}
            </div>

            {!selectedFile ? (
              <div className="mt-5 rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-10 text-center text-sm text-slate-500">
                还没有文件。先上传资料后，这里会展示解析方法、解析时间和文件元信息。
              </div>
            ) : (
              <div className="mt-5 space-y-5">
                <div className="rounded-2xl bg-slate-50 px-4 py-4">
                  <p className="text-sm font-semibold text-slate-900">{selectedFile.filename}</p>
                  <p className="mt-1 text-sm leading-6 text-slate-600">{getParserSummary(selectedFile)}</p>
                </div>

                <dl className="grid gap-3 sm:grid-cols-2">
                  {parseFacts.map((item) => (
                    <div key={item.label} className="rounded-xl border border-slate-200 px-3 py-3">
                      <dt className="text-xs font-medium tracking-[0.12em] text-slate-400">{item.label}</dt>
                      <dd className="mt-1 text-sm font-medium text-slate-800">{item.value}</dd>
                    </div>
                  ))}
                </dl>

                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-xl border border-slate-200 px-3 py-3">
                    <p className="text-xs font-medium tracking-[0.12em] text-slate-400">创建时间</p>
                    <p className="mt-1 text-sm font-medium text-slate-800">{formatDateTime(selectedFile.created_at)}</p>
                  </div>
                  <div className="rounded-xl border border-slate-200 px-3 py-3">
                    <p className="text-xs font-medium tracking-[0.12em] text-slate-400">流程状态</p>
                    <p className="mt-1 text-sm font-medium text-slate-800">{selectedFile.ingest_status || selectedFile.status}</p>
                  </div>
                </div>

                {selectedFile.error_message ? (
                  <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                    <p className="font-medium">错误信息</p>
                    <p className="mt-1 leading-6">{selectedFile.error_message}</p>
                  </div>
                ) : null}

                {selectedAssetCount > 0 ? (
                  <div className="rounded-xl border border-slate-200 px-4 py-3">
                    <p className="text-xs font-medium tracking-[0.12em] text-slate-400">提取资源</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {selectedFile.assets?.map((asset) => (
                        <a
                          key={asset.url}
                          href={asset.url}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-200"
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
                <p className="text-xs font-semibold tracking-[0.16em] text-slate-400">结果预览</p>
                <h2 className="mt-1 text-xl font-semibold text-slate-900">解析内容预览</h2>
              </div>
              {selectedFile?.markdown_ready ? (
                <Button variant="outline" size="sm" onClick={() => setPreviewFileUid(selectedFile.uid)}>
                  <Eye className="mr-1 h-4 w-4" />
                  放大查看
                </Button>
              ) : null}
            </div>

            <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50/60 p-4">
              {selectedFile?.markdown_content ? (
                <article className="prose prose-slate max-w-none">
                  <MarkdownViewer
                    content={selectedFile.markdown_content}
                    assetBaseUrl={selectedFile.asset_base_url ?? undefined}
                  />
                </article>
              ) : (
                <div className="flex min-h-[320px] items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white px-4 py-10 text-center text-sm text-slate-500">
                  {selectedFile
                    ? "当前文件的 Markdown 结果还没有准备好，等解析完成后这里会直接显示解析产物。"
                    : "选择文件后，这里会展示对应的 Markdown 解析内容和图片引用效果。"}
                </div>
              )}
            </div>
          </section>
        </div>

        <div className="mt-6 flex flex-col items-center justify-center gap-2">
          {isLoading && files.length === 0 ? (
            <div className="flex items-center gap-1.5 text-sm text-slate-400">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在加载文件...
            </div>
          ) : files.length === 0 ? (
            <div className="flex items-center gap-1.5 text-sm text-slate-400">
              暂无文件。请拖拽文件到上方区域，或点击“添加文件”开始上传。
            </div>
          ) : (
            <div className="text-sm text-slate-400">
              共 <span className="font-semibold text-slate-700">{filesData?.total ?? files.length}</span> 份文件，
              已完成 <span className="font-semibold text-emerald-600">{filesData?.ready_count ?? readyFiles.length}</span> 份。
            </div>
          )}
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
    </>
  );
}
