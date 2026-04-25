import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  BarChart3,
  BookOpen,
  Bot,
  Download,
  Edit3,
  FileText,
  FolderOpen,
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
import { resolveSubjectIcon } from "../../lib/subjectIcons";
import { cn } from "../../lib/utils";
import { publicAssetPath } from "../../lib/publicAsset";
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

const LOGO_SRC = publicAssetPath("logo.svg");

type SubjectWithIcon = SubjectItem & { icon_key?: string | null };

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
  const isGlobalAssistantActive = location.pathname === "/assistant";
  const isCreateSubjectActive = location.pathname === "/";
  const isMyLearningSpaceActive = location.pathname === "/spaces";
  const isLibraryActive = location.pathname === "/library";

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
        className="fixed left-4 top-4 z-50 flex h-11 w-11 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-700 shadow-sm dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 lg:hidden"
        aria-label={isMobileOpen ? "关闭导航" : "打开导航"}
      >
        {isMobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
      </button>

      {isMobileOpen ? (
        <div className="fixed inset-0 z-30 modal-backdrop lg:hidden" onClick={() => setIsMobileOpen(false)} />
      ) : null}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex min-h-0 shrink-0 self-stretch flex-col overflow-hidden rounded-r-[22px] border-r border-slate-200/50 dark:border-slate-800/50 bg-gradient-to-b from-white/96 to-white/92 dark:from-[#0b0f19]/96 dark:to-[#0b0f19]/92 shadow-[4px_0_24px_rgba(0,0,0,0.03)] dark:shadow-[4px_0_24px_rgba(0,0,0,0.3)] ring-1 ring-white/50 dark:ring-white/5 transition-[width,transform] duration-200 lg:static",
          effectiveCollapsed ? "w-[64px]" : "w-[240px]",
          isMobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
        )}
      >
        <div
          className={cn(
            "flex h-12 shrink-0 items-center border-b border-slate-100 dark:border-slate-800/50",
            effectiveCollapsed ? "justify-center px-0" : "justify-between px-4",
          )}
        >
          {effectiveCollapsed ? (
            <div className="group relative h-8 w-8">
              <img
                src={LOGO_SRC}
                alt="AITeachMe"
                className="pointer-events-none absolute inset-0 m-auto h-6 w-6 object-contain opacity-100 transition-opacity duration-150 group-hover:opacity-0 dark:invert dark:opacity-90 dark:group-hover:opacity-0"
              />
              <button
                type="button"
                onClick={() => setIsCollapsed(false)}
                className="absolute inset-0 flex h-8 w-8 items-center justify-center rounded text-slate-400 opacity-0 transition-all duration-150 group-hover:opacity-100 hover:bg-slate-100 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-800/50 dark:hover:text-slate-300"
                title="展开侧边栏"
              >
                <PanelLeftOpen className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <>
              <Link to="/" className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
                <img src={LOGO_SRC} alt="AITeachMe" className="h-5 w-auto dark:invert dark:opacity-90" />
              </Link>
              <button
                type="button"
                onClick={() => setIsCollapsed(true)}
                className="flex h-11 w-11 items-center justify-center rounded text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-800/50 dark:hover:text-slate-300 lg:h-8 lg:w-8"
                title="收起侧边栏"
              >
                <PanelLeftClose className="h-4 w-4" />
              </button>
            </>
          )}
        </div>

        <div className={cn("shrink-0 space-y-1", effectiveCollapsed ? "px-0 pb-2 pt-1" : "px-2 pb-2 pt-1")}>
          {effectiveCollapsed ? (
            <div className="flex flex-col items-center gap-1">
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
                  "flex h-6 w-6 items-center justify-center rounded-md transition-colors",
                  isCreateSubjectActive
                    ? "bg-[#eef2f6] text-[#243246] ring-1 ring-[#d9e1ea] hover:bg-[#e4ebf3] hover:text-[#182437] dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700 dark:hover:bg-slate-700/70 dark:hover:text-slate-50"
                    : "text-slate-500 hover:bg-[#eef3f8] hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200",
                )}
              >
                <Edit3 className="h-3.5 w-3.5 shrink-0" strokeWidth={2.2} />
              </button>

              <button
                type="button"
                onClick={() => {
                  setSubjectActionError(undefined);
                  setOpenMenuId(null);
                  setIsMobileOpen(false);
                  setIsCollapsed(false);
                  navigate("/assistant");
                }}
                title="全局助手"
                className={cn(
                  "flex h-6 w-6 items-center justify-center rounded-md transition-colors",
                  isGlobalAssistantActive
                    ? "bg-[#eef2f6] text-[#243246] ring-1 ring-[#d9e1ea] hover:bg-[#e4ebf3] hover:text-[#182437] dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700 dark:hover:bg-slate-700/70 dark:hover:text-slate-50"
                    : "text-slate-500 hover:bg-[#eef3f8] hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200",
                )}
              >
                <Bot className="h-3.5 w-3.5 shrink-0" strokeWidth={2.2} />
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
                  "flex h-6 w-6 items-center justify-center rounded-md transition-colors",
                  isMyLearningSpaceActive
                    ? "bg-[#eef2f6] text-[#243246] ring-1 ring-[#d9e1ea] hover:bg-[#e4ebf3] hover:text-[#182437] dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700 dark:hover:bg-slate-700/70 dark:hover:text-slate-50"
                    : "text-slate-500 hover:bg-[#eef3f8] hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200",
                )}
              >
                <LayoutGrid className="h-3.5 w-3.5 shrink-0" strokeWidth={2.2} />
              </button>

              <button
                type="button"
                onClick={() => {
                  setSubjectActionError(undefined);
                  setOpenMenuId(null);
                  setIsMobileOpen(false);
                  setIsCollapsed(false);
                  navigate("/library");
                }}
                title="我的资料库"
                className={cn(
                  "flex h-6 w-6 items-center justify-center rounded-md transition-colors",
                  isLibraryActive
                    ? "bg-[#eef2f6] text-[#243246] ring-1 ring-[#d9e1ea] hover:bg-[#e4ebf3] hover:text-[#182437] dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700 dark:hover:bg-slate-700/70 dark:hover:text-slate-50"
                    : "text-slate-500 hover:bg-[#eef3f8] hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200",
                )}
              >
                <FolderOpen className="h-3.5 w-3.5 shrink-0" strokeWidth={2.2} />
              </button>
            </div>
          ) : (
            <>
              <button
                type="button"
                className={cn(
                  "group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors",
                  isCreateSubjectActive
                    ? "bg-[#f3f6f9] text-slate-950 ring-1 ring-[#dbe3ec] hover:bg-[#e8eef5] dark:bg-slate-800/80 dark:text-slate-100 dark:ring-slate-700 dark:hover:bg-slate-700/70"
                    : "text-slate-900 hover:bg-[#eef3f8] dark:text-slate-300 dark:hover:bg-slate-800/60",
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
                  className={cn(
                    "h-3.5 w-3.5 shrink-0 transition-colors",
                    isCreateSubjectActive
                      ? "text-[#4b607b] group-hover:text-[#324761] dark:text-slate-300 dark:group-hover:text-slate-100"
                      : "text-slate-500 group-hover:text-slate-700 dark:text-slate-400 dark:group-hover:text-slate-200",
                  )}
                  strokeWidth={2.2}
                />
                <span
                  className={cn(
                    "text-xs tracking-[0.01em]",
                    isCreateSubjectActive
                      ? "font-semibold text-[#1f2937] group-hover:text-[#172033] dark:text-slate-100 dark:group-hover:text-white"
                      : "font-normal text-slate-900 group-hover:text-slate-950 dark:text-slate-300 dark:group-hover:text-slate-100",
                  )}
                >
                  新建学科
                </span>
              </button>

              <button
                type="button"
                className={cn(
                  "group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors",
                  isGlobalAssistantActive
                    ? "bg-[#f3f6f9] text-slate-950 ring-1 ring-[#dbe3ec] hover:bg-[#e8eef5] dark:bg-slate-800/80 dark:text-slate-100 dark:ring-slate-700 dark:hover:bg-slate-700/70"
                    : "text-slate-900 hover:bg-[#eef3f8] dark:text-slate-300 dark:hover:bg-slate-800/60",
                )}
                onClick={() => {
                  setSubjectActionError(undefined);
                  setOpenMenuId(null);
                  setIsMobileOpen(false);
                  navigate("/assistant");
                }}
              >
                <Bot
                  className={cn(
                    "h-3.5 w-3.5 shrink-0 transition-colors",
                    isGlobalAssistantActive
                      ? "text-[#4b607b] group-hover:text-[#324761] dark:text-slate-300 dark:group-hover:text-slate-100"
                      : "text-slate-500 group-hover:text-slate-700 dark:text-slate-400 dark:group-hover:text-slate-200",
                  )}
                  strokeWidth={2.2}
                />
                <span
                  className={cn(
                    "text-xs tracking-[0.01em]",
                    isGlobalAssistantActive
                      ? "font-semibold text-[#1f2937] group-hover:text-[#172033] dark:text-slate-100 dark:group-hover:text-white"
                      : "font-normal text-slate-900 group-hover:text-slate-950 dark:text-slate-300 dark:group-hover:text-slate-100",
                  )}
                >
                  全局助手
                </span>
              </button>

              <button
                type="button"
                className={cn(
                  "group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors",
                  isMyLearningSpaceActive
                    ? "bg-[#f3f6f9] text-slate-950 ring-1 ring-[#dbe3ec] hover:bg-[#e8eef5] dark:bg-slate-800/80 dark:text-slate-100 dark:ring-slate-700 dark:hover:bg-slate-700/70"
                    : "text-slate-900 hover:bg-[#eef3f8] dark:text-slate-300 dark:hover:bg-slate-800/60",
                )}
                onClick={() => {
                  setSubjectActionError(undefined);
                  setOpenMenuId(null);
                  setIsMobileOpen(false);
                  navigate("/spaces");
                }}
              >
                <LayoutGrid
                  className={cn(
                    "h-3.5 w-3.5 shrink-0 transition-colors",
                    isMyLearningSpaceActive
                      ? "text-[#4b607b] group-hover:text-[#324761] dark:text-slate-300 dark:group-hover:text-slate-100"
                      : "text-slate-500 group-hover:text-slate-700 dark:text-slate-400 dark:group-hover:text-slate-200",
                  )}
                  strokeWidth={2.2}
                />
                <span
                  className={cn(
                    "text-xs tracking-[0.01em]",
                    isMyLearningSpaceActive
                      ? "font-semibold text-[#1f2937] group-hover:text-[#172033] dark:text-slate-100 dark:group-hover:text-white"
                      : "font-normal text-slate-900 group-hover:text-slate-950 dark:text-slate-300 dark:group-hover:text-slate-100",
                  )}
                >
                  我的学习空间
                </span>
              </button>

              <button
                type="button"
                className={cn(
                  "group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors",
                  isLibraryActive
                    ? "bg-[#f3f6f9] text-slate-950 ring-1 ring-[#dbe3ec] hover:bg-[#e8eef5] dark:bg-slate-800/80 dark:text-slate-100 dark:ring-slate-700 dark:hover:bg-slate-700/70"
                    : "text-slate-900 hover:bg-[#eef3f8] dark:text-slate-300 dark:hover:bg-slate-800/60",
                )}
                onClick={() => {
                  setSubjectActionError(undefined);
                  setOpenMenuId(null);
                  setIsMobileOpen(false);
                  navigate("/library");
                }}
              >
                <FolderOpen
                  className={cn(
                    "h-3.5 w-3.5 shrink-0 transition-colors",
                    isLibraryActive
                      ? "text-[#4b607b] group-hover:text-[#324761] dark:text-slate-300 dark:group-hover:text-slate-100"
                      : "text-slate-500 group-hover:text-slate-700 dark:text-slate-400 dark:group-hover:text-slate-200",
                  )}
                  strokeWidth={2.2}
                />
                <span
                  className={cn(
                    "text-xs tracking-[0.01em]",
                    isLibraryActive
                      ? "font-semibold text-[#1f2937] group-hover:text-[#172033] dark:text-slate-100 dark:group-hover:text-white"
                      : "font-normal text-slate-900 group-hover:text-slate-950 dark:text-slate-300 dark:group-hover:text-slate-100",
                  )}
                >
                  我的资料库
                </span>
              </button>
            </>
          )}

          {!effectiveCollapsed && subjectActionError ? (
            <p className="px-1 text-xs text-red-500">{subjectActionError}</p>
          ) : null}
        </div>

        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto overflow-x-hidden px-3 pb-4 scrollbar-thin scrollbar-webkit">
          {!effectiveCollapsed ? (
            <div className="flex items-center gap-1.5 px-2 pb-2 pt-1">
              <span className="text-[11px] font-medium tracking-[0.08em] text-slate-400">学科</span>
              {isLoading ? <Loader2 className="h-3 w-3 animate-spin text-slate-400 dark:text-slate-500" /> : null}
            </div>
          ) : null}

          {!isLoading && groupedSubjects.length === 0 && !effectiveCollapsed ? (
            <p className="-mt-1 px-4 py-0 text-[11px] text-slate-300 dark:text-slate-600">暂无学科</p>
          ) : null}

          {groupedSubjects.map((subject) => {
            const expanded = expandedSubjects.has(subject.subject_id);
            const displayName = displaySubjectName(subject);
            const badgeClass = colorClassForSubject(subject.name || subject.subject_id);
            const isSubjectRouteActive = location.pathname.startsWith(`/subject/${subject.subject_id}/`);
            const SubjectIcon = resolveSubjectIcon((subject as SubjectWithIcon).icon_key);

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
                      <SubjectIcon className={cn(effectiveCollapsed ? "h-3.5 w-3.5" : "h-4 w-4")} strokeWidth={2.2} />
                    </div>
                    {!effectiveCollapsed ? <span className="ml-2 truncate text-sm font-medium text-slate-700 dark:text-slate-300">{displayName}</span> : null}
                  </button>

                  {!effectiveCollapsed ? (
                    <div className="relative" ref={openMenuId === subject.subject_id ? menuRef : undefined}>
                      <button
                        type="button"
                        onClick={() => setOpenMenuId((prev) => (prev === subject.subject_id ? null : subject.subject_id))}
                        className="flex h-8 w-8 items-center justify-center rounded-md text-slate-400 opacity-100 transition hover:bg-slate-100 hover:text-slate-700 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300 sm:opacity-0 sm:group-hover:opacity-100"
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
                            "flex min-h-10 items-center rounded-md px-2.5 py-2 text-sm transition-colors",
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
        <div className="z-10 mt-auto shrink-0 space-y-1 border-t border-slate-200/80 p-2 dark:border-slate-800/50">
          <button
            type="button"
            onClick={() => setIsCommunityModalOpen(true)}
            onMouseEnter={ensureCommunityQrPreloaded}
            className={cn(
              "flex items-center text-slate-500 transition-colors hover:bg-[#eef3f8] hover:text-slate-900 focus:outline-none focus-visible:outline-none dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200",
              effectiveCollapsed ? "mx-auto h-6 w-6 justify-center rounded-md" : "w-full rounded-md px-2 py-1.5 gap-2",
            )}
            title="社区"
          >
            <MessageCircle className="h-3.5 w-3.5 shrink-0" />
            {!effectiveCollapsed ? <span className="text-xs tracking-[0.01em]">社区</span> : null}
          </button>
          <button
            type="button"
            onClick={onOpenSettings}
            className={cn(
              "flex items-center text-slate-500 transition-colors hover:bg-[#eef3f8] hover:text-slate-900 focus:outline-none focus-visible:outline-none dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200",
              effectiveCollapsed ? "mx-auto h-6 w-6 justify-center rounded-md" : "w-full rounded-md px-2 py-1.5 gap-2",
            )}
            title="设置"
          >
            <Settings className="h-3.5 w-3.5 shrink-0" />
            {!effectiveCollapsed ? <span className="text-xs tracking-[0.01em]">设置</span> : null}
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
