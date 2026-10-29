<template>
  <view class="chat-list-shell">
  <scroll-view
    class="chat-scroll-area"
    scroll-y
    :scroll-top="scrollTop"
    :scroll-into-view="scrollIntoViewId"
    :scroll-with-animation="scrollWithAnimation"
    @scrolltoupper="onReachTop"
    @scroll="onScroll"
  >
    <view class="chat-list-padding">
      <view
        v-if="renderSlice.hiddenCount > 0"
        class="window-expand-pill"
        @tap="expandRenderWindow"
      >
        <text class="window-expand-text">展开更早的 {{ renderSlice.hiddenCount }} 条已加载消息</text>
      </view>

      <template
        v-for="(message, offset) in visibleMessages"
        :key="message.clientId || message.id"
      >
        <view
          v-if="timeDividers[renderSlice.startIndex + offset]"
          class="time-divider"
        >
          <text class="time-divider-text">{{ timeDividers[renderSlice.startIndex + offset] }}</text>
        </view>
        <ChatBubble
          :id="message.clientId"
          :message="message"
          :avatar-url="avatarUrl"
          :character-name="characterName"
          :show-avatar="shouldShowAiIdentity(message, renderSlice.startIndex + offset)"
          :show-name="shouldShowAiIdentity(message, renderSlice.startIndex + offset)"
          :is-latest-assistant="renderSlice.startIndex + offset === latestAssistantIndex"
          :animate-entry="shouldAnimateMessageEntry(message.clientId)"
          @longpress-message="emit('longpress-message', $event)"
          @retry-failed="emit('retry-failed', $event)"
          @copy-message="emit('copy-message', $event)"
          @regenerate-message="emit('regenerate-message')"
        />
      </template>

      <view v-if="messages.length === 0" class="empty-chat">
        <view class="empty-chat-mark">
          <view class="empty-chat-ring"></view>
          <view class="empty-chat-spark"></view>
        </view>
        <text class="empty-chat-title">故事从一句话开始</text>
        <text class="empty-chat-text">写下你想说的，让角色回应这次相遇。</text>
      </view>
    </view>
  </scroll-view>

  <view
    v-if="showJumpButton"
    class="jump-to-bottom"
    :class="{ 'has-unread': hasUnread }"
    @tap="emit('jump-to-bottom')"
  >
    <text class="jump-arrow">↓</text>
    <text class="jump-text">{{ hasUnread ? "新回复" : "回到底部" }}</text>
  </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch, getCurrentInstance, onMounted } from "vue";
import ChatBubble from "./ChatBubble.vue";
import type { ChatMessage } from "@/store/chatStore";
import {
  INITIAL_RENDER_WINDOW,
  RENDER_WINDOW_STEP,
  computeRenderWindow,
  computeTimeDividers,
  findLatestAssistantIndex,
  shouldAnimateMessageEntry,
  type ScrollMetrics,
} from "@/utils/chatDisplay";

const props = withDefaults(defineProps<{
  messages: ChatMessage[];
  avatarUrl: string;
  characterName: string;
  scrollTop: number;
  scrollIntoViewId: string;
  scrollWithAnimation: boolean;
  showJumpButton?: boolean;
  hasUnread?: boolean;
  maintainScrollPosition?: (anchorId: string) => Promise<void>;
}>(), {
  showJumpButton: false,
  hasUnread: false,
  maintainScrollPosition: undefined,
});

const emit = defineEmits<{
  (event: "load-more"): void;
  (event: "longpress-message", message: ChatMessage): void;
  (event: "retry-failed", message: ChatMessage): void;
  (event: "copy-message", message: ChatMessage): void;
  (event: "regenerate-message"): void;
  (event: "scroll-metrics", metrics: ScrollMetrics): void;
  (event: "jump-to-bottom"): void;
}>();

const latestAssistantIndex = computed(() => findLatestAssistantIndex(props.messages));
const timeDividers = computed(() => computeTimeDividers(props.messages));

// 长会话仅挂载最近 N 条消息；向上触顶时优先展开本地已加载的旧消息，再向后端请求更早分页。
const renderWindowSize = ref(INITIAL_RENDER_WINDOW);
watch(
  () => props.messages.length,
  (nextLen, prevLen) => {
    if (nextLen === 0) {
      renderWindowSize.value = INITIAL_RENDER_WINDOW;
    } else if (prevLen > 0 && nextLen - prevLen > 1 && renderWindowSize.value >= prevLen) {
      // 后端分页追加历史时同步扩大挂载窗口，保证新拉取的更早消息可见。
      renderWindowSize.value += nextLen - prevLen;
    }
  }
);

const renderSlice = computed(() =>
  computeRenderWindow(props.messages.length, renderWindowSize.value)
);
const visibleMessages = computed(() =>
  props.messages.slice(renderSlice.value.startIndex)
);

const expandRenderWindow = () => {
  const anchorId = visibleMessages.value[0]?.clientId;
  renderWindowSize.value += RENDER_WINDOW_STEP;
  if (anchorId && props.maintainScrollPosition) {
    void props.maintainScrollPosition(anchorId);
  }
};

const onReachTop = () => {
  if (renderSlice.value.hiddenCount > 0) {
    expandRenderWindow();
    return;
  }
  emit("load-more");
};

// scroll 事件不携带可视高度；按需测量并缓存，键盘与窗口变化后会在后续滚动中刷新。
const instance = getCurrentInstance();
const VIEWPORT_MEASURE_INTERVAL = 500;
let viewportHeight = 0;
let lastMeasuredAt = 0;

const measureViewport = () => {
  lastMeasuredAt = Date.now();
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

const shouldShowAiIdentity = (message: ChatMessage, index: number) => {
  if (message.role !== "assistant") return false;
  if (index === 0 || index === renderSlice.value.startIndex) return true;
  if (timeDividers.value[index]) return true;
  return messagesAt(index - 1)?.role !== "assistant";
};

const messagesAt = (index: number) => props.messages[index];
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

.window-expand-pill {
  align-self: center;
  margin: 8rpx 0 18rpx;
  padding: 8rpx 24rpx;
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  border-radius: var(--app-radius-pill, 999rpx);
  background-color: var(--app-color-surface-soft, rgba(255, 255, 255, 0.78));
}

.window-expand-text {
  color: var(--app-color-text-secondary, #64716b);
  font-size: var(--app-font-size-caption, 22rpx);
  font-weight: 560;
}

.time-divider {
  display: flex;
  justify-content: center;
  padding: 20rpx 32rpx 10rpx;
}

.time-divider-text {
  padding: 4rpx 18rpx;
  border-radius: var(--app-radius-pill, 999rpx);
  background-color: var(--app-color-surface-soft, rgba(255, 255, 255, 0.56));
  color: var(--app-color-text-muted, #89958f);
  font-size: 20rpx;
  font-weight: 550;
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
</style>
