import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { AnimatePresence, motion, type Variants } from "framer-motion";
import {
  BarChart3,
  BookOpen,
  ChevronRight,
  Download,
  Edit3,
  FileText,
  FolderOpen,
  LayoutGrid,
  Loader2,
  Menu,
  MoreVertical,
  PackagePlus,
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
  listCoursesApiApiV1CoursesListPost,
  previewDeleteCourseApiApiV1CoursesDeletePreviewPost,
} from "../../api/generated/courses";
import type { CourseDeletePreviewData, CourseItem } from "../../api/generated/model";
import { apiClient, getApiErrorMessage } from "../../api/client";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { resolveCourseIcon } from "../../lib/courseIcons";
import { COURSES_IMPORTED_EVENT, type CoursesImportedDetail } from "../../lib/courseEvents";
import { cn } from "../../lib/utils";
import { publicAssetPath } from "../../lib/publicAsset";
import { CourseExportModal } from "../course/CourseExportModal";
import { CourseImportModal } from "../course/CourseImportModal";
import { CourseDeleteConfirmModal } from "./CourseDeleteConfirmModal";
import { CommunityModal, ensureCommunityQrPreloaded } from "./CommunityPanel";
import { AiConversationSidebarSection } from "../interaction/AiConversationSidebarSection";
import { useAiInteraction } from "../interaction";

import { Button } from "../ui/Button";

const MODULES = [
  { id: "build", name: "构建", icon: Sparkles },
  { id: "knowledge-docs", name: "知识库", icon: BookOpen },
  { id: "exams", name: "考试", icon: FileText },
  { id: "profile", name: "学习画像", icon: BarChart3 },
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
const COURSE_SECTION_EXPANDED_STORAGE_KEY = "aiteachme.sidebar.coursesExpanded";

const sidebarListContainerMotion: Variants = {
  visible: {
    transition: {
      staggerChildren: 0.035,
      delayChildren: 0.02,
    },
  },
};

const sidebarItemMotion: Variants = {
  hidden: { opacity: 0, x: -8, scale: 0.98 },
  visible: {
    opacity: 1,
    x: 0,
    scale: 1,
    transition: { type: "spring", stiffness: 420, damping: 34 },
  },
  exit: {
    opacity: 0,
    x: -8,
    scale: 0.98,
    transition: { duration: 0.14, ease: "easeOut" },
  },
};

const sidebarChildItemMotion: Variants = {
  hidden: { opacity: 0, y: -4 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { type: "spring", stiffness: 420, damping: 32 },
  },
  exit: {
    opacity: 0,
    y: -4,
    transition: { duration: 0.12, ease: "easeOut" },
  },
};

type CourseWithIcon = CourseItem & { icon_key?: string | null };

function colorClassForCourse(name: string) {
  let hash = 0;
  for (let index = 0; index < name.length; index += 1) {
    hash = name.charCodeAt(index) + ((hash << 5) - hash);
  }
  return COLOR_CLASSES[Math.abs(hash) % COLOR_CLASSES.length];
}

function RenameCourseModal({
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
        url: "/api/v1/courses/update",
        data: { course_id: courseId, name: name.trim() },
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
          <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">重命名学科</h3>
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
            <p className="text-xs text-red-600 dark:text-red-400">{getApiErrorMessage(renameMutation.error, "重命名失败，请重试")}</p>
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

function displayCourseName(course: CourseItem): string {
  return course.name?.trim() || "无标题";
}

function readCourseSectionExpanded(): boolean {
  if (typeof window === "undefined") {
    return true;
  }
  try {
    return window.localStorage.getItem(COURSE_SECTION_EXPANDED_STORAGE_KEY) !== "false";
  } catch {
    return true;
  }
}

function writeCourseSectionExpanded(value: boolean) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(COURSE_SECTION_EXPANDED_STORAGE_KEY, value ? "true" : "false");
  } catch {
    // Keep the in-memory state when storage is unavailable in restricted webviews.
  }
}

export function Sidebar({ onOpenSettings }: { onOpenSettings?: () => void }) {
  const [expandedCourses, setExpandedCourses] = useState<Set<string>>(new Set());
  const [isCourseSectionExpanded, setIsCourseSectionExpanded] = useState(readCourseSectionExpanded);
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [courseActionError, setCourseActionError] = useState<string>();
  const [deleteTarget, setDeleteTarget] = useState<CourseItem | null>(null);
  const [deletePreview, setDeletePreview] = useState<CourseDeletePreviewData | null>(null);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<{ id: string; name: string } | null>(null);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [isCommunityModalOpen, setIsCommunityModalOpen] = useState(false);
  const [exportCourseId, setExportCourseId] = useState<string | null>(null);
  const [isImportModalOpen, setIsImportModalOpen] = useState(false);

  const menuRef = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const {
    activeScope,
    closeAiInteraction,
    notifyConversationSessionsChanged,
  } = useAiInteraction();
  const effectiveCollapsed = !isMobileOpen && isCollapsed;
  const isCreateCourseActive = location.pathname === "/";
  const isMyLearningSpaceActive = location.pathname === "/spaces";
  const isLibraryActive = location.pathname === "/library";

  const { data: courses = [], isLoading } = useQuery({
    queryKey: ["courses"],
    queryFn: async () =>
      unwrapOrvalResponse(
        await listCoursesApiApiV1CoursesListPost({
          page: 1,
          size: 100,
        }),
      )?.items ?? [],
  });

  const updateCourseSectionExpanded = useCallback((next: boolean | ((current: boolean) => boolean)) => {
    setIsCourseSectionExpanded((current) => {
      const value = typeof next === "function" ? next(current) : next;
      writeCourseSectionExpanded(value);
      return value;
    });
  }, []);

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
    const handleCoursesImported = (event: Event) => {
      const detail = (event as CustomEvent<CoursesImportedDetail>).detail;
      updateCourseSectionExpanded(true);
      setIsCollapsed(false);
      if (detail?.courseId) {
        setExpandedCourses((prev) => new Set([...prev, detail.courseId as string]));
      }
    };
    window.addEventListener(COURSES_IMPORTED_EVENT, handleCoursesImported);
    return () => window.removeEventListener(COURSES_IMPORTED_EVENT, handleCoursesImported);
  }, [updateCourseSectionExpanded]);

  useEffect(() => {
    const match = location.pathname.match(/^\/course\/([^/]+)/);
    if (!match?.[1]) {
      return;
    }
    setExpandedCourses((prev) => new Set([...prev, match[1]]));
    updateCourseSectionExpanded(true);
    setIsCollapsed(false);
  }, [location.pathname, updateCourseSectionExpanded]);

  const deletePreviewMutation = useMutation({
    mutationFn: async (courseId: string) =>
      unwrapOrvalResponse(
        await previewDeleteCourseApiApiV1CoursesDeletePreviewPost({ course_id: courseId }),
      ) ?? null,
    onSuccess: (preview) => {
      setDeletePreview(preview);
      setCourseActionError(undefined);
    },
    onError: (error) => {
      setDeletePreview(null);
      setCourseActionError(getApiErrorMessage(error, "删除预览加载失败，请重试"));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async ({
      courseId,
      knownDetailCounts,
    }: {
      courseId: string;
      knownDetailCounts?: Record<string, number> | null;
    }) => {
      await apiClient({
        method: "POST",
        url: "/api/v1/courses/delete",
        data: {
          course_id: courseId,
          force: true,
          known_detail_counts: knownDetailCounts ?? undefined,
        },
      });
    },
    onSuccess: (_, variables) => {
      const courseId = variables.courseId;
      void queryClient.invalidateQueries({ queryKey: ["courses"] });
      notifyConversationSessionsChanged();
      if (activeScope?.type === "course" && activeScope.courseId === courseId) {
        closeAiInteraction();
      }
      setCourseActionError(undefined);
      setIsDeleteModalOpen(false);
      setDeleteTarget(null);
      setDeletePreview(null);
      if (location.pathname.startsWith(`/course/${courseId}/`)) {
        navigate("/");
      }
    },
    onError: (error) => {
      setCourseActionError(getApiErrorMessage(error, "删除失败，请重试"));
    },
  });

  const groupedCourses = useMemo(() => courses as CourseItem[], [courses]);
  const shouldAnimateCourseItems = groupedCourses.length <= 24;
  const shouldShowCourseList = effectiveCollapsed || isCourseSectionExpanded;
  const expandNavigationSidebar = useCallback(() => {
    setIsCollapsed(false);
  }, []);
  const closeMobileNavigation = useCallback(() => {
    setIsMobileOpen(false);
  }, []);

  const toggleCourse = (courseId: string) => {
    if (effectiveCollapsed) {
      setIsCollapsed(false);
      return;
    }
    setExpandedCourses((prev) => {
      const next = new Set(prev);
      if (next.has(courseId)) {
        next.delete(courseId);
      } else {
        next.add(courseId);
      }
      return next;
    });
  };

  const openDeleteModal = (course: CourseItem) => {
    setDeleteTarget(course);
    setDeletePreview(null);
    setCourseActionError(undefined);
    setIsDeleteModalOpen(true);
    deletePreviewMutation.reset();
    deleteMutation.reset();
    deletePreviewMutation.mutate(course.course_id);
  };

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
        data-app-sidebar="true"
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex min-h-0 shrink-0 self-stretch flex-col overflow-hidden rounded-r-[22px] border-r border-slate-200/50 dark:border-slate-800/50 bg-gradient-to-b from-white/96 to-white/92 dark:from-[#0b0f19]/96 dark:to-[#0b0f19]/92 shadow-[4px_0_24px_rgba(0,0,0,0.03)] dark:shadow-[4px_0_24px_rgba(0,0,0,0.3)] ring-1 ring-white/50 dark:ring-white/5 transition-[width,transform] duration-200 lg:relative lg:z-[90]",
          effectiveCollapsed ? "w-[56px]" : "w-[240px]",
          isMobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
        )}
      >
        <div
          className={cn(
            "flex h-12 shrink-0 items-center border-b border-slate-100 dark:border-slate-800/50",
            effectiveCollapsed ? "justify-center px-0" : "justify-between px-3",
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
              <Link to="/" className="flex items-center gap-2 pl-2 text-slate-900 dark:text-slate-100">
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

        <div className={cn("shrink-0 space-y-1", effectiveCollapsed ? "px-0 pb-2 pt-1" : "px-3 pb-2 pt-1")}>
          {effectiveCollapsed ? (
            <div className="flex flex-col items-center gap-1">
              <button
                type="button"
                onClick={() => {
                  setCourseActionError(undefined);
                  setOpenMenuId(null);
                  setIsMobileOpen(false);
                  setIsCollapsed(false);
                  navigate("/", {
                    state: { newEntryAt: Date.now() },
                  });
                }}
                title="新建学科"
                className={cn(
                  "flex h-7 w-7 items-center justify-center rounded-md transition-colors",
                  isCreateCourseActive
                    ? "bg-[#eef2f6] text-[#243246] ring-1 ring-[#d9e1ea] hover:bg-[#e4ebf3] hover:text-[#182437] dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700 dark:hover:bg-slate-700/70 dark:hover:text-slate-50"
                    : "text-slate-500 hover:bg-[#eef3f8] hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200",
                )}
              >
                <Edit3 className="h-3.5 w-3.5 shrink-0" strokeWidth={2.2} />
              </button>

              <button
                type="button"
                onClick={() => {
                  setCourseActionError(undefined);
                  setOpenMenuId(null);
                  setIsMobileOpen(false);
                  setIsCollapsed(false);
                  navigate("/spaces");
                }}
                title="学习空间"
                className={cn(
                  "flex h-7 w-7 items-center justify-center rounded-md transition-colors",
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
                  setCourseActionError(undefined);
                  setOpenMenuId(null);
                  setIsMobileOpen(false);
                  setIsCollapsed(false);
                  navigate("/library");
                }}
                title="我的资料库"
                className={cn(
                  "flex h-7 w-7 items-center justify-center rounded-md transition-colors",
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
                  "group flex h-7 w-full items-center gap-2 rounded-md px-2 text-left transition-colors",
                  isCreateCourseActive
                    ? "bg-[#f3f6f9] text-slate-950 ring-1 ring-[#dbe3ec] hover:bg-[#e8eef5] dark:bg-slate-800/80 dark:text-slate-100 dark:ring-slate-700 dark:hover:bg-slate-700/70"
                    : "text-slate-900 hover:bg-[#eef3f8] dark:text-slate-300 dark:hover:bg-slate-800/60",
                )}
                onClick={() => {
                  setCourseActionError(undefined);
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
                    isCreateCourseActive
                      ? "text-[#4b607b] group-hover:text-[#324761] dark:text-slate-300 dark:group-hover:text-slate-100"
                      : "text-slate-500 group-hover:text-slate-700 dark:text-slate-400 dark:group-hover:text-slate-200",
                  )}
                  strokeWidth={2.2}
                />
                <span
                  className={cn(
                    "whitespace-nowrap text-xs tracking-[0.01em]",
                    isCreateCourseActive
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
                  "group flex h-7 w-full items-center gap-2 rounded-md px-2 text-left transition-colors",
                  isMyLearningSpaceActive
                    ? "bg-[#f3f6f9] text-slate-950 ring-1 ring-[#dbe3ec] hover:bg-[#e8eef5] dark:bg-slate-800/80 dark:text-slate-100 dark:ring-slate-700 dark:hover:bg-slate-700/70"
                    : "text-slate-900 hover:bg-[#eef3f8] dark:text-slate-300 dark:hover:bg-slate-800/60",
                )}
                onClick={() => {
                  setCourseActionError(undefined);
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
                    "whitespace-nowrap text-xs tracking-[0.01em]",
                    isMyLearningSpaceActive
                      ? "font-semibold text-[#1f2937] group-hover:text-[#172033] dark:text-slate-100 dark:group-hover:text-white"
                      : "font-normal text-slate-900 group-hover:text-slate-950 dark:text-slate-300 dark:group-hover:text-slate-100",
                  )}
                >
                  学习空间
                </span>
              </button>

              <button
                type="button"
                className={cn(
                  "group flex h-7 w-full items-center gap-2 rounded-md px-2 text-left transition-colors",
                  isLibraryActive
                    ? "bg-[#f3f6f9] text-slate-950 ring-1 ring-[#dbe3ec] hover:bg-[#e8eef5] dark:bg-slate-800/80 dark:text-slate-100 dark:ring-slate-700 dark:hover:bg-slate-700/70"
                    : "text-slate-900 hover:bg-[#eef3f8] dark:text-slate-300 dark:hover:bg-slate-800/60",
                )}
                onClick={() => {
                  setCourseActionError(undefined);
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
                    "whitespace-nowrap text-xs tracking-[0.01em]",
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

          {!effectiveCollapsed && courseActionError ? (
            <p className="px-1 text-xs text-red-500">{courseActionError}</p>
          ) : null}
        </div>

        <div className={cn("min-h-0 flex-1 space-y-0.5 overflow-y-auto overflow-x-hidden pb-4 scrollbar-thin scrollbar-webkit", effectiveCollapsed ? "px-2" : "px-3")}>
          {!effectiveCollapsed ? (
            <div className="flex h-7 items-center gap-1">
              <button
                type="button"
                onClick={() => updateCourseSectionExpanded((value) => !value)}
                className="group flex min-w-0 flex-1 items-center gap-1 rounded-md px-2 text-left text-[11px] font-medium text-slate-400 transition-colors hover:bg-[#eef3f8] hover:text-slate-700 dark:text-slate-500 dark:hover:bg-slate-800/60 dark:hover:text-slate-300"
                aria-expanded={isCourseSectionExpanded}
              >
                <span className="truncate">学科</span>
                <ChevronRight
                  className={cn(
                    "h-3 w-3 shrink-0 opacity-0 transition-[opacity,transform] group-hover:opacity-100 group-focus-visible:opacity-100",
                    isCourseSectionExpanded && "rotate-90",
                  )}
                />
                {isLoading ? <Loader2 className="h-3 w-3 animate-spin text-current opacity-70" /> : null}
              </button>
              <button
                type="button"
                onClick={() => setIsImportModalOpen(true)}
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-slate-400 transition hover:bg-[#eef3f8] hover:text-sky-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#9fb0c4]/45 dark:text-slate-500 dark:hover:bg-slate-800/60 dark:hover:text-sky-300"
                title="导入课程包"
                aria-label="导入课程包"
              >
                <PackagePlus className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <div className="flex h-6 items-center px-1">
              <div className="h-px w-full bg-slate-200 dark:bg-slate-800" />
            </div>
          )}

          {!isLoading && groupedCourses.length === 0 && !effectiveCollapsed && isCourseSectionExpanded ? (
            <p className="-mt-1 overflow-hidden whitespace-nowrap px-4 py-0 text-[11px] text-slate-300 dark:text-slate-600">暂无学科</p>
          ) : null}

          <AnimatePresence initial={false}>
            {shouldShowCourseList ? (
              <motion.div
                key="courses-list"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.18, ease: "easeOut" }}
                className="overflow-hidden"
              >
                <motion.div
                  className="space-y-0.5"
                  variants={shouldAnimateCourseItems ? sidebarListContainerMotion : undefined}
                  initial={shouldAnimateCourseItems ? "hidden" : false}
                  animate={shouldAnimateCourseItems ? "visible" : undefined}
                >
                  <AnimatePresence initial={false}>
              {groupedCourses.map((course) => {
                const expanded = expandedCourses.has(course.course_id);
                const displayName = displayCourseName(course);
                const badgeClass = colorClassForCourse(course.name || course.course_id);
                const CourseIcon = resolveCourseIcon((course as CourseWithIcon).icon_key);

                return (
                  <motion.div
                    key={course.course_id}
                    variants={shouldAnimateCourseItems ? sidebarItemMotion : undefined}
                    initial={shouldAnimateCourseItems ? "hidden" : false}
                    animate={shouldAnimateCourseItems ? "visible" : undefined}
                    exit={shouldAnimateCourseItems ? "exit" : undefined}
                    className="relative"
                  >
                <div
                  className={cn(
                    "group flex h-7 items-center gap-1 rounded-md transition-colors",
                    !effectiveCollapsed ? "hover:bg-[#eef3f8] dark:hover:bg-slate-800/60" : "",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => {
                      if (effectiveCollapsed) {
                        setIsCollapsed(false);
                        if (!expanded) {
                          toggleCourse(course.course_id);
                        }
                      } else {
                        toggleCourse(course.course_id);
                      }
                    }}
                    className={cn(
                      "flex items-center transition-colors",
                      effectiveCollapsed
                        ? "h-7 w-full justify-center rounded-md px-0 hover:bg-[#eef3f8] dark:hover:bg-slate-800/60"
                        : "h-7 flex-1 rounded-md px-2",
                    )}
                    title={effectiveCollapsed ? displayName : undefined}
                  >
                    <div className={cn("flex shrink-0 items-center justify-center font-bold text-white shadow-sm", 
                      effectiveCollapsed ? "h-5 w-5 rounded text-[10px]" : "h-5 w-5 rounded text-[10px]",
                      badgeClass
                    )}>
                      <CourseIcon className="h-3.5 w-3.5" strokeWidth={2.2} />
                    </div>
                    {!effectiveCollapsed ? <span className="ml-2 truncate text-xs font-medium text-slate-700 dark:text-slate-300">{displayName}</span> : null}
                  </button>

                  {!effectiveCollapsed ? (
                    <div className="relative" ref={openMenuId === course.course_id ? menuRef : undefined}>
                      <button
                        type="button"
                        onClick={() => setOpenMenuId((prev) => (prev === course.course_id ? null : course.course_id))}
                        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-slate-400 opacity-100 transition hover:bg-slate-100 hover:text-slate-700 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300 sm:opacity-0 sm:group-hover:opacity-100"
                        title="更多操作"
                      >
                        <MoreVertical className="h-3.5 w-3.5" />
                      </button>

                      {openMenuId === course.course_id ? (
                        <div className="absolute right-0 top-full z-50 mt-1 w-32 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-800">
                          <button
                            type="button"
                            onClick={() => {
                              setOpenMenuId(null);
                              setCourseActionError(undefined);
                              setExportCourseId(course.course_id);
                            }}
                            className="flex w-full items-center gap-2 px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400 dark:text-slate-200 dark:hover:bg-slate-700/50"
                          >
                            <Download className="h-3.5 w-3.5 text-slate-400 dark:text-slate-500" />
                            导出 .atmx
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setOpenMenuId(null);
                              setRenameTarget({ id: course.course_id, name: displayName === "无标题" ? "" : course.name });
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
                              openDeleteModal(course);
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

                <AnimatePresence initial={false}>
                  {!effectiveCollapsed && expanded ? (
                    <motion.div
                      key="modules"
                      initial={{ gridTemplateRows: "0fr", opacity: 0 }}
                      animate={{ gridTemplateRows: "1fr", opacity: 1 }}
                      exit={{ gridTemplateRows: "0fr", opacity: 0 }}
                      transition={{ duration: 0.18, ease: "easeOut" }}
                      className="grid"
                    >
                      <div className="min-h-0 overflow-hidden">
                        <div className="ml-4 mt-1 space-y-0.5 border-l border-slate-200 pl-2">
                          <AnimatePresence initial={false}>
                            {MODULES.map((moduleItem) => {
                              const path = `/course/${course.course_id}/${moduleItem.id}`;
                              const isActive = location.pathname === path;
                              const Icon = moduleItem.icon;
                              return (
                                <motion.div
                                  key={moduleItem.id}
                                  variants={sidebarChildItemMotion}
                                  initial="hidden"
                                  animate="visible"
                                  exit="exit"
                                  whileTap={{ scale: 0.985 }}
                                >
                                  <Link
                                    to={path}
                                    onClick={() => setIsMobileOpen(false)}
                                    className={cn(
                                      "flex h-7 items-center overflow-hidden whitespace-nowrap rounded-md px-2 text-xs transition-colors",
                                      isActive
                                        ? "bg-[#edf3f8] font-medium text-[#243246] dark:bg-slate-800 dark:text-slate-200"
                                        : "text-slate-500 hover:bg-slate-50 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800/40 dark:hover:text-slate-200",
                                    )}
                                  >
                                    <Icon className={cn("mr-2 h-3.5 w-3.5", isActive ? "text-[#556b86] dark:text-slate-300" : undefined)} />
                                    {moduleItem.name}
                                  </Link>
                                </motion.div>
                              );
                            })}
                          </AnimatePresence>
                        </div>
                      </div>
                    </motion.div>
                  ) : null}
                </AnimatePresence>
                  </motion.div>
                );
              })}
                  </AnimatePresence>
                </motion.div>
              </motion.div>
            ) : null}
          </AnimatePresence>

          <AiConversationSidebarSection
            collapsed={effectiveCollapsed}
            onExpandSidebar={expandNavigationSidebar}
            onNavigate={closeMobileNavigation}
          />
        </div>

        {/* Bottom actions */}
        <div
          className={cn(
            "z-10 mt-auto shrink-0 space-y-1 border-t border-slate-200/80 dark:border-slate-800/50",
            effectiveCollapsed ? "p-2" : "px-3 py-2",
          )}
        >
          <button
            type="button"
            onClick={() => setIsCommunityModalOpen(true)}
            onMouseEnter={ensureCommunityQrPreloaded}
            className={cn(
              "flex items-center text-slate-500 transition-colors hover:bg-[#eef3f8] hover:text-slate-900 focus:outline-none focus-visible:outline-none dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200",
              effectiveCollapsed ? "mx-auto h-7 w-7 justify-center rounded-md" : "h-7 w-full rounded-md px-2 gap-2",
            )}
            title="社区"
          >
            <MessageCircle className="h-3.5 w-3.5 shrink-0" />
            {!effectiveCollapsed ? <span className="whitespace-nowrap text-xs tracking-[0.01em]">社区</span> : null}
          </button>
          <button
            type="button"
            onClick={onOpenSettings}
            className={cn(
              "flex items-center text-slate-500 transition-colors hover:bg-[#eef3f8] hover:text-slate-900 focus:outline-none focus-visible:outline-none dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200",
              effectiveCollapsed ? "mx-auto h-7 w-7 justify-center rounded-md" : "h-7 w-full rounded-md px-2 gap-2",
            )}
            title="设置"
          >
            <Settings className="h-3.5 w-3.5 shrink-0" />
            {!effectiveCollapsed ? <span className="whitespace-nowrap text-xs tracking-[0.01em]">设置</span> : null}
          </button>
        </div>
      </aside>

      <CourseDeleteConfirmModal
        open={isDeleteModalOpen}
        course={deleteTarget}
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
            deleteMutation.mutate({
              courseId: deleteTarget.course_id,
              knownDetailCounts: deletePreview?.detail_counts,
            });
          }
        }}
      />

      {renameTarget ? (
        <RenameCourseModal
          courseId={renameTarget.id}
          initialName={renameTarget.name}
          onClose={() => setRenameTarget(null)}
          onSuccess={() => void queryClient.invalidateQueries({ queryKey: ["courses"] })}
        />
      ) : null}

      {exportCourseId ? (
        <CourseExportModal courseId={exportCourseId} onClose={() => setExportCourseId(null)} />
      ) : null}

      {isImportModalOpen ? (
        <CourseImportModal onClose={() => setIsImportModalOpen(false)} />
      ) : null}

      <CommunityModal isOpen={isCommunityModalOpen} onClose={() => setIsCommunityModalOpen(false)} />
    </>
  );
}
