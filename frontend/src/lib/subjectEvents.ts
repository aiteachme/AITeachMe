export const SUBJECTS_IMPORTED_EVENT = "aiteachme:subjects-imported";

export interface SubjectsImportedDetail {
  subjectId?: string;
}

export function notifySubjectsImported(detail: SubjectsImportedDetail = {}) {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent<SubjectsImportedDetail>(SUBJECTS_IMPORTED_EVENT, { detail }));
}
