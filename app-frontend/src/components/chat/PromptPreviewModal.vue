<template>
  <view v-if="isOpen" class="modal-backdrop" @tap="close">
    <view class="prompt-preview-modal" @tap.stop>
      <view class="modal-header">
        <text class="modal-title">当前 Prompt 组装预览</text>
        <view class="modal-close-btn" @tap="close">×</view>
      </view>
      <scroll-view scroll-y class="prompt-preview-scroll">
        <!-- Token Estimate Section -->
        <view v-if="tokenEstimate" class="token-estimate-container">
          <view class="estimate-summary-row" @tap="toggleDetails">
            <view class="summary-stat">
              <text class="stat-label">估算 Token</text>
              <view class="stat-value-group">
                <text class="stat-value accent">~{{ tokenEstimate.estimated_tokens }}</text>
                <text class="stat-range">({{ tokenEstimate.lower_bound }} - {{ tokenEstimate.upper_bound }})</text>
              </view>
            </view>
            <view class="summary-stat">
              <text class="stat-label">总可见字符数</text>
              <text class="stat-value">{{ tokenEstimate.characters }}</text>
            </view>
            <view class="toggle-btn">
              <text class="toggle-arrow" :class="{ 'is-expanded': isDetailsExpanded }">▼</text>
            </view>
          </view>

          <view v-if="isDetailsExpanded" class="estimate-details-table">
            <view class="table-header">
              <text class="col-name">区段</text>
              <text class="col-chars">字符</text>
              <text class="col-tokens">估算 Tokens</text>
            </view>
            <view 
              v-for="(sec, key) in tokenEstimate.sections" 
              :key="key" 
              class="table-row"
            >
              <text class="col-name">{{ getSectionName(key) }}</text>
              <text class="col-chars">{{ sec.characters }}</text>
              <view class="col-tokens">
                <text class="token-main">{{ sec.estimated_tokens }}</text>
                <text class="token-sub">({{ sec.lower_bound }}-{{ sec.upper_bound }})</text>
              </view>
            </view>
            <view class="method-footer">
              估算方法: {{ tokenEstimate.method }} | * 该统计由启发式算法计算，仅供参考。
            </view>
          </view>
        </view>

        <view class="prompt-preview-content">
          <view v-if="sections.length > 0" class="sections-toolbar">
            <text class="toolbar-summary">共 {{ sections.length }} 个区块 · {{ messages.length }} 条消息</text>
            <view class="toolbar-action-btn" @tap="toggleAllSections">
              <text class="toolbar-action-text">{{ isAllExpanded ? "全部收起" : "全部展开" }}</text>
            </view>
          </view>

          <view
            v-for="section in sections"
            :key="section.key"
            class="prompt-section-card"
            :class="{ 'is-empty-section': section.items.length === 0 }"
          >
            <view class="section-header" @tap="toggleSection(section.key)">
              <view class="section-title-col">
                <text class="section-title">{{ section.title }}</text>
                <text class="section-subtitle">{{ section.description }}</text>
              </view>
              <view class="section-meta-col">
                <text class="section-badge" :class="{ 'is-muted': section.items.length === 0 }">
                  {{ section.items.length > 0 ? `${section.items.length} 项 · ${section.totalChars} 字` : "未注入" }}
                </text>
                <text class="toggle-arrow" :class="{ 'is-expanded': isSectionExpanded(section.key) }">▼</text>
              </view>
            </view>

            <view v-if="isSectionExpanded(section.key)" class="section-body">
              <view v-if="section.items.length === 0" class="section-empty-hint">
                <text class="section-empty-text">{{ section.emptyHint }}</text>
              </view>
              <view
                v-else
                v-for="(item, idx) in section.items"
                :key="idx"
                class="prompt-msg-card"
                :class="'role-' + item.role"
              >
                <view class="prompt-msg-header">
                  <view class="prompt-msg-role-tag">{{ item.role.toUpperCase() }}</view>
                  <text v-if="item.label" class="prompt-msg-subtag">{{ item.label }}</text>
                </view>
                <text class="prompt-msg-text" :selectable="true" :user-select="true">{{ item.content }}</text>
              </view>
            </view>
          </view>
        </view>
      </scroll-view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { TokenEstimate } from "@/types/prompts";
import {
  buildPromptPreviewSections,
  type CompiledPromptMessage,
  type PromptSectionKey,
} from "@/utils/promptPreview";

const props = defineProps<{
  isOpen: boolean;
  messages: CompiledPromptMessage[];
  tokenEstimate?: TokenEstimate | null;
}>();

const emit = defineEmits<{
  (e: "close"): void;
}>();

const isDetailsExpanded = ref(false);
const expandedSectionKeys = ref<string[]>([]);

const sections = computed(() => buildPromptPreviewSections(props.messages));

watch(
  [() => props.isOpen, () => props.messages],
  ([open]) => {
    if (open) {
      expandedSectionKeys.value = [];
    }
  }
);

const isSectionExpanded = (key: PromptSectionKey): boolean => {
  return expandedSectionKeys.value.includes(key);
};

const toggleSection = (key: PromptSectionKey) => {
  if (isSectionExpanded(key)) {
    expandedSectionKeys.value = expandedSectionKeys.value.filter((item) => item !== key);
  } else {
    expandedSectionKeys.value = [...expandedSectionKeys.value, key];
  }
};

const isAllExpanded = computed(
  () => sections.value.length > 0 && sections.value.every((sec) => isSectionExpanded(sec.key))
);

const toggleAllSections = () => {
  if (isAllExpanded.value) {
    expandedSectionKeys.value = [];
  } else {
    expandedSectionKeys.value = sections.value.map((sec) => sec.key);
  }
};

const toggleDetails = () => {
  isDetailsExpanded.value = !isDetailsExpanded.value;
};

const close = () => {
  emit("close");
};

const getSectionName = (key: string): string => {
  const SECTION_NAMES: Record<string, string> = {
    character: "角色设定 (System)",
    examples: "对话示例 (Examples)",
    context_summary: "上下文摘要",
    recent_history: "历史消息 (History)",
    scenario: "当前场景 (Scenario)",
    cognition: "认知状态 (Cognition)",
    status: "心情好感 (Status)",
    lorebook: "世界书激活 (Lorebook)",
    long_term_memory: "长期记忆 (LTM)",
    graph: "图谱关系 (Graph)",
    current_user_message: "当前用户消息",
    other: "格式包装 (Other)"
  };
  return SECTION_NAMES[key] || key;
};
</script>

<style scoped>
.modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: var(--app-color-mask, rgba(25, 37, 32, 0.42));
  backdrop-filter: blur(12px);
  z-index: 120;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.25s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.prompt-preview-modal {
  width: 90vw;
  max-width: 680rpx;
  height: 80vh;
  background-color: var(--app-color-background, #f7f9f7);
  border-radius: var(--app-radius-lg, 32rpx);
  display: flex;
  flex-direction: column;
  box-shadow: var(--app-shadow-card, 0 18rpx 48rpx rgba(45, 72, 62, 0.14));
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  animation: modalFadeIn 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
}

@keyframes modalFadeIn {
  from { opacity: 0; transform: scale(0.95); }
  to { opacity: 1; transform: scale(1); }
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 32rpx 36rpx;
  border-bottom: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  background-color: var(--app-color-surface, #ffffff);
}

.modal-title {
  font-size: 32rpx;
  font-weight: 700;
  color: var(--app-color-text-primary, #26332e);
  letter-spacing: -0.3px;
}

.modal-close-btn {
  font-size: 44rpx;
  color: var(--app-color-text-secondary, #64716b);
  cursor: pointer;
  padding: 0 10rpx;
  line-height: 1;
  font-weight: 300;
}

.modal-close-btn:active {
  color: var(--app-color-text-primary, #26332e);
}

.prompt-preview-scroll {
  flex: 1;
  height: 0;
  min-height: 0;
}

/* Token Estimate Styles */
.token-estimate-container {
  margin: 24rpx 36rpx 12rpx 36rpx;
  background: var(--app-color-surface, #ffffff);
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  border-radius: 20rpx;
  overflow: hidden;
  box-shadow: 0 6rpx 18rpx rgba(45, 72, 62, 0.04);
}

.estimate-summary-row {
  display: flex;
  align-items: center;
  padding: 24rpx 28rpx;
  cursor: pointer;
  position: relative;
  background-color: var(--app-color-surface, #ffffff);
}

.estimate-summary-row:active {
  background-color: rgba(112, 174, 155, 0.06);
}

.summary-stat {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}

.stat-label {
  font-size: 20rpx;
  color: var(--app-color-text-muted, #89958f);
  font-weight: 500;
}

.stat-value-group {
  display: flex;
  align-items: baseline;
  gap: 8rpx;
}

.stat-value {
  font-size: 32rpx;
  font-weight: 700;
  color: var(--app-color-text-primary, #26332e);
}

.stat-value.accent {
  color: var(--app-color-primary-strong, #4f8e7c);
}

.stat-range {
  font-size: 20rpx;
  color: var(--app-color-text-muted, #89958f);
}

.toggle-btn {
  padding: 0 10rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.toggle-arrow {
  font-size: 20rpx;
  color: var(--app-color-text-secondary, #64716b);
  transition: transform 0.3s ease;
}

.toggle-arrow.is-expanded {
  transform: rotate(180deg);
}

/* Details Table */
.estimate-details-table {
  border-top: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  padding: 20rpx 28rpx 24rpx 28rpx;
  background-color: rgba(247, 249, 247, 0.72);
  animation: slideDown 0.25s ease-out;
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

.table-header {
  display: flex;
  font-size: 20rpx;
  font-weight: 600;
  color: var(--app-color-text-muted, #89958f);
  padding-bottom: 12rpx;
  border-bottom: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  margin-bottom: 8rpx;
}

.table-row {
  display: flex;
  align-items: center;
  padding: 12rpx 0;
  font-size: 22rpx;
  color: var(--app-color-text-primary, #26332e);
  border-bottom: 1px dashed rgba(38, 51, 46, 0.06);
}

.table-row:last-child {
  border-bottom: none;
}

.col-name {
  flex: 2;
  font-weight: 500;
}

.col-chars {
  flex: 1;
  text-align: right;
  color: var(--app-color-text-secondary, #64716b);
}

.col-tokens {
  flex: 1.8;
  text-align: right;
  display: flex;
  justify-content: flex-end;
  align-items: baseline;
  gap: 4rpx;
}

.token-main {
  font-weight: 600;
  color: var(--app-color-text-primary, #26332e);
}

.token-sub {
  font-size: 16rpx;
  color: var(--app-color-text-muted, #89958f);
}

.method-footer {
  margin-top: 20rpx;
  font-size: 18rpx;
  color: var(--app-color-text-muted, #89958f);
  text-align: center;
}

.prompt-preview-content {
  padding: 20rpx 36rpx 36rpx 36rpx;
  display: flex;
  flex-direction: column;
  gap: 18rpx;
}

.sections-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4rpx 4rpx 8rpx 4rpx;
}

.toolbar-summary {
  font-size: 22rpx;
  color: var(--app-color-text-secondary, #64716b);
  font-weight: 500;
}

.toolbar-action-btn {
  padding: 8rpx 20rpx;
  border-radius: 999rpx;
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
  cursor: pointer;
}

.toolbar-action-btn:active {
  background-color: rgba(112, 174, 155, 0.24);
}

.toolbar-action-text {
  font-size: 22rpx;
  font-weight: 600;
  color: var(--app-color-primary-strong, #4f8e7c);
}

.prompt-section-card {
  background-color: var(--app-color-surface, #ffffff);
  border-radius: 20rpx;
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  box-shadow: 0 6rpx 18rpx rgba(45, 72, 62, 0.04);
  overflow: hidden;
}

.prompt-section-card.is-empty-section {
  background-color: rgba(255, 255, 255, 0.72);
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
  padding: 24rpx 28rpx;
  cursor: pointer;
}

.section-header:active {
  background-color: rgba(112, 174, 155, 0.06);
}

.section-title-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}

.section-title {
  font-size: 27rpx;
  font-weight: 600;
  color: var(--app-color-text-primary, #26332e);
}

.section-subtitle {
  font-size: 20rpx;
  color: var(--app-color-text-secondary, #64716b);
  line-height: 1.4;
}

.section-meta-col {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.section-badge {
  font-size: 20rpx;
  font-weight: 500;
  color: var(--app-color-primary-strong, #4f8e7c);
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
  padding: 4rpx 14rpx;
  border-radius: 999rpx;
}

.section-badge.is-muted {
  color: var(--app-color-text-muted, #89958f);
  background-color: rgba(38, 51, 46, 0.06);
}

.section-body {
  border-top: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  padding: 20rpx;
  background-color: rgba(247, 249, 247, 0.75);
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.section-empty-hint {
  padding: 16rpx 12rpx;
}

.section-empty-text {
  font-size: 22rpx;
  line-height: 1.5;
  color: var(--app-color-text-secondary, #64716b);
}

.prompt-msg-card {
  background-color: var(--app-color-surface, #ffffff);
  border-radius: 16rpx;
  padding: 20rpx;
  display: flex;
  flex-direction: column;
  gap: 12rpx;
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
}

.prompt-msg-card.role-system {
  background-color: rgba(139, 184, 220, 0.08);
  border-color: rgba(139, 184, 220, 0.22);
}

.prompt-msg-card.role-user {
  background-color: var(--app-color-surface, #ffffff);
  border-color: var(--app-color-border, rgba(38, 51, 46, 0.08));
}

.prompt-msg-card.role-assistant {
  background-color: rgba(112, 174, 155, 0.07);
  border-color: rgba(112, 174, 155, 0.2);
}

.prompt-msg-header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10rpx;
}

.prompt-msg-role-tag {
  font-size: 18rpx;
  font-weight: 700;
  padding: 4rpx 12rpx;
  border-radius: 6rpx;
  letter-spacing: 0.5px;
}

.prompt-msg-subtag {
  font-size: 20rpx;
  font-weight: 500;
  color: var(--app-color-text-secondary, #64716b);
}

.role-system .prompt-msg-role-tag {
  background-color: rgba(139, 184, 220, 0.18);
  color: #3f76a3;
}

.role-user .prompt-msg-role-tag {
  background-color: rgba(38, 51, 46, 0.08);
  color: var(--app-color-text-primary, #26332e);
}

.role-assistant .prompt-msg-role-tag {
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.16));
  color: var(--app-color-primary-strong, #4f8e7c);
}

.prompt-msg-text {
  font-size: 25rpx;
  line-height: 1.6;
  color: var(--app-color-text-primary, #26332e);
  word-break: break-all;
}

@media (prefers-reduced-motion: reduce) {
  .modal-backdrop,
  .prompt-preview-modal,
  .estimate-details-table,
  .toggle-arrow {
    animation: none !important;
    transition: none !important;
  }
}
</style>
