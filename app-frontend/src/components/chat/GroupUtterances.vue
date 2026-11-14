<template>
  <view class="group-utterances">
    <ChatTranscriptMessage
      v-for="utterance in utterances" :key="utterance.item_id"
      :content="utterance.content"
      :name="`${utterance.speaker_name} · 成员 ${memberSlot(utterance.speaker_persona_id)}`"
      :avatar-url="memberAvatar(utterance.speaker_persona_id)"
    />
  </view>
</template>

<script setup lang="ts">
import ChatTranscriptMessage from "./ChatTranscriptMessage.vue";
import { getAvatarUrl } from "@/api/characters";
import type { GroupSessionMember, GroupUtterance, GroupMemberPortrait } from "@/types/groupSessions";

const props = defineProps<{ utterances: GroupUtterance[]; members: GroupSessionMember[]; portraits?: GroupMemberPortrait[] }>();
const memberSlot = (id: number) => props.members.find(member => member.persona_id === id)?.slot ?? "?";
const memberAvatar = (id: number) => getAvatarUrl(
  props.portraits?.find(row => row.persona_id === id)?.image_path
    || props.members.find(member => member.persona_id === id)?.character.avatar_path || "",
);
</script>
