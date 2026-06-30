import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertCircle,
  ArrowUp,
  Atom,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  ClipboardList,
  Code2,
  Calculator,
  ChartScatter,
  FileCode,
  FileImage,
  FolderOpen,
  Loader2,
  MessageCircle,
  FileText,
  FileType,
  Paperclip,
  RefreshCw,
  Search,
  Sparkles,
  X,
  FileUp,
  Package,
  Sigma,
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
import { AI_SCENE_HOME_INTAKE, useAiInteraction } from "../components/interaction";
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
    prompt: "我想构建一门初中数学函数复习课，覆盖一次函数、反比例函数、二次函数、函数图像、解析式和应用题。",
    icon: BookOpen,
  },
  {
    id: "high-school-physics",
    label: "高中物理",
    prompt: "我想构建一门高中物理力学基础课，覆盖运动学、受力分析、牛顿运动定律、功和能量、动量守恒。",
    icon: Target,
  },
  {
    id: "college-calculus",
    label: "大学高数",
    prompt: "我想构建一门大学高数期末复习课，覆盖极限、导数、中值定理、不定积分、定积分和定积分应用。",
    icon: ClipboardList,
  },
  {
    id: "python-basics",
    label: "Python入门",
    prompt: "我想构建一门 Python 数据处理入门课，覆盖变量、分支循环、函数、列表字典、文件读写、异常处理和 CSV 数据处理。",
    icon: FileCode,
  },
] as const;

const HOME_FILE_PROMPT_STARTERS = [
  {
    id: "files-computer-basics",
    label: "计算机资料",
    prompt: "根据我上传的计算机相关资料，整理出一门覆盖全面、结构清晰、适合系统复习的课程。",
    icon: BookOpen,
  },
  {
    id: "files-final-review",
    label: "期末复习",
    prompt: "根据我上传的课件和题库，按章节整理一门期末复习课，重点覆盖老师划定的考试范围。",
    icon: ClipboardList,
  },
  {
    id: "files-foundation-course",
    label: "基础补课",
    prompt: "根据我上传的资料，帮我整理出从基础概念到核心章节的学习课程，内容要详细、有层次。",
    icon: Target,
  },
  {
    id: "files-course-outline",
    label: "资料成课",
    prompt: "根据我上传的课程资料，提炼主要知识点并整理成一门适合考前复习的课程。",
    icon: FileText,
  },
] as const;

const HOME_COURSE_TYPING_EXAMPLES = [
  "我想系统复习大学高数，范围包括极限、导数、中值定理、不定积分、定积分和应用。",
  "我想构建一门高中物理力学补基础课，覆盖运动学、受力分析、牛顿运动定律、功和能量。",
  "我想复习计算机基础，覆盖操作系统、计算机网络、数据库、数据结构和程序设计。",
  "我想学 Python 数据处理，覆盖变量、分支循环、函数、列表字典、文件读写和 CSV 数据处理。",
] as const;

const HOME_FILE_TYPING_EXAMPLES = [
  "根据我上传的计算机相关资料，整理出一门覆盖全面、结构清晰、适合系统复习的课程。",
  "根据我上传的课件和题库，按章节整理一门期末复习课，重点覆盖老师划定的考试范围。",
  "根据我上传的资料，帮我整理出从基础概念到核心章节的学习课程，内容要详细、有层次。",
  "根据我上传的课程资料，提炼主要知识点并整理成一门适合考前复习的课程。",
] as const;

const HOME_CHAT_PROMPT_STARTERS = [
  {
    id: "chat-study-diagnosis",
    label: "诊断建课",
    prompt: "我想做一门计算机基础冲刺课，但还没想清楚范围；先问我几个问题，帮我整理清楚要学哪些内容。",
    icon: Target,
  },
  {
    id: "chat-material-course",
    label: "资料转课",
    prompt: "我上传了课程资料，但不知道适合做成什么课；先帮我判断资料里主要覆盖哪些知识。",
    icon: BookOpen,
  },
  {
    id: "chat-exam-strategy",
    label: "考试冲刺",
    prompt: "距离高数期末还有三天，范围到定积分应用；先帮我确认应该重点复习哪些知识。",
    icon: ClipboardList,
  },
  {
    id: "chat-concept-course",
    label: "补课方案",
    prompt: "我想把线性代数里的矩阵、行列式和特征值补成一门小课；先帮我确认需要覆盖哪些内容。",
    icon: MessageCircle,
  },
] as const;

const HOME_CHAT_WITH_FILES_DEFAULT_PROMPT =
  "我已经选择了这些资料，请先帮我判断适合建成什么课，并和我确认后再开始构建。";

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

const DEMO_COURSE_ACCENTS = [
  {
    shell: "border-indigo-100 bg-gradient-to-br from-white via-white to-indigo-50/70 hover:border-indigo-300 hover:shadow-indigo-200/40 dark:border-indigo-500/20 dark:from-slate-950 dark:via-slate-950 dark:to-indigo-950/30 dark:hover:border-indigo-400/40",
    icon: "border-indigo-100 bg-indigo-50 text-indigo-600 dark:border-indigo-400/20 dark:bg-indigo-400/10 dark:text-indigo-300",
    strip: "from-indigo-500 via-sky-400 to-violet-400",
  },
  {
    shell: "border-cyan-100 bg-gradient-to-br from-white via-white to-cyan-50/70 hover:border-cyan-300 hover:shadow-cyan-200/40 dark:border-cyan-500/20 dark:from-slate-950 dark:via-slate-950 dark:to-cyan-950/25 dark:hover:border-cyan-400/40",
    icon: "border-cyan-100 bg-cyan-50 text-cyan-700 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-300",
    strip: "from-cyan-500 via-emerald-400 to-sky-400",
  },
  {
    shell: "border-violet-100 bg-gradient-to-br from-white via-white to-violet-50/70 hover:border-violet-300 hover:shadow-violet-200/40 dark:border-violet-500/20 dark:from-slate-950 dark:via-slate-950 dark:to-violet-950/30 dark:hover:border-violet-400/40",
    icon: "border-violet-100 bg-violet-50 text-violet-600 dark:border-violet-400/20 dark:bg-violet-400/10 dark:text-violet-300",
    strip: "from-violet-500 via-fuchsia-400 to-indigo-400",
  },
] as const;

function getDemoCourseTheme(courseName: string, index: number) {
  const accent = DEMO_COURSE_ACCENTS[index % DEMO_COURSE_ACCENTS.length];
  if (/Python|C语言|编程|程序|代码/i.test(courseName)) {
    return { ...accent, icon: Code2 };
  }
  if (/概率|统计|数理统计/.test(courseName)) {
    return { ...DEMO_COURSE_ACCENTS[1], icon: ChartScatter };
  }
  if (/物理|力学|牛顿|受力/.test(courseName)) {
    return { ...DEMO_COURSE_ACCENTS[1], icon: Atom };
  }
  if (/线性代数|矩阵|行列式|特征值/.test(courseName)) {
    return { ...DEMO_COURSE_ACCENTS[2], icon: Sigma };
  }
  if (/高等数学|高数|微积分|极限|导数|积分/.test(courseName)) {
    return { ...DEMO_COURSE_ACCENTS[0], icon: Calculator };
  }
  return { ...accent, icon: BookOpen };
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
  onUploadRequest,
}: {
  selectedFileIds: string[];
  onClose: () => void;
  onConfirm: (fileIds: string[], files: FileRecord[]) => void;
  onUploadRequest: () => void;
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
    if (selectedCount === 0 || filesQuery.isLoading) {
      return;
    }
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
              <button
                type="button"
                onClick={onUploadRequest}
                className="mt-4 inline-flex min-h-10 items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-900/15 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white dark:focus:ring-slate-100/15"
              >
                <FileUp className="h-4 w-4" />
                上传资料
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
              disabled={filesQuery.isLoading || selectedCount === 0}
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
  const { openAiInteraction } = useAiInteraction();
  const isElectron = isElectronRuntime();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const [prompt, setPrompt] = useState("");
  const [typedCourseExample, setTypedCourseExample] = useState("");
  const [draftCourseId, setDraftCourseId] = useState<string | null>(null);
  const [isCreatingDraftCourse, setIsCreatingDraftCourse] = useState(false);
  const [isStartingBuild, setIsStartingBuild] = useState(false);
  const [isUploadingFiles, setIsUploadingFiles] = useState(false);
  const [uploadingFileNames, setUploadingFileNames] = useState<string[]>([]);
  const [entryFileIds, setEntryFileIds] = useState<string[]>([]);
  const [entryMode, setEntryMode] = useState<"course" | "chat">("course");
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
    setEntryMode("course");
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
  const {
    data: courses = [],
    isLoading: demoCoursesLoading,
    isFetching: demoCoursesFetching,
  } = useQuery({
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
    if (!canGenerate || isWorking) return;
    setError(null);
    const selectedModel = toChatRequestModel(chatModel);
    if (entryMode === "chat") {
      const chatDraft = prompt.trim() || (entryFileIds.length > 0 ? HOME_CHAT_WITH_FILES_DEFAULT_PROMPT : "");
      openAiInteraction({
        mode: "fullscreen",
        scope: { type: "global" },
        draft: chatDraft,
        autoSend: chatDraft.length > 0,
        model: selectedModel,
        scene: AI_SCENE_HOME_INTAKE,
        source: AI_SCENE_HOME_INTAKE,
        attachedFileIds: entryFileIds,
        newSession: true,
      });
      return;
    }

    setIsStartingBuild(true);
    try {
      const courseId = await ensureDraftCourseId();
      if (entryFileIds.length > 0) {
        await linkFilesToCourse(courseId, entryFileIds);
        void queryClient.invalidateQueries({ queryKey: ["courses"] });
        void queryClient.invalidateQueries({ queryKey: ["files", courseId] });
      }
      const userGoal = prompt.trim() || "请基于我选择的资料，直接生成一份课程构建规划。";
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
      if (isWorking) return;
      void handleGenerate();
    }
  };

  const handlePromptStarterClick = useCallback((starterPrompt: string) => {
    setError(null);
    const textarea = textareaRef.current;
    if (!textarea || typeof document === "undefined" || typeof document.execCommand !== "function") {
      setPrompt(starterPrompt);
      window.requestAnimationFrame(() => {
        const currentTextarea = textareaRef.current;
        if (!currentTextarea) {
          return;
        }
        currentTextarea.focus();
        currentTextarea.setSelectionRange(starterPrompt.length, starterPrompt.length);
      });
      return;
    }

    textarea.focus();
    textarea.setSelectionRange(0, textarea.value.length);
    // Native insertion keeps template replacement in the browser undo stack.
    let appliedWithUndo = false;
    try {
      appliedWithUndo = document.execCommand("insertText", false, starterPrompt);
    } catch {
      appliedWithUndo = false;
    }
    if (!appliedWithUndo) {
      setPrompt(starterPrompt);
      window.requestAnimationFrame(() => {
        const currentTextarea = textareaRef.current;
        if (!currentTextarea) {
          return;
        }
        currentTextarea.focus();
        currentTextarea.setSelectionRange(starterPrompt.length, starterPrompt.length);
      });
      return;
    }
    setPrompt(starterPrompt);
    textarea.setSelectionRange(starterPrompt.length, starterPrompt.length);
  }, []);

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

  const handleLibraryUploadRequest = useCallback(() => {
    setLibraryPickerOpen(false);
    window.requestAnimationFrame(() => fileInputRef.current?.click());
  }, []);

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
  const shouldReserveDemoCourseSection = shouldShowDemoCourseSection || demoCoursesLoading || demoCoursesFetching;
  const isCourseEntryMode = entryMode === "course";
  const activePromptStarters = isCourseEntryMode
    ? hasEntryFiles ? HOME_FILE_PROMPT_STARTERS : HOME_PROMPT_STARTERS
    : HOME_CHAT_PROMPT_STARTERS;
  useEffect(() => {
    if (!isCourseEntryMode || prompt.length > 0 || isWorking) {
      setTypedCourseExample("");
      return;
    }

    const examples = hasEntryFiles ? HOME_FILE_TYPING_EXAMPLES : HOME_COURSE_TYPING_EXAMPLES;
    if (typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setTypedCourseExample(examples[0] ?? "");
      return;
    }

    let exampleIndex = 0;
    let charIndex = 0;
    let holdTicks = 0;
    let phase: "typing" | "holding" | "deleting" = "typing";

    const timer = window.setInterval(() => {
      const current = examples[exampleIndex % examples.length] ?? "";
      if (!current) return;

      if (phase === "typing") {
        charIndex = Math.min(current.length, charIndex + 1);
        setTypedCourseExample(`${current.slice(0, charIndex)}|`);
        if (charIndex >= current.length) {
          phase = "holding";
          holdTicks = 0;
        }
        return;
      }

      if (phase === "holding") {
        holdTicks += 1;
        setTypedCourseExample(`${current}|`);
        if (holdTicks >= 22) phase = "deleting";
        return;
      }

      charIndex = Math.max(0, charIndex - 1);
      setTypedCourseExample(charIndex > 0 ? `${current.slice(0, charIndex)}|` : "");
      if (charIndex <= 0) {
        exampleIndex += 1;
        phase = "typing";
      }
    }, 52);

    return () => window.clearInterval(timer);
  }, [hasEntryFiles, isCourseEntryMode, isWorking, prompt.length]);

  const coursePlaceholderExample = typedCourseExample || (hasEntryFiles
    ? "根据我上传的计算机相关资料，整理出一门覆盖全面、结构清晰、适合系统复习的课程。"
    : "大学高数期末复习课：范围包括极限、导数、中值定理、不定积分、定积分及应用。");
  const textareaPlaceholder = isCourseEntryMode
    ? hasEntryFiles
      ? `写下这门课要怎样构建\n例如：${coursePlaceholderExample}`
      : `写下你想构建的课程\n例如：${coursePlaceholderExample}`
    : hasEntryFiles
      ? "先和 AI 聊清楚课程方向\n例如：基于这些资料，帮我判断适合建成什么课、先学哪些章节、要配哪些练习。"
      : "先和 AITeachMe 聊清楚课程方向\n例如：我想做一门高数期末冲刺课，范围到定积分应用；先帮我确认目标、章节和练习安排。";
  const generateButtonLabel = isWorking
    ? isCourseEntryMode ? "正在进入课程规划" : "正在处理对话"
    : canGenerate
      ? isCourseEntryMode ? "开始构建课程" : "发送到对话"
      : isCourseEntryMode ? "填写课程目标或选择资料后开始构建" : "输入问题或选择资料后开始对话";
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
        "atm-home-surface relative flex w-full flex-col items-center overflow-x-clip p-4 pt-[clamp(5rem,7vh,6.5rem)] selection:bg-zinc-200 md:p-8 md:pt-[clamp(5.5rem,7vh,7.5rem)]",
        isElectron ? "min-h-full" : "min-h-[100dvh]",
      )}
    >
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: "easeOut" }}
        className={cn(
          "relative z-20 flex w-full max-w-[920px] flex-col items-center",
          shouldReserveDemoCourseSection
            ? "min-h-[clamp(560px,64dvh,680px)] justify-end pb-5 pt-5 md:min-h-[clamp(480px,62dvh,660px)] md:pb-6 md:pt-7"
            : "min-h-[calc(100dvh-9rem)] translate-y-[8vh] justify-center md:translate-y-[11vh]",
        )}
      >
        {/* ── Logo & Title ── */}
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.1, type: "spring", stiffness: 200, damping: 20 }}
          className="mb-1 flex flex-col items-center justify-center"
        >
          <HeroAnimation width={116} height={106} />
          <motion.div
            initial={{ opacity: 0, y: 10, filter: "blur(6px)" }}
            animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
            transition={{ duration: 0.7, ease: "easeOut", delay: 0.25 }}
            className="flex flex-col items-center mt-3"
          >
            <h1
              className="bg-gradient-to-r from-slate-900 via-indigo-700 to-violet-600 bg-clip-text text-[2.1rem] font-extrabold leading-none tracking-normal text-transparent animate-text-gradient dark:from-slate-100 dark:via-indigo-400 dark:to-violet-400 md:text-[2.6rem]"
              style={{
                backgroundSize: "200% auto",
                fontFamily:
                  '"Bahnschrift", "Aptos Display", "Segoe UI Variable Display", Inter, system-ui, sans-serif',
              }}
            >
              AITeachMe
            </h1>
          </motion.div>
        </motion.div>

        {/* ── Slogan ── */}
        <motion.p
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.45, duration: 0.5 }}
          className="mb-5 px-4 text-center text-base leading-relaxed text-zinc-500 dark:text-slate-400"
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
            <div className="flex flex-col gap-2 border-b border-slate-100 px-4 py-3 dark:border-slate-800 sm:flex-row sm:items-center sm:justify-between sm:px-5">
              <div className="inline-flex w-fit rounded-xl bg-slate-100 p-1 dark:bg-slate-900">
                {[
                  { key: "course" as const, label: "构建课程", icon: BookOpen },
                  { key: "chat" as const, label: "先聊再建课", icon: MessageCircle },
                ].map((item) => {
                  const ModeIcon = item.icon;
                  const active = entryMode === item.key;
                  return (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => setEntryMode(item.key)}
                      disabled={isWorking}
                      aria-pressed={active}
                      className={cn(
                        "inline-flex h-7 items-center gap-1.5 rounded-lg px-2.5 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60",
                        active
                          ? "bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-slate-100"
                          : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200",
                      )}
                    >
                      <ModeIcon className="h-3.5 w-3.5" />
                      {item.label}
                    </button>
                  );
                })}
              </div>
            </div>
            <textarea
              ref={textareaRef}
              aria-label={isCourseEntryMode ? "课程构建需求" : "自由对话输入"}
              placeholder={textareaPlaceholder}
              className="w-full min-h-[112px] max-h-[320px] resize-none border-0 bg-transparent px-5 pb-2 pt-5 text-[15px] leading-7 text-zinc-900 focus:outline-none placeholder:text-zinc-400 dark:text-slate-100 dark:placeholder:text-slate-500 sm:min-h-[120px] sm:px-7 sm:pt-6 sm:text-[16px]"
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
                    <span>{isUploadingFiles ? "上传中" : "上传资料"}</span>
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
                    <span>选资料</span>
                  </button>
                  {isWorking && (
                    <span className="ml-2 flex items-center text-xs font-medium text-zinc-500">
                      <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                      {isStartingBuild || isCreatingDraftCourse ? "正在进入课程规划..." : "正在上传并解析资料..."}
                    </span>
                  )}
                </div>

                <div className="flex w-full items-center justify-end gap-1.5 sm:w-auto sm:shrink-0">
                  <ChatModelSelect
                    value={chatModel}
                    onChange={setChatModel}
                    disabled={isWorking}
                    showBuildEstimate={isCourseEntryMode}
                    className={cn(
                      "flex-none",
                      isCourseEntryMode ? "w-[128px] sm:w-[132px]" : "w-[112px] sm:w-[112px]",
                    )}
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

          <div className="mt-3 w-full px-1">
            <div className="mb-2 flex items-center justify-center gap-2 text-[11px] font-medium text-zinc-400 dark:text-slate-500">
              <Sparkles className="h-3.5 w-3.5 text-indigo-400" />
              <span>{isCourseEntryMode ? hasEntryFiles ? "资料课程示例" : "课程需求示例" : "对话建课示例"}</span>
            </div>
            <div className="flex gap-2 overflow-x-auto pb-1.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
              {activePromptStarters.map((starter, index) => {
                const StarterIcon = starter.icon;
                return (
                  <button
                    key={starter.id}
                    type="button"
                    onClick={() => handlePromptStarterClick(starter.prompt)}
                    disabled={isWorking}
                    aria-label={`套用${starter.label}提示词示例`}
                    title={starter.prompt}
                    className="group relative flex min-w-[224px] flex-1 items-stretch gap-2 rounded-2xl border border-slate-200/70 bg-white/60 px-3.5 py-2.5 text-left shadow-[0_14px_32px_-30px_rgba(15,23,42,0.55)] backdrop-blur transition hover:-translate-y-0.5 hover:border-indigo-200 hover:bg-white hover:shadow-[0_18px_38px_-30px_rgba(79,70,229,0.42)] focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/15 disabled:cursor-not-allowed disabled:opacity-55 dark:border-slate-800 dark:bg-slate-950/45 dark:hover:border-indigo-500/30 dark:hover:bg-slate-950"
                  >
                    <span className="mt-1 h-auto w-px shrink-0 rounded-full bg-gradient-to-b from-indigo-400/70 via-sky-300/70 to-transparent transition-opacity group-hover:opacity-100 dark:from-indigo-300/60 dark:via-cyan-300/40" />
                    <span className="min-w-0 flex-1 py-0.5">
                      <span className="mb-1 flex items-center gap-1.5 text-[11px] font-bold text-slate-500 transition-colors group-hover:text-indigo-600 dark:text-slate-400 dark:group-hover:text-indigo-300">
                        <StarterIcon className="h-3.5 w-3.5" />
                        {starter.label}
                      </span>
                      <span className="line-clamp-2 text-[12.5px] font-medium leading-5 text-slate-600 transition-colors group-hover:text-slate-900 dark:text-slate-300 dark:group-hover:text-slate-100">
                        {starter.prompt}
                      </span>
                    </span>
                    <span className="mt-0.5 font-mono text-[10px] font-semibold text-slate-300 tabular-nums transition-colors group-hover:text-indigo-400 dark:text-slate-600 dark:group-hover:text-indigo-300">
                      {String(index + 1).padStart(2, "0")}
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
          className="relative z-10 mt-3 w-full max-w-6xl flex flex-col items-center"
        >
          {/* Section Toggle */}
          <button
            type="button"
            onClick={() => setRecentOpen(!recentOpen)}
            aria-expanded={recentOpen}
            aria-controls="home-demo-courses"
            className="group flex w-full cursor-pointer items-center gap-4 py-2.5"
          >
            <div className="flex-1 h-[1px] bg-zinc-200 group-hover:bg-zinc-300 transition-colors dark:bg-slate-800 dark:group-hover:bg-slate-700" />
            <span className="flex shrink-0 select-none items-center gap-2 rounded-full border border-indigo-100 bg-white px-3 py-1.5 text-[13px] font-semibold text-slate-700 shadow-sm transition-colors group-hover:border-indigo-200 group-hover:text-indigo-700 dark:border-indigo-500/20 dark:bg-slate-950 dark:text-slate-300 dark:group-hover:text-indigo-300">
              <Package className="h-4 w-4 text-indigo-500" />
              精选演示课程包
              <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[12px] text-indigo-600 dark:bg-indigo-400/10 dark:text-indigo-300">{courses.length}</span>
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
                <div className="pb-10 pt-3">
                  {demoCourseError ? (
                    <div className="mb-4 rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-center text-sm font-medium text-red-600">
                      {demoCourseError}
                    </div>
                  ) : null}
                  {courses.length > 0 && (
                    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
                      {courses.map((course, i) => {
                        const theme = getDemoCourseTheme(course.course_name, i);
                        const CourseIcon = theme.icon;
                        const isImportingThisCourse =
                          courseImportMutation.isPending
                          && courseImportMutation.variables?.filename === course.filename;
                        return (
                          <motion.div
                            key={course.filename}
                            initial={{ opacity: 0, y: 16 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: i * 0.05, duration: 0.35, ease: "easeOut" }}
                          >
                            <button
                              type="button"
                              onClick={() => courseImportMutation.mutate({ filename: course.filename })}
                              disabled={courseImportMutation.isPending}
                              className={cn(
                                "atm-deferred-card group relative flex h-full min-h-[118px] w-full overflow-hidden rounded-lg border p-4 text-left shadow-[0_12px_28px_-24px_rgba(15,23,42,0.45)] transition-all duration-300 hover:-translate-y-0.5 hover:shadow-[0_18px_34px_-28px_rgba(79,70,229,0.45)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 disabled:cursor-wait disabled:hover:translate-y-0 dark:shadow-black/20",
                                theme.shell,
                              )}
                              title={`导入 ${course.course_name} 到左侧课程列表`}
                              aria-label={`导入 ${course.course_name}`}
                            >
                              <div className={cn("pointer-events-none absolute inset-x-0 top-0 h-1 bg-gradient-to-r", theme.strip)} />
                              <div className="min-w-0 pr-12">
                                <h3 className="line-clamp-2 text-[15px] font-bold leading-snug tracking-normal text-slate-950 dark:text-slate-100">{course.course_name}</h3>
                              </div>

                              <div className={cn("absolute right-4 top-5 rounded-md border p-1.5", theme.icon)}>
                                {isImportingThisCourse ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <CourseIcon className="h-3.5 w-3.5" />
                                )}
                              </div>

                              <div className="absolute bottom-4 right-4 text-xs font-medium text-slate-400 transition-colors group-hover:text-slate-500 dark:text-slate-500 dark:group-hover:text-slate-400">
                                <span>{isImportingThisCourse ? "正在加入课程列表" : "点击加入课程"}</span>
                              </div>
                            </button>
                          </motion.div>
                        );
                      })}
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
          onUploadRequest={handleLibraryUploadRequest}
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
