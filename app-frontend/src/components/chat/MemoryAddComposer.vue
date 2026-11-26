<template>
  <view class="add-memory-container" :class="{ 'is-expanded': expanded }">
    <view v-if="!expanded" class="add-trigger" @tap="emit('open')">
      <view class="add-trigger-icon">+</view>
      <view class="add-trigger-copy">
        <text class="add-trigger-title">添加一条记忆</text>
        <text class="add-trigger-description">补充希望 AI 长期记住的内容</text>
      </view>
    </view>
    <view v-else class="add-composer">
      <view class="add-composer-header">
        <text class="add-composer-title">添加一条记忆</text>
        <text class="add-composer-cancel" @tap="emit('cancel')">取消</text>
      </view>
      <textarea
        v-model="draft"
        class="add-textarea"
        placeholder="例如：我不喜欢别人叫我的全名"
        :maxlength="-1"
        :show-confirm-bar="false"
        :focus="expanded"
      />
      <view
        class="add-submit-btn"
        :class="{ 'is-active': draft.trim().length > 0 }"
        @tap="emit('submit')"
      >
        <text class="submit-btn-text">添加到记忆</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  modelValue: string;
  expanded: boolean;
}>();

const emit = defineEmits<{
  (e: "update:modelValue", value: string): void;
  (e: "open"): void;
  (e: "cancel"): void;
  (e: "submit"): void;
}>();

const draft = computed({
  get: () => props.modelValue,
  set: (value: string) => emit("update:modelValue", value),
});
</script>

<style scoped>
.add-memory-container {
  padding: 18rpx 32rpx calc(24rpx + env(safe-area-inset-bottom));
  background-color: #ffffff;
  border-top: 1px solid rgba(0, 0, 0, 0.04);
  flex-shrink: 0;
}

.add-trigger {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 18rpx 20rpx;
  border: 1px solid rgba(88, 86, 214, 0.1);
  border-radius: 18rpx;
  background-color: rgba(88, 86, 214, 0.055);
  transition: transform 0.2s, background-color 0.2s;
}

.add-trigger:active {
  transform: scale(0.99);
  background-color: rgba(88, 86, 214, 0.09);
}

.add-trigger-icon {
  width: 54rpx;
  height: 54rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border-radius: 50%;
  background-color: #5856d6;
  color: #ffffff;
  font-size: 36rpx;
  font-weight: 400;
  line-height: 1;
}

.add-trigger-copy {
  display: flex;
  flex-direction: column;
  gap: 3rpx;
}

.add-trigger-title {
  color: var(--app-color-text-primary, #26332e);
  font-size: 25rpx;
  font-weight: 650;
}

.add-trigger-description {
  color: var(--app-color-text-secondary, #64716b);
  font-size: 20rpx;
}

.add-composer {
  display: flex;
  flex-direction: column;
  gap: 14rpx;
}

.add-composer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.add-composer-title {
  color: var(--app-color-text-primary, #26332e);
  font-size: 25rpx;
  font-weight: 650;
}

.add-composer-cancel {
  padding: 8rpx 0 8rpx 20rpx;
  color: var(--app-color-text-secondary, #64716b);
  font-size: 23rpx;
}

.add-textarea {
  width: 100%;
  height: 140rpx;
  background-color: var(--app-color-background, #f7f9f7);
  border: 1px solid var(--app-color-border-strong, rgba(38, 51, 46, 0.14));
  border-radius: 16rpx;
  padding: 16rpx 20rpx;
  font-size: 26rpx;
  color: var(--app-color-text-primary, #26332e);
  line-height: 1.4;
  box-sizing: border-box;
}

.add-submit-btn {
  width: 100%;
  height: 68rpx;
  background-color: rgba(38, 51, 46, 0.06);
  border-radius: 16rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background-color 0.2s;
}

.add-submit-btn.is-active {
  background-color: var(--app-color-primary-strong, #4f8e7c);
}

.submit-btn-text {
  font-size: 26rpx;
  color: var(--app-color-text-muted, #89958f);
  font-weight: 600;
}

.add-submit-btn.is-active .submit-btn-text {
  color: #ffffff;
}
</style>
