<template>
  <view v-if="isOpen" class="modal-backdrop">
    <view class="edit-modal">
      <text class="modal-title">API 访问密钥配置</text>
      <text class="modal-desc">当后端开启 ACCESS_API_KEY 访问控制时，请在此配置匹配的 X-API-Key 密钥。</text>
      <input
        class="key-input"
        v-model="inputValue"
        placeholder="请输入密钥..."
        password
      />
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
  value: string;
}>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "save", val: string): void;
}>();

const inputValue = ref("");

watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    inputValue.value = props.value;
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
.modal-backdrop {
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
}

.edit-modal {
  width: 580rpx;
  background-color: var(--app-color-surface, #ffffff);
  border-radius: var(--app-radius-lg, 32rpx);
  padding: 44rpx 36rpx;
  display: flex;
  flex-direction: column;
  gap: 24rpx;
  box-shadow: var(--app-shadow-card, 0 18rpx 48rpx rgba(45, 72, 62, 0.1));
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
}

.modal-title {
  font-size: 32rpx;
  font-weight: 600;
  color: var(--app-color-text-primary, #26332e);
  text-align: center;
}

.modal-desc {
  font-size: 22rpx;
  color: var(--app-color-text-secondary, #64716b);
  line-height: 1.5;
  text-align: center;
}

.key-input {
  width: 100%;
  height: 80rpx;
  background-color: var(--app-color-background, #f7f9f7);
  border: 1px solid var(--app-color-border-strong, rgba(38, 51, 46, 0.14));
  border-radius: 16rpx;
  padding: 0 24rpx;
  font-size: 28rpx;
  color: var(--app-color-text-primary, #26332e);
  box-sizing: border-box;
}

.modal-actions {
  display: flex;
  justify-content: space-between;
  gap: 20rpx;
  margin-top: 10rpx;
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
</style>
