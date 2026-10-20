import type { CharacterBase } from "@/api/characters";
import type { CharacterReadingFields, CharacterTranslation } from "@/types/characterTranslation";
import { getCardGreetings } from "./characterCard";

export function readingFields(card: CharacterBase): CharacterReadingFields {
  return {
    description: card.description || "", personality: card.personality || "",
    scenario: card.scenario || "", first_mes: card.first_mes || "",
    mes_example: card.mes_example || "", creator_notes: card.creator_notes || "",
    alternate_greetings: getCardGreetings(card),
  };
}

/** 仅用于渲染；调用方继续保存、导出和聊天时使用原始 card。 */
export function translatedReadingCard<T extends CharacterBase>(card: T, translation: CharacterTranslation): T {
  const { alternate_greetings, ...fields } = translation.fields;
  return { ...card, ...fields, extensions: { ...card.extensions, alternate_greetings: [...alternate_greetings] } };
}
