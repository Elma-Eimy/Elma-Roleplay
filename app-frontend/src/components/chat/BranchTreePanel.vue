<template>
  <view v-if="isOpen" class="tree-overlay-backdrop">
    <view class="tree-overlay-panel">
      <!-- 导航栏头部 -->
      <view class="custom-header border-bottom">
        <view class="header-btn left-btn" @tap="close">
          <image class="back-icon" style="width: 44rpx; height: 44rpx;" src="/static/icons/drawer_close.svg" mode="aspectFit" />
        </view>
        <view class="header-center">
          <text class="character-name">时空分支树</text>
        </view>
        <view class="header-btn right-btn" style="opacity: 0; pointer-events: none;">
          <view style="width: 40rpx; height: 40rpx;"></view>
        </view>
      </view>

      <!-- 树渲染区域 -->
      <scroll-view scroll-y class="tree-scroll-area">
        <view class="tree-padding">
          <view v-if="isLoading" class="tree-loading">
            <text class="loading-text">正在加载平行时空...</text>
          </view>
          <BranchTreeView 
            v-else
            :sessions="sessions" 
            @tap-node="tapNode"
            @longpress-node="longpressNode"
            @branch-node="branchNode"
          />
        </view>
      </scroll-view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { defineProps, defineEmits } from "vue";
import BranchTreeView from "./BranchTreeView.vue";

defineProps<{
  isOpen: boolean;
  isLoading: boolean;
  sessions: any[];
}>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "tap-node", session: any): void;
  (e: "longpress-node", session: any): void;
  (e: "branch-node", session: any): void;
}>();

const close = () => {
  emit("close");
};

const tapNode = (session: any) => {
  emit("tap-node", session);
};

const longpressNode = (session: any) => {
  emit("longpress-node", session);
};

const branchNode = (session: any) => {
  emit("branch-node", session);
};
</script>

<style scoped>
/* ===== 自定义导航栏头部 ===== */
.custom-header {
  padding-top: env(safe-area-inset-top, 40rpx);
  height: calc(env(safe-area-inset-top, 40rpx) + 110rpx);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-left: 36rpx;
  padding-right: 36rpx;
  background-color: rgba(255, 255, 255, 0.65);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
  z-index: 50;
}

.header-btn {
  width: 60rpx;
  height: 60rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.02);
}

.header-btn:active {
  background-color: rgba(0, 0, 0, 0.06);
}

.left-btn {
  margin-left: -10rpx;
}

.right-btn {
  margin-right: -10rpx;
  color: #1c1c1e;
}

.header-center {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.character-name {
  font-size: 30rpx;
  font-weight: 600;
  color: #1c1c1e;
}

/* ===== 平行时空分支树全屏遮罩面板样式 ===== */
.tree-overlay-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: rgba(0, 0, 0, 0.4);
  z-index: 100;
  display: flex;
  justify-content: flex-end;
}

.tree-overlay-panel {
  width: 100%;
  height: 100%;
  background-color: #ffffff;
  display: flex;
  flex-direction: column;
  animation: slideUp 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slideUp {
  from {
    transform: translateY(100%);
  }
  to {
    transform: translateY(0);
  }
}

.border-bottom {
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
}

.tree-scroll-area {
  flex: 1;
  width: 100%;
  height: 0;
  background-color: #fafafa;
}

.tree-padding {
  padding: 36rpx;
  padding-bottom: calc(36rpx + env(safe-area-inset-bottom, 24rpx));
}

.tree-loading {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 80rpx 0;
}

.loading-text {
  font-size: 26rpx;
  color: #8e8e93;
}

.back-icon {
  width: 44rpx;
  height: 44rpx;
}
</style>
