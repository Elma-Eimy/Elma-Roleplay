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
          <view 
            class="prompt-msg-card" 
            v-for="(msg, idx) in messages" 
            :key="idx"
            :class="'role-' + msg.role"
          >
            <view class="prompt-msg-role-tag">{{ msg.role.toUpperCase() }}</view>
            <text class="prompt-msg-text" :selectable="true" :user-select="true">{{ msg.content }}</text>
          </view>
        </view>
      </scroll-view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, defineProps, defineEmits } from "vue";
import type { TokenEstimate } from "@/api/sessions";

interface CompiledMessage {
  role: string;
  content: string;
}

defineProps<{
  isOpen: boolean;
  messages: CompiledMessage[];
  tokenEstimate?: TokenEstimate | null;
}>();

const emit = defineEmits<{
  (e: "close"): void;
}>();

const isDetailsExpanded = ref(false);

const toggleDetails = () => {
  isDetailsExpanded.value = !isDetailsExpanded.value;
};

const close = () => {
  emit("close");
};

const getSectionName = (key: string): string => {
  const SECTION_NAMES: Record<string, string> = {
    character: "角色设定 (System)",
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
  background-color: rgba(0, 0, 0, 0.35);
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
  background-color: #f8f8fa;
  border-radius: 32rpx;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.15);
  border: 1px solid rgba(0, 0, 0, 0.05);
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
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
  background-color: #ffffff;
}

.modal-title {
  font-size: 32rpx;
  font-weight: 700;
  color: #1c1c1e;
  letter-spacing: -0.3px;
}

.modal-close-btn {
  font-size: 44rpx;
  color: #8e8e93;
  cursor: pointer;
  padding: 0 10rpx;
  line-height: 1;
  font-weight: 300;
}

.modal-close-btn:active {
  color: #1c1c1e;
}

.prompt-preview-scroll {
  flex: 1;
  height: 0;
  min-height: 0;
}

/* Token Estimate Styles */
.token-estimate-container {
  margin: 24rpx 36rpx 12rpx 36rpx;
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 20rpx;
  overflow: hidden;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.02);
}

.estimate-summary-row {
  display: flex;
  align-items: center;
  padding: 24rpx 28rpx;
  cursor: pointer;
  position: relative;
  background-color: #ffffff;
}

.estimate-summary-row:active {
  background-color: rgba(0, 0, 0, 0.02);
}

.summary-stat {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}

.stat-label {
  font-size: 20rpx;
  color: #8e8e93;
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
  color: #1c1c1e;
}

.stat-value.accent {
  color: #007aff;
}

.stat-range {
  font-size: 20rpx;
  color: #8e8e93;
}

.toggle-btn {
  padding: 0 10rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.toggle-arrow {
  font-size: 20rpx;
  color: #8e8e93;
  transition: transform 0.3s ease;
}

.toggle-arrow.is-expanded {
  transform: rotate(180deg);
}

/* Details Table */
.estimate-details-table {
  border-top: 1px solid rgba(0, 0, 0, 0.04);
  padding: 20rpx 28rpx 24rpx 28rpx;
  background-color: rgba(242, 242, 247, 0.4);
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
  color: #8e8e93;
  padding-bottom: 12rpx;
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
  margin-bottom: 8rpx;
}

.table-row {
  display: flex;
  align-items: center;
  padding: 12rpx 0;
  font-size: 22rpx;
  color: #3a3a3c;
  border-bottom: 1px dashed rgba(0, 0, 0, 0.03);
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
  color: #8e8e93;
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
  color: #1c1c1e;
}

.token-sub {
  font-size: 16rpx;
  color: #8e8e93;
}

.method-footer {
  margin-top: 20rpx;
  font-size: 18rpx;
  color: #aeaea2;
  text-align: center;
}

.prompt-preview-content {
  padding: 36rpx;
  display: flex;
  flex-direction: column;
  gap: 28rpx;
}

.prompt-msg-card {
  background-color: #ffffff;
  border-radius: 20rpx;
  padding: 24rpx;
  display: flex;
  flex-direction: column;
  gap: 16rpx;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.03);
}

.prompt-msg-card.role-system {
  background-color: rgba(0, 122, 255, 0.02);
  border-color: rgba(0, 122, 255, 0.06);
}

.prompt-msg-card.role-user {
  background-color: rgba(0, 0, 0, 0.01);
  border-color: rgba(0, 0, 0, 0.03);
}

.prompt-msg-card.role-assistant {
  background-color: rgba(52, 199, 89, 0.02);
  border-color: rgba(52, 199, 89, 0.06);
}

.prompt-msg-role-tag {
  font-size: 18rpx;
  font-weight: 700;
  padding: 4rpx 12rpx;
  border-radius: 6rpx;
  align-self: flex-start;
  letter-spacing: 0.5px;
}

.role-system .prompt-msg-role-tag {
  background-color: rgba(0, 122, 255, 0.1);
  color: #007aff;
}

.role-user .prompt-msg-role-tag {
  background-color: rgba(28, 28, 30, 0.1);
  color: #1c1c1e;
}

.role-assistant .prompt-msg-role-tag {
  background-color: rgba(52, 199, 89, 0.1);
  color: #34c759;
}

.prompt-msg-text {
  font-size: 26rpx;
  line-height: 1.6;
  color: #1c1c1e;
  word-break: break-all;
}
</style>
