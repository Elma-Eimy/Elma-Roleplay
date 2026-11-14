<template>
  <ChatBubble :message="message" :character-name="name" :avatar-url="avatarUrl" :show-name="!!name" :user-nickname="userNickname" read-only />
</template>

<script setup lang="ts">
import { computed } from "vue";
import ChatBubble from "./ChatBubble.vue";
import type { ChatMessage } from "@/store/chatStore";
const props = withDefaults(defineProps<{
  content: string; name?: string; avatarUrl?: string; isUser?: boolean; userNickname?: string;
}>(), { name: "", avatarUrl: "", isUser: false, userNickname: "" });
const message = computed<ChatMessage>(() => ({ id: 0, role: props.isUser ? "user" : "assistant",
  content: props.content, emotion_tag: null, affection_change: null, created_at: "", status: "done" }));
</script>
