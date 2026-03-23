import { memo, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  BarChart3,
  BookOpen,
  ChevronDown,
  ChevronRight,
  FileText,
  FileEdit,
  Loader2,
  Menu,
  Plus,
  Trash2,
  Upload,
  X,
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
import { getApiErrorMessage } from "../../api/client";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { cn } from "../../lib/utils";
import { SubjectDeleteConfirmModal } from "./SubjectDeleteConfirmModal";
import { Button } from "../ui/Button";

const MODULES = [
  { id: "upload", name: "上传资料", icon: <Upload className="w-4 h-4" /> },
  { id: "summary", name: "知识总结", icon: <BookOpen className="w-4 h-4" /> },
  { id: "exam", name: "考题预测", icon: <FileText className="w-4 h-4" /> },
  { id: "analysis", name: "学习分析", icon: <BarChart3 className="w-4 h-4" /> },
  { id: "doc", name: "文档", icon: <FileEdit className="w-4 h-4" /> },
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
  const [isCollapsed, setIsCollapsed] = useState(true); // Default collapsed on desktop
  const [showNewForm, setShowNewForm] = useState(false);
  const [createError, setCreateError] = useState<string | undefined>();
  const [subjectActionError, setSubjectActionError] = useState<string | undefined>();
  const [deleteTarget, setDeleteTarget] = useState<SubjectItem | null>(null);
  const [deletePreview, setDeletePreview] = useState<SubjectDeletePreviewData | null>(null);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);

  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

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
      navigate(`/subject/${created.subject_id}/upload`);
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
    if (isCollapsed) setIsCollapsed(false);
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
        animate={{ width: isCollapsed ? 76 : 280 }}
        transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1] }}
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex flex-col border-r border-slate-200 bg-white shadow-sm lg:static overflow-hidden shrink-0",
          isMobileOpen ? "translate-x-0 w-[280px]" : "-translate-x-full lg:translate-x-0"
        )}
      >
        <div className="border-b border-slate-100 p-4 flex items-center justify-between h-16 shrink-0">
          <AnimatePresence mode="popLayout">
            {!isCollapsed && (
              <motion.h1
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -10 }}
                className="text-lg font-extrabold text-slate-900 tracking-tight whitespace-nowrap overflow-hidden"
              >
                AI 赛博私教
              </motion.h1>
            )}
          </AnimatePresence>
          <button
            onClick={() => setIsCollapsed(!isCollapsed)}
            className="hidden lg:flex p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-800 transition-colors mx-auto lg:mx-0"
          >
            {isCollapsed ? <PanelLeftOpen className="w-5 h-5" /> : <PanelLeftClose className="w-5 h-5" />}
          </button>
        </div>

        <div className="space-y-2 p-3 shrink-0">
          <Button
            onClick={() => {
              if (isCollapsed) setIsCollapsed(false);
              setShowNewForm(!showNewForm);
            }}
            variant="outline"
            className={cn(
              "w-full bg-slate-50 border-slate-200 text-slate-700 hover:bg-slate-100 hover:text-slate-900 transition-all shadow-sm",
              isCollapsed ? "justify-center px-0 h-10 w-10 mx-auto" : "justify-start px-3"
            )}
            title={isCollapsed ? "新建学科" : undefined}
          >
            <Plus className="h-4 w-4 shrink-0 shadow-sm" />
            {!isCollapsed && <span className="ml-2 font-medium">新建学科</span>}
          </Button>

          <AnimatePresence>
            {!isCollapsed && showNewForm && (
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

          {subjectActionError && !isCollapsed && (
            <p className="px-1 text-xs text-red-500 font-medium">{subjectActionError}</p>
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-3 pb-4 stylish-scrollbar">
          {isLoading && (
            <div className="flex flex-col items-center justify-center py-6 text-slate-400">
              <Loader2 className="h-5 w-5 animate-spin" />
              {!isCollapsed && <span className="mt-2 text-xs font-medium">加载中...</span>}
            </div>
          )}

          {subjects.map((subject: SubjectItem) => (
            <div key={subject.subject_id} className="mb-1.5 min-w-[36px]">
              <div className="group flex items-center w-full">
                <button
                  onClick={() => toggleSubject(subject.subject_id)}
                  className={cn(
                    "flex flex-1 items-center rounded-lg py-2 transition-all hover:bg-slate-100",
                    isCollapsed ? "justify-center px-0 mx-auto w-10" : "px-3"
                  )}
                  title={isCollapsed ? subject.name : undefined}
                >
                  {isCollapsed ? (
                    <div className="w-6 h-6 rounded bg-slate-100 border border-slate-200 text-slate-800 flex items-center justify-center font-bold text-xs">
                      {subject.name.charAt(0).toUpperCase()}
                    </div>
                  ) : (
                    <>
                      {expandedSubjects.has(subject.subject_id) ? (
                        <ChevronDown className="mr-2 h-4 w-4 shrink-0 text-slate-400" />
                      ) : (
                        <ChevronRight className="mr-2 h-4 w-4 shrink-0 text-slate-400" />
                      )}
                      <span className="truncate text-sm font-medium text-slate-700">{subject.name}</span>
                    </>
                  )}
                </button>
                {!isCollapsed && (
                  <button
                    onClick={() => openDeleteModal(subject)}
                    disabled={deletePreviewMutation.isPending || deleteMutation.isPending}
                    className="mr-1 rounded p-1.5 text-slate-400 opacity-0 transition-all hover:bg-red-50 hover:text-red-600 group-hover:opacity-100 focus:opacity-100"
                    title="删除学科"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>

              <AnimatePresence>
                {!isCollapsed && expandedSubjects.has(subject.subject_id) && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="ml-6 mt-1 space-y-0.5 overflow-hidden border-l border-slate-100 pl-2 py-1"
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
                            "flex items-center rounded-md px-3 py-1.5 text-xs font-medium transition-all",
                            isActive
                              ? "bg-slate-100/80 text-slate-900 shadow-sm"
                              : "text-slate-500 hover:bg-slate-100/50 hover:text-slate-900"
                          )}
                        >
                          <span className={cn("mr-2", isActive ? "text-slate-700" : "text-slate-400")}>
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
    </>
  );
}
