import { request, USE_MOCK } from "./config";
import type { CharacterBase } from "./characters";
import type { CharacterTranslationResponse } from "@/types/characterTranslation";
import { readingFields } from "@/utils/characterTranslation";

// 只发送阅读字段，隐藏 Prompt、世界书和第三方扩展不参与翻译请求。
function payload(card: CharacterBase) {
  const { alternate_greetings, ...fields } = readingFields(card);
  return { name: card.name, ...fields, extensions: { alternate_greetings } };
}

export async function getCharacterTranslation(card: CharacterBase): Promise<CharacterTranslationResponse> {
  if (USE_MOCK) return { translation: null };
  return request("/characters/translation-cache", {
    method: "POST", body: JSON.stringify({ card: payload(card) }),
  });
}

export async function translateCharacter(card: CharacterBase, force = false): Promise<CharacterTranslationResponse> {
  if (USE_MOCK) throw new Error("离线演示不提供在线翻译，请连接后端后重试。");
  return request("/characters/translate", {
    method: "POST", body: JSON.stringify({ card: payload(card), force }), timeout: 600000,
  });
}
