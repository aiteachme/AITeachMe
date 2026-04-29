export const COURSES_IMPORTED_EVENT = "aiteachme:courses-imported";

export interface CoursesImportedDetail {
  courseId?: string;
}

export function notifyCoursesImported(detail: CoursesImportedDetail = {}) {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent<CoursesImportedDetail>(COURSES_IMPORTED_EVENT, { detail }));
}
