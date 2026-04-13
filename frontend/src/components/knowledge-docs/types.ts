/* ------------------------------------------------------------------ */
/*  Knowledge Docs — Unified Type Definitions                          */
/*  Single source of truth for all types used across the knowledge     */
/*  docs page components, hooks, and sub-systems.                      */
/* ------------------------------------------------------------------ */

import type {
  BuildPreviewChapterProgressResponse,
  BuildPreviewNodeResponse,
  BuildPreviewRecentEventResponse,
  BuildSampleCardResponse,
  DocGenGetResponse as ApiDocGenGetResponse,
  FileRecord,
  KnowledgeBuildMetricsResponse,
  KnowledgeBuildPreviewResponse,
  KnowledgeBuildStatusResponse,
} from "../../api/generated/model";

/* ---- TOC ---- */

export interface TocItem {
  id: string;
  text: string;
  level: number;
}

export interface TocTreeNode {
  item: TocItem;
  children: TocTreeNode[];
}

/* ---- Comments ---- */

export interface Comment {
  id: string;
  threadId: string;
  sessionId: string | null;
  anchorId: string;
  selectedText: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;
  streaming?: boolean;
}

export interface FloatingComment {
  anchorId: string;
  selectedText: string;
  selectionViewportTop: number;
  top: number;
}

export interface FloatingToolbar {
  anchorId: string;
  selectedText: string;
  top: number;
  left: number;
  selectionViewportTop: number;
}

export interface HighlightSegment {
  top: number;
  left: number;
  width: number;
  height: number;
}

export interface SelectionHighlight {
  id: string;
  threadId: string;
  anchorId: string;
  selectedText: string;
  segments: HighlightSegment[];
}

export interface CommentThreadView {
  threadId: string;
  anchorId: string;
  selectedText: string;
  comments: Comment[];
  createdAt: number;
}

export interface CommentThreadLayout {
  top: number;
  aligned: boolean;
}

export interface CommentThreadLayoutResult {
  positions: Record<string, CommentThreadLayout>;
  totalHeight: number;
}

/* ---- API Response Shapes ---- */

export interface ApiResponse<T> {
  code: number;
  data: T;
}

export interface PaginatedData<T> {
  items: T[];
  page?: number;
  size?: number;
  total?: number;
  pages?: number;
}

export interface ThreadMessageItem {
  id: number;
  turn_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface ThreadTurnItem {
  turn_id: string;
  session_id: string;
  source?: string | null;
  anchor_id?: string | null;
  selected_text?: string | null;
  created_at: string;
  messages: ThreadMessageItem[];
}

/* ---- Build Status & Preview ---- */

export type DocGenBuildStatus = KnowledgeBuildStatusResponse;
export type BuildSampleCard = BuildSampleCardResponse;
export type BuildPreviewNode = BuildPreviewNodeResponse;
export type BuildPreviewChapterProgress = BuildPreviewChapterProgressResponse;
export type BuildPreviewRecentEvent = BuildPreviewRecentEventResponse;
export type KnowledgeBuildPreview = KnowledgeBuildPreviewResponse;
export type KnowledgeBuildMetrics = KnowledgeBuildMetricsResponse;
export type DocGenGetResponse = ApiDocGenGetResponse;

export interface FilesListResponse {
  items: FileRecord[];
}

/* ---- View Mode ---- */

export type DocViewMode = "live" | "draft";

/* ---- Build Process Step ---- */

export type ProcessStepState = "done" | "active" | "pending";

export interface BuildProcessStep {
  key: string;
  title: string;
  description: string;
  state: ProcessStepState;
}
