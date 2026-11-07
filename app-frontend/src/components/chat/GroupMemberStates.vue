<template>
  <view class="member-states">
    <view v-for="state in states" :key="state.persona_id" class="member-state">
      <text class="member-title">{{ memberName(state.persona_id) }}</text>
      <text class="state-copy">好感度 {{ state.affection_score }} · 心情 {{ state.current_mood || '未记录' }}</text>
      <text v-if="state.role_state.scene" class="state-copy">场景：{{ state.role_state.scene }}</text>
      <view v-for="(actor, name) in state.role_state.characters" :key="name">
        <text class="state-copy">{{ name }}：{{ actorDescription(actor) }}</text>
      </view>
      <text class="state-label">继承的认知起点</text>
      <text class="state-copy">{{ state.cognition_state === undefined ? '当前服务器未提供认知资料。' : state.cognition_state || '入群时尚无认知摘要。' }}</text>
      <text class="state-label">本候选可用的认识与关系</text>
      <text v-if="state.insights === undefined" class="state-copy">当前服务器未提供成长资料。</text>
      <text v-else-if="!state.insights.length" class="state-copy">此候选暂无可用的新认识。</text>
      <view v-for="(insight, index) in state.insights" :key="index" class="insight">
        <text class="state-copy">{{ insightLabel(insight) }}</text>
        <text class="state-copy">{{ insight.content }}</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import type { GroupCandidateMemberState, GroupMemberInsight, GroupSessionMember } from "@/types/groupSessions";
import type { ActorState } from "@/types/roleState";

const props = defineProps<{ states: GroupCandidateMemberState[]; members: GroupSessionMember[]; userNickname: string }>();
const memberName = (id: number) => {
  const member = props.members.find(row => row.persona_id === id);
  return member ? `${member.character.name} · 成员 ${member.slot}` : "未知成员";
};
const actorDescription = (actor: ActorState) => [actor.posture, actor.clothing, actor.location].filter(Boolean).join(" · ");
const insightLabel = (insight: GroupMemberInsight) => insight.kind === "cognition" ? "自己的认识"
  : insight.kind === "user" ? `对${props.userNickname}的看法`
    : `对${insight.target_persona_id === null ? insight.target_name || '其他成员' : memberName(insight.target_persona_id)}的看法`;
</script>

<style scoped>
.member-state { margin-top: 24rpx; padding-top: 24rpx; border-top: 1px solid var(--app-color-border); }
.member-title { display: block; font-size: var(--app-font-size-body); font-weight: 600; }
.state-label { display: block; margin-top: 20rpx; color: var(--app-color-primary-strong); font-size: var(--app-font-size-caption); }
.state-copy { display: block; margin-top: 10rpx; color: var(--app-color-text-secondary); font-size: var(--app-font-size-body-sm); line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.insight { margin-top: 16rpx; padding-left: 20rpx; border-left: 2px solid var(--app-color-primary-soft); }
</style>
