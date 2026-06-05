import { LONG_RUNNING_API_TIMEOUT_MS, orvalApiClient } from "../../api/client";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";

export interface QuestionTemplateGradeResult {
  question_template_id: number;
  question_type: string;
  is_correct: boolean;
  score_obtained: number;
  score_max: number;
  feedback_text: string;
  error_cause_label?: string | null;
  grading_mode: "objective_rule" | "subjective_llm" | "subjective_fallback";
  correct_answer: string;
}

export function isAiGradedQuestionType(questionType?: string | null): boolean {
  return ["fill_blank", "short_answer"].includes(String(questionType ?? "").trim().toLowerCase());
}

export async function gradeQuestionTemplateAnswer(
  courseId: string,
  questionTemplateId: number,
  answer: string,
): Promise<QuestionTemplateGradeResult> {
  const response = await orvalApiClient<{ data?: { code?: number; message?: string; data?: QuestionTemplateGradeResult } }>(
    `/api/v1/courses/${courseId}/exams/question-templates/${questionTemplateId}/grade`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer }),
      timeout: LONG_RUNNING_API_TIMEOUT_MS,
    },
  );
  const graded = unwrapOrvalResponse<QuestionTemplateGradeResult>(response);
  if (!graded) {
    throw new Error("AI 判题没有返回结果");
  }
  return graded;
}
