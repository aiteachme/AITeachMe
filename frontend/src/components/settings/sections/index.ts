import type { ComponentType } from "react";

import type { SectionId } from "../types";

import { ConnectionSection } from "./ConnectionSection";
import { LearningSection } from "./LearningSection";
import { ModelsSection } from "./ModelsSection";
import { ObservabilitySection } from "./ObservabilitySection";
import { OpsSection } from "./OpsSection";
import { SearchSection } from "./SearchSection";

export const SECTION_RENDERERS: Record<SectionId, ComponentType> = {
  connection: ConnectionSection,
  models: ModelsSection,
  learning: LearningSection,
  search: SearchSection,
  ops: OpsSection,
  observability: ObservabilitySection,
};
