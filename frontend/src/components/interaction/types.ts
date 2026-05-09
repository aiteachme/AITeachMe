import type { ChatSelectionContext } from "../../api/generated/model";

export type AiInteractionDisplayMode = "sidebar" | "fullscreen";
export type AiConversationScene =
  | "global_assistant"
  | "course_chat"
  | "document_selection"
  | "exam_question"
  | "build_assistant"
  | "home_intake"
  | "web_research";

export type AiConversationScope =
  | { type: "global" }
  | { type: "course"; courseId: string };

export const AI_SOURCE_DOCUMENT_SELECTION = "quick_chat";
export const AI_SOURCE_EXAM_QUESTION = "exam_question";
export const AI_SCENE_GLOBAL_ASSISTANT: AiConversationScene = "global_assistant";
export const AI_SCENE_COURSE_CHAT: AiConversationScene = "course_chat";
export const AI_SCENE_DOCUMENT_SELECTION: AiConversationScene = "document_selection";
export const AI_SCENE_EXAM_QUESTION: AiConversationScene = "exam_question";
export const AI_SCENE_BUILD_ASSISTANT: AiConversationScene = "build_assistant";
export const AI_SCENE_HOME_INTAKE: AiConversationScene = "home_intake";
export const AI_SCENE_WEB_RESEARCH: AiConversationScene = "web_research";
export const EXAM_QUESTION_JUMP_EVENT = "aiteachme:exam-question-jump";

export interface ExamQuestionJumpDetail {
  courseId: string;
  paperId: number;
  questionOrder: number;
  anchorId: string;
  selectedText?: string;
  sessionId?: string | null;
}

const EXAM_QUESTION_ANCHOR_PATTERN = /^exam-paper-(\d+)-question-(\d+)$/;

export function buildExamQuestionAnchorId(paperId: number, questionOrder: number): string {
  return `exam-paper-${paperId}-question-${questionOrder}`;
}

export function parseExamQuestionAnchorId(anchorId?: string | null): { paperId: number; questionOrder: number } | null {
  const match = anchorId?.trim().match(EXAM_QUESTION_ANCHOR_PATTERN);
  if (!match) {
    return null;
  }
  const paperId = Number(match[1]);
  const questionOrder = Number(match[2]);
  if (!Number.isFinite(paperId) || !Number.isFinite(questionOrder)) {
    return null;
  }
  return { paperId, questionOrder };
}

export interface OpenAiInteractionOptions {
  mode?: AiInteractionDisplayMode;
  scope?: AiConversationScope | null;
  sessionId?: string | null;
  draft?: string;
  autoSend?: boolean;
  model?: string | null;
  scene?: AiConversationScene | null;
  source?: string | null;
  anchorId?: string | null;
  selectedText?: string | null;
  selectionContext?: ChatSelectionContext | null;
  attachedFileIds?: string[];
  clientThreadId?: string | null;
  newSession?: boolean;
  showSelectionContext?: boolean;
}

export interface AiInteractionOpenRequest {
  key: number;
  sessionId?: string | null;
  draft?: string;
  autoSend?: boolean;
  model?: string | null;
  scene?: AiConversationScene | null;
  source?: string | null;
  anchorId?: string | null;
  selectedText?: string | null;
  selectionContext?: OpenAiInteractionOptions["selectionContext"];
  attachedFileIds?: string[];
  clientThreadId?: string | null;
  newSession?: boolean;
  showSelectionContext?: boolean;
}

export function getAiConversationScopeKey(scope: AiConversationScope | null): string {
  if (!scope) {
    return "none";
  }
  return scope.type === "global" ? "global" : `course:${scope.courseId}`;
}

export function getAiConversationBackendCourseId(scope: AiConversationScope | null): string | null {
  if (!scope) {
    return null;
  }

  // The current chat APIs are course-scoped. Keep the existing global compatibility scope
  // isolated here so the window components do not care how the backend stores conversations.
  return scope.type === "global" ? "global" : scope.courseId;
}
