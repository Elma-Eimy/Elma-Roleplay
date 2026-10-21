<template>
  <view v-if="isOpen" class="story-overlay">
    <view class="story-backdrop" @tap="closeModal"></view>
    <view class="story-panel" role="dialog" aria-label="开启新故事">
      <view class="story-header"
        ><view
          ><text class="story-kicker">A NEW CHAPTER</text
          ><text class="story-title">{{
            showGreetings ? "选择故事的开始" : "延续这段故事"
          }}</text></view
        ><button class="close-button" aria-label="关闭" @tap="closeModal">
          ×
        </button></view
      >
      <scroll-view scroll-y class="story-body"
        ><view class="story-body-inner">
          <text class="field-label">故事名称</text
          ><input
            class="story-input"
            v-model="sessionTitle"
            placeholder="为这次相遇起个名字（可选）"
            :maxlength="100"
          />
          <CharacterGreetings
            v-if="showGreetings"
            v-model="selectedIndex"
            :first-mes="firstMes"
            :alternates="alternateGreetings"
            :character-name="characterName || '角色'"
            :user-name="personaStore.nicknameFor(characterId)"
          />
          <text v-else class="story-hint"
            >新分支会继承当前剧情进度与人物状态。</text
          >
        </view></scroll-view
      >
      <view class="story-footer"
        ><button class="cancel-button" @tap="closeModal">取消</button
        ><button class="confirm-button" @tap="onConfirm">
          开启故事 →
        </button></view
      >
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import { usePersonaStore } from "@/store/personaStore";
import CharacterGreetings from "@/components/character/CharacterGreetings.vue";
const personaStore = usePersonaStore();
const props = withDefaults(
  defineProps<{
    isOpen: boolean;
    alternateGreetings?: string[];
    firstMes?: string;
    characterName?: string;
    characterId?: number | null;
    showGreetings?: boolean;
  }>(),
  { alternateGreetings: () => [], firstMes: "", showGreetings: true },
);
const emit = defineEmits<{
  (event: "update:isOpen", value: boolean): void;
  (event: "close"): void;
  (
    event: "confirm",
    payload: { title: string; greeting_index: number | null },
  ): void;
}>();
const sessionTitle = ref("");
const selectedIndex = ref<number | null>(null);
watch(
  () => props.isOpen,
  () => {
    sessionTitle.value = "";
    selectedIndex.value = null;
  },
);
const closeModal = () => {
  emit("update:isOpen", false);
  emit("close");
};
const onConfirm = () => {
  emit("confirm", {
    title: sessionTitle.value.trim() || "新故事会话",
    greeting_index: props.showGreetings ? selectedIndex.value : null,
  });
  closeModal();
};
</script>

<style scoped>
.story-overlay {
  position: fixed;
  inset: 0;
  z-index: 300;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24rpx;
  box-sizing: border-box;
}
.story-backdrop {
  position: absolute;
  inset: 0;
  background: #17291f70;
  backdrop-filter: blur(8px);
}
.story-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 680px;
  max-height: 90vh;
  background: #fff;
  border-radius: 28rpx;
  overflow: hidden;
}
.story-header {
  padding: 28rpx 32rpx;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20rpx;
}
.story-kicker {
  display: block;
  font-size: 18rpx;
  letter-spacing: 3rpx;
  color: #71917f;
  margin-bottom: 8rpx;
}
.story-title {
  display: block;
  font-size: 34rpx;
  color: #26332e;
  font-weight: 700;
}
.close-button {
  margin: 0;
  width: 64rpx;
  height: 64rpx;
  padding: 0;
  line-height: 58rpx;
  border-radius: 50%;
  font-size: 40rpx;
  background: #f3f6f3;
  color: #718177;
}
.story-body {
  flex: 1;
  min-height: 0;
  height: 65vh;
}
.story-body-inner {
  padding: 0 32rpx 32rpx;
}
.field-label {
  display: block;
  font-size: 25rpx;
  font-weight: 600;
  color: #4f6958;
}
.story-input {
  height: 88rpx;
  box-sizing: border-box;
  padding: 0 22rpx;
  border: 1px solid #e1e8e2;
  border-radius: 16rpx;
  margin: 16rpx 0 28rpx;
  font-size: 26rpx;
  background: #f7f9f7;
}
.story-hint {
  font-size: 26rpx;
  line-height: 1.8;
  color: #7c8983;
}
.story-footer {
  display: flex;
  gap: 20rpx;
  padding: 24rpx 32rpx;
  padding-bottom: max(24rpx, env(safe-area-inset-bottom));
  border-top: 1px solid #e3e9e5;
}
.story-footer button {
  margin: 0;
  font-size: 26rpx;
  border-radius: 18rpx;
  line-height: 84rpx;
}
.cancel-button {
  background: #f3f6f3;
  color: #7c8983;
  width: 180rpx;
}
.confirm-button {
  flex: 1;
  background: #4f8e7c;
  color: #fff;
}
@media (max-width: 600px) {
  .story-overlay {
    padding: 0;
    align-items: flex-end;
  }
  .story-panel {
    border-radius: 28rpx 28rpx 0 0;
    max-height: 94vh;
  }
}
</style>
