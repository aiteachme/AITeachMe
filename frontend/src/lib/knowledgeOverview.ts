import { knowledgeOverviewApiV1SubjectsSubjectKnowledgeOverviewPost } from "../api/generated/knowledge";
import type { KnowledgeOverviewRequest, KnowledgeOverviewResponse } from "../api/generated/model";
import { unwrapOrvalResponse } from "./unwrapOrvalResponse";

export type KnowledgeOverviewSection = NonNullable<KnowledgeOverviewRequest["include"]>[number];

export const OVERVIEW_INCLUDE_PRESETS = {
  wordCloud: ["graph"],
  themeTree: ["theme_tree"],
  prereqDag: ["prereq_dag", "units"],
  knowledgeGraph: ["graph"],
  profileMappings: ["graph", "units"],
} as const satisfies Record<string, readonly KnowledgeOverviewSection[]>;

export function buildKnowledgeOverviewQueryKey(
  subjectId: string,
  include: readonly KnowledgeOverviewSection[],
) {
  return ["knowledge-overview", subjectId, [...include].sort().join(",")] as const;
}

export async function fetchKnowledgeOverview(
  subjectId: string,
  include: readonly KnowledgeOverviewSection[],
): Promise<KnowledgeOverviewResponse> {
  const raw = await knowledgeOverviewApiV1SubjectsSubjectKnowledgeOverviewPost(subjectId, {
    full: false,
    include: [...include],
  });
  return (
    unwrapOrvalResponse<KnowledgeOverviewResponse>(raw) ?? {
      subject: subjectId,
      generated_at: new Date().toISOString(),
      snapshot: null,
      theme_tree: null,
      prereq_dag: null,
      graph: null,
      units: [],
      stats: undefined,
    }
  );
}
