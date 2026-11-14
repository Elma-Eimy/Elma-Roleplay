<template>
  <view class="member-states">
    <view v-for="state in states" :key="state.persona_id" class="member-state">
      <view class="member-overview">
        <AvatarImage class="member-portrait" :src="memberImage(state)" />
        <view class="member-identity"><text class="member-title">{{ memberName(state.persona_id) }}</text><text class="member-mood">{{ state.current_mood || '心情未记录' }}</text></view>
      </view>
      <AffectionMeter :score="state.affection_score" :label="`对${userNickname || '你'}的好感`" />
      <button class="detail-toggle" :aria-expanded="!!expanded[state.persona_id]" @tap="expanded[state.persona_id] = !expanded[state.persona_id]">{{ expanded[state.persona_id] ? '收起详情' : '状态与关系' }} <text>{{ expanded[state.persona_id] ? '−' : '＋' }}</text></button>
      <view v-if="expanded[state.persona_id]" class="member-detail">
        <text v-if="state.role_state.scene" class="state-copy">场景：{{ state.role_state.scene }}</text>
        <view v-for="(actor, name) in state.role_state.characters" :key="name">
          <text class="state-copy">{{ name }}：{{ actorDescription(actor) }}</text>
        </view>
        <text class="state-label">入群时的认知</text>
        <text class="state-copy">{{ state.cognition_state === undefined ? '当前服务器未提供认知资料。' : state.cognition_state || '入群时尚无认知摘要。' }}</text>
        <text class="state-label">当前的认识与关系</text>
        <text v-if="state.insights === undefined" class="state-copy">当前服务器未提供成长资料。</text>
        <text v-else-if="!state.insights.length" class="state-copy">此候选暂无可用的新认识。</text>
        <view v-for="(insight, index) in state.insights" :key="index" class="insight">
          <text class="state-copy">{{ insightLabel(insight) }}</text>
          <text class="state-copy">{{ insight.content }}</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import AffectionMeter from "./AffectionMeter.vue";
import { ref } from "vue";
import type { GroupCandidateMemberState, GroupMemberInsight, GroupSessionMember } from "@/types/groupSessions";
import type { ActorState } from "@/types/roleState";
import AvatarImage from "@/components/common/AvatarImage.vue";
import { getAvatarUrl } from "@/api/characters";

const props = defineProps<{ states: GroupCandidateMemberState[]; members: GroupSessionMember[]; userNickname: string }>();
const expanded = ref<Record<number, boolean>>({});
const memberImage = (state: GroupCandidateMemberState) => getAvatarUrl(state.portrait?.image_path
  || props.members.find(member => member.persona_id === state.persona_id)?.character.avatar_path || '');
const memberName = (id: number) => {
  const member = props.members.find(row => row.persona_id === id);
  return member?.character.name || "未知成员";
};
const actorDescription = (actor: ActorState) => [actor.posture, actor.clothing, actor.location].filter(Boolean).join(" · ");
const insightLabel = (insight: GroupMemberInsight) => insight.kind === "cognition" ? "自己的认识"
  : insight.kind === "user" ? `对${props.userNickname}的看法`
    : `对${insight.target_persona_id === null ? insight.target_name || '其他成员' : memberName(insight.target_persona_id)}的看法`;
</script>

<style scoped>
.member-states { display: flex; flex-direction: column; gap: 20rpx; }
.member-state { padding: 24rpx; border: 1px solid var(--app-color-border); border-radius: 24rpx; background: var(--app-color-background); }
.member-overview { display: flex; align-items: center; gap: 20rpx; }
.member-identity { flex: 1; min-width: 0; }
.member-title { display: block; font-size: 28rpx; font-weight: 650; overflow-wrap: anywhere; }
.member-portrait { width: 80rpx; height: 80rpx; border-radius: 24rpx; flex-shrink: 0; }
.member-mood { display: block; margin-top: 6rpx; color: var(--app-color-text-secondary); font-size: 24rpx; }
.detail-toggle { display: flex; align-items: center; justify-content: space-between; min-height: 80rpx; margin: 0; padding: 12rpx 0 0; background: transparent; color: var(--app-color-primary-strong); font-size: 24rpx; line-height: 1.5; text-align: left; }
.detail-toggle::after { border: 0; }
.member-detail { padding-top: 10rpx; }
.state-label { display: block; margin-top: 20rpx; color: var(--app-color-primary-strong); font-size: 24rpx; font-weight: 600; }
.state-copy { display: block; margin-top: 10rpx; color: var(--app-color-text-secondary); font-size: 24rpx; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.insight { margin-top: 16rpx; padding-left: 20rpx; border-left: 2px solid var(--app-color-primary-soft); }
</style>
