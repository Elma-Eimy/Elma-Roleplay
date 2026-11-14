<template>
  <ChatDrawer
    :is-open="isOpen"
    :session-id="sessionId"
    :background-mode="backgroundMode"
    :profile="drawerProfile"
    @close="emit('close')"
    @update:background-mode="emit('update:background-mode', $event)"
    @delete-session="emit('delete-session')"
    @open-memory-view="emit('open-memory-view')"
    @open-prompt-preview="emit('open-prompt-preview')"
  >
    <template #role-state>
      <view class="panel-section">
        <RoleStatePanel
          :session-id="sessionId"
          :processing="chatStore.isLoading"
          :timeline="portraitTimeline"
        />
      </view>
    </template>

    <template #portraits>
      <view v-if="personaStore.activeCharacter?.id" class="panel-section">
        <CharacterPortraitPanel
          :character-id="personaStore.activeCharacter.id"
          :session-id="sessionId"
          :disabled="chatStore.isLoading"
          :timeline="portraitTimeline"
          @changed="emit('portrait-changed')"
        />
      </view>
    </template>

    <template #before-settings>
      <view class="panel-section">
        <text class="section-title">我的设定</text>
        <view class="setting-row">
          <view class="setting-row-left">
            <image class="setting-row-icon" src="/static/icons/menu_user_plus.svg" mode="aspectFit" />
            <view class="setting-row-copy">
              <text class="setting-row-label">我的名字</text>
              <text class="setting-row-hint">只对当前角色生效</text>
            </view>
          </view>
          <input
            class="drawer-nickname-input"
            v-model="userNicknameInput"
            @blur="saveUserNickname"
            confirm-type="done"
            @confirm="saveUserNickname"
            placeholder="请输入你的昵称..."
          />
        </view>
      </view>
    </template>

    <template #model-meta>
      <text v-if="chatStore.lastMeta?.model_used" class="generation-scope">
        上次回复使用：{{ chatStore.lastMeta.model_used }}
      </text>
    </template>

    <template #after-settings>
      <view class="panel-section">
        <text class="section-title">平行宇宙</text>
        <view class="action-btn outline" @tap="emit('open-branch-tree')">
          <image class="btn-icon" src="/static/icons/char_branch.svg" mode="aspectFit" />
          <text class="btn-text">查看分支时空树</text>
        </view>
      </view>
    </template>

    <template #memory-extra>
      <MemoryProcessingPanel :session-id="sessionId" />
      <view class="action-btn outline" @tap="updateCognition">
        <image class="btn-icon" src="/static/icons/drawer_sync.svg" mode="aspectFit" />
        <text class="btn-text">更新微观认知</text>
      </view>
    </template>
  </ChatDrawer>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import { useChatStore } from "@/store/chatStore";
import { usePersonaStore } from "@/store/personaStore";
import { triggerCognition } from "@/api/sessions";
import ChatDrawer, { type ChatDrawerProfile } from "./ChatDrawer.vue";
import RoleStatePanel from "./RoleStatePanel.vue";
import CharacterPortraitPanel from "@/components/character/CharacterPortraitPanel.vue";
import MemoryProcessingPanel from "./MemoryProcessingPanel.vue";

const props = defineProps<{
  isOpen: boolean;
  sessionId: number | null;
  backgroundMode: "clean" | "character";
}>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "portrait-changed"): void;
  (e: "delete-session"): void;
  (e: "open-branch-tree"): void;
  (e: "open-memory-view"): void;
  (e: "open-prompt-preview"): void;
  (e: "update:background-mode", mode: "clean" | "character"): void;
}>();

const chatStore = useChatStore();
const personaStore = usePersonaStore();

const portraitTimeline = computed(
  () => `${chatStore.isLoading}:${chatStore.messages.map((message) => message.id).join(",")}`
);

const drawerProfile = computed<ChatDrawerProfile>(() => ({
  name: personaStore.characterName,
  character: personaStore.activeCharacter,
  affection: personaStore.affectionScore,
  mood: personaStore.currentMood,
  cognition: personaStore.cognitionState,
  loading: personaStore.isLoadingPersona,
}));

const userNicknameInput = ref(personaStore.userNickname);
watch(() => personaStore.userNickname, (newVal) => {
  userNicknameInput.value = newVal;
});

const saveUserNickname = () => {
  const name = userNicknameInput.value.trim();
  const characterId = personaStore.activeCharacter?.id;
  if (name && characterId != null) {
    personaStore.updateUserNickname(name, characterId);
  } else {
    userNicknameInput.value = personaStore.userNickname;
  }
};

const updateCognition = async () => {
  if (props.sessionId === null) return;
  try {
    uni.showLoading({ title: "正在更新认知..." });
    const res = await triggerCognition(props.sessionId);
    await personaStore.loadSessionDetail(props.sessionId);
    uni.hideLoading();
    uni.showToast({ title: res.message || "认知更新完成", icon: "success" });
  } catch (e) {
    uni.hideLoading();
    uni.showToast({ title: "认知更新失败", icon: "none" });
    console.error(e);
  }
};
</script>

<style scoped>
@import "./chatDrawer.css";
</style>
