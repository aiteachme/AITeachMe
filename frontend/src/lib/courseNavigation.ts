import type { LucideIcon } from "lucide-react";
import {
  BarChart3,
  BookOpen,
  FileText,
  Sparkles,
} from "lucide-react";

export type CourseRouteId =
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
  doc: "knowledge-docs",
  docs: "knowledge-docs",
} as const;

const FULL_BLEED_COURSE_SEGMENTS = new Set<string>([
  ...COURSE_NAV_ITEMS.map((item) => item.id),
  ...Object.keys(COURSE_ROUTE_REDIRECTS),
]);

export function buildCoursePath(courseId: string, routeId: CourseRouteId): string {
  return `/course/${courseId}/${routeId}`;
}

export function isFullBleedCoursePath(pathname: string): boolean {
  const match = pathname.match(/^\/course\/[^/]+\/([^/?#]+)/);
  if (!match?.[1]) {
    return false;
  }
  return FULL_BLEED_COURSE_SEGMENTS.has(match[1]);
}
