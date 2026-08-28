import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ClipboardEvent,
  type ReactNode,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  AlertCircle,
  Check,
  CheckCircle2,
  FileCode,
  FileImage,
  FileText,
  FileType,
  FileUp,
  FolderOpen,
  Loader2,
  RefreshCw,
  Search,
  X,
} from "lucide-react";

import { apiClient, getApiErrorMessage } from "../../../api/client";
import {
  buildAlreadyParsedUploadNotice,
  buildUnsupportedFilesMessage,
  buildImageParserUnavailableMessage,
  extractPasteFiles,
  FILE_ACCEPT,
  IMAGE_UPLOAD_PARSER_UNAVAILABLE_TITLE,
  partitionUploadFilesForRuntime,
} from "../../../lib/fileUpload";
import { cn } from "../../../lib/utils";
import type { FileRecord, FilesData, FilesUploadData } from "../../../types/files";
import { FileDropOverlay, useFileDropZone } from "../../ui/FileDropZone";
import { resolveFileProcessingLabel } from "../../knowledge-docs/utils";
import { useToast } from "../../ui/Toast";

interface ApiResponse<T> {
  code: number;
  data: T;
}

interface AiConversationDraftFileAttachmentsProps {
  fileIds: string[];
  files: FileRecord[];
  onChange: (fileIds: string[], files: FileRecord[]) => void;
  onUploadingChange: (isUploading: boolean) => void;
  disabled?: boolean;
  children: (state: {
    attachmentContent: ReactNode;
    toolbarActions: ReactNode;
    modalContent: ReactNode;
    hasFiles: boolean;
    isUploading: boolean;
    onPaste: (event: ClipboardEvent<HTMLTextAreaElement>) => void;
    onFilesDrop: (files: File[]) => void;
    onOpenLibraryPicker: () => void;
  }) => ReactNode;
}

const DRAFT_FILES_QUERY_KEY = (fileIds: string[]) => ["conversation-draft-files", fileIds.join(",")] as const;

async function uploadDraftFiles(files: File[]): Promise<FilesUploadData> {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }

  const response = await apiClient<ApiResponse<FilesUploadData>>({
    method: "POST",
    url: "/api/v1/files/upload",
    data: formData,
    headers: { "Content-Type": "multipart/form-data" },
  });
  return response.data;
}

async function fetchFiles(fileIds: string[]): Promise<FilesData> {
  const query = fileIds.map((fileId) => `file_ids=${encodeURIComponent(fileId)}`).join("&");
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "GET",
    url: `/api/v1/files${query ? `?${query}` : ""}`,
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

function uniqueStrings(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)));
}

function normalizeFileExt(filetype?: string | null): string {
  return String(filetype ?? "").trim().toLowerCase().replace(/^\./, "");
}

function draftFileIcon(file: Pick<FileRecord, "filetype">) {
  const ext = normalizeFileExt(file.filetype);
  if (ext === "pdf") return <FileText className="h-3.5 w-3.5 text-red-400" />;
  if (["png", "jpg", "jpeg", "webp"].includes(ext)) return <FileImage className="h-3.5 w-3.5 text-emerald-400" />;
  if (["md", "markdown"].includes(ext)) return <FileCode className="h-3.5 w-3.5 text-indigo-400" />;
  if (["docx", "doc"].includes(ext)) return <FileText className="h-3.5 w-3.5 text-indigo-400" />;
  if (["ppt", "pptx"].includes(ext)) return <FileType className="h-3.5 w-3.5 text-orange-400" />;
  return <FileUp className="h-3.5 w-3.5 text-zinc-400" />;
}

function draftFileStatusMeta(file: Pick<FileRecord, "markdown_ready" | "error_message" | "status">) {
  if (file.markdown_ready) {
    return {
      label: "已就绪",
      icon: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />,
      tone: "text-emerald-600",
    };
  }
  if (file.error_message?.trim() || file.status === "failed") {
    return {
      label: "处理失败",
      icon: <AlertCircle className="h-3.5 w-3.5 text-red-500" />,
      tone: "text-red-600",
    };
  }
  return {
    label: "解析中",
    icon: <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-500" />,
    tone: "text-indigo-600",
  };
}

function LibraryPickerModal({
  selectedFileIds,
  onClose,
  onConfirm,
  onUploadLocalFiles,
  onDropFiles,
  isUploading,
  disabled = false,
}: {
  selectedFileIds: string[];
  onClose: () => void;
  onConfirm: (fileIds: string[], files: FileRecord[]) => void;
  onUploadLocalFiles: () => void;
  onDropFiles: (files: File[]) => void;
  isUploading: boolean;
  disabled?: boolean;
}) {
  const [searchTerm, setSearchTerm] = useState("");
  const [selected, setSelected] = useState<Set<string>>(() => new Set(selectedFileIds));
  const { isDragActive, dropZoneHandlers } = useFileDropZone<HTMLDivElement>({
    disabled: disabled || isUploading,
    onDropFiles,
  });

  useEffect(() => {
    setSelected(new Set(selectedFileIds));
  }, [selectedFileIds]);

  const filesQuery = useQuery({
    queryKey: ["files-library"],
    queryFn: () => fetchFiles([]),
    refetchInterval: (query) => {
      const data = query.state.data as FilesData | undefined;
      return (data?.processing_count ?? 0) > 0 ? 2000 : false;
    },
  });

  const files = filesQuery.data?.items ?? [];
  const normalizedSearchTerm = searchTerm.trim().toLowerCase();
  const visibleFiles = useMemo(() => {
    if (!normalizedSearchTerm) {
      return files;
    }
    return files.filter((file) => {
      const ext = normalizeFileExt(file.filetype);
      return file.filename.toLowerCase().includes(normalizedSearchTerm) || ext.includes(normalizedSearchTerm);
    });
  }, [files, normalizedSearchTerm]);

  const selectedFiles = useMemo(
    () => files.filter((file) => selected.has(file.id)),
    [files, selected],
  );
  const selectedCount = selected.size;

  const toggleFileId = (fileId: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(fileId)) {
        next.delete(fileId);
      } else {
        next.add(fileId);
      }
      return next;
    });
  };

  const confirmSelection = () => {
    onConfirm(Array.from(selected), selectedFiles);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center px-4">
      <div className="absolute inset-0 modal-backdrop" onClick={onClose} />
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95 }}
        role="dialog"
        aria-modal="true"
        aria-label="从资料库选择"
        {...dropZoneHandlers}
        className={cn(
          "relative z-10 flex max-h-[82vh] w-[640px] max-w-full flex-col overflow-hidden rounded-2xl border bg-white shadow-2xl transition-colors dark:bg-slate-900",
          isDragActive
            ? "border-slate-900 ring-4 ring-slate-900/10 dark:border-slate-100 dark:ring-slate-100/10"
            : "border-slate-200 dark:border-slate-800",
        )}
      >
        {isDragActive ? <FileDropOverlay /> : null}
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4 dark:border-slate-800/80">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-900 text-white shadow-sm dark:bg-slate-100 dark:text-slate-900">
              <FolderOpen className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">从资料库选择</h3>
              <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">把已有资料加入这次对话草稿</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300"
            title="关闭"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="border-b border-slate-100 px-5 py-3 dark:border-slate-800/80">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                placeholder="搜索文件名或格式"
                className="h-10 w-full rounded-xl border border-slate-200 bg-white pl-9 pr-3 text-sm text-slate-800 outline-none transition focus:border-slate-300 focus:ring-2 focus:ring-slate-900/10 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:ring-slate-100/10"
              />
            </div>
            <button
              type="button"
              onClick={onUploadLocalFiles}
              disabled={disabled || isUploading}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-slate-900 px-3 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
              title="上传本地文件到资料库"
            >
              {isUploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />}
              上传本地文件
            </button>
            <button
              type="button"
              onClick={() => void filesQuery.refetch()}
              disabled={filesQuery.isFetching}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-slate-200 px-3 text-sm font-medium text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <RefreshCw className={cn("h-4 w-4", filesQuery.isFetching && "animate-spin")} />
              刷新
            </button>
          </div>
        </div>

        <div className="min-h-[260px] flex-1 overflow-y-auto px-5 py-4">
          {filesQuery.isLoading ? (
            <div className="flex min-h-[240px] items-center justify-center text-sm text-slate-500 dark:text-slate-400">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              正在加载资料库...
            </div>
          ) : null}

          {!filesQuery.isLoading && files.length === 0 ? (
            <div className="flex min-h-[240px] flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-slate-50/70 px-6 text-center dark:border-slate-800 dark:bg-slate-800/30">
              <FolderOpen className="h-8 w-8 text-slate-400" />
              <p className="mt-3 text-sm font-medium text-slate-700 dark:text-slate-300">资料库还没有文件</p>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-500">先上传资料后，就可以在这里选择。</p>
              <button
                type="button"
                onClick={onUploadLocalFiles}
                disabled={disabled || isUploading}
                className="mt-4 inline-flex h-9 items-center justify-center gap-2 rounded-xl bg-slate-900 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
              >
                {isUploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />}
                上传本地文件
              </button>
            </div>
          ) : null}

          {!filesQuery.isLoading && files.length > 0 && visibleFiles.length === 0 ? (
            <div className="flex min-h-[200px] items-center justify-center text-sm text-slate-500 dark:text-slate-400">
              没有匹配的资料
            </div>
          ) : null}

          {visibleFiles.length > 0 ? (
            <div className="space-y-2">
              {visibleFiles.map((file) => {
                const checked = selected.has(file.id);
                const meta = draftFileStatusMeta(file);
                return (
                  <label
                    key={file.id}
                    className={cn(
                      "flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-3 transition",
                      checked
                        ? "border-slate-900 bg-slate-50 shadow-sm dark:border-slate-500 dark:bg-slate-800/70"
                        : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-700 dark:hover:bg-slate-800/60",
                    )}
                  >
                    <span
                      className={cn(
                        "flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition",
                        checked
                          ? "border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900"
                          : "border-slate-300 bg-white dark:border-slate-700 dark:bg-slate-900",
                      )}
                    >
                      {checked ? <Check className="h-3.5 w-3.5" /> : null}
                    </span>
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={checked}
                      onChange={() => toggleFileId(file.id)}
                    />
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 dark:bg-slate-800">
                      {draftFileIcon(file)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold text-slate-800 dark:text-slate-100">
                        {file.filename}
                      </span>
                      <span className="mt-0.5 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                        <span className={cn("inline-flex items-center gap-1", meta.tone)}>
                          {meta.icon}
                          {meta.label}
                        </span>
                        <span>{normalizeFileExt(file.filetype) || "file"}</span>
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
          ) : null}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-slate-100 px-5 py-4 dark:border-slate-800/80">
          <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
            已选择 {selectedCount} 份资料
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="h-9 rounded-xl px-4 text-sm font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
            >
              取消
            </button>
            <button
              type="button"
              onClick={confirmSelection}
              className="h-9 rounded-xl bg-slate-900 px-4 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
            >
              加入草稿
            </button>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

export function AiConversationDraftFileAttachments({
  fileIds,
  files,
  onChange,
  onUploadingChange,
  disabled = false,
  children,
}: AiConversationDraftFileAttachmentsProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [isUploading, setIsUploading] = useState(false);
  const [uploadingFileNames, setUploadingFileNames] = useState<string[]>([]);
  const [libraryPickerOpen, setLibraryPickerOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    onUploadingChange(isUploading);
  }, [isUploading, onUploadingChange]);

  const selectedFilesQuery = useQuery({
    queryKey: DRAFT_FILES_QUERY_KEY(fileIds),
    queryFn: () => fetchFiles(fileIds),
    enabled: fileIds.length > 0,
    refetchInterval: (query) => {
      const data = query.state.data as FilesData | undefined;
      return (data?.processing_count ?? 0) > 0 ? 2000 : false;
    },
  });

  const selectedFiles = selectedFilesQuery.data?.items ?? files;
  const optimisticUploadingFiles = uploadingFileNames.filter(
    (name) => !selectedFiles.some((file) => file.filename === name),
  );
  const hasFiles = selectedFiles.length > 0 || optimisticUploadingFiles.length > 0;

  const syncFilesCache = useCallback((nextFileIds: string[], nextFiles: FileRecord[]) => {
    queryClient.setQueryData<FilesData>(DRAFT_FILES_QUERY_KEY(nextFileIds), (previous) => {
      const previousItems = previous?.items ?? [];
      const nextById = new Map(previousItems.map((item) => [item.id, item]));
      for (const item of nextFiles) {
        nextById.set(item.id, item);
      }
      const nextItems = Array.from(nextById.values()).sort(
        (left, right) =>
          Date.parse(right.latest_updated_at || right.created_at || "") -
          Date.parse(left.latest_updated_at || left.created_at || ""),
      );
      return {
        course_id: null,
        total: nextItems.length,
        ready_count: nextItems.filter((item) => item.markdown_ready).length,
        processing_count: nextItems.filter((item) => !item.markdown_ready && item.status !== "failed" && !item.error_message?.trim()).length,
        failed_count: nextItems.filter((item) => Boolean(item.error_message?.trim()) || item.status === "failed").length,
        items: nextItems,
      };
    });
  }, [queryClient]);

  const uploadPendingFiles = useCallback(async (pendingFiles: File[]) => {
    if (!pendingFiles.length || disabled) {
      return;
    }

    const { supportedFiles, unsupportedFiles, imageParserUnavailableFiles, limitExceededMessage } =
      await partitionUploadFilesForRuntime(pendingFiles);
    const unsupportedMessage = unsupportedFiles.length ? buildUnsupportedFilesMessage(unsupportedFiles) : null;
    const imageParserUnavailableMessage = imageParserUnavailableFiles.length
      ? buildImageParserUnavailableMessage(imageParserUnavailableFiles)
      : null;
    setError(unsupportedMessage ?? imageParserUnavailableMessage ?? limitExceededMessage);
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
    if (limitExceededMessage) {
      toast({
        title: "上传超出限制",
        description: limitExceededMessage,
        variant: "error",
      });
      return;
    }
    if (!supportedFiles.length) {
      return;
    }

    setIsUploading(true);
    setUploadingFileNames(supportedFiles.map((file) => file.name));
    try {
      const result = await uploadDraftFiles(supportedFiles);
      const alreadyParsedNotice = buildAlreadyParsedUploadNotice(result);
      if (alreadyParsedNotice) {
        toast({ ...alreadyParsedNotice, variant: "info" });
      }
      const uploaded = result.uploaded_items ?? [];
      const uploadedIds = uploaded.map((file) => file.id);
      const nextFileIds = uniqueStrings([...fileIds, ...uploadedIds]);
      const nextFiles = [...selectedFiles.filter((file) => nextFileIds.includes(file.id)), ...uploaded]
        .filter((file, index, items) => items.findIndex((item) => item.id === file.id) === index);
      onChange(nextFileIds, nextFiles);
      syncFilesCache(nextFileIds, nextFiles);
      void queryClient.invalidateQueries({ queryKey: DRAFT_FILES_QUERY_KEY(nextFileIds) });
      void queryClient.invalidateQueries({ queryKey: ["files-library"] });
    } catch (requestError: unknown) {
      setError(getApiErrorMessage(requestError, "资料上传失败"));
    } finally {
      setIsUploading(false);
      setUploadingFileNames([]);
    }
  }, [disabled, fileIds, onChange, queryClient, selectedFiles, syncFilesCache, toast]);

  const handleSelectLibraryFiles = useCallback((nextFileIds: string[], nextFiles: FileRecord[]) => {
    const normalizedFileIds = uniqueStrings(nextFileIds);
    onChange(normalizedFileIds, nextFiles);
    setError(null);
    if (nextFiles.length > 0) {
      syncFilesCache(normalizedFileIds, nextFiles);
    }
    if (normalizedFileIds.length > 0) {
      void queryClient.invalidateQueries({ queryKey: DRAFT_FILES_QUERY_KEY(normalizedFileIds) });
    }
  }, [onChange, queryClient, syncFilesCache]);

  const openLibraryPicker = useCallback(() => {
    if (!disabled) {
      setLibraryPickerOpen(true);
    }
  }, [disabled]);

  const removeFile = useCallback((fileId: string) => {
    const nextFileIds = fileIds.filter((item) => item !== fileId);
    const nextFiles = selectedFiles.filter((file) => file.id !== fileId);
    onChange(nextFileIds, nextFiles);
    setError(null);
    if (nextFileIds.length > 0) {
      syncFilesCache(nextFileIds, nextFiles);
    }
  }, [fileIds, onChange, selectedFiles, syncFilesCache]);

  const handleFileSelect = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    const selectedUploadFiles = Array.from(event.target.files ?? []);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
    if (selectedUploadFiles.length === 0) {
      return;
    }
    void uploadPendingFiles(selectedUploadFiles);
  }, [uploadPendingFiles]);

  const handlePaste = useCallback((event: ClipboardEvent<HTMLTextAreaElement>) => {
    const pastedFiles = extractPasteFiles(event);
    if (pastedFiles.length === 0) {
      return;
    }
    event.preventDefault();
    void uploadPendingFiles(pastedFiles);
  }, [uploadPendingFiles]);

  const attachmentContent = hasFiles || error ? (
    <div className="space-y-2">
      {hasFiles ? (
        <div className="flex flex-wrap gap-2">
          {selectedFiles.map((file) => {
            const meta = draftFileStatusMeta(file);
            return (
              <div
                key={file.id}
                className="group inline-flex max-w-full items-center gap-2 rounded-2xl border border-zinc-200/80 bg-zinc-50/90 px-3 py-2 text-[13px] text-zinc-700 transition-colors hover:border-zinc-300 hover:bg-white dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:bg-slate-800/80"
              >
                <span className="shrink-0">{draftFileIcon(file)}</span>
                <span className="max-w-[220px] truncate font-medium text-zinc-800 dark:text-slate-200">{file.filename}</span>
                <span className={cn("shrink-0", meta.tone)} title={resolveFileProcessingLabel(file)}>
                  {meta.icon}
                </span>
                <button
                  type="button"
                  onClick={() => removeFile(file.id)}
                  title="从本次草稿中移除"
                  className="rounded-md p-0.5 text-zinc-400 transition-colors hover:bg-red-50 hover:text-red-500 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={disabled}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            );
          })}

          {optimisticUploadingFiles.map((filename) => (
            <div
              key={`uploading-${filename}`}
              className="inline-flex max-w-full items-center gap-2 rounded-2xl border border-zinc-200/80 bg-zinc-50/90 px-3 py-2 text-[13px] text-zinc-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
            >
              <FileUp className="h-3.5 w-3.5 shrink-0 text-zinc-400 dark:text-slate-500" />
              <span className="max-w-[220px] truncate font-medium text-zinc-800 dark:text-slate-200">{filename}</span>
              <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-indigo-500" />
            </div>
          ))}
        </div>
      ) : null}
      {error ? <p className="px-1 text-xs leading-5 text-red-500">{error}</p> : null}
    </div>
  ) : null;

  const toolbarActions = (
    <>
      <input
        ref={fileInputRef}
        type="file"
        title="选择要上传的文件资料"
        multiple
        className="hidden"
        onChange={handleFileSelect}
        accept={FILE_ACCEPT}
      />
      <button
        type="button"
        onClick={openLibraryPicker}
        disabled={disabled}
        className="flex h-8 items-center gap-1.5 whitespace-nowrap rounded-lg px-2.5 text-xs font-medium text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 disabled:cursor-not-allowed disabled:opacity-60 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
        title="从资料库选择或上传本地文件"
      >
        {isUploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FolderOpen className="h-3.5 w-3.5" />}
        资料库
      </button>
    </>
  );

  const modalContent = libraryPickerOpen ? (
    <LibraryPickerModal
      selectedFileIds={fileIds}
      onClose={() => setLibraryPickerOpen(false)}
      onConfirm={handleSelectLibraryFiles}
      onUploadLocalFiles={() => fileInputRef.current?.click()}
      onDropFiles={(droppedFiles) => void uploadPendingFiles(droppedFiles)}
      isUploading={isUploading}
      disabled={disabled}
    />
  ) : null;

  return (
    <>
      {children({
        attachmentContent,
        toolbarActions,
        modalContent,
        hasFiles,
        isUploading,
        onPaste: handlePaste,
        onFilesDrop: (droppedFiles) => void uploadPendingFiles(droppedFiles),
        onOpenLibraryPicker: openLibraryPicker,
      })}
    </>
  );
}
