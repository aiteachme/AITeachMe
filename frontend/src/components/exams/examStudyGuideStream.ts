import type { ExamStudyGuideResponse } from "./types";

export interface ExamStudyGuideStreamPayload {
  exam_paper_id?: number;
  status?: string;
  stage?: string;
  step?: string;
  detail?: string;
  error_code?: string;
  sequence?: number;
  draft?: ExamStudyGuideResponse;
  guide?: ExamStudyGuideResponse;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStudyGuide(value: unknown): value is ExamStudyGuideResponse {
  return isRecord(value)
    && typeof value.exam_paper_id === "number"
    && typeof value.course_name === "string"
    && typeof value.generated_at === "string"
    && typeof value.overall_summary === "string"
    && Array.isArray(value.strengths)
    && Array.isArray(value.priority_gaps)
    && Array.isArray(value.action_steps)
    && Array.isArray(value.review_tasks)
    && Array.isArray(value.focus_units);
}

export function parseExamStudyGuideStreamPayload(rawData: string): ExamStudyGuideStreamPayload | null {
  let value: unknown;
  try {
    value = JSON.parse(rawData);
  } catch {
    return null;
  }
  if (!isRecord(value)) return null;

  const payload: ExamStudyGuideStreamPayload = {};
  if (typeof value.exam_paper_id === "number") payload.exam_paper_id = value.exam_paper_id;
  if (typeof value.status === "string") payload.status = value.status;
  if (typeof value.stage === "string") payload.stage = value.stage;
  if (typeof value.step === "string") payload.step = value.step;
  if (typeof value.detail === "string") payload.detail = value.detail;
  if (typeof value.error_code === "string") payload.error_code = value.error_code;
  if (typeof value.sequence === "number" && Number.isInteger(value.sequence) && value.sequence >= 0) {
    payload.sequence = value.sequence;
  }
  if (isStudyGuide(value.draft)) payload.draft = value.draft;
  if (isStudyGuide(value.guide)) payload.guide = value.guide;
  return payload;
}
