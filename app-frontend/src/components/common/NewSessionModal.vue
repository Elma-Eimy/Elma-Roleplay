<template>
  <view class="modal-container" :class="{ 'is-open': isOpen }">
    <view class="backdrop" @tap="closeModal"></view>
    
    <view class="modal-panel">
      <view class="modal-header">
        <text class="modal-title">开启新故事会话</text>
        <view class="close-btn-wrapper" @tap="closeModal">
          <PhX class="close-icon" :size="16" weight="regular" />
        </view>
      </view>

      <view class="modal-body">
        <text class="input-label">会话故事主题</text>
        <input 
          class="title-input" 
          v-model="sessionTitle" 
          placeholder="为这篇故事起一个名字..."
          :focus="isOpen"
        />
        <text class="input-hint">留空将使用默认标题 “新故事会话”。</text>
      </view>

      <view class="modal-footer">
        <view class="btn cancel-btn" @tap="closeModal">取消</view>
        <view class="btn confirm-btn" @tap="onConfirm">开启</view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import { PhX } from "@phosphor-icons/vue";

const props = defineProps<{
  isOpen: boolean;
}>();

const emit = defineEmits<{
  (e: "update:isOpen", value: boolean): void;
  (e: "confirm", title: string): void;
}>();

const sessionTitle = ref("");

// 当模态框打开时清空并重置输入的故事主题标题
watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    sessionTitle.value = "";
  }
});

const closeModal = () => {
  emit("update:isOpen", false);
};

const onConfirm = () => {
  emit("confirm", sessionTitle.value.trim() || "新故事会话");
  closeModal();
};
</script>

<style scoped>
.modal-container {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  z-index: 200;
  pointer-events: none;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-container.is-open {
  pointer-events: auto;
}

.backdrop {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.3);
  opacity: 0;
  transition: opacity 0.25s ease;
  backdrop-filter: blur(4px);
}

.is-open .backdrop {
  opacity: 1;
}

.modal-panel {
  position: relative;
  width: 85vw;
  max-width: 580rpx;
  background-color: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.05);
  border-radius: 28rpx;
  box-shadow: 0 15px 40px rgba(0, 0, 0, 0.12);
  transform: translateY(30rpx) scale(0.96);
  opacity: 0;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  display: flex;
  flex-direction: column;
}

.is-open .modal-panel {
  transform: translateY(0) scale(1);
  opacity: 1;
}

.modal-header {
  padding: 32rpx 36rpx;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid rgba(0, 0, 0, 0.03);
}

.modal-title {
  font-size: 30rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.close-btn-wrapper {
  width: 44rpx;
  height: 44rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.02);
}

.close-btn-wrapper:active {
  background-color: rgba(0, 0, 0, 0.06);
}

.close-icon {
  color: #8e8e93;
}

.modal-body {
  padding: 36rpx;
  display: flex;
  flex-direction: column;
}

.input-label {
  font-size: 24rpx;
  font-weight: 600;
  color: #48484a;
  margin-bottom: 16rpx;
}

.title-input {
  width: 100%;
  height: 80rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 14rpx;
  padding: 0 20rpx;
  font-size: 28rpx;
  color: #1c1c1e;
  box-sizing: border-box;
}

.title-input:focus {
  border-color: #1c1c1e;
  background-color: #ffffff;
}

.input-hint {
  font-size: 22rpx;
  color: #8e8e93;
  margin-top: 14rpx;
}

.modal-footer {
  padding: 24rpx 36rpx 36rpx 36rpx;
  display: flex;
  justify-content: flex-end;
  gap: 16rpx;
  border-top: 1px solid rgba(0, 0, 0, 0.03);
}

.btn {
  padding: 16rpx 36rpx;
  border-radius: 40rpx;
  font-size: 26rpx;
  font-weight: 600;
  text-align: center;
  transition: all 0.2s;
}

.cancel-btn {
  background-color: rgba(0, 0, 0, 0.03);
  color: #48484a;
}

.cancel-btn:active {
  background-color: rgba(0, 0, 0, 0.06);
}

.confirm-btn {
  background-color: #1c1c1e;
  color: #ffffff;
}

.confirm-btn:active {
  background-color: #000000;
  transform: scale(0.96);
}
</style>
