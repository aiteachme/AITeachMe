import type { ReactNode } from "react";

export const COURSE_PAGE_HEADER_ACTION_BUTTON_CLASS =
  "h-10 rounded-lg bg-white px-4 text-sm font-semibold shadow-sm dark:bg-slate-950";
export const COURSE_PAGE_SHELL_CLASS = "mx-auto min-h-full w-full max-w-[1500px] px-4 pb-24 sm:px-6 lg:px-8 xl:px-10";
export const COURSE_PAGE_CONTENT_CLASS = "mx-auto flex w-full max-w-[1400px] flex-col";

interface CourseTitleParts {
  main: string;
  emphasis: string | null;
}

function splitCourseTitle(title: string): CourseTitleParts {
  const trimmed = title.trim() || "当前课程";
  const match = trimmed.match(/^(.+?)(\d+\s*天\s*(?:速通|通关)|\d+\s*天|速通|通关)$/u);
  if (!match) {
    return { main: trimmed, emphasis: null };
  }
  return {
    main: match[1].trim() || trimmed,
    emphasis: match[2].replace(/\s+/g, ""),
  };
}

function CourseHeaderTitle({ title }: { title: string }) {
  const parts = splitCourseTitle(title);

  return (
    <div className="min-w-0">
      <h1 className="break-words text-[30px] font-black leading-[1.06] tracking-normal text-slate-950 dark:text-slate-50 sm:text-[38px] lg:text-[42px]">
        <span>{parts.main}</span>
        {parts.emphasis ? <span>{parts.emphasis}</span> : null}
      </h1>
      <div className="mt-3 h-1.5 w-20 rounded-full bg-indigo-500 dark:bg-indigo-400" />
    </div>
  );
}

interface CoursePageHeaderProps {
  title: string;
  description: string;
  actions?: ReactNode;
  className?: string;
}

export function CoursePageHeader({ title, description, actions, className = "" }: CoursePageHeaderProps) {
  return (
    <section className={`border-b border-slate-200 pb-5 dark:border-slate-800 ${className}`.trim()}>
      <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <CourseHeaderTitle title={title} />
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-500 dark:text-slate-400 sm:text-[15px]">
            {description}
          </p>
        </div>

        {actions ? <div className="flex shrink-0 flex-wrap gap-2 lg:justify-end">{actions}</div> : null}
      </div>
    </section>
  );
}
