import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  BarChart3,
  BookOpen,
  Download,
  Edit3,
  FileText,
  LayoutGrid,
  Loader2,
  Menu,
  MoreVertical,
  PanelLeftClose,
  PanelLeftOpen,
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
import { CommunityModal, ensureCommunityQrPreloaded } from "./CommunityPanel";

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
      <div
        className="absolute inset-0 modal-backdrop"
        onClick={onClose}
      />
      <div className="relative z-10 w-[380px] max-w-[90vw] rounded-2xl border border-slate-200 bg-white shadow-[0_18px_48px_-24px_rgba(15,23,42,0.35)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_24px_56px_-28px_rgba(0,0,0,0.72)]">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4 dark:border-slate-800">
          <h3 className="text-sm font-bold text-slate-900">重命名学科</h3>
          <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-200">
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
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:ring-slate-700"
            placeholder="输入学科名称"
            autoFocus
          />
          {renameMutation.isError ? (
            <p className="text-xs text-red-600">{getApiErrorMessage(renameMutation.error, "重命名失败，请重试")}</p>
          ) : null}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-100 bg-slate-50 px-5 py-3 dark:border-slate-800 dark:bg-slate-900/80">
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
  const isCreateSubjectActive = location.pathname === "/";
  const isMyLearningSpaceActive = location.pathname === "/spaces";

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
        className="fixed left-4 top-4 z-50 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-2 shadow-sm lg:hidden text-slate-700 dark:text-slate-300"
      >
        {isMobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
      </button>

      {isMobileOpen ? (
        <div className="fixed inset-0 z-30 modal-backdrop lg:hidden" onClick={() => setIsMobileOpen(false)} />
      ) : null}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex shrink-0 flex-col border-r border-slate-200/50 dark:border-slate-800/50 bg-gradient-to-b from-white/96 to-white/92 dark:from-[#0b0f19]/96 dark:to-[#0b0f19]/92 shadow-[4px_0_24px_rgba(0,0,0,0.03)] dark:shadow-[4px_0_24px_rgba(0,0,0,0.3)] ring-1 ring-white/50 dark:ring-white/5 transition-[width,transform] duration-200 lg:static",
          effectiveCollapsed ? "w-[64px]" : "w-[240px]",
          isMobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
        )}
      >
        <div
          className={cn(
            "flex h-14 items-center border-b border-slate-100 dark:border-slate-800/50",
            effectiveCollapsed ? "justify-center px-0" : "justify-between px-4",
          )}
        >
          {!effectiveCollapsed ? (
            <Link to="/" className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
              <img src="/logo.svg" alt="AITeachMe" className="h-5 w-auto dark:invert dark:opacity-90" />
            </Link>
          ) : null}
          <button
            type="button"
            onClick={() => setIsCollapsed((prev) => !prev)}
            className="flex h-6 w-6 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-800/50 dark:hover:text-slate-300 transition-colors"
            title={effectiveCollapsed ? "展开侧边栏" : "收起侧边栏"}
          >
            {effectiveCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </button>
        </div>

        <div className={cn("space-y-2", effectiveCollapsed ? "px-0 py-3" : "p-3")}>
          {effectiveCollapsed ? (
            <div className="flex flex-col items-center gap-2">
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
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-lg transition-colors",
                  isCreateSubjectActive
                    ? "bg-[#eef2f6] text-[#243246] ring-1 ring-[#d9e1ea] dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700"
                    : "text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/50 dark:hover:text-slate-200",
                )}
              >
                <Edit3 className="h-4 w-4 shrink-0" strokeWidth={2.2} />
              </button>

              <button
                type="button"
                onClick={() => {
                  setSubjectActionError(undefined);
                  setOpenMenuId(null);
                  setIsMobileOpen(false);
                  setIsCollapsed(false);
                  navigate("/spaces");
                }}
                title="我的学习空间"
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-lg transition-colors",
                  isMyLearningSpaceActive
                    ? "bg-[#eef2f6] text-[#243246] ring-1 ring-[#d9e1ea] dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700"
                    : "text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/50 dark:hover:text-slate-200",
                )}
              >
                <LayoutGrid className="h-4 w-4 shrink-0" strokeWidth={2.2} />
              </button>
            </div>
          ) : (
            <>
              <button
                type="button"
                className={cn(
                  "flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition-colors",
                  isCreateSubjectActive
                    ? "bg-[#f3f6f9] text-slate-950 ring-1 ring-[#dbe3ec] dark:bg-slate-800/80 dark:text-slate-100 dark:ring-slate-700"
                    : "text-slate-900 hover:bg-slate-100/80 dark:text-slate-300 dark:hover:bg-slate-800/40",
                )}
                onClick={() => {
                  setSubjectActionError(undefined);
                  setOpenMenuId(null);
                  setIsMobileOpen(false);
                  navigate("/", {
                    state: { newEntryAt: Date.now() },
                  });
                }}
              >
                <Edit3
                  className={cn("h-5 w-5 shrink-0", isCreateSubjectActive ? "text-[#4b607b] dark:text-slate-300" : "text-slate-500 dark:text-slate-400")}
                  strokeWidth={2.2}
                />
                <span
                  className={cn(
                    "text-[15px] tracking-[0.01em]",
                    isCreateSubjectActive ? "font-semibold text-[#1f2937] dark:text-slate-100" : "font-normal text-slate-900 dark:text-slate-300",
                  )}
                >
                  新建学科
                </span>
              </button>

              <button
                type="button"
                className={cn(
                  "flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition-colors",
                  isMyLearningSpaceActive
                    ? "bg-[#f3f6f9] text-slate-950 ring-1 ring-[#dbe3ec] dark:bg-slate-800/80 dark:text-slate-100 dark:ring-slate-700"
                    : "text-slate-900 hover:bg-slate-100/80 dark:text-slate-300 dark:hover:bg-slate-800/40",
                )}
                onClick={() => {
                  setSubjectActionError(undefined);
                  setOpenMenuId(null);
                  setIsMobileOpen(false);
                  navigate("/spaces");
                }}
              >
                <LayoutGrid
                  className={cn("h-5 w-5 shrink-0", isMyLearningSpaceActive ? "text-[#4b607b] dark:text-slate-300" : "text-slate-500 dark:text-slate-400")}
                  strokeWidth={2.2}
                />
                <span
                  className={cn(
                    "text-[15px] tracking-[0.01em]",
                    isMyLearningSpaceActive ? "font-semibold text-[#1f2937] dark:text-slate-100" : "font-normal text-slate-900 dark:text-slate-300",
                  )}
                >
                  我的学习空间
                </span>
              </button>
            </>
          )}

          {!effectiveCollapsed && subjectActionError ? (
            <p className="px-1 text-xs text-red-500">{subjectActionError}</p>
          ) : null}
        </div>

        <div className="flex-1 overflow-y-auto overflow-x-hidden px-3 pb-4 space-y-1 scrollbar-thin scrollbar-webkit">
          {!effectiveCollapsed ? (
            <div className="px-2 pb-2 pt-1">
              <span className="text-[11px] font-medium tracking-[0.08em] text-slate-400">学科</span>
            </div>
          ) : null}

          {isLoading ? (
            <div className="flex flex-col items-center justify-center py-6 text-slate-400">
              <Loader2 className="h-5 w-5 animate-spin" />
              {!effectiveCollapsed ? <span className="mt-2 text-xs">加载中…</span> : null}
            </div>
          ) : null}

          {groupedSubjects.map((subject) => {
            const expanded = expandedSubjects.has(subject.subject_id);
            const displayName = displaySubjectName(subject);
            const badgeClass = colorClassForSubject(subject.name || subject.subject_id);
            const isSubjectRouteActive = location.pathname.startsWith(`/subject/${subject.subject_id}/`);

            return (
              <div key={subject.subject_id} className="relative">
                <div
                  className={cn(
                    "group flex items-center gap-1 rounded-lg transition-colors",
                    !effectiveCollapsed && isSubjectRouteActive
                      ? "bg-[#f7f9fb] ring-1 ring-[#e3e8ee] dark:bg-slate-800/60 dark:ring-slate-700/50"
                      : !effectiveCollapsed
                        ? "hover:bg-slate-100/60 dark:hover:bg-slate-800/40"
                        : "",
                  )}
                >
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
                    )}
                    title={effectiveCollapsed ? displayName : undefined}
                  >
                    <div className={cn("flex shrink-0 items-center justify-center font-bold text-white shadow-sm", 
                      effectiveCollapsed ? "h-6 w-6 rounded text-[11px]" : "h-7 w-7 rounded-md text-xs",
                      badgeClass
                    )}>
                      {(subject.name.trim().charAt(0) || "新").toUpperCase()}
                    </div>
                    {!effectiveCollapsed ? <span className="ml-2 truncate text-sm font-medium text-slate-700 dark:text-slate-300">{displayName}</span> : null}
                  </button>

                  {!effectiveCollapsed ? (
                    <div className="relative" ref={openMenuId === subject.subject_id ? menuRef : undefined}>
                      <button
                        type="button"
                        onClick={() => setOpenMenuId((prev) => (prev === subject.subject_id ? null : subject.subject_id))}
                        className="rounded-md p-1.5 text-slate-400 opacity-0 transition hover:text-slate-700 group-hover:opacity-100 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300"
                        title="更多操作"
                      >
                        <MoreVertical className="h-4 w-4" />
                      </button>

                      {openMenuId === subject.subject_id ? (
                        <div className="absolute right-0 top-full z-50 mt-1 w-32 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-800">
                          <button
                            type="button"
                            onClick={() => {
                              setOpenMenuId(null);
                              void handleExportSubject(subject);
                            }}
                            disabled={exportingSubjectId === subject.subject_id}
                            className="flex w-full items-center gap-2 px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400 dark:text-slate-200 dark:hover:bg-slate-700/50"
                          >
                            {exportingSubjectId === subject.subject_id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400 dark:text-slate-500" />
                            ) : (
                              <Download className="h-3.5 w-3.5 text-slate-400 dark:text-slate-500" />
                            )}
                            导出 .atmx
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setOpenMenuId(null);
                              setRenameTarget({ id: subject.subject_id, name: displayName === "无标题" ? "" : subject.name });
                            }}
                            className="flex w-full items-center gap-2 border-t border-slate-100 px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-700/50"
                          >
                            <Edit3 className="h-3.5 w-3.5 text-slate-400 dark:text-slate-500" />
                            重命名
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setOpenMenuId(null);
                              openDeleteModal(subject);
                            }}
                            className="flex w-full items-center gap-2 border-t border-slate-100 px-3 py-2 text-xs text-red-600 hover:bg-red-50 dark:border-slate-700 dark:text-red-400 dark:hover:bg-red-900/20"
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
                            isActive
                              ? "bg-[#eef3f8] text-[#1f2937] ring-1 ring-[#d9e2ec] font-medium dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700"
                              : "text-slate-500 hover:bg-slate-50 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800/40 dark:hover:text-slate-200",
                          )}
                        >
                          <Icon className={cn("mr-2.5 h-4 w-4", isActive ? "text-[#556b86] dark:text-slate-300" : undefined)} />
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
        <div className="border-t border-slate-200/80 dark:border-slate-800/50 p-2.5 space-y-1 z-10">
          <button
            type="button"
            onClick={() => setIsCommunityModalOpen(true)}
            onMouseEnter={ensureCommunityQrPreloaded}
            onFocus={ensureCommunityQrPreloaded}
            className={cn(
              "flex items-center text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800/50 dark:hover:text-slate-200",
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
              "flex items-center text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800/50 dark:hover:text-slate-200",
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
