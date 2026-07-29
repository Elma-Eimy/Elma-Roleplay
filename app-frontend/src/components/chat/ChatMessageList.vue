<template>
  <scroll-view
    class="chat-scroll-area"
    scroll-y
    :scroll-top="scrollTop"
    :scroll-into-view="scrollIntoViewId"
    :scroll-with-animation="scrollWithAnimation"
    @scrolltoupper="emit('load-more')"
  >
    <view class="chat-list-padding">
      <ChatBubble
        v-for="(message, index) in messages"
        :id="message.clientId"
        :key="message.clientId || message.id"
        :message="message"
        :avatar-url="avatarUrl"
        :character-name="characterName"
        :show-avatar="shouldShowAiIdentity(message, index)"
        :show-name="shouldShowAiIdentity(message, index)"
        @longpress-message="emit('longpress-message', $event)"
      />

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
</template>

<script setup lang="ts">
import ChatBubble from "./ChatBubble.vue";
import type { ChatMessage } from "@/store/chatStore";

const props = defineProps<{
  messages: ChatMessage[];
  avatarUrl: string;
  characterName: string;
  scrollTop: number;
  scrollIntoViewId: string;
  scrollWithAnimation: boolean;
}>();

const emit = defineEmits<{
  (event: "load-more"): void;
  (event: "longpress-message", message: ChatMessage): void;
}>();

const shouldShowAiIdentity = (message: ChatMessage, index: number) => {
  if (message.role !== "assistant") return false;
  if (index === 0) return true;
  return messagesAt(index - 1)?.role !== "assistant";
};

const messagesAt = (index: number) => props.messages[index];
</script>

<style scoped>
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
