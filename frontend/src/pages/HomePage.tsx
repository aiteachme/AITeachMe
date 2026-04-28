import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertCircle,
  ArrowUp,
  Check,
  CheckCircle2,
  ChevronDown,
  FileCode,
  FileImage,
  FolderOpen,
  Loader2,
  FileText,
  FileType,
  Paperclip,
  RefreshCw,
  Search,
  Upload,
  X,
  FileUp,
  Package,
} from "lucide-react";

import { createSubjectApiApiV1SubjectsAddPost } from "../api/generated/subjects";
import { apiClient, getApiErrorMessage } from "../api/client";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { cn } from "../lib/utils";
import { isElectronRuntime } from "../lib/electronRuntime";
import { useSystemSettingsOverview } from "../hooks/useSystemSettingsOverview";
import {
  buildUnsupportedFilesMessage,
  FILE_ACCEPT,
  extractPasteFiles,
  partitionUploadFiles,
} from "../lib/fileUpload";
import { resolveFileProcessingLabel } from "../components/knowledge-docs";
import { notifySubjectsImported } from "../lib/subjectEvents";
import { HeroAnimation } from "../components/ui/HeroAnimation";
import { FullPageDropOverlay } from "../components/ui/FullPageDropOverlay";
import { SubjectExportModal } from "../components/subject/SubjectExportModal";
import { useToast } from "../components/ui/Toast";
import {
  ChatModelSelect,
  DEFAULT_CHAT_MODEL_CHOICE,
  type ChatModelChoice,
  toChatRequestModel,
} from "../components/chat/ChatModelSelect";
import type { FileRecord, FilesData, FilesUploadData } from "../types/files";

/* ── API helpers (same as BuildPlanPage) ── */

interface ApiResponse<T> { code: number; data: T; }

async function uploadFiles(files: File[]): Promise<FilesUploadData> {
  const formData = new FormData();
  for (const file of files) formData.append("files", file);

  const response = await apiClient<ApiResponse<FilesUploadData>>({
    method: "POST",
    url: `/api/v1/files/upload`,
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
    subject_id: null,
    total: 0,
    ready_count: 0,
    processing_count: 0,
    failed_count: 0,
    items: [],
  };
}

async function linkFilesToSubject(subject: string, fileIds: string[]): Promise<FilesData> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/files/link`,
    data: { file_ids: fileIds },
  });
  return response.data;
}

/* ── Export / Import API helpers ── */

interface ImportResultData {
  subject_id: string;
  subject_name: string;
  imported_counts: Record<string, number>;
  warnings: string[];
}

/* ── Demo courses API ── */

interface CoursePackageItem {
  filename: string;
  subject_name: string;
  file_size_bytes: number;
  exported_at: string | null;
  stats: Record<string, number>;
}

async function fetchAvailableCourses(): Promise<CoursePackageItem[]> {
  const response = await apiClient<ApiResponse<CoursePackageItem[]>>({
    method: "GET",
    url: `/api/v1/courses`,
  });
  return response.data;
}

async function importCourseByFilename(filename: string, newName?: string): Promise<ImportResultData> {
  const response = await apiClient<ApiResponse<ImportResultData>>({
    method: "POST",
    url: `/api/v1/courses/${encodeURIComponent(filename)}/import`,
    data: newName ? { new_subject_name: newName } : {},
    timeout: 120000,
  });
  return response.data;
}

async function importSubject(file: File, newName?: string): Promise<ImportResultData> {
  const formData = new FormData();
  formData.append("file", file);
  if (newName) formData.append("new_subject_name", newName);
  const response = await apiClient<ApiResponse<ImportResultData>>({
    method: "POST",
    url: `/api/v1/subjects/import`,
    data: formData,
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120000,
  });
  return response.data;
}
/* ── Helpers ── */

const HOME_ENTRY_FILES_QUERY_KEY = (fileIds: string[]) => ["home-entry-files", fileIds.join(",")] as const;

function uniqueStrings(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)));
}

function formatFileSize(bytes?: number | null): string {
  if (bytes == null || !Number.isFinite(bytes)) return "未知";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) { value /= 1024; unitIndex += 1; }
  return `${value >= 10 || unitIndex === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unitIndex]}`;
}

function normalizeFileExt(filetype?: string | null): string {
  return String(filetype ?? "").trim().toLowerCase().replace(/^\./, "");
}

function homeFileIcon(file: Pick<FileRecord, "filetype">) {
  const ext = normalizeFileExt(file.filetype);
  if (ext === "pdf") return <FileText className="h-3.5 w-3.5 text-red-400" />;
  if (["png", "jpg", "jpeg", "webp"].includes(ext)) return <FileImage className="h-3.5 w-3.5 text-emerald-400" />;
  if (["md", "markdown"].includes(ext)) return <FileCode className="h-3.5 w-3.5 text-violet-400" />;
  if (["docx", "doc"].includes(ext)) return <FileText className="h-3.5 w-3.5 text-blue-400" />;
  if (["ppt", "pptx"].includes(ext)) return <FileType className="h-3.5 w-3.5 text-orange-400" />;
  return <FileUp className="h-3.5 w-3.5 text-zinc-400" />;
}

function homeFileStatusMeta(file: Pick<FileRecord, "markdown_ready" | "error_message" | "status">) {
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
    icon: <Loader2 className="h-3.5 w-3.5 animate-spin text-sky-500" />,
    tone: "text-sky-600",
  };
}

function LibraryPickerModal({
  selectedFileIds,
  onClose,
  onConfirm,
}: {
  selectedFileIds: string[];
  onClose: () => void;
  onConfirm: (fileIds: string[], files: FileRecord[]) => void;
}) {
  const [searchTerm, setSearchTerm] = useState("");
  const [selected, setSelected] = useState<Set<string>>(() => new Set(selectedFileIds));

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
      return (
        file.filename.toLowerCase().includes(normalizedSearchTerm) ||
        ext.includes(normalizedSearchTerm)
      );
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
        className="relative z-10 flex max-h-[82vh] w-[640px] max-w-full flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-900"
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4 dark:border-slate-800/80">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-900 text-white shadow-sm dark:bg-slate-100 dark:text-slate-900">
              <FolderOpen className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">从资料库选择</h3>
              <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">把已有资料加入这次新建学科</p>
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
                const meta = homeFileStatusMeta(file);
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
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={checked}
                      onChange={() => toggleFileId(file.id)}
                    />
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
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 dark:bg-slate-800">
                      {homeFileIcon(file)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                        {file.filename}
                      </span>
                      <span className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400 dark:text-slate-500">
                        <span>{normalizeFileExt(file.filetype).toUpperCase() || "FILE"}</span>
                        <span>{formatFileSize(file.file_size_bytes)}</span>
                        {file.estimated_pages ? <span>{file.estimated_pages} 页</span> : null}
                      </span>
                    </span>
                    <span className={cn("flex shrink-0 items-center gap-1 text-xs font-medium", meta.tone)} title={resolveFileProcessingLabel(file)}>
                      {meta.icon}
                      {meta.label}
                    </span>
                  </label>
                );
              })}
            </div>
          ) : null}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-slate-100 bg-slate-50/70 px-5 py-4 dark:border-slate-800/80 dark:bg-slate-900">
          <div className="text-xs font-medium text-slate-500 dark:text-slate-400">已选 {selectedCount} 份资料</div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
            >
              取消
            </button>
            <button
              type="button"
              onClick={confirmSelection}
              disabled={filesQuery.isLoading && selectedCount === 0}
              className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-sm font-bold text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white dark:disabled:bg-slate-800 dark:disabled:text-slate-600"
            >
              <Check className="h-4 w-4" />
              确认选择
            </button>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

/* ── Export Modal ── */

/* ── Import Modal ── */

function ImportModal({
  onClose,
  onSuccess,
}: {
  onClose: () => void;
  onSuccess: (result: ImportResultData) => void;
}) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [customName, setCustomName] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const importMutation = useMutation({
    mutationFn: () => importSubject(selectedFile!, customName.trim() || undefined),
    onSuccess: (result) => { onSuccess(result); onClose(); },
  });

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div className="absolute inset-0 modal-backdrop" onClick={onClose} />
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95 }}
        className="relative z-10 w-[480px] max-w-[90vw] bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden dark:bg-slate-900 dark:border-slate-800"
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 dark:border-slate-800/80">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 shadow-sm">
              <Upload className="w-5 h-5 text-white" />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">导入学科</h3>
              <p className="text-xs text-slate-500 mt-0.5 dark:text-slate-400">从 .atmx 文件导入已构建的学科</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors dark:hover:bg-slate-800 dark:text-slate-500 dark:hover:text-slate-300" title="关闭">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="px-6 py-5 space-y-4">
          <input
            type="file"
            ref={inputRef}
            accept=".atmx,.zip"
            className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) setSelectedFile(f); }}
          />
          <div
            onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setDragOver(true); }}
            onDragLeave={(e) => { e.stopPropagation(); setDragOver(false); }}
            onDrop={(e) => { e.preventDefault(); e.stopPropagation(); setDragOver(false); const f = e.dataTransfer.files[0]; if (f) setSelectedFile(f); }}
            onClick={() => inputRef.current?.click()}
            className={cn(
              "flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-8 cursor-pointer transition-all",
              dragOver
                ? "border-emerald-400 bg-emerald-50 dark:bg-emerald-900/10"
                : selectedFile
                  ? "border-slate-300 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/50"
                  : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-700 dark:hover:bg-slate-800/80"
            )}
          >
            {selectedFile ? (
              <>
                <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-emerald-100 dark:bg-emerald-900/30">
                  <Package className="w-6 h-6 text-emerald-600 dark:text-emerald-400" />
                </div>
                <div className="text-center">
                  <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">{selectedFile.name}</p>
                  <p className="text-xs text-slate-400 mt-1">{formatFileSize(selectedFile.size)}</p>
                </div>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); setSelectedFile(null); }}
                  className="text-xs text-slate-500 hover:text-red-500 dark:text-slate-400 dark:hover:text-red-400 underline"
                >
                  重新选择
                </button>
              </>
            ) : (
              <>
                <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-slate-100 dark:bg-slate-800">
                  <Upload className="w-6 h-6 text-slate-400 dark:text-slate-500" />
                </div>
                <div className="text-center">
                  <p className="text-sm font-medium text-slate-600 dark:text-slate-300">点击选择或拖拽 .atmx 文件</p>
                  <p className="text-xs text-slate-400 mt-1 dark:text-slate-500">支持 AITeachMe 导出包</p>
                </div>
              </>
            )}
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1.5 dark:text-slate-400">自定义学科名称（可选）</label>
            <input
              type="text"
              value={customName}
              onChange={(e) => setCustomName(e.target.value)}
              placeholder="留空则使用导出时的原名"
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-300 transition-colors dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:placeholder:text-slate-500 dark:focus:ring-slate-100/10"
            />
          </div>
          {importMutation.isError && (
            <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2">
              <p className="text-sm text-red-600">{getApiErrorMessage(importMutation.error, "导入失败")}</p>
            </div>
          )}
        </div>
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-100 bg-slate-50/50 dark:border-slate-800/80 dark:bg-slate-900">
          <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 rounded-lg hover:bg-slate-100 transition-colors dark:text-slate-400 dark:hover:text-slate-200 dark:hover:bg-slate-800">
            取消
          </button>
          <button
            onClick={() => importMutation.mutate()}
            disabled={!selectedFile || importMutation.isPending}
            className={cn(
              "flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-bold transition-all",
              selectedFile && !importMutation.isPending
                ? "bg-slate-900 text-white hover:bg-slate-800 shadow-sm hover:shadow-md"
                : "bg-slate-200 text-slate-400 cursor-not-allowed"
            )}
          >
            {importMutation.isPending ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> 导入中…</>
            ) : (
              <><Upload className="w-4 h-4" /> 导入</>
            )}
          </button>
        </div>
      </motion.div>
    </div>
  );
}

/* ── Rename Modal ── */

function RenameModal({
  subjectId,
  initialName,
  onClose,
  onSuccess,
}: {
  subjectId: string;
  initialName: string;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [name, setName] = useState(initialName);

  const renameMutation = useMutation({
    mutationFn: async () => {
      await apiClient({
        method: "POST",
        url: `/api/v1/subjects/update`,
        data: { subject_id: subjectId, name: name.trim() },
      });
    },
    onSuccess: () => { onSuccess(); onClose(); },
  });

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div className="absolute inset-0 modal-backdrop" onClick={onClose} />
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95 }}
        className="relative z-10 w-[420px] max-w-[90vw] bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden dark:bg-slate-900 dark:border-slate-800"
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 dark:border-slate-800/80">
          <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">重命名学科</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors dark:hover:bg-slate-800 dark:text-slate-500 dark:hover:text-slate-300" title="关闭">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="px-6 py-5">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) renameMutation.mutate(); }}
            placeholder="输入学科名称"
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-300 transition-colors dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:placeholder:text-slate-500 dark:focus:ring-slate-100/10"
            autoFocus
          />
          {renameMutation.isError && (
            <p className="mt-2 text-sm text-red-600">{getApiErrorMessage(renameMutation.error, "重命名失败")}</p>
          )}
        </div>
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-100 bg-slate-50/50 dark:border-slate-800/80 dark:bg-slate-900">
          <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 rounded-lg hover:bg-slate-100 transition-colors dark:text-slate-400 dark:hover:text-slate-200 dark:hover:bg-slate-800">
            取消
          </button>
          <button
            onClick={() => renameMutation.mutate()}
            disabled={!name.trim() || renameMutation.isPending}
            className={cn(
              "flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-bold transition-all",
              name.trim() && !renameMutation.isPending
                ? "bg-slate-900 text-white hover:bg-slate-800 shadow-sm hover:shadow-md"
                : "bg-slate-200 text-slate-400 cursor-not-allowed"
            )}
          >
            {renameMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            确认
          </button>
        </div>
      </motion.div>
    </div>
  );
}

/* ── Main HomePage ── */

export function HomePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const isElectron = isElectronRuntime();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const settingsOverview = useSystemSettingsOverview();

  const [prompt, setPrompt] = useState("");
  const [draftSubjectId, setDraftSubjectId] = useState<string | null>(null);
  const [isCreatingDraftSubject, setIsCreatingDraftSubject] = useState(false);
  const [isStartingBuild, setIsStartingBuild] = useState(false);
  const [isUploadingFiles, setIsUploadingFiles] = useState(false);
  const [uploadingFileNames, setUploadingFileNames] = useState<string[]>([]);
  const [entryFileIds, setEntryFileIds] = useState<string[]>([]);
  const [chatModel, setChatModel] = useState<ChatModelChoice>(DEFAULT_CHAT_MODEL_CHOICE);
  const [recentOpen, setRecentOpen] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal state
  const [exportSubjectId, setExportSubjectId] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [libraryPickerOpen, setLibraryPickerOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<{ id: string; name: string } | null>(null);
  const newEntryAt = (location.state as { newEntryAt?: number } | null)?.newEntryAt;

  useEffect(() => {
    if (!newEntryAt) {
      return;
    }
    setPrompt("");
    setDraftSubjectId(null);
    setIsCreatingDraftSubject(false);
    setIsStartingBuild(false);
    setIsUploadingFiles(false);
    setUploadingFileNames([]);
    setEntryFileIds([]);
    setLibraryPickerOpen(false);
    setError(null);
    navigate("/", { replace: true, state: null });
    window.requestAnimationFrame(() => textareaRef.current?.focus());
  }, [navigate, newEntryAt]);

  const { data: entryFilesData } = useQuery({
    queryKey: HOME_ENTRY_FILES_QUERY_KEY(entryFileIds),
    enabled: entryFileIds.length > 0,
    queryFn: () => fetchFiles(entryFileIds),
    refetchInterval: (query) => {
      const data = query.state.data as FilesData | undefined;
      if (isUploadingFiles || (data?.processing_count ?? 0) > 0) {
        return 2000;
      }
      return false;
    },
  });

  // ── Courses query ──
  const shouldShowDemoCourses = settingsOverview?.mode === "cloud";
  const { data: courses = [], isLoading: coursesLoading } = useQuery({
    queryKey: ["available-courses"],
    queryFn: fetchAvailableCourses,
    enabled: shouldShowDemoCourses,
  });

  const courseImportMutation = useMutation({
    mutationFn: ({ filename, newName }: { filename: string; newName?: string }) =>
      importCourseByFilename(filename, newName),
    onSuccess: (result) => {
      setError(null);
      notifySubjectsImported({ subjectId: result.subject_id });
      queryClient.invalidateQueries({ queryKey: ["subjects"] });
      queryClient.invalidateQueries({ queryKey: ["available-courses"] });
      toast({
        title: "导入成功",
        description: `${result.subject_name} 已加入左侧学科列表。`,
        variant: "success",
      });
    },
    onError: (err: unknown) => {
      const message = getApiErrorMessage(err, "演示课程导入失败");
      setError(message);
      toast({
        title: "导入失败",
        description: message,
        variant: "error",
      });
    },
  });

  // ── Mutations ──
  const ensureDraftSubjectId = useCallback(async () => {
    if (draftSubjectId) {
      return draftSubjectId;
    }
    setIsCreatingDraftSubject(true);
    try {
      const created = unwrapOrvalResponse(
        await createSubjectApiApiV1SubjectsAddPost({ name: "" })
      );
      if (!created) {
        throw new Error("创建学科失败");
      }
      setDraftSubjectId(created.subject_id);
      await queryClient.invalidateQueries({ queryKey: ["subjects"] });
      return created.subject_id;
    } catch (err: unknown) {
      const message = getApiErrorMessage(err, "创建学习空间失败，请重试");
      setError(message);
      throw new Error(message);
    } finally {
      setIsCreatingDraftSubject(false);
    }
  }, [draftSubjectId, queryClient]);

  const syncEntryFilesCache = useCallback((fileIds: string[], uploaded: FileRecord[]) => {
    queryClient.setQueryData<FilesData>(HOME_ENTRY_FILES_QUERY_KEY(fileIds), (previous) => {
      const previousItems = previous?.items ?? [];
      const nextById = new Map(previousItems.map((item) => [item.id, item]));
      for (const item of uploaded) {
        nextById.set(item.id, item);
      }
      const nextItems = Array.from(nextById.values()).sort(
        (left, right) =>
          Date.parse(right.latest_updated_at || right.created_at || "") -
          Date.parse(left.latest_updated_at || left.created_at || ""),
      );
      return {
        subject_id: null,
        total: nextItems.length,
        ready_count: nextItems.filter((item) => item.markdown_ready).length,
        processing_count: nextItems.filter((item) => !item.markdown_ready && item.status !== "failed" && !item.error_message?.trim()).length,
        failed_count: nextItems.filter((item) => Boolean(item.error_message?.trim()) || item.status === "failed").length,
        items: nextItems,
      };
    });
  }, [queryClient]);

  const uploadPendingFiles = useCallback(async (files: File[]) => {
    if (!files.length) {
      return;
    }
    const { supportedFiles, unsupportedFiles } = partitionUploadFiles(files);
    const unsupportedMessage = unsupportedFiles.length
      ? buildUnsupportedFilesMessage(unsupportedFiles)
      : null;
    setError(unsupportedMessage);
    if (!supportedFiles.length) {
      return;
    }
    setIsUploadingFiles(true);
    setUploadingFileNames(supportedFiles.map((file) => file.name));
    try {
      const result = await uploadFiles(supportedFiles);
      const uploaded = result.uploaded_items ?? [];
      const uploadedIds = uploaded.map((file) => file.id);
      const nextFileIds = uniqueStrings([...entryFileIds, ...uploadedIds]);
      setEntryFileIds(nextFileIds);
      syncEntryFilesCache(nextFileIds, uploaded);
      await queryClient.invalidateQueries({ queryKey: HOME_ENTRY_FILES_QUERY_KEY(nextFileIds) });
      await queryClient.invalidateQueries({ queryKey: ["files-library"] });
    } catch (err: unknown) {
      setError(getApiErrorMessage(err, "文件上传失败"));
    } finally {
      setIsUploadingFiles(false);
      setUploadingFileNames([]);
    }
  }, [entryFileIds, queryClient, syncEntryFilesCache]);

  const handleSelectLibraryFiles = useCallback((fileIds: string[], files: FileRecord[]) => {
    const nextFileIds = uniqueStrings(fileIds);
    setEntryFileIds(nextFileIds);
    setError(null);
    if (files.length > 0) {
      syncEntryFilesCache(nextFileIds, files);
    }
    if (nextFileIds.length > 0) {
      void queryClient.invalidateQueries({ queryKey: HOME_ENTRY_FILES_QUERY_KEY(nextFileIds) });
    }
  }, [queryClient, syncEntryFilesCache]);

  // ── Handlers ──
  const uploadedFiles = entryFilesData?.items ?? [];
  const optimisticUploadingFiles = uploadingFileNames.filter(
    (name) => !uploadedFiles.some((file) => file.filename === name),
  );
  const hasEntryFiles = uploadedFiles.length > 0 || optimisticUploadingFiles.length > 0;
  const entryFilesStatusText = useMemo(() => {
    if (isCreatingDraftSubject) {
      return "正在创建学习空间，并关联已选择资料。";
    }
    if (isUploadingFiles) {
      return "资料正在上传，上传完成后会继续后台解析；文件会保留在这里，除非你手动移除。";
    }
    if (!hasEntryFiles) {
      return "";
    }
    const readyCount = entryFilesData?.ready_count ?? uploadedFiles.filter((file) => file.markdown_ready).length;
    const processingCount =
      entryFilesData?.processing_count ??
      uploadedFiles.filter((file) => !file.markdown_ready && file.status !== "failed" && !file.error_message?.trim()).length;
    const failedCount =
      entryFilesData?.failed_count ??
      uploadedFiles.filter((file) => Boolean(file.error_message?.trim()) || file.status === "failed").length;

    if (processingCount > 0) {
      return `${processingCount} 份资料正在解析中；完成后会自动转为可用状态。`;
    }
    if (readyCount > 0 && failedCount === 0) {
      return `${readyCount} 份资料已就绪，可以直接开始规划。`;
    }
    if (readyCount > 0 && failedCount > 0) {
      return `${readyCount} 份资料已就绪，${failedCount} 份资料处理失败；可以先移除失败文件。`;
    }
    if (failedCount > 0) {
      return `${failedCount} 份资料处理失败；你可以先从本次新建中移除。`;
    }
    return "资料已加入，会继续在后台解析；从这里移除不会删除资料库文件。";
  }, [entryFilesData?.failed_count, entryFilesData?.processing_count, entryFilesData?.ready_count, hasEntryFiles, isCreatingDraftSubject, isUploadingFiles, uploadedFiles]);
  const canGenerate = prompt.trim().length > 0 || hasEntryFiles;

  const handleGenerate = async () => {
    if (!canGenerate) return;
    setError(null);
    setIsStartingBuild(true);
    try {
      const subjectId = await ensureDraftSubjectId();
      if (entryFileIds.length > 0) {
        await linkFilesToSubject(subjectId, entryFileIds);
        await queryClient.invalidateQueries({ queryKey: ["subjects"] });
        await queryClient.invalidateQueries({ queryKey: ["files", subjectId] });
      }
      const userGoal = prompt.trim();
      const selectedModel = toChatRequestModel(chatModel);
      navigate(`/subject/${subjectId}/build`, {
        state: userGoal || selectedModel
          ? { initialPrompt: userGoal || undefined, autoStart: Boolean(userGoal), model: selectedModel }
          : undefined,
      });
    } catch {
      // ensureDraftSubjectId already writes user-facing error
    } finally {
      setIsStartingBuild(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleGenerate();
    }
  };

  const handlePaste = useCallback((e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const files = extractPasteFiles(e);
    if (files.length > 0) {
      e.preventDefault();
      void uploadPendingFiles(files);
    }
    // If no files, let the default text paste proceed
  }, [uploadPendingFiles]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newFiles = Array.from(e.target.files ?? []);
    if (fileInputRef.current) fileInputRef.current.value = "";
    if (newFiles.length === 0) return;
    void uploadPendingFiles(newFiles);
  };

  const handleFileDrop = useCallback((droppedFiles: File[]) => {
    if (!droppedFiles.length) return;
    void uploadPendingFiles(droppedFiles);
  }, [uploadPendingFiles]);

  const handleRemoveEntryFile = useCallback((fileId: string) => {
    const nextFileIds = entryFileIds.filter((item) => item !== fileId);
    setEntryFileIds(nextFileIds);
    setError(null);
    if (nextFileIds.length > 0) {
      syncEntryFilesCache(nextFileIds, uploadedFiles.filter((file) => file.id !== fileId));
    }
  }, [entryFileIds, syncEntryFilesCache, uploadedFiles]);

  const isWorking = isCreatingDraftSubject || isStartingBuild || isUploadingFiles;
  const hasDemoCourses = shouldShowDemoCourses && courses.length > 0;
  const shouldShowDemoCourseSection = shouldShowDemoCourses && (coursesLoading || hasDemoCourses);

  return (
    <>
    <FullPageDropOverlay
      onDrop={(droppedFiles) => {
        handleFileDrop(droppedFiles);
      }}
      disabled={isWorking || Boolean(exportSubjectId) || importOpen || libraryPickerOpen || Boolean(renameTarget)}
    />
    <div
      className={cn(
        "relative flex w-full flex-col items-center overflow-x-clip bg-transparent p-4 pt-24 selection:bg-zinc-200 md:p-8 md:pt-32",
        isElectron ? "min-h-full" : "min-h-[100dvh]",
      )}
    >
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: "easeOut" }}
        className={cn(
          "relative z-20 w-full max-w-[800px] flex flex-col items-center",
          !shouldShowDemoCourseSection
            ? "justify-center min-h-[calc(100dvh-9rem)] translate-y-[8vh] md:translate-y-[11vh]"
            : "mt-[10vh]"
        )}
      >
        {/* ── Logo & Title ── */}
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.1, type: "spring", stiffness: 200, damping: 20 }}
          className="flex flex-col items-center justify-center mb-2"
        >
          <HeroAnimation />
          <motion.div
            initial={{ opacity: 0, y: 10, filter: "blur(6px)" }}
            animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
            transition={{ duration: 0.8, ease: "easeOut", delay: 2.8 }}
            className="flex flex-col items-center mt-3"
          >
            <h1
              className="text-2xl md:text-3xl font-bold tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-slate-800 via-indigo-700 to-violet-600 animate-text-gradient dark:from-slate-100 dark:via-indigo-400 dark:to-violet-400"
              style={{ backgroundSize: "200% auto" }}
            >
              AITeachMe
            </h1>
          </motion.div>
        </motion.div>

        {/* ── Slogan ── */}
        <motion.p
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 3.0, duration: 0.6 }}
          className="mb-8 px-4 text-center text-[15px] leading-relaxed text-zinc-500 dark:text-slate-400"
        >
          把任何令人头疼的学习资料，变成你的 24 小时专属"赛博私教"。
        </motion.p>

        {/* ── Unified Input Area ── */}
        <motion.div
          initial={{ opacity: 0, scale: 0.97 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.35 }}
          className="w-full relative z-10"
        >
          <div className={cn(
            "w-full overflow-hidden rounded-[30px] border-[1.5px] backdrop-blur-xl transition-all",
            hasEntryFiles
              ? "border-indigo-300/80 bg-indigo-50/40 shadow-[0_8px_30px_rgb(99,102,241,0.10)] ring-2 ring-indigo-500/8 dark:border-indigo-500/30 dark:bg-indigo-900/10 dark:shadow-[0_8px_30px_rgb(99,102,241,0.2)]"
              : "border-zinc-200/80 bg-white/70 shadow-[0_8px_30px_rgb(0,0,0,0.06)] hover:border-zinc-300 hover:bg-white/80 hover:shadow-[0_8px_30px_rgb(0,0,0,0.1)] dark:border-slate-700 dark:bg-slate-900/70 dark:hover:border-slate-600 dark:hover:bg-slate-900/90",
            "focus-within:border-indigo-300 focus-within:shadow-[0_8px_30px_rgb(99,102,241,0.15)] focus-within:ring-4 focus-within:ring-indigo-500/10 dark:focus-within:border-indigo-500/50"
          )}>
            <textarea
              ref={textareaRef}
              placeholder="直接输入学习目标，也可以先上传资料再一起规划"
              className="w-full min-h-[96px] max-h-[240px] resize-none border-0 bg-transparent px-4 pb-2 pt-4 text-[15px] leading-[1.8] text-zinc-800 focus:outline-none placeholder:text-zinc-400 dark:text-slate-200 dark:placeholder:text-slate-500"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              rows={3}
              disabled={isCreatingDraftSubject}
            />

            <div className="px-4 pb-3 pt-1 flex flex-col gap-2">
              {(hasEntryFiles || isUploadingFiles) && (
                <div className="space-y-2">
                  <div className="flex flex-wrap gap-2">
                  {uploadedFiles.map((file) => {
                    const meta = homeFileStatusMeta(file);
                    return (
                      <div
                        key={file.id}
                        className="group inline-flex max-w-full items-center gap-2 rounded-2xl border border-zinc-200/80 bg-zinc-50/90 px-3 py-2 text-[13px] text-zinc-700 transition-colors hover:border-zinc-300 hover:bg-white dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:bg-slate-800/80"
                      >
                        <span className="shrink-0">{homeFileIcon(file)}</span>
                        <span className="max-w-[220px] truncate font-medium text-zinc-800 dark:text-slate-200">{file.filename}</span>
                        <span className={cn("shrink-0", meta.tone)} title={resolveFileProcessingLabel(file)}>
                          {meta.icon}
                        </span>
                        <button
                          type="button"
                          onClick={() => handleRemoveEntryFile(file.id)}
                          title="从本次新建中移除"
                          className="rounded-md p-0.5 text-zinc-400 transition-colors hover:bg-red-50 hover:text-red-500 disabled:cursor-not-allowed disabled:opacity-50"
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
                      <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-sky-500" />
                    </div>
                  ))}
                  </div>
                  {entryFilesStatusText ? (
                    <p className="px-1 text-[12px] leading-5 text-zinc-500">{entryFilesStatusText}</p>
                  ) : null}
                </div>
              )}

              <div className="flex flex-wrap items-center justify-between gap-2 px-1">
                <div className="flex flex-1 flex-wrap items-center gap-2">
                  <input 
                    type="file" 
                    title="选择要上传的文件资料"
                    multiple 
                    className="hidden" 
                    ref={fileInputRef} 
                    onChange={handleFileSelect}
                    accept={FILE_ACCEPT}
                  />
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[12px] font-medium text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                  >
                    {isUploadingFiles || isCreatingDraftSubject ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Paperclip className="h-3.5 w-3.5" />
                    )}
                    {hasEntryFiles ? "添加资料" : "添加资料"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setLibraryPickerOpen(true)}
                    disabled={isWorking}
                    className="flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[12px] font-medium text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 disabled:cursor-not-allowed disabled:opacity-60 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                    title="从我的资料库选择已有文件"
                  >
                    <FolderOpen className="h-3.5 w-3.5" />
                    从资料库选
                  </button>
                  {isWorking && (
                    <span className="ml-2 flex items-center text-[12px] font-medium text-zinc-500">
                      <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                      {isStartingBuild || isCreatingDraftSubject ? "正在创建学习空间..." : "正在上传并解析资料..."}
                    </span>
                  )}
                </div>

                <div className="ml-2 flex shrink-0 items-center gap-2">
                  <ChatModelSelect
                    value={chatModel}
                    onChange={setChatModel}
                    disabled={isWorking}
                  />
                  <button
                    onClick={handleGenerate}
                    disabled={!canGenerate || isWorking}
                    className={cn(
                      "flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-all focus:outline-none focus:ring-4 focus:ring-zinc-900/10 active:scale-[0.98]",
                      canGenerate && !isWorking
                        ? "bg-zinc-900 text-white shadow-sm hover:bg-zinc-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
                        : "cursor-not-allowed bg-zinc-100 text-zinc-300 dark:bg-slate-800 dark:text-slate-600"
                    )}
                  >
                    <ArrowUp className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </div>
          </div>
        </motion.div>

        {/* ── Error ── */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-4 w-full p-4 bg-red-50 border border-red-100 rounded-xl"
            >
              <p className="text-sm text-red-600 font-medium text-center">
                {error}
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      {/* ═══ Recent Classrooms / Demo Courses ═══ */}
      {shouldShowDemoCourseSection && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.5 }}
          className="relative z-10 mt-12 w-full max-w-5xl flex flex-col items-center"
        >
          {/* Section Toggle */}
          <button
            onClick={() => setRecentOpen(!recentOpen)}
            className="group flex w-full cursor-pointer items-center gap-4 py-3"
          >
            <div className="flex-1 h-[1px] bg-zinc-200 group-hover:bg-zinc-300 transition-colors dark:bg-slate-800 dark:group-hover:bg-slate-700" />
            <span className="flex shrink-0 select-none items-center gap-2 text-[13px] font-semibold tracking-tight text-zinc-400 transition-colors group-hover:text-zinc-800 dark:text-slate-500 dark:group-hover:text-slate-300">
              <Package className="h-4 w-4" />
              演示课程
              <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-500 shadow-[inset_0_1px_2px_rgba(0,0,0,0.02)] dark:bg-slate-800 dark:text-slate-400">{courses.length}</span>
              <motion.div
                animate={{ rotate: recentOpen ? 180 : 0 }}
                transition={{ duration: 0.3, ease: "easeInOut" }}
              >
                <ChevronDown className="h-4 w-4" />
              </motion.div>
            </span>
            <div className="flex-1 h-[1px] bg-zinc-200 group-hover:bg-zinc-300 transition-colors dark:bg-slate-800 dark:group-hover:bg-slate-700" />
          </button>

          {/* Expandable Content */}
          <AnimatePresence>
            {recentOpen && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.4, ease: [0.25, 0.1, 0.25, 1] }}
                className="w-full overflow-hidden"
              >
                <div className="flex items-center justify-end pt-4 pb-2 px-1">
                  <button
                    onClick={() => setImportOpen(true)}
                    className="flex items-center gap-2 px-3.5 py-2 rounded-xl text-sm font-medium text-slate-600 bg-white border border-slate-200 hover:border-slate-300 hover:bg-slate-50 shadow-sm hover:shadow transition-all dark:bg-slate-900 dark:border-slate-800 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:bg-slate-800"
                    title="从文件导入学科包"
                  >
                    <Upload className="w-4 h-4 text-emerald-500" />
                    上传导入
                  </button>
                </div>

                  <div className="pt-2 pb-12">
                    {coursesLoading && (
                      <div className="py-8 flex justify-center">
                        <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
                      </div>
                    )}
                    {courses.length > 0 && (
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                        {courses.map((course, i) => (
                          <motion.div
                            key={course.filename}
                            initial={{ opacity: 0, y: 16 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: i * 0.05, duration: 0.35, ease: "easeOut" }}
                          >
                            <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm hover:shadow-md hover:border-slate-300 transition-all duration-300 h-full flex flex-col hover:-translate-y-1">
                              <div className="flex items-start justify-between mb-3">
                                <div className="flex-1 mr-3">
                                  <h3 className="text-lg font-bold text-slate-900 line-clamp-1">{course.subject_name}</h3>
                                  <p className="mt-1 text-xs font-medium text-emerald-600">演示课程</p>
                                </div>
                                <div className="p-2 bg-gradient-to-br from-emerald-50 to-teal-50 rounded-lg border border-emerald-100">
                                  <Package className="w-5 h-5 text-emerald-500" />
                                </div>
                              </div>

                              {/* Stats chips */}
                              <div className="flex flex-wrap gap-1.5 mb-4">
                                {course.stats.knowledge_unit_count > 0 && (
                                  <span className="text-[10px] font-medium text-slate-500 bg-slate-100 px-2 py-0.5 rounded-full">
                                    {course.stats.knowledge_unit_count} 知识点
                                  </span>
                                )}
                                {course.stats.raw_file_count > 0 && (
                                  <span className="text-[10px] font-medium text-slate-500 bg-slate-100 px-2 py-0.5 rounded-full">
                                    {course.stats.raw_file_count} 文件
                                  </span>
                                )}
                                {course.file_size_bytes > 0 && (
                                  <span className="text-[10px] font-medium text-slate-500 bg-slate-100 px-2 py-0.5 rounded-full">
                                    {formatFileSize(course.file_size_bytes)}
                                  </span>
                                )}
                              </div>

                              {/* Footer */}
                              <div className="mt-auto border-t border-slate-100 pt-3">
                                <button
                                  onClick={() => courseImportMutation.mutate({ filename: course.filename })}
                                  disabled={courseImportMutation.isPending}
                                  className={cn(
                                    "flex min-h-9 w-full items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm font-bold transition-all",
                                    !courseImportMutation.isPending
                                      ? "bg-slate-900 text-white hover:bg-slate-800 shadow-sm hover:shadow-md"
                                      : "bg-slate-200 text-slate-400 cursor-not-allowed"
                                  )}
                                  title={`导入 ${course.subject_name} 到左侧学科列表`}
                                >
                                  {courseImportMutation.isPending ? (
                                    <><Loader2 className="h-4 w-4 animate-spin" /> 导入中</>
                                  ) : (
                                    <><Upload className="h-4 w-4" /> 导入</>
                                  )}
                                </button>
                              </div>
                            </div>
                          </motion.div>
                        ))}
                      </div>
                    )}
                  </div>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      )}

      {/* Footer */}
      <div className="mt-auto pt-12 pb-6 text-center text-sm text-slate-400 font-medium tracking-wide">
        <a 
          href="https://github.com/aiteachme/AiTeachMe" 
          target="_blank" 
          rel="noopener noreferrer" 
          className="hover:text-slate-600 transition-colors"
        >
          AITeachMe Open Source Project
        </a>
      </div>
    </div>
    {/* ═══ Modals ═══ */}
    <AnimatePresence>
      {exportSubjectId && (
        <SubjectExportModal
          key="export"
          subjectId={exportSubjectId}
          onClose={() => setExportSubjectId(null)}
        />
      )}
      {importOpen && (
        <ImportModal
          key="import"
          onClose={() => setImportOpen(false)}
          onSuccess={(result) => {
            notifySubjectsImported({ subjectId: result.subject_id });
            queryClient.invalidateQueries({ queryKey: ["subjects"] });
            toast({
              title: "导入成功",
              description: `${result.subject_name} 已加入左侧学科列表。`,
              variant: "success",
            });
          }}
        />
      )}
      {libraryPickerOpen && (
        <LibraryPickerModal
          key="library-picker"
          selectedFileIds={entryFileIds}
          onClose={() => setLibraryPickerOpen(false)}
          onConfirm={handleSelectLibraryFiles}
        />
      )}
      {renameTarget && (
        <RenameModal
          key="rename"
          subjectId={renameTarget.id}
          initialName={renameTarget.name}
          onClose={() => setRenameTarget(null)}
          onSuccess={() => queryClient.invalidateQueries({ queryKey: ["subjects"] })}
        />
      )}
    </AnimatePresence>
    </>
  );
}
