import type { CharacterBase } from "@/api/characters";

export type CardImportMode = "replace" | "fill";
export interface GreetingOption {
  index: number | null;
  title: string;
  content: string;
  preview: string;
}

export function plainCardText(value = ""): string {
  return value
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/<[^>]*>/g, "")
    .replace(/[#*_`~>|]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function getCardGreetings(
  card: Pick<CharacterBase, "first_mes" | "extensions">,
): string[] {
  const values = card.extensions?.alternate_greetings;
  // 空项保留索引，不能让显示索引与后端 greeting_index 错位。
  return Array.isArray(values)
    ? values.map((value) => (typeof value === "string" ? value : ""))
    : [];
}

export function greetingOptions(
  first = "",
  alternates: string[] = [],
): GreetingOption[] {
  return [first, ...alternates].map((content, i) => {
    const heading =
      content.match(/✦\s*([^\n✦]+)\s*✦/)?.[1] ||
      content.match(/^\s*#{1,3}\s+([^\n]+)/m)?.[1];
    return {
      index: i === 0 ? null : i - 1,
      title:
        i === 0
          ? "默认开场"
          : plainCardText(heading || "").slice(0, 64) || `开场 ${i + 1}`,
      content,
      preview: plainCardText(content).slice(0, 100) || "此开场暂无内容",
    };
  });
}

export function getCardMetadata(card: CharacterBase): {
  creator: string;
  version: string;
} {
  const raw = card.extensions?.ai_roleplay_card;
  const info =
    raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  return {
    creator: typeof info.creator === "string" ? info.creator : "",
    version:
      typeof info.character_version === "string" ? info.character_version : "",
  };
}

export function getEmbeddedEntries(
  card: CharacterBase,
): Record<string, unknown>[] {
  const book = card.extensions?.character_book as
    | { entries?: unknown }
    | undefined;
  return Array.isArray(book?.entries)
    ? book!.entries.filter((entry) => entry && typeof entry === "object")
    : [];
}

const textFields = [
  "name",
  "description",
  "personality",
  "scenario",
  "first_mes",
  "mes_example",
  "creator_notes",
  "system_prompt_override",
  "post_history_instructions",
] as const;

function fillMissing(current: unknown, incoming: unknown): unknown {
  if (
    current == null ||
    current === "" ||
    (Array.isArray(current) && !current.length)
  )
    return incoming;
  if (
    current &&
    incoming &&
    typeof current === "object" &&
    typeof incoming === "object" &&
    !Array.isArray(current) &&
    !Array.isArray(incoming)
  ) {
    const result = { ...current } as Record<string, unknown>;
    for (const [key, value] of Object.entries(incoming)) {
      Object.defineProperty(result, key, {
        value: fillMissing(
          Object.prototype.hasOwnProperty.call(result, key)
            ? result[key]
            : undefined,
          value,
        ),
        enumerable: true,
        configurable: true,
        writable: true,
      });
    }
    return result;
  }
  return current;
}

export function mergeCharacterCard(
  current: CharacterBase,
  incoming: CharacterBase,
  mode: CardImportMode,
): CharacterBase {
  const result: CharacterBase = { name: "", description: "" };
  for (const key of textFields) {
    const existing = current[key] || "";
    result[key] =
      mode === "fill" && existing.trim() ? existing : incoming[key] || "";
  }
  result.avatar_path =
    mode === "fill" && current.avatar_path
      ? current.avatar_path
      : incoming.avatar_path || current.avatar_path || "";
  result.tags = [
    ...(mode === "fill" && current.tags?.length
      ? current.tags
      : incoming.tags || []),
  ];
  result.extensions = JSON.parse(
    JSON.stringify(
      mode === "fill"
        ? fillMissing(current.extensions || {}, incoming.extensions || {})
        : incoming.extensions || {},
    ),
  );
  return result;
}

export function cardImportError(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error || "");
  const detail = raw.match(/"detail"\s*:\s*"((?:[^"\\]|\\.)*)"/);
  if (detail) {
    try {
      return JSON.parse(`"${detail[1]}"`);
    } catch {
      /* 使用通用说明 */
    }
  }
  if (/413|文件过大/.test(raw))
    return "文件超过服务器允许的大小，请尝试导入 JSON 角色卡。";
  if (/timeout|fail|network|fetch|网络|连接/i.test(raw))
    return "未能连接服务器，请检查连接设置后重试。";
  return raw || "未能读取角色卡，请选择带角色数据的原始 PNG 或 JSON 文件。";
}
