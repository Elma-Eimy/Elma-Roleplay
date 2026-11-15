<template>
  <view v-if="isOpen" class="rename-modal-backdrop">
    <view class="rename-modal">
      <text class="modal-title">重命名分支</text>
      <input class="rename-input" v-model="inputValue" placeholder="请输入新分支名称..." :focus="true" />
      <view class="modal-actions">
        <view class="modal-btn cancel" @tap="close">取消</view>
        <view class="modal-btn save" @tap="save">保存</view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";

const props = defineProps<{
  isOpen: boolean;
  title: string;
}>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "save", newTitle: string): void;
}>();

const inputValue = ref("");

watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    inputValue.value = props.title;
  }
});

const close = () => {
  emit("close");
};

const save = () => {
  emit("save", inputValue.value.trim());
};
</script>

<style scoped>
.rename-modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: var(--app-color-mask, rgba(25, 37, 32, 0.42));
  backdrop-filter: blur(10px);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.2s ease;
}

.rename-modal {
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

.rename-input {
  width: 100%;
  height: 80rpx;
  background-color: var(--app-color-background, #f7f9f7);
  border: 1px solid var(--app-color-border-strong, rgba(38, 51, 46, 0.14));
  border-radius: 16rpx;
  padding: 0 20rpx;
  font-size: 28rpx;
  color: var(--app-color-text-primary, #26332e);
  box-sizing: border-box;
}

.rename-input:focus {
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
  transition: all 0.2s;
}

.modal-btn.cancel {
  background-color: rgba(38, 51, 46, 0.05);
  color: var(--app-color-text-secondary, #64716b);
}

.modal-btn.cancel:active {
  background-color: rgba(38, 51, 46, 0.1);
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
