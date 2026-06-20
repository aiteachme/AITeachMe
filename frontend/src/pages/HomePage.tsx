import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertCircle,
  ArrowUp,
  BookOpen,
  CalendarCheck,
  Check,
  CheckCircle2,
  ChevronDown,
  ClipboardList,
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
  Target,
} from "lucide-react";

import { LONG_RUNNING_API_TIMEOUT_MS, apiClient, getApiErrorMessage } from "../api/client";
import { cn } from "../lib/utils";
import { isElectronRuntime } from "../lib/electronRuntime";
import {
  buildUnsupportedFilesMessage,
  buildImageParserUnavailableMessage,
  FILE_ACCEPT,
  extractPasteFiles,
  IMAGE_UPLOAD_PARSER_UNAVAILABLE_TITLE,
  partitionUploadFilesForRuntime,
} from "../lib/fileUpload";
import { resolveFileProcessingLabel } from "../components/knowledge-docs/utils";
import { notifyCoursesImported } from "../lib/courseEvents";
import { buildCoursePath } from "../lib/courseNavigation";
import { HeroAnimation } from "../components/ui/HeroAnimation";
import { FullPageDropOverlay } from "../components/ui/FullPageDropOverlay";
import { CourseExportModal } from "../components/course/CourseExportModal";
import { useToast } from "../components/ui/Toast";
import {
  ChatModelSelect,
  toChatRequestModel,
  useGlobalChatModelChoice,
} from "../components/chat/ChatModelSelect";
import type { FileRecord, FilesData, FilesUploadData } from "../types/files";

/* ── API helpers (same as BuildPlanPage) ── */

interface ApiResponse<T> { code: number; data: T; }

interface CourseItem {
  course_id: string;
  name: string;
  description?: string;
  user_intent?: string;
  icon_key?: string | null;
  created_at: string;
  updated_at: string;
}

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
    course_id: null,
    total: 0,
    ready_count: 0,
    processing_count: 0,
    failed_count: 0,
    items: [],
  };
}

async function linkFilesToCourse(course: string, fileIds: string[]): Promise<FilesData> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "POST",
    url: `/api/v1/courses/${course}/files/link`,
    data: { file_ids: fileIds },
  });
  return response.data;
}

/* ── Export / Import API helpers ── */

interface ImportResultData {
  course_id: string;
  course_name: string;
  imported_counts: Record<string, number>;
  warnings: string[];
}

/* ── Demo courses API ── */

interface CoursePackageItem {
  filename: string;
  course_name: string;
  file_size_bytes: number;
  exported_at: string | null;
  stats: Record<string, number>;
}

async function fetchDemoCourses(): Promise<CoursePackageItem[]> {
  const response = await apiClient<ApiResponse<CoursePackageItem[]>>({
    method: "GET",
    url: `/api/v1/demo-courses`,
  });
  return response.data;
}

async function importDemoCourse(filename: string, newName?: string): Promise<ImportResultData> {
  const response = await apiClient<ApiResponse<ImportResultData>>({
    method: "POST",
    url: `/api/v1/demo-courses/${encodeURIComponent(filename)}/import`,
    data: newName ? { new_course_name: newName } : {},
    timeout: LONG_RUNNING_API_TIMEOUT_MS,
  });
  return response.data;
}
/* ── Helpers ── */

async function createDraftCourse(): Promise<CourseItem> {
  const response = await apiClient<ApiResponse<CourseItem>>({
    method: "POST",
    url: `/api/v1/courses/draft`,
    data: {},
  });
  return response.data;
}

const HOME_ENTRY_FILES_QUERY_KEY = (fileIds: string[]) => ["home-entry-files", fileIds.join(",")] as const;

const HOME_PROMPT_STARTERS = [
  {
    id: "middle-school-math",
    label: "初中数学",
    prompt: "构建一门初中数学函数复习课，覆盖函数图像、一次函数、二次函数和常见易错题，配套概念讲解、例题和练习。",
    icon: BookOpen,
  },
  {
    id: "high-school-physics",
    label: "高中物理",
    prompt: "生成一门高中物理力学入门课，从受力分析、牛顿定律到列式解题逐步展开，重点讲清公式适用条件和典型题型。",
    icon: Target,
  },
  {
    id: "college-calculus",
    label: "大学高数",
    prompt: "制定大学高数期末复习课程，系统梳理极限、导数和积分，突出核心概念、常见题型和容易混淆的解题方法。",
    icon: ClipboardList,
  },
  {
    id: "python-basics",
    label: "Python入门",
    prompt: "生成一门 Python 入门课程，从变量、条件判断、循环和函数开始，每节包含代码示例、动手练习和常见错误说明。",
    icon: FileCode,
  },
] as const;

const HOME_FILE_PROMPT_STARTERS = [
  {
    id: "files-high-school-chemistry",
    label: "高中化学",
    prompt: "基于上传的化学复习资料，提炼考试重点，整理常见易混概念和高频题型，生成适合考前复习的课程结构。",
    icon: BookOpen,
  },
  {
    id: "files-linear-algebra",
    label: "大学线代",
    prompt: "基于上传的线性代数课件，按学习顺序整理课程路线，重点讲清矩阵、方程组、向量空间和特征值之间的关系。",
    icon: Target,
  },
  {
    id: "files-marxism-basics",
    label: "大学马原",
    prompt: "基于上传的马原资料，按章节生成考前复习课程，重点区分唯物论、辩证法、认识论和历史观等容易混淆的内容。",
    icon: ClipboardList,
  },
  {
    id: "files-computer-basics",
    label: "计算机基础",
    prompt: "基于上传的计算机基础资料，整理一条入门学习路线，串联操作系统、网络、数据库和程序设计的核心概念。",
    icon: CalendarCheck,
  },
] as const;

const HOME_PROMPT_TEMPLATE_TEXTS = new Set<string>(
  [...HOME_PROMPT_STARTERS, ...HOME_FILE_PROMPT_STARTERS].map((starter) => starter.prompt),
);

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
  if (["md", "markdown"].includes(ext)) return <FileCode className="h-3.5 w-3.5 text-indigo-400" />;
  if (["docx", "doc"].includes(ext)) return <FileText className="h-3.5 w-3.5 text-indigo-400" />;
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
    icon: <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-500" />,
    tone: "text-indigo-600",
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
        role="dialog"
        aria-modal="true"
        aria-label="从资料库选择"
        className="relative z-10 flex h-[82vh] max-h-[920px] w-[640px] max-w-full flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-900"
      >
        <div className="flex shrink-0 items-center justify-between border-b border-slate-100 px-5 py-4 dark:border-slate-800/80">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-900 text-white shadow-sm dark:bg-slate-100 dark:text-slate-900">
              <FolderOpen className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">从资料库选择</h3>
              <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">把已有资料加入这次新建课程</p>
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

        <div className="shrink-0 border-b border-slate-100 px-5 py-3 dark:border-slate-800/80">
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

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
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
                  <button
                    type="button"
                    key={file.id}
                    role="checkbox"
                    aria-checked={checked}
                    onClick={() => toggleFileId(file.id)}
                    className={cn(
                      "flex w-full cursor-pointer items-center gap-3 rounded-xl border px-3 py-3 text-left transition",
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
                  </button>
                );
              })}
            </div>
          ) : null}
        </div>

        <div className="flex shrink-0 items-center justify-between gap-3 border-t border-slate-100 bg-slate-50/70 px-5 py-4 dark:border-slate-800/80 dark:bg-slate-900">
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

/* ── Rename Modal ── */

function RenameModal({
  courseId,
  initialName,
  onClose,
  onSuccess,
}: {
  courseId: string;
  initialName: string;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [name, setName] = useState(initialName);

  const renameMutation = useMutation({
    mutationFn: async () => {
      await apiClient({
        method: "POST",
        url: `/api/v1/courses/update`,
        data: { course_id: courseId, name: name.trim() },
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
          <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">重命名课程</h3>
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
            placeholder="输入课程名称"
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
                ? "bg-slate-900 text-white shadow-sm hover:bg-slate-800 hover:shadow-md dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
                : "cursor-not-allowed bg-slate-200 text-slate-400 dark:bg-slate-800 dark:text-slate-600"
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

  const [prompt, setPrompt] = useState("");
  const [draftCourseId, setDraftCourseId] = useState<string | null>(null);
  const [isCreatingDraftCourse, setIsCreatingDraftCourse] = useState(false);
  const [isStartingBuild, setIsStartingBuild] = useState(false);
  const [isUploadingFiles, setIsUploadingFiles] = useState(false);
  const [uploadingFileNames, setUploadingFileNames] = useState<string[]>([]);
  const [entryFileIds, setEntryFileIds] = useState<string[]>([]);
  const [chatModel, setChatModel] = useGlobalChatModelChoice();
  const [recentOpen, setRecentOpen] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demoCourseError, setDemoCourseError] = useState<string | null>(null);

  // Modal state
  const [exportCourseId, setExportCourseId] = useState<string | null>(null);
  const [libraryPickerOpen, setLibraryPickerOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<{ id: string; name: string } | null>(null);
  const newEntryAt = (location.state as { newEntryAt?: number } | null)?.newEntryAt;

  useEffect(() => {
    if (!newEntryAt) {
      return;
    }
    setPrompt("");
    setDraftCourseId(null);
    setIsCreatingDraftCourse(false);
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
  const { data: courses = [] } = useQuery({
    queryKey: ["available-demo-courses"],
    queryFn: fetchDemoCourses,
    retry: false,
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: "always",
  });

  const courseImportMutation = useMutation({
    mutationFn: ({ filename, newName }: { filename: string; newName?: string }) =>
      importDemoCourse(filename, newName),
    onSuccess: (result) => {
      setDemoCourseError(null);
      notifyCoursesImported({ courseId: result.course_id });
      queryClient.invalidateQueries({ queryKey: ["courses"] });
      const warning = result.warnings.find((item) => item.trim())?.trim();
      toast({
        title: warning ? "导入成功，有提示" : "导入成功",
        description: warning
          ? `${result.course_name} 已加入左侧课程列表。${warning}`
          : `${result.course_name} 已加入左侧课程列表。`,
        variant: warning ? "warning" : "success",
        duration: warning ? 8000 : undefined,
      });
    },
    onError: (err: unknown) => {
      const message = getApiErrorMessage(err, "演示课程导入失败");
      setDemoCourseError(message);
      void queryClient.invalidateQueries({ queryKey: ["available-demo-courses"] });
      toast({
        title: "导入失败",
        description: message,
        variant: "error",
      });
    },
  });

  const ensureDraftCourseId = useCallback(async () => {
    if (draftCourseId) {
      return draftCourseId;
    }
    setIsCreatingDraftCourse(true);
    try {
      const created = await createDraftCourse();
      if (!created) {
        throw new Error("创建课程失败");
      }
      setDraftCourseId(created.course_id);
      void queryClient.invalidateQueries({ queryKey: ["courses"] });
      return created.course_id;
    } catch (err: unknown) {
      const message = getApiErrorMessage(err, "创建课程失败，请重试");
      setError(message);
      throw new Error(message);
    } finally {
      setIsCreatingDraftCourse(false);
    }
  }, [draftCourseId, queryClient]);

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
        course_id: null,
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
    const { supportedFiles, unsupportedFiles, imageParserUnavailableFiles, limitExceededMessage } =
      await partitionUploadFilesForRuntime(files);
    const unsupportedMessage = unsupportedFiles.length
      ? buildUnsupportedFilesMessage(unsupportedFiles)
      : null;
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
    setIsUploadingFiles(true);
    setUploadingFileNames(supportedFiles.map((file) => file.name));
    try {
      const result = await uploadFiles(supportedFiles);
      const uploaded = result.uploaded_items ?? [];
      const uploadedIds = uploaded.map((file) => file.id);
      const nextFileIds = uniqueStrings([...entryFileIds, ...uploadedIds]);
      setEntryFileIds(nextFileIds);
      syncEntryFilesCache(nextFileIds, uploaded);
      void queryClient.invalidateQueries({ queryKey: HOME_ENTRY_FILES_QUERY_KEY(nextFileIds) });
      void queryClient.invalidateQueries({ queryKey: ["files-library"] });
    } catch (err: unknown) {
      setError(getApiErrorMessage(err, "文件上传失败"));
    } finally {
      setIsUploadingFiles(false);
      setUploadingFileNames([]);
    }
  }, [entryFileIds, queryClient, syncEntryFilesCache, toast]);

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
    if (isCreatingDraftCourse) {
      return "正在创建课程，并关联已选择资料。";
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
  }, [entryFilesData?.failed_count, entryFilesData?.processing_count, entryFilesData?.ready_count, hasEntryFiles, isCreatingDraftCourse, isUploadingFiles, uploadedFiles]);
  const canGenerate = prompt.trim().length > 0 || hasEntryFiles;

  const handleGenerate = async () => {
    if (!canGenerate) return;
    setError(null);
    setIsStartingBuild(true);
    try {
      const courseId = await ensureDraftCourseId();
      if (entryFileIds.length > 0) {
        await linkFilesToCourse(courseId, entryFileIds);
        void queryClient.invalidateQueries({ queryKey: ["courses"] });
        void queryClient.invalidateQueries({ queryKey: ["files", courseId] });
      }
      const userGoal = prompt.trim() || "请基于我选择的资料，直接生成一份课程构建规划。";
      const selectedModel = toChatRequestModel(chatModel);
      navigate(buildCoursePath(courseId, "build"), {
        state: { initialPrompt: userGoal, autoStart: true, entrySource: "home_arrow", model: selectedModel },
      });
    } catch {
      // ensureDraftCourseId already writes user-facing error.
    } finally {
      setIsStartingBuild(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleGenerate();
    }
  };

  const handlePromptStarterClick = useCallback((starterPrompt: string) => {
    const currentPrompt = prompt.trim();
    const nextPrompt = currentPrompt
      ? HOME_PROMPT_TEMPLATE_TEXTS.has(currentPrompt)
        ? starterPrompt
        : currentPrompt.includes(starterPrompt)
          ? currentPrompt
          : `${prompt.trimEnd()}\n\n${starterPrompt}`
      : starterPrompt;

    setPrompt(nextPrompt);
    setError(null);
    window.requestAnimationFrame(() => {
      const textarea = textareaRef.current;
      if (!textarea) {
        return;
      }
      textarea.focus();
      textarea.setSelectionRange(nextPrompt.length, nextPrompt.length);
    });
  }, [prompt]);

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

  const isWorking = isCreatingDraftCourse || isStartingBuild || isUploadingFiles;
  const shouldShowDemoCourseSection = courses.length > 0;
  const activePromptStarters = hasEntryFiles ? HOME_FILE_PROMPT_STARTERS : HOME_PROMPT_STARTERS;
  const generateButtonLabel = isWorking
    ? "正在处理学习规划"
    : canGenerate
      ? "开始规划学习课程"
      : "输入学习目标或选择资料后开始规划";

  return (
    <>
    <FullPageDropOverlay
      onDrop={(droppedFiles) => {
        handleFileDrop(droppedFiles);
      }}
      disabled={isWorking || Boolean(exportCourseId) || libraryPickerOpen || Boolean(renameTarget)}
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
          "relative z-20 flex w-full max-w-[800px] flex-col items-center",
          shouldShowDemoCourseSection
            ? "min-h-[54dvh] justify-end pb-8 pt-8 md:min-h-[58dvh] md:pb-10"
            : "min-h-[calc(100dvh-9rem)] translate-y-[8vh] justify-center md:translate-y-[11vh]",
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
          className="mb-8 px-4 text-center text-base leading-relaxed text-zinc-500 dark:text-slate-400"
        >
          让天下没有难学的课程
        </motion.p>

        {/* ── Unified Input Area ── */}
        <motion.div
          initial={{ opacity: 0, scale: 0.97 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.35 }}
          className="w-full relative z-10"
        >
          <div className={cn(
            "w-full overflow-hidden rounded-3xl border bg-white transition-all dark:bg-slate-950",
            hasEntryFiles
              ? "border-slate-300 shadow-[0_18px_42px_rgba(15,23,42,0.08)] dark:border-slate-700"
              : "border-slate-200 shadow-[0_18px_42px_rgba(15,23,42,0.07)] hover:border-slate-300 dark:border-slate-800 dark:hover:border-slate-700",
            "focus-within:border-indigo-300 focus-within:shadow-[0_20px_54px_rgba(99,102,241,0.16)] focus-within:ring-4 focus-within:ring-indigo-500/10 dark:focus-within:border-indigo-500/50 dark:focus-within:shadow-[0_20px_54px_rgba(99,102,241,0.22)]"
          )}>
            <textarea
              ref={textareaRef}
              placeholder={"输入学习目标或课程主题\n可以说明考试范围、当前基础、重点章节；有课件、讲义、教材也可以直接上传。"}
              className="w-full min-h-[148px] max-h-[320px] resize-none border-0 bg-transparent px-5 pb-3 pt-5 text-[15px] leading-7 text-zinc-900 focus:outline-none placeholder:text-zinc-400 dark:text-slate-100 dark:placeholder:text-slate-500 sm:min-h-[156px] sm:px-6 sm:pt-6"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              rows={3}
              disabled={isCreatingDraftCourse}
            />

            <div className="flex flex-col gap-2 px-4 pb-3 pt-2 sm:px-5">
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
                          aria-label={`从本次新建中移除 ${file.filename}`}
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
                      <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-indigo-500" />
                    </div>
                  ))}
                  </div>
                  {entryFilesStatusText ? (
                    <p className="px-1 text-xs leading-5 text-zinc-500">{entryFilesStatusText}</p>
                  ) : null}
                </div>
              )}

              <div className="flex flex-col gap-2 px-1 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex min-w-0 w-full flex-wrap items-center gap-1.5 sm:flex-1 sm:gap-2">
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
                    disabled={isWorking}
                    aria-label={isUploadingFiles || isCreatingDraftCourse ? "正在上传资料" : "上传资料"}
                    title={isUploadingFiles || isCreatingDraftCourse ? "正在上传资料" : "上传资料"}
                    className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 focus:outline-none focus:ring-2 focus:ring-zinc-900/10 disabled:cursor-not-allowed disabled:opacity-60 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200 dark:focus:ring-slate-100/10"
                  >
                    {isUploadingFiles ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Paperclip className="h-3.5 w-3.5" />
                    )}
                    <span>{isUploadingFiles ? "上传中" : "上传"}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setLibraryPickerOpen(true)}
                    disabled={isWorking}
                    className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 focus:outline-none focus:ring-2 focus:ring-zinc-900/10 disabled:cursor-not-allowed disabled:opacity-60 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200 dark:focus:ring-slate-100/10"
                    aria-label="从资料库选择"
                    title="从我的资料库选择已有文件"
                  >
                    <FolderOpen className="h-3.5 w-3.5" />
                    <span>资料库</span>
                  </button>
                  {isWorking && (
                    <span className="ml-2 flex items-center text-xs font-medium text-zinc-500">
                      <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                      {isStartingBuild || isCreatingDraftCourse ? "正在创建课程..." : "正在上传并解析资料..."}
                    </span>
                  )}
                </div>

                <div className="flex w-full items-center justify-between gap-2 sm:w-auto sm:shrink-0 sm:justify-end">
                  <ChatModelSelect
                    value={chatModel}
                    onChange={setChatModel}
                    disabled={isWorking}
                    className="flex-1 sm:flex-none sm:w-[128px]"
                  />
                  <button
                    type="button"
                    onClick={() => void handleGenerate()}
                    disabled={!canGenerate || isWorking}
                    aria-label={generateButtonLabel}
                    title={generateButtonLabel}
                    className={cn(
                      "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition-all focus:outline-none focus:ring-2 focus:ring-zinc-900/10 active:scale-[0.98]",
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

          <div className="mt-3 w-full px-2">
            <div className="mb-1 flex items-center gap-3 text-[11px] font-medium text-zinc-400 dark:text-slate-500">
              <span className="h-px flex-1 bg-gradient-to-r from-transparent via-zinc-200 to-zinc-200/60 dark:via-slate-800 dark:to-slate-800/60" />
              <span>{hasEntryFiles ? "基于资料的完整提示模板" : "完整提示模板"}</span>
              <span className="h-px flex-1 bg-gradient-to-l from-transparent via-zinc-200 to-zinc-200/60 dark:via-slate-800 dark:to-slate-800/60" />
            </div>
            <div className="divide-y divide-zinc-200/60 dark:divide-slate-800/70">
              {activePromptStarters.map((starter, index) => {
                return (
                  <button
                    key={starter.id}
                    type="button"
                    onClick={() => handlePromptStarterClick(starter.prompt)}
                    disabled={isWorking}
                    aria-label={`套用${starter.label}提示模板`}
                    title={starter.prompt}
                    className="group relative flex w-full items-baseline gap-2 py-2 pl-1 pr-3 text-left transition-colors hover:bg-transparent focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/15 disabled:cursor-not-allowed disabled:opacity-55"
                  >
                    <span className="absolute left-0 top-2 h-[calc(100%-16px)] w-px bg-indigo-400 opacity-0 transition-opacity group-hover:opacity-100 dark:bg-indigo-300" />
                    <span className="w-5 shrink-0 pl-2 font-mono text-[10px] font-semibold text-zinc-300 tabular-nums transition-colors group-hover:text-indigo-400 dark:text-slate-600 dark:group-hover:text-indigo-300">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <span className="shrink-0 text-sm font-semibold text-zinc-800 transition-colors group-hover:text-indigo-700 dark:text-slate-100 dark:group-hover:text-indigo-200">
                      {starter.label}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[13px] leading-6 text-zinc-500 transition-colors group-hover:text-zinc-800 dark:text-slate-400 dark:group-hover:text-slate-200">
                      {starter.prompt}
                    </span>
                  </button>
                );
              })}
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
          className="relative z-10 mt-4 w-full max-w-5xl flex flex-col items-center"
        >
          {/* Section Toggle */}
          <button
            type="button"
            onClick={() => setRecentOpen(!recentOpen)}
            aria-expanded={recentOpen}
            aria-controls="home-demo-courses"
            className="group flex w-full cursor-pointer items-center gap-4 py-3"
          >
            <div className="flex-1 h-[1px] bg-zinc-200 group-hover:bg-zinc-300 transition-colors dark:bg-slate-800 dark:group-hover:bg-slate-700" />
            <span className="flex shrink-0 select-none items-center gap-2 text-[13px] font-semibold tracking-tight text-zinc-400 transition-colors group-hover:text-zinc-800 dark:text-slate-500 dark:group-hover:text-slate-300">
              <Package className="h-4 w-4" />
              演示课程
              <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[12px] text-zinc-500 shadow-[inset_0_1px_2px_rgba(0,0,0,0.02)] dark:bg-slate-800 dark:text-slate-400">{courses.length}</span>
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
                id="home-demo-courses"
                className="w-full overflow-hidden"
              >
                <div className="pt-6 pb-12">
                  {demoCourseError ? (
                    <div className="mb-4 rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-center text-sm font-medium text-red-600">
                      {demoCourseError}
                    </div>
                  ) : null}
                  {courses.length > 0 && (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                        {courses.map((course, i) => (
                          <motion.div
                            key={course.filename}
                            initial={{ opacity: 0, y: 16 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: i * 0.05, duration: 0.35, ease: "easeOut" }}
                          >
                            <div className="atm-deferred-card flex h-full flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:border-slate-300 hover:shadow-md dark:border-slate-800 dark:bg-slate-900/80 dark:hover:border-slate-700">
                              <div className="flex items-start justify-between mb-3">
                                <div className="flex-1 mr-3">
                                  <h3 className="line-clamp-1 text-lg font-bold text-slate-900 dark:text-slate-100">{course.course_name}</h3>
                                  <p className="mt-1 text-xs font-medium text-indigo-600 dark:text-indigo-300">演示课程</p>
                                </div>
                                <div className="rounded-lg border border-indigo-100 bg-gradient-to-br from-indigo-50 to-violet-50 p-2 dark:border-indigo-500/20 dark:from-indigo-500/10 dark:to-violet-500/10">
                                  <Package className="w-5 h-5 text-indigo-500" />
                                </div>
                              </div>

                              {/* Stats chips */}
                              <div className="flex flex-wrap gap-1.5 mb-4">
                                {course.stats.knowledge_unit_count > 0 && (
                                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                                    {course.stats.knowledge_unit_count} 知识点
                                  </span>
                                )}
                                {course.stats.raw_file_count > 0 && (
                                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                                    {course.stats.raw_file_count} 文件
                                  </span>
                                )}
                                {course.file_size_bytes > 0 && (
                                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                                    {formatFileSize(course.file_size_bytes)}
                                  </span>
                                )}
                              </div>

                              {/* Footer */}
                              <div className="mt-auto border-t border-slate-100 pt-3 dark:border-slate-800">
                                <button
                                  onClick={() => courseImportMutation.mutate({ filename: course.filename })}
                                  disabled={courseImportMutation.isPending}
                                  className={cn(
                                    "flex min-h-9 w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-bold transition-all",
                                    !courseImportMutation.isPending
                                      ? "bg-slate-900 text-white shadow-sm hover:bg-slate-800 hover:shadow-md dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
                                      : "cursor-not-allowed bg-slate-200 text-slate-400 dark:bg-slate-800 dark:text-slate-600"
                                  )}
                                  title={`导入 ${course.course_name} 到左侧课程列表`}
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
      {exportCourseId && (
        <CourseExportModal
          key="export"
          courseId={exportCourseId}
          onClose={() => setExportCourseId(null)}
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
          courseId={renameTarget.id}
          initialName={renameTarget.name}
          onClose={() => setRenameTarget(null)}
          onSuccess={() => queryClient.invalidateQueries({ queryKey: ["courses"] })}
        />
      )}
    </AnimatePresence>
    </>
  );
}
