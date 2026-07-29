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
        :show-confirm-bar="false"
        @input="handleInput"
      ></textarea>
      <view class="modal-actions">
        <view class="modal-btn cancel" @tap="emit('cancel')">取消</view>
        <view class="modal-btn save" @tap="emit('save')">保存</view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
defineProps<{
  isOpen: boolean;
  modelValue: string;
  isAndroid: boolean;
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
.modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  height: 100dvh;
  background-color: rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(10px);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.2s ease;
}

.modal-backdrop.is-android {
  backdrop-filter: none;
  background-color: rgba(0, 0, 0, 0.5);
}

.edit-modal {
  width: 580rpx;
  background-color: var(--app-color-surface, #ffffff);
  border-radius: var(--app-radius-lg, 28rpx);
  padding: 44rpx 36rpx;
  display: flex;
  flex-direction: column;
  gap: 28rpx;
  box-shadow: 0 15px 35px rgba(0, 0, 0, 0.1);
  border: 1px solid var(--app-color-border, rgba(0, 0, 0, 0.05));
}

.modal-title {
  font-size: 32rpx;
  font-weight: 600;
  color: var(--app-color-text-primary, #1c1c1e);
  text-align: center;
}

.edit-textarea {
  width: 100%;
  height: 260rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 16rpx;
  padding: 20rpx 24rpx;
  font-size: 28rpx;
  color: var(--app-color-text-primary, #1c1c1e);
  line-height: 1.5;
  box-sizing: border-box;
}

.edit-textarea:focus {
  border-color: var(--app-color-text-primary, #1c1c1e);
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
  background-color: rgba(0, 0, 0, 0.03);
  color: #48484a;
}

.modal-btn.save {
  background-color: var(--app-color-text-primary, #1c1c1e);
  color: #ffffff;
}

.modal-btn.save:active {
  background-color: #000000;
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
