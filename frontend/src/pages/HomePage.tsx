import { useState, useRef, useCallback, useMemo } from "react";
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
  Loader2,
  MessageSquare,
  FileText,
  FileImage,
  FileCode,
  FileType,
  Paperclip,
  Trash2,
  X,
  FileUp
} from "lucide-react";

import { listSubjectsApiApiV1SubjectsListPost, createSubjectApiApiV1SubjectsAddPost } from "../api/generated/subjects";
import { apiClient } from "../api/client";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { getApiErrorMessage } from "../api/client";
import { cn } from "../lib/utils";
import { HeroAnimation } from "../components/ui/HeroAnimation";
import { FullPageDropOverlay } from "../components/ui/FullPageDropOverlay";
import type { FileRecord, FilesData, FilesUploadData } from "../types/files";

/* ── API helpers (same as FilesPage) ── */

interface ApiResponse<T> { code: number; data: T; }

interface KnowledgeBuildData {
  accepted_file_uids: string[];
  prompt: string | null;
  ready_file_count: number;
  requested_at: string;
}

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

/* ── File Card (reused from FilesPage pattern) ── */

function HomeFileCard({ file, onDelete, isDeleting }: { file: FileRecord; onDelete: () => void; isDeleting: boolean }) {
  const meta = getFileStatusMeta(file);
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

  // Phase state: null = hero phase, string = workspace phase
  const [activeSubjectId, setActiveSubjectId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [recentOpen, setRecentOpen] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // ── Subject list (for "recent" section) ──
  const { data: subjects = [], isLoading: subjectsLoading } = useQuery({
    queryKey: ["subjects"],
    queryFn: async () =>
      unwrapOrvalResponse(
        await listSubjectsApiApiV1SubjectsListPost({ page: 1, size: 100 }),
      )?.items ?? [],
  });

  // ── Files query (active once a subject is created) ──
  const { data: filesData } = useQuery({
    queryKey: ["files", activeSubjectId],
    queryFn: () => fetchFiles(activeSubjectId!),
    enabled: Boolean(activeSubjectId),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      return items.some((item) => !item.markdown_ready && item.status !== "failed") ? 1500 : false;
    },
  });

  const files = filesData?.items ?? [];
  const readyFiles = useMemo(() => files.filter((f) => f.markdown_ready), [files]);

  // ── Mutations ──
  const createMutation = useMutation({
    mutationFn: async ({ name, description }: { name: string; description: string }) => {
      const created = unwrapOrvalResponse(
        await createSubjectApiApiV1SubjectsAddPost({ name, description })
      );
      if (!created) throw new Error("创建学科失败");
      return created;
    },
    onSuccess: async (created) => {
      queryClient.invalidateQueries({ queryKey: ["subjects"] });
      setError(null);
      setActiveSubjectId(created.subject_id);
      // Immediately upload pending files via API — no router state, no double fire
      if (pendingFiles.length > 0) {
        try {
          await uploadFiles(created.subject_id, pendingFiles);
          setPendingFiles([]);
          queryClient.invalidateQueries({ queryKey: ["files", created.subject_id] });
        } catch (e) {
          setError(getApiErrorMessage(e, "文件上传失败"));
        }
      }
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

  const buildMutation = useMutation({
    mutationFn: () => triggerKnowledgeBuild(activeSubjectId!, prompt.trim() || undefined),
    onSuccess: (data) => {
      navigate(`/subject/${activeSubjectId}/knowledge-docs?requested_at=${encodeURIComponent(data.requested_at)}`);
    },
  });

  // ── Handlers ──
  const canGenerate = prompt.trim().length > 0 || pendingFiles.length > 0;

  const handleGenerate = () => {
    if (!canGenerate) return;
    setError(null);
    const name = generateSubjectName(pendingFiles, prompt);
    createMutation.mutate({ name, description: prompt.trim() });
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
      // Phase 2: upload directly via API
      uploadMutation.mutate(newFiles);
    } else {
      // Phase 1: collect locally
      setPendingFiles(prev => [...prev, ...newFiles]);
    }
  };

  const handleFileDrop = useCallback((droppedFiles: File[]) => {
    if (!droppedFiles.length) return;
    // Will be set after subject creation via onSuccess → can't check here.
    // So always route through setPendingFiles or upload.
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
              {/* File chips (Phase 1: pending files) */}
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

                {/* Action button: Phase1 = 开始学习, Phase2 = 构建知识产物 */}
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
                    onClick={() => buildMutation.mutate()}
                    disabled={readyFiles.length === 0 || buildMutation.isPending}
                    className={cn(
                      "flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-lg px-5 transition-all focus:outline-none focus:ring-4 focus:ring-zinc-900/10 active:scale-[0.98]",
                      readyFiles.length > 0 && !buildMutation.isPending
                        ? "bg-zinc-900 text-white shadow-sm hover:bg-zinc-800"
                        : "cursor-not-allowed bg-zinc-100 text-zinc-300"
                    )}
                  >
                    {buildMutation.isPending ? (
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

        {/* ── Error ── */}
        <AnimatePresence>
          {(error || uploadMutation.isError || buildMutation.isError) && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-4 w-full p-4 bg-red-50 border border-red-100 rounded-xl"
            >
              <p className="text-sm text-red-600 font-medium text-center">
                {error || getApiErrorMessage(uploadMutation.error || buildMutation.error, "操作失败")}
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      {/* ═══ Phase 2: File List (after subject created) ═══ */}
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

      {/* ═══ Recent Classrooms ═══ */}
      {!activeSubjectId && subjects.length > 0 && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.5 }}
          className="relative z-10 mt-12 w-full max-w-5xl flex flex-col items-center"
        >
          {/* Trigger */}
          <button
            onClick={() => setRecentOpen(!recentOpen)}
            className="group flex w-full cursor-pointer items-center gap-4 py-3"
          >
            <div className="flex-1 h-[1px] bg-zinc-200 group-hover:bg-zinc-300 transition-colors" />
            <span className="flex shrink-0 select-none items-center gap-2 text-[13px] font-semibold tracking-tight text-zinc-400 transition-colors group-hover:text-zinc-800">
              <Clock className="h-4 w-4" />
              最近的学习空间
              <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-500 shadow-[inset_0_1px_2px_rgba(0,0,0,0.02)]">{subjects.length}</span>
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
                <div className="pt-6 pb-12 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
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
                      <Link to={`/subject/${subject.subject_id}/files`} className="group block h-full">
                        <div className="group/card relative flex h-full flex-col overflow-hidden rounded-2xl border border-zinc-200/80 bg-white p-5 shadow-[0_2px_8px_rgba(0,0,0,0.04)] transition-all duration-300 hover:-translate-y-1 hover:border-zinc-300 hover:shadow-[0_8px_24px_rgba(0,0,0,0.08)]">
                          <div className="relative z-10 mb-4 flex items-start justify-between">
                            <h3 className="line-clamp-1 text-[15px] font-semibold tracking-tight text-zinc-900 transition-colors group-hover/card:text-zinc-800">
                              {subject.name}
                            </h3>
                            <div className="rounded-lg bg-zinc-50 p-2 transition-colors group-hover/card:bg-zinc-100/80">
                              <BookOpen className="h-[18px] w-[18px] text-zinc-400 transition-colors group-hover/card:text-zinc-700" />
                            </div>
                          </div>
                          <div className="relative z-10 mt-auto flex items-center gap-2.5 border-t border-zinc-100 pt-4">
                            <span className="flex items-center rounded-md bg-zinc-100/80 px-2 py-1 text-[11px] font-semibold text-zinc-500">
                              <MessageSquare className="mr-1 h-3.5 w-3.5" /> 会话
                            </span>
                            <span className="flex items-center rounded-md bg-zinc-100/80 px-2 py-1 text-[11px] font-semibold text-zinc-500">
                              <FileText className="mr-1 h-3.5 w-3.5" /> 资料
                            </span>
                            <span className="ml-auto flex items-center text-[11px] font-semibold text-zinc-400 transition-colors group-hover/card:text-zinc-900">
                               进入学习 <ChevronDown className="ml-0.5 h-3.5 w-3.5 -rotate-90" />
                            </span>
                          </div>
                        </div>
                      </Link>
                    </motion.div>
                  ))}
                </div>
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
    </>
  );
}
