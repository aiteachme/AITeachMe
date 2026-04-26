import { useCallback, useEffect, useState } from "react";

export type ExamResultDisplayMode = "completed" | "score";

const EXAM_RESULT_DISPLAY_STORAGE_KEY = "aiteachme:exam-result-display-mode";
const EXAM_RESULT_DISPLAY_CHANGE_EVENT = "aiteachme:exam-result-display-mode-change";
const DEFAULT_EXAM_RESULT_DISPLAY_MODE: ExamResultDisplayMode = "score";

function isExamResultDisplayMode(value: unknown): value is ExamResultDisplayMode {
  return value === "completed" || value === "score";
}

export function readExamResultDisplayMode(): ExamResultDisplayMode {
  if (typeof window === "undefined") {
    return DEFAULT_EXAM_RESULT_DISPLAY_MODE;
  }

  try {
    const storedMode = window.localStorage.getItem(EXAM_RESULT_DISPLAY_STORAGE_KEY);
    return isExamResultDisplayMode(storedMode) ? storedMode : DEFAULT_EXAM_RESULT_DISPLAY_MODE;
  } catch {
    return DEFAULT_EXAM_RESULT_DISPLAY_MODE;
  }
}

export function writeExamResultDisplayMode(nextMode: ExamResultDisplayMode): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(EXAM_RESULT_DISPLAY_STORAGE_KEY, nextMode);
  } catch {
    // Keep the in-memory UI responsive even when storage is unavailable.
  }

  window.dispatchEvent(
    new CustomEvent<ExamResultDisplayMode>(EXAM_RESULT_DISPLAY_CHANGE_EVENT, {
      detail: nextMode,
    }),
  );
}

export function useExamResultDisplayPreference() {
  const [mode, setModeState] = useState<ExamResultDisplayMode>(() => readExamResultDisplayMode());

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const syncMode = () => {
      setModeState(readExamResultDisplayMode());
    };

    const handlePreferenceChange = (event: Event) => {
      const nextMode = event instanceof CustomEvent ? event.detail : null;
      setModeState(isExamResultDisplayMode(nextMode) ? nextMode : readExamResultDisplayMode());
    };

    const handleStorage = (event: StorageEvent) => {
      if (event.key === EXAM_RESULT_DISPLAY_STORAGE_KEY) {
        syncMode();
      }
    };

    syncMode();
    window.addEventListener(EXAM_RESULT_DISPLAY_CHANGE_EVENT, handlePreferenceChange);
    window.addEventListener("storage", handleStorage);
    return () => {
      window.removeEventListener(EXAM_RESULT_DISPLAY_CHANGE_EVENT, handlePreferenceChange);
      window.removeEventListener("storage", handleStorage);
    };
  }, []);

  const setMode = useCallback((nextMode: ExamResultDisplayMode) => {
    setModeState(nextMode);
    writeExamResultDisplayMode(nextMode);
  }, []);

  return { mode, setMode };
}
