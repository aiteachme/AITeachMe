import { useState, useRef, useCallback, useMemo, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowRight,
  ArrowUp,
  BookOpen,
  CheckCircle2,
  AlertCircle,
  ChevronDown,
  Clock,
  Download,
  Edit3,
  Loader2,
  MessageSquare,
  MoreVertical,
  FileText,
  FileImage,
  FileCode,
  FileType,
  Paperclip,
  Trash2,
  Upload,
  X,
  FileUp,
  Package,
} from "lucide-react";

import { listSubjectsApiApiV1SubjectsListPost, createSubjectApiApiV1SubjectsAddPost } from "../api/generated/subjects";
import { apiClient } from "../api/client";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { getApiErrorMessage } from "../api/client";
import { KnowledgeBuildResolutionModal } from "../components/pages/KnowledgeBuildResolutionModal";
import { SubjectVectorNotice } from "../components/pages/SubjectVectorNotice";
import { cn } from "../lib/utils";
import { HeroAnimation } from "../components/ui/HeroAnimation";
import { FullPageDropOverlay } from "../components/ui/FullPageDropOverlay";
import { useKnowledgeBuildFlow } from "../hooks/useKnowledgeBuildFlow";
import { fetchKnowledgeDocState, buildKnowledgeDocStateQueryKey } from "../lib/knowledgeDocs";
import { formatMinerUErrorForUser } from "../lib/mineruErrors";
import type { FileRecord, FilesData, FilesUploadData } from "../types/files";
import { getStoredAppSettings } from "../hooks/useSettings";

/* ── API helpers (same as BuildPlanPage) ── */

interface ApiResponse<T> { code: number; data: T; }

async function fetchFiles(subject: string): Promise<FilesData> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "GET",
    url: `/api/v1/subjects/${subject}/files`,
  });
  return response.data;
}

async function uploadFiles(subject: string, files: File[]): Promise<FilesUploadData> {
  const formData = new FormData();
  for (const file of files) formData.append("files", file);

  // 前端 settings 属于浏览器本机偏好，上传时需要把解析引擎选择随请求传给后端。
  // 这样后端后台 ingest 任务无需依赖浏览器 localStorage，就能按本次设置走指定方案。
  const settings = getStoredAppSettings();
  if (settings.parserProvider === "markitdown") {
    formData.append("parser_provider", "markitdown");
  }
  if (settings.parserProvider === "mineru") {
    const token = settings.mineruApiToken?.trim();
    formData.append("parser_provider", "mineru");
    if (token) {
      formData.append("mineru_api_token", token);
    }
    formData.append("mineru_model_version", settings.mineruModelVersion ?? "vlm");
    formData.append("mineru_enable_formula", String(settings.mineruEnableFormula));
    formData.append("mineru_enable_table", String(settings.mineruEnableTable));
    formData.append("mineru_is_ocr", String(settings.mineruIsOcr));
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
  const token = localStorage.getItem("token");
  const base = import.meta.env.VITE_API_URL ?? "";
  const url = `${base}/api/v1/subjects/${subject}/export`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({}),
  });
  if (!response.ok) throw new Error(`导出失败 (${response.status})`);
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition");
  let filename = `${subject}.atmx`;
  if (disposition) {
    const match = disposition.match(/filename[^;=\n]*=["']?([^"';\n]*)["']?/);
    if (match?.[1]) filename = match[1];
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
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

function generateSubjectName(files: File[], prompt: string): string {
  if (files.length > 0) {
    const baseName = files[0].name.replace(/\.[^/.]+$/, "").trim();
    if (baseName) return baseName;
  }
  const trimmed = prompt.trim();
  if (trimmed) {
    const firstLine = trimmed.split(/[\r\n]/)[0].trim();
    return firstLine.length > 20 ? firstLine.slice(0, 20) + "…" : firstLine;
  }
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `学科_${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}`;
}

function getFileStatusMeta(file: FileRecord) {
  if (file.markdown_ready)
    return { label: "已完成", tone: "text-emerald-600 bg-emerald-50 border-emerald-200", dotColor: "bg-emerald-500", icon: <CheckCircle2 className="h-4 w-4 text-emerald-500" /> };
  if (file.status === "failed")
    return { label: "解析失败", tone: "text-red-600 bg-red-50 border-red-200", dotColor: "bg-red-500", icon: <AlertCircle className="h-4 w-4 text-red-500" /> };
  const stageLabels: Record<string, string> = { classifying: "分类中…", fast_parsing: "解析中…", fast_parsed: "已解析", enhancing: "优化中…", ready_for_digest: "就绪" };
  if (new Set(["pending", "processing", "running"]).has(file.status) || file.ingest_status !== "pending") {
    return { label: stageLabels[file.ingest_status] ?? "处理中…", tone: "text-slate-700 bg-slate-50 border-slate-200", dotColor: "bg-sky-500 animate-pulse", icon: <Loader2 className="h-4 w-4 animate-spin text-slate-500" /> };
  }
  return { label: "等待处理", tone: "text-amber-600 bg-amber-50 border-amber-200", dotColor: "bg-amber-500 animate-pulse", icon: <Loader2 className="h-4 w-4 animate-spin text-amber-500" /> };
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

function formatFileSize(bytes?: number | null): string {
  if (bytes == null || !Number.isFinite(bytes)) return "未知";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) { value /= 1024; unitIndex += 1; }
  return `${value >= 10 || unitIndex === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unitIndex]}`;
}

/* ── Subject Card Three-dot Dropdown ── */

function SubjectMenu({
  subjectId,
  subjectName,
  onExport,
  onRename,
}: {
  subjectId: string;
  subjectName: string;
  onExport: (id: string) => void;
  onRename: (id: string, name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={menuRef} className="relative z-30">
      <button
        type="button"
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(!open); }}
        className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors"
        title="更多操作"
      >
        <MoreVertical className="w-4 h-4" />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: -4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -4 }}
            transition={{ duration: 0.15 }}
            className="absolute right-0 top-full mt-1 w-36 bg-white rounded-xl border border-slate-200 shadow-lg overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(false); onExport(subjectId); }}
              className="w-full flex items-center gap-2.5 px-3.5 py-2.5 text-sm text-slate-700 hover:bg-slate-50 transition-colors"
            >
              <Download className="w-4 h-4 text-slate-400" />
              <span>导出学科</span>
            </button>
            <button
              type="button"
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(false); onRename(subjectId, subjectName); }}
              className="w-full flex items-center gap-2.5 px-3.5 py-2.5 text-sm text-slate-700 hover:bg-slate-50 transition-colors border-t border-slate-100"
            >
              <Edit3 className="w-4 h-4 text-slate-400" />
              <span>重命名</span>
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
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
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
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
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
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
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
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

/* ── File Card ── */

function HomeFileCard({ file, onDelete, isDeleting }: { file: FileRecord; onDelete: () => void; isDeleting: boolean }) {
  const meta = getFileStatusMeta(file);
  const failureReason = useMemo(() => {
    if (file.status !== "failed" || !file.error_message) return null;
    const mapped = formatMinerUErrorForUser(file.error_message);
    if (mapped) return mapped;
    if (/mineru/i.test(file.error_message)) return "MinerU 解析失败。建议：请稍后重试，或在调试模式查看详细错误。";
    return file.error_message;
  }, [file.error_message, file.status]);
  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95 }}
      className="group flex items-center gap-3 rounded-xl border border-zinc-200/80 bg-white px-3 py-2 shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition-all hover:border-zinc-300 hover:shadow-[0_4px_12px_rgba(0,0,0,0.04)]"
    >
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-zinc-50 border border-zinc-100/80">
        {getFileIcon(file)}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-[13px] font-semibold text-zinc-900">{file.filename}</p>
          <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium leading-none", meta.tone)}>
            <span className={cn("h-1.5 w-1.5 rounded-full", meta.dotColor)} />
            {meta.label}
          </span>
        </div>
        <div className="mt-0.5 flex items-center gap-3 text-xs text-zinc-400">
          <span>{file.filetype ? file.filetype.toUpperCase() : "未知"}</span>
          <span>·</span>
          <span>{formatFileSize(file.file_size_bytes)}</span>
          {file.estimated_pages != null && (<><span>·</span><span>{file.estimated_pages} 页</span></>)}
        </div>
        {failureReason ? (
          <p className="mt-1 truncate text-xs text-red-600" title={failureReason}>
            失败原因：{failureReason}
          </p>
        ) : null}
      </div>
      <button
        type="button"
        onClick={onDelete}
        disabled={isDeleting}
        className="shrink-0 rounded-lg p-1.5 text-zinc-300 opacity-0 transition-all hover:bg-red-50 hover:text-red-500 group-hover:opacity-100 disabled:opacity-30"
        title="删除文件"
      >
        <Trash2 className="h-4 w-4" />
      </button>
    </motion.div>
  );
}

/* ── Main HomePage ── */

export function HomePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // activeSubjectId powers the "Phase 2" inline file list on HomePage.
  // After createMutation we now navigate to BuildPlanPage, so the setter
  // is not called; prefix with underscore to satisfy noUnusedLocals.
  const [activeSubjectId, _setActiveSubjectId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [recentOpen, setRecentOpen] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal state
  const [exportSubjectId, setExportSubjectId] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<{ id: string; name: string } | null>(null);

  // Section tab: "recent" | "courses"
  const [sectionTab, setSectionTab] = useState<"recent" | "courses">("recent");

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

  // ── Subject list ──
  const { data: subjects = [], isLoading: subjectsLoading } = useQuery({
    queryKey: ["subjects"],
    queryFn: async () =>
      unwrapOrvalResponse(
        await listSubjectsApiApiV1SubjectsListPost({ page: 1, size: 100 }),
      )?.items ?? [],
  });

  // ── Files query ──
  const { data: filesData, error: filesError } = useQuery({
    queryKey: ["files", activeSubjectId],
    queryFn: () => fetchFiles(activeSubjectId!),
    enabled: Boolean(activeSubjectId),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      return items.some((item) => !item.markdown_ready && item.status !== "failed") ? 1500 : false;
    },
  });

  const { data: knowledgeDocState, error: knowledgeDocStateError } = useQuery({
    queryKey: buildKnowledgeDocStateQueryKey(activeSubjectId ?? ""),
    queryFn: () => fetchKnowledgeDocState(activeSubjectId!),
    enabled: Boolean(activeSubjectId),
    retry: false,
  });

  const files = filesData?.items ?? [];
  const readyFiles = useMemo(() => files.filter((f) => f.markdown_ready), [files]);

  useEffect(() => {
    if (!activeSubjectId) {
      return;
    }

    if (filesError) {
      setError(getApiErrorMessage(filesError, "学科创建后读取资料失败"));
      return;
    }

    if (knowledgeDocStateError) {
      setError(getApiErrorMessage(knowledgeDocStateError, "学科创建后读取知识状态失败"));
      return;
    }

    setError((currentError) => {
      if (
        currentError === "学科创建后读取资料失败" ||
        currentError === "学科创建后读取知识状态失败"
      ) {
        return null;
      }
      return currentError;
    });
  }, [activeSubjectId, filesError, knowledgeDocStateError]);

  // ── Mutations ──
  const createMutation = useMutation({
    mutationFn: async ({ name }: { name: string }) => {
      const created = unwrapOrvalResponse(
        await createSubjectApiApiV1SubjectsAddPost({ name })
      );
      if (!created) throw new Error("创建学科失败");
      return created;
    },
    onSuccess: async (created) => {
      queryClient.invalidateQueries({ queryKey: ["subjects"] });
      setError(null);

      // Upload pending files before navigating
      if (pendingFiles.length > 0) {
        try {
          await uploadFiles(created.subject_id, pendingFiles);
          setPendingFiles([]);
        } catch (e) {
          setError(getApiErrorMessage(e, "文件上传失败"));
          return;
        }
      }

      // Navigate to BuildPlanPage — same planner flow as clicking "开始" there
      const userGoal = prompt.trim();
      navigate(`/subject/${created.subject_id}/build`, {
        state: userGoal
          ? { initialPrompt: userGoal, autoStart: true }
          : undefined,
      });
    },
    onError: (err: unknown) => {
      setError(getApiErrorMessage(err, "创建失败，请重试"));
    },
  });

  const uploadMutation = useMutation({
    mutationFn: (selectedFiles: File[]) => uploadFiles(activeSubjectId!, selectedFiles),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["files", activeSubjectId] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (fileUid: string) => deleteFile(activeSubjectId!, fileUid),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["files", activeSubjectId] }),
  });

  const knowledgeBuild = useKnowledgeBuildFlow({
    subjectId: activeSubjectId ?? "",
    buildRequest: () => ({
      prompt: prompt.trim() || undefined,
    }),
    fallbackErrorMessage: "知识构建失败，请重试。",
    onSuccess: (data) => {
      navigate(`/subject/${activeSubjectId}/knowledge-docs?requested_at=${encodeURIComponent(data.requested_at)}`);
    },
  });

  // ── Handlers ──
  const canGenerate = prompt.trim().length > 0 || pendingFiles.length > 0;

  const handleGenerate = async () => {
    if (!canGenerate) return;
    setError(null);

    // Try AI name suggestion first
    let name: string;
    try {
      const suggestResponse = await apiClient<{ data: { name: string } }>({
        method: "POST",
        url: "/api/v1/subjects/suggest-name",
        data: {
          prompt: prompt.trim() || undefined,
          filenames: pendingFiles.length > 0 ? pendingFiles.map((f) => f.name) : undefined,
        },
      });
      name = suggestResponse.data?.name || generateSubjectName(pendingFiles, prompt);
    } catch {
      name = generateSubjectName(pendingFiles, prompt);
    }

    createMutation.mutate({ name });
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

    if (activeSubjectId) {
      uploadMutation.mutate(newFiles);
    } else {
      setPendingFiles(prev => [...prev, ...newFiles]);
    }
  };

  const handleFileDrop = useCallback((droppedFiles: File[]) => {
    if (!droppedFiles.length) return;
    setPendingFiles(prev => [...prev, ...droppedFiles]);
  }, []);

  const removePendingFile = (index: number) => {
    setPendingFiles(prev => prev.filter((_, i) => i !== index));
  };

  const isWorking = createMutation.isPending;

  return (
    <>
    <FullPageDropOverlay
      onDrop={(droppedFiles) => {
        if (activeSubjectId) {
          uploadMutation.mutate(droppedFiles);
        } else {
          handleFileDrop(droppedFiles);
        }
      }}
      disabled={isWorking}
    />
    <div className="relative flex min-h-[100dvh] w-full flex-col items-center overflow-x-hidden bg-zinc-50 p-4 pt-16 md:p-8 md:pt-24 selection:bg-zinc-200">
      
      {/* ═══ Background Decor ═══ */}
      <div className="pointer-events-none absolute inset-0 z-0 flex justify-center overflow-hidden">
        <div className="h-full w-full bg-[linear-gradient(to_right,#e4e4e7_1px,transparent_1px),linear-gradient(to_bottom,#e4e4e7_1px,transparent_1px)] bg-[size:32px_32px] [mask-image:radial-gradient(ellipse_120%_100%_at_50%_0%,#000_50%,transparent_100%)]"></div>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: "easeOut" }}
        className={cn(
          "relative z-20 w-full max-w-[800px] flex flex-col items-center",
          !activeSubjectId && subjects.length === 0 ? "justify-center min-h-[calc(100dvh-12rem)]" : "mt-[5vh]"
        )}
      >
        {/* ── Logo & Title ── */}
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.1, type: "spring", stiffness: 200, damping: 20 }}
          className="flex items-center justify-center gap-1 mb-2"
        >
          <HeroAnimation />
          <h1 className="text-4xl md:text-5xl font-semibold text-zinc-900 tracking-tight">AI 赛博私教</h1>
        </motion.div>

        {/* ── Slogan ── */}
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.25 }}
          className="mb-8 px-4 text-center text-[15px] leading-relaxed text-zinc-500"
        >
          把任何令人头疼的学习资料，变成你的 24 小时专属"赛博私教"。
        </motion.p>

        {/* ── Unified Input Area ── */}
        <motion.div
          initial={{ opacity: 0, scale: 0.97 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.35 }}
          className="w-full"
        >
          <div className="w-full rounded-2xl border border-zinc-200/60 bg-white shadow-[0_2px_8px_rgba(0,0,0,0.04)] transition-all focus-within:border-zinc-300 focus-within:shadow-[0_4px_16px_rgba(0,0,0,0.06)] focus-within:ring-4 focus-within:ring-zinc-900/5">
            <div className="relative z-20 flex items-start justify-between px-4 pt-4">
              <span className="text-[13px] font-semibold text-zinc-700 tracking-tight">
                {activeSubjectId ? "📂 学习空间已就绪" : "你好，学习者 👋"}
              </span>
              {activeSubjectId && (
                <span className="text-[11px] font-medium text-zinc-400">可继续添加文件或开始构建</span>
              )}
            </div>

            <textarea
              ref={textareaRef}
              placeholder="描述你的学习目标（可选），例如：期末考试复习重点、考研知识梳理、Python 核心编程入门..."
              className="w-full min-h-[120px] max-h-[250px] resize-none border-0 bg-transparent px-4 pb-3 pt-4 text-[14px] leading-[1.8] text-zinc-800 focus:outline-none placeholder:text-zinc-400"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={!activeSubjectId ? handleKeyDown : undefined}
              rows={3}
              disabled={isWorking}
            />

            <div className="px-3 pb-3 flex flex-col gap-2">
              {/* File chips (Phase 1) */}
              {!activeSubjectId && pendingFiles.length > 0 && (
                <div className="flex flex-wrap gap-2 px-1 py-3 border-t border-zinc-100">
                  {pendingFiles.map((file, idx) => (
                    <div key={idx} className="group flex items-center gap-1.5 rounded-lg border border-zinc-200/60 bg-zinc-50 px-2.5 py-1.5 text-[13px] text-zinc-700 transition-colors hover:bg-white hover:border-zinc-300 hover:shadow-sm">
                      <FileUp className="h-3.5 w-3.5 text-zinc-400 group-hover:text-zinc-600" />
                      <span className="max-w-[140px] truncate font-medium">{file.name}</span>
                      <button 
                        onClick={() => removePendingFile(idx)}
                        title="移除文件"
                        className="ml-0.5 rounded-md p-0.5 text-zinc-400 transition-colors hover:bg-red-50 hover:text-red-500"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              <div className="flex items-end justify-between px-1">
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
                    <Paperclip className="h-4 w-4" />
                    上传文件资料
                  </button>
                  {(isWorking || uploadMutation.isPending) && (
                    <span className="ml-2 flex items-center text-[13px] font-medium text-zinc-500">
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                      {isWorking ? "正在准备学习空间..." : "正在上传..."}
                    </span>
                  )}
                </div>

                {!activeSubjectId ? (
                  <button
                    onClick={handleGenerate}
                    disabled={!canGenerate || isWorking}
                    className={cn(
                      "flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-lg px-5 transition-all focus:outline-none focus:ring-4 focus:ring-zinc-900/10 active:scale-[0.98]",
                      canGenerate && !isWorking
                        ? "bg-zinc-900 text-white shadow-sm hover:bg-zinc-800"
                        : "cursor-not-allowed bg-zinc-100 text-zinc-300"
                    )}
                  >
                    <span className="text-[14px] font-medium">开始学习</span>
                    <ArrowUp className="ml-0.5 h-3.5 w-3.5" />
                  </button>
                ) : (
                  <button
                    onClick={() => knowledgeBuild.submitBuild()}
                    disabled={readyFiles.length === 0 || knowledgeBuild.isPending}
                    className={cn(
                      "flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-lg px-5 transition-all focus:outline-none focus:ring-4 focus:ring-zinc-900/10 active:scale-[0.98]",
                      readyFiles.length > 0 && !knowledgeBuild.isPending
                        ? "bg-zinc-900 text-white shadow-sm hover:bg-zinc-800"
                        : "cursor-not-allowed bg-zinc-100 text-zinc-300"
                    )}
                  >
                    {knowledgeBuild.isPending ? (
                      <><Loader2 className="h-3.5 w-3.5 animate-spin" /> <span className="text-[14px] font-medium">正在提交…</span></>
                    ) : (
                      <><span className="text-[14px] font-medium">构建知识产物</span><ArrowRight className="ml-0.5 h-3.5 w-3.5" /></>
                    )}
                  </button>
                )}
              </div>
            </div>
          </div>
        </motion.div>

        {activeSubjectId ? (
          <SubjectVectorNotice
            status={knowledgeBuild.latestVectorStatus ?? knowledgeDocState?.vector_status}
            className="mt-4 w-full"
          />
        ) : null}

        {/* ── Error ── */}
        <AnimatePresence>
          {(error || uploadMutation.isError || knowledgeBuild.errorMessage) && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-4 w-full p-4 bg-red-50 border border-red-100 rounded-xl"
            >
              <p className="text-sm text-red-600 font-medium text-center">
                {error || knowledgeBuild.errorMessage || getApiErrorMessage(uploadMutation.error, "操作失败")}
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      {/* ═══ Phase 2: File List ═══ */}
      {activeSubjectId && files.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="relative z-10 mt-6 w-full max-w-[800px]"
        >
          <details className="group rounded-[1.25rem] border border-zinc-200/80 bg-white/70 shadow-[0_2px_8px_rgba(0,0,0,0.02)] transition-all open:bg-white/95 backdrop-blur-xl overflow-hidden" open>
            <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-4 outline-none [&::-webkit-details-marker]:hidden border-b border-transparent group-open:border-zinc-100">
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="text-[14px] font-semibold tracking-tight text-zinc-900">已上传资料</h2>
                <span className="rounded-full bg-zinc-100 px-2.5 py-0.5 text-[11px] font-semibold text-zinc-600 shadow-[inset_0_1px_2px_rgba(0,0,0,0.02)]">
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
                  <HomeFileCard
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

      {/* ═══ Recent Classrooms / Import Courses ═══ */}
      {!activeSubjectId && (subjects.length > 0 || courses.length > 0) && (
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
              <Clock className="h-4 w-4" />
              最近的学习空间
              <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-500 shadow-[inset_0_1px_2px_rgba(0,0,0,0.02)]">{subjects.length + courses.length}</span>
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
                {/* Tab Bar */}
                <div className="flex items-center gap-1 pt-4 pb-2 px-1">
                  <button
                    onClick={() => setSectionTab("recent")}
                    className={cn(
                      "flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all",
                      sectionTab === "recent"
                        ? "bg-slate-900 text-white shadow-sm"
                        : "text-slate-500 hover:text-slate-800 hover:bg-slate-100"
                    )}
                    title="最近的学习空间"
                  >
                    <Clock className="w-4 h-4" />
                    最近的学习空间
                    {subjects.length > 0 && (
                      <span className={cn(
                        "text-xs px-1.5 py-0.5 rounded-full",
                        sectionTab === "recent" ? "bg-white/20" : "bg-slate-100"
                      )}>{subjects.length}</span>
                    )}
                  </button>
                  <button
                    onClick={() => setSectionTab("courses")}
                    className={cn(
                      "flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all",
                      sectionTab === "courses"
                        ? "bg-slate-900 text-white shadow-sm"
                        : "text-slate-500 hover:text-slate-800 hover:bg-slate-100"
                    )}
                    title="导入课程"
                  >
                    <Package className="w-4 h-4" />
                    导入课程
                    {courses.length > 0 && (
                      <span className={cn(
                        "text-xs px-1.5 py-0.5 rounded-full",
                        sectionTab === "courses" ? "bg-white/20" : "bg-slate-100"
                      )}>{courses.length}</span>
                    )}
                  </button>

                  {/* Upload import button */}
                  <div className="ml-auto">
                    <button
                      onClick={() => setImportOpen(true)}
                      className="flex items-center gap-2 px-3.5 py-2 rounded-xl text-sm font-medium text-slate-600 bg-white border border-slate-200 hover:border-slate-300 hover:bg-slate-50 shadow-sm hover:shadow transition-all"
                      title="从文件导入学科包"
                    >
                      <Upload className="w-4 h-4 text-emerald-500" />
                      上传导入
                    </button>
                  </div>
                </div>

                {/* Tab: Recent Subjects */}
                {sectionTab === "recent" && (
                  <div className="pt-2 pb-12 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                    {subjectsLoading && (
                      <div className="col-span-full py-8 flex justify-center w-full">
                        <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
                      </div>
                    )}
                    {subjects.map((subject: any, i: number) => (
                      <motion.div
                        key={subject.subject_id}
                        initial={{ opacity: 0, y: 16 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: i * 0.05, duration: 0.35, ease: "easeOut" }}
                      >
                        <div className="relative block group">
                          <div className="group/card relative flex h-full flex-col overflow-hidden rounded-2xl border border-zinc-200/80 bg-white p-5 shadow-[0_2px_8px_rgba(0,0,0,0.04)] transition-all duration-300 hover:-translate-y-1 hover:border-zinc-300 hover:shadow-[0_8px_24px_rgba(0,0,0,0.08)]">
                            <div className="relative z-10 mb-4 flex items-start justify-between">
                              <h3 className="line-clamp-1 flex-1 mr-2 text-[15px] font-semibold tracking-tight text-zinc-900 transition-colors group-hover/card:text-zinc-800">
                                {subject.name}
                              </h3>
                              <div className="flex items-center gap-1 pointer-events-auto">
                                <SubjectMenu
                                  subjectId={subject.subject_id}
                                  subjectName={subject.name}
                                  onExport={(id: string) => setExportSubjectId(id)}
                                  onRename={(id: string, name: string) => setRenameTarget({ id, name })}
                                />
                                <Link to={`/subject/${subject.subject_id}/build`} className="rounded-lg bg-zinc-50 p-2 transition-colors group-hover/card:bg-zinc-100/80">
                                  <BookOpen className="h-[18px] w-[18px] text-zinc-400 transition-colors group-hover/card:text-zinc-700" />
                                </Link>
                              </div>
                            </div>
                            <Link to={`/subject/${subject.subject_id}/build`} className="relative z-10 mt-auto flex items-center gap-2.5 border-t border-zinc-100 pt-4">
                              <span className="flex items-center rounded-md bg-zinc-100/80 px-2 py-1 text-[11px] font-semibold text-zinc-500">
                                <MessageSquare className="mr-1 h-3.5 w-3.5" /> 会话
                              </span>
                              <span className="flex items-center rounded-md bg-zinc-100/80 px-2 py-1 text-[11px] font-semibold text-zinc-500">
                                <FileText className="mr-1 h-3.5 w-3.5" /> 资料
                              </span>
                              <span className="ml-auto flex items-center text-[11px] font-semibold text-zinc-400 transition-colors group-hover/card:text-zinc-900">
                                 进入学习 <ChevronDown className="ml-0.5 h-3.5 w-3.5 -rotate-90" />
                              </span>
                            </Link>
                          </div>
                        </div>
                      </motion.div>
                    ))}
                    {!subjectsLoading && subjects.length === 0 && (
                      <div className="col-span-full py-12 text-center text-slate-400 text-sm">
                        暂无学习空间，上方创建或导入课程开始学习
                      </div>
                    )}
                  </div>
                )}

                {/* Tab: Import Courses */}
                {sectionTab === "courses" && (
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
                        <p className="text-sm font-medium text-slate-600 mb-1">暂无可导入课程</p>
                        <p className="text-xs text-slate-400">
                          将 <code className="px-1 py-0.5 bg-slate-100 rounded text-xs">.atmx</code> 文件放入{" "}
                          <code className="px-1 py-0.5 bg-slate-100 rounded text-xs">data/_courses/</code> 目录即可在此显示
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
                                    <><Download className="w-4 h-4" /> 一键导入</>
                                  )}
                                </button>
                              </div>
                            </div>
                          </motion.div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      )}

      {/* Footer */}
      <div className="mt-auto pt-12 pb-6 text-center text-sm text-slate-400 font-medium">
        AITeachMe Open Source Project
      </div>
    </div>
    <KnowledgeBuildResolutionModal
      open={knowledgeBuild.precheckConflict !== null}
      conflict={knowledgeBuild.precheckConflict}
      isSubmitting={knowledgeBuild.isPending}
      onClose={knowledgeBuild.closePrecheckConflict}
      onResolve={knowledgeBuild.resolvePrecheckConflict}
    />

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
