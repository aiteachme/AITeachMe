import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { AnimatePresence, motion, type Variants } from "framer-motion";
import {
  ChevronRight,
  Download,
  Edit3,
  FolderOpen,
  Loader2,
  Menu,
  MoreVertical,
  PackagePlus,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Trash2,
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
import { resolveCourseIcon, resolveCourseTone } from "../../lib/courseIcons";
import { COURSES_IMPORTED_EVENT } from "../../lib/courseEvents";
import { cn } from "../../lib/utils";
import { publicAssetPath } from "../../lib/publicAsset";
import { buildCoursePath, getCourseIdFromPathname } from "../../lib/courseNavigation";

import { CourseExportModal } from "../course/CourseExportModal";
import { CourseImportModal } from "../course/CourseImportModal";
import { CourseOperationModal } from "../course/CourseOperationModal";
import { CourseDeleteConfirmModal } from "./CourseDeleteConfirmModal";
import { CommunityModal, ensureCommunityQrPreloaded } from "./CommunityPanel";
import { AiConversationSidebarSection } from "../interaction/AiConversationSidebarSection";
import { useAiInteraction, type AiConversationScope } from "../interaction";

import { Button } from "../ui/Button";



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

type CourseWithIcon = CourseItem & { icon_key?: string | null };

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
    <CourseOperationModal
      eyebrow="Rename"
      title="重命名课程"
      description="更新课程在侧边栏和课程页中的显示名称，不会影响课程内容和学习记录。"
      icon={Edit3}
      tone="slate"
      onClose={onClose}
      className="max-w-2xl"
      sidebar={
        <div className="text-xs leading-5 text-slate-500 dark:text-slate-400">
          一个清晰的课程名会让后续导出、分享和复习定位都更稳定。
        </div>
      }
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} className="rounded-md text-slate-500 hover:text-slate-900">
            取消
          </Button>
          <Button
            onClick={() => renameMutation.mutate()}
            disabled={!name.trim() || renameMutation.isPending}
            className="rounded-md bg-slate-950 px-4 text-white shadow-none hover:bg-slate-800 hover:shadow-none dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-white"
          >
            {renameMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            保存名称
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <label className="block">
          <span className="text-sm font-medium text-slate-800 dark:text-slate-200">课程名称</span>
          <span className="mt-1 block text-xs leading-5 text-slate-500 dark:text-slate-400">
            建议使用学科、目标和阶段组合，例如“初中数学 14 天中考复习”。
          </span>
          <input
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && name.trim()) {
                renameMutation.mutate();
              }
            }}
            className="mt-3 h-11 w-full rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-900 placeholder:text-slate-400 transition focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-slate-500 dark:focus:ring-slate-800"
            placeholder="输入课程名称"
            autoFocus
          />
        </label>
        {renameMutation.isError ? (
          <p className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {getApiErrorMessage(renameMutation.error, "重命名失败，请重试")}
          </p>
        ) : null}
      </div>
    </CourseOperationModal>
  );
}

function displayCourseName(course: CourseItem): string {
  return course.name?.trim() || "未命名课程";
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

export function Sidebar({
  onOpenSettings,
  onMobileOpenChange,
}: {
  onOpenSettings?: () => void;
  onMobileOpenChange?: (isOpen: boolean) => void;
}) {

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
    fullscreenScope,
    closeAiInteraction,
    notifyConversationSessionsChanged,
  } = useAiInteraction();
  const effectiveCollapsed = !isMobileOpen && isCollapsed;
  const isLibraryActive = location.pathname === "/library";
  const isAssistantPage = location.pathname === "/assistant";
  const assistantScope = isAssistantPage ? fullscreenScope ?? activeScope : activeScope;
  const isCreateCourseActive = location.pathname === "/";
  const routeCourseId = useMemo(() => getCourseIdFromPathname(location.pathname), [location.pathname]);
  const sidebarConversationScope = useMemo<AiConversationScope>(() => {
    if (isAssistantPage && assistantScope) {
      return assistantScope;
    }
    if (routeCourseId) {
      return { type: "course", courseId: routeCourseId };
    }
    return { type: "global" };
  }, [assistantScope, isAssistantPage, routeCourseId]);
  const isCourseConversationScope = sidebarConversationScope.type === "course";

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    ensureCommunityQrPreloaded();
  }, []);

  useEffect(() => {
    onMobileOpenChange?.(isMobileOpen);
  }, [isMobileOpen, onMobileOpenChange]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }

    const largeScreenQuery = window.matchMedia("(min-width: 1024px)");
    const closeMobileSidebarOnLargeScreen = (event: MediaQueryListEvent | MediaQueryList) => {
      if (event.matches) {
        setIsMobileOpen(false);
      }
    };

    closeMobileSidebarOnLargeScreen(largeScreenQuery);
    largeScreenQuery.addEventListener("change", closeMobileSidebarOnLargeScreen);
    return () => largeScreenQuery.removeEventListener("change", closeMobileSidebarOnLargeScreen);
  }, []);

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
    const handleCoursesImported = () => {
      updateCourseSectionExpanded(true);
      setIsCollapsed(false);
    };
    window.addEventListener(COURSES_IMPORTED_EVENT, handleCoursesImported);
    return () => window.removeEventListener(COURSES_IMPORTED_EVENT, handleCoursesImported);
  }, [updateCourseSectionExpanded]);

  useEffect(() => {
    if (!routeCourseId) {
      return;
    }
    updateCourseSectionExpanded(true);
    setIsCollapsed(false);
  }, [routeCourseId, updateCourseSectionExpanded]);

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
      if (getCourseIdFromPathname(location.pathname) === courseId) {
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
  const openCreateCoursePage = useCallback(() => {
    setCourseActionError(undefined);
    setOpenMenuId(null);
    setIsMobileOpen(false);
    navigate("/", {
      state: { newEntryAt: Date.now() },
    });
  }, [navigate]);

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
        data-mobile-nav-toggle="true"
        onClick={() => setIsMobileOpen((prev) => !prev)}
        className={cn(
          "fixed left-4 top-[calc(1.125rem+env(safe-area-inset-top))] z-50 flex h-11 w-11 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-700 shadow-sm transition-[transform,opacity,background-color,box-shadow,color] duration-200 ease-out dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 lg:hidden",
          isMobileOpen
            ? "translate-x-[80vw] bg-white/65 text-slate-500 opacity-60 shadow-none backdrop-blur-[3px] dark:bg-slate-900/65 dark:text-slate-500"
            : "translate-x-0 opacity-100",
        )}
        aria-label={isMobileOpen ? "关闭导航" : "打开导航"}
      >
        <Menu className="h-5 w-5" />
      </button>

      {isMobileOpen ? (
        <div className="fixed inset-0 z-30 sidebar-backdrop lg:hidden" onClick={() => setIsMobileOpen(false)} />
      ) : null}

      <aside
        data-app-sidebar="true"
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex min-h-0 shrink-0 self-stretch flex-col overflow-hidden border-r border-slate-200/50 bg-white pt-[calc(0.75rem+env(safe-area-inset-top))] dark:border-slate-800/40 dark:bg-[#0b0f19] shadow-[6px_0_28px_rgba(15,23,42,0.08)] lg:shadow-none dark:shadow-[6px_0_28px_rgba(0,0,0,0.36)] lg:dark:shadow-none ring-1 ring-slate-900/5 lg:ring-0 dark:ring-white/5 lg:dark:ring-0 transition-[width,transform] duration-200 lg:relative lg:z-[90] lg:pt-0",
          "rounded-none",
          isMobileOpen ? "w-[80vw] lg:w-[240px]" : effectiveCollapsed ? "w-[56px]" : "w-[240px]",
          isMobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
        )}
      >
        <div
          className={cn(
            "flex shrink-0 items-center border-b border-slate-100 dark:border-slate-800/50",
            isMobileOpen ? "h-14" : "h-12",
            effectiveCollapsed ? "justify-center px-0" : isMobileOpen ? "justify-between px-4" : "justify-between px-3",
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
              <Link to="/" className="flex h-11 items-center gap-2 pl-2 text-slate-900 dark:text-slate-100">
                <img src={LOGO_SRC} alt="AITeachMe" className="h-5 w-auto dark:invert dark:opacity-90" />
                {isMobileOpen ? (
                  <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                    AITeachMe
                  </span>
                ) : null}
              </Link>
              <button
                type="button"
                onClick={() => {
                  if (isMobileOpen) {
                    setIsMobileOpen(false);
                    return;
                  }
                  setIsCollapsed(true);
                }}
                className="flex h-11 w-11 items-center justify-center rounded-xl text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-800/50 dark:hover:text-slate-300 lg:h-8 lg:w-8 lg:rounded"
                aria-label={isMobileOpen ? "关闭导航" : "收起侧边栏"}
                title={isMobileOpen ? "关闭导航" : "收起侧边栏"}
              >
                <PanelLeftClose className="h-5 w-5 lg:h-4 lg:w-4" />
              </button>
            </>
          )}
        </div>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className={cn("shrink-0 space-y-1", effectiveCollapsed ? "px-0 pb-2 pt-1" : isMobileOpen ? "px-4 pb-2 pt-2" : "px-3 pb-2 pt-1")}>
            {effectiveCollapsed ? (
              <div className="flex flex-col items-center gap-1">
                <button
                  type="button"
                  onClick={() => {
                    setIsCollapsed(false);
                    openCreateCoursePage();
                  }}
                  title="新建课程"
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-md transition-colors",
                    isCreateCourseActive
                      ? "bg-[#eef2f6] text-[#243246] ring-1 ring-[#d9e1ea] hover:bg-[#e4ebf3] hover:text-[#182437] dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700 dark:hover:bg-slate-700/70 dark:hover:text-slate-50"
                      : "text-slate-500 hover:bg-[#eef3f8] hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200",
                  )}
                >
                  <Edit3 className="h-4 w-4 shrink-0" strokeWidth={2.2} />
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
                  "flex h-8 w-8 items-center justify-center rounded-md transition-colors",
                  isLibraryActive
                    ? "bg-[#eef2f6] text-[#243246] ring-1 ring-[#d9e1ea] hover:bg-[#e4ebf3] hover:text-[#182437] dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700 dark:hover:bg-slate-700/70 dark:hover:text-slate-50"
                    : "text-slate-500 hover:bg-[#eef3f8] hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200",
                )}
              >
                <FolderOpen className="h-4 w-4 shrink-0" strokeWidth={2.2} />
              </button>
            </div>
          ) : (
            <>
              <button
                type="button"
                className={cn(
                  "group flex w-full items-center gap-2 rounded-md px-2 text-left transition-colors",
                  isMobileOpen ? "h-10" : "h-8",
                  isCreateCourseActive
                    ? "bg-[#f3f6f9] text-slate-950 ring-1 ring-[#dbe3ec] hover:bg-[#e8eef5] dark:bg-slate-800/80 dark:text-slate-100 dark:ring-slate-700 dark:hover:bg-slate-700/70"
                    : "text-slate-900 hover:bg-[#eef3f8] dark:text-slate-300 dark:hover:bg-slate-800/60",
                )}
                onClick={openCreateCoursePage}
              >
                <Edit3
                  className={cn(
                    "shrink-0 transition-colors",
                    isMobileOpen ? "h-5 w-5" : "h-4 w-4",
                    isCreateCourseActive
                      ? "text-[#4b607b] group-hover:text-[#324761] dark:text-slate-300 dark:group-hover:text-slate-100"
                      : "text-slate-500 group-hover:text-slate-700 dark:text-slate-400 dark:group-hover:text-slate-200",
                  )}
                  strokeWidth={2.2}
                />
                <span
                  className={cn(
                    "whitespace-nowrap",
                    isMobileOpen ? "text-sm" : "text-xs",
                    isCreateCourseActive
                      ? "font-semibold text-[#1f2937] group-hover:text-[#172033] dark:text-slate-100 dark:group-hover:text-white"
                      : "font-normal text-slate-900 group-hover:text-slate-950 dark:text-slate-300 dark:group-hover:text-slate-100",
                  )}
                >
                  新建课程
                </span>
              </button>

              <button
                type="button"
                className={cn(
                  "group flex w-full items-center gap-2 rounded-md px-2 text-left transition-colors",
                  isMobileOpen ? "h-10" : "h-8",
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
                    "shrink-0 transition-colors",
                    isMobileOpen ? "h-5 w-5" : "h-4 w-4",
                    isLibraryActive
                      ? "text-[#4b607b] group-hover:text-[#324761] dark:text-slate-300 dark:group-hover:text-slate-100"
                      : "text-slate-500 group-hover:text-slate-700 dark:text-slate-400 dark:group-hover:text-slate-200",
                  )}
                  strokeWidth={2.2}
                />
                <span
                  className={cn(
                    "whitespace-nowrap",
                    isMobileOpen ? "text-sm" : "text-xs",
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

        <div
          className={cn(
            "min-h-0 flex-1 space-y-2 overflow-y-auto overflow-x-hidden pb-3 scrollbar-thin scrollbar-webkit",
            effectiveCollapsed ? "px-2" : isMobileOpen ? "px-4" : "px-3",
          )}
        >
          {!effectiveCollapsed ? (
            <div className={cn("flex items-center gap-1", isMobileOpen ? "h-10" : "h-8")}>
              <button
                type="button"
                onClick={() => updateCourseSectionExpanded((value) => !value)}
                className="group flex min-w-0 flex-1 items-center gap-1 rounded-md px-2 text-left text-[13px] font-medium text-slate-500 transition-colors hover:bg-[#eef3f8] hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200"
                aria-expanded={isCourseSectionExpanded}
              >
                <span className="truncate">课程</span>
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
                onClick={() => {
                  setCourseActionError(undefined);
                  setOpenMenuId(null);
                  setIsImportModalOpen(true);
                }}
                className={cn(
                  "flex shrink-0 items-center justify-center gap-1 rounded-md font-medium text-slate-500 transition hover:bg-[#eef3f8] hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300/70 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200 dark:focus-visible:ring-slate-700",
                  isMobileOpen ? "h-8 px-2 text-sm" : "h-7 px-1.5 text-[13px]",
                )}
                title="导入课程包"
                aria-label="导入课程包"
              >
                <PackagePlus className={cn("shrink-0", isMobileOpen ? "h-4 w-4" : "h-3.5 w-3.5")} strokeWidth={2.1} />
                <span>导入课程</span>
              </button>
            </div>
          ) : (
            <div className="flex h-6 items-center px-1">
              <div className="h-px w-full bg-slate-200 dark:bg-slate-800" />
            </div>
          )}

          {!isLoading && groupedCourses.length === 0 && !effectiveCollapsed && isCourseSectionExpanded ? (
            <p className="-mt-1 overflow-hidden whitespace-nowrap px-4 py-0 text-[12px] text-slate-300 dark:text-slate-600">暂无课程</p>
          ) : null}

          <AnimatePresence initial={false}>
            {shouldShowCourseList ? (
              <motion.div
                key="courses-list"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.18, ease: "easeOut" }}
                className="min-h-0 overflow-hidden"
              >
                <motion.div
                  className="space-y-0.5 overflow-x-hidden overflow-y-auto pr-1 max-h-[260px] xl:max-h-[300px] scrollbar-thin scrollbar-webkit"
                  variants={shouldAnimateCourseItems ? sidebarListContainerMotion : undefined}
                  initial={shouldAnimateCourseItems ? "hidden" : false}
                  animate={shouldAnimateCourseItems ? "visible" : undefined}
                >
                  <AnimatePresence initial={false}>
              {groupedCourses.map((course) => {

                const displayName = displayCourseName(course);
                const CourseIcon = resolveCourseIcon((course as CourseWithIcon).icon_key);
                const toneClass = resolveCourseTone(displayName);
                const isActive = getCourseIdFromPathname(location.pathname) === course.course_id;

                return (
                  <motion.div
                    key={course.course_id}
                    ref={openMenuId === course.course_id ? menuRef : undefined}
                    variants={shouldAnimateCourseItems ? sidebarItemMotion : undefined}
                    initial={shouldAnimateCourseItems ? "hidden" : false}
                    animate={shouldAnimateCourseItems ? "visible" : undefined}
                    exit={shouldAnimateCourseItems ? "exit" : undefined}
                    className="relative"
                  >
                <div
                  className={cn(
                    "group relative flex items-center rounded-md transition-all duration-200",
                    isMobileOpen ? "h-10" : "h-8",
                    isActive
                      ? "bg-[#e2eaf2] shadow-sm ring-1 ring-black/5 dark:bg-slate-800 dark:ring-white/10"
                      : !effectiveCollapsed ? "hover:bg-[#eef3f8] dark:hover:bg-slate-800/60" : "",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => {
                      if (effectiveCollapsed) {
                        setIsCollapsed(false);
                      }
                      if (isMobileOpen) {
                        setIsMobileOpen(false);
                      }
                      navigate(buildCoursePath(course.course_id, "nav"));
                    }}
                    className={cn(
                      "flex items-center transition-colors min-w-0 w-full",
                      effectiveCollapsed
                        ? "h-8 justify-center rounded-md px-0"
                        : isMobileOpen
                        ? "h-10 rounded-md px-2"
                        : "h-8 rounded-md px-2",
                    )}
                    title={effectiveCollapsed ? displayName : undefined}
                  >
                    <div
                      className={cn(
                        "flex shrink-0 items-center justify-center bg-gradient-to-br font-bold text-white shadow-sm",
                        effectiveCollapsed ? "h-5 w-5 rounded text-[10px]" : isMobileOpen ? "h-6 w-6 rounded-md text-[11px]" : "h-5 w-5 rounded text-[10px]",
                        toneClass,
                      )}
                    >
                      <CourseIcon className={cn(isMobileOpen ? "h-4 w-4" : "h-3.5 w-3.5")} strokeWidth={2.2} />
                    </div>
                    {!effectiveCollapsed ? <span className={cn("ml-2 truncate pr-4 font-medium text-slate-700 dark:text-slate-300", isMobileOpen ? "text-sm" : "text-xs")}>{displayName}</span> : null}
                  </button>

                  {!effectiveCollapsed ? (
                    <>
                      <div className="absolute right-1 top-1/2 -translate-y-1/2">
                        <button
                          type="button"
                          onClick={() => setOpenMenuId((prev) => (prev === course.course_id ? null : course.course_id))}
                          className={cn(
                            "flex shrink-0 items-center justify-center rounded text-slate-400 opacity-100 transition-all hover:text-slate-700 dark:text-slate-500 dark:hover:text-slate-300 sm:opacity-0 sm:group-hover:opacity-100",
                            isActive ? "bg-[#e2eaf2] dark:bg-slate-800" : "bg-[#eef3f8] dark:bg-slate-800/60",
                            isMobileOpen ? "h-8 w-8" : "h-6 w-6",
                          )}
                          title="更多操作"
                        >
                          <MoreVertical className={cn(isMobileOpen ? "h-5 w-5" : "h-4 w-4")} />
                        </button>
                    </div>
                    </>
                  ) : null}
                </div>

                {openMenuId === course.course_id ? (
                  <div className="ml-8 mr-1 mt-1 overflow-hidden rounded-lg border border-slate-200 bg-white p-1 shadow-sm ring-1 ring-slate-950/5 dark:border-slate-700 dark:bg-slate-900 dark:ring-white/5">
                    <button
                      type="button"
                      onClick={() => {
                        setOpenMenuId(null);
                        setCourseActionError(undefined);
                        setExportCourseId(course.course_id);
                      }}
                      className="group flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400 dark:text-slate-200 dark:hover:bg-slate-800"
                    >
                      <Download className="h-4 w-4 shrink-0 text-slate-400 transition group-hover:text-slate-700 dark:text-slate-500 dark:group-hover:text-slate-200" />
                      <span className="min-w-0">
                        <span className="block font-medium text-slate-900 dark:text-slate-100">导出 .atmx</span>
                        <span className="block text-[11px] leading-4 text-slate-500 dark:text-slate-400">课程迁移包</span>
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setOpenMenuId(null);
                        setRenameTarget({ id: course.course_id, name: displayName === "未命名课程" ? "" : course.name });
                      }}
                      className="group flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm transition hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800"
                    >
                      <Edit3 className="h-4 w-4 shrink-0 text-slate-400 transition group-hover:text-slate-700 dark:text-slate-500 dark:group-hover:text-slate-200" />
                      <span className="min-w-0">
                        <span className="block font-medium text-slate-900 dark:text-slate-100">重命名</span>
                        <span className="block text-[11px] leading-4 text-slate-500 dark:text-slate-400">显示名称</span>
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setOpenMenuId(null);
                        openDeleteModal(course);
                      }}
                      className="mt-1 flex w-full items-center gap-2.5 rounded-md border-t border-slate-100 px-2.5 py-2 text-left text-sm text-red-600 transition hover:bg-red-50 dark:border-slate-800 dark:text-red-400 dark:hover:bg-red-500/10"
                    >
                      <Trash2 className="h-4 w-4 shrink-0" />
                      <span className="min-w-0">
                        <span className="block font-medium">删除课程</span>
                        <span className="block text-[11px] leading-4 text-red-500/80 dark:text-red-300/80">不可撤销</span>
                      </span>
                    </button>
                  </div>
                ) : null}


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
            targetScope={sidebarConversationScope}
            title={isCourseConversationScope ? "课程最近" : "全局最近"}
            showCourseBadge={false}
            emptyText={isMobileOpen && !isCourseConversationScope ? "" : isCourseConversationScope ? "暂无课程对话" : "暂无全局对话"}
          />
        </div>
        </div>

        {/* Bottom actions */}
        <div
          className={cn(
            "z-10 mt-auto shrink-0 space-y-1 border-t border-slate-200/80 dark:border-slate-800/50",
            effectiveCollapsed ? "p-2" : isMobileOpen ? "px-4 py-2.5" : "px-3 py-2",
          )}
        >
          <button
            type="button"
            onClick={() => setIsCommunityModalOpen(true)}
            onMouseEnter={ensureCommunityQrPreloaded}
            className={cn(
              "flex items-center text-slate-500 transition-colors hover:bg-[#eef3f8] hover:text-slate-900 focus:outline-none focus-visible:outline-none dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200",
              effectiveCollapsed ? "mx-auto h-8 w-8 justify-center rounded-md" : isMobileOpen ? "h-10 w-full rounded-md px-2 gap-2.5" : "h-8 w-full rounded-md px-2 gap-2",
            )}
            title="社区"
          >
            <MessageCircle className={cn("shrink-0", isMobileOpen ? "h-5 w-5" : "h-4 w-4")} />
            {!effectiveCollapsed ? <span className={cn("whitespace-nowrap", isMobileOpen ? "text-sm" : "text-xs")}>社区</span> : null}
          </button>
          <button
            type="button"
            onClick={onOpenSettings}
            className={cn(
              "flex items-center text-slate-500 transition-colors hover:bg-[#eef3f8] hover:text-slate-900 focus:outline-none focus-visible:outline-none dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200",
              effectiveCollapsed ? "mx-auto h-8 w-8 justify-center rounded-md" : isMobileOpen ? "h-10 w-full rounded-md px-2 gap-2.5" : "h-8 w-full rounded-md px-2 gap-2",
            )}
            title="设置"
          >
            <Settings className={cn("shrink-0", isMobileOpen ? "h-5 w-5" : "h-4 w-4")} />
            {!effectiveCollapsed ? <span className={cn("whitespace-nowrap", isMobileOpen ? "text-sm" : "text-xs")}>设置</span> : null}
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
