import type {
  ModelCapability,
  ModelProfile,
  GenerationOverride,
} from "@/types/generation";
import type { AppSettings } from "@/api/settings";

export function configuredCatalog(
  settings: Pick<AppSettings, "model_catalog" | "model_profiles">,
): ModelCapability[] {
  const values = new Map(
    (settings.model_catalog || []).map((model) => [model.id, model]),
  );
  for (const model of settings.model_profiles || []) {
    values.set(model.id, {
      ...model,
      label: model.label || model.id,
      thinking:
        model.adapter === "deepseek"
          ? "toggle"
          : model.adapter === "reasoning"
            ? "always"
            : "unsupported",
      efforts:
        model.adapter === "deepseek"
          ? ["low", "high", "max"]
          : model.adapter === "reasoning"
            ? ["low", "medium", "high"]
            : [],
    });
  }
  return [...values.values()];
}

export function effectiveGeneration(
  settings: AppSettings,
  override: GenerationOverride,
) {
  const id = override.model || settings.default_chat_model;
  const capability = configuredCatalog(settings).find((item) => item.id === id);
  const thinking =
    capability?.thinking === "always" ||
    (capability?.thinking === "toggle" &&
      (override.thinking_mode === "inherit"
        ? settings.reasoning_mode
        : override.thinking_mode === "enabled"));
  return {
    id,
    label: capability?.label || id || "全局默认模型",
    capability,
    thinking: Boolean(thinking),
    effort:
      override.reasoning_effort === "inherit"
        ? settings.reasoning_effort
        : override.reasoning_effort,
  };
}

export function normalizeOverride(value: unknown): GenerationOverride {
  const raw =
    value && typeof value === "object"
      ? (value as Record<string, unknown>)
      : {};
  return {
    model: typeof raw.model === "string" ? raw.model : "",
    thinking_mode:
      raw.thinking_mode === "enabled" || raw.thinking_mode === "disabled"
        ? raw.thinking_mode
        : "inherit",
    reasoning_effort:
      typeof raw.reasoning_effort === "string"
        ? raw.reasoning_effort
        : "inherit",
  };
}
