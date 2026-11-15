<template>
  <view
    v-if="isOpen"
    class="modal-backdrop"
    :class="{ 'is-android': isAndroid }"
  >
    <view class="edit-modal">
      <text class="modal-title">编辑消息</text>
      <textarea
        class="edit-textarea"
        :value="modelValue"
        :maxlength="-1"
        :disabled="isSaving"
        :show-confirm-bar="false"
        @input="handleInput"
      ></textarea>
      <text v-if="error" class="edit-error" role="alert">{{ error }}</text>
      <view class="modal-actions">
        <view class="modal-btn cancel" @tap="emit('cancel')">取消</view>
        <view class="modal-btn save" :class="{ 'is-disabled': isSaving }" :aria-disabled="isSaving" @tap="!isSaving && emit('save')">{{ isSaving ? "保存中…" : "保存" }}</view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
defineProps<{
  isOpen: boolean;
  modelValue: string;
  isAndroid: boolean;
  isSaving?: boolean;
  error?: string;
}>();

const emit = defineEmits<{
  (event: "update:modelValue", value: string): void;
  (event: "cancel"): void;
  (event: "save"): void;
}>();

const handleInput = (event: Event) => {
  const inputEvent = event as unknown as { detail: { value: string } };
  emit("update:modelValue", inputEvent.detail.value);
};
</script>

<style scoped>
.edit-error {
  display: block;
  color: var(--app-color-danger, #d9655d);
  margin-top: 16rpx;
  font-size: 24rpx;
}

.modal-btn.is-disabled {
  opacity: 0.55;
}

.modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  height: 100dvh;
  background-color: var(--app-color-mask, rgba(25, 37, 32, 0.42));
  backdrop-filter: blur(10px);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.2s ease;
}

.modal-backdrop.is-android {
  backdrop-filter: none;
  background-color: rgba(25, 37, 32, 0.56);
}

.edit-modal {
  width: 580rpx;
  background-color: var(--app-color-surface, #ffffff);
  border-radius: var(--app-radius-lg, 32rpx);
  padding: 44rpx 36rpx;
  display: flex;
  flex-direction: column;
  gap: 28rpx;
  box-shadow: var(--app-shadow-card, 0 18rpx 48rpx rgba(45, 72, 62, 0.1));
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
}

.modal-title {
  font-size: 32rpx;
  font-weight: 600;
  color: var(--app-color-text-primary, #26332e);
  text-align: center;
}

.edit-textarea {
  width: 100%;
  height: 260rpx;
  background-color: var(--app-color-background, #f7f9f7);
  border: 1px solid var(--app-color-border-strong, rgba(38, 51, 46, 0.14));
  border-radius: 16rpx;
  padding: 20rpx 24rpx;
  font-size: 28rpx;
  color: var(--app-color-text-primary, #26332e);
  line-height: 1.5;
  box-sizing: border-box;
}

.edit-textarea:focus {
  border-color: var(--app-color-primary, #70ae9b);
  background-color: var(--app-color-surface, #ffffff);
}

.modal-actions {
  display: flex;
  justify-content: space-between;
  gap: 20rpx;
}

.modal-btn {
  flex: 1;
  height: 80rpx;
  border-radius: 40rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26rpx;
  font-weight: 600;
  transition:
    transform var(--app-motion-fast, 0.2s),
    background-color var(--app-motion-fast, 0.2s);
}

.modal-btn.cancel {
  background-color: rgba(38, 51, 46, 0.05);
  color: var(--app-color-text-secondary, #64716b);
}

.modal-btn.save {
  background-color: var(--app-color-primary-strong, #4f8e7c);
  color: #ffffff;
}

.modal-btn.save:active {
  background-color: #427a6a;
  transform: scale(0.97);
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
</style>
