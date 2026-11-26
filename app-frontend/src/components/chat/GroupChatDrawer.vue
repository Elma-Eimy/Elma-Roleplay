<template>
  <ChatDrawer
    :is-open="isOpen"
    :session-id="group.session_id"
    :background-mode="backgroundMode"
    :profile="drawerProfile"
    :hide-delete="hideDelete"
    @close="emit('close')"
    @update:background-mode="emit('update:background-mode', $event)"
    @delete-session="emit('delete-session')"
    @open-prompt-preview="emit('open-prompt-preview', member.persona_id)"
    @open-memory-view="emit('open-memory-view', member.persona_id)"
  >
    <template #top>
      <view class="panel-section">
        <text class="section-title">群聊成员</text>
        <view class="member-chips">
          <view
            v-for="item in group.members"
            :key="item.persona_id"
            class="member-chip"
            :class="{ 'is-active': member.persona_id === item.persona_id }"
            role="button"
            @tap="emit('select-member', item.persona_id)"
          >
            <AvatarImage class="member-chip-avatar" :src="getAvatarUrl(item.character.avatar_path || '')" />
            <text class="member-chip-name">{{ item.character.name }}</text>
          </view>
        </view>
        <text class="member-picker-hint">切换成员，查看各自的状态、立绘与记忆。</text>
      </view>
    </template>

    <template #role-state>
      <view class="panel-section">
        <text v-if="loadingAdoptedState" class="drawer-inline-hint">正在同步成员状态…</text>
        <text v-if="adoptedStateError" class="drawer-inline-error">{{ adoptedStateError }}</text>
        <RoleStatePanel
          v-if="hasAdoptedStateView"
          :session-id="null"
          :readonly-state="memberState.role_state"
          :processing="operationBusy"
        />
        <text v-else class="drawer-inline-hint">
          {{ operationBusy ? '正在生成，完成后同步当前状态。' : '状态尚未同步，请刷新后查看。' }}
        </text>
        <view
          class="action-btn outline"
          :class="{ 'is-disabled': loadingAdoptedState || operationBusy }"
          role="button"
          @tap="!(loadingAdoptedState || operationBusy) && emit('refresh-state')"
        >
          <image class="btn-icon" src="/static/icons/drawer_sync.svg" mode="aspectFit" />
          <text class="btn-text">刷新状态</text>
        </view>
      </view>
    </template>

    <template #portraits>
      <view class="panel-section">
        <GroupPortraitPicker
          :member="member"
          :portrait-data="portraitData"
          :portrait-options="portraitOptions"
          :loading-portraits="loadingPortraits"
          :portrait-writing="portraitWriting"
          :portrait-error="portraitError"
          :can-choose-portrait="canChoosePortrait"
          :disabled="operationBusy"
          @choose="(personaId, portraitId) => emit('choose-portrait', personaId, portraitId)"
          @load-options="(personaId, append) => emit('load-portrait-options', personaId, append)"
          @refresh="emit('refresh-portraits')"
        />
      </view>
    </template>

    <template #after-cognition>
      <view v-if="memberState.insights?.length" class="panel-section">
        <text class="section-title">认识与关系</text>
        <view v-for="(insight, index) in memberState.insights" :key="index" class="insight-item">
          <text class="insight-text">{{ insight.content }}</text>
        </view>
      </view>
    </template>

    <template #extra-tools>
      <view class="panel-section">
        <text class="section-title">共同设定</text>
        <text class="drawer-body-copy">{{ group.shared_setting || '未填写共同设定。' }}</text>
        <text class="drawer-meta-copy">你的名字：{{ group.user_nickname }}</text>
      </view>

      <view class="panel-section">
        <text class="section-title">成员起点</text>
        <text class="drawer-body-copy">
          {{ member.origin.mode === 'card' ? '从原卡开始' : `导入单聊快照 · ${member.origin.inherited_memory_count} 张记忆卡` }}
        </text>
        <text class="drawer-meta-copy">
          起点好感：{{ member.state.affection_score ?? '未记录' }} · 起点心情：{{ member.state.current_mood || '未记录' }}
        </text>
      </view>

      <view class="panel-section">
        <text class="section-title">群聊管理</text>
        <view
          class="action-btn outline"
          :class="{ 'is-disabled': loadingGroup || deleting }"
          role="button"
          @tap="!(loadingGroup || deleting) && emit('refresh-group')"
        >
          <image class="btn-icon" src="/static/icons/drawer_sync.svg" mode="aspectFit" />
          <text class="btn-text">刷新群聊资料</text>
        </view>
        <text v-if="groupError" class="drawer-inline-error">{{ groupError }}</text>
      </view>
    </template>
  </ChatDrawer>
</template>

<script setup lang="ts">
import { computed } from "vue";
import AvatarImage from "@/components/common/AvatarImage.vue";
import { getAvatarUrl } from "@/api/characters";
import type { GroupPortraitsResponse, GroupSessionDetail, GroupSessionMember } from "@/types/groupSessions";
import type { RoleState } from "@/types/roleState";
import ChatDrawer, { type ChatDrawerProfile } from "./ChatDrawer.vue";
import RoleStatePanel from "./RoleStatePanel.vue";
import GroupPortraitPicker, { type GroupPortraitOptionBucket } from "./GroupPortraitPicker.vue";

export interface GroupDrawerMemberState {
  affection_score?: number | null;
  current_mood?: string | null;
  cognition_state?: string | null;
  role_state: RoleState;
  insights?: { content: string }[];
}

const props = defineProps<{
  isOpen: boolean;
  group: GroupSessionDetail;
  member: GroupSessionMember;
  memberState: GroupDrawerMemberState;
  hasAdoptedStateView: boolean;
  backgroundMode: "clean" | "character";
  hideDelete?: boolean;
  operationBusy: boolean;
  loadingAdoptedState: boolean;
  adoptedStateError: string;
  portraitData: GroupPortraitsResponse | null;
  portraitOptions: Record<number, GroupPortraitOptionBucket>;
  loadingPortraits: boolean;
  portraitWriting: boolean;
  portraitError: string;
  canChoosePortrait: boolean;
  loadingGroup: boolean;
  deleting: boolean;
  groupError: string;
}>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "update:background-mode", mode: "clean" | "character"): void;
  (e: "delete-session"): void;
  (e: "select-member", personaId: number): void;
  (e: "open-prompt-preview", personaId: number): void;
  (e: "open-memory-view", personaId: number): void;
  (e: "refresh-state"): void;
  (e: "refresh-group"): void;
  (e: "choose-portrait", personaId: number, portraitId: number | null): void;
  (e: "load-portrait-options", personaId: number, append: boolean): void;
  (e: "refresh-portraits"): void;
}>();

const drawerProfile = computed<ChatDrawerProfile>(() => ({
  name: props.member.character.name,
  character: props.member.character,
  affection: props.hasAdoptedStateView ? props.memberState.affection_score ?? 0 : null,
  mood: props.memberState.current_mood ?? null,
  cognition: props.memberState.cognition_state ?? null,
}));
</script>

<style scoped>
@import "./chatDrawer.css";

.member-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
}

.member-chip {
  display: inline-flex;
  align-items: center;
  gap: 10rpx;
  padding: 8rpx 18rpx 8rpx 10rpx;
  border-radius: 999rpx;
  border: 1px solid rgba(38, 51, 46, 0.08);
  background: rgba(0, 0, 0, 0.025);
  color: #46544e;
  transition: background-color 0.16s ease, border-color 0.16s ease;
}

.member-chip.is-active {
  background: rgba(112, 174, 155, 0.16);
  border-color: rgba(79, 142, 124, 0.45);
  color: #2f6355;
}

.member-chip-avatar {
  width: 40rpx;
  height: 40rpx;
  border-radius: 50%;
  flex-shrink: 0;
}

.member-chip-name {
  font-size: 23rpx;
  font-weight: 600;
}

.member-picker-hint,
.drawer-meta-copy,
.drawer-inline-hint {
  font-size: 22rpx;
  line-height: 1.5;
  color: #7c8983;
}

.drawer-body-copy {
  font-size: 24rpx;
  line-height: 1.65;
  color: #3a3a3c;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.drawer-inline-error {
  font-size: 23rpx;
  line-height: 1.5;
  color: #d9655d;
  overflow-wrap: anywhere;
}

.insight-item {
  padding: 12rpx 16rpx;
  border-left: 4rpx solid rgba(112, 174, 155, 0.45);
  background: rgba(0, 0, 0, 0.02);
  border-radius: 0 12rpx 12rpx 0;
}

.insight-text {
  font-size: 24rpx;
  line-height: 1.6;
  color: #3a3a3c;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.action-btn.is-disabled {
  opacity: 0.45;
  pointer-events: none;
}
</style>
