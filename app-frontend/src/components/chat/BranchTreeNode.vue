<template>
  <view class="branch-tree-node" :class="{ 'is-root': depth === 0 }">
    <!-- 节点行（包含连接线和卡片） -->
    <view class="node-card-row">
      <!-- 非根节点的连接线区域 -->
      <view v-if="depth > 0" class="connector-line-wrapper">
        <view class="connector-line-vertical" :class="{ 'is-last': isLast }"></view>
        <view class="connector-line-horizontal"></view>
      </view>

      <!-- 卡片主体 -->
      <view 
        class="node-card" 
        :class="{ 'is-latest': node.id === latestSessionId }"
        @tap="onTap"
        @longpress="onLongPress"
        @contextmenu.prevent="onLongPress"
      >
        <!-- 最新活跃时空徽章 -->
        <view v-if="node.id === latestSessionId" class="latest-badge">
          <text class="latest-badge-text">最新活跃</text>
        </view>

        <!-- 卡片头部信息 -->
        <view class="card-header">
          <text class="card-title">{{ node.title || '平行宇宙' }}</text>
          
          <view class="card-meta">
            <view v-if="node.persona?.affection_score !== undefined" class="meta-tag affection">
              <image class="affection-heart-icon-node" src="/static/icons/meta_heart.svg" mode="aspectFit" />
              <text class="tag-val">{{ node.persona.affection_score }}</text>
            </view>
            <view v-if="node.persona?.current_mood" class="meta-tag mood">
              <text class="tag-val">{{ node.persona.current_mood }}</text>
            </view>
          </view>
        </view>

        <!-- 聊天信息预览 -->
        <text class="card-preview">{{ node.lastMessage || '开启新的聊天...' }}</text>
        
        <!-- 卡片底部操作栏 -->
        <view class="card-footer">
          <text class="card-date">{{ formattedDate }}</text>
          
          <view class="card-actions">
            <!-- 从此分叉按钮 -->
            <view class="action-btn branch" @tap.stop="onBranch">
              <image class="action-icon" src="/static/icons/header_plus.svg" mode="aspectFit" />
              <text class="action-text">分叉新宇宙</text>
            </view>
            <!-- 进入时空按钮 -->
            <view class="action-btn enter" @tap.stop="onTap">
              <text class="action-text enter-text">进入 →</text>
            </view>
          </view>
        </view>
      </view>
    </view>

    <!-- 递归子节点列表 -->
    <view v-if="node.children && node.children.length > 0" class="children-wrapper">
      <BranchTreeNode
        v-for="(child, index) in node.children"
        :key="child.id"
        :node="child"
        :depth="depth + 1"
        :is-last="index === node.children.length - 1"
        :latest-session-id="latestSessionId"
        @tap-node="emitTapNode"
        @longpress-node="emitLongpressNode"
        @branch-node="emitBranchNode"
      />
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from "vue";

// 声明组件选项（Vue 3.3+）
defineOptions({
  name: 'BranchTreeNode'
});

interface SessionNode {
  id: number;
  title: string;
  parent_session_id: number | null;
  created_at: string;
  updated_at: string;
  persona?: {
    id: number;
    affection_score?: number;
    current_mood?: string;
  };
  lastMessage?: string;
  children: SessionNode[];
  depth: number;
}

const props = defineProps<{
  node: SessionNode;
  depth: number;
  isLast: boolean;
  latestSessionId: number | null;
}>();

const emit = defineEmits<{
  (e: 'tap-node', session: any): void;
  (e: 'longpress-node', session: any): void;
  (e: 'branch-node', session: any): void;
}>();

const formattedDate = computed(() => {
  if (!props.node.updated_at) return "";
  const date = new Date(props.node.updated_at);
  const now = new Date();
  const isToday = date.toDateString() === now.toDateString();
  
  if (isToday) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
  }
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
});

const onTap = () => {
  emit('tap-node', props.node);
};

const onLongPress = () => {
  emit('longpress-node', props.node);
};

const onBranch = () => {
  emit('branch-node', props.node);
};

// 递归向上传递事件
const emitTapNode = (session: any) => emit('tap-node', session);
const emitLongpressNode = (session: any) => emit('longpress-node', session);
const emitBranchNode = (session: any) => emit('branch-node', session);
</script>

<style scoped>
.branch-tree-node {
  display: flex;
  flex-direction: column;
  width: 100%;
}

.node-card-row {
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  position: relative;
}

/* ===== 连接线连接层样式 ===== */
.connector-line-wrapper {
  position: relative;
  width: 40rpx;
  align-self: stretch;
  flex-shrink: 0;
}

.connector-line-vertical {
  position: absolute;
  left: 20rpx;
  top: -24rpx;
  width: 2rpx;
  background-color: rgba(0, 0, 0, 0.08);
  bottom: -24rpx;
}

.connector-line-vertical.is-last {
  bottom: auto;
  height: calc(44rpx + 24rpx); /* 延伸到水平线高度即停止 */
}

.connector-line-horizontal {
  position: absolute;
  left: 20rpx;
  top: 44rpx;
  width: 20rpx;
  height: 2rpx;
  background-color: rgba(0, 0, 0, 0.08);
}

/* ===== 故事卡片主体 ===== */
.node-card {
  flex: 1;
  background-color: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 20rpx;
  padding: 24rpx 24rpx;
  display: flex;
  flex-direction: column;
  gap: 12rpx;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.01);
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  margin-bottom: 24rpx;
  position: relative;
}

.node-card:active {
  transform: scale(0.985);
  border-color: rgba(0, 0, 0, 0.1);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
}

/* 最新时空的高亮框线 */
.node-card.is-latest {
  border-color: rgba(28, 28, 30, 0.15);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.02), 0 0 0 1px rgba(28, 28, 30, 0.04);
  background: linear-gradient(to bottom right, #ffffff, #fafafa);
}

.latest-badge {
  position: absolute;
  top: -16rpx;
  right: 20rpx;
  background-color: #1c1c1e;
  border-radius: 6rpx;
  padding: 4rpx 12rpx;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
  z-index: 2;
}

.latest-badge-text {
  font-size: 20rpx;
  color: #ffffff;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12rpx;
}

.card-title {
  font-size: 32rpx;
  font-weight: 600;
  color: #1c1c1e;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

.card-meta {
  display: flex;
  gap: 8rpx;
  flex-shrink: 0;
}

.meta-tag {
  display: flex;
  align-items: center;
  gap: 4rpx;
  font-size: 22rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.03);
  padding: 6rpx 16rpx;
  border-radius: 40rpx;
}

.meta-tag.affection {
  font-weight: 600;
  color: #ff3b30;
  background-color: rgba(255, 59, 48, 0.02);
  border-color: rgba(255, 59, 48, 0.05);
}

.affection-heart-icon-node {
  width: 20rpx;
  height: 20rpx;
  flex-shrink: 0;
}

.meta-tag.mood {
  font-weight: 500;
  color: #8e8e93;
}

.card-preview {
  font-size: 28rpx;
  color: #8e8e93;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.4;
  min-height: 38rpx;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 4rpx;
  border-top: 1px solid rgba(0, 0, 0, 0.02);
  padding-top: 12rpx;
}

.card-date {
  font-size: 22rpx;
  color: #c7c7cc;
  font-weight: 500;
}

.card-actions {
  display: flex;
  gap: 16rpx;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 6rpx;
  padding: 10rpx 20rpx;
  border-radius: 30rpx;
  background-color: rgba(0, 0, 0, 0.02);
  transition: all 0.2s;
}

.action-btn:active {
  background-color: rgba(0, 0, 0, 0.06);
}

.action-btn.enter {
  background-color: #1c1c1e;
}

.action-btn.enter:active {
  background-color: #000000;
}

.action-icon {
  width: 26rpx;
  height: 26rpx;
}

.action-text {
  font-size: 22rpx;
  font-weight: 600;
  color: #48484a;
}

.action-text.enter-text {
  color: #ffffff;
}

/* ===== 子节点缩进容器 ===== */
.children-wrapper {
  position: relative;
  padding-left: 40rpx;
}
</style>
