<template>
  <view class="group-page">
    <AppPageHeader title="群聊详情" eyebrow="GROUP STORY" subtitle="共同起点、当前剧情与整轮候选" show-back />
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
          <view class="group-notice"><text class="group-copy">发送下一条消息时，会确认当前采用的完整候选。生成期间可以离开页面，返回后会查询已保存进展。</text></view>
          <view v-for="member in group.members" :key="member.persona_id" class="group-card">
            <view class="group-row"><AvatarImage class="group-avatar" :src="getAvatarUrl(member.character.avatar_path || '')" /><view class="member-name"><text class="group-heading">{{ member.character.name }}</text><text class="group-caption">成员 {{ member.slot }}</text></view></view>
            <text class="group-label">{{ member.origin.mode === 'card' ? '从原卡开始' : '导入单聊快照' }}</text>
            <text class="group-copy">{{ member.origin.mode === 'card' ? '没有导入单聊状态与私人记忆。' : `来源故事 #${member.origin.source_session_id} · 已导入 ${member.origin.inherited_memory_count} 张记忆卡` }}</text>
            <text v-if="member.origin.mode === 'single_snapshot'" class="group-copy">导入时间：{{ formatTime(member.origin.captured_at) }}。来源故事之后的变化不会回写到此起点。</text>
            <text class="group-copy">起点好感度：{{ member.state.affection_score ?? '未记录' }}　起点心情：{{ member.state.current_mood || '未记录' }}</text>
            <text v-if="member.state.role_state.scene || member.state.current_scenario_override" class="group-copy">场景：{{ member.state.role_state.scene || member.state.current_scenario_override }}</text>
            <text class="group-label">认知</text><text class="group-copy">{{ member.state.cognition_state || '尚未建立认知摘要。' }}</text>
            <view v-for="(actor, name) in member.state.role_state.characters" :key="name" class="group-copy"><text>{{ name }}：{{ actorDescription(actor) }}</text></view>
          </view>
          <view class="group-card">
            <view class="group-row"><text class="group-heading">当前采用的发言</text><view class="group-action" role="button" :aria-disabled="loading || loadingRounds || deleting || operationBusy" @tap="refreshRounds">刷新</view></view>
            <text class="group-copy">按最近轮次展示，每轮内按发言先后排列。</text>
            <AppStatusState v-if="loadingRounds && !rounds.length" kind="loading" title="正在读取发言" />
            <AppStatusState v-else-if="!rounds.length && !roundsError" kind="empty" title="还没有已保存发言" description="可以输入第一条消息，开始这次相遇。" />
            <view v-for="round in rounds" :key="round.round_id" class="saved-round">
              <text class="group-label">第 {{ round.round_index }} 轮 · {{ roundStatus(round) }}</text>
              <text class="group-caption">{{ group.user_nickname }}</text><text class="group-copy">{{ round.user_content }}</text>
              <view v-for="utterance in round.utterances" :key="utterance.item_id" class="saved-utterance">
                <text class="group-caption">{{ utterance.speaker_name }} · {{ memberLabel(utterance.speaker_persona_id) }}</text>
                <text class="group-copy">{{ utterance.content }}</text>
              </view>
              <text v-if="groupRoundNotice(round)" :class="round.status === 'failed' ? 'group-error' : 'group-copy'">{{ groupRoundNotice(round) }}</text>
              <button role="button" v-if="current" class="group-action" :disabled="submitting || deleting || loading" @tap="state.loadCandidates(round.round_id)">查看整轮候选</button>
            </view>
            <text v-if="roundsError" class="group-error" role="alert">{{ roundsError }}</text>
            <view v-if="roundsError" class="group-action" role="button" :aria-disabled="loading || loadingRounds || deleting" @tap="retryRounds">重新读取发言</view>
            <view v-else-if="hasMoreRounds" class="group-action" role="button" :aria-disabled="loading || loadingRounds || deleting" @tap="moreRounds">{{ loadingRounds ? '正在读取…' : '加载更早轮次' }}</view>
          </view>
          <view v-if="candidateRoundId" class="group-card">
            <view class="group-row"><text class="group-heading">整轮候选</text><button role="button" class="group-action" :disabled="submitting || loadingCandidates || deleting" @tap="state.loadCandidates(candidateRoundId)">刷新候选</button></view>
            <text class="group-copy">查看候选不会改变采用内容。只有完整候选才能切换采用；失败前缀可查看或显式继续。</text>
            <text v-if="loadingCandidates" class="group-copy">正在读取候选…</text>
            <view v-for="candidate in candidates" :key="candidate.candidate_id" class="candidate-row">
              <text class="group-copy">候选 {{ candidate.version }} · {{ candidateStatus(candidate.status) }}{{ isSelected(candidate.candidate_id) ? ' · 当前采用' : '' }}</text>
              <view class="candidate-actions">
                <button role="button" class="group-action" :disabled="submitting || deleting" @tap="state.viewCandidate(candidateRoundId, candidate.candidate_id)">查看正文与状态</button>
                <button role="button" v-if="candidate.can_select && !isSelected(candidate.candidate_id)" class="group-action" :disabled="locked || loadingCandidates || !!candidatesError" @tap="state.command('select', candidate)">采用此候选</button>
                <button role="button" v-if="candidate.can_resume" class="group-action" :disabled="locked || !canGenerate || loadingCandidates || !!candidatesError" @tap="state.command('resume', candidate, confirmResume)">继续此候选</button>
              </view>
            </view>
            <text v-if="candidatesError" class="group-error" role="alert">{{ candidatesError }}</text>
            <button role="button" v-if="hasMoreCandidates" class="group-action" :disabled="loadingCandidates || submitting || deleting" @tap="state.loadCandidates(candidateRoundId, true)">加载更早候选</button>
            <text v-if="loadingPreview" class="group-copy">正在读取候选正文…</text>
            <text v-if="previewError" class="group-error" role="alert">{{ previewError }}，可再次点击查看。</text>
            <view v-if="preview" class="candidate-preview">
              <text class="group-label">候选 {{ preview.candidate.version }} · {{ isSelected(preview.candidate.candidate_id) ? '当前采用' : '仅预览，未采用' }}</text>
              <text class="group-copy">{{ preview.round.user_content }}</text>
              <view v-for="utterance in preview.utterances" :key="utterance.item_id" class="saved-utterance">
                <text class="group-caption">{{ utterance.speaker_name }} · {{ memberLabel(utterance.speaker_persona_id) }}</text>
                <text class="group-copy">{{ utterance.content }}</text>
              </view>
              <text v-if="preview.candidate.status === 'failed'" class="group-error">此候选未完成，以上仅为已保存前缀，不会作为完整结果确认。</text>
              <text v-else-if="!preview.utterances.length" class="group-copy">此候选尚无角色发言。</text>
              <text class="group-label">此候选的状态预览</text>
              <view v-for="member in preview.state_preview.members" :key="member.persona_id">
                <text class="group-copy">{{ memberLabel(member.persona_id) }} · 好感度 {{ member.affection_score }} · 心情 {{ member.current_mood || '未记录' }}</text>
                <text v-if="member.role_state.scene" class="group-copy">场景：{{ member.role_state.scene }}</text>
                <view v-for="(actor, name) in member.role_state.characters" :key="name" class="group-copy"><text>{{ name }}：{{ actorDescription(actor) }}</text></view>
              </view>
            </view>
          </view>
          <view class="group-card">
            <text class="group-heading">继续剧情</text>
            <text v-if="!current || !canGenerate" class="group-copy">{{ !current ? '当前仅可阅读。请刷新发言，或连接支持群聊操作的后端。' : '生成服务暂不可用，已有内容仍可阅读。' }}</text>
            <text v-if="pending || current?.active_operation" class="group-copy">{{ submitting ? '正在提交…' : recovering ? '正在查询进展…' : '已有请求正在处理或结果待确认，请先查询。' }}</text>
            <text v-if="notice" class="group-copy" role="status">{{ notice }}</text>
            <text v-if="operationError" class="group-error" role="alert">{{ operationError }}</text>
            <text v-if="historyStale" class="group-copy" role="status">剧情已有更新，请刷新当前采用的发言后再操作。</text>
            <button role="button" v-if="pending || current?.active_operation" class="group-action" :disabled="recovering || submitting || loading" @tap="state.recover">查询请求结果</button>
            <textarea v-model="draft" class="group-textarea" :disabled="locked || !canGenerate" :maxlength="20000" placeholder="输入你的行动或台词…" auto-height />
            <button role="button" class="group-action" :disabled="!canSend || !draft.trim()" @tap="state.command('send')">发送并推进剧情</button>
            <text v-if="current?.latest && !current.latest.confirmed" class="group-copy">发送下一条消息会确认当前采用候选；未完成轮次需要先继续、重新生成或撤回。</text>
            <view class="candidate-actions">
              <button role="button" class="group-action" :disabled="!canRegenerate" @tap="state.command('regenerate')">整轮重新生成</button>
              <button role="button" class="group-action group-danger" :disabled="!canDiscard" @tap="state.command('discard', undefined, confirmDiscard)">撤回当前轮次</button>
            </view>
          </view>
          <text v-if="error" class="group-error" role="alert">{{ error }}</text>
          <view class="group-action" role="button" :aria-disabled="loading || deleting" @tap="state.load">{{ loading ? '正在刷新…' : '刷新详情' }}</view>
          <view class="group-action group-danger" role="button" :aria-disabled="!canDelete" @tap="remove">{{ deleting ? '正在处理…' : '删除整个群聊' }}</view>
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
import { groupRoundStatus as roundStatus, groupRoundNotice } from "@/utils/groupRounds";

const backToList = () => uni.navigateBack({ fail: () => uni.redirectTo({ url: "/pages/group/index" }) });
const state = useGroupSessionDetail(backToList);
const { group, loading, deleting, error, needsSelection, rounds, loadingRounds, roundsError, hasMoreRounds,
  current, canGenerate, draft, submitting, recovering, operationError, notice, pending, operationBusy, locked, historyStale, canDelete,
  canSend, canRegenerate, canDiscard, candidates, candidateRoundId, loadingCandidates, candidatesError,
  hasMoreCandidates, preview, loadingPreview, previewError } = state;
onLoad(options => state.setSessionId(Number(options?.sessionId)));
onShow(state.show); onHide(state.hide); onUnload(state.hide);
const formatTime = (value: string) => value.replace("T", " ").slice(0, 19);
const actorDescription = (actor: ActorState) => [actor.posture, actor.clothing, actor.location].filter(Boolean).join(" · ");
const refreshRounds = () => state.loadRounds();
const moreRounds = () => state.loadRounds(true);
const retryRounds = () => state.retryRounds();
const memberLabel = (id: number) => `成员 ${group.value?.members.find(member => member.persona_id === id)?.slot ?? "?"}`;
const isSelected = (id: number) => candidateRoundId.value === current.value?.latest?.round_id
  ? current.value.latest.candidate_id === id : preview.value?.round.selected_candidate_id === id || candidates.value.some(row => row.candidate_id === id && row.selected);
const candidateStatus = (status: string) => status === 'failed' ? '未完成' : status === 'generating' ? '处理中' : '完整结果';
const confirmAction = (title: string, content: string) => new Promise<boolean>(resolve => uni.showModal({
  title, content, success: result => resolve(result.confirm), fail: () => resolve(false),
}));
const confirmDiscard = () => confirmAction('撤回当前轮次？', '此轮将移出后续剧情，已确认的更早轮次不会撤销。');
const confirmResume = () => confirmAction('继续未完成候选？', '会沿用原参数，从最后保存的进度继续。未保存成功的步骤可能再次调用模型并产生费用。');
const retry = () => { if (needsSelection.value) backToList(); else void state.load(); };
const remove = () => state.remove(() => new Promise<boolean>(resolve => uni.showModal({
  title: "删除整个群聊？", content: "全部成员与本群数据将被删除，来源单聊和角色卡会保留。此操作无法撤销。",
  confirmText: "删除群聊", confirmColor: "#d9655d", success: result => resolve(result.confirm), fail: () => resolve(false),
})));
</script>

<style scoped>
@import "./group.css";
.member-name { flex: 1; min-width: 0; }
.saved-round { margin-top: 28rpx; border-top: 1px solid var(--app-color-border); padding-top: 12rpx; }
.saved-utterance { margin-top: 24rpx; padding-left: 20rpx; border-left: 2px solid var(--app-color-primary-soft); }
.candidate-row, .candidate-preview { margin-top: 20rpx; border-top: 1px solid var(--app-color-border); padding-top: 16rpx; }
.candidate-actions { display: flex; flex-wrap: wrap; gap: 12rpx; }
button.group-action { margin: 12rpx 0; background: var(--app-color-surface); border-radius: var(--app-radius-sm); }
button.group-action::after { border: none; }
.group-textarea { margin-top: 24rpx; }
</style>
