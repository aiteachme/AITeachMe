export type AiInteractionDisplayMode = "sidebar" | "fullscreen";

export type AiConversationScope =
  | { type: "global" }
  | { type: "subject"; subjectId: string };

export interface OpenAiInteractionOptions {
  mode?: AiInteractionDisplayMode;
  scope?: AiConversationScope | null;
  sessionId?: string | null;
  draft?: string;
  source?: string | null;
  anchorId?: string | null;
  selectedText?: string | null;
  selectionContext?: {
    selected_text: string;
    anchor_id: string;
    anchor_title?: string;
    heading_path: string[];
    before_text?: string;
    after_text?: string;
    section_title?: string;
    section_excerpt?: string;
    section_truncated: boolean;
    local_context_truncated: boolean;
  } | null;
  clientThreadId?: string | null;
  newSession?: boolean;
  showSelectionContext?: boolean;
}

export interface AiInteractionOpenRequest {
  key: number;
  sessionId?: string | null;
  draft?: string;
  source?: string | null;
  anchorId?: string | null;
  selectedText?: string | null;
  selectionContext?: OpenAiInteractionOptions["selectionContext"];
  clientThreadId?: string | null;
  newSession?: boolean;
  showSelectionContext?: boolean;
}

export function getAiConversationScopeKey(scope: AiConversationScope | null): string {
  if (!scope) {
    return "none";
  }
  return scope.type === "global" ? "global" : `subject:${scope.subjectId}`;
}

export function getAiConversationBackendSubjectId(scope: AiConversationScope | null): string | null {
  if (!scope) {
    return null;
  }

  // The current chat APIs are subject-scoped. Keep the existing global compatibility scope
  // isolated here so the window components do not care how the backend stores conversations.
  return scope.type === "global" ? "global" : scope.subjectId;
}
