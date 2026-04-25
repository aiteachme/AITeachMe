export type AiInteractionDisplayMode = "sidebar" | "fullscreen";

export type AiConversationScope =
  | { type: "global" }
  | { type: "subject"; subjectId: string };

export interface OpenAiInteractionOptions {
  mode?: AiInteractionDisplayMode;
  scope?: AiConversationScope | null;
  sessionId?: string | null;
  draft?: string;
}

export interface AiInteractionOpenRequest {
  key: number;
  sessionId?: string | null;
  draft?: string;
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
