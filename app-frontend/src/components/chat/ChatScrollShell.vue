<template>
  <view class="chat-list-shell">
    <scroll-view
      class="chat-scroll-area"
      scroll-y
      :scroll-top="scrollTop"
      :scroll-into-view="scrollIntoViewId"
      :scroll-with-animation="scrollWithAnimation"
      @scrolltoupper="emit('reach-top')"
      @scroll="onScroll"
    >
      <view class="chat-list-padding">
        <slot />
        <slot v-if="isEmpty" name="empty">
          <view class="empty-chat">
            <view class="empty-chat-mark">
              <view class="empty-chat-ring"></view>
              <view class="empty-chat-spark"></view>
            </view>
            <text class="empty-chat-title">{{ emptyTitle }}</text>
            <text class="empty-chat-text">{{ emptyDescription }}</text>
          </view>
        </slot>
      </view>
    </scroll-view>

    <view
      v-if="showJumpButton"
      class="jump-to-bottom"
      :class="{ 'has-unread': hasUnread }"
      @tap="emit('jump-to-bottom')"
    >
      <text class="jump-arrow">↓</text>
      <text class="jump-text">{{ hasUnread ? unreadLabel : jumpLabel }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { getCurrentInstance, onMounted } from "vue";
import type { ScrollMetrics } from "@/utils/chatDisplay";

withDefaults(defineProps<{
  scrollTop: number;
  scrollIntoViewId: string;
  scrollWithAnimation: boolean;
  showJumpButton?: boolean;
  hasUnread?: boolean;
  jumpLabel?: string;
  unreadLabel?: string;
  isEmpty?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
}>(), {
  showJumpButton: false,
  hasUnread: false,
  jumpLabel: "回到底部",
  unreadLabel: "新回复",
  isEmpty: false,
  emptyTitle: "故事从一句话开始",
  emptyDescription: "写下你想说的，让角色回应这次相遇。",
});

const emit = defineEmits<{
  (event: "reach-top"): void;
  (event: "scroll-metrics", metrics: ScrollMetrics): void;
  (event: "jump-to-bottom"): void;
}>();

// scroll 事件不携带可视高度；按需测量并缓存，键盘与窗口变化后会在后续滚动中刷新。
const instance = getCurrentInstance();
const VIEWPORT_MEASURE_INTERVAL = 500;
let viewportHeight = 0;
let lastMeasuredAt = 0;

const measureViewport = () => {
  lastMeasuredAt = Date.now();
  if (typeof uni === "undefined" || typeof uni.createSelectorQuery !== "function") return;
  const query = uni.createSelectorQuery();
  if (instance?.proxy) query.in(instance.proxy);
  query
    .select(".chat-scroll-area")
    .boundingClientRect((rect) => {
      const node = (Array.isArray(rect) ? rect[0] : rect) as UniApp.NodeInfo | null;
      if (node?.height) viewportHeight = node.height;
    })
    .exec();
};

onMounted(measureViewport);

const onScroll = (event: Event) => {
  const detail = (event as unknown as { detail?: { scrollTop?: number; scrollHeight?: number } }).detail;
  if (!detail || typeof detail.scrollTop !== "number" || typeof detail.scrollHeight !== "number") return;
  if (Date.now() - lastMeasuredAt > VIEWPORT_MEASURE_INTERVAL) measureViewport();
  emit("scroll-metrics", {
    scrollTop: detail.scrollTop,
    scrollHeight: detail.scrollHeight,
    viewportHeight,
  });
};

defineExpose({ measureViewport });
</script>

<style scoped>
.chat-list-shell {
  position: relative;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  width: 100%;
}

.chat-scroll-area {
  flex: 1;
  width: 100%;
  height: 0;
  min-height: 0;
  overflow: hidden;
  position: relative;
  z-index: 1;
  background-color: transparent !important;
}

.chat-list-padding {
  padding: 28rpx 0 34rpx;
  display: flex;
  flex-direction: column;
  min-height: 100%;
}

.empty-chat {
  flex: 1;
  display: flex;
  padding: 120rpx var(--app-page-gutter, 36rpx);
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}

.empty-chat-mark {
  position: relative;
  width: 112rpx;
  height: 112rpx;
  margin-bottom: 28rpx;
}

.empty-chat-ring {
  position: absolute;
  inset: 10rpx;
  border: 2rpx solid var(--app-color-border-strong, rgba(38, 51, 46, 0.14));
  border-radius: 44% 56% 52% 48%;
  background-color: rgba(255, 255, 255, 0.56);
  box-shadow: var(--app-shadow-soft, 0 12rpx 36rpx rgba(45, 72, 62, 0.08));
  transform: rotate(12deg);
}

.empty-chat-spark {
  position: absolute;
  top: 0;
  right: 4rpx;
  width: 30rpx;
  height: 30rpx;
  border: 8rpx solid var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
  border-radius: 50%;
  background-color: var(--app-color-primary, #70ae9b);
}

.empty-chat-title {
  color: var(--app-color-text-primary, #26332e);
  font-size: var(--app-font-size-title-sm, 32rpx);
  font-weight: 680;
}

.empty-chat-text {
  max-width: 480rpx;
  margin-top: 12rpx;
  color: var(--app-color-text-secondary, #7c8983);
  font-size: var(--app-font-size-body-sm, 24rpx);
  line-height: 1.6;
}

.jump-to-bottom {
  position: absolute;
  left: 50%;
  bottom: 16rpx;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 8rpx;
  min-height: 56rpx;
  padding: 0 24rpx;
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  border-radius: var(--app-radius-pill, 999rpx);
  background-color: var(--app-color-surface-translucent, rgba(255, 255, 255, 0.88));
  box-shadow: var(--app-shadow-soft, 0 12rpx 36rpx rgba(45, 72, 62, 0.08));
  transform: translateX(-50%);
  animation: jump-fade-in var(--app-motion-normal, 240ms) ease both;
}

.jump-to-bottom:active {
  transform: translateX(-50%) scale(0.95);
}

.jump-to-bottom.has-unread {
  border-color: rgba(112, 174, 155, 0.3);
  background-color: var(--app-color-primary, #70ae9b);
}

.jump-arrow,
.jump-text {
  color: var(--app-color-text-secondary, #64716b);
  font-size: var(--app-font-size-body-sm, 24rpx);
  font-weight: 600;
}

.has-unread .jump-arrow,
.has-unread .jump-text {
  color: #ffffff;
}

@keyframes jump-fade-in {
  from { opacity: 0; transform: translate(-50%, 12rpx); }
  to { opacity: 1; transform: translate(-50%, 0); }
}
</style>
