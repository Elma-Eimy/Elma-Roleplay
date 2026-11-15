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
    <view class="chat-workspace">
      <view class="chat-conversation">
        <ChatScrollShell
          ref="scrollShellRef"
          :scroll-top="scrollTop"
          :scroll-into-view-id="scrollIntoViewId"
          :scroll-with-animation="scrollWithAnimation"
          :show-jump-button="hasUnreadBelow || (!isPinnedToBottom && (chronologicalRounds.length > 0 || !!optimisticUserContent))"
          :has-unread="hasUnreadBelow"
          :is-empty="!!group && !rounds.length && !optimisticUserContent && !roundsError && !hasGreetings && !loadingRounds"
          empty-title="故事从这里开始"
          empty-description="写下你的行动或台词，让角色回应你。"
          @reach-top="onReachTop"
          @scroll-metrics="updateScrollMetrics"
          @jump-to-bottom="onJumpToBottom"
        >
          <AppStatusState v-if="loading && !group" kind="loading" title="正在读取群聊" />
          <AppStatusState v-else-if="!group" kind="error" title="暂时无法查看群聊" :description="error || '请返回故事列表重新选择群聊。'" :action-label="needsSelection ? '返回故事列表' : '重新加载'" @action="retry" />
          <view v-else class="group-transcript">
            <view v-if="hasMoreRounds" class="history-actions">
              <button class="history-pill" :disabled="loading || loadingRounds || deleting || operationBusy" @tap="moreRounds">
                <text class="history-pill-text">{{ loadingRounds ? '正在读取…' : '加载更早消息' }}</text>
              </button>
            </view>
            <text v-if="roundsError" class="group-error" role="alert">{{ roundsError }}</text>
            <button v-if="roundsError" class="group-action" :disabled="loading || loadingRounds || deleting" @tap="retryRounds">重新读取发言</button>
            <template v-if="!hasMoreRounds">
              <ChatBubble
                v-for="member in group.members.filter(item => item.greeting_content)"
                :key="'greeting-' + member.persona_id"
                :message="{ id: -member.persona_id, role: 'assistant', status: 'done', content: member.greeting_content || '' }"
                :character-name="`${member.character.name} · 开场`"
                :avatar-url="getAvatarUrl(member.character.avatar_path || '')"
                :user-nickname="group.user_nickname"
                read-only
              />
            </template>
            <AppStatusState v-if="loadingRounds && !rounds.length" kind="loading" title="正在读取发言" />
            <view v-for="round in chronologicalRounds" :id="`group-round-${round.round_id}`" :key="round.round_id" class="saved-round">
              <text class="round-divider">第 {{ round.round_index }} 轮 · {{ roundHeaderStatus(round) }}</text>
              <ChatBubble
                :message="{ id: -round.round_id * 10 - 1, role: 'user', status: 'done', content: round.user_content }"
                :user-nickname="group.user_nickname"
                read-only
              />
              <view v-if="hasPausedOrFailedPendingCandidate(round)" class="round-candidate-switcher">
                <text class="switcher-caption">{{ round.pending_candidate?.error_code === 'resource_paused' ? '重新生成已暂停，可继续生成新候选或切回原采用回复。' : '重新生成未完成，以下为已保留草稿，尚未替换原采用回复。' }}</text>
                <view class="switcher-pills">
                  <view
                    class="switcher-pill"
                    :class="{ 'is-active': activeRoundTab(round) === 'pending' }"
                    role="button"
                    @tap="setRoundTab(round.round_id, 'pending')"
                  >
                    <text class="switcher-pill-text">新候选草稿 ({{ round.pending_candidate?.utterances.length || 0 }})</text>
                  </view>
                  <view
                    class="switcher-pill"
                    :class="{ 'is-active': activeRoundTab(round) === 'adopted' }"
                    role="button"
                    @tap="setRoundTab(round.round_id, 'adopted')"
                  >
                    <text class="switcher-pill-text">当前采用 ({{ round.utterances.length }})</text>
                  </view>
                </view>
              </view>
              <GroupUtterances
                v-if="displayedUtterances(round).length"
                :utterances="displayedUtterances(round)"
                :members="group.members"
                :portraits="round.portraits"
                :user-nickname="group.user_nickname"
              />
              <view v-if="isRoundGenerating(round) && !displayedUtterances(round).length" class="group-waiting-row" role="status">
                <view class="waiting-avatar-stack">
                  <AvatarImage
                    v-for="(member, mIndex) in waitingMembers"
                    :key="'wait-' + round.round_id + '-' + member.persona_id"
                    class="waiting-avatar"
                    :class="{ 'is-stacked': mIndex > 0 }"
                    :src="getAvatarUrl(member.character.avatar_path || '')"
                  />
                </view>
                <view class="waiting-content-area">
                  <text class="waiting-speaker-label">{{ waitingTitle(round) }}</text>
                  <view class="waiting-bubble-card">
                    <view class="waiting-pulse-row">
                      <view class="ai-thinking">
                        <view class="ai-dot"></view>
                        <view class="ai-dot delay-1"></view>
                        <view class="ai-dot delay-2"></view>
                      </view>
                      <text class="waiting-subtitle">{{ waitingSubtitle(round) }}</text>
                    </view>
                  </view>
                </view>
              </view>
              <view v-else-if="isRoundGenerating(round)" class="group-continuation-bar" role="status">
                <view class="continuation-avatars">
                  <AvatarImage
                    v-for="(member, mIndex) in waitingMembers"
                    :key="'cont-' + round.round_id + '-' + member.persona_id"
                    class="continuation-avatar"
                    :class="{ 'is-stacked': mIndex > 0 }"
                    :src="getAvatarUrl(member.character.avatar_path || '')"
                  />
                </view>
                <view class="ai-thinking is-compact">
                  <view class="ai-dot"></view>
                  <view class="ai-dot delay-1"></view>
                  <view class="ai-dot delay-2"></view>
                </view>
                <text class="continuation-copy">{{ continuationCopy(round) }}</text>
              </view>
              <text v-if="!isRoundGenerating(round) && activeRoundTab(round) === 'pending' && !displayedUtterances(round).length" class="group-copy round-notice">此新候选尚未生成任何角色发言。</text>
              <text v-if="!isRoundGenerating(round) && activeRoundTab(round) === 'adopted' && groupRoundNotice(round)" :class="round.status === 'failed' && round.error_code !== 'resource_paused' ? 'group-error round-notice' : 'group-copy round-notice'">{{ groupRoundNotice(round) }}</text>
              <view v-if="roundActionItems(round).length" class="round-actions">
                <ChatActionBar :items="roundActionItems(round)" @select="onRoundAction($event, round)" />
              </view>
            </view>
            <view v-if="optimisticUserContent" id="group-round-optimistic" class="saved-round is-optimistic-round">
              <text class="round-divider">第 {{ nextRoundIndex }} 轮 · 处理中</text>
              <ChatBubble
                :message="{ id: -999999, role: 'user', status: 'sending', content: optimisticUserContent }"
                :user-nickname="group.user_nickname"
                animate-entry
                read-only
              />
              <view class="group-waiting-row" role="status">
                <view class="waiting-avatar-stack">
                  <AvatarImage
                    v-for="(member, mIndex) in waitingMembers"
                    :key="'opt-wait-' + member.persona_id"
                    class="waiting-avatar"
                    :class="{ 'is-stacked': mIndex > 0 }"
                    :src="getAvatarUrl(member.character.avatar_path || '')"
                  />
                </view>
                <view class="waiting-content-area">
                  <text class="waiting-speaker-label">{{ waitingTitle() }}</text>
                  <view class="waiting-bubble-card">
                    <view class="waiting-pulse-row">
                      <view class="ai-thinking">
                        <view class="ai-dot"></view>
                        <view class="ai-dot delay-1"></view>
                        <view class="ai-dot delay-2"></view>
                      </view>
                      <text class="waiting-subtitle">{{ waitingSubtitle() }}</text>
                    </view>
                  </view>
                </view>
              </view>
            </view>
          </view>
        </ChatScrollShell>
        <view v-if="group" class="group-composer">
          <view v-if="composerFeedback" class="composer-feedback" :class="{ 'is-error': !!operationError }" role="status">
            <text class="feedback-copy">{{ composerFeedback }}</text>
            <button v-if="historyStale" class="feedback-action" :disabled="loading || loadingRounds || operationBusy" @tap="refreshRounds">刷新</button>
            <button v-else-if="operationError && (pending || current?.active_operation)" class="feedback-action" :disabled="recovering || submitting || loading" @tap="state.recover">{{ recovering ? '查询中' : '查询结果' }}</button>
          </view>
          <ChatComposer
            :model-value="optimisticUserContent ? '' : draft"
            :use-reasoning="chatSettingsStore.useReasoning"
            :model-summary="chatSettingsStore.modelSummary"
            :is-focused="isFocused"
            :is-android="isAndroid"
            :keyboard-height="keyboardHeight"
            :wrapper-style="inputWrapperStyle"
            :is-generating="operationBusy"
            :disabled="composerDisabled"
            :character-name="group.title || '群聊成员'"
            :maxlength="20000"
            @update:model-value="draft = $event"
            @open-model-settings="openModelSettings"
            @focus-change="onFocusChange"
            @line-change="followNewContent"
            @send="send"
          />
        </view>
      </view>
    </view>
    <PromptPreviewModal :is-open="promptPreview !== null" :messages="promptPreview?.messages || []" :token-estimate="promptPreview?.token_estimate" @close="promptPreview = null" />
    <GenerationSettingsSheet :is-open="isModelSettingsOpen" @close="isModelSettingsOpen = false" />
    <GroupChatDrawer
      v-if="group && drawerMember && drawerMemberState"
      :is-open="showDetails"
      :group="group"
      :member="drawerMember"
      :member-state="drawerMemberState"
      :has-adopted-state-view="!current?.latest?.candidate_id || !!adoptedState"
      :background-mode="backgroundMode"
      :hide-delete="!canDelete"
      :operation-busy="operationBusy"
      :loading-adopted-state="loadingAdoptedState"
      :adopted-state-error="adoptedStateError"
      :portrait-data="portraitData"
      :portrait-options="portraitOptions"
      :loading-portraits="loadingPortraits"
      :portrait-writing="portraitWriting"
      :portrait-error="portraitError"
      :can-choose-portrait="canChoosePortrait"
      :loading-group="loading"
      :deleting="deleting"
      :group-error="error"
      @close="showDetails = false"
      @update:background-mode="setBackgroundMode"
      @delete-session="remove"
      @select-member="drawerPersonaId = $event"
      @open-prompt-preview="openMemberPrompt"
      @open-memory-view="openMemberMemories"
      @refresh-state="state.loadAdoptedState"
      @refresh-group="state.load"
      @choose-portrait="state.choosePortrait"
      @load-portrait-options="state.loadPortraitOptions"
      @refresh-portraits="state.refreshPortraits"
    />
    <MemoryManagerModal v-if="group && memoryPersonaId" :key="`${group.session_id}:${memoryPersonaId}`" :is-open="true" :session-id="group.session_id" :group-persona-id="memoryPersonaId" :context-title="`${group.title} · ${group.members.find(member => member.persona_id === memoryPersonaId)?.character.name || ''}`" local-label="群内记忆" @close="memoryPersonaId = null" />
    <GroupCandidateModal
      :is-open="showCandidates"
      :group="group"
      :current="current"
      :candidate-round-id="candidateRoundId"
      :candidates="candidates"
      :loading-candidates="loadingCandidates"
      :candidates-error="candidatesError"
      :has-more-candidates="hasMoreCandidates"
      :preview="preview"
      :loading-preview="loadingPreview"
      :preview-error="previewError"
      :submitting="submitting"
      :deleting="deleting"
      :locked="locked"
      :can-generate="canGenerate"
      :is-android="isAndroid"
      @close="showCandidates = false"
      @refresh="state.loadCandidates($event)"
      @load-more="state.loadCandidates($event, true)"
      @view="(roundId, candidateId) => state.viewCandidate(roundId, candidateId)"
      @select="selectCandidate"
      @resume="resumeCandidate"
    />
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { onLoad, onShow, onHide, onUnload, onResize } from "@dcloudio/uni-app";
import ChatSceneBackground from "@/components/chat/ChatSceneBackground.vue";
import ChatBubble from "@/components/chat/ChatBubble.vue";
import ChatActionBar, { type ChatActionBarItem } from "@/components/chat/ChatActionBar.vue";
import AvatarImage from "@/components/common/AvatarImage.vue";
import GroupChatDrawer from "@/components/chat/GroupChatDrawer.vue";
import GroupCandidateModal from "@/components/chat/GroupCandidateModal.vue";
import MemoryManagerModal from "@/components/chat/MemoryManagerModal.vue";
import PromptPreviewModal from "@/components/chat/PromptPreviewModal.vue";
import { compileGroupMemberPrompt } from "@/api/groupSessions";
import type { GroupCandidateSummary, GroupPromptPreview } from "@/types/groupSessions";
import GenerationSettingsSheet from "@/components/chat/GenerationSettingsSheet.vue";
import { useChatSettingsStore } from "@/store/chatSettingsStore";
import { getBaseUrl } from "@/api/config";
import { STORY_PALETTES } from "@/composables/useStoryKeepsakes";
import ChatHeader from "@/components/chat/ChatHeader.vue";
import ChatComposer from "@/components/chat/ChatComposer.vue";
import ChatScrollShell from "@/components/chat/ChatScrollShell.vue";
import { useChatScroll } from "@/composables/useChatScroll";
import AppStatusState from "@/components/common/AppStatusState.vue";
import GroupUtterances from "@/components/chat/GroupUtterances.vue";
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

const backToList = () => uni.navigateBack({ fail: () => uni.switchTab({ url: "/pages/index/index" }) });
const chatSettingsStore = useChatSettingsStore();
const state = useGroupSessionDetail(backToList, id => chatSettingsStore.requestGeneration(id, { ...chatSettingsStore.selection }));
const { group, loading, deleting, error, needsSelection, rounds, loadingRounds, roundsError, hasMoreRounds,
  current, canGenerate, draft, submitting, submittingKind, submittedContent, submittedBaseRoundId, recovering, operationError, notice, pending, operationBusy, locked, historyStale, canDelete,
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
const openMemberMemories = (personaId?: number) => {
  const target = personaId ?? drawerMember.value?.persona_id;
  if (target) {
    memoryPersonaId.value = target;
    showDetails.value = false;
  }
};

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
const scrollShellRef = ref<InstanceType<typeof ChatScrollShell> | null>(null);
onResize(({ size }) => {
  if (size) isWideScreen.value = size.windowWidth >= 900;
  scrollShellRef.value?.measureViewport();
});
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
const { scrollTop, scrollIntoViewId, scrollWithAnimation, keyboardHeight, isAndroid, isPinnedToBottom,
  followNewContent, pinToBottom, updateScrollMetrics, maintainScrollPosition, hasUnreadBelow, resetPinState, triggerPhasedScroll } = useChatScroll();
const inputWrapperStyle = computed(() => keyboardHeight.value > 0 ? { paddingBottom: '14rpx' } : {});
const onFocusChange = (focused: boolean) => {
  isFocused.value = focused;
  if (focused) triggerPhasedScroll();
};
const chronologicalRounds = computed(() => [...rounds.value].sort((a, b) => a.round_index - b.round_index));
type GroupRoundItem = (typeof chronologicalRounds.value)[number];
const pendingRoundTab = ref<Record<number, "pending" | "adopted">>({});
const activeOperationKind = computed(() => submittingKind.value || pending.value?.kind || current.value?.active_operation?.kind || null);
const hasPersistedNewSendRound = computed(() => {
  if (submittedBaseRoundId.value === null) return chronologicalRounds.value.length > 0;
  return chronologicalRounds.value.some(round => round.round_id > submittedBaseRoundId.value!);
});
const optimisticUserContent = computed(() => (
  !operationError.value && activeOperationKind.value === "send" && operationBusy.value && !hasPersistedNewSendRound.value
    ? (submittedContent.value || "")
    : ""
));
const nextRoundIndex = computed(() => (chronologicalRounds.value[chronologicalRounds.value.length - 1]?.round_index ?? 0) + 1);
const composerDisabled = computed(() =>
  !canSend.value && (!operationBusy.value || !!operationError.value || !!optimisticUserContent.value)
);
const waitingMembers = computed(() => (group.value?.members || []).slice(0, 3));
const isLatestRound = (round: GroupRoundItem) => {
  const latestId = current.value?.latest?.round_id;
  if (latestId !== undefined && latestId !== null) return round.round_id === latestId;
  return round.round_id === chronologicalRounds.value[chronologicalRounds.value.length - 1]?.round_id;
};
const isRoundRegenerating = (round: GroupRoundItem) =>
  round.pending_candidate?.status === "generating"
  || (isLatestRound(round) && !!operationBusy.value && !operationError.value
    && (activeOperationKind.value === "regenerate" || (activeOperationKind.value === "resume" && !!round.pending_candidate)));
const isRoundGenerating = (round: GroupRoundItem) =>
  round.status === "generating"
  || isRoundRegenerating(round)
  || (isLatestRound(round) && !!operationBusy.value && !operationError.value
    && (activeOperationKind.value === "resume" || (activeOperationKind.value === "send" && hasPersistedNewSendRound.value)));
const hasPausedOrFailedPendingCandidate = (round: GroupRoundItem) =>
  !!round.pending_candidate && !isRoundRegenerating(round);
const activeRoundTab = (round: GroupRoundItem): "pending" | "adopted" => {
  if (isRoundRegenerating(round)) return "pending";
  if (hasPausedOrFailedPendingCandidate(round)) return pendingRoundTab.value[round.round_id] ?? "pending";
  return "adopted";
};
const setRoundTab = (roundId: number, tab: "pending" | "adopted") => {
  pendingRoundTab.value = { ...pendingRoundTab.value, [roundId]: tab };
};
const displayedUtterances = (round: GroupRoundItem) =>
  activeRoundTab(round) === "pending" ? (round.pending_candidate?.utterances ?? []) : round.utterances;
const roundHeaderStatus = (round: GroupRoundItem) =>
  isRoundRegenerating(round) ? "重新生成中" : isRoundGenerating(round) ? "处理中" : roundStatus(round);
const waitingTitle = (round?: GroupRoundItem) => {
  if (round && isRoundRegenerating(round)) return "正在重新生成整轮回应";
  if (activeOperationKind.value === "resume") return "正在继续本轮回应";
  return `${memberNames.value || "群聊成员"} · 正在构思回应`;
};
const waitingSubtitle = (round?: GroupRoundItem) => {
  const steps = current.value?.active_operation?.call_count ?? 0;
  if (round && isRoundRegenerating(round)) {
    return steps > 0
      ? `已暂隐原采用回复，正在生成新候选（已推进 ${steps} 步）…`
      : "已暂隐原采用回复，新候选完成后将直接替换…";
  }
  return steps > 0
    ? `导演正在调度角色互动（已推进 ${steps} 步）…`
    : "导演正在安排角色登场，请稍候…";
};
const continuationCopy = (round: GroupRoundItem) =>
  `已有 ${displayedUtterances(round).length} 条角色发言，下一位角色正在回应…`;
const roundActionItems = (round: GroupRoundItem): ChatActionBarItem[] => {
  const items: ChatActionBarItem[] = [];
  if (current.value) {
    items.push({
      key: "candidates",
      label: "整轮候选",
      icon: "/static/icons/char_list.svg",
      disabled: submitting.value || deleting.value || loading.value,
    });
  }
  if (round.round_id === current.value?.latest?.round_id && !operationBusy.value) {
    if (round.error_code === "resource_paused" || round.pending_candidate?.error_code === "resource_paused") {
      items.push({
        key: "resume",
        label: "继续对话",
        icon: "/static/icons/chat_sparkle.svg",
        disabled: locked.value || !canGenerate.value || loadingCandidates.value,
      });
    }
    items.push(
      {
        key: "regenerate",
        label: "重新生成",
        icon: "/static/icons/drawer_sync.svg",
        disabled: !canRegenerate.value,
      },
      {
        key: "discard",
        label: "撤回",
        icon: "/static/icons/drawer_trash.svg",
        danger: true,
        disabled: !canDiscard.value,
      }
    );
  }
  return items;
};
const onRoundAction = (key: string, round: GroupRoundItem) => {
  if (key === "candidates") void openCandidates(round.round_id);
  else if (key === "resume") {
    followNewContent();
    void state.resumeRound(round, confirmResume);
  }
  else if (key === "regenerate") {
    followNewContent();
    void state.command("regenerate");
  }
  else if (key === "discard") void state.command("discard", undefined, confirmDiscard);
};
const onJumpToBottom = () => {
  scrollWithAnimation.value = true;
  pinToBottom();
};
const onReachTop = () => {
  if (hasMoreRounds.value && !loading.value && !loadingRounds.value && !deleting.value && !operationBusy.value) {
    void moreRounds();
  }
};
watch(() => {
  const latest = chronologicalRounds.value[chronologicalRounds.value.length - 1];
  const base = latest
    ? JSON.stringify([latest.round_id, latest.status, latest.utterances, latest.pending_candidate])
    : "";
  return `${base}:${optimisticUserContent.value}:${activeOperationKind.value}:${operationBusy.value}`;
}, () => followNewContent());
watch(() => group.value?.session_id, () => {
  drawerPersonaId.value = null; memoryPersonaId.value = null;
  pendingRoundTab.value = {};
  promptVersion++; promptPreview.value = null; promptLoading.value = false; promptError.value = "";
  isModelSettingsOpen.value = false;
  if (group.value) chatSettingsStore.activateSession(group.value.session_id);
  showDetails.value = false;
  showCandidates.value = false;
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
const openCandidates = async (roundId: number) => {
  const version = pageViewVersion, sessionId = group.value?.session_id, server = getBaseUrl();
  const valid = () => showCandidates.value && version === pageViewVersion && sessionId === group.value?.session_id
    && server === getBaseUrl() && candidateRoundId.value === roundId;
  showCandidates.value = true;
  await state.loadCandidates(roundId);
  if (!valid() || preview.value || loadingPreview.value) return;
  const list = candidates.value || [];
  if (!list.length) return;
  const preferred = list.find(item => item.selected || item.candidate_id === current.value?.latest?.candidate_id) || list[0];
  if (preferred) void state.viewCandidate(roundId, preferred.candidate_id);
};
const selectCandidate = async (candidate: GroupCandidateSummary) => {
  const targetId = candidate.candidate_id;
  await state.command('select', candidate);
  if (!operationError.value && (operationBusy.value || current.value?.latest?.candidate_id === targetId)) {
    showCandidates.value = false;
  }
};
const resumeCandidate = async (candidate: GroupCandidateSummary) => {
  await state.command('resume', candidate, confirmResume);
  if (!operationError.value && operationBusy.value) {
    showCandidates.value = false;
  }
};
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
@import "../../components/chat/chatTheme.css";
.group-chat-page :deep(.status-text) { max-width: 250rpx; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.group-transcript { flex: 1; display: flex; flex-direction: column; padding: 0 0 8rpx; }
.history-actions, .round-actions { display: flex; flex-wrap: wrap; justify-content: center; gap: 12rpx; }
.history-actions { margin: 8rpx 0 18rpx; }
.history-pill { margin: 0; padding: 8rpx 24rpx; min-height: 0; line-height: 1.4; border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08)); border-radius: var(--app-radius-pill, 999rpx); background-color: var(--app-color-surface-soft, rgba(255, 255, 255, 0.78)); }
.history-pill::after { border: 0; }
.history-pill[disabled] { opacity: .55; }
.history-pill-text { color: var(--app-color-text-secondary, #64716b); font-size: var(--app-font-size-caption, 22rpx); font-weight: 560; }
.is-immersive .history-pill { background-color: rgba(19, 31, 27, 0.72); border-color: rgba(255, 255, 255, 0.16); }
.is-immersive .history-pill-text { color: #d9e4df; }
.round-actions { justify-content: flex-start; padding: 0 32rpx 16rpx 116rpx; }
.round-divider { display: block; text-align: center; font-size: var(--app-font-size-caption); color: var(--app-color-text-muted); margin: 24rpx 0 12rpx; }
.round-notice { display: block; margin: 12rpx 28rpx; padding: 18rpx 24rpx; border-radius: 18rpx; background: var(--app-color-surface); font-size: 24rpx; line-height: 1.6; }
.round-candidate-switcher {
  display: flex; flex-direction: column; gap: 14rpx;
  margin: 10rpx 32rpx 14rpx; padding: 18rpx 22rpx;
  border-radius: 20rpx; background: var(--app-color-surface-soft, rgba(255, 255, 255, 0.82));
  border: 1px dashed var(--app-color-border-strong, rgba(38, 51, 46, 0.16));
}
.switcher-caption { font-size: 23rpx; line-height: 1.5; color: var(--app-color-text-secondary, #64716b); }
.switcher-pills { display: flex; flex-wrap: wrap; gap: 12rpx; }
.switcher-pill {
  display: inline-flex; align-items: center; min-height: 56rpx; padding: 0 22rpx;
  border-radius: var(--app-radius-pill, 999rpx);
  background-color: var(--app-color-surface, #ffffff);
  border: 1px solid var(--app-color-border-strong, rgba(38, 51, 46, 0.14));
  transition: background-color 0.18s ease, border-color 0.18s ease, transform 0.15s ease;
}
.switcher-pill:active { transform: scale(0.96); }
.switcher-pill.is-active {
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.16));
  border-color: var(--app-color-primary, #70ae9b);
}
.switcher-pill-text { font-size: 22rpx; font-weight: 560; color: var(--app-color-text-secondary, #64716b); }
.switcher-pill.is-active .switcher-pill-text { color: var(--app-color-primary-strong, #4f8e7c); font-weight: 650; }
.group-waiting-row {
  display: flex; width: 100%; padding: 14rpx 32rpx; gap: 18rpx; align-items: flex-start; box-sizing: border-box;
  animation: waiting-fade-in 0.28s cubic-bezier(0.16, 1, 0.3, 1) both;
}
.waiting-avatar-stack { display: flex; align-items: center; min-width: 72rpx; min-height: 72rpx; flex-shrink: 0; }
.waiting-avatar, .waiting-avatar-stack :deep(.waiting-avatar) {
  width: 44rpx; height: 44rpx; border-radius: 16rpx; flex-shrink: 0;
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
  border: 2rpx solid var(--app-color-surface, #ffffff);
  box-shadow: 0 6rpx 16rpx rgba(45, 72, 62, 0.12);
}
.waiting-avatar.is-stacked, .waiting-avatar-stack :deep(.waiting-avatar.is-stacked) { margin-left: -18rpx; }
.waiting-content-area { flex: 1; min-width: 0; max-width: calc(100% - 96rpx); display: flex; flex-direction: column; align-items: flex-start; }
.waiting-speaker-label {
  margin-bottom: 8rpx; margin-left: 10rpx;
  color: var(--app-color-primary-strong, #4f8e7c); font-size: var(--app-font-size-caption, 22rpx); font-weight: 650;
}
.waiting-bubble-card {
  padding: 20rpx 26rpx; border-radius: 26rpx; border-top-left-radius: 10rpx;
  background-color: var(--app-color-bubble-ai, rgba(255, 255, 255, 0.72));
  border: 1px solid var(--app-color-bubble-ai-border, rgba(112, 174, 155, 0.22));
  box-shadow: 0 10rpx 30rpx rgba(45, 72, 62, 0.05);
  animation: waiting-glow 2.4s ease-in-out infinite;
}
.waiting-pulse-row { display: flex; align-items: center; gap: 14rpx; flex-wrap: wrap; }
.waiting-subtitle { font-size: 24rpx; line-height: 1.5; color: var(--app-color-text-secondary, #64716b); }
.group-continuation-bar {
  display: inline-flex; align-items: center; align-self: flex-start; flex-wrap: wrap; gap: 12rpx;
  margin: 8rpx 32rpx 16rpx 122rpx; padding: 10rpx 20rpx;
  border-radius: var(--app-radius-pill, 999rpx);
  background-color: var(--app-color-surface-soft, rgba(255, 255, 255, 0.78));
  border: 1px solid var(--app-color-border, rgba(112, 174, 155, 0.18));
  box-shadow: 0 6rpx 18rpx rgba(45, 72, 62, 0.05);
}
.continuation-avatars { display: flex; align-items: center; flex-shrink: 0; }
.continuation-avatar, .continuation-avatars :deep(.continuation-avatar) {
  width: 30rpx; height: 30rpx; border-radius: 10rpx; flex-shrink: 0;
  border: 2rpx solid var(--app-color-surface, #ffffff);
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
}
.continuation-avatar.is-stacked, .continuation-avatars :deep(.continuation-avatar.is-stacked) { margin-left: -12rpx; }
.continuation-copy { font-size: 22rpx; line-height: 1.4; color: var(--app-color-text-secondary, #64716b); }
.ai-thinking { display: flex; align-items: center; gap: 8rpx; padding: 4rpx 2rpx; flex-shrink: 0; }
.ai-thinking.is-compact { gap: 6rpx; padding: 2rpx 0; }
.ai-dot {
  width: 10rpx; height: 10rpx; border-radius: 50%;
  background-color: var(--app-color-primary, #70ae9b);
  animation: group-ai-bounce 1.4s ease-in-out infinite;
}
.ai-thinking.is-compact .ai-dot { width: 8rpx; height: 8rpx; }
.ai-dot.delay-1 { animation-delay: 0.2s; }
.ai-dot.delay-2 { animation-delay: 0.4s; }
@keyframes group-ai-bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.35; }
  30% { transform: translateY(-7rpx); opacity: 1; }
}
@keyframes waiting-glow {
  0%, 100% { border-color: var(--app-color-bubble-ai-border, rgba(112, 174, 155, 0.22)); }
  50% { border-color: var(--app-color-primary, #70ae9b); }
}
@keyframes waiting-fade-in {
  from { opacity: 0; transform: translateY(12rpx); }
  to { opacity: 1; transform: translateY(0); }
}
.is-immersive .round-actions, .is-immersive .round-notice, .is-immersive .round-divider, .is-immersive .composer-feedback {
  --app-color-surface: rgba(20,34,28,.92); --app-color-border: rgba(255,255,255,.18);
  --app-color-border-strong: rgba(255,255,255,.35); --app-color-text-secondary: #e0eae4;
  --app-color-primary-strong: #d2eddf; --app-color-danger: #ffb5ad;
}
.is-immersive .round-divider { color: #e0eae4; text-shadow: 0 1px 4px #14221c; }
.is-immersive .waiting-speaker-label { color: #ffffff; text-shadow: 0 1px 5px rgba(0, 0, 0, 0.7); }
.is-immersive .waiting-bubble-card {
  background-color: rgba(19, 29, 27, 0.72); border-color: rgba(255, 255, 255, 0.2);
}
.is-immersive .waiting-subtitle, .is-immersive .continuation-copy { color: #e0eae4; }
.is-immersive .group-continuation-bar {
  background-color: rgba(19, 29, 27, 0.74); border-color: rgba(255, 255, 255, 0.2);
}
.is-immersive .round-candidate-switcher {
  background-color: rgba(20, 34, 28, 0.86); border-color: rgba(255, 255, 255, 0.22);
}
.is-immersive .switcher-caption { color: #d9e4df; }
.is-immersive .switcher-pill {
  background-color: rgba(255, 255, 255, 0.08); border-color: rgba(255, 255, 255, 0.2);
}
.is-immersive .switcher-pill.is-active {
  background-color: rgba(157, 207, 179, 0.24); border-color: rgba(210, 237, 223, 0.55);
}
.is-immersive .switcher-pill-text { color: #e0eae4; }
.is-immersive .switcher-pill.is-active .switcher-pill-text { color: #ffffff; }
@media (prefers-reduced-motion: reduce) {
  .group-waiting-row, .waiting-bubble-card, .ai-dot { animation: none !important; }
}
.composer-feedback { display: flex; align-items: center; gap: 16rpx; margin: 8rpx 24rpx; padding: 18rpx 22rpx; border-radius: 20rpx; color: var(--app-color-text-secondary); background: var(--app-color-surface); border: 1px solid var(--app-color-border); }
.composer-feedback.is-error { color: var(--app-color-danger); }
.feedback-copy { flex: 1; min-width: 0; font-size: 24rpx; line-height: 1.6; overflow-wrap: anywhere; }
.feedback-action { flex-shrink: 0; margin: 0; padding: 10rpx 16rpx; min-height: 72rpx; line-height: 1.5; font-size: 24rpx; background: transparent; color: var(--app-color-primary-strong); }
.feedback-action::after { border: 0; }
.group-composer { flex-shrink: 0; }
.group-composer .group-card { margin: 0; padding: 0 32rpx; background: transparent; border: 0; }
.group-composer .group-copy, .group-composer .group-error { margin: 8rpx 0; font-size: var(--app-font-size-caption); }
button.group-action { margin: 4rpx 0; background: transparent; border-radius: var(--app-radius-sm); }
button.group-action::after { border: none; }
button.group-action[disabled] { opacity: .45; }
</style>
