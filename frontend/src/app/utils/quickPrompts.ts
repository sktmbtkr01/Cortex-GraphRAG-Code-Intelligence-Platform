export type PromptTemplate = {
  id: string;
  label: string;
  buildPrompt: (repo: string) => string;
};

export const QUICK_PROMPTS: PromptTemplate[] = [
  {
    id: "arch",
    label: "Architecture Overview",
    buildPrompt: (repo) => `Give me a high-level architecture overview of ${repo}. Include modules, data flow, and key integration points.`,
  },
  {
    id: "entry",
    label: "Where to Start",
    buildPrompt: (repo) => `I am new to ${repo}. What files should I read first to understand the system quickly?`,
  },
  {
    id: "hotspots",
    label: "Risk Hotspots",
    buildPrompt: (repo) => `Find the top security and reliability risk hotspots in ${repo} and explain why they are risky.`,
  },
  {
    id: "improvements",
    label: "Refactor Ideas",
    buildPrompt: (repo) => `Suggest practical refactors for ${repo} that improve maintainability without major rewrites.`,
  },
];
