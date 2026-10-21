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

/** 把旧的继承值一次性解析为会话自己的明确配置。 */
export function snapshotGeneration(settings: AppSettings, value: unknown): GenerationOverride {
  const override = normalizeOverride(value);
  const effective = effectiveGeneration(settings, override);
  const capability = effective.capability;
  let effort = effective.effort || "high";
  if (capability?.adapter === "deepseek") {
    effort = ({ minimal: "low", medium: "high", xhigh: "high", ultra: "max" } as Record<string, string>)[effort] || effort;
  }
  if (capability?.efforts.length && !capability.efforts.includes(effort))
    effort = capability.efforts.includes("high") ? "high" : capability.efforts[0];
  return { model: effective.id, thinking_mode: effective.thinking ? "enabled" : "disabled", reasoning_effort: effort };
}

export function effortLabel(value: string): string {
  return ({ low: "低", medium: "中", high: "高", max: "最高" } as Record<string, string>)[value] || value;
}

export function modelOptionLabel(model: ModelCapability, catalog: ModelCapability[]): string {
  return catalog.some(item => item.id !== model.id && item.label === model.label)
    ? `${model.label} (${model.id})` : model.label;
}
