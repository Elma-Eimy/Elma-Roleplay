<template>
  <view v-if="isOpen" class="modal-backdrop" @tap="close">
    <view class="prompt-preview-modal" @tap.stop>
      <view class="modal-header">
        <text class="modal-title">当前 Prompt 组装预览</text>
        <view class="modal-close-btn" @tap="close">×</view>
      </view>
      <scroll-view scroll-y class="prompt-preview-scroll">
        <view class="prompt-preview-content">
          <view 
            class="prompt-msg-card" 
            v-for="(msg, idx) in messages" 
            :key="idx"
            :class="'role-' + msg.role"
          >
            <view class="prompt-msg-role-tag">{{ msg.role.toUpperCase() }}</view>
            <text class="prompt-msg-text" :selectable="true" :user-select="true">{{ msg.content }}</text>
          </view>
        </view>
      </scroll-view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { defineProps, defineEmits } from "vue";

interface CompiledMessage {
  role: string;
  content: string;
}

defineProps<{
  isOpen: boolean;
  messages: CompiledMessage[];
}>();

const emit = defineEmits<{
  (e: "close"): void;
}>();

const close = () => {
  emit("close");
};
</script>

<style scoped>
.modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(10px);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.prompt-preview-modal {
  width: 90vw;
  max-width: 680rpx;
  height: 80vh;
  background-color: #ffffff;
  border-radius: 28rpx;
  display: flex;
  flex-direction: column;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.15);
  animation: modalFadeIn 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
}

@keyframes modalFadeIn {
  from { opacity: 0; transform: scale(0.95); }
  to { opacity: 1; transform: scale(1); }
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 32rpx 36rpx;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
}

.modal-title {
  font-size: 32rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.modal-close-btn {
  font-size: 40rpx;
  color: #8e8e93;
  cursor: pointer;
  padding: 0 10rpx;
  line-height: 1;
}

.modal-close-btn:active {
  color: #1c1c1e;
}

.prompt-preview-scroll {
  flex: 1;
  height: 0;
  min-height: 0;
}

.prompt-preview-content {
  padding: 36rpx;
  display: flex;
  flex-direction: column;
  gap: 28rpx;
}

.prompt-msg-card {
  border-radius: 16rpx;
  padding: 20rpx;
  display: flex;
  flex-direction: column;
  gap: 12rpx;
  border: 1px solid rgba(0, 0, 0, 0.05);
}

.prompt-msg-card.role-system {
  background-color: rgba(0, 122, 255, 0.03);
  border-color: rgba(0, 122, 255, 0.1);
}

.prompt-msg-card.role-user {
  background-color: rgba(0, 0, 0, 0.02);
  border-color: rgba(0, 0, 0, 0.05);
}

.prompt-msg-card.role-assistant {
  background-color: rgba(52, 199, 89, 0.03);
  border-color: rgba(52, 199, 89, 0.1);
}

.prompt-msg-role-tag {
  font-size: 20rpx;
  font-weight: 700;
  padding: 2rpx 10rpx;
  border-radius: 8rpx;
  align-self: flex-start;
}

.role-system .prompt-msg-role-tag {
  background-color: #007aff;
  color: #ffffff;
}

.role-user .prompt-msg-role-tag {
  background-color: #1c1c1e;
  color: #ffffff;
}

.role-assistant .prompt-msg-role-tag {
  background-color: #34c759;
  color: #ffffff;
}

.prompt-msg-text {
  font-size: 26rpx;
  line-height: 1.6;
  color: #3a3a3c;
  word-break: break-all;
}
</style>
