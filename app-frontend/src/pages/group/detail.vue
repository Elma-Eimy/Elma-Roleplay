<template>
  <view class="page-container group-chat-page"
    :style="paletteStyle"
    :class="[`font-${chatSettingsStore.readingPrefs.fontScale}`, `spacing-${chatSettingsStore.readingPrefs.lineSpacing}`,
      `style-${chatSettingsStore.readingPrefs.bubbleStyle}`, `theme-${chatSettingsStore.readingPrefs.colorTheme}`,
      { 'is-immersive': isImmersive, 'is-android': isAndroid, 'is-portrait-only': isImmersive && isPortraitOnly }]">
    <ChatSceneBackground :src="backgroundUrl" :immersive="isImmersive" :wide="isWideScreen" @unavailable="onBackgroundUnavailable" />
    <ChatHeader
      :character-name="group?.title || '群聊故事'" :current-mood="memberNames || '群聊'"
      :avatar-url="group?.members[0] ? getAvatarUrl(group.members[0].character.avatar_path || '') : ''"
      :is-android="isAndroid" :show-portrait-toggle="isImmersive" @back="backToList" @open-status="openDetails"
      @toggle-portrait-view="isPortraitOnly = true"
    />
    <view v-if="isImmersive && isPortraitOnly" class="portrait-only-overlay" @tap="isPortraitOnly = false">
      <view class="portrait-exit-pill"><text class="portrait-exit-text">返回对话</text></view>
    </view>
    <view class="chat-workspace group-conversation">
      <scroll-view class="group-scroll conversation-scroll" scroll-y :scroll-top="scrollTop" :scroll-into-view="scrollIntoViewId"
        :scroll-with-animation="scrollWithAnimation" @scroll="onScroll">
        <AppStatusState v-if="loading && !group" kind="loading" title="正在读取群聊" />
        <AppStatusState v-else-if="!group" kind="error" title="暂时无法查看群聊" :description="error || '请返回列表重新选择群聊。'" :action-label="needsSelection ? '返回群聊列表' : '重新加载'" @action="retry" />
        <view v-else class="group-transcript">
          <view class="history-actions">
            <button v-if="hasMoreRounds" class="group-action" :disabled="loading || loadingRounds || deleting || operationBusy" @tap="moreRounds">{{ loadingRounds ? '正在读取…' : '加载更早消息' }}</button>
          </view>
          <text v-if="roundsError" class="group-error" role="alert">{{ roundsError }}</text>
          <button v-if="roundsError" class="group-action" :disabled="loading || loadingRounds || deleting" @tap="retryRounds">重新读取发言</button>
          <template v-if="!hasMoreRounds">
            <ChatTranscriptMessage v-for="member in group.members.filter(item => item.greeting_content)"
              :key="'greeting-' + member.persona_id" :content="member.greeting_content || ''"
              :name="`${member.character.name} · 开场`" :avatar-url="getAvatarUrl(member.character.avatar_path || '')" />
          </template>
          <AppStatusState v-if="loadingRounds && !rounds.length" kind="loading" title="正在读取发言" />
          <AppStatusState v-else-if="!rounds.length && !roundsError && !hasGreetings" kind="empty" title="故事从这里开始" description="写下你的行动或台词，让角色回应你。" />
          <view v-for="round in chronologicalRounds" :id="`group-round-${round.round_id}`" :key="round.round_id" class="saved-round">
            <text class="round-divider">第 {{ round.round_index }} 轮 · {{ roundStatus(round) }}</text>
            <ChatTranscriptMessage :content="round.user_content" is-user />
            <GroupUtterances :utterances="round.utterances" :members="group.members" :portraits="round.portraits" />
            <template v-if="round.pending_candidate">
              <text class="candidate-notice">{{ round.pending_candidate.status === 'failed' ? '重新生成未完成，以下回复已保留，尚未采用。' : '正在重新生成，以下回复尚未采用。' }}</text>
              <GroupUtterances :utterances="round.pending_candidate.utterances" :members="group.members" />
            </template>
            <text v-if="groupRoundNotice(round)" :class="round.status === 'failed' ? 'group-error round-notice' : 'group-copy round-notice'">{{ groupRoundNotice(round) }}</text>
            <view class="round-actions">
              <button v-if="current" class="group-action" :disabled="submitting || deleting || loading" @tap="openCandidates(round.round_id)">整轮候选</button>
              <template v-if="round.round_id === current?.latest?.round_id && !operationBusy">
                <button class="group-action" :disabled="!canRegenerate" @tap="state.command('regenerate')">重新生成</button>
                <button class="group-action group-danger" :disabled="!canDiscard" @tap="state.command('discard', undefined, confirmDiscard)">撤回</button>
              </template>
            </view>
          </view>
        </view>
      </scroll-view>
      <button v-if="hasUnreadBelow" class="group-action unread-button" @tap="pinToBottom">查看最新消息 ↓</button>
      <view v-if="group" class="group-composer">
        <view v-if="composerFeedback" class="composer-feedback" :class="{ 'is-error': !!operationError }" role="status">
          <text class="feedback-copy">{{ composerFeedback }}</text>
          <button v-if="historyStale" class="feedback-action" :disabled="loading || loadingRounds || operationBusy" @tap="refreshRounds">刷新</button>
          <button v-else-if="operationError && (pending || current?.active_operation)" class="feedback-action" :disabled="recovering || submitting || loading" @tap="state.recover">{{ recovering ? '查询中' : '查询结果' }}</button>
        </view>
        <ChatComposer v-model="draft" :use-reasoning="chatSettingsStore.useReasoning" :model-summary="chatSettingsStore.modelSummary"
          :is-focused="isFocused" :is-android="isAndroid" :keyboard-height="keyboardHeight" :wrapper-style="inputWrapperStyle"
          :is-generating="operationBusy" :disabled="!canSend" :maxlength="20000"
          @open-model-settings="openModelSettings"
          @focus-change="onFocusChange" @line-change="followNewContent" @send="send" />
      </view>
    </view>
    <PromptPreviewModal :is-open="promptPreview !== null" :messages="promptPreview?.messages || []" :token-estimate="promptPreview?.token_estimate" @close="promptPreview = null" />
    <GenerationSettingsSheet :is-open="isModelSettingsOpen" @close="isModelSettingsOpen = false" />
    <ChatDrawer v-if="group && drawerMember && drawerMemberState" :is-open="showDetails" :session-id="group.session_id" :background-mode="backgroundMode" :member-context="drawerMemberContext" :hide-delete="!canDelete"
      @close="showDetails = false" @update:background-mode="setBackgroundMode" @delete-session="remove"
      @open-prompt-preview="openMemberPrompt(drawerMember.persona_id)" @open-memory-view="openMemberMemories">
      <template #member-picker>
        <view class="group-member-picker"><text class="group-label">群聊成员</text><view class="background-members">
          <button v-for="member in group.members" :key="member.persona_id" class="background-member" :class="{ 'is-active': drawerMember.persona_id === member.persona_id }" @tap="drawerPersonaId = member.persona_id">{{ member.character.name }}</button>
        </view><text class="group-copy">切换成员，查看各自的状态与记忆。</text></view>
      </template>
      <template #role-state>
        <text v-if="loadingAdoptedState" class="group-copy">正在同步成员状态…</text>
        <text v-if="adoptedStateError" class="group-error">{{ adoptedStateError }}</text>
        <RoleStatePanel v-if="!current?.latest?.candidate_id || adoptedState" :session-id="null" :readonly-state="drawerMemberState.role_state" :processing="operationBusy" />
        <text v-else class="group-copy">{{ operationBusy ? '正在生成，完成后同步当前状态。' : '状态尚未同步，请刷新后查看。' }}</text>
        <button class="group-action" :disabled="loadingAdoptedState || operationBusy" @tap="state.loadAdoptedState">刷新状态</button>
      </template>
      <template #portraits>
          <view class="panel-section">
            <view class="group-row"><text class="group-heading">成员立绘</text><button class="group-action" :aria-expanded="showPortraits" @tap="togglePortraits">{{ showPortraits ? '收起' : '查看' }}</button></view>
            <template v-if="showPortraits">
              <text class="group-copy">每名成员独立选择。立绘随采用候选保存，切换候选和撤回会恢复对应选择，已删除素材回退头像。</text>
              <text v-if="loadingPortraits" class="group-copy" role="status">正在读取立绘…</text>
              <text v-if="portraitWriting" class="group-copy" role="status">正在保存选择，请稍候…</text>
              <text v-if="portraitError" class="group-error" role="alert">{{ portraitError }}</text>
              <text v-if="portraitData && !portraitData.can_update" class="group-copy">当前只可查看；请求处理完成并刷新后，才能修改最新未确认候选的选择。</text>
              <view v-if="portraitData" class="portrait-scene">
                <view v-for="member in group.members" :key="member.persona_id" class="portrait-member">
                  <text class="group-label">{{ member.character.name }} · 成员 {{ member.slot }}</text>
                  <AvatarImage class="scene-image" :src="portraitImage(member.persona_id)" mode="aspectFit" />
                  <text class="group-copy">{{ selectedPortrait(member.persona_id) ? '采用立绘' : '角色头像' }}</text>
                  <button class="group-action" :disabled="!canChoosePortrait" @tap="state.choosePortrait(member.persona_id, null)">使用头像</button>
                  <button class="group-action" :disabled="!canChoosePortrait || portraitOptions[member.persona_id]?.loading" @tap="state.loadPortraitOptions(member.persona_id)">选择已有立绘</button>
                  <template v-if="portraitOptions[member.persona_id]">
                    <text v-if="portraitOptions[member.persona_id].loading" class="group-copy">正在读取素材…</text>
                    <text v-if="portraitOptions[member.persona_id].error" class="group-error">{{ portraitOptions[member.persona_id].error }}</text>
                    <text v-if="!portraitOptions[member.persona_id].loading && !portraitOptions[member.persona_id].error && !portraitOptions[member.persona_id].rows.length" class="group-copy">还没有立绘，可到角色档案添加。</text>
                    <button v-for="portrait in portraitOptions[member.persona_id].rows" :key="portrait.id" class="group-action" :disabled="!canChoosePortrait" @tap="state.choosePortrait(member.persona_id, portrait.id)">{{ portrait.name }}{{ selectedPortrait(member.persona_id) === portrait.id ? ' · 当前采用' : '' }}</button>
                    <button v-if="portraitOptions[member.persona_id].hasMore" class="group-action" :disabled="!canChoosePortrait || portraitOptions[member.persona_id].loading" @tap="state.loadPortraitOptions(member.persona_id, true)">加载更多立绘</button>
                  </template>
                </view>
              </view>
              <button class="group-action" :disabled="loadingPortraits || portraitWriting || operationBusy || loading || deleting" @tap="state.refreshPortraits">刷新立绘</button>
            </template>
          </view>

      </template>
      <template #member-insights>
        <view v-if="drawerMemberState.insights?.length" class="panel-section"><text class="section-title">认识与关系</text><text v-for="(insight, index) in drawerMemberState.insights" :key="index" class="group-copy">{{ insight.content }}</text></view>
      </template>
      <template #group-tools>
        <view class="panel-section"><text class="section-title">共同设定</text><text class="group-copy">{{ group.shared_setting || '未填写共同设定。' }}</text><text class="group-copy">你的名字：{{ group.user_nickname }}</text></view>
        <view class="panel-section"><text class="section-title">成员起点</text><text class="group-copy">{{ drawerMember.origin.mode === 'card' ? '从原卡开始' : `导入单聊快照 · ${drawerMember.origin.inherited_memory_count} 张记忆卡` }}</text><text class="group-copy">起点好感：{{ drawerMember.state.affection_score ?? '未记录' }} · 起点心情：{{ drawerMember.state.current_mood || '未记录' }}</text></view>
        <view class="panel-section"><text class="section-title">群聊管理</text><button class="action-btn outline" :disabled="loading || deleting" @tap="state.load">刷新群聊资料</button><text v-if="error" class="group-error">{{ error }}</text></view>
      </template>
    </ChatDrawer>
    <MemoryManagerModal v-if="group && memoryPersonaId" :key="`${group.session_id}:${memoryPersonaId}`" :is-open="true" :session-id="group.session_id" :group-persona-id="memoryPersonaId" :context-title="`${group.title} · ${group.members.find(member => member.persona_id === memoryPersonaId)?.character.name || ''}`" local-label="群内记忆" @close="memoryPersonaId = null" />
    <view v-if="showCandidates && group" class="status-panel-backdrop" :class="{ 'is-android': isAndroid }" @tap="showCandidates = false">
      <view class="status-panel" role="dialog" aria-label="整轮候选" @tap.stop>
        <view class="panel-header"><text class="group-heading">整轮候选</text><button class="group-action" @tap="showCandidates = false">关闭</button></view>
        <scroll-view class="group-scroll" scroll-y><view class="group-content">
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
              <ChatTranscriptMessage :content="preview.round.user_content" is-user />
              <GroupUtterances :utterances="preview.utterances" :members="group.members" :portraits="previewPortraits" />
              <text v-if="preview.candidate.status === 'failed'" class="group-error">此候选未完成，以上仅为已保存前缀，不会作为完整结果确认。</text>
              <text v-else-if="!preview.utterances.length" class="group-copy">此候选尚无角色发言。</text>
              <text class="group-label">此候选的状态预览</text>
              <GroupMemberStates :states="preview.state_preview.members" :members="group.members" :user-nickname="group.user_nickname" />
            </view>
          </view>
        </view></scroll-view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch, getCurrentInstance } from "vue";
import { onLoad, onShow, onHide, onUnload, onReady, onResize } from "@dcloudio/uni-app";
import ChatSceneBackground from "@/components/chat/ChatSceneBackground.vue";
import ChatDrawer from "@/components/chat/ChatDrawer.vue";
import MemoryManagerModal from "@/components/chat/MemoryManagerModal.vue";
import RoleStatePanel from "@/components/chat/RoleStatePanel.vue";
import PromptPreviewModal from "@/components/chat/PromptPreviewModal.vue";
import { compileGroupMemberPrompt } from "@/api/groupSessions";
import type { GroupPromptPreview } from "@/types/groupSessions";
import GenerationSettingsSheet from "@/components/chat/GenerationSettingsSheet.vue";
import { useChatSettingsStore } from "@/store/chatSettingsStore";
import { getBaseUrl } from "@/api/config";
import { STORY_PALETTES } from "@/composables/useStoryKeepsakes";
import ChatHeader from "@/components/chat/ChatHeader.vue";
import ChatComposer from "@/components/chat/ChatComposer.vue";
import ChatTranscriptMessage from "@/components/chat/ChatTranscriptMessage.vue";
import { useChatScroll } from "@/composables/useChatScroll";
import AppStatusState from "@/components/common/AppStatusState.vue";
import AvatarImage from "@/components/common/AvatarImage.vue";
import GroupUtterances from "@/components/chat/GroupUtterances.vue";
import GroupMemberStates from "@/components/chat/GroupMemberStates.vue";
import { getAvatarUrl } from "@/api/characters";
import { useGroupSessionDetail } from "@/composables/useGroupSessions";
import { groupRoundStatus as roundStatus, groupRoundNotice } from "@/utils/groupRounds";

const promptPreview = ref<GroupPromptPreview | null>(null);
const promptLoading = ref(false), promptError = ref("");
let promptVersion = 0;
async function openMemberPrompt(personaId: number) {
  if (!group.value || promptLoading.value) return;
  const version = ++promptVersion, sessionId = group.value.session_id, server = getBaseUrl();
  const valid = () => version === promptVersion && group.value?.session_id === sessionId && getBaseUrl() === server;
  promptLoading.value = true; promptError.value = "";
  try {
    const result = await compileGroupMemberPrompt(sessionId, personaId);
    if (valid()) { showDetails.value = false; promptPreview.value = result; }
  } catch (cause) { if (valid()) promptError.value = cause instanceof Error ? cause.message : String(cause); }
  finally { if (valid()) promptLoading.value = false; }
}

const backToList = () => uni.navigateBack({ fail: () => uni.redirectTo({ url: "/pages/group/index" }) });
const chatSettingsStore = useChatSettingsStore();
const state = useGroupSessionDetail(backToList, id => chatSettingsStore.requestGeneration(id, { ...chatSettingsStore.selection }));
const showPortraits = ref(false);
const { group, loading, deleting, error, needsSelection, rounds, loadingRounds, roundsError, hasMoreRounds,
  current, canGenerate, draft, submitting, recovering, operationError, notice, pending, operationBusy, locked, historyStale, canDelete,
  canSend, canRegenerate, canDiscard, candidates, candidateRoundId, loadingCandidates, candidatesError,
  hasMoreCandidates, preview, loadingPreview, previewError, adoptedState, loadingAdoptedState, adoptedStateError,
  portraitData, loadingPortraits, portraitWriting, portraitError, portraitOptions, canChoosePortrait } = state;
const composerFeedback = computed(() => {
  if (operationError.value) return operationError.value;
  if (historyStale.value) return '剧情已有更新，刷新后继续。';
  if (!current.value) return '正在同步群聊，已有消息仍可阅读。';
  if (!canGenerate.value) return '生成服务暂不可用，已有消息仍可阅读。';
  if (!operationBusy.value && notice.value && !notice.value.startsWith('操作已完成')
      && !notice.value.startsWith('请求已接受')) return notice.value;
  return '';
});
const palette = STORY_PALETTES[0];
const paletteStyle = { '--story-accent': palette.color, '--story-soft': palette.soft, '--story-mist': palette.mist };
const hasGreetings = computed(() => !!group.value?.members.some(member => member.greeting_content?.trim()));
const backgroundMode = ref<'clean' | 'character'>('character');
const focusedPersona = ref<number | null>(null);
const isPortraitOnly = ref(false);
const isWideScreen = ref(uni.getSystemInfoSync().windowWidth >= 900);
const drawerPersonaId = ref<number | null>(null);
const memoryPersonaId = ref<number | null>(null);
const drawerMember = computed(() => group.value?.members.find(member => member.persona_id === drawerPersonaId.value) || group.value?.members[0]);
const drawerMemberState = computed(() => {
  const member = drawerMember.value;
  if (!member) return null;
  return adoptedState.value?.state_preview.members.find(row => row.persona_id === member.persona_id)
    || { persona_id: member.persona_id, ...member.state, insights: [] };
});
const drawerMemberContext = computed(() => drawerMember.value && drawerMemberState.value ? {
  name: drawerMember.value.character.name, character: drawerMember.value.character,
  affection: current.value?.latest?.candidate_id && !adoptedState.value ? null : drawerMemberState.value.affection_score ?? 0, mood: drawerMemberState.value.current_mood,
  cognition: drawerMemberState.value.cognition_state ?? null,
} : undefined);
const openMemberMemories = () => { if (drawerMember.value) { memoryPersonaId.value = drawerMember.value.persona_id; showDetails.value = false; } };

const lastSpokenRound = computed(() => rounds.value.find(round => round.utterances.length > 0));
const backgroundMember = computed(() => {
  const latest = lastSpokenRound.value;
  const lastSpeaker = latest?.utterances[latest.utterances.length - 1]?.speaker_persona_id;
  return group.value?.members.find(member => member.persona_id === (focusedPersona.value ?? lastSpeaker)) || group.value?.members[0];
});
const backgroundPath = computed(() => {
  const member = backgroundMember.value;
  if (!member) return '';
  const selection = [portraitData.value?.members, rounds.value[0]?.portraits, lastSpokenRound.value?.portraits]
    .map(rows => rows?.find(row => row.persona_id === member.persona_id)).find(row => row !== undefined);
  return selection?.image_path || member.character.avatar_path || '';
});
const failedBackgrounds = ref<string[]>([]);
const backgroundUrl = computed(() => [backgroundPath.value, backgroundMember.value?.character.avatar_path]
  .filter((path): path is string => !!path).map(getAvatarUrl).find(url => !failedBackgrounds.value.includes(url)) || '');
const isImmersive = computed(() => backgroundMode.value === 'character' && !!backgroundUrl.value);
const onBackgroundUnavailable = (event: Event) => {
  const target = event.currentTarget as unknown as { dataset?: { source?: string } };
  if (target?.dataset?.source === backgroundUrl.value) failedBackgrounds.value = [...failedBackgrounds.value, backgroundUrl.value];
};
const backgroundKey = () => `group_background_mode:${getBaseUrl()}:${group.value?.session_id}`;
const setBackgroundMode = (mode: 'clean' | 'character') => {
  backgroundMode.value = mode;
  try { uni.setStorageSync(backgroundKey(), mode); } catch { /* The current view still uses the selected mode. */ }
};
watch([current, loading, loadingRounds, operationBusy], () => {
  if (group.value && current.value && !loading.value && !loadingRounds.value && !operationBusy.value) {
    void state.loadPortraits();
    if (showDetails.value) void state.loadAdoptedState();
  }
});
onResize(({ size }) => { if (size) isWideScreen.value = size.windowWidth >= 900; });
const openDetails = () => {
  showDetails.value = true;
  void state.loadAdoptedState();
  void state.loadPortraits();
};
const showDetails = ref(false), showCandidates = ref(false), isFocused = ref(false);
const isModelSettingsOpen = ref(false);
const openModelSettings = () => {
  if (!group.value) return;
  chatSettingsStore.activateSession(group.value.session_id);
  showDetails.value = false;
  isModelSettingsOpen.value = true;
};
let pageViewVersion = 0;
watch(() => group.value?.session_id, () => { pageViewVersion++; }, { flush: 'sync' });
const { scrollTop, scrollIntoViewId, scrollWithAnimation, keyboardHeight, isAndroid,
  followNewContent, pinToBottom, updateScrollMetrics, maintainScrollPosition, hasUnreadBelow, resetPinState, triggerPhasedScroll } = useChatScroll();
const inputWrapperStyle = computed(() => keyboardHeight.value > 0 ? { paddingBottom: '14rpx' } : {});
const onFocusChange = (focused: boolean) => {
  isFocused.value = focused;
  if (focused) triggerPhasedScroll();
};
const chronologicalRounds = computed(() => [...rounds.value].sort((a, b) => a.round_index - b.round_index));
const instance = getCurrentInstance();
let viewportHeight = 0, lastMeasuredAt = 0;
const measureViewport = () => {
  lastMeasuredAt = Date.now();
  const query = uni.createSelectorQuery();
  if (instance?.proxy) query.in(instance.proxy);
  query.select(".conversation-scroll").boundingClientRect(rect => {
    const node = (Array.isArray(rect) ? rect[0] : rect) as UniApp.NodeInfo | null;
    if (node?.height) viewportHeight = node.height;
  }).exec();
};
onReady(measureViewport);
onResize(measureViewport);
const onScroll = (event: { detail: { scrollTop: number; scrollHeight: number } }) => {
  if (Date.now() - lastMeasuredAt > 500) measureViewport();
  updateScrollMetrics({ ...event.detail, viewportHeight });
};
watch(() => {
  const latest = chronologicalRounds.value[chronologicalRounds.value.length - 1];
  return latest ? JSON.stringify([latest.round_id, latest.utterances, latest.pending_candidate]) : "";
}, () => followNewContent());
watch(() => group.value?.session_id, () => {
  drawerPersonaId.value = null; memoryPersonaId.value = null;
  promptVersion++; promptPreview.value = null; promptLoading.value = false; promptError.value = "";
  isModelSettingsOpen.value = false;
  if (group.value) chatSettingsStore.activateSession(group.value.session_id);
  showDetails.value = false;
  showCandidates.value = false;
  showPortraits.value = false;
  focusedPersona.value = null;
  isPortraitOnly.value = false;
  failedBackgrounds.value = [];
  backgroundMode.value = 'character';
  try { if (uni.getStorageSync(backgroundKey()) === 'clean') backgroundMode.value = 'clean'; } catch {}
  resetPinState();
});
const send = () => {
  if (!canSend.value || !draft.value.trim()) return;
  pinToBottom();
  void state.command('send');
};
const openCandidates = (roundId: number) => {
  showCandidates.value = true;
  void state.loadCandidates(roundId);
};
const togglePortraits = () => {
  showPortraits.value = !showPortraits.value;
  if (showPortraits.value) void state.refreshPortraits();
};
const portraitImage = (id: number) => getAvatarUrl(portraitData.value?.members.find(row => row.persona_id === id)?.image_path || "");
const selectedPortrait = (id: number) => portraitData.value?.members.find(row => row.persona_id === id)?.portrait_id;
const previewPortraits = computed(() => preview.value?.state_preview.members.flatMap(row => row.portrait ? [row.portrait] : []) || []);
const memberNames = computed(() => group.value?.members.map(member => member.character.name).join(" · ") || "");
onLoad(options => state.setSessionId(Number(options?.sessionId)));
onShow(() => {
  if (group.value) chatSettingsStore.activateSession(group.value.session_id);
  void chatSettingsStore.refreshModels();
  state.show();
});
const hide = () => { memoryPersonaId.value = null; promptVersion++; promptPreview.value = null; promptLoading.value = false; pageViewVersion++; isModelSettingsOpen.value = false; isFocused.value = false; showDetails.value = false; showCandidates.value = false; state.hide(); };
onHide(hide); onUnload(hide);
const refreshRounds = () => state.loadRounds();
const moreRounds = async () => {
  const anchor = chronologicalRounds.value[0]?.round_id;
  const version = pageViewVersion, sessionId = group.value?.session_id, server = getBaseUrl();
  const valid = () => version === pageViewVersion && sessionId === group.value?.session_id && server === getBaseUrl();
  const loaded = await state.loadRounds(true);
  if (loaded && valid() && anchor !== undefined) maintainScrollPosition(`group-round-${anchor}`, valid);
};
const retryRounds = () => state.retryRounds();
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
@import "../chat/chat.css";
@import "../../components/chat/chatDrawer.css";
.group-chat-page { height: 100vh; height: 100dvh; overflow: hidden; color: var(--app-color-text-primary); }
.group-chat-page .status-panel {
  width: 90vw; max-width: 760rpx; color: #26332e;
  --app-color-text-primary: #26332e; --app-color-text-secondary: #64716b;
  --app-color-text-muted: #7c8983; --app-color-primary-strong: #3f7e6d;
  --app-color-primary-soft: #e8f1ed; --app-color-border: #e6ebe8;
  --app-color-surface: #fff; --app-color-background: #f6f8f7;
}
.group-chat-page .panel-section { gap: 12rpx; box-shadow: none; border: 1px solid #e9eeeb; }
.group-chat-page .panel-section .group-heading { font-size: 28rpx; }
.group-chat-page .panel-section .group-copy { margin-top: 0; font-size: 24rpx; }
.group-chat-page :deep(.status-text) { max-width: 250rpx; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.background-member::after { border: 0; }
.background-members { display: flex; gap: 12rpx; flex-wrap: wrap; margin-top: 20rpx; }
.background-member { margin: 0; padding: 10rpx 18rpx; border-radius: 999rpx; font-size: 22rpx; line-height: 1.5; background: #f1f4f2; color: #64716b; }
.background-member.is-active { background: #e2eee8; color: #3f7e6d; }
.background-mode-option { margin: 0; line-height: 1.5; }
@media (prefers-reduced-motion: reduce) { .group-chat-page .status-panel { animation: none; } }
.group-conversation { display: flex; flex: 1; flex-direction: column; min-height: 0; width: 100%; max-width: 800px; margin: 0 auto; position: relative; }
.group-transcript { padding: 12rpx 0 28rpx; }
.history-actions, .round-actions { display: flex; flex-wrap: wrap; justify-content: center; gap: 12rpx; }
.round-actions { justify-content: flex-start; padding: 0 32rpx 16rpx 122rpx; }
.round-divider { display: block; text-align: center; font-size: var(--app-font-size-caption); color: var(--app-color-text-muted); margin: 24rpx 0 12rpx; }
.round-notice, .candidate-notice { display: block; margin: 12rpx 28rpx; padding: 18rpx 24rpx; border-radius: 18rpx; background: var(--app-color-surface); font-size: 24rpx; line-height: 1.6; }
.candidate-notice { color: var(--app-color-text-secondary); border: 1px dashed var(--app-color-border-strong); }
.round-actions .group-action { padding: 8rpx 22rpx; min-height: 64rpx; background: var(--app-color-surface); border: 1px solid var(--app-color-border); border-radius: 999rpx; font-size: 22rpx; }
.is-immersive .round-actions, .is-immersive .round-notice, .is-immersive .candidate-notice, .is-immersive .round-divider, .is-immersive .composer-feedback {
  --app-color-surface: rgba(20,34,28,.92); --app-color-border: rgba(255,255,255,.18);
  --app-color-border-strong: rgba(255,255,255,.35); --app-color-text-secondary: #e0eae4;
  --app-color-primary-strong: #d2eddf; --app-color-danger: #ffb5ad;
}
.is-immersive .round-divider { color: #e0eae4; text-shadow: 0 1px 4px #14221c; }
.composer-feedback { display: flex; align-items: center; gap: 16rpx; margin: 8rpx 24rpx; padding: 18rpx 22rpx; border-radius: 20rpx; color: var(--app-color-text-secondary); background: var(--app-color-surface); border: 1px solid var(--app-color-border); }
.composer-feedback.is-error { color: var(--app-color-danger); }
.feedback-copy { flex: 1; min-width: 0; font-size: 24rpx; line-height: 1.6; overflow-wrap: anywhere; }
.feedback-action { flex-shrink: 0; margin: 0; padding: 10rpx 16rpx; min-height: 72rpx; line-height: 1.5; font-size: 24rpx; background: transparent; color: var(--app-color-primary-strong); }
.feedback-action::after { border: 0; }
.group-composer { flex-shrink: 0; }
.group-composer .group-card { margin: 0; padding: 0 32rpx; background: transparent; border: 0; }
.group-composer .group-copy, .group-composer .group-error { margin: 8rpx 0; font-size: var(--app-font-size-caption); }
.unread-button { position: absolute; right: 24rpx; bottom: 220rpx; background: var(--app-color-surface); border-radius: var(--app-radius-pill); box-shadow: var(--app-shadow-sm); z-index: 12; }
.member-name { flex: 1; min-width: 0; }
.portrait-scene { display: flex; flex-wrap: wrap; gap: 24rpx; }
.portrait-member { flex: 1 1 260rpx; min-width: 0; }
.portrait-member .group-label, .portrait-member .group-action { overflow-wrap: anywhere; white-space: normal; }
.scene-image { width: 100%; height: 420rpx; }
.candidate-row, .candidate-preview { margin-top: 20rpx; border-top: 1px solid var(--app-color-border); padding-top: 16rpx; }
.candidate-actions { display: flex; flex-wrap: wrap; gap: 12rpx; }
button.group-action { margin: 4rpx 0; background: transparent; border-radius: var(--app-radius-sm); }
button.group-action::after { border: none; }
button.group-action[disabled] { opacity: .45; }

.group-member-picker { padding: 0 28rpx 24rpx; }
</style>
