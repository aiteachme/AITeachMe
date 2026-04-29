import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  FileCode,
  FileImage,
  FileText,
  FileType,
  FolderOpen,
  Loader2,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-react";

import { apiClient, getApiErrorMessage } from "../api/client";
import { resolveFileProcessingLabel } from "../components/knowledge-docs";
import { buildUnsupportedFilesMessage, FILE_ACCEPT, partitionUploadFiles } from "../lib/fileUpload";
import { cn } from "../lib/utils";
import type { FileRecord, FilesData, FilesUploadData } from "../types/files";

interface ApiResponse<T> {
  code: number;
  data: T;
}

async function fetchLibraryFiles(): Promise<FilesData> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "GET",
    url: "/api/v1/files",
  });
  return response.data ?? {
    course_id: null,
    total: 0,
    ready_count: 0,
    processing_count: 0,
    failed_count: 0,
    items: [],
  };
}

async function uploadLibraryFiles(files: File[]): Promise<FilesUploadData> {
  const data = new FormData();
  files.forEach((file) => data.append("files", file));
  const response = await apiClient<ApiResponse<FilesUploadData>>({
    method: "POST",
    url: "/api/v1/files/upload",
    data,
    headers: { "Content-Type": "multipart/form-data" },
  });
  return response.data;
}

async function deleteLibraryFile(fileId: string): Promise<void> {
  await apiClient<ApiResponse<{ deleted_file_ids: string[] }>>({
    method: "POST",
    url: "/api/v1/files/delete",
    data: { file_id: fileId },
  });
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

function normalizeFileExt(filetype?: string | null): string {
  return String(filetype ?? "").trim().toLowerCase().replace(/^\./, "");
}

function fileIcon(file: Pick<FileRecord, "filetype">) {
  const ext = normalizeFileExt(file.filetype);
  if (ext === "pdf") return <FileText className="h-4 w-4 text-red-500" />;
  if (["png", "jpg", "jpeg", "webp"].includes(ext)) return <FileImage className="h-4 w-4 text-emerald-500" />;
  if (["md", "markdown"].includes(ext)) return <FileCode className="h-4 w-4 text-violet-500" />;
  if (["docx", "doc"].includes(ext)) return <FileText className="h-4 w-4 text-blue-500" />;
  if (["ppt", "pptx"].includes(ext)) return <FileType className="h-4 w-4 text-orange-500" />;
  return <FileText className="h-4 w-4 text-slate-400" />;
}

function statusMeta(file: FileRecord) {
  if (file.markdown_ready) {
    return {
      label: "已解析",
      icon: <CheckCircle2 className="h-4 w-4 text-emerald-500" />,
      className: "bg-emerald-50 text-emerald-700 ring-emerald-100 dark:bg-emerald-950/30 dark:text-emerald-300 dark:ring-emerald-900/60",
    };
  }
  if (file.error_message?.trim() || file.status === "failed") {
    return {
      label: "解析失败",
      icon: <AlertCircle className="h-4 w-4 text-red-500" />,
      className: "bg-red-50 text-red-700 ring-red-100 dark:bg-red-950/30 dark:text-red-300 dark:ring-red-900/60",
    };
  }
  return {
    label: resolveFileProcessingLabel(file),
    icon: <Loader2 className="h-4 w-4 animate-spin text-sky-500" />,
    className: "bg-sky-50 text-sky-700 ring-sky-100 dark:bg-sky-950/30 dark:text-sky-300 dark:ring-sky-900/60",
  };
}

export function LibraryPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const [uploadingNames, setUploadingNames] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const filesQuery = useQuery({
    queryKey: ["files-library"],
    queryFn: fetchLibraryFiles,
    refetchInterval: (query) => {
      const data = query.state.data as FilesData | undefined;
      return (data?.processing_count ?? 0) > 0 ? 2000 : false;
    },
  });

  const uploadMutation = useMutation({
    mutationFn: uploadLibraryFiles,
    onMutate: (files) => {
      setError(null);
      setUploadingNames(files.map((file) => file.name));
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["files-library"] });
    },
    onError: (err: unknown) => {
      setError(getApiErrorMessage(err, "资料上传失败"));
    },
    onSettled: () => {
      setUploadingNames([]);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteLibraryFile,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["files-library"] });
    },
    onError: (err: unknown) => {
      setError(getApiErrorMessage(err, "删除资料失败"));
    },
  });

  const files = filesQuery.data?.items ?? [];
  const hasFiles = files.length > 0;

  return (
    <div className="min-h-full pb-12">
      <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 rounded-full bg-white/85 px-3 py-1 text-xs font-medium text-slate-500 ring-1 ring-slate-200/80 backdrop-blur dark:bg-slate-800/85 dark:text-slate-400 dark:ring-slate-700/80">
            <FolderOpen className="h-3.5 w-3.5" />
            我的资料库
          </div>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100 sm:text-[32px]">我的资料库</h1>
            <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
              集中查看已上传资料、解析状态和文件信息。
            </p>
          </div>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row">
          <button
            type="button"
            onClick={() => filesQuery.refetch()}
            disabled={filesQuery.isFetching}
            className="inline-flex items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:bg-slate-800"
          >
            <RefreshCw className={cn("h-4 w-4", filesQuery.isFetching && "animate-spin")} />
            刷新
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={FILE_ACCEPT}
            className="hidden"
            onChange={(event) => {
              const selected = Array.from(event.target.files ?? []);
              if (fileInputRef.current) fileInputRef.current.value = "";
              if (selected.length > 0) {
                const { supportedFiles, unsupportedFiles } = partitionUploadFiles(selected);
                setError(unsupportedFiles.length ? buildUnsupportedFilesMessage(unsupportedFiles) : null);
                if (supportedFiles.length > 0) {
                  uploadMutation.mutate(supportedFiles);
                }
              }
            }}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadMutation.isPending}
            className="inline-flex items-center justify-center gap-2 rounded-2xl bg-slate-900 px-4 py-3 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
          >
            {uploadMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            上传资料
          </button>
        </div>
      </div>

      <div className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-4">
        {[
          { label: "全部资料", value: filesQuery.data?.total ?? files.length },
          { label: "已解析", value: filesQuery.data?.ready_count ?? 0 },
          { label: "解析中", value: filesQuery.data?.processing_count ?? 0 },
          { label: "失败", value: filesQuery.data?.failed_count ?? 0 },
        ].map((item) => (
          <div key={item.label} className="rounded-2xl border border-slate-200/80 bg-white/80 px-4 py-3 shadow-sm dark:border-slate-800/80 dark:bg-slate-900/80">
            <div className="text-xs font-medium text-slate-500 dark:text-slate-400">{item.label}</div>
            <div className="mt-1 text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">{item.value}</div>
          </div>
        ))}
      </div>

      {error ? (
        <div className="mt-5 rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm font-medium text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
          {error}
        </div>
      ) : null}

      {uploadingNames.length > 0 ? (
        <div className="mt-5 rounded-2xl border border-sky-100 bg-sky-50 px-4 py-3 dark:border-sky-900/60 dark:bg-sky-950/30">
          <div className="flex items-center gap-2 text-sm font-medium text-sky-700 dark:text-sky-300">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在上传 {uploadingNames.length} 份资料
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {uploadingNames.map((name) => (
              <span key={name} className="max-w-full truncate rounded-full bg-white/80 px-3 py-1 text-xs text-sky-700 ring-1 ring-sky-100 dark:bg-sky-950/50 dark:text-sky-300 dark:ring-sky-900/60">
                {name}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {filesQuery.isLoading ? (
        <div className="mt-12 flex min-h-[180px] items-center justify-center">
          <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在加载资料库...
          </div>
        </div>
      ) : null}

      {!filesQuery.isLoading && !hasFiles ? (
        <div className="mt-14 flex min-h-[180px] flex-col items-center justify-center px-6 text-center">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-slate-100/80 text-slate-500 dark:bg-slate-800/80 dark:text-slate-400">
            <FolderOpen className="h-5 w-5" />
          </div>
          <h2 className="mt-4 text-lg font-semibold text-slate-900 dark:text-slate-100">还没有资料</h2>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="mt-5 inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
          >
            <Upload className="h-4 w-4" />
            上传资料
          </button>
        </div>
      ) : null}

      {!filesQuery.isLoading && hasFiles ? (
        <div className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="hidden grid-cols-[minmax(0,1.5fr)_120px_150px_110px_56px] gap-4 border-b border-slate-100 bg-slate-50 px-4 py-3 text-xs font-medium text-slate-500 dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-400 md:grid">
            <div>文件</div>
            <div>大小</div>
            <div>状态</div>
            <div>更新时间</div>
            <div />
          </div>

          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            {files.map((file) => {
              const meta = statusMeta(file);
              return (
                <div key={file.id} className="grid gap-3 px-4 py-4 md:grid-cols-[minmax(0,1.5fr)_120px_150px_110px_56px] md:items-center md:gap-4">
                  <div className="flex min-w-0 items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-100 dark:bg-slate-800">
                      {fileIcon(file)}
                    </div>
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">{file.filename}</div>
                      <div className="mt-1 flex items-center gap-2 text-xs text-slate-400 dark:text-slate-500">
                        <span>{normalizeFileExt(file.filetype).toUpperCase() || "FILE"}</span>
                        {file.estimated_pages ? <span>{file.estimated_pages} 页</span> : null}
                        {file.image_count ? <span>{file.image_count} 图</span> : null}
                      </div>
                    </div>
                  </div>

                  <div className="text-sm text-slate-500 dark:text-slate-400">{formatFileSize(file.file_size_bytes)}</div>

                  <div>
                    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1", meta.className)} title={resolveFileProcessingLabel(file)}>
                      {meta.icon}
                      {meta.label}
                    </span>
                    {file.error_message ? <div className="mt-1 line-clamp-2 text-xs text-red-500">{file.error_message}</div> : null}
                  </div>

                  <div className="text-xs text-slate-400 dark:text-slate-500">
                    {new Date(file.latest_updated_at || file.created_at).toLocaleDateString()}
                  </div>

                  <div className="flex justify-end">
                    <button
                      type="button"
                      onClick={() => deleteMutation.mutate(file.id)}
                      disabled={deleteMutation.isPending}
                      className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 transition hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-red-950/30 dark:hover:text-red-300"
                      title="删除资料"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}
