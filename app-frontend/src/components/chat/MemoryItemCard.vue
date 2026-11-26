<template>
  <view
    class="memory-card"
    :class="{ 'is-inherited': !item.is_local, 'is-superseded': item.is_superseded }"
  >
    <view class="card-body">
      <view v-if="isEditing" class="edit-mode-container">
        <textarea
          v-model="draftContent"
          class="card-textarea"
          :maxlength="-1"
          :show-confirm-bar="false"
        />
        <view class="edit-actions">
          <view class="edit-btn cancel" @tap="emit('cancel-edit')">取消</view>
          <view class="edit-btn save" @tap="emit('save-edit', item.id)">保存</view>
        </view>
      </view>
      <view v-else class="content-text-container">
        <text class="content-text">{{ item.content }}</text>
      </view>
    </view>

    <view v-if="!isEditing" class="card-meta">
      <view class="tag-row">
        <text class="memory-type-badge">{{ getMemoryTypeLabel(item.memory_type) }}</text>
        <text v-if="!item.is_local" class="inherited-badge">
          {{ groupMode ? "入群时继承" : "来自主故事" }}
        </text>
        <text v-else class="local-badge">{{ localLabel || "当前故事" }}</text>
        <text v-if="item.is_superseded" class="superseded-badge">历史原卡</text>
        <text v-if="item.consolidation_id" class="local-badge">整理结果</text>
        <text v-if="item.source_start_message_id || item.source_message_id" class="source-text">
          {{ formatMemorySource(item) }}
        </text>
      </view>
      <text v-if="item.indexed !== undefined" class="source-text">
        {{ item.indexed ? "已建向量索引" : "向量待同步" }}
      </text>
      <text class="score-text">权重 {{ item.importance_score.toFixed(1) }}</text>
    </view>

    <view v-if="editable && !isEditing" class="card-actions">
      <view class="action-icon-btn" @tap="emit('start-edit', item)">
        <image class="action-svg-icon" src="/static/icons/char_pencil.svg" mode="aspectFit" />
        <text class="action-icon-text">编辑</text>
      </view>
      <view class="action-icon-btn danger" @tap="emit('delete', item.id)">
        <image class="action-svg-icon" src="/static/icons/drawer_trash.svg" mode="aspectFit" />
        <text class="action-icon-text">删除</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { MemoryChunk } from "@/types/memories";

const props = withDefaults(
  defineProps<{
    item: MemoryChunk;
    isEditing: boolean;
    editingContent: string;
    editable: boolean;
    localLabel?: string;
    groupMode?: boolean;
  }>(),
  {
    localLabel: "",
    groupMode: false,
  }
);

const emit = defineEmits<{
  (e: "start-edit", item: MemoryChunk): void;
  (e: "update:editing-content", value: string): void;
  (e: "cancel-edit"): void;
  (e: "save-edit", id: number): void;
  (e: "delete", id: number): void;
}>();

const draftContent = computed({
  get: () => props.editingContent,
  set: (value: string) => emit("update:editing-content", value),
});

const memoryTypeLabels: Record<string, string> = {
  fact: "事实",
  event: "经历",
  emotion: "情绪",
  relationship: "关系",
  preference: "偏好",
  personality: "性格",
  summary: "摘要",
};

const getMemoryTypeLabel = (type: string) =>
  memoryTypeLabels[type.trim().toLowerCase()] || "其他";

const formatMemorySource = (item: MemoryChunk) => {
  const startId = item.source_start_message_id || item.source_message_id;
  const endId = item.source_message_id;
  if (startId && endId && startId !== endId) {
    return `消息 #${startId}–#${endId}`;
  }
  return `消息 #${startId}`;
};
</script>

<style scoped>
.memory-card {
  background-color: #ffffff;
  border-radius: 20rpx;
  padding: 26rpx;
  margin-bottom: 20rpx;
  box-shadow: 0 6rpx 20rpx rgba(22, 22, 28, 0.035);
  border: 1px solid rgba(60, 60, 67, 0.06);
  transition: transform 0.2s;
}

.memory-card.is-inherited {
  border-left: 5rpx solid rgba(88, 86, 214, 0.55);
  background-color: rgba(248, 247, 255, 0.9);
}

.memory-card.is-superseded {
  opacity: 0.58;
  border-color: rgba(255, 149, 0, 0.16);
  box-shadow: none;
}

.card-meta {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16rpx;
}

.tag-row {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 8rpx;
  flex-wrap: wrap;
  min-width: 0;
}

.memory-type-badge {
  font-size: 20rpx;
  font-weight: 600;
  color: #5856d6;
  background-color: rgba(88, 86, 214, 0.1);
  padding: 5rpx 12rpx;
  border-radius: 8rpx;
}

.inherited-badge {
  font-size: 20rpx;
  font-weight: 500;
  color: #5856d6;
  background-color: rgba(88, 86, 214, 0.08);
  padding: 5rpx 12rpx;
  border-radius: 8rpx;
}

.local-badge {
  font-size: 20rpx;
  font-weight: 500;
  color: #248a3d;
  background-color: rgba(52, 199, 89, 0.09);
  padding: 5rpx 12rpx;
  border-radius: 8rpx;
}

.superseded-badge {
  font-size: 20rpx;
  font-weight: 500;
  color: #ff9500;
  background-color: rgba(255, 149, 0, 0.1);
  padding: 5rpx 12rpx;
  border-radius: 8rpx;
}

.source-text {
  font-size: 20rpx;
  font-weight: 500;
  color: var(--app-color-text-secondary, #64716b);
}

.score-text {
  flex-shrink: 0;
  padding-top: 4rpx;
  font-size: 21rpx;
  font-weight: 550;
  color: var(--app-color-primary-strong, #4f8e7c);
}

.card-body {
  margin-bottom: 20rpx;
}

.content-text {
  font-size: 28rpx;
  color: var(--app-color-text-primary, #26332e);
  line-height: 1.62;
  word-break: break-word;
}

.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8rpx;
  border-top: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  padding-top: 12rpx;
  margin-top: 18rpx;
}

.action-icon-btn {
  display: flex;
  align-items: center;
  gap: 6rpx;
  min-height: 48rpx;
  padding: 0 12rpx;
  border-radius: 12rpx;
  opacity: 0.72;
  transition: opacity 0.2s, background-color 0.2s;
}

.action-icon-btn:active {
  opacity: 1;
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
}

.action-svg-icon {
  width: 24rpx;
  height: 24rpx;
}

.action-icon-text {
  font-size: 22rpx;
  color: var(--app-color-text-secondary, #64716b);
  font-weight: 500;
}

.action-icon-btn.danger .action-icon-text {
  color: var(--app-color-danger, #d9655d);
}

.edit-mode-container {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.card-textarea {
  width: 100%;
  height: 140rpx;
  background-color: var(--app-color-background, #f7f9f7);
  border: 1px solid var(--app-color-border-strong, rgba(38, 51, 46, 0.14));
  border-radius: 12rpx;
  padding: 12rpx 16rpx;
  font-size: 26rpx;
  color: var(--app-color-text-primary, #26332e);
  line-height: 1.4;
  box-sizing: border-box;
}

.edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 16rpx;
}

.edit-btn {
  padding: 8rpx 20rpx;
  border-radius: 10rpx;
  font-size: 22rpx;
  font-weight: 500;
}

.edit-btn.cancel {
  background-color: rgba(38, 51, 46, 0.05);
  color: var(--app-color-text-secondary, #64716b);
}

.edit-btn.save {
  background-color: var(--app-color-primary-strong, #4f8e7c);
  color: #ffffff;
}
</style>
