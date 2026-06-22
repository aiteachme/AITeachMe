import type {
  ChatMessageItem,
  ExamHistoryItem,
  MasteryStateResponse,
} from "../api/generated/model";

export type LearningActivityKind = "chat" | "exam" | "knowledge";

export interface LearningActivityEvent {
  id: string;
  kind: LearningActivityKind;
  occurredAt: string;
  label: string;
}

export interface LearningCalendarDay {
  key: string;
  label: string;
  day: string;
  count: number;
  intensity: number;
  isToday: boolean;
}

export interface LearningCalendarCell extends LearningCalendarDay {
  isPlaceholder: boolean;
}

export interface LearningCalendarWeek {
  key: string;
  days: LearningCalendarCell[];
}

interface BuildLearningActivityEventsInput {
  chatMessages?: ChatMessageItem[];
  exams?: ExamHistoryItem[];
  masteryStates?: MasteryStateResponse[];
}

interface BuildLearningCalendarDaysOptions {
  days?: number;
  today?: Date;
}

interface BuildLearningCalendarWeeksOptions {
  weeks?: number;
  today?: Date;
}

function toDateKey(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function parseTimestamp(value?: string | null): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function startOfDay(value: Date): Date {
  const date = new Date(value);
  date.setHours(0, 0, 0, 0);
  return date;
}

function mondayFirstWeekdayIndex(value: Date): number {
  return (value.getDay() + 6) % 7;
}

function clipLabel(value: string, fallback: string): string {
  const text = value.replace(/\s+/g, " ").trim();
  if (!text) return fallback;
  return text.length > 26 ? `${text.slice(0, 26)}...` : text;
}

function getExamActivityTimestamp(item: ExamHistoryItem): string | null {
  return item.submitted_at ?? item.graded_at ?? item.created_at ?? null;
}

function getKnowledgeUnitName(state: Pick<MasteryStateResponse, "knowledge_unit_id" | "knowledge_unit_name">) {
  return state.knowledge_unit_name?.trim() || `知识点 #${state.knowledge_unit_id}`;
}

export function buildLearningActivityEvents({
  chatMessages = [],
  exams = [],
  masteryStates = [],
}: BuildLearningActivityEventsInput): LearningActivityEvent[] {
  const events: LearningActivityEvent[] = [];

  for (const item of exams) {
    const occurredAt = getExamActivityTimestamp(item);
    if (!occurredAt || !parseTimestamp(occurredAt)) continue;
    events.push({
      id: `exam-${item.id}`,
      kind: "exam",
      occurredAt,
      label: item.status === "graded" || item.status === "submitted" ? "完成测验" : "创建测验",
    });
  }

  for (const message of chatMessages) {
    if (message.role !== "user" || !parseTimestamp(message.created_at)) continue;
    events.push({
      id: `chat-${message.id}`,
      kind: "chat",
      occurredAt: message.created_at,
      label: clipLabel(message.content, "发起问答"),
    });
  }

  for (const state of masteryStates) {
    if (!state.total_attempts || !parseTimestamp(state.last_attempt_at)) continue;
    events.push({
      id: `knowledge-${state.id}`,
      kind: "knowledge",
      occurredAt: state.last_attempt_at as string,
      label: getKnowledgeUnitName(state),
    });
  }

  return events.sort((left, right) => (
    new Date(right.occurredAt).getTime() - new Date(left.occurredAt).getTime()
  ));
}

export function buildLearningCalendarDays(
  events: LearningActivityEvent[],
  options: BuildLearningCalendarDaysOptions = {},
): LearningCalendarDay[] {
  const dayCount = Math.max(1, options.days ?? 28);
  const today = startOfDay(options.today ?? new Date());

  const days = Array.from({ length: dayCount }, (_, index) => {
    const date = new Date(today);
    date.setDate(today.getDate() - (dayCount - 1 - index));
    return {
      key: toDateKey(date),
      label: date.toLocaleDateString("zh-CN", { weekday: "short" }),
      day: String(date.getDate()),
      count: 0,
    };
  });
  const counts = new Map(days.map((day) => [day.key, 0]));

  for (const event of events) {
    const date = parseTimestamp(event.occurredAt);
    if (!date) continue;
    const key = toDateKey(date);
    if (counts.has(key)) {
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }

  return days.map((day) => {
    const count = counts.get(day.key) ?? 0;
    return {
      ...day,
      count,
      intensity: count >= 4 ? 3 : count >= 2 ? 2 : count > 0 ? 1 : 0,
      isToday: day.key === toDateKey(today),
    };
  });
}

export function buildLearningCalendarWeeks(
  events: LearningActivityEvent[],
  options: BuildLearningCalendarWeeksOptions = {},
): LearningCalendarWeek[] {
  const weekCount = Math.max(1, options.weeks ?? 8);
  const today = startOfDay(options.today ?? new Date());
  const start = new Date(today);
  start.setDate(today.getDate() - mondayFirstWeekdayIndex(today) - (weekCount - 1) * 7);

  const counts = new Map<string, number>();
  for (const event of events) {
    const date = parseTimestamp(event.occurredAt);
    if (!date) continue;
    const key = toDateKey(date);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }

  return Array.from({ length: weekCount }, (_, weekIndex) => {
    const weekStart = new Date(start);
    weekStart.setDate(start.getDate() + weekIndex * 7);
    return {
      key: toDateKey(weekStart),
      days: Array.from({ length: 7 }, (_, dayIndex) => {
        const date = new Date(weekStart);
        date.setDate(weekStart.getDate() + dayIndex);
        const key = toDateKey(date);
        const count = date <= today ? counts.get(key) ?? 0 : 0;
        return {
          key,
          label: date.toLocaleDateString("zh-CN", { weekday: "short" }),
          day: String(date.getDate()),
          count,
          intensity: count >= 4 ? 3 : count >= 2 ? 2 : count > 0 ? 1 : 0,
          isToday: key === toDateKey(today),
          isPlaceholder: date > today,
        };
      }),
    };
  });
}

export function countLearningActivitySince(events: LearningActivityEvent[], days: number): number {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() - Math.max(0, days - 1));
  const startMs = start.getTime();
  return events.filter((event) => {
    const date = parseTimestamp(event.occurredAt);
    return date ? date.getTime() >= startMs : false;
  }).length;
}

export function getLatestLearningActivity(events: LearningActivityEvent[]): LearningActivityEvent | null {
  return events[0] ?? null;
}

export function formatLearningActivityKind(kind: LearningActivityKind): string {
  if (kind === "exam") return "测验";
  if (kind === "chat") return "问答";
  return "知识点作答";
}

export function formatLearningActivityTime(value?: string | null): string {
  const date = parseTimestamp(value);
  if (!date) return "暂无记录";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function getLearningActivityTileClass(intensity: number): string {
  if (intensity >= 3) {
    return "bg-violet-600 text-white dark:bg-violet-500";
  }
  if (intensity === 2) {
    return "bg-violet-200 text-violet-800 dark:bg-violet-500/30 dark:text-violet-100";
  }
  if (intensity === 1) {
    return "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-200";
  }
  return "bg-slate-50 text-slate-400 dark:bg-slate-900 dark:text-slate-600";
}
