export type StudyGuideSectionVisibility = {
  strengths: boolean;
  focusUnits: boolean;
  priorityGaps: boolean;
  actionSteps: boolean;
};

export type StudyGuideGenerationProgress = {
  label: string;
};

export function getStudyGuideProgressValue({
  isStreaming,
  hasPendingSection,
}: {
  isStreaming: boolean;
  hasPendingSection: boolean;
}): number | undefined {
  return isStreaming || hasPendingSection ? undefined : 100;
}

export type StudyGuideSectionKey = keyof StudyGuideSectionVisibility;

const STUDY_GUIDE_SECTION_ORDER: StudyGuideSectionKey[] = [
  "strengths",
  "focusUnits",
  "priorityGaps",
  "actionSteps",
];

type StudyGuideSectionAvailability = StudyGuideSectionVisibility;

export function getStudyGuideSectionVisibility(
  availability: StudyGuideSectionAvailability,
): StudyGuideSectionVisibility {
  // Sections already have a fixed DOM order in ExamStudyGuideView.  Do not use
  // an optional empty section (for example, no strengths on an all-wrong paper)
  // as a gate for later streamed sections, otherwise they all appear at once
  // only after the SSE completes.
  return availability;
}

export function getStudyGuideGenerationProgress({
  hasSummary,
  strengths,
  focusUnits,
  priorityGaps,
  actionSteps,
}: StudyGuideSectionAvailability & { hasSummary: boolean }): StudyGuideGenerationProgress {
  if (actionSteps) return { label: "正在完善学习步骤" };
  if (priorityGaps) return { label: "正在生成下一步学习建议" };
  if (focusUnits) return { label: "正在提炼优先补漏" };
  if (strengths) return { label: "正在分析重点知识点" };
  if (hasSummary) return { label: "正在总结本次作答" };
  return { label: "正在整理本次作答" };
}

export function getNextStudyGuideSection(
  availability: StudyGuideSectionAvailability,
  visibility: StudyGuideSectionVisibility,
): StudyGuideSectionKey | null {
  return STUDY_GUIDE_SECTION_ORDER.find(
    (section) => availability[section] && !visibility[section],
  ) ?? null;
}

export function mergeStudyGuideActionItems(
  actionSteps?: string[] | null,
  legacyReviewTasks?: string[] | null,
): string[] {
  const merged: string[] = [];
  const seen = new Set<string>();

  for (const rawItem of [...(actionSteps ?? []), ...(legacyReviewTasks ?? [])]) {
    if (typeof rawItem !== "string") continue;
    const item = rawItem.trim();
    if (!item) continue;
    const key = item.replace(/\s+/g, " ").toLocaleLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(item);
    if (merged.length >= 3) break;
  }

  return merged;
}
