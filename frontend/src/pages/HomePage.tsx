import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertCircle,
  ArrowUp,
  CheckCircle2,
  ChevronDown,
  Download,
  FileCode,
  FileImage,
  Loader2,
  FileText,
  FileType,
  Paperclip,
  Upload,
  X,
  FileUp,
  Package,
} from "lucide-react";

import { createSubjectApiApiV1SubjectsAddPost } from "../api/generated/subjects";
import { apiClient } from "../api/client";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { getApiErrorMessage } from "../api/client";
import { cn } from "../lib/utils";
import { downloadSubjectPackage } from "../lib/subjectPackage";
import { resolveFileProcessingLabel } from "../components/knowledge-docs";
import { HeroAnimation } from "../components/ui/HeroAnimation";
import { FullPageDropOverlay } from "../components/ui/FullPageDropOverlay";
import type { FileRecord, FilesData, FilesUploadData } from "../types/files";

/* ── API helpers (same as BuildPlanPage) ── */

interface ApiResponse<T> { code: number; data: T; }

async function uploadFiles(subject: string, files: File[]): Promise<FilesUploadData> {
  const formData = new FormData();
  for (const file of files) formData.append("files", file);

  const response = await apiClient<ApiResponse<FilesUploadData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/files/upload`,
    data: formData,
    headers: { "Content-Type": "multipart/form-data" },
  });
  return response.data;
}

async function fetchFiles(subject: string): Promise<FilesData> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "GET",
    url: `/api/v1/subjects/${subject}/files`,
  });
  return response.data ?? {
    subject,
    total: 0,
    ready_count: 0,
    processing_count: 0,
    failed_count: 0,
    items: [],
  };
}

async function deleteFile(subject: string, uid: string) {
  await apiClient<ApiResponse<{ deleted_file_uids: string[] }>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/files/delete`,
    data: { file_uid: uid },
  });
}

/* ── Export / Import API helpers ── */

interface ExportPreviewStats {
  raw_file_count: number;
  total_raw_file_size_bytes: number;
  knowledge_document_count: number;
  knowledge_unit_count: number;
  knowledge_edge_count: number;
  question_template_count: number;
  exam_paper_count: number;
  chat_session_count: number;
  user_knowledge_state_count: number;
}

interface ExportPreviewData {
  subject_id: string;
  subject_name: string;
  stats: ExportPreviewStats;
  estimated_size_bytes: number;
}

interface ImportResultData {
  subject_id: string;
  subject_name: string;
  imported_counts: Record<string, number>;
  warnings: string[];
}

/* ── Courses folder API ── */

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

async function fetchExportPreview(subject: string): Promise<ExportPreviewData> {
  const response = await apiClient<ApiResponse<ExportPreviewData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/export/preview`,
  });
  return response.data;
}

async function downloadExport(subject: string): Promise<void> {
  await downloadSubjectPackage(subject);
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

const ACCEPT_TEXT = ".pdf,.docx,.doc,.ppt,.pptx,.md,.markdown,.txt,.png,.jpg,.jpeg,.webp";
const HOME_ENTRY_FILES_QUERY_KEY = (subjectId: string) => ["home-entry-files", subjectId] as const;

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

/* ── Export Modal ── */

function ExportModal({
  subjectId,
  onClose,
}: {
  subjectId: string;
  onClose: () => void;
}) {
  const { data: preview, isLoading } = useQuery({
    queryKey: ["export-preview", subjectId],
    queryFn: () => fetchExportPreview(subjectId),
  });

  const exportMutation = useMutation({
    mutationFn: () => downloadExport(subjectId),
    onSuccess: () => onClose(),
  });

  const stats = preview?.stats;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div className="absolute inset-0 modal-backdrop" onClick={onClose} />
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95 }}
        className="relative z-10 w-[480px] max-w-[90vw] bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden"
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 shadow-sm">
              <Package className="w-5 h-5 text-white" />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-900">导出学科</h3>
              <p className="text-xs text-slate-500 mt-0.5">{preview?.subject_name ?? "加载中…"}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors" title="关闭">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="px-6 py-5">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
              <span className="ml-2 text-sm text-slate-500">正在统计内容…</span>
            </div>
          ) : stats ? (
            <div className="space-y-3">
              <p className="text-sm text-slate-600 mb-4">
                将以下内容打包为 <code className="px-1.5 py-0.5 bg-slate-100 rounded text-xs font-mono">.atmx</code> 文件，导入后即可直接使用。
              </p>
              <div className="grid grid-cols-2 gap-2">
                {[
                  { label: "上传文件", value: stats.raw_file_count, show: true },
                  { label: "知识文档", value: stats.knowledge_document_count, show: true },
                  { label: "知识图谱节点", value: stats.knowledge_unit_count, show: true },
                  { label: "知识图谱边", value: stats.knowledge_edge_count, show: true },
                  { label: "题目模板", value: stats.question_template_count, show: stats.question_template_count > 0 },
                  { label: "考试记录", value: stats.exam_paper_count, show: stats.exam_paper_count > 0 },
                  { label: "对话记录", value: stats.chat_session_count, show: stats.chat_session_count > 0 },
                ].filter(s => s.show).map(({ label, value }) => (
                  <div key={label} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2">
                    <span className="text-xs text-slate-500">{label}</span>
                    <span className="text-sm font-semibold text-slate-800">{value}</span>
                  </div>
                ))}
              </div>
              {stats.total_raw_file_size_bytes > 0 && (
                <p className="text-xs text-slate-400 mt-2">
                  文件体积约 {formatFileSize(stats.total_raw_file_size_bytes)}
                </p>
              )}
            </div>
          ) : null}
        </div>
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-100 bg-slate-50/50">
          <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 rounded-lg hover:bg-slate-100 transition-colors">
            取消
          </button>
          <button
            onClick={() => exportMutation.mutate()}
            disabled={isLoading || exportMutation.isPending}
            className={cn(
              "flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-bold transition-all",
              !isLoading && !exportMutation.isPending
                ? "bg-slate-900 text-white hover:bg-slate-800 shadow-sm hover:shadow-md"
                : "bg-slate-200 text-slate-400 cursor-not-allowed"
            )}
          >
            {exportMutation.isPending ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> 导出中…</>
            ) : (
              <><Download className="w-4 h-4" /> 导出</>
            )}
          </button>
        </div>
      </motion.div>
    </div>
  );
}

/* ── Import Modal ── */

function ImportModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [customName, setCustomName] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const importMutation = useMutation({
    mutationFn: () => importSubject(selectedFile!, customName.trim() || undefined),
    onSuccess: () => { onSuccess(); onClose(); },
  });

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div className="absolute inset-0 modal-backdrop" onClick={onClose} />
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95 }}
        className="relative z-10 w-[480px] max-w-[90vw] bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden"
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 shadow-sm">
              <Upload className="w-5 h-5 text-white" />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-900">导入学科</h3>
              <p className="text-xs text-slate-500 mt-0.5">从 .atmx 文件导入已构建的学科</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors" title="关闭">
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
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files[0]; if (f) setSelectedFile(f); }}
            onClick={() => inputRef.current?.click()}
            className={cn(
              "flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-8 cursor-pointer transition-all",
              dragOver
                ? "border-emerald-400 bg-emerald-50"
                : selectedFile
                  ? "border-slate-300 bg-slate-50"
                  : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
            )}
          >
            {selectedFile ? (
              <>
                <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-emerald-100">
                  <Package className="w-6 h-6 text-emerald-600" />
                </div>
                <div className="text-center">
                  <p className="text-sm font-semibold text-slate-800">{selectedFile.name}</p>
                  <p className="text-xs text-slate-400 mt-1">{formatFileSize(selectedFile.size)}</p>
                </div>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); setSelectedFile(null); }}
                  className="text-xs text-slate-500 hover:text-red-500 underline"
                >
                  重新选择
                </button>
              </>
            ) : (
              <>
                <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-slate-100">
                  <Upload className="w-6 h-6 text-slate-400" />
                </div>
                <div className="text-center">
                  <p className="text-sm font-medium text-slate-600">点击选择或拖拽 .atmx 文件</p>
                  <p className="text-xs text-slate-400 mt-1">支持 AITeachMe 导出包</p>
                </div>
              </>
            )}
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1.5">自定义学科名称（可选）</label>
            <input
              type="text"
              value={customName}
              onChange={(e) => setCustomName(e.target.value)}
              placeholder="留空则使用导出时的原名"
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-300 transition-colors"
            />
          </div>
          {importMutation.isError && (
            <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2">
              <p className="text-sm text-red-600">{getApiErrorMessage(importMutation.error, "导入失败")}</p>
            </div>
          )}
        </div>
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-100 bg-slate-50/50">
          <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 rounded-lg hover:bg-slate-100 transition-colors">
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
        className="relative z-10 w-[420px] max-w-[90vw] bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden"
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <h3 className="text-base font-bold text-slate-900">重命名学科</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors" title="关闭">
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
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-300 transition-colors"
            autoFocus
          />
          {renameMutation.isError && (
            <p className="mt-2 text-sm text-red-600">{getApiErrorMessage(renameMutation.error, "重命名失败")}</p>
          )}
        </div>
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-100 bg-slate-50/50">
          <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 rounded-lg hover:bg-slate-100 transition-colors">
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
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const [prompt, setPrompt] = useState("");
  const [draftSubjectId, setDraftSubjectId] = useState<string | null>(null);
  const [isCreatingDraftSubject, setIsCreatingDraftSubject] = useState(false);
  const [isUploadingFiles, setIsUploadingFiles] = useState(false);
  const [uploadingFileNames, setUploadingFileNames] = useState<string[]>([]);
  const [recentOpen, setRecentOpen] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal state
  const [exportSubjectId, setExportSubjectId] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<{ id: string; name: string } | null>(null);
  const newEntryAt = (location.state as { newEntryAt?: number } | null)?.newEntryAt;

  useEffect(() => {
    if (!newEntryAt) {
      return;
    }
    setPrompt("");
    setDraftSubjectId(null);
    setIsCreatingDraftSubject(false);
    setIsUploadingFiles(false);
    setUploadingFileNames([]);
    setError(null);
    navigate("/", { replace: true, state: null });
    window.requestAnimationFrame(() => textareaRef.current?.focus());
  }, [navigate, newEntryAt]);

  const { data: entryFilesData } = useQuery({
    queryKey: HOME_ENTRY_FILES_QUERY_KEY(draftSubjectId ?? "pending"),
    enabled: Boolean(draftSubjectId),
    queryFn: () => fetchFiles(draftSubjectId!),
    refetchInterval: (query) => {
      const data = query.state.data as FilesData | undefined;
      if (isUploadingFiles || (data?.processing_count ?? 0) > 0) {
        return 2000;
      }
      return false;
    },
  });

  // ── Courses query ──
  const { data: courses = [], isLoading: coursesLoading } = useQuery({
    queryKey: ["available-courses"],
    queryFn: fetchAvailableCourses,
  });

  const courseImportMutation = useMutation({
    mutationFn: ({ filename, newName }: { filename: string; newName?: string }) =>
      importCourseByFilename(filename, newName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["subjects"] });
      queryClient.invalidateQueries({ queryKey: ["available-courses"] });
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

  const syncEntryFilesCache = useCallback((subjectId: string, uploaded: FileRecord[]) => {
    queryClient.setQueryData<FilesData>(HOME_ENTRY_FILES_QUERY_KEY(subjectId), (previous) => {
      const previousItems = previous?.items ?? [];
      const nextByUid = new Map(previousItems.map((item) => [item.uid, item]));
      for (const item of uploaded) {
        nextByUid.set(item.uid, item);
      }
      const nextItems = Array.from(nextByUid.values()).sort(
        (left, right) =>
          Date.parse(right.latest_updated_at || right.created_at || "") -
          Date.parse(left.latest_updated_at || left.created_at || ""),
      );
      return {
        subject: subjectId,
        total: nextItems.length,
        ready_count: nextItems.filter((item) => item.markdown_ready).length,
        processing_count: nextItems.filter((item) => !item.markdown_ready && !item.error_message?.trim()).length,
        failed_count: nextItems.filter((item) => Boolean(item.error_message?.trim()) || item.status === "failed").length,
        items: nextItems,
      };
    });
  }, [queryClient]);

  const uploadPendingFiles = useCallback(async (files: File[]) => {
    if (!files.length) {
      return;
    }
    const subjectId = await ensureDraftSubjectId();
    setError(null);
    setIsUploadingFiles(true);
    setUploadingFileNames(files.map((file) => file.name));
    try {
      const result = await uploadFiles(subjectId, files);
      syncEntryFilesCache(subjectId, result.uploaded_items ?? []);
      await queryClient.invalidateQueries({ queryKey: HOME_ENTRY_FILES_QUERY_KEY(subjectId) });
    } catch (err: unknown) {
      setError(getApiErrorMessage(err, "文件上传失败"));
    } finally {
      setIsUploadingFiles(false);
      setUploadingFileNames([]);
    }
  }, [ensureDraftSubjectId, queryClient, syncEntryFilesCache]);

  // ── Handlers ──
  const uploadedFiles = entryFilesData?.items ?? [];
  const optimisticUploadingFiles = uploadingFileNames.filter(
    (name) => !uploadedFiles.some((file) => file.filename === name),
  );
  const hasEntryFiles = uploadedFiles.length > 0 || optimisticUploadingFiles.length > 0;
  const entryFilesStatusText = useMemo(() => {
    if (isCreatingDraftSubject) {
      return "正在创建学习空间，随后会立即上传资料。";
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
      uploadedFiles.filter((file) => !file.markdown_ready && !file.error_message?.trim()).length;
    const failedCount =
      entryFilesData?.failed_count ??
      uploadedFiles.filter((file) => Boolean(file.error_message?.trim()) || file.status === "failed").length;

    if (processingCount > 0) {
      return `${processingCount} 份资料正在解析中；已上传的资料会持续保留，完成后会自动转为可用状态。`;
    }
    if (readyCount > 0 && failedCount === 0) {
      return `${readyCount} 份资料已就绪，可以直接开始规划。资料会保留，除非你手动移除。`;
    }
    if (readyCount > 0 && failedCount > 0) {
      return `${readyCount} 份资料已就绪，${failedCount} 份资料处理失败；失败文件可删掉后重新上传。`;
    }
    if (failedCount > 0) {
      return `${failedCount} 份资料处理失败；你可以移除后重新上传。`;
    }
    return "资料已上传，会继续在后台解析；文件会保留在这里，除非你手动移除。";
  }, [entryFilesData?.failed_count, entryFilesData?.processing_count, entryFilesData?.ready_count, hasEntryFiles, isCreatingDraftSubject, isUploadingFiles, uploadedFiles]);
  const canGenerate = prompt.trim().length > 0 || hasEntryFiles;

  const handleGenerate = async () => {
    if (!canGenerate) return;
    setError(null);
    try {
      const subjectId = await ensureDraftSubjectId();
      const userGoal = prompt.trim();
      navigate(`/subject/${subjectId}/build`, {
        state: userGoal
          ? { initialPrompt: userGoal, autoStart: true }
          : undefined,
      });
    } catch {
      // ensureDraftSubjectId already writes user-facing error
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleGenerate();
    }
  };

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

  const deleteEntryFileMutation = useMutation({
    mutationFn: async (uid: string) => {
      if (!draftSubjectId) {
        throw new Error("缺少临时学习空间，无法删除文件。");
      }
      await deleteFile(draftSubjectId, uid);
    },
    onSuccess: async () => {
      if (draftSubjectId) {
        await queryClient.invalidateQueries({ queryKey: HOME_ENTRY_FILES_QUERY_KEY(draftSubjectId) });
      }
    },
    onError: (err: unknown) => {
      setError(getApiErrorMessage(err, "删除文件失败"));
    },
  });

  const isWorking = isCreatingDraftSubject || isUploadingFiles;

  return (
    <>
    <FullPageDropOverlay
      onDrop={(droppedFiles) => {
        handleFileDrop(droppedFiles);
      }}
      disabled={isWorking}
    />
    <div className="relative flex min-h-[100dvh] w-full flex-col items-center overflow-x-hidden bg-transparent p-4 pt-24 md:p-8 md:pt-32 selection:bg-zinc-200">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: "easeOut" }}
        className={cn(
          "relative z-20 w-full max-w-[800px] flex flex-col items-center",
          courses.length === 0 ? "justify-center min-h-[calc(100dvh-9rem)] translate-y-[8vh] md:translate-y-[11vh]" : "mt-[10vh]"
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
              className="text-2xl md:text-3xl font-bold tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-slate-800 via-indigo-700 to-violet-600 animate-text-gradient"
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
          className="mb-8 px-4 text-center text-[15px] leading-relaxed text-zinc-500"
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
          <div className="w-full rounded-[30px] border-[1.5px] border-zinc-200/80 bg-white/70 backdrop-blur-xl shadow-[0_8px_30px_rgb(0,0,0,0.06)] transition-all focus-within:border-indigo-300 focus-within:shadow-[0_8px_30px_rgb(99,102,241,0.15)] focus-within:ring-4 focus-within:ring-indigo-500/10 hover:border-zinc-300 hover:bg-white/80 hover:shadow-[0_8px_30px_rgb(0,0,0,0.1)]">
            <textarea
              ref={textareaRef}
              placeholder="直接输入学习目标，也可以先上传资料再一起规划"
              className="w-full min-h-[108px] max-h-[240px] resize-none border-0 bg-transparent px-6 pb-4 pt-7 text-[15px] leading-[1.9] text-zinc-800 focus:outline-none placeholder:text-zinc-400"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={3}
              disabled={isCreatingDraftSubject}
            />

            <div className="mx-5 h-px bg-zinc-100" />

            <div className="px-5 pb-4 pt-3 flex flex-col gap-3">
              {(hasEntryFiles || isUploadingFiles) && (
                <div className="space-y-2">
                  <div className="flex flex-wrap gap-2">
                  {uploadedFiles.map((file) => {
                    const meta = homeFileStatusMeta(file);
                    return (
                      <div
                        key={file.uid}
                        className="group inline-flex max-w-full items-center gap-2 rounded-2xl border border-zinc-200/80 bg-zinc-50/90 px-3 py-2 text-[13px] text-zinc-700 transition-colors hover:border-zinc-300 hover:bg-white"
                      >
                        <span className="shrink-0">{homeFileIcon(file)}</span>
                        <span className="max-w-[220px] truncate font-medium text-zinc-800">{file.filename}</span>
                        <span className={cn("shrink-0", meta.tone)} title={resolveFileProcessingLabel(file)}>
                          {meta.icon}
                        </span>
                        <button
                          type="button"
                          onClick={() => deleteEntryFileMutation.mutate(file.uid)}
                          disabled={deleteEntryFileMutation.isPending}
                          title="移除文件"
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
                      className="inline-flex max-w-full items-center gap-2 rounded-2xl border border-zinc-200/80 bg-zinc-50/90 px-3 py-2 text-[13px] text-zinc-700"
                    >
                      <FileUp className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
                      <span className="max-w-[220px] truncate font-medium text-zinc-800">{filename}</span>
                      <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-sky-500" />
                    </div>
                  ))}
                  </div>
                  {entryFilesStatusText ? (
                    <p className="px-1 text-[12px] leading-5 text-zinc-500">{entryFilesStatusText}</p>
                  ) : null}
                </div>
              )}

              <div className="flex items-end justify-between px-1 pt-1">
                <div className="flex items-center gap-2 flex-1">
                  <input 
                    type="file" 
                    title="选择要上传的文件资料"
                    multiple 
                    className="hidden" 
                    ref={fileInputRef} 
                    onChange={handleFileSelect}
                    accept={ACCEPT_TEXT}
                  />
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-medium text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900"
                  >
                    {isUploadingFiles || isCreatingDraftSubject ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Paperclip className="h-4 w-4" />
                    )}
                    {hasEntryFiles ? "添加资料" : "添加资料"}
                  </button>
                  {isWorking && (
                    <span className="ml-2 flex items-center text-[13px] font-medium text-zinc-500">
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                      {isCreatingDraftSubject ? "正在创建学习空间..." : "正在上传并解析资料..."}
                    </span>
                  )}
                </div>

                <button
                  onClick={handleGenerate}
                  disabled={!canGenerate || isWorking}
                  className={cn(
                    "flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl transition-all focus:outline-none focus:ring-4 focus:ring-zinc-900/10 active:scale-[0.98]",
                    canGenerate && !isWorking
                      ? "bg-zinc-900 text-white shadow-sm hover:bg-zinc-800"
                      : "cursor-not-allowed bg-zinc-100 text-zinc-300"
                  )}
                >
                  <ArrowUp className="h-4 w-4" />
                </button>
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
            <div className="flex-1 h-[1px] bg-zinc-200 group-hover:bg-zinc-300 transition-colors" />
            <span className="flex shrink-0 select-none items-center gap-2 text-[13px] font-semibold tracking-tight text-zinc-400 transition-colors group-hover:text-zinc-800">
              <Package className="h-4 w-4" />
              演示课程
              <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-500 shadow-[inset_0_1px_2px_rgba(0,0,0,0.02)]">{courses.length}</span>
              <motion.div
                animate={{ rotate: recentOpen ? 180 : 0 }}
                transition={{ duration: 0.3, ease: "easeInOut" }}
              >
                <ChevronDown className="h-4 w-4" />
              </motion.div>
            </span>
            <div className="flex-1 h-[1px] bg-zinc-200 group-hover:bg-zinc-300 transition-colors" />
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
                    className="flex items-center gap-2 px-3.5 py-2 rounded-xl text-sm font-medium text-slate-600 bg-white border border-slate-200 hover:border-slate-300 hover:bg-slate-50 shadow-sm hover:shadow transition-all"
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
                    {!coursesLoading && courses.length === 0 && (
                      <div className="py-12 text-center">
                        <div className="flex items-center justify-center w-16 h-16 rounded-2xl bg-slate-100 mx-auto mb-4">
                          <Package className="w-8 h-8 text-slate-400" />
                        </div>
                        <p className="text-sm font-medium text-slate-600 mb-1">暂无演示课程</p>
                        <p className="text-xs text-slate-400">
                          将 <code className="px-1 py-0.5 bg-slate-100 rounded text-xs">.atmx</code> 文件放入{" "}
                          <code className="px-1 py-0.5 bg-slate-100 rounded text-xs">backend/data/_courses/</code> 目录即可在此显示为演示课程
                        </p>
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
                              <div className="mt-auto pt-3 border-t border-slate-100">
                                <button
                                  onClick={() => courseImportMutation.mutate({ filename: course.filename })}
                                  disabled={courseImportMutation.isPending}
                                  className={cn(
                                    "w-full flex items-center justify-center gap-2 py-2 rounded-xl text-sm font-bold transition-all",
                                    !courseImportMutation.isPending
                                      ? "bg-slate-900 text-white hover:bg-slate-800 shadow-sm hover:shadow-md"
                                      : "bg-slate-200 text-slate-400 cursor-not-allowed"
                                  )}
                                  title={`导入 ${course.subject_name}`}
                                >
                                  {courseImportMutation.isPending ? (
                                    <><Loader2 className="w-4 h-4 animate-spin" /> 导入中…</>
                                  ) : (
                                    <><Download className="w-4 h-4" /> 导入体验</>
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
        <ExportModal
          key="export"
          subjectId={exportSubjectId}
          onClose={() => setExportSubjectId(null)}
        />
      )}
      {importOpen && (
        <ImportModal
          key="import"
          onClose={() => setImportOpen(false)}
          onSuccess={() => queryClient.invalidateQueries({ queryKey: ["subjects"] })}
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
