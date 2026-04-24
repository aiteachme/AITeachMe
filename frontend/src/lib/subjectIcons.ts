import type { LucideIcon } from "lucide-react";
import {
  Atom,
  BookOpen,
  Brain,
  BriefcaseBusiness,
  Calculator,
  ChartLine,
  Code,
  FileText,
  FlaskConical,
  Globe,
  Landmark,
  Languages,
  Microscope,
  Music,
  Palette,
  Sigma,
} from "lucide-react";

export const SUBJECT_ICON_MAP: Record<string, LucideIcon> = {
  "book-open": BookOpen,
  calculator: Calculator,
  sigma: Sigma,
  "flask-conical": FlaskConical,
  atom: Atom,
  microscope: Microscope,
  code: Code,
  languages: Languages,
  brain: Brain,
  "briefcase-business": BriefcaseBusiness,
  "chart-line": ChartLine,
  landmark: Landmark,
  globe: Globe,
  palette: Palette,
  music: Music,
  "file-text": FileText,
};

export function resolveSubjectIcon(iconKey?: string | null): LucideIcon {
  return SUBJECT_ICON_MAP[String(iconKey || "").trim()] ?? BookOpen;
}
