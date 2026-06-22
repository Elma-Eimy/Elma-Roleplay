<template>
  <view v-if="isOpen" class="modal-backdrop">
    <view class="edit-modal">
      <text class="modal-title">服务器连接地址配置</text>
      <text class="modal-desc">请在此输入后端服务器的 API 访问地址（例如：http://127.0.0.1:8000）。修改后会实时生效并保存于本地缓存中。</text>
      <input
        class="key-input"
        v-model="inputValue"
        placeholder="例如：http://127.0.0.1:8000"
        confirm-type="done"
        @confirm="save"
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
  let url = inputValue.value.trim();
  if (!url) {
    uni.showToast({ title: "连接地址不能为空", icon: "none" });
    return;
  }
  // 如果输入没有 http:// 或 https://，自动补齐
  if (!/^https?:\/\//i.test(url)) {
    url = "http://" + url;
  }
  emit("save", url);
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
}

.edit-modal {
  width: 580rpx;
  background-color: #ffffff;
  border-radius: 28rpx;
  padding: 44rpx 36rpx;
  display: flex;
  flex-direction: column;
  gap: 24rpx;
  box-shadow: 0 15px 35px rgba(0, 0, 0, 0.1);
  border: 1px solid rgba(0, 0, 0, 0.05);
}

.modal-title {
  font-size: 32rpx;
  font-weight: 600;
  color: #1c1c1e;
  text-align: center;
}

.modal-desc {
  font-size: 22rpx;
  color: #8e8e93;
  line-height: 1.5;
  text-align: center;
}

.key-input {
  width: 100%;
  height: 80rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 16rpx;
  padding: 0 24rpx;
  font-size: 28rpx;
  color: #1c1c1e;
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
  background-color: rgba(0, 0, 0, 0.03);
  color: #48484a;
}

.modal-btn.cancel:active {
  background-color: rgba(0, 0, 0, 0.06);
}

.modal-btn.save {
  background-color: #1c1c1e;
  color: #ffffff;
}

.modal-btn.save:active {
  background-color: #000000;
  transform: scale(0.97);
}
</style>
