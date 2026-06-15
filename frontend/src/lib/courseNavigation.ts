import type { LucideIcon } from "lucide-react";
import {
  BarChart3,
  BookOpen,
  Compass,
  FileText,
  Sparkles,
} from "lucide-react";

export type CourseRouteId =
  | "nav"
  | "build"
  | "knowledge-docs"
  | "exams"
  | "profile";

export interface CourseNavItem {
  id: CourseRouteId;
  label: string;
  icon: LucideIcon;
  description: string;
}

export const COURSE_NAV_ITEMS: CourseNavItem[] = [
  {
    id: "nav",
    label: "导航",
    icon: Compass,
    description: "汇总课程入口、近期试卷和学习画像",
  },
  {
    id: "build",
    label: "构建",
    icon: Sparkles,
    description: "上传资料，规划并启动知识构建",
  },
  {
    id: "knowledge-docs",
    label: "知识库",
    icon: BookOpen,
    description: "查看知识文档、讲义与知识图谱",
  },
  {
    id: "exams",
    label: "考试",
    icon: FileText,
    description: "生成练习卷并完成测评",
  },
  {
    id: "profile",
    label: "学习画像",
    icon: BarChart3,
    description: "查看掌握度与复习任务",
  },
];

export const COURSE_ROUTE_REDIRECTS = {
  files: "build",
  upload: "build",
  summary: "knowledge-docs",
  "knowledge-graph": "knowledge-docs",
  chat: "knowledge-docs",
  exam: "exams",
  analysis: "profile",
  navigation: "nav",
  overview: "nav",
  doc: "knowledge-docs",
  docs: "knowledge-docs",
} as const;

const FULL_BLEED_COURSE_SEGMENTS = new Set<string>([
  ...COURSE_NAV_ITEMS.map((item) => item.id),
  ...Object.keys(COURSE_ROUTE_REDIRECTS),
]);

export const COURSE_ROUTE_BASE = "/courses";
export const LEGACY_COURSE_ROUTE_BASE = "/course";

const COURSE_PATH_PATTERN = /^\/courses?\/([^/?#]+)(?:\/([^?#]*))?/;

function encodeCoursePathSegment(segment: string): string {
  return encodeURIComponent(segment);
}

export function buildCoursePath(courseId: string, routeId: CourseRouteId): string {
  return buildCourseSubPath(courseId, routeId);
}

export function buildCourseSubPath(courseId: string, ...segments: Array<string | number | null | undefined>): string {
  const suffix = segments
    .filter((segment): segment is string | number => segment !== null && segment !== undefined && `${segment}` !== "")
    .map((segment) => encodeCoursePathSegment(String(segment)))
    .join("/");
  return suffix
    ? `${COURSE_ROUTE_BASE}/${encodeCoursePathSegment(courseId)}/${suffix}`
    : `${COURSE_ROUTE_BASE}/${encodeCoursePathSegment(courseId)}`;
}

export function getCourseIdFromPathname(pathname: string): string | null {
  const match = pathname.match(COURSE_PATH_PATTERN);
  if (!match?.[1]) {
    return null;
  }
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

export function getCourseRouteSegmentFromPathname(pathname: string): string | null {
  const match = pathname.match(COURSE_PATH_PATTERN);
  return match?.[2]?.split("/")[0] || null;
}

export function isCourseRouteActive(pathname: string, courseId: string, routeId: CourseRouteId): boolean {
  return getCourseIdFromPathname(pathname) === courseId && getCourseRouteSegmentFromPathname(pathname) === routeId;
}

export function isFullBleedCoursePath(pathname: string): boolean {
  const segment = getCourseRouteSegmentFromPathname(pathname);
  if (!segment) {
    return false;
  }
  return FULL_BLEED_COURSE_SEGMENTS.has(segment);
}
