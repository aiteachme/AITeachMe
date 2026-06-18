import { useMemo } from "react";
import { Link, useParams, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { LucideIcon } from "lucide-react";
import {
  Compass,
  Sparkles,
  BookOpen,
  FileText,
  BarChart3,
  Lock,
} from "lucide-react";

import { cn } from "../../lib/utils";
import { buildCoursePath, getCourseRouteSegmentFromPathname } from "../../lib/courseNavigation";
import { apiClient } from "../../api/client";
import type { ApiResponse } from "../../api/types";
import type { DocGenGetResponse } from "../../api/generated/model";
import { TopBar } from "../layout/TopBar";

interface CoursePagePillTitleProps {
  icon: LucideIcon;
  label: string;
  href?: string;
  className?: string;
  innerClassName?: string;
}

export function CoursePagePillTitle({ icon: Icon, label, href, className, innerClassName }: CoursePagePillTitleProps) {
  const params = useParams<{ courseId: string }>();
  const { pathname } = useLocation();
  const courseId = params.courseId || (href ? href.split("/")[2] : undefined);
  const shellClassName = cn(
    "sticky top-0 z-30 grid h-16 w-full shrink-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center border-b border-slate-200/70 bg-[#fafafa]/92 px-4 backdrop-blur-md dark:border-slate-800/60 dark:bg-[#0b0f19]/92",
    className,
  );
  const navClassName = cn(
    "flex max-w-full items-center gap-1.5 overflow-x-auto rounded-lg border border-slate-200/80 bg-white/95 p-1.5 shadow-[0_2px_12px_rgba(15,23,42,0.05)] scrollbar-none dark:border-slate-800/80 dark:bg-slate-900/95",
    innerClassName,
  );

  if (!courseId) {
    const inner = (
      <div className={cn("inline-flex h-8 items-center gap-2 rounded-md px-3 text-[12px] font-semibold text-slate-600 dark:text-slate-300", innerClassName)}>
        <Icon className="h-3 w-3 shrink-0" />
        <span>{label}</span>
      </div>
    );
    return (
      <div className={shellClassName}>
        <div />
        {inner}
        <div className="flex justify-end">
          <TopBar />
        </div>
      </div>
    );
  }

  // 1. Query Document Build Status
  const docMarkdownQuery = useQuery({
    queryKey: ["docgen-content", courseId, null],
    queryFn: async (): Promise<DocGenGetResponse> => {
      if (!courseId) throw new Error("缺少课程 ID");
      const response = await apiClient<ApiResponse<DocGenGetResponse>>({
        method: "POST",
        url: `/api/v1/courses/${courseId}/knowledge/docs`,
      });
      if (!response.data) throw new Error("加载知识文档状态失败");
      return response.data;
    },
    enabled: Boolean(courseId),
    staleTime: 30000,
  });

  const buildStatus = useMemo(() => {
    return (docMarkdownQuery.data?.build?.status ?? "").trim();
  }, [docMarkdownQuery.data?.build?.status]);

  const isBuilding = useMemo(() => {
    const status = buildStatus;
    return status === "accepted" || status === "running" || status === "publishing";
  }, [buildStatus]);

  const isBuilt = useMemo(() => {
    return Boolean(docMarkdownQuery.data?.exists);
  }, [docMarkdownQuery.data?.exists]);

  const hasDraftDoc = useMemo(() => {
    const data = docMarkdownQuery.data as (DocGenGetResponse & { draft_markdown?: string | null }) | undefined;
    return Boolean(String(data?.draft_markdown ?? "").trim());
  }, [docMarkdownQuery.data]);

  const hasBuildStarted = useMemo(() => {
    return isBuilt || hasDraftDoc || Boolean(buildStatus && buildStatus !== "idle");
  }, [buildStatus, hasDraftDoc, isBuilt]);

  const currentSegment = getCourseRouteSegmentFromPathname(pathname);

  const navItems = [
    { id: "build", label: "方案规划", icon: Sparkles, href: buildCoursePath(courseId, "build") },
    { id: "knowledge-docs", label: "知识库", icon: BookOpen, href: buildCoursePath(courseId, "knowledge-docs") },
    { id: "exams", label: "训练中心", icon: FileText, href: buildCoursePath(courseId, "exams") },
    { id: "profile", label: "学习画像", icon: BarChart3, href: buildCoursePath(courseId, "profile") },
  ] as const;

  return (
    <div className={shellClassName}>
      <div />
      <nav className={navClassName} aria-label="课程页面导航">
        {href && (
          <Link
            to={href}
            className="group flex h-8 shrink-0 items-center gap-2 rounded-md px-3 text-[12px] font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
            title="返回课程导航页"
            aria-label="返回课程导航页"
          >
            <Compass className="h-3.5 w-3.5 shrink-0 text-slate-400 transition-colors group-hover:text-indigo-600 dark:group-hover:text-indigo-400" />
            <span className="hidden whitespace-nowrap sm:inline">导航页</span>
          </Link>
        )}

        {href ? <div className="h-5 w-px shrink-0 bg-slate-200 dark:bg-slate-800" /> : null}

        {navItems.map((item) => {
          const isActive = item.id === currentSegment || (item.id === "exams" && label === "训练中心");
          let disabledReason = "";
          if (item.id === "knowledge-docs" && docMarkdownQuery.isFetched && !hasBuildStarted) {
            disabledReason = "请先开始构建知识库";
          } else if (item.id === "exams" && (!isBuilt || isBuilding)) {
            disabledReason = isBuilding ? "知识库构建中" : "请先构建知识库";
          } else if (item.id === "profile") {
            if (!isBuilt || isBuilding) {
              disabledReason = isBuilding ? "知识库构建中" : "请先构建知识库";
            }
          }

          const itemClassName = cn(
            "flex h-8 shrink-0 items-center gap-2 rounded-md px-3 text-[12px] font-medium transition-colors",
            isActive
              ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-950/45 dark:text-indigo-300"
              : "text-slate-600 hover:bg-slate-100 hover:text-slate-950 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white",
          );

          if (disabledReason) {
            return (
              <div
                key={item.id}
                title={disabledReason}
                aria-disabled="true"
                className="flex h-8 shrink-0 cursor-not-allowed select-none items-center gap-2 rounded-md px-3 text-[12px] font-medium text-slate-400 dark:text-slate-600"
              >
                <item.icon className="h-3.5 w-3.5 shrink-0 text-slate-300 dark:text-slate-700" />
                <span className="whitespace-nowrap">{item.label}</span>
                <Lock className="h-3 w-3 shrink-0 text-slate-300 dark:text-slate-700" strokeWidth={1.5} />
              </div>
            );
          }

          return (
            <Link
              key={item.id}
              to={item.href}
              className={itemClassName}
              aria-current={isActive ? "page" : undefined}
              title={item.label}
            >
              <item.icon className={cn("h-3.5 w-3.5 shrink-0", isActive ? "text-indigo-600 dark:text-indigo-300" : "text-slate-400")} />
              <span className="whitespace-nowrap">{item.label}</span>
            </Link>
          );
        })}
      </nav>
      <div className="flex justify-end pr-1">
        <TopBar />
      </div>
    </div>
  );
}
