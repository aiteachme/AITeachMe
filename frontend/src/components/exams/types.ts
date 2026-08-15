export interface ExamStudyGuideFocusUnit {
  knowledge_unit_id?: number | null;
  knowledge_unit_name: string;
  paper_attempts?: number;
  paper_correct_attempts?: number;
  paper_score_obtained?: number;
  paper_score_max?: number;
  paper_score_rate?: number | null;
  mastery_score?: number | null;
  reason: string;
}

export interface ExamStudyGuideResponse {
  schema_version?: 2;
  exam_paper_id: number;
  course_name: string;
  generated_at: string;
  overall_summary: string;
  strengths: string[];
  priority_gaps: string[];
  action_steps: string[];
  review_tasks: string[];
  focus_units: ExamStudyGuideFocusUnit[];
}
