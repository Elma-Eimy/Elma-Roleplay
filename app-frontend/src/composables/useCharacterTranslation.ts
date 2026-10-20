import { ref, computed, watch, onScopeDispose } from "vue";
import type { CharacterBase } from "@/api/characters";
import type { CharacterTranslation } from "@/types/characterTranslation";
import { getCharacterTranslation, translateCharacter } from "@/api/characterTranslations";
import { getBaseUrl } from "@/api/config";
import { readingFields, translatedReadingCard } from "@/utils/characterTranslation";
import { cardImportError } from "@/utils/characterCard";

export function useCharacterTranslation(source: () => (CharacterBase & { id?: number }) | null) {
  const translation = ref<CharacterTranslation | null>(null);
  const language = ref<"original" | "zh">("original");
  const translating = ref(false);
  const error = ref("");
  let generation = 0;
  let languageChoice = 0;
  function selectLanguage(value: "original" | "zh") {
    languageChoice++;
    language.value = value;
  }
  watch(() => {
    const card = source();
    return card ? JSON.stringify([getBaseUrl(), card.id, readingFields(card)]) : "";
  }, async () => {
    const version = ++generation;
    const endpoint = getBaseUrl();
    languageChoice = 0;
    const choice = languageChoice;
    translation.value = null;
    language.value = "original";
    translating.value = false;
    error.value = "";
    const card = source();
    if (!card) return;
    try {
      const result = await getCharacterTranslation(card);
      if (version !== generation || endpoint !== getBaseUrl()) return;
      translation.value = result.translation;
      if (result.translation && choice === languageChoice) language.value = "zh";
    } catch {
      // 缓存暂不可读不阻塞导入，手动翻译时再反馈网络状态。
    }
  }, { immediate: true, flush: "sync" });
  onScopeDispose(() => { generation++; });

  async function translate(force = false) {
    const card = source();
    if (!card || translating.value) return;
    const version = ++generation;
    const endpoint = getBaseUrl();
    const choice = languageChoice;
    const current = () => version === generation && endpoint === getBaseUrl();
    translating.value = true;
    error.value = "";
    try {
      const result = await translateCharacter(card, force);
      if (!current()) return;
      if (!result.translation) throw new Error("翻译未返回结果，请重试。");
      translation.value = result.translation;
      if (choice === languageChoice) language.value = "zh";
    } catch (failure) {
      if (current()) error.value = cardImportError(failure);
    } finally {
      // 切服务器但尚未加载到新角色时，旧请求仍拥有自己的忙碌标记。
      if (version === generation) translating.value = false;
    }
  }
  const readingCard = computed(() => {
    const card = source();
    return card && language.value === "zh" && translation.value
      ? translatedReadingCard(card, translation.value) : card;
  });
  return { translation, language, selectLanguage, translating, error, readingCard, translate };
}
