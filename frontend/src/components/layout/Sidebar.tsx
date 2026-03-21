import { memo, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  BarChart3,
  BookOpen,
  ChevronDown,
  ChevronRight,
  FileText,
  Loader2,
  Menu,
  MessageSquare,
  Plus,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createSubject,
  deleteSubject,
  fetchSubjectDeletePreview,
  fetchSubjects,
  type SubjectDeletePreviewData,
  type SubjectItem,
} from "../../api/subjectsApi";
import { getApiErrorMessage } from "../../api/client";
import { cn } from "../../lib/utils";
import { SubjectDeleteConfirmModal } from "./SubjectDeleteConfirmModal";
import { Button } from "../ui/Button";

const MODULES = [
  { id: "chat", name: "对话", icon: <MessageSquare className="h-4 w-4" /> },
  { id: "upload", name: "上传资料", icon: <Upload className="h-4 w-4" /> },
  { id: "summary", name: "知识总结", icon: <BookOpen className="h-4 w-4" /> },
  { id: "exam", name: "考试练习", icon: <FileText className="h-4 w-4" /> },
  { id: "analysis", name: "学习分析", icon: <BarChart3 className="h-4 w-4" /> },
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
    if (!name.trim()) {
      return;
    }
    onSubmit(name.trim(), description.trim());
  };

  return (
    <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
      <input
        ref={nameInputRef}
        className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-300"
        placeholder="学科名称，例如：高等数学"
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      <textarea
        className="min-h-20 w-full resize-y rounded-md border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-300"
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
    </div>
  );
});

export function Sidebar() {
  const [expandedSubjects, setExpandedSubjects] = useState<Set<string>>(new Set());
  const [isMobileOpen, setIsMobileOpen] = useState(false);
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
    queryFn: fetchSubjects,
  });

  useEffect(() => {
    const match = location.pathname.match(/^\/subject\/([^/]+)/);
    if (!match?.[1]) {
      return;
    }
    setExpandedSubjects((prev) => new Set([...prev, match[1]]));
  }, [location.pathname]);

  const createMutation = useMutation({
    mutationFn: createSubject,
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["subjects"] });
      setExpandedSubjects((prev) => new Set([...prev, created.subject_id]));
      setShowNewForm(false);
      setCreateError(undefined);
      setSubjectActionError(undefined);
      navigate(`/subject/${created.subject_id}/chat`);
    },
    onError: (error: unknown) => {
      setCreateError(getApiErrorMessage(error, "创建失败，请重试"));
    },
  });

  const deletePreviewMutation = useMutation({
    mutationFn: fetchSubjectDeletePreview,
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
    mutationFn: deleteSubject,
    onSuccess: (_, subjectId) => {
      queryClient.invalidateQueries({ queryKey: ["subjects"] });
      setSubjectActionError(undefined);
      closeDeleteModal();
      if (location.pathname.startsWith(`/subject/${subjectId}/`)) {
        navigate("/");
      }
    },
    onError: (error: unknown) => {
      setSubjectActionError(getApiErrorMessage(error, "删除失败，请重试"));
    },
  });

  const toggleSubject = (subjectId: string) => {
    setExpandedSubjects((prev) => {
      const next = new Set(prev);
      if (next.has(subjectId)) {
        next.delete(subjectId);
      } else {
        next.add(subjectId);
      }
      return next;
    });
  };

  const handleCreate = (name: string, description: string) => {
    setCreateError(undefined);
    setSubjectActionError(undefined);
    createMutation.mutate({ name, description });
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
    deletePreviewMutation.reset();
    deleteMutation.reset();
  };

  const previewError = deletePreviewMutation.isError
    ? getApiErrorMessage(deletePreviewMutation.error, "删除预览加载失败，请重试")
    : undefined;
  const deleteError = deleteMutation.isError
    ? getApiErrorMessage(deleteMutation.error, "删除失败，请重试")
    : undefined;

  return (
    <>
      <button
        onClick={() => setIsMobileOpen(!isMobileOpen)}
        className="fixed left-4 top-4 z-50 rounded-lg border border-slate-200 bg-white p-2 shadow-sm lg:hidden"
      >
        {isMobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
      </button>

      {isMobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/20 lg:hidden"
          onClick={() => setIsMobileOpen(false)}
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-slate-200 bg-white transition-transform duration-200 lg:static",
          isMobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
        )}
      >
        <div className="border-b border-slate-200 p-4">
          <h1 className="text-xl font-bold text-slate-900">AI TEACH ME</h1>
        </div>

        <div className="space-y-2 p-4">
          <Button
            onClick={() => setShowNewForm((value) => !value)}
            className="w-full justify-start"
          >
            <Plus className="h-4 w-4" />
            新建学科
          </Button>

          {showNewForm && (
            <NewSubjectForm
              onSubmit={handleCreate}
              onCancel={() => {
                setShowNewForm(false);
                setCreateError(undefined);
              }}
              isPending={createMutation.isPending}
              error={createError}
            />
          )}

          {subjectActionError && (
            <p className="px-0.5 text-xs text-red-500">{subjectActionError}</p>
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-3 pb-4">
          {isLoading && (
            <div className="flex items-center justify-center py-6 text-slate-400">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              加载中...
            </div>
          )}

          {subjects.map((subject) => (
            <div key={subject.subject_id} className="mb-2">
              <div className="group flex items-center">
                <button
                  onClick={() => toggleSubject(subject.subject_id)}
                  className="flex flex-1 items-center rounded-lg px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-100"
                >
                  {expandedSubjects.has(subject.subject_id) ? (
                    <ChevronDown className="mr-2 h-4 w-4 shrink-0" />
                  ) : (
                    <ChevronRight className="mr-2 h-4 w-4 shrink-0" />
                  )}
                  <span className="truncate">{subject.name}</span>
                </button>
                <button
                  onClick={() => openDeleteModal(subject)}
                  disabled={deletePreviewMutation.isPending || deleteMutation.isPending}
                  className="mr-1 rounded p-1 text-slate-400 opacity-0 transition-all hover:text-red-500 group-hover:opacity-100"
                  title="删除学科"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>

              {expandedSubjects.has(subject.subject_id) && (
                <div className="ml-6 mt-1 space-y-1">
                  {MODULES.map((moduleItem) => {
                    const path = `/subject/${subject.subject_id}/${moduleItem.id}`;
                    return (
                      <Link
                        key={moduleItem.id}
                        to={path}
                        onClick={() => setIsMobileOpen(false)}
                        className={cn(
                          "flex items-center rounded-lg px-3 py-2 text-sm transition-colors",
                          location.pathname === path
                            ? "bg-slate-100 font-medium text-slate-900"
                            : "text-slate-600 hover:bg-slate-50",
                        )}
                      >
                        {moduleItem.icon}
                        <span className="ml-2">{moduleItem.name}</span>
                      </Link>
                    );
                  })}
                </div>
              )}
            </div>
          ))}
        </div>
      </aside>

      <SubjectDeleteConfirmModal
        open={isDeleteModalOpen}
        subject={deleteTarget}
        preview={deletePreview}
        isPreviewLoading={deletePreviewMutation.isPending}
        previewError={previewError}
        isDeleting={deleteMutation.isPending}
        deleteError={deleteError}
        onClose={closeDeleteModal}
        onConfirm={() => {
          if (!deleteTarget) {
            return;
          }
          deleteMutation.mutate(deleteTarget.subject_id);
        }}
      />
    </>
  );
}
