<template>
  <view class="drawer-container" :class="{ 'is-open': isOpen }">
    <!-- 遮罩层：点击关闭侧边抽屉 -->
    <view class="backdrop" @tap="closeDrawer"></view>

    <!-- 抽屉面板 -->
    <view class="drawer-panel">
      <!-- 面板头部区域 -->
      <view class="drawer-header">
        <text class="drawer-title">History</text>
        <view class="new-btn" @tap="onNewSession">
          <text class="new-icon">+</text>
        </view>
      </view>

      <!-- 会话历史列表 -->
      <scroll-view scroll-y class="session-scroll-view">
        <view 
          v-for="session in sessions" 
          :key="session.id"
          class="session-item"
          :class="{ 'is-active': activeSessionId === session.id }"
          @tap="onSelectSession(session.id)"
        >
          <AvatarImage
            class="session-avatar" 
            :src="characterAvatar"
          />
          <view class="session-content">
            <view class="title-row">
              <text class="session-title">{{ session.title || 'New Story' }}</text>
              <text class="branch-badge" v-if="session.parent_session_id !== null">分支</text>
            </view>
            <view class="session-meta">
              <text class="session-date">{{ formatDate(session.updated_at) }}</text>
              <text class="session-mood" v-if="session.persona?.current_mood">
                {{ session.persona.current_mood }}
              </text>
            </view>
          </view>
        </view>

        <!-- 会话空状态 -->
        <view v-if="sessions.length === 0" class="empty-state">
          <text class="empty-text">No conversations yet</text>
        </view>
      </scroll-view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { SessionSummary } from "@/api/sessions";
import AvatarImage from "@/components/common/AvatarImage.vue";

const props = defineProps<{
  isOpen: boolean;
  sessions: SessionSummary[];
  activeSessionId: number | null;
  characterAvatar?: string;
}>();

const emit = defineEmits<{
  (e: "update:isOpen", value: boolean): void;
  (e: "select", sessionId: number): void;
  (e: "create"): void;
}>();

const closeDrawer = () => {
  emit("update:isOpen", false);
};

const onSelectSession = (id: number) => {
  emit("select", id);
  closeDrawer();
};

const onNewSession = () => {
  emit("create");
  closeDrawer();
};

const formatDate = (dateString: string) => {
  if (!dateString) return "";
  const date = new Date(dateString);
  const now = new Date();
  const isToday = date.toDateString() === now.toDateString();
  
  if (isToday) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
};
</script>

<style scoped>
/* ===== 外层容器与遮罩层 ===== */
.drawer-container {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  z-index: 100;
  pointer-events: none; /* 当侧边栏关闭时允许点击事件穿透 */
}

.drawer-container.is-open {
  pointer-events: auto;
}

.backdrop {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.4);
  opacity: 0;
  transition: opacity 0.3s ease;
}

.is-open .backdrop {
  opacity: 1;
}

/* ===== 抽屉面板 ===== */
.drawer-panel {
  position: absolute;
  top: 0;
  left: 0;
  width: 80vw;
  max-width: 600rpx;
  height: 100%;
  background-color: #f9fafb; /* Minimalist off-white */
  transform: translateX(-100%);
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  flex-direction: column;
  box-shadow: 4px 0 16px rgba(0, 0, 0, 0.05);
}

.is-open .drawer-panel {
  transform: translateX(0);
}

/* ===== 面板头部 ===== */
.drawer-header {
  padding: env(safe-area-inset-top, 40rpx) 32rpx 32rpx 32rpx;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #e5e7eb;
  background-color: #ffffff;
}

.drawer-title {
  font-size: 36rpx;
  font-weight: 700;
  color: #111827;
  letter-spacing: 1rpx;
}

.new-btn {
  width: 64rpx;
  height: 64rpx;
  border-radius: 50%;
  background-color: #000000;
  display: flex;
  align-items: center;
  justify-content: center;
}

.new-icon {
  color: #ffffff;
  font-size: 40rpx;
  font-weight: 300;
  line-height: 1;
  margin-top: -4rpx; /* 微调以保证视觉居中对齐 */
}

/* ===== 滚动视图与列表 ===== */
.session-scroll-view {
  flex: 1;
  padding: 24rpx;
  padding-bottom: calc(env(safe-area-inset-bottom, 40rpx) + 24rpx);
}

.session-item {
  display: flex;
  align-items: center;
  padding: 20rpx 24rpx;
  margin-bottom: 16rpx;
  background-color: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 16rpx;
  transition: all 0.2s ease;
  gap: 20rpx;
}

.session-item.is-active {
  border-color: #111827;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.session-avatar {
  width: 80rpx;
  height: 80rpx;
  border-radius: 40rpx;
  background-color: #f3f4f6;
  border: 1px solid #e5e7eb;
  flex-shrink: 0;
}

.session-content {
  flex: 1;
  min-width: 0; /* 防止弹性子元素溢出容器 */
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.session-title {
  font-size: 32rpx;
  font-weight: 600;
  color: #111827;
  display: block;
  margin-bottom: 6rpx;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.session-date {
  font-size: 24rpx;
  color: #6b7280;
}

.session-mood {
  font-size: 24rpx;
  color: #4b5563;
  background-color: #f3f4f6;
  padding: 6rpx 16rpx;
  border-radius: 100rpx;
}

/* ===== 空状态 ===== */
.empty-state {
  padding: 64rpx 0;
  display: flex;
  justify-content: center;
}

.empty-text {
  font-size: 28rpx;
  color: #9ca3af;
}

/* ===== 从属分支徽章 ===== */
.title-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-bottom: 6rpx;
}

.session-title {
  margin-bottom: 0 !important; /* 覆盖由外层 title-row 处理的下边距 */
}

.branch-badge {
  font-size: 22rpx;
  color: #10b981;
  background-color: rgba(16, 185, 129, 0.1);
  padding: 4rpx 12rpx;
  border-radius: 6rpx;
  font-weight: 600;
  flex-shrink: 0;
}
</style>
