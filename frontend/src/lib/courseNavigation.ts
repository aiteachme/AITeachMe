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
    description: "汇总课程入口、近期试卷和课程画像",
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
    label: "课程画像",
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
const LAST_COURSE_ROUTE_STORAGE_PREFIX = "aiteachme.course.lastRoute";
const COURSE_ENTRY_FALLBACK_ROUTE: CourseRouteId = "knowledge-docs";
const REMEMBERABLE_COURSE_ROUTES = new Set<CourseRouteId>([
  "build",
  "knowledge-docs",
  "exams",
  "profile",
]);

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

function courseLastRouteStorageKey(courseId: string): string {
  return `${LAST_COURSE_ROUTE_STORAGE_PREFIX}.${courseId}`;
}

function normalizeRememberableCoursePath(courseId: string, path: string): string | null {
  const expectedPrefix = `${COURSE_ROUTE_BASE}/${encodeCoursePathSegment(courseId)}`;
  if (!path.startsWith(`${expectedPrefix}/`)) {
    return null;
  }
  const segment = getCourseRouteSegmentFromPathname(path);
  if (!segment || !REMEMBERABLE_COURSE_ROUTES.has(segment as CourseRouteId)) {
    return null;
  }
  return path;
}

export function rememberCourseRoute(path: string): void {
  if (typeof window === "undefined") {
    return;
  }
  const courseId = getCourseIdFromPathname(path);
  if (!courseId) {
    return;
  }
  const normalized = normalizeRememberableCoursePath(courseId, path);
  if (!normalized) {
    return;
  }
  try {
    window.localStorage.setItem(courseLastRouteStorageKey(courseId), normalized);
  } catch {
    // Restricted webviews may block storage; route fallback still works.
  }
}

export function buildPreferredCourseEntryPath(courseId: string): string {
  if (typeof window !== "undefined") {
    try {
      const stored = window.localStorage.getItem(courseLastRouteStorageKey(courseId));
      if (stored) {
        const normalized = normalizeRememberableCoursePath(courseId, stored);
        if (normalized) {
          return normalized;
        }
      }
    } catch {
      // Keep navigation usable even when localStorage is unavailable.
    }
  }
  return buildCoursePath(courseId, COURSE_ENTRY_FALLBACK_ROUTE);
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

export function isTrainingDetailPath(pathname: string): boolean {
  const match = pathname.match(COURSE_PATH_PATTERN);
  const routeParts = match?.[2]?.split("/").filter(Boolean) ?? [];
  return routeParts[0] === "exams" && routeParts.length > 1;
}

export function isFullBleedCoursePath(pathname: string): boolean {
  const segment = getCourseRouteSegmentFromPathname(pathname);
  if (!segment) {
    return false;
  }
  return FULL_BLEED_COURSE_SEGMENTS.has(segment);
}
