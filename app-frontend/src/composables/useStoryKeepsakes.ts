import { computed, ref, watch, onScopeDispose } from "vue";
import type { Ref } from "vue";
import type { ChatMessage } from "@/store/chatStore";
import { getBaseUrl } from "@/api/config";
import { onServerChange } from "@/utils/connectionEvents";

export const STORY_PALETTES = [
  { id: "sage", name: "绿色", color: "#527c69", soft: "#e8f1ec", mist: "#b6d2c3" },
  { id: "rose", name: "粉色", color: "#a4556e", soft: "#f7e9ee", mist: "#e0b8c5" },
  { id: "blue", name: "蓝色", color: "#496f9d", soft: "#e8eff8", mist: "#b6cbe4" },
  { id: "amber", name: "棕色", color: "#90652e", soft: "#f6eedf", mist: "#dfc9a4" },
] as const;
export type StoryPaletteId = typeof STORY_PALETTES[number]["id"];
export interface StoryKeepsake {
  id: string;
  messageId: number;
  title: string;
  content: string;
  speaker: string;
  savedAt: string;
}

export function useStoryKeepsakes(sessionId: Ref<number | null>, characterId: () => number | undefined) {
  const cards = ref<StoryKeepsake[]>([]);
  const paletteId = ref<StoryPaletteId>("sage");
  const isOpen = ref(false);
  let endpoint = getBaseUrl();
  const cardKey = () => `story_keepsakes_v1:${endpoint}:${sessionId.value}`;
  const paletteKey = () => `character_palette_v1:${endpoint}:${characterId()}`;
  const read = (key: string): unknown => {
    try {
      const raw = uni.getStorageSync(key);
      return typeof raw === "string" && raw ? JSON.parse(raw) : raw;
    } catch { return null; }
  };
  const reload = () => {
    endpoint = getBaseUrl();
    const raw = sessionId.value === null ? null : read(cardKey());
    cards.value = Array.isArray(raw) ? raw.filter((card): card is StoryKeepsake =>
      card && typeof card.id === "string" && Number.isInteger(card.messageId) && card.messageId > 0 &&
      typeof card.title === "string" && typeof card.content === "string" &&
      typeof card.speaker === "string" && typeof card.savedAt === "string") : [];
    const savedPalette = characterId() ? read(paletteKey()) : null;
    paletteId.value = STORY_PALETTES.find(item => item.id === savedPalette)?.id || "sage";
  };
  const persistCards = (next: StoryKeepsake[]) => {
    if (sessionId.value === null || endpoint !== getBaseUrl()) return false;
    try {
      uni.setStorageSync(cardKey(), JSON.stringify(next));
      cards.value = next;
      return true;
    } catch {
      uni.showToast({ title: "保存失败，请检查本机存储空间", icon: "none" });
      return false;
    }
  };
  const save = (message: ChatMessage, speaker: string) => {
    if (message.id <= 0 || !message.content.trim() ||
        (message.status && message.status !== "done")) return;
    // 以消息 ID 和原文区分收藏，后续编辑不改动已经保存的片段。
    if (cards.value.some(card => card.messageId === message.id && card.content === message.content)) {
      isOpen.value = true;
      return;
    }
    const savedAt = new Date().toISOString();
    const card: StoryKeepsake = {
      id: `${message.id}:${savedAt}:${Math.random().toString(36).slice(2)}`,
      messageId: message.id,
      title: "值得记住的这一刻",
      content: message.content,
      speaker,
      savedAt,
    };
    if (persistCards([card, ...cards.value])) {
      uni.showToast({ title: "已收藏到故事回忆册", icon: "none" });
    }
  };
  const rename = (id: string, title: string) => persistCards(cards.value.map(card =>
    card.id === id ? { ...card, title: title.trim().slice(0, 40) || "值得记住的这一刻" } : card));
  const remove = (id: string) => persistCards(cards.value.filter(card => card.id !== id));
  const selectPalette = (id: StoryPaletteId) => {
    if (!characterId() || endpoint !== getBaseUrl() || !STORY_PALETTES.some(item => item.id === id)) return;
    try {
      uni.setStorageSync(paletteKey(), JSON.stringify(id));
      paletteId.value = id;
    } catch { uni.showToast({ title: "配色保存失败，请重试", icon: "none" }); }
  };
  const palette = computed(() => STORY_PALETTES.find(item => item.id === paletteId.value) || STORY_PALETTES[0]);
  const paletteStyle = computed(() => ({
    "--story-accent": palette.value.color,
    "--story-soft": palette.value.soft,
    "--story-mist": palette.value.mist,
  }));
  watch([sessionId, characterId], () => { isOpen.value = false; reload(); }, { immediate: true, flush: "sync" });
  const unsubscribe = onServerChange(() => {
    isOpen.value = false;
    cards.value = [];
    paletteId.value = "sage";
    endpoint = getBaseUrl();
  });
  onScopeDispose(unsubscribe);
  return { cards, paletteId, paletteStyle, isOpen, save, rename, remove, selectPalette };
}
