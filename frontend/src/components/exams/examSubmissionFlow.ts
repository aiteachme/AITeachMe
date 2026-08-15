export type ExamSubmissionTerminalState = "graded" | "grading_failed" | null;

function wasGrading(status: string | null | undefined) {
  return status === "submitted" || status === "grading";
}

export function resolveExamSubmissionTerminalState(
  currentStatus: string | null | undefined,
  previousStatus: string | null | undefined,
  isLocalSubmissionPending: boolean,
): ExamSubmissionTerminalState {
  if (!isLocalSubmissionPending && !wasGrading(previousStatus)) {
    return null;
  }
  if (currentStatus === "graded" || currentStatus === "grading_failed") {
    return currentStatus;
  }
  return null;
}
