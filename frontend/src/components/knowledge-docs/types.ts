/* ------------------------------------------------------------------ */
/*  Knowledge Docs — Unified Type Definitions                          */
/*  Single source of truth for all types used across the knowledge     */
/*  docs page components, hooks, and sub-systems.                      */
/* ------------------------------------------------------------------ */

import type { FileRecord, SubjectVectorStatusResponse } from "../../api/generated/model";

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

export interface DocGenBuildStatus {
  status?: string | null;
  requested_at?: string | null;
  stage?: string | null;
  error_message?: string | null;
  draft_available?: boolean;
  digest_mode?: string | null;
}

export interface BuildSampleCard {
  title: string;
  card_type: string;
  summary: string;
}

export interface BuildPreviewNode {
  name: string;
  node_type: string;
}

export interface BuildPreviewChapterProgress {
  chapter_index: number;
  title: string;
  status: string;
  source_count?: number;
  local_hits?: number;
  web_hits?: number;
  query_count?: number;
  word_count?: number;
  fallback_used?: boolean;
}

export interface BuildPreviewRecentEvent {
  stage: string;
  chapter_index?: number | null;
  title?: string | null;
  summary: string;
  created_at?: string | null;
  domains?: string[];
  source_titles?: string[];
  source_urls?: string[];
}

export interface KnowledgeBuildPreview {
  current_stage_description?: string | null;
  digest_mode?: string | null;
  mode_reason?: string | null;
  plan_summary?: string | null;
  processed_chunks?: number;
  total_chunks?: number;
  discovered_node_count?: number;
  discovered_node_types?: Record<string, number>;
  sample_nodes?: BuildPreviewNode[];
  sample_cards?: BuildSampleCard[];
  chapter_progress?: BuildPreviewChapterProgress[];
  recent_events?: BuildPreviewRecentEvent[];
  latest_chapter_titles?: string[];
  draft_excerpt?: string;
}

export interface KnowledgeBuildMetrics {
  llm_total_calls?: number;
  failed_llm_call_count?: number;
  llm_avg_latency_ms?: number;
  call_count_by_lane?: Record<string, number>;
}

export interface DocGenGetResponse {
  exists: boolean;
  markdown?: string;
  updated_at?: string | null;
  source_file_uids?: string[];
  prompt?: string | null;
  draft_markdown?: string;
  draft_updated_at?: string | null;
  build?: DocGenBuildStatus | null;
  build_preview?: KnowledgeBuildPreview | null;
  build_metrics?: KnowledgeBuildMetrics | null;
  vector_status?: SubjectVectorStatusResponse | null;
}

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
