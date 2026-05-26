import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { getCharacters, getCharacter, deleteCharacter } from "@/api/characters";
import type { CharacterDetail, CharacterSummary } from "@/api/characters";
import { getSession } from "@/api/sessions";
import type { PersonaDetail, SessionDetail } from "@/api/sessions";

export const usePersonaStore = defineStore("persona", () => {
  // ===== 状态变量 =====

  /** 当前选中的角色完整设定详情 */
  const activeCharacter = ref<CharacterDetail | null>(null);

  /** 所有可用的角色简要列表 */
  const characterList = ref<CharacterSummary[]>([]);

  /** 当前会话的角色人格状态数据（情绪、好感度、微观认知） */
  const currentPersona = ref<PersonaDetail | null>(null);

  /** 是否正在从后端加载角色列表 */
  const isLoadingCharacters = ref(false);

  /** 是否正在加载人设状态详情 */
  const isLoadingPersona = ref(false);

  // ===== 计算属性 (Getters) =====

  const hasActiveCharacter = computed(() => activeCharacter.value !== null);

  const characterName = computed(
    () => activeCharacter.value?.name ?? "Unknown"
  );

  const affectionScore = computed(
    () => currentPersona.value?.affection_score ?? 0
  );

  const currentMood = computed(
    () => currentPersona.value?.current_mood ?? "平静"
  );

  const cognitionState = computed(
    () => currentPersona.value?.cognition_state ?? ""
  );

  /** 返回限制在 0-100 之间的好感度百分比，用于 UI 进度条的长度渲染 */
  const affectionPercent = computed(() =>
    Math.min(100, Math.max(0, affectionScore.value))
  );

  const getCharacterById = computed(() => (id: number) => {
    return characterList.value.find((c) => c.id === id) || null;
  });

  // ===== 操作方法 (Actions) =====

  /** 从后端 API 异步加载角色设定列表 */
  async function loadCharacters() {
    isLoadingCharacters.value = true;
    try {
      const res = await getCharacters();
      characterList.value = res.characters;
    } catch (e) {
      console.error("Failed to load characters", e);
    } finally {
      isLoadingCharacters.value = false;
    }
  }

  /** 根据会话 ID 异步加载会话详情与关联的角色设定信息 */
  async function loadSessionDetail(sessionId: number) {
    isLoadingPersona.value = true;
    try {
      const session = await getSession(sessionId);
      currentPersona.value = session.persona;
      
      // Load full character details to populate activeCharacter
      const fullChar = await getCharacter(session.character.id);
      activeCharacter.value = fullChar;
    } catch (e) {
      console.error(`Failed to load session ${sessionId} detail`, e);
    } finally {
      isLoadingPersona.value = false;
    }
  }

  /** 从完整的详情对象中直接设置活跃角色设定 */
  function setActiveCharacter(character: CharacterDetail) {
    activeCharacter.value = character;
  }

  /** 从 API 直接设置更新本地的角色简要列表 */
  function setCharacterList(list: CharacterSummary[]) {
    characterList.value = list;
  }

  /** 从会话详情的响应中加载设置角色人格状态数据 */
  function setPersonaFromSession(session: SessionDetail) {
    currentPersona.value = session.persona;
  }

  /** 直接更新人设状态数据（例如在聊天收到好感度变化或情绪变动时） */
  function updatePersona(patch: Partial<PersonaDetail>) {
    if (currentPersona.value) {
      currentPersona.value = { ...currentPersona.value, ...patch };
    }
  }

  /**
   * 应用从聊天接口响应中收到的好感度增量与情绪变动。
   * 将好感度最终得分限制在 0 至 100 之间。
   */
  function applyAffectionChange(
    delta: number,
    newScore: number,
    newMood?: string
  ) {
    if (currentPersona.value) {
      currentPersona.value.affection_score = Math.min(100, Math.max(0, newScore));
      if (newMood) {
        currentPersona.value.current_mood = newMood;
      }
    }
  }

  /** 清除当前的活跃角色和人设状态数据（例如在登出或切换角色时） */
  function clearActiveCharacter() {
    activeCharacter.value = null;
    currentPersona.value = null;
  }

  /** 在列表中添加或更新角色简要条目 */
  function upsertCharacterInList(character: CharacterSummary) {
    const idx = characterList.value.findIndex((c) => c.id === character.id);
    if (idx !== -1) {
      characterList.value[idx] = character;
    } else {
      characterList.value.push(character);
    }
  }

  /** 通过 API 删除指定角色设定并从本地同步移除 */
  async function removeCharacterFromList(characterId: number) {
    try {
      await deleteCharacter(characterId);
      characterList.value = characterList.value.filter(
        (c) => c.id !== characterId
      );
      if (activeCharacter.value?.id === characterId) {
        clearActiveCharacter();
      }
    } catch (e) {
      console.error("Failed to delete character", e);
    }
  }

  /** 重置整个 Store 的状态变量 */
  function $reset() {
    activeCharacter.value = null;
    characterList.value = [];
    currentPersona.value = null;
    isLoadingCharacters.value = false;
    isLoadingPersona.value = false;
  }

  return {
    // State
    activeCharacter,
    characterList,
    currentPersona,
    isLoadingCharacters,
    isLoadingPersona,
    // Getters
    hasActiveCharacter,
    characterName,
    affectionScore,
    currentMood,
    cognitionState,
    affectionPercent,
    getCharacterById,
    // Actions
    loadCharacters,
    loadSessionDetail,
    setActiveCharacter,
    setCharacterList,
    setPersonaFromSession,
    updatePersona,
    applyAffectionChange,
    clearActiveCharacter,
    upsertCharacterInList,
    removeCharacterFromList,
    $reset,
  };
});
