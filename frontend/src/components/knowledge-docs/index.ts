/* ------------------------------------------------------------------ */
/*  knowledge-docs barrel export                                       */
/* ------------------------------------------------------------------ */

/* Types */
export type * from "./types";

/* Utils */
export {
  ACTIVE_DOC_BUILD_STATUSES,
  COMPACT_PANEL_BREAKPOINT,
  formatDocTimestamp,
  parseIsoTimestamp,
  buildChapterStatusLabel,
  chapterStatusClasses,
  normalizeDomainLabel,
  formatBuildEventTime,
  resolveFileProcessingLabel,
  resolveFileProgressScore,
  buildCommentThreadLayout,
} from "./utils";

/* Hooks */
export { useDocMarkdown } from "./hooks/useDocMarkdown";
export { useDocBuildProgress } from "./hooks/useDocBuildProgress";
export { useDocToc } from "./hooks/useDocToc";

/* Build View Components */
export { BuildView } from "./BuildView";
export { BuildProcessTimeline, useBuildTimelineSteps } from "./BuildProcessTimeline";
export { BuildChapterProgress } from "./BuildChapterProgress";
export { BuildResearchSources } from "./BuildResearchSources";
export { BuildMaterialPipeline } from "./BuildMaterialPipeline";
export { BuildLiveDraft } from "./BuildLiveDraft";
export { BuildMetricsBadges } from "./BuildMetricsBadges";

/* Doc Reader Components */
export { DocHeader } from "./DocHeader";
export { DocEmptyState } from "./DocEmptyState";
export { DocErrorState } from "./DocErrorState";
export { DocUpdatingBanner } from "./DocUpdatingBanner";
export { DocTocSidebar } from "./DocTocSidebar";
