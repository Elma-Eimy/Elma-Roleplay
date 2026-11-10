<template>
  <view class="chat-bubble-wrapper" :class="{ 'is-user': isUser }">
    <AvatarImage v-if="!isUser" class="avatar" :src="avatarUrl" />
    <view class="bubble-content-area">
      <text v-if="!isUser && name" class="name-tag">{{ name }}</text>
      <view class="bubble" :class="isUser ? 'user-bubble' : 'ai-bubble'">
        <text v-if="isUser" class="plain-text">{{ content }}</text>
        <rich-text v-else class="markdown-content" :nodes="renderedContent" />
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from "vue";
import AvatarImage from "@/components/common/AvatarImage.vue";
import { renderChatMarkdown } from "@/utils/markdown";

const props = withDefaults(defineProps<{
  content: string;
  name?: string;
  avatarUrl?: string;
  isUser?: boolean;
}>(), { name: "", avatarUrl: "", isUser: false });
const renderedContent = computed(() => renderChatMarkdown(props.content));
</script>

<style scoped>
@import "./chatMessage.css";
.chat-bubble-wrapper { box-sizing: border-box; }
.plain-text { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
