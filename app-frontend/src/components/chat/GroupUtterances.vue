<template>
  <view class="group-utterances">
    <ChatBubble
      v-for="utterance in utterances"
      :key="utterance.item_id"
      :message="{ role: 'assistant', content: utterance.content, status: 'done' }"
      :character-name="`${utterance.speaker_name} · 成员 ${memberSlot(utterance.speaker_persona_id)}`"
      :avatar-url="memberAvatar(utterance.speaker_persona_id)"
      :user-nickname="userNickname"
      show-name
      read-only
    />
  </view>
</template>

<script setup lang="ts">
import ChatBubble from "./ChatBubble.vue";
import { getAvatarUrl } from "@/api/characters";
import type { GroupSessionMember, GroupUtterance, GroupMemberPortrait } from "@/types/groupSessions";

const props = withDefaults(defineProps<{
  utterances: GroupUtterance[];
  members: GroupSessionMember[];
  portraits?: GroupMemberPortrait[];
  userNickname?: string;
}>(), {
  portraits: undefined,
  userNickname: "",
});

const memberSlot = (id: number) => props.members.find(member => member.persona_id === id)?.slot ?? "?";
const memberAvatar = (id: number) => getAvatarUrl(
  props.portraits?.find(row => row.persona_id === id)?.image_path
    || props.members.find(member => member.persona_id === id)?.character.avatar_path || "",
);
</script>
