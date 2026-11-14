export type ThinkingMode = "inherit" | "enabled" | "disabled";
export type ModelAdapter = "compatible" | "deepseek" | "reasoning";
export interface ModelProfile {
  id: string;
  label: string;
  adapter: ModelAdapter;
  thinking?: "toggle" | "always" | "unsupported" | null;
  efforts?: string[] | null;
}
export interface ModelCapability extends ModelProfile {
  thinking: "toggle" | "always" | "unsupported";
  efforts: string[];
}
export interface GenerationOverride {
  model: string;
  thinking_mode: ThinkingMode;
  reasoning_effort: string;
}
export const EMPTY_GENERATION: GenerationOverride = {
  model: "",
  thinking_mode: "inherit",
  reasoning_effort: "inherit",
};
