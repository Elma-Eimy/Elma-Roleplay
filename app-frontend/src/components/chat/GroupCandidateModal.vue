<template>
  <view
    v-if="isOpen && group"
    class="modal-backdrop"
    :class="{ 'is-android': isAndroid }"
    @tap="emit('close')"
  >
    <view class="candidate-modal" role="dialog" aria-label="整轮候选" @tap.stop>
      <view class="modal-header">
        <view class="header-copy">
          <text class="modal-title">整轮候选</text>
          <text class="modal-subtitle">
            查看或切换整轮角色回复与状态，不影响已确认的更早轮次
          </text>
        </view>
        <view class="header-actions">
          <button
            v-if="candidateRoundId"
            role="button"
            class="candidate-pill-btn"
            :disabled="submitting || loadingCandidates || deleting"
            @tap="emit('refresh', candidateRoundId)"
          >
            <image class="pill-icon" src="/static/icons/drawer_sync.svg" mode="aspectFit" />
            <text>刷新</text>
          </button>
          <view class="close-btn" role="button" aria-label="关闭" @tap="emit('close')">
            <image class="close-icon" src="/static/icons/drawer_close.svg" mode="aspectFit" />
          </view>
        </view>
      </view>

      <scroll-view class="modal-scroll" scroll-y>
        <view class="modal-body">
          <view v-if="candidateRoundId" class="candidate-section">
            <text class="candidate-notice-banner">
              查看候选不会改变采用内容。只有完整候选才能切换采用；失败前缀可查看或显式继续。
            </text>

            <view v-if="loadingCandidates" class="candidate-status-tip">
              <text class="candidate-status-text">正在读取候选…</text>
            </view>

            <view class="candidate-list">
              <view
                v-for="candidate in candidates"
                :key="candidate.candidate_id"
                class="candidate-card"
                :class="{
                  'is-selected': isSelected(candidate.candidate_id),
                  'is-previewing': preview?.candidate.candidate_id === candidate.candidate_id,
                }"
                @tap="!submitting && !deleting && candidateRoundId && emit('view', candidateRoundId, candidate.candidate_id)"
              >
                <view class="candidate-card-head">
                  <text class="candidate-version">候选 {{ candidate.version }}</text>
                  <view class="candidate-badges">
                    <text
                      class="candidate-badge"
                      :class="{
                        'is-failed': candidate.status === 'failed' && candidate.error_code !== 'resource_paused',
                        'is-paused': candidate.error_code === 'resource_paused',
                      }"
                    >
                      {{ candidateStatus(candidate.status, candidate.error_code) }}
                    </text>
                    <text v-if="isSelected(candidate.candidate_id)" class="candidate-badge is-adopted">
                      当前采用
                    </text>
                  </view>
                </view>

                <view class="candidate-actions">
                  <button
                    role="button"
                    class="candidate-action-btn"
                    :class="{ 'is-previewing': preview?.candidate.candidate_id === candidate.candidate_id }"
                    :disabled="submitting || deleting"
                    @tap.stop="emit('view', candidateRoundId, candidate.candidate_id)"
                  >
                    {{ preview?.candidate.candidate_id === candidate.candidate_id ? '正在预览' : '查看正文与状态' }}
                  </button>
                  <button
                    v-if="candidate.can_select && !isSelected(candidate.candidate_id)"
                    role="button"
                    class="candidate-action-btn is-primary"
                    :disabled="locked || loadingCandidates || !!candidatesError"
                    @tap.stop="emit('select', candidate)"
                  >
                    采用此候选
                  </button>
                  <button
                    v-if="candidate.can_resume"
                    role="button"
                    class="candidate-action-btn is-accent"
                    :disabled="locked || !canGenerate || loadingCandidates || !!candidatesError"
                    @tap.stop="emit('resume', candidate)"
                  >
                    继续此候选
                  </button>
                </view>
              </view>
            </view>

            <text v-if="candidatesError" class="candidate-error-text" role="alert">
              {{ candidatesError }}
            </text>

            <button
              v-if="hasMoreCandidates"
              role="button"
              class="candidate-load-more"
              :disabled="loadingCandidates || submitting || deleting"
              @tap="emit('load-more', candidateRoundId)"
            >
              加载更早候选
            </button>

            <view v-if="loadingPreview" class="candidate-status-tip">
              <text class="candidate-status-text">正在读取候选正文…</text>
            </view>
            <text v-if="previewError" class="candidate-error-text" role="alert">
              {{ previewError }}，可再次点击查看。
            </text>

            <view v-if="preview" class="candidate-preview">
              <view class="preview-header">
                <text class="preview-title">
                  候选 {{ preview.candidate.version }} · {{ isSelected(preview.candidate.candidate_id) ? '当前采用' : '仅预览，未采用' }}
                </text>
              </view>

              <view class="preview-transcript">
                <ChatBubble
                  :message="{ id: -preview.round.round_id * 10 - 2, role: 'user', status: 'done', content: preview.round.user_content }"
                  :user-nickname="group.user_nickname"
                  read-only
                />
                <GroupUtterances
                  :utterances="preview.utterances"
                  :members="group.members"
                  :portraits="previewPortraits"
                  :user-nickname="group.user_nickname"
                />
              </view>

              <text v-if="preview.candidate.status === 'failed'" class="candidate-error-text">
                此候选未完成，以上仅为已保存前缀，不会作为完整结果确认。
              </text>
              <text v-else-if="!preview.utterances.length" class="candidate-status-text">
                此候选尚无角色发言。
              </text>

              <text class="preview-section-label">此候选的状态预览</text>
              <GroupMemberStates
                :states="preview.state_preview.members"
                :members="group.members"
                :user-nickname="group.user_nickname"
              />
            </view>
          </view>
        </view>
      </scroll-view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from "vue";
import ChatBubble from "./ChatBubble.vue";
import GroupUtterances from "./GroupUtterances.vue";
import GroupMemberStates from "./GroupMemberStates.vue";
import type {
  GetGroupCandidateResponse,
  GroupCandidateSummary,
  GroupCurrentState,
  GroupSessionDetail,
} from "@/types/groupSessions";

const props = withDefaults(
  defineProps<{
    isOpen: boolean;
    group: GroupSessionDetail | null;
    current: GroupCurrentState | null;
    candidateRoundId: number | null;
    candidates: GroupCandidateSummary[];
    loadingCandidates: boolean;
    candidatesError: string;
    hasMoreCandidates: boolean;
    preview: GetGroupCandidateResponse | null;
    loadingPreview: boolean;
    previewError: string;
    submitting: boolean;
    deleting: boolean;
    locked: boolean;
    canGenerate: boolean;
    isAndroid?: boolean;
  }>(),
  {
    isAndroid: false,
  }
);

const emit = defineEmits<{
  (e: "close"): void;
  (e: "refresh", roundId: number): void;
  (e: "load-more", roundId: number): void;
  (e: "view", roundId: number, candidateId: number): void;
  (e: "select", candidate: GroupCandidateSummary): void;
  (e: "resume", candidate: GroupCandidateSummary): void;
}>();

const isSelected = (id: number) =>
  props.candidateRoundId === props.current?.latest?.round_id
    ? props.current.latest.candidate_id === id
    : props.preview?.round.selected_candidate_id === id ||
      props.candidates.some((row) => row.candidate_id === id && row.selected);

const candidateStatus = (status: string, code?: string | null) =>
  code === "resource_paused"
    ? "已暂停"
    : status === "failed"
      ? "未完成"
      : status === "generating"
        ? "处理中"
        : "完整结果";

const previewPortraits = computed(
  () => props.preview?.state_preview.members.flatMap((row) => (row.portrait ? [row.portrait] : [])) || []
);
</script>

<style scoped>
.modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: rgba(15, 23, 20, 0.42);
  backdrop-filter: blur(10px);
  z-index: 120;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.2s ease;
}

.modal-backdrop.is-android {
  backdrop-filter: none;
  background-color: rgba(15, 23, 20, 0.56);
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.candidate-modal {
  width: 92vw;
  max-width: 780rpx;
  height: 84vh;
  background-color: #f6f8f7;
  color: #26332e;
  --app-color-text-primary: #26332e;
  --app-color-text-secondary: #64716b;
  --app-color-text-muted: #7c8983;
  --app-color-primary-strong: #3f7e6d;
  --app-color-primary-soft: #e8f1ed;
  --app-color-border: #e6ebe8;
  --app-color-border-strong: #d3ddd8;
  --app-color-surface: #ffffff;
  --app-color-surface-soft: #ffffff;
  --app-color-background: #f6f8f7;
  --app-color-danger: #d9655d;
  border-radius: 32rpx;
  display: flex;
  flex-direction: column;
  box-shadow: 0 24rpx 64rpx rgba(18, 30, 25, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.7);
  animation: modalScaleUp 0.24s cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
}

@keyframes modalScaleUp {
  from { opacity: 0; transform: scale(0.96); }
  to { opacity: 1; transform: scale(1); }
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20rpx;
  padding: 28rpx 32rpx 22rpx;
  background-color: #ffffff;
  border-bottom: 1px solid #e9eeeb;
}

.header-copy {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6rpx;
}

.modal-title {
  font-size: 32rpx;
  font-weight: 700;
  color: #26332e;
}

.modal-subtitle {
  font-size: 22rpx;
  line-height: 1.4;
  color: #7c8983;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 14rpx;
  flex-shrink: 0;
}

.candidate-pill-btn {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  min-height: 56rpx;
  margin: 0;
  padding: 0 20rpx;
  border-radius: 999rpx;
  border: 1px solid #dce4e0;
  background-color: #f6f8f7;
  color: #3f7e6d;
  font-size: 24rpx;
  font-weight: 600;
  line-height: 1;
}

.candidate-pill-btn::after {
  border: 0;
}

.candidate-pill-btn[disabled] {
  opacity: 0.48;
}

.pill-icon {
  width: 24rpx;
  height: 24rpx;
}

.close-btn {
  width: 56rpx;
  height: 56rpx;
  border-radius: 50%;
  background-color: rgba(38, 51, 46, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
}

.close-btn:active {
  background-color: rgba(38, 51, 46, 0.12);
}

.close-icon {
  width: 24rpx;
  height: 24rpx;
  opacity: 0.7;
}

.modal-scroll {
  flex: 1;
  height: 0;
  min-height: 0;
}

.modal-body {
  box-sizing: border-box;
  padding: 24rpx 28rpx calc(36rpx + env(safe-area-inset-bottom));
}

.candidate-section {
  display: flex;
  flex-direction: column;
  gap: 18rpx;
}

.candidate-notice-banner {
  display: block;
  padding: 18rpx 22rpx;
  border-radius: 18rpx;
  background-color: #ffffff;
  border: 1px solid #e6ebe8;
  color: #64716b;
  font-size: 23rpx;
  line-height: 1.55;
}

.candidate-status-tip {
  padding: 12rpx 4rpx;
}

.candidate-status-text {
  display: block;
  font-size: 24rpx;
  color: #64716b;
  line-height: 1.6;
}

.candidate-error-text {
  display: block;
  padding: 16rpx 20rpx;
  border-radius: 16rpx;
  background-color: #fdf2f1;
  border: 1px solid #f4d3d0;
  color: #d9655d;
  font-size: 24rpx;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.candidate-list {
  display: flex;
  flex-direction: column;
  gap: 14rpx;
}

.candidate-card {
  padding: 22rpx 24rpx;
  border-radius: 22rpx;
  background-color: #ffffff;
  border: 2rpx solid #e6ebe8;
  display: flex;
  flex-direction: column;
  gap: 16rpx;
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, background-color 0.18s ease, transform 0.14s ease;
}

.candidate-card:active {
  transform: scale(0.99);
}

.candidate-card.is-selected {
  background-color: #f4faf7;
  border-color: #b7d7ca;
}

.candidate-card.is-previewing {
  border-color: #3f7e6d;
  box-shadow: 0 8rpx 24rpx rgba(63, 126, 109, 0.14);
}

.candidate-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
}

.candidate-version {
  font-size: 28rpx;
  font-weight: 650;
  color: #26332e;
}

.candidate-badges {
  display: flex;
  align-items: center;
  gap: 10rpx;
  flex-wrap: wrap;
}

.candidate-badge {
  padding: 4rpx 14rpx;
  border-radius: 999rpx;
  font-size: 21rpx;
  font-weight: 600;
  background-color: #eef3f0;
  color: #64716b;
}

.candidate-badge.is-adopted {
  background-color: #e2eee8;
  color: #3f7e6d;
}

.candidate-badge.is-paused {
  background-color: #fcf3e3;
  color: #9e6a1c;
}

.candidate-badge.is-failed {
  background-color: #fdf0ef;
  color: #d9655d;
}

.candidate-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
}

.candidate-action-btn {
  margin: 0;
  min-height: 60rpx;
  padding: 0 22rpx;
  border-radius: 999rpx;
  border: 1px solid #d7e0dc;
  background-color: #ffffff;
  color: #26332e;
  font-size: 23rpx;
  font-weight: 560;
  line-height: 60rpx;
}

.candidate-action-btn::after {
  border: 0;
}

.candidate-action-btn[disabled] {
  opacity: 0.45;
}

.candidate-action-btn.is-previewing {
  border-color: #3f7e6d;
  background-color: #eef7f3;
  color: #2f6c5b;
  font-weight: 620;
}

.candidate-action-btn.is-primary {
  background-color: #3f7e6d;
  border-color: #3f7e6d;
  color: #ffffff;
}

.candidate-action-btn.is-accent {
  border-color: #9ac6b5;
  background-color: #eef7f3;
  color: #2f6c5b;
}

.candidate-load-more {
  margin: 0;
  width: 100%;
  min-height: 68rpx;
  border-radius: 18rpx;
  border: 1px dashed #cdd8d2;
  background-color: #ffffff;
  color: #3f7e6d;
  font-size: 24rpx;
  font-weight: 600;
  line-height: 68rpx;
}

.candidate-load-more::after {
  border: 0;
}

.candidate-load-more[disabled] {
  opacity: 0.45;
}

.candidate-preview {
  margin-top: 8rpx;
  padding-top: 24rpx;
  border-top: 1px solid #dfe6e2;
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.preview-title {
  font-size: 27rpx;
  font-weight: 650;
  color: #26332e;
}

.preview-transcript {
  padding: 16rpx 8rpx;
  border-radius: 22rpx;
  background-color: #ffffff;
  border: 1px solid #e6ebe8;
}

.preview-section-label {
  display: block;
  margin-top: 8rpx;
  font-size: 26rpx;
  font-weight: 650;
  color: #26332e;
}

@media (prefers-reduced-motion: reduce) {
  .modal-backdrop,
  .candidate-modal {
    animation: none;
  }
}
</style>
