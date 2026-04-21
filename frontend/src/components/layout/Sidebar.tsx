import { useEffect, useMemo, useRef, useState } from "react";
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
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Settings,
  Sparkles,
  Trash2,
  X,
  MessageCircle,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteSubjectApiApiV1SubjectsDeletePost,
  listSubjectsApiApiV1SubjectsListPost,
  previewDeleteSubjectApiApiV1SubjectsDeletePreviewPost,
} from "../../api/generated/subjects";
import type { SubjectDeletePreviewData, SubjectItem } from "../../api/generated/model";
import { apiClient, getApiErrorMessage } from "../../api/client";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { downloadSubjectPackage } from "../../lib/subjectPackage";
import { cn } from "../../lib/utils";
import { SubjectDeleteConfirmModal } from "./SubjectDeleteConfirmModal";
import { CommunityModal } from "./CommunityPanel";

import { Button } from "../ui/Button";

const MODULES = [
  { id: "build", name: "构建", icon: Sparkles },
  { id: "knowledge-docs", name: "知识库", icon: BookOpen },
  { id: "exams", name: "考试", icon: FileText },
  { id: "profile", name: "学习画像", icon: BarChart3 },
  { id: "knowledge-debug", name: "知识调试", icon: BookOpen },
] as const;

const COLOR_CLASSES = [
  "bg-slate-900",
  "bg-emerald-600",
  "bg-rose-600",
  "bg-indigo-600",
  "bg-cyan-600",
  "bg-amber-600",
];

function colorClassForSubject(name: string) {
  let hash = 0;
  for (let index = 0; index < name.length; index += 1) {
    hash = name.charCodeAt(index) + ((hash << 5) - hash);
  }
  return COLOR_CLASSES[Math.abs(hash) % COLOR_CLASSES.length];
}

function RenameSubjectModal({
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
        url: "/api/v1/subjects/update",
        data: { subject_id: subjectId, name: name.trim() },
      });
    },
    onSuccess: () => {
      onSuccess();
      onClose();
    },
  });

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-[380px] max-w-[90vw] rounded-2xl border border-slate-200 bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h3 className="text-sm font-bold text-slate-900">重命名学科</h3>
          <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-3 px-5 py-4">
          <input
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && name.trim()) {
                renameMutation.mutate();
              }
            }}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-300"
            placeholder="输入学科名称"
            autoFocus
          />
          {renameMutation.isError ? (
            <p className="text-xs text-red-600">{getApiErrorMessage(renameMutation.error, "重命名失败，请重试")}</p>
          ) : null}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-100 bg-slate-50 px-5 py-3">
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={() => renameMutation.mutate()} disabled={!name.trim() || renameMutation.isPending}>
            {renameMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            确认
          </Button>
        </div>
      </div>
    </div>
  );
}

function displaySubjectName(subject: SubjectItem): string {
  return subject.name?.trim() || "无标题";
}

export function Sidebar({ onOpenSettings }: { onOpenSettings?: () => void }) {
  const [expandedSubjects, setExpandedSubjects] = useState<Set<string>>(new Set());
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [subjectActionError, setSubjectActionError] = useState<string>();
  const [deleteTarget, setDeleteTarget] = useState<SubjectItem | null>(null);
  const [deletePreview, setDeletePreview] = useState<SubjectDeletePreviewData | null>(null);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<{ id: string; name: string } | null>(null);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [isCommunityModalOpen, setIsCommunityModalOpen] = useState(false);
  const [exportingSubjectId, setExportingSubjectId] = useState<string | null>(null);

  const menuRef = useRef<HTMLDivElement>(null);
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
    if (!openMenuId) {
      return;
    }
    const handlePointerDown = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setOpenMenuId(null);
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [openMenuId]);

  useEffect(() => {
    const match = location.pathname.match(/^\/subject\/([^/]+)/);
    if (!match?.[1]) {
      return;
    }
    setExpandedSubjects((prev) => new Set([...prev, match[1]]));
    setIsCollapsed(false);
  }, [location.pathname]);

  const deletePreviewMutation = useMutation({
    mutationFn: async (subjectId: string) =>
      unwrapOrvalResponse(
        await previewDeleteSubjectApiApiV1SubjectsDeletePreviewPost({ subject_id: subjectId }),
      ) ?? null,
    onSuccess: (preview) => {
      setDeletePreview(preview);
      setSubjectActionError(undefined);
    },
    onError: (error) => {
      setDeletePreview(null);
      setSubjectActionError(getApiErrorMessage(error, "删除预览加载失败，请重试"));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (subjectId: string) => {
      await deleteSubjectApiApiV1SubjectsDeletePost({ subject_id: subjectId, force: true });
    },
    onSuccess: (_, subjectId) => {
      void queryClient.invalidateQueries({ queryKey: ["subjects"] });
      setSubjectActionError(undefined);
      setIsDeleteModalOpen(false);
      setDeleteTarget(null);
      setDeletePreview(null);
      if (location.pathname.startsWith(`/subject/${subjectId}/`)) {
        navigate("/");
      }
    },
    onError: (error) => {
      setSubjectActionError(getApiErrorMessage(error, "删除失败，请重试"));
    },
  });

  const groupedSubjects = useMemo(() => subjects as SubjectItem[], [subjects]);

  const toggleSubject = (subjectId: string) => {
    if (effectiveCollapsed) {
      setIsCollapsed(false);
      return;
    }
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

  const openDeleteModal = (subject: SubjectItem) => {
    setDeleteTarget(subject);
    setDeletePreview(null);
    setSubjectActionError(undefined);
    setIsDeleteModalOpen(true);
    deletePreviewMutation.reset();
    deleteMutation.reset();
    deletePreviewMutation.mutate(subject.subject_id);
  };

  async function handleExportSubject(subject: SubjectItem) {
    setSubjectActionError(undefined);
    setExportingSubjectId(subject.subject_id);
    try {
      await downloadSubjectPackage(subject.subject_id);
    } catch (error: unknown) {
      setSubjectActionError(getApiErrorMessage(error, "导出失败，请重试"));
    } finally {
      setExportingSubjectId((current) => (current === subject.subject_id ? null : current));
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setIsMobileOpen((prev) => !prev)}
        className="fixed left-4 top-4 z-50 rounded-lg border border-slate-200 bg-white p-2 shadow-sm lg:hidden"
      >
        {isMobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
      </button>

      {isMobileOpen ? (
        <div className="fixed inset-0 z-30 bg-black/20 backdrop-blur-sm lg:hidden" onClick={() => setIsMobileOpen(false)} />
      ) : null}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex shrink-0 flex-col border-r border-slate-200/50 bg-gradient-to-b from-white/90 to-white/50 backdrop-blur-2xl shadow-[4px_0_30px_rgba(0,0,0,0.03)] ring-1 ring-white/50 transition-all lg:static",
          effectiveCollapsed ? "w-[64px]" : "w-[240px]",
          isMobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
        )}
      >
        <div
          className={cn(
            "flex h-14 items-center border-b border-slate-100",
            effectiveCollapsed ? "justify-center px-0" : "justify-between px-4",
          )}
        >
          {!effectiveCollapsed ? (
            <Link to="/" className="flex items-center gap-2 text-slate-900">
              <span className="text-lg font-bold">AITeachMe</span>
            </Link>
          ) : null}
          <button
            type="button"
            onClick={() => setIsCollapsed((prev) => !prev)}
            className="flex h-6 w-6 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
            title={effectiveCollapsed ? "展开侧边栏" : "收起侧边栏"}
          >
            {effectiveCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </button>
        </div>

        <div className={cn("space-y-2", effectiveCollapsed ? "px-0 py-3" : "p-3")}>
          {effectiveCollapsed ? (
            <div className="flex justify-center">
              <button
                type="button"
                onClick={() => {
                  setSubjectActionError(undefined);
                  setOpenMenuId(null);
                  setIsMobileOpen(false);
                  setIsCollapsed(false);
                  navigate("/", {
                    state: { newEntryAt: Date.now() },
                  });
                }}
                title="新建学科"
                className="flex h-6 w-6 items-center justify-center rounded border border-slate-200 bg-white text-slate-700 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900"
              >
                <Plus className="h-4 w-4 shrink-0" />
              </button>
            </div>
          ) : (
            <Button
              variant="outline"
              className="w-full justify-start"
              onClick={() => {
                setSubjectActionError(undefined);
                setOpenMenuId(null);
                setIsMobileOpen(false);
                navigate("/", {
                  state: { newEntryAt: Date.now() },
                });
              }}
            >
              <Plus className="h-4 w-4 shrink-0" />
              <span className="ml-2">新建学科</span>
            </Button>
          )}

          {!effectiveCollapsed && subjectActionError ? (
            <p className="px-1 text-xs text-red-500">{subjectActionError}</p>
          ) : null}
        </div>

        <div className="flex-1 overflow-y-auto overflow-x-hidden px-3 pb-4 space-y-1 scrollbar-thin scrollbar-webkit">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center py-6 text-slate-400">
              <Loader2 className="h-5 w-5 animate-spin" />
              {!effectiveCollapsed ? <span className="mt-2 text-xs">加载中…</span> : null}
            </div>
          ) : null}

          {groupedSubjects.map((subject) => {
            const expanded = expandedSubjects.has(subject.subject_id);
            const activeSubject = location.pathname.startsWith(`/subject/${subject.subject_id}/`);
            const displayName = displaySubjectName(subject);
            const badgeClass = colorClassForSubject(subject.name || subject.subject_id);

            return (
              <div key={subject.subject_id} className="relative">
                <div className="group flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => {
                      if (effectiveCollapsed) {
                        setIsCollapsed(false);
                        if (!expanded) {
                          toggleSubject(subject.subject_id);
                        }
                      } else {
                        toggleSubject(subject.subject_id);
                      }
                    }}
                    className={cn(
                      "flex items-center transition-colors",
                      effectiveCollapsed ? "h-8 w-full justify-center rounded px-0" : "flex-1 rounded-lg px-2 py-2",
                      activeSubject || expanded ? "bg-slate-100/60" : "hover:bg-slate-100/60",
                    )}
                    title={effectiveCollapsed ? displayName : undefined}
                  >
                    {effectiveCollapsed ? null : (
                      <ChevronRight className={cn("mr-1.5 h-4 w-4 shrink-0 text-slate-400 transition-transform", expanded ? "rotate-90" : "rotate-0")} />
                    )}
                    <div className={cn("flex shrink-0 items-center justify-center font-bold text-white shadow-sm", 
                      effectiveCollapsed ? "h-6 w-6 rounded text-[11px]" : "h-7 w-7 rounded-md text-xs",
                      badgeClass
                    )}>
                      {(subject.name.trim().charAt(0) || "新").toUpperCase()}
                    </div>
                    {!effectiveCollapsed ? <span className="ml-2 truncate text-sm font-medium text-slate-700">{displayName}</span> : null}
                  </button>

                  {!effectiveCollapsed ? (
                    <div className="relative" ref={openMenuId === subject.subject_id ? menuRef : undefined}>
                      <button
                        type="button"
                        onClick={() => setOpenMenuId((prev) => (prev === subject.subject_id ? null : subject.subject_id))}
                        className="rounded-md p-1.5 text-slate-400 opacity-0 transition hover:bg-slate-100 hover:text-slate-700 group-hover:opacity-100"
                        title="更多操作"
                      >
                        <MoreVertical className="h-4 w-4" />
                      </button>

                      {openMenuId === subject.subject_id ? (
                        <div className="absolute right-0 top-full z-50 mt-1 w-32 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg">
                          <button
                            type="button"
                            onClick={() => {
                              setOpenMenuId(null);
                              void handleExportSubject(subject);
                            }}
                            disabled={exportingSubjectId === subject.subject_id}
                            className="flex w-full items-center gap-2 px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
                          >
                            {exportingSubjectId === subject.subject_id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" />
                            ) : (
                              <Download className="h-3.5 w-3.5 text-slate-400" />
                            )}
                            导出 .atmx
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setOpenMenuId(null);
                              setRenameTarget({ id: subject.subject_id, name: displayName === "无标题" ? "" : subject.name });
                            }}
                            className="flex w-full items-center gap-2 border-t border-slate-100 px-3 py-2 text-xs text-slate-700 hover:bg-slate-50"
                          >
                            <Edit3 className="h-3.5 w-3.5 text-slate-400" />
                            重命名
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setOpenMenuId(null);
                              openDeleteModal(subject);
                            }}
                            className="flex w-full items-center gap-2 border-t border-slate-100 px-3 py-2 text-xs text-red-600 hover:bg-red-50"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                            删除
                          </button>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>

                {!effectiveCollapsed && expanded ? (
                  <div className="ml-6 mt-1 space-y-1 border-l border-slate-200 pl-3">
                    {MODULES.map((moduleItem) => {
                      const path = `/subject/${subject.subject_id}/${moduleItem.id}`;
                      const isActive = location.pathname === path;
                      const Icon = moduleItem.icon;
                      return (
                        <Link
                          key={moduleItem.id}
                          to={path}
                          onClick={() => setIsMobileOpen(false)}
                          className={cn(
                            "flex items-center rounded-md px-2.5 py-1.5 text-sm transition-colors",
                            isActive ? "bg-slate-100 text-slate-900" : "text-slate-500 hover:bg-slate-50 hover:text-slate-700",
                          )}
                        >
                          <Icon className="mr-2.5 h-4 w-4" />
                          {moduleItem.name}
                        </Link>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>

        {/* Bottom actions */}
        <div className="border-t border-slate-200/80 p-2.5 space-y-1 z-10">
          <button
            type="button"
            onClick={() => setIsCommunityModalOpen(true)}
            className={cn(
              "flex items-center text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700",
              effectiveCollapsed ? "h-6 w-6 justify-center rounded mx-auto" : "w-full rounded-lg py-2 gap-2.5 px-3",
            )}
            title="社区"
          >
            <MessageCircle className="h-4 w-4 shrink-0" />
            {!effectiveCollapsed ? <span className="text-sm">社区</span> : null}
          </button>
          <button
            type="button"
            onClick={onOpenSettings}
            className={cn(
              "flex items-center text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700",
              effectiveCollapsed ? "h-6 w-6 justify-center rounded mx-auto" : "w-full rounded-lg py-2 gap-2.5 px-3",
            )}
            title="设置"
          >
            <Settings className="h-4 w-4 shrink-0" />
            {!effectiveCollapsed ? <span className="text-sm">设置</span> : null}
          </button>
        </div>
      </aside>

      <SubjectDeleteConfirmModal
        open={isDeleteModalOpen}
        subject={deleteTarget}
        preview={deletePreview}
        isPreviewLoading={deletePreviewMutation.isPending}
        previewError={deletePreviewMutation.isError ? getApiErrorMessage(deletePreviewMutation.error, "删除预览失败") : undefined}
        isDeleting={deleteMutation.isPending}
        deleteError={deleteMutation.isError ? getApiErrorMessage(deleteMutation.error, "删除失败") : undefined}
        onClose={() => {
          setIsDeleteModalOpen(false);
          setDeleteTarget(null);
          setDeletePreview(null);
        }}
        onConfirm={() => {
          if (deleteTarget) {
            deleteMutation.mutate(deleteTarget.subject_id);
          }
        }}
      />

      {renameTarget ? (
        <RenameSubjectModal
          subjectId={renameTarget.id}
          initialName={renameTarget.name}
          onClose={() => setRenameTarget(null)}
          onSuccess={() => void queryClient.invalidateQueries({ queryKey: ["subjects"] })}
        />
      ) : null}

      <CommunityModal isOpen={isCommunityModalOpen} onClose={() => setIsCommunityModalOpen(false)} />
    </>
  );
}
