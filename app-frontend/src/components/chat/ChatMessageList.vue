<template>
  <ChatScrollShell
    :scroll-top="scrollTop"
    :scroll-into-view-id="scrollIntoViewId"
    :scroll-with-animation="scrollWithAnimation"
    :show-jump-button="showJumpButton"
    :has-unread="hasUnread"
    :is-empty="messages.length === 0"
    @reach-top="onReachTop"
    @scroll-metrics="emit('scroll-metrics', $event)"
    @jump-to-bottom="emit('jump-to-bottom')"
  >
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
        :user-nickname="userNickname"
        :is-busy="isBusy"
        :is-playing-audio="activeAudioMessageId === message.id"
        :show-avatar="shouldShowAiIdentity(message, renderSlice.startIndex + offset)"
        :show-name="shouldShowAiIdentity(message, renderSlice.startIndex + offset)"
        :is-latest-assistant="renderSlice.startIndex + offset === latestAssistantIndex"
        :animate-entry="shouldAnimateMessageEntry(message.clientId)"
        @longpress-message="emit('longpress-message', message)"
        @retry-failed="emit('retry-failed', message)"
        @copy-message="emit('copy-message', message)"
        @regenerate-message="emit('regenerate-message')"
        @play-tts="emit('play-tts', message)"
        @switch-candidate="emit('switch-candidate', $event)"
      />
    </template>
  </ChatScrollShell>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import ChatBubble from "./ChatBubble.vue";
import ChatScrollShell from "./ChatScrollShell.vue";
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
  userNickname?: string;
  isBusy?: boolean;
  activeAudioMessageId?: number | null;
  scrollTop: number;
  scrollIntoViewId: string;
  scrollWithAnimation: boolean;
  showJumpButton?: boolean;
  hasUnread?: boolean;
  maintainScrollPosition?: (anchorId: string) => Promise<void>;
}>(), {
  userNickname: "",
  isBusy: false,
  activeAudioMessageId: null,
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
  (event: "play-tts", message: ChatMessage): void;
  (event: "switch-candidate", payload: { messageId: number; candidateId: number }): void;
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

const shouldShowAiIdentity = (message: ChatMessage, index: number) => {
  if (message.role !== "assistant") return false;
  if (index === 0 || index === renderSlice.value.startIndex) return true;
  if (timeDividers.value[index]) return true;
  return messagesAt(index - 1)?.role !== "assistant";
};

const messagesAt = (index: number) => props.messages[index];
</script>

<style scoped>
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
</style>
