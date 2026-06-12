import { useState, useRef, useEffect, useMemo } from "react";
import { Link, useParams, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { LucideIcon } from "lucide-react";
import {
  ChevronDown,
  Compass,
  Sparkles,
  BookOpen,
  FileText,
  BarChart3,
  Lock,
} from "lucide-react";

import { cn } from "../../lib/utils";
import { buildCoursePath, getCourseRouteSegmentFromPathname } from "../../lib/courseNavigation";
import { AnimatePresence, motion } from "framer-motion";
import { useMasteryOverviewApiV1CoursesCourseIdProfileMasteryGet } from "../../api/generated/profile";
import { useExamHistoryApiV1CoursesCourseIdExamsHistoryGet } from "../../api/generated/exams";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { apiClient } from "../../api/client";
import type { ApiResponse } from "../../api/types";
import type { DocGenGetResponse, ExamHistoryItem } from "../../api/generated/model";

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
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    const handleOutsideClick = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, [isOpen]);

  if (!courseId) {
    const inner = (
      <div className={cn("group inline-flex items-center gap-2 rounded-full border border-slate-200/80 bg-white px-3 py-1.5 text-[11px] font-semibold uppercase tracking-widest text-slate-500 shadow-[0_2px_10px_rgb(0,0,0,0.02)] transition-all dark:border-slate-800/80 dark:bg-slate-900 dark:text-slate-400", innerClassName)}>
        <Icon className="h-3 w-3 shrink-0" />
        <span>{label}</span>
      </div>
    );
    return (
      <div className={cn("flex items-center justify-center pb-2 pt-6 z-10 relative", className)}>
        {inner}
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

  const isBuilding = useMemo(() => {
    const status = (docMarkdownQuery.data?.build?.status ?? "").trim();
    return status === "accepted" || status === "running" || status === "publishing";
  }, [docMarkdownQuery.data]);

  // 2. Query Mastery Overview
  const masteryQuery = useMasteryOverviewApiV1CoursesCourseIdProfileMasteryGet(
    courseId ?? "",
    { query: { enabled: Boolean(courseId) } }
  );

  const isBuilt = useMemo(() => {
    const masteryData = unwrapOrvalResponse<any>(masteryQuery.data);
    return Boolean(masteryData?.course_profile?.generated_at);
  }, [masteryQuery.data]);

  // 3. Query Exam History
  const historyQuery = useExamHistoryApiV1CoursesCourseIdExamsHistoryGet(
    courseId ?? "",
    { page: 1, size: 24 },
    { query: { enabled: Boolean(courseId) } }
  );

  const hasExams = useMemo(() => {
    const historyItems = unwrapOrvalResponse<{ items?: ExamHistoryItem[] }>(historyQuery.data)?.items ?? [];
    return historyItems.length > 0;
  }, [historyQuery.data]);

  const currentSegment = getCourseRouteSegmentFromPathname(pathname);

  const navItems = [
    { id: "build", label: "方案规划", icon: Sparkles, href: buildCoursePath(courseId, "build") },
    { id: "knowledge-docs", label: "知识库", icon: BookOpen, href: buildCoursePath(courseId, "knowledge-docs") },
    { id: "exams", label: "训练中心", icon: FileText, href: buildCoursePath(courseId, "exams") },
    { id: "profile", label: "学习画像", icon: BarChart3, href: buildCoursePath(courseId, "profile") },
  ] as const;

  return (
    <div ref={dropdownRef} className={cn("flex flex-col items-center justify-center pb-2 pt-6 z-30 relative", className)}>
      <div className={cn("inline-flex items-center rounded-full border border-slate-200/80 bg-white shadow-[0_2px_10px_rgba(0,0,0,0.02)] transition-all dark:border-slate-800/80 dark:bg-slate-900", innerClassName)}>
        
        {/* Left Back Arrow: Directly links back to dashboard / main navigation page */}
        {href && (
          <Link
            to={href}
            className="flex h-8 items-center pl-3 pr-2.5 rounded-l-full border-r border-slate-100 hover:bg-slate-55 dark:border-slate-800 dark:hover:bg-slate-800 text-slate-405 hover:text-indigo-600 transition-colors"
            title="返回课程大盘"
          >
            <Compass className="h-4 w-4" />
          </Link>
        )}

        {/* Middle/Right: Dropdown trigger */}
        <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          className={cn(
            "flex h-8 items-center gap-1.5 px-3 text-[11px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400 hover:text-indigo-650 dark:hover:text-indigo-400 transition-colors rounded-r-full",
            !href && "rounded-l-full"
          )}
        >
          <Icon className="h-3.5 w-3.5 shrink-0 text-slate-400 group-hover:text-indigo-505" />
          <span>{label}</span>
          <ChevronDown className={cn("h-3 w-3 text-slate-400 transition-transform duration-200", isOpen && "rotate-180")} />
        </button>
      </div>

      {/* Dropdown Menu */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: -8, scale: 0.95 }}
            animate={{ opacity: 1, y: 4, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.95 }}
            transition={{ duration: 0.15, ease: "easeOut" }}
            className="absolute top-full mt-1.5 w-44 rounded-xl border border-slate-200/70 bg-white/95 backdrop-blur-md p-1.5 shadow-[0_10px_25px_rgba(0,0,0,0.08)] dark:border-slate-800/80 dark:bg-slate-900/95 z-50"
          >
            {navItems.map((item) => {
              const isActive = item.id === currentSegment || (item.id === "exams" && label === "训练中心");
              
              // Define disabled state and reason
              let isDisabled = false;
              let disabledReason = "";
              if (item.id === "exams") {
                if (!isBuilt || isBuilding) {
                  isDisabled = true;
                  disabledReason = isBuilding ? "知识库构建中" : "请先构建知识库";
                }
              } else if (item.id === "profile") {
                if (!isBuilt || isBuilding) {
                  isDisabled = true;
                  disabledReason = isBuilding ? "知识库构建中" : "请先构建知识库";
                } else if (!hasExams) {
                  isDisabled = true;
                  disabledReason = "需先完成测验";
                }
              }

              if (isDisabled) {
                return (
                  <div
                    key={item.id}
                    title={disabledReason}
                    className="flex items-center justify-between w-full px-3 py-2 text-[12px] font-semibold text-slate-400 dark:text-slate-600 cursor-not-allowed select-none"
                  >
                    <span className="flex items-center gap-2">
                      <item.icon className="h-3.5 w-3.5 text-slate-300 dark:text-slate-700" />
                      <span className="font-medium">{item.label}</span>
                    </span>
                    <Lock className="h-3.5 w-3.5 text-slate-300 dark:text-slate-700" strokeWidth={1.5} />
                  </div>
                );
              }

              return (
                <Link
                  key={item.id}
                  to={item.href}
                  onClick={() => setIsOpen(false)}
                  className={cn(
                    "flex items-center gap-2 w-full px-3 py-2 text-left text-[12px] font-medium rounded-lg transition-colors",
                    isActive
                      ? "bg-indigo-50 text-indigo-600 dark:bg-indigo-950/40 dark:text-indigo-400"
                      : "text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 hover:text-slate-950 dark:hover:text-white"
                  )}
                >
                  <item.icon className={cn("h-3.5 w-3.5", isActive ? "text-indigo-600 dark:text-indigo-400" : "text-slate-400")} />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
