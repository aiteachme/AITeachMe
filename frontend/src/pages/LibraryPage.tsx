import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  Database,
  FileCode,
  FileImage,
  FileText,
  FileType,
  FolderOpen,
  HardDrive,
  Loader2,
  Search,
  RefreshCw,
  Trash2,
  Upload,
  X,
} from "lucide-react";

import { apiClient, getApiErrorMessage } from "../api/client";
import { resolveFileProcessingLabel } from "../components/knowledge-docs";
import { useToast } from "../components/ui/Toast";
import {
  buildImageParserUnavailableMessage,
  buildUnsupportedFilesMessage,
  FILE_ACCEPT,
  IMAGE_UPLOAD_PARSER_UNAVAILABLE_TITLE,
  partitionUploadFilesForRuntime,
} from "../lib/fileUpload";
import { cn } from "../lib/utils";
import type { FileRecord, FilesData, FilesUploadData } from "../types/files";

interface ApiResponse<T> {
  code: number;
  data: T;
}

type FileStatusFilter = "all" | "ready" | "processing" | "failed";
type FileStatusKind = Exclude<FileStatusFilter, "all">;
type FileSortKey = "updated_desc" | "name_asc" | "size_desc";

interface SelectOption<T extends string> {
  value: T;
  label: string;
}

const FILE_STATUS_FILTER_OPTIONS: Array<SelectOption<FileStatusFilter>> = [
  { value: "all", label: "全部状态" },
  { value: "ready", label: "已解析" },
  { value: "processing", label: "解析中" },
  { value: "failed", label: "失败" },
];

const FILE_SORT_OPTIONS: Array<SelectOption<FileSortKey>> = [
  { value: "updated_desc", label: "最近更新" },
  { value: "name_asc", label: "文件名 A-Z" },
  { value: "size_desc", label: "文件大小" },
];

const fileNameCollator = new Intl.Collator("zh-Hans-CN", {
  numeric: true,
  sensitivity: "base",
});

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
  if (["md", "markdown"].includes(ext)) return <FileCode className="h-4 w-4 text-indigo-500" />;
  if (["docx", "doc"].includes(ext)) return <FileText className="h-4 w-4 text-indigo-500" />;
  if (["ppt", "pptx"].includes(ext)) return <FileType className="h-4 w-4 text-orange-500" />;
  return <FileText className="h-4 w-4 text-slate-400" />;
}

function getFileStatusKind(file: FileRecord): FileStatusKind {
  if (file.markdown_ready) {
    return "ready";
  }
  if (file.error_message?.trim() || file.status === "failed") {
    return "failed";
  }
  return "processing";
}

function getFileUpdatedTime(file: FileRecord): number {
  const value = Date.parse(file.latest_updated_at || file.created_at || "");
  return Number.isFinite(value) ? value : 0;
}

function statusMeta(file: FileRecord) {
  const status = getFileStatusKind(file);
  if (status === "ready") {
    return {
      label: "已解析",
      icon: <CheckCircle2 className="h-4 w-4 text-emerald-500" />,
      className: "bg-emerald-50 text-emerald-700 ring-emerald-100 dark:bg-emerald-950/30 dark:text-emerald-300 dark:ring-emerald-900/60",
    };
  }
  if (status === "failed") {
    return {
      label: "解析失败",
      icon: <AlertCircle className="h-4 w-4 text-red-500" />,
      className: "bg-red-50 text-red-700 ring-red-100 dark:bg-red-950/30 dark:text-red-300 dark:ring-red-900/60",
    };
  }
  return {
    label: resolveFileProcessingLabel(file),
    icon: <Loader2 className="h-4 w-4 animate-spin text-indigo-500" />,
    className: "bg-indigo-50 text-indigo-700 ring-indigo-100 dark:bg-indigo-950/30 dark:text-indigo-300 dark:ring-indigo-900/60",
  };
}

export function LibraryPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [uploadingNames, setUploadingNames] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<FileStatusFilter>("all");
  const [sortKey, setSortKey] = useState<FileSortKey>("updated_desc");

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
  const statusCounts = useMemo<Record<FileStatusFilter, number>>(() => {
    const counts: Record<FileStatusFilter, number> = {
      all: files.length,
      ready: 0,
      processing: 0,
      failed: 0,
    };

    files.forEach((file) => {
      counts[getFileStatusKind(file)] += 1;
    });

    return counts;
  }, [files]);
  const visibleFiles = useMemo(() => {
    const keyword = searchQuery.trim().toLowerCase();
    const next = files.filter((file) => {
      if (statusFilter !== "all" && getFileStatusKind(file) !== statusFilter) {
        return false;
      }
      if (!keyword) {
        return true;
      }

      const meta = statusMeta(file);
      const searchable = [
        file.filename,
        normalizeFileExt(file.filetype),
        meta.label,
        file.error_message ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return searchable.includes(keyword);
    });

    return next.sort((a, b) => {
      if (sortKey === "name_asc") {
        return fileNameCollator.compare(a.filename, b.filename);
      }
      if (sortKey === "size_desc") {
        return (b.file_size_bytes ?? 0) - (a.file_size_bytes ?? 0);
      }
      return getFileUpdatedTime(b) - getFileUpdatedTime(a);
    });
  }, [files, searchQuery, sortKey, statusFilter]);
  const hasVisibleFiles = visibleFiles.length > 0;
  const hasActiveFilters = searchQuery.trim().length > 0 || statusFilter !== "all";
  const visibleCountLabel = visibleFiles.length === files.length ? `${files.length} 份` : `${visibleFiles.length}/${files.length} 份`;
  const libraryStats = [
    {
      label: "全部资料",
      value: filesQuery.data?.total ?? files.length,
      icon: <Database className="h-4 w-4" />,
      tone: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
    },
    {
      label: "已解析",
      value: filesQuery.data?.ready_count ?? 0,
      icon: <CheckCircle2 className="h-4 w-4" />,
      tone: "bg-emerald-50 text-emerald-600 dark:bg-emerald-950/30 dark:text-emerald-300",
    },
    {
      label: "解析中",
      value: filesQuery.data?.processing_count ?? 0,
      icon: <Clock3 className="h-4 w-4" />,
      tone: "bg-indigo-50 text-indigo-600 dark:bg-indigo-950/30 dark:text-indigo-300",
    },
    {
      label: "失败",
      value: filesQuery.data?.failed_count ?? 0,
      icon: <AlertCircle className="h-4 w-4" />,
      tone: "bg-red-50 text-red-600 dark:bg-red-950/30 dark:text-red-300",
    },
  ];

  return (
    <div className="min-h-full pb-24 sm:pb-12">
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
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:bg-slate-800"
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
            onChange={async (event) => {
              const selected = Array.from(event.target.files ?? []);
              if (fileInputRef.current) fileInputRef.current.value = "";
              if (selected.length > 0) {
                const { supportedFiles, unsupportedFiles, imageParserUnavailableFiles } =
                  await partitionUploadFilesForRuntime(selected);
                const unsupportedMessage = unsupportedFiles.length
                  ? buildUnsupportedFilesMessage(unsupportedFiles)
                  : null;
                const imageParserUnavailableMessage = imageParserUnavailableFiles.length
                  ? buildImageParserUnavailableMessage(imageParserUnavailableFiles)
                  : null;
                setError(unsupportedMessage ?? imageParserUnavailableMessage);
                if (unsupportedMessage) {
                  toast({
                    title: "文件类型暂不支持",
                    description: unsupportedMessage,
                    variant: "error",
                  });
                }
                if (imageParserUnavailableMessage) {
                  toast({
                    title: IMAGE_UPLOAD_PARSER_UNAVAILABLE_TITLE,
                    description: imageParserUnavailableMessage,
                    variant: "error",
                  });
                }
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
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-4 py-3 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
          >
            {uploadMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            上传资料
          </button>
        </div>
      </div>

      <div className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {libraryStats.map((item) => (
          <div key={item.label} className="rounded-xl border border-slate-200/80 bg-white/90 px-4 py-4 shadow-sm dark:border-slate-800/80 dark:bg-slate-900/80">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-xs font-medium text-slate-500 dark:text-slate-400">{item.label}</div>
                <div className="mt-1 text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">{item.value}</div>
              </div>
              <div className={cn("flex h-9 w-9 items-center justify-center rounded-lg", item.tone)}>{item.icon}</div>
            </div>
          </div>
        ))}
      </div>

      {error ? (
        <div className="mt-5 rounded-lg border border-red-100 bg-red-50 px-4 py-3 text-sm font-medium text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
          {error}
        </div>
      ) : null}

      {uploadingNames.length > 0 ? (
        <div className="mt-5 rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-3 dark:border-indigo-900/60 dark:bg-indigo-950/30">
          <div className="flex items-center gap-2 text-sm font-medium text-indigo-700 dark:text-indigo-300">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在上传 {uploadingNames.length} 份资料
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {uploadingNames.map((name) => (
              <span key={name} className="max-w-full truncate rounded-full bg-white/80 px-3 py-1 text-xs text-indigo-700 ring-1 ring-indigo-100 dark:bg-indigo-950/50 dark:text-indigo-300 dark:ring-indigo-900/60">
                {name}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {filesQuery.isLoading ? (
        <div className="mt-10 flex min-h-[180px] items-center justify-center pb-12 sm:mt-12 sm:pb-0">
          <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在加载资料库...
          </div>
        </div>
      ) : null}

      {!filesQuery.isLoading && !hasFiles ? (
        <div className="mt-10 flex min-h-[180px] flex-col items-center justify-center px-6 pb-12 text-center sm:mt-14 sm:pb-0">
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
        <div className="mt-6 rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="rounded-t-xl border-b border-slate-100 bg-white px-4 py-4 dark:border-slate-800 dark:bg-slate-900">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">文件列表</h2>
                <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                  搜索、筛选和排序资料，解析完成后可直接用于课程构建和提问。
                </p>
              </div>
              <div className="inline-flex w-fit shrink-0 items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs font-medium text-slate-500 dark:bg-slate-800/70 dark:text-slate-400">
                <HardDrive className="h-3.5 w-3.5" />
                {visibleCountLabel}
              </div>
            </div>

            <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
              <label className="relative block min-w-0">
                <span className="sr-only">搜索资料</span>
                <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  type="search"
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder="搜索文件名、类型或状态"
                  className="h-11 w-full rounded-xl border border-slate-200 bg-slate-50/60 pl-10 pr-10 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-slate-300 focus:bg-white focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-slate-600 dark:focus:bg-slate-900 dark:focus:ring-slate-700/60"
                />
                {searchQuery ? (
                  <button
                    type="button"
                    onClick={() => setSearchQuery("")}
                    className="absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-200/70 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                    aria-label="清空搜索"
                  >
                    <X className="h-4 w-4" />
                  </button>
                ) : null}
              </label>

              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <label className="block min-w-0">
                  <span className="sr-only">状态筛选</span>
                  <select
                    value={statusFilter}
                    onChange={(event) => setStatusFilter(event.target.value as FileStatusFilter)}
                    className="h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 outline-none transition hover:border-slate-300 focus:border-slate-300 focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:focus:ring-slate-700/60"
                  >
                    {FILE_STATUS_FILTER_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label} ({statusCounts[option.value]})
                      </option>
                    ))}
                  </select>
                </label>

                <label className="block min-w-0">
                  <span className="sr-only">排序方式</span>
                  <select
                    value={sortKey}
                    onChange={(event) => setSortKey(event.target.value as FileSortKey)}
                    className="h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 outline-none transition hover:border-slate-300 focus:border-slate-300 focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:focus:ring-slate-700/60"
                  >
                    {FILE_SORT_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
          </div>

          {hasVisibleFiles ? (
            <div className="hidden grid-cols-[minmax(0,1.7fr)_120px_170px_120px_48px] gap-4 border-b border-slate-100 bg-slate-50/80 px-4 py-3 text-xs font-medium text-slate-500 dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-400 md:grid">
              <div>文件</div>
              <div>大小</div>
              <div>状态</div>
              <div>更新时间</div>
              <div />
            </div>
          ) : null}

          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            {visibleFiles.map((file) => {
              const meta = statusMeta(file);
              return (
                <div key={file.id} className="atm-deferred-row group grid gap-3 px-4 py-4 transition hover:bg-slate-50/70 dark:hover:bg-slate-800/35 md:grid-cols-[minmax(0,1.7fr)_120px_170px_120px_48px] md:items-center md:gap-4">
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

                  <div className="flex items-center justify-between gap-3 text-sm text-slate-500 dark:text-slate-400 md:block">
                    <span className="text-xs font-medium text-slate-400 md:hidden">大小</span>
                    <span>{formatFileSize(file.file_size_bytes)}</span>
                  </div>

                  <div className="flex items-start justify-between gap-3 md:block">
                    <span className="pt-1 text-xs font-medium text-slate-400 md:hidden">状态</span>
                    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1", meta.className)} title={resolveFileProcessingLabel(file)}>
                      {meta.icon}
                      {meta.label}
                    </span>
                    {file.error_message ? <div className="mt-1 line-clamp-2 text-xs text-red-500">{file.error_message}</div> : null}
                  </div>

                  <div className="flex items-center justify-between gap-3 text-xs text-slate-400 dark:text-slate-500 md:block">
                    <span className="font-medium md:hidden">更新</span>
                    <span>{new Date(file.latest_updated_at || file.created_at).toLocaleDateString()}</span>
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

          {!hasVisibleFiles ? (
            <div className="flex min-h-[220px] flex-col items-center justify-center px-6 py-12 text-center">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-slate-100/80 text-slate-500 dark:bg-slate-800/80 dark:text-slate-400">
                <Search className="h-5 w-5" />
              </div>
              <h2 className="mt-4 text-base font-semibold text-slate-900 dark:text-slate-100">没有匹配的资料</h2>
              <p className="mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">
                换个关键词，或切回全部状态查看完整资料库。
              </p>
              {hasActiveFilters ? (
                <button
                  type="button"
                  onClick={() => {
                    setSearchQuery("");
                    setStatusFilter("all");
                  }}
                  className="mt-5 inline-flex h-10 items-center justify-center rounded-xl border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:bg-slate-800"
                >
                  清除筛选
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
