<template>
  <view class="group-page">
    <AppPageHeader title="群聊详情" eyebrow="GROUP STORY" subtitle="查看这次相遇的共同起点" show-back />
    <scroll-view class="group-scroll" scroll-y>
      <view class="group-content">
        <AppStatusState v-if="loading && !group" kind="loading" title="正在读取群聊" />
        <AppStatusState v-else-if="!group" kind="error" title="暂时无法查看群聊" :description="error || '请返回列表重新选择群聊。'" :action-label="needsSelection ? '返回群聊列表' : '重新加载'" @action="retry" />
        <template v-else>
          <view class="group-card">
            <text class="group-caption">{{ group.members.length }} 名角色 · 你的昵称：{{ group.user_nickname }}</text>
            <text class="group-heading">{{ group.title }}</text>
            <text class="group-label">共同设定</text>
            <text class="group-copy">{{ group.shared_setting || '未填写共同设定，角色保留各自的角色卡设定。' }}</text>
          </view>
          <view class="group-notice"><text class="group-copy">群聊已建立。目前仅支持查看起点与成员状态，角色互动将在后续开放。</text></view>
          <view v-for="member in group.members" :key="member.persona_id" class="group-card">
            <view class="group-row"><AvatarImage class="group-avatar" :src="getAvatarUrl(member.character.avatar_path || '')" /><view class="member-name"><text class="group-heading">{{ member.character.name }}</text><text class="group-caption">成员 {{ member.slot }}</text></view></view>
            <text class="group-label">{{ member.origin.mode === 'card' ? '从原卡开始' : '导入单聊快照' }}</text>
            <text class="group-copy">{{ member.origin.mode === 'card' ? '没有导入单聊状态与私人记忆。' : `来源故事 #${member.origin.source_session_id} · 已导入 ${member.origin.inherited_memory_count} 张记忆卡` }}</text>
            <text v-if="member.origin.mode === 'single_snapshot'" class="group-copy">导入时间：{{ formatTime(member.origin.captured_at) }}。来源故事之后的变化不会回写到此起点。</text>
            <text class="group-copy">好感度：{{ member.state.affection_score ?? '未记录' }}　心情：{{ member.state.current_mood || '未记录' }}</text>
            <text v-if="member.state.role_state.scene || member.state.current_scenario_override" class="group-copy">场景：{{ member.state.role_state.scene || member.state.current_scenario_override }}</text>
            <text class="group-label">认知</text><text class="group-copy">{{ member.state.cognition_state || '尚未建立认知摘要。' }}</text>
            <view v-for="(actor, name) in member.state.role_state.characters" :key="name" class="group-copy"><text>{{ name }}：{{ actorDescription(actor) }}</text></view>
          </view>
          <text v-if="error" class="group-error" role="alert">{{ error }}</text>
          <view class="group-action" role="button" :aria-disabled="loading || deleting" @tap="state.load">{{ loading ? '正在刷新…' : '刷新详情' }}</view>
          <view class="group-action group-danger" role="button" :aria-disabled="deleting || loading" @tap="remove">{{ deleting ? '正在处理…' : '删除整个群聊' }}</view>
        </template>
      </view>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { onLoad, onShow, onHide, onUnload } from "@dcloudio/uni-app";
import AppPageHeader from "@/components/common/AppPageHeader.vue";
import AppStatusState from "@/components/common/AppStatusState.vue";
import AvatarImage from "@/components/common/AvatarImage.vue";
import { getAvatarUrl } from "@/api/characters";
import { useGroupSessionDetail } from "@/composables/useGroupSessions";
import type { ActorState } from "@/types/roleState";

const backToList = () => uni.navigateBack({ fail: () => uni.redirectTo({ url: "/pages/group/index" }) });
const state = useGroupSessionDetail(backToList);
const { group, loading, deleting, error, needsSelection } = state;
onLoad(options => state.setSessionId(Number(options?.sessionId)));
onShow(state.show); onHide(state.hide); onUnload(state.hide);
const formatTime = (value: string) => value.replace("T", " ").slice(0, 19);
const actorDescription = (actor: ActorState) => [actor.posture, actor.clothing, actor.location].filter(Boolean).join(" · ");
const retry = () => { if (needsSelection.value) backToList(); else void state.load(); };
const remove = () => state.remove(() => new Promise<boolean>(resolve => uni.showModal({
  title: "删除整个群聊？", content: "全部成员与本群数据将被删除，来源单聊和角色卡会保留。此操作无法撤销。",
  confirmText: "删除群聊", confirmColor: "#d9655d", success: result => resolve(result.confirm), fail: () => resolve(false),
})));
</script>

<style scoped>
@import "./group.css";
.member-name { flex: 1; min-width: 0; }
</style>
