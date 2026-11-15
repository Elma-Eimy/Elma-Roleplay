import type { CharacterDetail } from "../types/characters";
import type { LorebookDetail } from "../api/lorebooks";

export interface CharacterLorebookEntryView {
  keys: string[];
  secondary_keys: string[];
  content: string;
  constant: boolean;
  enabled: boolean;
  priority: number;
  position?: string;
  depth?: number;
  comment?: string;
  sourceName: string;
  sourceType: "embedded" | "bound";
  sourceLorebookId?: number;
}

export interface CharacterLorebookSummaryView {
  embeddedName: string;
  entries: CharacterLorebookEntryView[];
  activeCount: number;
  totalCount: number;
}

const POSITION_LABELS: Record<string, string> = {
  before_char: "角色设定前",
  after_char: "角色设定后",
  before_examples: "对话示例前",
  after_examples: "对话示例后",
  at_depth: "按深度插入",
  an_top: "作者注释顶部",
  an_bottom: "作者注释底部",
  outlet: "Outlet",
  "0": "角色设定前",
  "1": "角色设定后",
  "2": "作者注释顶部",
  "3": "作者注释底部",
  "4": "按深度插入",
  "5": "对话示例前",
  "6": "对话示例后",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

/**
 * 兼容数组与字典形态的 character_book.entries，并按数字键升序排列。
 */
export function coerceRawLorebookEntries(entries: unknown): Record<string, unknown>[] {
  if (Array.isArray(entries)) {
    return entries.filter((entry): entry is Record<string, unknown> => isRecord(entry));
  }
  if (isRecord(entries)) {
    return Object.keys(entries)
      .sort((a, b) => {
        const na = Number(a);
        const nb = Number(b);
        const aIsNum = a.trim() !== "" && !Number.isNaN(na);
        const bIsNum = b.trim() !== "" && !Number.isNaN(nb);
        if (aIsNum && bIsNum) return na - nb;
        if (aIsNum) return -1;
        if (bIsNum) return 1;
        return a.localeCompare(b);
      })
      .map((key) => entries[key])
      .filter((entry): entry is Record<string, unknown> => isRecord(entry));
  }
  return [];
}

function normalizeKeysList(raw: unknown): string[] {
  if (Array.isArray(raw)) {
    return raw
      .map((item) => (typeof item === "string" ? item.trim() : String(item ?? "").trim()))
      .filter(Boolean);
  }
  if (typeof raw === "string") {
    return raw
      .split(/[,，]/)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [];
}

function pickFirstString(...candidates: unknown[]): string {
  for (const candidate of candidates) {
    if (typeof candidate === "string") return candidate;
  }
  return "";
}

function pickFiniteNumber(...candidates: unknown[]): number | undefined {
  for (const candidate of candidates) {
    if (typeof candidate === "number" && Number.isFinite(candidate)) {
      return candidate;
    }
  }
  return undefined;
}

function resolveEnabledFlag(rawEntry: Record<string, unknown>): boolean {
  if (typeof rawEntry.enabled === "boolean") return rawEntry.enabled;
  if (typeof rawEntry.disable === "boolean") return !rawEntry.disable;
  if (typeof rawEntry.disabled === "boolean") return !rawEntry.disabled;
  return true;
}

function resolvePositionLabel(rawEntry: Record<string, unknown>): string | undefined {
  const extensions = isRecord(rawEntry.extensions) ? rawEntry.extensions : undefined;
  const rawPosition = rawEntry.position ?? extensions?.position;
  if (rawPosition === undefined || rawPosition === null || rawPosition === "") return undefined;
  const key = String(rawPosition);
  return POSITION_LABELS[key] ?? key;
}

/**
 * 统一归一化角色内嵌世界书与独立世界书词条，兼容 SillyTavern 常见别名字段。
 */
export function normalizeLorebookEntry(
  rawEntry: Record<string, unknown>,
  meta: {
    sourceName: string;
    sourceType: "embedded" | "bound";
    sourceLorebookId?: number;
  },
): CharacterLorebookEntryView {
  const extensions = isRecord(rawEntry.extensions) ? rawEntry.extensions : undefined;
  const keys = normalizeKeysList(rawEntry.keys ?? rawEntry.key);
  const secondaryKeys = normalizeKeysList(
    rawEntry.secondary_keys ?? rawEntry.keysecondary ?? rawEntry.secondaryKeys,
  );
  const content = pickFirstString(rawEntry.content, rawEntry.entry, rawEntry.value);
  const commentRaw = pickFirstString(rawEntry.comment, rawEntry.name).trim();
  const priority = pickFiniteNumber(rawEntry.priority, rawEntry.insertion_order, rawEntry.order) ?? 100;
  const depth = pickFiniteNumber(rawEntry.depth, extensions?.depth);

  return {
    keys,
    secondary_keys: secondaryKeys,
    content,
    constant: Boolean(rawEntry.constant ?? rawEntry.constant_activation),
    enabled: resolveEnabledFlag(rawEntry),
    priority,
    position: resolvePositionLabel(rawEntry),
    depth,
    comment: commentRaw || undefined,
    sourceName: meta.sourceName,
    sourceType: meta.sourceType,
    sourceLorebookId: meta.sourceLorebookId,
  };
}

/**
 * 汇总角色卡内嵌世界书与当前绑定的独立世界书条目，同时保留停用条目用于展示与检索。
 */
export function buildCharacterLorebookEntries(
  character: Pick<CharacterDetail, "extensions"> | null | undefined,
  boundDetails: LorebookDetail[],
): CharacterLorebookSummaryView {
  const entries: CharacterLorebookEntryView[] = [];
  const rawBook = character?.extensions?.character_book;
  let embeddedName = "";

  if (isRecord(rawBook)) {
    if (typeof rawBook.name === "string") {
      embeddedName = rawBook.name.trim();
    }
    const embeddedSourceName = embeddedName ? `专属 · ${embeddedName}` : "专属";
    for (const rawEntry of coerceRawLorebookEntries(rawBook.entries)) {
      entries.push(
        normalizeLorebookEntry(rawEntry, {
          sourceName: embeddedSourceName,
          sourceType: "embedded",
        }),
      );
    }
  }

  for (const lorebook of boundDetails) {
    if (!lorebook) continue;
    for (const rawEntry of coerceRawLorebookEntries(lorebook.entries)) {
      entries.push(
        normalizeLorebookEntry(rawEntry, {
          sourceName: lorebook.name,
          sourceType: "bound",
          sourceLorebookId: lorebook.id,
        }),
      );
    }
  }

  const activeCount = entries.filter((entry) => entry.enabled).length;
  return {
    embeddedName,
    entries,
    activeCount,
    totalCount: entries.length,
  };
}

/**
 * 按关键字、副关键字、备注、正文或来源书名检索世界书条目。
 */
export function filterLorebookEntries(
  entries: CharacterLorebookEntryView[],
  query: string,
): CharacterLorebookEntryView[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return entries;

  return entries.filter((entry) => {
    if (entry.sourceName.toLowerCase().includes(normalized)) return true;
    if (entry.comment && entry.comment.toLowerCase().includes(normalized)) return true;
    if (entry.content.toLowerCase().includes(normalized)) return true;
    if (entry.keys.some((k) => k.toLowerCase().includes(normalized))) return true;
    if (entry.secondary_keys.some((k) => k.toLowerCase().includes(normalized))) return true;
    return false;
  });
}

/**
 * 结合角色已存 lorebooks 或 extensions.lorebook_ids，按世界书库列表解析有效的关联摘要。
 */
export function resolveCharacterLorebookRefs(
  character: Pick<CharacterDetail, "lorebooks" | "extensions">,
  library: Array<{ id: number; name: string }>,
): { id: number; name: string }[] {
  const byId = new Map<number, string>();
  for (const lb of library) {
    byId.set(lb.id, lb.name);
  }

  const rawIds = character.extensions?.lorebook_ids;
  if (Array.isArray(rawIds)) {
    const seen = new Set<number>();
    const refs: { id: number; name: string }[] = [];
    for (const rawId of rawIds) {
      if (typeof rawId !== "number" || !Number.isFinite(rawId) || seen.has(rawId)) continue;
      seen.add(rawId);
      const name = byId.get(rawId);
      if (name !== undefined) {
        refs.push({ id: rawId, name });
      }
    }
    return refs;
  }

  if (Array.isArray(character.lorebooks)) {
    return character.lorebooks
      .filter((item) => item && typeof item.id === "number")
      .map((item) => ({
        id: item.id,
        name: byId.get(item.id) ?? item.name,
      }));
  }

  return [];
}

