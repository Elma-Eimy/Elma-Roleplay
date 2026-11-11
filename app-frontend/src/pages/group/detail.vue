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
              <text class="group-copy">{{ round.pending_candidate.status === 'failed' ? '重新生成未完成，以下回复已保留，尚未采用。' : '正在重新生成，以下回复尚未采用。' }}</text>
              <GroupUtterances :utterances="round.pending_candidate.utterances" :members="group.members" />
            </template>
            <text v-if="groupRoundNotice(round)" :class="round.status === 'failed' ? 'group-error round-notice' : 'group-copy round-notice'">{{ groupRoundNotice(round) }}</text>
            <view class="round-actions">
              <button v-if="current" class="group-action" :disabled="submitting || deleting || loading" @tap="openCandidates(round.round_id)">整轮候选</button>
              <template v-if="round.round_id === current?.latest?.round_id">
                <button class="group-action" :disabled="!canRegenerate" @tap="state.command('regenerate')">重新生成</button>
                <button class="group-action group-danger" :disabled="!canDiscard" @tap="state.command('discard', undefined, confirmDiscard)">撤回</button>
              </template>
            </view>
          </view>
        </view>
      </scroll-view>
      <button v-if="hasUnreadBelow" class="group-action unread-button" @tap="pinToBottom">查看最新消息 ↓</button>
      <view v-if="group" class="group-composer">
          <view class="group-card">
            <text v-if="!current || !canGenerate" class="group-copy">{{ !current ? '当前仅可阅读。请刷新发言，或连接支持群聊操作的后端。' : '生成服务暂不可用，已有内容仍可阅读。' }}</text>
            <text v-if="pending || current?.active_operation" class="group-copy">{{ submitting ? '正在提交…' : recovering ? '正在查询进展…' : '已有请求正在处理或结果待确认，请先查询。' }}</text>
            <text v-if="notice" class="group-copy" role="status">{{ notice }}</text>
            <text v-if="operationError" class="group-error" role="alert">{{ operationError }}</text>
            <text v-if="historyStale" class="group-copy" role="status">剧情已有更新，请刷新当前采用的发言后再操作。</text>
            <button v-if="historyStale" class="group-action" :disabled="loading || loadingRounds || operationBusy" @tap="refreshRounds">刷新消息</button>
            <button role="button" v-if="pending || current?.active_operation" class="group-action" :disabled="recovering || submitting || loading" @tap="state.recover">查询请求结果</button>
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
    <view v-if="showDetails && group" class="status-panel-backdrop" :class="{ 'is-android': isAndroid }" @tap="showDetails = false">
      <view class="status-panel" role="dialog" aria-label="群聊资料" @tap.stop>
        <view class="panel-header"><text class="drawer-title">群聊资料</text><button class="close-btn" aria-label="关闭群聊资料" @tap="showDetails = false"><image class="close-icon" src="/static/icons/drawer_close.svg" /></button></view>
        <scroll-view class="panel-content" scroll-y><view class="drawer-body">
          <view class="char-card group-hero">
            <view class="char-card-info"><text class="char-card-name">{{ group.title }}</text><text class="hero-subtitle">{{ group.members.length }} 位角色</text></view>
            <view class="group-avatars"><button v-for="member in group.members" :key="member.persona_id" class="profile-avatar-link" :aria-label="`查看${member.character.name}的人物档案`" :disabled="openingProfile || loading || !member.character.id" @tap.stop="openCharacterProfile(member.persona_id)"><AvatarImage class="char-card-avatar" :src="getAvatarUrl(member.character.avatar_path || '')" /></button></view>
          </view>
          <view class="drawer-tabs"><button v-for="tab in drawerTabs" :key="tab.id" class="drawer-tab" :class="{ 'is-active': drawerTab === tab.id }" @tap="selectDrawerTab(tab.id)">{{ tab.label }}</button></view>
          <template v-if="drawerTab === 'members'">
            <view class="panel-section">
              <text class="group-heading">各角色提示词组装</text>
              <text class="group-copy">预览当前剧情后的组装结果，与生成使用同一入口；不是上一条回复的请求存档。</text>
              <button v-for="member in group.members" :key="member.persona_id" class="group-action" :disabled="promptLoading || !current?.latest?.candidate_id" @tap="openMemberPrompt(member.persona_id)">查看 {{ member.character.name }} 的提示词</button>
              <text v-if="promptError" class="group-error">{{ promptError }}</text>
            </view>
            <view v-if="!current?.latest?.candidate_id" class="panel-section">
              <view v-for="member in group.members" :key="member.persona_id" class="member-summary">
                <button class="profile-avatar-link" :aria-label="`查看${member.character.name}的人物档案`" :disabled="openingProfile || loading || !member.character.id" @tap.stop="openCharacterProfile(member.persona_id)"><AvatarImage class="member-summary-avatar" :src="getAvatarUrl(member.character.avatar_path || '')" /></button>
                <view class="member-name"><text class="group-heading">{{ member.character.name }}</text><text class="group-copy">{{ member.state.current_mood || '—' }} · {{ member.state.affection_score ?? 0 }} / 100</text></view>
              </view>
            </view>
          <view v-if="current?.latest?.candidate_id" class="panel-section">
            <view class="group-row"><text class="group-heading">当前采用的成员状态</text><button class="group-action" :aria-expanded="showMemberStates" @tap="toggleMemberStates">{{ showMemberStates ? '收起' : '查看' }}</button></view>
            <template v-if="showMemberStates">
              <text class="group-copy">状态对应当前采用的剧情，候选预览不会改变这里的内容。</text>
              <text v-if="operationBusy" class="group-copy" role="status">正在处理请求，结果确认后可重新读取成员状态。</text>
              <text v-else-if="!current" class="group-copy">请先刷新发言，取得当前采用信息后再读取成员状态。</text>
              <text v-else-if="!current?.latest?.candidate_id" class="group-copy">尚无采用候选，成员初始资料可在上方“设定与成员起点”查看。</text>
              <text v-else-if="historyStale" class="group-copy">剧情已有更新，请先刷新发言。</text>
              <template v-else>
                <text v-if="loadingAdoptedState" class="group-copy" role="status">正在读取成员状态…</text>
                <text v-else-if="adoptedStateError" class="group-error" role="alert">{{ adoptedStateError }}</text>
                <text v-else-if="!adoptedState" class="group-copy">请重新读取此轮成员状态。</text>
                <template v-if="adoptedState">
                  <text class="group-caption">第 {{ adoptedState.round.round_index }} 轮 · 候选 {{ adoptedState.candidate.version }} · 当前采用</text>
                  <text v-if="adoptedState.candidate.status === 'failed'" class="group-copy">本轮未完成，状态只反映已经保存的发言。</text>
                  <GroupMemberStates :states="adoptedState.state_preview.members" :members="group.members" :user-nickname="group.user_nickname" />
                </template>
                <button class="group-action" :disabled="loadingAdoptedState || loading || deleting" @tap="state.loadAdoptedState">{{ loadingAdoptedState ? '正在读取…' : '重新读取成员状态' }}</button>
              </template>
            </template>
          </view>
          </template>
          <template v-if="drawerTab === 'origins'">
          <view v-if="showOrigins" class="panel-section">
            <text class="group-heading">共同设定</text>
            <text class="group-copy">{{ group.shared_setting || '未填写共同设定，角色保留各自的角色卡设定。' }}</text>
            <text class="group-copy">以下是入群时固定的成员起点，不随剧情或候选预览改变。</text>
          </view>
          <template v-if="showOrigins">
          <view v-for="member in group.members" :key="member.persona_id" class="panel-section">
            <view class="group-row"><button class="profile-avatar-link" :aria-label="`查看${member.character.name}的人物档案`" :disabled="openingProfile || loading || !member.character.id" @tap.stop="openCharacterProfile(member.persona_id)"><AvatarImage class="group-avatar" :src="getAvatarUrl(member.character.avatar_path || '')" /></button><view class="member-name"><text class="group-heading">{{ member.character.name }}</text><text class="group-caption">成员 {{ member.slot }}</text></view></view>
            <text class="group-label">{{ member.origin.mode === 'card' ? '从原卡开始' : '导入单聊快照' }}</text>
            <text class="group-copy">{{ member.origin.mode === 'card' ? '没有导入单聊状态与私人记忆。' : `来源故事 #${member.origin.source_session_id} · 已导入 ${member.origin.inherited_memory_count} 张记忆卡` }}</text>
            <text v-if="member.origin.mode === 'single_snapshot'" class="group-copy">导入时间：{{ formatTime(member.origin.captured_at) }}。来源故事之后的变化不会回写到此起点。</text>
            <text class="group-copy">起点好感度：{{ member.state.affection_score ?? '未记录' }}　起点心情：{{ member.state.current_mood || '未记录' }}</text>
            <text v-if="member.state.role_state.scene || member.state.current_scenario_override" class="group-copy">场景：{{ member.state.role_state.scene || member.state.current_scenario_override }}</text>
            <text class="group-label">认知</text><text class="group-copy">{{ member.state.cognition_state || '尚未建立认知摘要。' }}</text>
            <view v-for="(actor, name) in member.state.role_state.characters" :key="name" class="group-copy"><text>{{ name }}：{{ actorDescription(actor) }}</text></view>
          </view>
          </template>
          </template>
          <template v-if="drawerTab === 'appearance'">
            <view class="panel-section">
              <text class="section-title">故事模型</text>
              <text class="group-copy">{{ chatSettingsStore.modelSummary }}</text>
              <button class="action-btn outline" @tap="openModelSettings"><text class="btn-text">选择模型与思考强度</text></button>
              <text class="group-copy">发送与重新生成使用当前选择；继续未完成候选时沿用原参数。</text>
            </view>
            <view class="panel-section"><ChatReadingPreferences /></view>
            <view class="panel-section group-background-settings">
              <text class="section-title">聊天背景</text>
              <view class="background-mode-picker">
                <button class="background-mode-option" :class="{ 'is-active': backgroundMode === 'clean' }" @tap="setBackgroundMode('clean')"><view class="background-mode-preview preview-clean" /><text class="background-mode-label">纯净背景</text></button>
                <button class="background-mode-option" :class="{ 'is-active': backgroundMode === 'character' }" @tap="setBackgroundMode('character')"><view class="background-mode-preview preview-character"><AvatarImage class="background-mode-avatar" :src="backgroundUrl" /></view><text class="background-mode-label">角色立绘</text></button>
              </view>
              <text class="group-copy">默认跟随最后发言的成员，也可固定查看一名角色。</text>
              <view class="background-members">
                <button class="background-member" :class="{ 'is-active': focusedPersona === null }" @tap="focusedPersona = null">跟随发言</button>
                <button v-for="member in group.members" :key="member.persona_id" class="background-member" :class="{ 'is-active': focusedPersona === member.persona_id }" @tap="focusedPersona = member.persona_id">{{ member.character.name }}</button>
              </view>
            </view>
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
          <template v-if="drawerTab === 'manage'">
          <text v-if="error" class="group-error" role="alert">{{ error }}</text>
          <view class="group-action" role="button" :aria-disabled="loading || deleting" @tap="state.load">{{ loading ? '正在刷新…' : '刷新详情' }}</view>

          <view  class="panel-section">
            <text class="group-copy">删除会移除全部成员与本群数据，来源单聊和角色卡会保留。</text>
            <button class="action-btn danger-btn group-delete" :disabled="!canDelete" @tap="remove"><image class="danger-icon" src="/static/icons/drawer_trash.svg" /><text class="danger-btn-text">{{ deleting ? '正在处理…' : '删除整个群聊' }}</text></button>
          </view>
          </template>
        </view></scroll-view>
      </view>
    </view>
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
import ChatReadingPreferences from "@/components/chat/ChatReadingPreferences.vue";
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
import type { ActorState } from "@/types/roleState";
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
    if (valid()) promptPreview.value = result;
  } catch (cause) { if (valid()) promptError.value = cause instanceof Error ? cause.message : String(cause); }
  finally { if (valid()) promptLoading.value = false; }
}

const backToList = () => uni.navigateBack({ fail: () => uni.redirectTo({ url: "/pages/group/index" }) });
const chatSettingsStore = useChatSettingsStore();
const state = useGroupSessionDetail(backToList, id => chatSettingsStore.requestGeneration(id, { ...chatSettingsStore.selection }));
const showOrigins = ref(false), showManagement = ref(false), showMemberStates = ref(false), showPortraits = ref(false);
const { group, loading, deleting, error, needsSelection, rounds, loadingRounds, roundsError, hasMoreRounds,
  current, canGenerate, draft, submitting, recovering, operationError, notice, pending, operationBusy, locked, historyStale, canDelete,
  canSend, canRegenerate, canDiscard, candidates, candidateRoundId, loadingCandidates, candidatesError,
  hasMoreCandidates, preview, loadingPreview, previewError, adoptedState, loadingAdoptedState, adoptedStateError,
  portraitData, loadingPortraits, portraitWriting, portraitError, portraitOptions, canChoosePortrait } = state;
const palette = STORY_PALETTES[0];
const paletteStyle = { '--story-accent': palette.color, '--story-soft': palette.soft, '--story-mist': palette.mist };
const hasGreetings = computed(() => !!group.value?.members.some(member => member.greeting_content?.trim()));
const backgroundMode = ref<'clean' | 'character'>('character');
const focusedPersona = ref<number | null>(null);
const isPortraitOnly = ref(false);
const isWideScreen = ref(uni.getSystemInfoSync().windowWidth >= 900);
const drawerTab = ref('members');
const drawerTabs = [{ id: 'members', label: '成员' }, { id: 'appearance', label: '外观' }, { id: 'origins', label: '起点' }, { id: 'manage', label: '管理' }];
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
  if (group.value && current.value && !loading.value && !loadingRounds.value && !operationBusy.value) void state.loadPortraits();
});
onResize(({ size }) => { if (size) isWideScreen.value = size.windowWidth >= 900; });
const openDetails = () => {
  showDetails.value = true;
  showMemberStates.value = true;
  if (drawerTab.value === 'members') void state.loadAdoptedState();
};
const selectDrawerTab = (tab: string) => {
  drawerTab.value = tab;
  showOrigins.value = true;
  showManagement.value = true;
  showMemberStates.value = true;
  showPortraits.value = true;
  if (tab === 'members') void state.loadAdoptedState();
  if (tab === 'appearance') void state.loadPortraits();
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
const openingProfile = ref(false);
let profileNavigationVersion = 0;
const resetProfileNavigation = () => { profileNavigationVersion++; openingProfile.value = false; };
const openCharacterProfile = (personaId: number) => {
  const member = group.value?.members.find(row => row.persona_id === personaId);
  if (!showDetails.value || !member?.character.id || loading.value || openingProfile.value) return;
  const sessionId = group.value!.session_id, server = getBaseUrl(), version = ++profileNavigationVersion;
  const valid = () => version === profileNavigationVersion && group.value?.session_id === sessionId && getBaseUrl() === server;
  openingProfile.value = true;
  uni.navigateTo({
    url: `/pages/character/detail?id=${member.character.id}`,
    success: () => { if (valid()) showDetails.value = false; },
    fail: () => { if (valid()) uni.showToast({ title: '无法打开人物档案，请重试', icon: 'none' }); },
    complete: () => { if (valid()) openingProfile.value = false; },
  });
};
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
  promptVersion++; promptPreview.value = null; promptLoading.value = false; promptError.value = "";
  isModelSettingsOpen.value = false;
  if (group.value) chatSettingsStore.activateSession(group.value.session_id);
  resetProfileNavigation();
  showDetails.value = false;
  showCandidates.value = false;
  showOrigins.value = false;
  showMemberStates.value = false;
  showPortraits.value = false;
  showManagement.value = false;
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
const toggleMemberStates = () => {
  showMemberStates.value = !showMemberStates.value;
  if (showMemberStates.value) void state.loadAdoptedState();
};
const memberNames = computed(() => group.value?.members.map(member => member.character.name).join(" · ") || "");
onLoad(options => state.setSessionId(Number(options?.sessionId)));
onShow(() => {
  if (group.value) chatSettingsStore.activateSession(group.value.session_id);
  void chatSettingsStore.refreshModels();
  state.show();
});
const hide = () => { promptVersion++; promptPreview.value = null; promptLoading.value = false; pageViewVersion++; resetProfileNavigation(); isModelSettingsOpen.value = false; isFocused.value = false; showDetails.value = false; showCandidates.value = false; state.hide(); };
onHide(hide); onUnload(hide);
const formatTime = (value: string) => value.replace("T", " ").slice(0, 19);
const actorDescription = (actor: ActorState) => [actor.posture, actor.clothing, actor.location].filter(Boolean).join(" · ");
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
.group-chat-page .status-panel { color: #26332e; }
.drawer-title { margin-right: auto; margin-left: 32rpx; font-size: 26rpx; font-weight: 650; color: #26332e; }
.group-chat-page .close-btn { margin: 0; padding: 0; flex-shrink: 0; }
.group-delete::after { border: 0; }
.group-delete[disabled] { opacity: .45; }
.group-chat-page :deep(.status-text) { max-width: 250rpx; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.drawer-body { padding-bottom: calc(32rpx + env(safe-area-inset-bottom)); }
.group-hero { flex-direction: column; align-items: stretch; gap: 8rpx; }
.group-hero .char-card-info { flex-direction: row; justify-content: space-between; align-items: center; }
.hero-subtitle { color: rgba(255,255,255,.6); font-size: 22rpx; }
.group-hero .group-avatars { margin: 12rpx 0 0; }
.group-hero .char-card-avatar { width: 80rpx; height: 80rpx; }
.profile-avatar-link { display: flex; flex-shrink: 0; margin: 0; padding: 0; line-height: 0; background: transparent; border-radius: 24rpx; }
.profile-avatar-link::after { border: 0; }
.drawer-tabs { display: flex; margin: 0 20rpx 24rpx; padding: 6rpx; gap: 4rpx; background: rgba(38,51,46,.06); border-radius: 16rpx; }
.drawer-tab { flex: 1; margin: 0; padding: 14rpx 0; line-height: 1.4; background: transparent; color: #7c8983; font-size: 24rpx; border-radius: 12rpx; }
.drawer-tab.is-active { color: #3f7e6d; background: #fff; box-shadow: 0 2rpx 8rpx rgba(0,0,0,.04); font-weight: 650; }
.drawer-tab::after, .close-btn::after, .background-member::after, .background-mode-option::after { border: 0; }
.member-summary { display: flex; align-items: center; gap: 18rpx; padding: 20rpx 0; }
.member-summary + .member-summary { border-top: 1px solid rgba(0,0,0,.05); }
.member-summary-avatar { width: 72rpx; height: 72rpx; border-radius: 24rpx; flex-shrink: 0; }
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
.round-notice { padding: 0 32rpx; }
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
</style>
