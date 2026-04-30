import type { ChatSelectionContext } from "../../api/generated/model";

export interface PendingSelectionContext {
  source: string;
  anchorId: string | null;
  selectedText: string;
  selectionContext: ChatSelectionContext | null;
  clientThreadId: string | null;
}

export interface ChatSessionSelectionTarget {
  kind: "document" | "exam_question";
  sessionId: string | null;
  anchorId: string;
  selectedText: string;
  paperId?: number;
  questionOrder?: number;
}
