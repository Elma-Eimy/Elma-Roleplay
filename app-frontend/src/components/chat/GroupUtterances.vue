<template>
  <view class="group-utterances">
    <view v-for="utterance in utterances" :key="utterance.item_id" class="utterance">
      <AvatarImage class="speaker-avatar" :src="memberAvatar(utterance.speaker_persona_id)" />
      <view class="utterance-body">
        <text class="speaker-name">{{ utterance.speaker_name }} · 成员 {{ memberSlot(utterance.speaker_persona_id) }}</text>
        <text class="utterance-content">{{ utterance.content }}</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import AvatarImage from "@/components/common/AvatarImage.vue";
import { getAvatarUrl } from "@/api/characters";
import type { GroupSessionMember, GroupUtterance, GroupMemberPortrait } from "@/types/groupSessions";

const props = defineProps<{ utterances: GroupUtterance[]; members: GroupSessionMember[]; portraits?: GroupMemberPortrait[] }>();
const memberSlot = (id: number) => props.members.find(member => member.persona_id === id)?.slot ?? "?";
const memberAvatar = (id: number) => getAvatarUrl(
  props.portraits?.find(row => row.persona_id === id)?.image_path
    || props.members.find(member => member.persona_id === id)?.character.avatar_path || "",
);
</script>

<style scoped>
.utterance { display: flex; align-items: flex-start; gap: 20rpx; margin-top: 28rpx; }
.speaker-avatar { flex: 0 0 64rpx; width: 64rpx; height: 64rpx; border-radius: var(--app-radius-sm); }
.utterance-body { flex: 1; min-width: 0; }
.speaker-name { display: block; color: var(--app-color-primary-strong); font-size: var(--app-font-size-caption); }
.utterance-content {
  display: block; margin-top: 10rpx; color: var(--app-color-text-primary);
  font-size: var(--app-font-size-body); line-height: 1.85; white-space: pre-wrap; overflow-wrap: anywhere;
}
</style>
