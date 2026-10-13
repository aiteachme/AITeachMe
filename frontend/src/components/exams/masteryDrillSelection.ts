import type { ConfigStorage } from "./examConfig.ts";

const LAST_MASTERY_DRILL_SELECTION_STORAGE_PREFIX =
  "aiteachme.exam.masteryDrillLastSelection.v1";

function getBrowserSessionStorage(): ConfigStorage | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function normalizeTemplateIds(values: readonly unknown[]): number[] {
  const normalized: number[] = [];
  const seen = new Set<number>();
  values.forEach((value) => {
    const templateId = Number(value);
    if (!Number.isInteger(templateId) || templateId <= 0 || seen.has(templateId)) {
      return;
    }
    seen.add(templateId);
    normalized.push(templateId);
  });
  return normalized;
}

function normalizeQuestionTypes(values: readonly unknown[]): string[] {
  return Array.from(
    new Set(
      values
        .map((value) => String(value ?? "").trim())
        .filter(Boolean),
    ),
  );
}

function hashValueForSession(value: string, seed: number): number {
  const text = `${seed}:${value}`;
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function getLastMasteryDrillSelectionStorageKey(courseId: string): string {
  return `${LAST_MASTERY_DRILL_SELECTION_STORAGE_PREFIX}.${courseId}`;
}

export function loadLastMasteryDrillTemplateIds(
  courseId: string,
  storage: ConfigStorage | null = getBrowserSessionStorage(),
): number[] {
  if (!storage) {
    return [];
  }
  try {
    const raw = storage.getItem(getLastMasteryDrillSelectionStorageKey(courseId));
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? normalizeTemplateIds(parsed) : [];
  } catch {
    return [];
  }
}

export function saveLastMasteryDrillTemplateIds(
  courseId: string,
  templateIds: readonly number[],
  storage: ConfigStorage | null = getBrowserSessionStorage(),
): void {
  if (!storage) {
    return;
  }
  try {
    storage.setItem(
      getLastMasteryDrillSelectionStorageKey(courseId),
      JSON.stringify(normalizeTemplateIds(templateIds)),
    );
  } catch {
    // Selection rotation is best-effort and must never block starting a drill.
  }
}

export function selectMasteryDrillQuestionTypes(
  availableQuestionTypes: readonly string[],
  configuredQuestionTypes: readonly string[],
  seed: number,
  requestedQuestionCount: number,
): string[] {
  const normalizedAvailableTypes = availableQuestionTypes
    .map((questionType) => String(questionType ?? "").trim())
    .filter(Boolean);
  const availableTypes = normalizeQuestionTypes(normalizedAvailableTypes);
  const availableCounts = new Map<string, number>();
  normalizedAvailableTypes.forEach((questionType) => {
    availableCounts.set(questionType, (availableCounts.get(questionType) ?? 0) + 1);
  });
  const availableTypeSet = new Set(availableTypes);
  const normalizedConfiguredTypes = normalizeQuestionTypes(configuredQuestionTypes);
  const configuredTypes = normalizedConfiguredTypes
    .filter((questionType) => availableTypeSet.has(questionType));
  if (normalizedConfiguredTypes.length > 0) {
    return configuredTypes;
  }
  if (availableTypes.length === 0) {
    return [];
  }

  const normalizedQuestionCount = Math.max(1, Math.floor(Number(requestedQuestionCount) || 1));
  const maximumTypeCount = Math.min(availableTypes.length, normalizedQuestionCount);
  const orderedTypes = [...availableTypes].sort((left, right) =>
    hashValueForSession(left, seed) - hashValueForSession(right, seed) || left.localeCompare(right),
  );
  if (maximumTypeCount === 1) {
    return orderedTypes.slice(0, 1);
  }

  const typeCountRange = maximumTypeCount - 1;
  const selectedTypeCount = 2 + (
    hashValueForSession([...availableTypes].sort().join("|"), seed) % typeCountRange
  );
  const selectedTypes = orderedTypes.slice(0, selectedTypeCount);
  let availableQuestionCount = selectedTypes.reduce(
    (total, questionType) => total + (availableCounts.get(questionType) ?? 0),
    0,
  );
  while (
    availableQuestionCount < normalizedQuestionCount &&
    selectedTypes.length < maximumTypeCount
  ) {
    const nextType = orderedTypes[selectedTypes.length];
    selectedTypes.push(nextType);
    availableQuestionCount += availableCounts.get(nextType) ?? 0;
  }
  return selectedTypes;
}

export function interleaveMasteryDrillCandidateIdsByType(
  candidates: readonly { id: number; questionType: string }[],
): number[] {
  const groups = new Map<string, number[]>();
  const seenIds = new Set<number>();
  candidates.forEach((candidate) => {
    const candidateId = Number(candidate.id);
    const questionType = String(candidate.questionType ?? "").trim();
    if (!Number.isInteger(candidateId) || candidateId <= 0 || !questionType || seenIds.has(candidateId)) {
      return;
    }
    seenIds.add(candidateId);
    const group = groups.get(questionType) ?? [];
    group.push(candidateId);
    groups.set(questionType, group);
  });

  const interleavedIds: number[] = [];
  const typeGroups = Array.from(groups.values());
  const maximumGroupSize = typeGroups.reduce((maximum, group) => Math.max(maximum, group.length), 0);
  for (let index = 0; index < maximumGroupSize; index += 1) {
    typeGroups.forEach((group) => {
      const candidateId = group[index];
      if (candidateId !== undefined) {
        interleavedIds.push(candidateId);
      }
    });
  }
  return interleavedIds;
}

export function selectNextMasteryDrillCandidateIds(
  orderedCandidateIds: readonly number[],
  previousTemplateIds: readonly number[],
  requestedCount: number,
): number[] {
  const candidates = normalizeTemplateIds(orderedCandidateIds);
  const normalizedCount = Math.min(
    candidates.length,
    Math.max(0, Math.floor(Number(requestedCount) || 0)),
  );
  if (normalizedCount === 0) {
    return [];
  }

  const previousIds = normalizeTemplateIds(previousTemplateIds);
  const previousIdSet = new Set(previousIds);
  const unseenCandidates = candidates.filter((templateId) => !previousIdSet.has(templateId));
  const repeatedCandidates = candidates.filter((templateId) => previousIdSet.has(templateId));
  const selected = [...unseenCandidates, ...repeatedCandidates].slice(0, normalizedCount);

  const repeatsPreviousOrder =
    previousIds.length >= selected.length &&
    selected.every((templateId, index) => templateId === previousIds[index]);
  if (repeatsPreviousOrder && selected.length > 1) {
    return [...selected.slice(1), selected[0]];
  }
  return selected;
}
