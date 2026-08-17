import defaultMdxComponents from "fumadocs-ui/mdx";
import type { MDXComponents } from "mdx/types";
import {
  DocsHomeHero,
  GuideCallout,
  GuideFooter,
  GuideStep,
  GuideSteps,
  LearningLoop,
  ProductEvidence,
  ProductShot,
  PromptExample,
  TaskCard,
  TaskGrid,
} from "@/components/docs/GuideComponents";

export function getMDXComponents(components?: MDXComponents): MDXComponents {
  return {
    ...defaultMdxComponents,
    DocsHomeHero,
    GuideCallout,
    GuideFooter,
    GuideStep,
    GuideSteps,
    LearningLoop,
    ProductEvidence,
    ProductShot,
    PromptExample,
    TaskCard,
    TaskGrid,
    ...components,
  };
}
