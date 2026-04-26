export interface ExamStudyGuideFocusUnit {
  knowledge_unit_id?: number | null;
  knowledge_unit_name: string;
  mastery_score?: number | null;
  reason: string;
}

export interface ExamStudyGuideResponse {
  exam_paper_id: number;
  subject: string;
  generated_at: string;
  overall_summary: string;
  strengths: string[];
  priority_gaps: string[];
  action_steps: string[];
  review_tasks: string[];
  focus_units: ExamStudyGuideFocusUnit[];
}
