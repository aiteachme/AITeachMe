import { memo, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  BarChart3,
  BookOpen,
  ChevronRight,
  Download,
  Edit3,
  FileText,
  Loader2,
  Menu,
  MoreVertical,
  Plus,
  Trash2,
  Upload,
  X,
  Package,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";

import {
  createSubjectApiApiV1SubjectsAddPost,
  deleteSubjectApiApiV1SubjectsDeletePost,
  listSubjectsApiApiV1SubjectsListPost,
  previewDeleteSubjectApiApiV1SubjectsDeletePreviewPost,
} from "../../api/generated/subjects";
import type { SubjectDeletePreviewData, SubjectItem } from "../../api/generated/model";
import { getApiErrorMessage, apiClient } from "../../api/client";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { cn } from "../../lib/utils";
import { SubjectDeleteConfirmModal } from "./SubjectDeleteConfirmModal";
import { Button } from "../ui/Button";

const CURATED_GRADIENTS = [
  "linear-gradient(135deg, #1e293b, #0f172a)", // Obsidian Black
  "linear-gradient(135deg, #10b981, #047857)", // Emerald Green
  "linear-gradient(135deg, #f43f5e, #be123c)", // Rose Red
  "linear-gradient(135deg, #6366f1, #4338ca)", // Deep Indigo
  "linear-gradient(135deg, #14b8a6, #0f766e)", // Teal
  "linear-gradient(135deg, #f59e0b, #b45309)", // Amber
  "linear-gradient(135deg, #8b5cf6, #6d28d9)", // Violet
  "linear-gradient(135deg, #0ea5e9, #0369a1)", // Ocean Sky
  "linear-gradient(135deg, #ec4899, #be185d)", // Pink Blossom
  "linear-gradient(135deg, #64748b, #334155)", // Slate
];

function getStyleForSubject(name: string) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const index = Math.abs(hash) % CURATED_GRADIENTS.length;
  return {
    background: CURATED_GRADIENTS[index]
  };
}

const MODULES = [
  { id: "files", name: "文件", icon: <Upload className="w-[18px] h-[18px]" /> },
  { id: "knowledge-docs", name: "知识库", icon: <BookOpen className="w-[18px] h-[18px]" /> },
  { id: "exams", name: "考试", icon: <FileText className="w-[18px] h-[18px]" /> },
  { id: "profile", name: "学习画像", icon: <BarChart3 className="w-[18px] h-[18px]" /> },
];

const NewSubjectForm = memo(function NewSubjectForm({
  onSubmit,
  onCancel,
  isPending,
  error,
}: {
  onSubmit: (name: string, description: string) => void;
  onCancel: () => void;
  isPending: boolean;
  error?: string;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const nameInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameInputRef.current?.focus();
  }, []);

  const handleSubmit = () => {
    if (!name.trim()) return;
    onSubmit(name.trim(), description.trim());
  };

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3 overflow-hidden"
    >
      <input
        ref={nameInputRef}
        className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-300 transition-shadow"
        placeholder="学科名称，例如：高等数学"
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      <textarea
        className="min-h-20 w-full resize-y rounded-md border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-300 transition-shadow"
        placeholder="学科描述，可选"
        value={description}
        onChange={(event) => setDescription(event.target.value)}
      />
      <p className="px-0.5 text-xs text-slate-500">
        系统会自动生成学科标识，无需手动填写。
      </p>
      {error && <p className="px-0.5 text-xs text-red-500">{error}</p>}
      <div className="flex gap-2">
        <Button className="flex-1" onClick={handleSubmit} disabled={!name.trim() || isPending}>
          {isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "创建"}
        </Button>
        <Button variant="outline" className="flex-1" onClick={onCancel}>
          取消
        </Button>
      </div>
    </motion.div>
  );
});

export function Sidebar() {
  const [expandedSubjects, setExpandedSubjects] = useState<Set<string>>(new Set());
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false); // Default expanded (LLM Arena style)
  const [showNewForm, setShowNewForm] = useState(false);
  const [createError, setCreateError] = useState<string | undefined>();
  const [subjectActionError, setSubjectActionError] = useState<string | undefined>();
  const [deleteTarget, setDeleteTarget] = useState<SubjectItem | null>(null);
  const [deletePreview, setDeletePreview] = useState<SubjectDeletePreviewData | null>(null);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [exportSubjectId, setExportSubjectId] = useState<string | null>(null);
  const [renameTarget, setRenameTarget] = useState<{ id: string; name: string } | null>(null);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close three-dot menu on outside click
  useEffect(() => {
    if (!openMenuId) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpenMenuId(null);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [openMenuId]);

  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const effectiveCollapsed = !isMobileOpen && isCollapsed;

  const { data: subjects = [], isLoading } = useQuery({
    queryKey: ["subjects"],
    queryFn: async () =>
      unwrapOrvalResponse(
        await listSubjectsApiApiV1SubjectsListPost({
          page: 1,
          size: 100,
        }),
      )?.items ?? [],
  });

  useEffect(() => {
    const match = location.pathname.match(/^\/subject\/([^/]+)/);
    if (!match?.[1]) return;
    setExpandedSubjects((prev) => new Set([...prev, match[1]]));
    // Auto-expand sidebar if navigating into a subject
    setIsCollapsed(false);
  }, [location.pathname]);

  const createMutation = useMutation({
    mutationFn: async ({ name, description }: { name: string; description: string }) => {
      const created = unwrapOrvalResponse(
        await createSubjectApiApiV1SubjectsAddPost({ name, description })
      );
      if (!created) throw new Error("创建学科失败");
      return created;
    },
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["subjects"] });
      setExpandedSubjects((prev) => new Set([...prev, created.subject_id]));
      setShowNewForm(false);
      setCreateError(undefined);
      setSubjectActionError(undefined);
      navigate(`/subject/${created.subject_id}/files`);
    },
    onError: (error: unknown) => {
      setCreateError(getApiErrorMessage(error, "创建失败，请重试"));
    },
  });

  const deletePreviewMutation = useMutation({
    mutationFn: async (subjectId: string) =>
      unwrapOrvalResponse(
        await previewDeleteSubjectApiApiV1SubjectsDeletePreviewPost({
          subject_id: subjectId,
        })
      ) ?? null,
    onSuccess: (preview) => {
      setDeletePreview(preview);
      setSubjectActionError(undefined);
    },
    onError: (error: unknown) => {
      setDeletePreview(null);
      setSubjectActionError(getApiErrorMessage(error, "删除预览加载失败，请重试"));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (subjectId: string) => {
      await deleteSubjectApiApiV1SubjectsDeletePost({
        subject_id: subjectId,
        force: true,
      });
    },
    onSuccess: (_, subjectId) => {
      queryClient.invalidateQueries({ queryKey: ["subjects"] });
      setSubjectActionError(undefined);
      closeDeleteModal();
      if (location.pathname.startsWith(`/subject/${subjectId}/`)) navigate("/");
    },
    onError: (error: unknown) => {
      setSubjectActionError(getApiErrorMessage(error, "删除失败，请重试"));
    },
  });

  const toggleSubject = (subjectId: string) => {
    if (effectiveCollapsed) setIsCollapsed(false);
    setExpandedSubjects((prev) => {
      const next = new Set(prev);
      if (next.has(subjectId)) next.delete(subjectId);
      else next.add(subjectId);
      return next;
    });
  };

  const openDeleteModal = (subject: SubjectItem) => {
    setDeleteTarget(subject);
    setDeletePreview(null);
    setSubjectActionError(undefined);
    setIsDeleteModalOpen(true);
    deletePreviewMutation.reset();
    deleteMutation.reset();
    deletePreviewMutation.mutate(subject.subject_id);
  };

  const closeDeleteModal = () => {
    setIsDeleteModalOpen(false);
    setDeleteTarget(null);
    setDeletePreview(null);
  };

  return (
    <>
      <button
        onClick={() => setIsMobileOpen(!isMobileOpen)}
        className="fixed left-4 top-4 z-50 rounded-lg border border-slate-200 bg-white p-2 shadow-sm lg:hidden transition-all hover:bg-slate-50 text-slate-700"
      >
        {isMobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
      </button>

      {isMobileOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-30 bg-black/20 backdrop-blur-sm lg:hidden"
          onClick={() => setIsMobileOpen(false)}
        />
      )}

      <motion.aside
        animate={{ width: effectiveCollapsed ? 76 : 280 }}
        transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1] }}
        className={cn(
          "fixed inset-y-0 left-0 z-40 relative flex flex-col border-r border-slate-200 bg-white shadow-sm lg:static overflow-hidden lg:overflow-visible shrink-0",
          isMobileOpen ? "translate-x-0 w-[280px]" : "-translate-x-full lg:translate-x-0"
        )}
      >
        <div className="border-b border-slate-100 px-4 flex items-center justify-between h-14 shrink-0">
          <AnimatePresence mode="popLayout">
            {!effectiveCollapsed && (
              <Link to="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity cursor-pointer">
                <motion.div
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -10 }}
                  className="flex items-center gap-2 whitespace-nowrap overflow-hidden"
                >
                  <span className="text-[22px]">🎓</span>
                  <span className="text-[17px] font-bold text-slate-900 tracking-tight ml-0.5">AITeachMe</span>
                  <span className="text-[9px] text-slate-500 font-bold bg-slate-100 px-1.5 py-0.5 rounded ml-0.5">v1</span>
                </motion.div>
              </Link>
            )}
          </AnimatePresence>
          <button
            type="button"
            onClick={() => setIsCollapsed(!isCollapsed)}
            className="rounded-md p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
            title={effectiveCollapsed ? "展开侧边栏" : "收起侧边栏"}
          >
            {isCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </button>
        </div>

        {/* Toggle button moved to header */}

        <div className="space-y-2 p-3 shrink-0">
          <Button
            onClick={() => {
              if (effectiveCollapsed) setIsCollapsed(false);
              setShowNewForm(!showNewForm);
            }}
            variant="outline"
            className={cn(
              "w-full bg-slate-50 border-slate-200 text-slate-700 hover:bg-slate-100 hover:text-slate-900 transition-all shadow-sm",
              effectiveCollapsed ? "justify-center px-0 h-10 w-10 mx-auto" : "justify-start px-3"
            )}
            title={effectiveCollapsed ? "新建学科" : undefined}
          >
            <Plus className="h-4 w-4 shrink-0 shadow-sm" />
            {!effectiveCollapsed && <span className="ml-2 font-medium">新建学科</span>}
          </Button>

          <AnimatePresence>
            {!effectiveCollapsed && showNewForm && (
              <NewSubjectForm
                onSubmit={(name, desc) => {
                  setCreateError(undefined);
                  setSubjectActionError(undefined);
                  createMutation.mutate({ name, description: desc });
                }}
                onCancel={() => {
                  setShowNewForm(false);
                  setCreateError(undefined);
                }}
                isPending={createMutation.isPending}
                error={createError}
              />
            )}
          </AnimatePresence>

          {subjectActionError && !effectiveCollapsed && (
            <p className="px-1 text-xs text-red-500 font-medium">{subjectActionError}</p>
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-3 pb-4 stylish-scrollbar">
          {isLoading && (
            <div className="flex flex-col items-center justify-center py-6 text-slate-400">
              <Loader2 className="h-5 w-5 animate-spin" />
              {!effectiveCollapsed && <span className="mt-2 text-xs font-medium">加载中...</span>}
            </div>
          )}

          {subjects.map((subject: SubjectItem) => (
            <div key={subject.subject_id} className="mb-1.5 min-w-[36px]">
              <div className="group flex items-center w-full">
                <button
                  onClick={() => toggleSubject(subject.subject_id)}
                  className={cn(
                    "flex flex-1 items-center rounded-lg py-2 transition-all duration-200",
                    expandedSubjects.has(subject.subject_id) ? "bg-slate-50/80" : "hover:bg-slate-100/60",
                    effectiveCollapsed ? "justify-center px-0 mx-auto w-12" : "px-2"
                  )}
                  title={effectiveCollapsed ? subject.name : undefined}
                >
                  {effectiveCollapsed ? (
                    <div 
                      className="w-[26px] h-[26px] rounded-md text-white flex items-center justify-center font-bold text-[12px] shadow-sm transition-transform duration-300 hover:scale-[1.04]" 
                      style={getStyleForSubject(subject.name)}
                    >
                      {subject.name.charAt(0).toUpperCase()}
                    </div>
                  ) : (
                    <>
                      <motion.div
                         animate={{ rotate: expandedSubjects.has(subject.subject_id) ? 90 : 0 }}
                         transition={{ duration: 0.15 }}
                         className="mr-1.5 flex items-center justify-center"
                      >
                         <ChevronRight className="h-4 w-4 shrink-0 text-slate-400 group-hover:text-slate-600 transition-colors" />
                      </motion.div>
                      <div 
                        className="w-6 h-6 rounded-md text-white flex items-center justify-center font-bold text-[11px] shadow-[0_1px_4px_rgba(0,0,0,0.1)] mr-2.5 shrink-0"
                        style={getStyleForSubject(subject.name)}
                      >
                         {subject.name.charAt(0).toUpperCase()}
                      </div>
                      <span className="truncate text-[13px] font-semibold text-slate-700/90 group-hover:text-slate-900 transition-colors tracking-wide max-w-[130px]">{subject.name}</span>
                    </>
                  )}
                </button>
                {!effectiveCollapsed && (
                  <div className="relative" ref={openMenuId === subject.subject_id ? menuRef : undefined}>
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setOpenMenuId(openMenuId === subject.subject_id ? null : subject.subject_id); }}
                      className="mr-1 rounded p-1.5 text-slate-400 opacity-0 transition-all hover:bg-slate-100 hover:text-slate-700 group-hover:opacity-100 focus:opacity-100"
                      title="更多操作"
                    >
                      <MoreVertical className="h-3.5 w-3.5" />
                    </button>
                    <AnimatePresence>
                      {openMenuId === subject.subject_id && (
                        <motion.div
                          initial={{ opacity: 0, scale: 0.95, y: -4 }}
                          animate={{ opacity: 1, scale: 1, y: 0 }}
                          exit={{ opacity: 0, scale: 0.95, y: -4 }}
                          transition={{ duration: 0.12 }}
                          className="absolute right-0 top-full mt-1 w-32 bg-white rounded-lg border border-slate-200 shadow-lg overflow-hidden z-50"
                        >
                          <button
                            type="button"
                            onClick={() => { setOpenMenuId(null); setRenameTarget({ id: subject.subject_id, name: subject.name }); }}
                            className="w-full flex items-center gap-2 px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 transition-colors"
                          >
                            <Edit3 className="w-3.5 h-3.5 text-slate-400" /> 重命名
                          </button>
                          <button
                            type="button"
                            onClick={() => { setOpenMenuId(null); setExportSubjectId(subject.subject_id); }}
                            className="w-full flex items-center gap-2 px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 transition-colors border-t border-slate-100"
                          >
                            <Download className="w-3.5 h-3.5 text-slate-400" /> 导出
                          </button>
                          <button
                            type="button"
                            onClick={() => { setOpenMenuId(null); openDeleteModal(subject); }}
                            className="w-full flex items-center gap-2 px-3 py-2 text-xs text-red-600 hover:bg-red-50 transition-colors border-t border-slate-100"
                          >
                            <Trash2 className="w-3.5 h-3.5" /> 删除
                          </button>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                )}
              </div>

              <AnimatePresence>
                {!effectiveCollapsed && expandedSubjects.has(subject.subject_id) && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="ml-6 mt-1 space-y-0.5 overflow-hidden border-l border-slate-200/60 pl-2.5 py-1"
                  >
                    {MODULES.map((moduleItem) => {
                      const path = `/subject/${subject.subject_id}/${moduleItem.id}`;
                      const isActive = location.pathname === path;
                      return (
                        <Link
                          key={moduleItem.id}
                          to={path}
                          onClick={() => setIsMobileOpen(false)}
                          className={cn(
                            "flex items-center rounded-md px-2.5 py-1.5 text-[13px] font-medium transition-all duration-200 relative group",
                            isActive
                              ? "bg-slate-100/70 text-slate-900"
                              : "text-slate-500 hover:bg-slate-50/80 hover:text-slate-700"
                          )}
                        >
                          {isActive && (
                            <motion.div 
                              layoutId={`indicator-${subject.subject_id}`}
                              className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-[14px] bg-slate-800 rounded-full -ml-[11px]"
                            />
                          )}
                          <span className={cn("mr-2.5 transition-colors duration-200 opacity-90", isActive ? "text-slate-700" : "text-slate-400 group-hover:text-slate-500")}>
                            {moduleItem.icon}
                          </span>
                          {moduleItem.name}
                        </Link>
                      );
                    })}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          ))}
        </div>
      </motion.aside>

      <SubjectDeleteConfirmModal
        open={isDeleteModalOpen}
        subject={deleteTarget}
        preview={deletePreview}
        isPreviewLoading={deletePreviewMutation.isPending}
        previewError={deletePreviewMutation.isError ? getApiErrorMessage(deletePreviewMutation.error, "删除预览失败") : undefined}
        isDeleting={deleteMutation.isPending}
        deleteError={deleteMutation.isError ? getApiErrorMessage(deleteMutation.error, "删除失败") : undefined}
        onClose={closeDeleteModal}
        onConfirm={() => {
          if (deleteTarget) deleteMutation.mutate(deleteTarget.subject_id);
        }}
      />

      {/* ── Export Modal ── */}
      <AnimatePresence>
        {exportSubjectId && (
          <SidebarExportModal
            key="export"
            subjectId={exportSubjectId}
            onClose={() => setExportSubjectId(null)}
          />
        )}
      </AnimatePresence>

      {/* ── Rename Modal ── */}
      <AnimatePresence>
        {renameTarget && (
          <SidebarRenameModal
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

/* ── Sidebar Export Modal (inline) ── */

interface ApiResponse<T> { code: number; data: T; }

interface ExportPreviewStats {
  raw_file_count: number;
  total_raw_file_size_bytes: number;
  knowledge_document_count: number;
  knowledge_node_count: number;
  knowledge_edge_count: number;
  teaching_unit_count: number;
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

function formatBytes(bytes?: number | null): string {
  if (bytes == null || !Number.isFinite(bytes)) return "未知";
  const units = ["B", "KB", "MB", "GB"];
  let v = bytes, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return `${v >= 10 || i === 0 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`;
}

function SidebarExportModal({ subjectId, onClose }: { subjectId: string; onClose: () => void }) {
  const { data: preview, isLoading } = useQuery({
    queryKey: ["export-preview", subjectId],
    queryFn: async () => {
      const resp = await apiClient<ApiResponse<ExportPreviewData>>({
        method: "POST",
        url: `/api/v1/subjects/${subjectId}/export/preview`,
      });
      return resp.data;
    },
  });

  const exportMutation = useMutation({
    mutationFn: async () => {
      const token = localStorage.getItem("token");
      const base = import.meta.env.VITE_API_URL ?? "";
      const resp = await fetch(`${base}/api/v1/subjects/${subjectId}/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({}),
      });
      if (!resp.ok) throw new Error(`导出失败 (${resp.status})`);
      const blob = await resp.blob();
      const disposition = resp.headers.get("content-disposition");
      let filename = `${subjectId}.atmx`;
      if (disposition) {
        const m = disposition.match(/filename[^;=\n]*=["']?([^"';\n]*)["']?/);
        if (m?.[1]) filename = m[1];
      }
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(a.href);
    },
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
        className="relative z-10 w-[460px] max-w-[90vw] bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden"
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 shadow-sm">
              <Package className="w-4 h-4 text-white" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-900">导出学科</h3>
              <p className="text-xs text-slate-500">{preview?.subject_name ?? "加载中…"}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors" title="关闭">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-6 py-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
              <span className="ml-2 text-sm text-slate-500">正在统计…</span>
            </div>
          ) : stats ? (
            <div className="grid grid-cols-2 gap-2">
              {[
                { label: "上传文件", value: stats.raw_file_count },
                { label: "知识文档", value: stats.knowledge_document_count },
                { label: "知识节点", value: stats.knowledge_node_count },
                { label: "知识边", value: stats.knowledge_edge_count },
                { label: "教学单元", value: stats.teaching_unit_count },
              ].map(({ label, value }) => (
                <div key={label} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2">
                  <span className="text-xs text-slate-500">{label}</span>
                  <span className="text-sm font-semibold text-slate-800">{value}</span>
                </div>
              ))}
              <div className="col-span-2 text-xs text-slate-400 mt-1">
                预计体积 {formatBytes(preview?.estimated_size_bytes)}
              </div>
            </div>
          ) : null}
        </div>
        <div className="flex items-center justify-end gap-3 px-6 py-3 border-t border-slate-100 bg-slate-50/50">
          <button onClick={onClose} className="px-3 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-800 rounded-lg hover:bg-slate-100 transition-colors">取消</button>
          <button
            onClick={() => exportMutation.mutate()}
            disabled={isLoading || exportMutation.isPending}
            className={cn(
              "flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-bold transition-all",
              !isLoading && !exportMutation.isPending
                ? "bg-slate-900 text-white hover:bg-slate-800 shadow-sm"
                : "bg-slate-200 text-slate-400 cursor-not-allowed"
            )}
          >
            {exportMutation.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
            {exportMutation.isPending ? "导出中…" : "导出"}
          </button>
        </div>
      </motion.div>
    </div>
  );
}

/* ── Sidebar Rename Modal (inline) ── */

function SidebarRenameModal({
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
        data: { subject_id: subjectId, name: name.trim(), description: "" },
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
        className="relative z-10 w-[380px] max-w-[90vw] bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden"
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-100">
          <h3 className="text-sm font-bold text-slate-900">重命名学科</h3>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors" title="关闭">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-5 py-4">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) renameMutation.mutate(); }}
            placeholder="输入学科名称"
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-300 transition-colors"
            autoFocus
          />
          {renameMutation.isError && (
            <p className="mt-2 text-xs text-red-600">{getApiErrorMessage(renameMutation.error, "重命名失败")}</p>
          )}
        </div>
        <div className="flex items-center justify-end gap-3 px-5 py-3 border-t border-slate-100 bg-slate-50/50">
          <button onClick={onClose} className="px-3 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-800 rounded-lg hover:bg-slate-100 transition-colors">取消</button>
          <button
            onClick={() => renameMutation.mutate()}
            disabled={!name.trim() || renameMutation.isPending}
            className={cn(
              "flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-bold transition-all",
              name.trim() && !renameMutation.isPending
                ? "bg-slate-900 text-white hover:bg-slate-800 shadow-sm"
                : "bg-slate-200 text-slate-400 cursor-not-allowed"
            )}
          >
            {renameMutation.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
            确认
          </button>
        </div>
      </motion.div>
    </div>
  );
}
