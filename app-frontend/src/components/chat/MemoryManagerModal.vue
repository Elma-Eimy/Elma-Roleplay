<template>
  <view v-if="isOpen" class="modal-backdrop" @tap="emit('close')">
    <view class="memory-modal" @tap.stop>
      <!-- Header -->
      <view class="modal-header">
        <view class="header-title-row">
          <image class="title-icon" src="/static/icons/settings_database.svg" mode="aspectFit" />
          <text class="modal-title">记忆库 ({{ memories.length }})</text>
        </view>
        <view class="close-btn" @tap="emit('close')">
          <image class="close-icon" src="/static/icons/drawer_close.svg" mode="aspectFit" />
        </view>
      </view>

      <!-- Search Bar -->
      <view class="search-container">
        <input
          class="search-input"
          v-model="searchQuery"
          placeholder="搜索记忆元..."
          confirm-type="search"
        />
      </view>

      <!-- Memory List -->
      <scroll-view scroll-y class="memory-list" @scrolltolower="loadMore">
        <view v-if="filteredMemories.length === 0" class="empty-state">
          <text class="empty-text">{{ searchQuery ? '无搜索结果' : '暂无向量记忆，聊天中将自动提取...' }}</text>
        </view>
        <view
          v-for="item in filteredMemories"
          :key="item.id"
          class="memory-card"
          :class="{ 'is-inherited': !item.is_local, 'is-superseded': item.is_superseded }"
        >
          <view class="card-header">
            <view class="tag-row">
              <text class="memory-type-badge">{{ item.memory_type }}</text>
              <text v-if="!item.is_local" class="inherited-badge">继承记忆</text>
              <text v-else class="local-badge">本地记忆</text>
              <text v-if="item.is_superseded" class="superseded-badge">已替代</text>
              <text v-if="item.source_start_message_id || item.source_message_id" class="source-badge">
                来源: #{{ item.source_start_message_id || item.source_message_id }}<template v-if="item.source_start_message_id && item.source_message_id && item.source_start_message_id !== item.source_message_id">-#{{ item.source_message_id }}</template>
              </text>
            </view>
            <text class="score-text">权重: {{ item.importance_score.toFixed(1) }}</text>
          </view>

          <!-- Content display / edit inline -->
          <view class="card-body">
            <view v-if="editingId === item.id" class="edit-mode-container">
              <textarea
                class="card-textarea"
                v-model="editingContent"
                :maxlength="-1"
                :show-confirm-bar="false"
              />
              <view class="edit-actions">
                <view class="edit-btn cancel" @tap="cancelInlineEdit">取消</view>
                <view class="edit-btn save" @tap="saveInlineEdit(item.id)">保存</view>
              </view>
            </view>
            <view v-else class="content-text-container">
              <text class="content-text">{{ item.content }}</text>
            </view>
          </view>

          <!-- Card Actions (only if local) -->
          <view v-if="item.is_local && editingId !== item.id" class="card-actions">
            <view class="action-icon-btn" @tap="startInlineEdit(item)">
              <image class="action-svg-icon" src="/static/icons/char_pencil.svg" mode="aspectFit" />
              <text class="action-icon-text">编辑</text>
            </view>
            <view class="action-icon-btn danger" @tap="deleteMemory(item.id)">
              <image class="action-svg-icon" src="/static/icons/drawer_trash.svg" mode="aspectFit" />
              <text class="action-icon-text">删除</text>
            </view>
          </view>
        </view>

        <!-- Loading More Footer -->
        <view v-if="memories.length > 0" class="list-footer">
          <text v-if="isMoreLoading" class="footer-text">正在加载更多...</text>
          <text v-else-if="!hasMore" class="footer-text">没有更多记忆了</text>
        </view>
      </scroll-view>

      <!-- Manual Add Memory Box -->
      <view class="add-memory-container">
        <textarea
          class="add-textarea"
          v-model="newMemoryContent"
          placeholder="手动输入关于我的喜好/设定..."
          :maxlength="-1"
          :show-confirm-bar="false"
        />
        <view
          class="add-submit-btn"
          :class="{ 'is-active': newMemoryContent.trim().length > 0 }"
          @tap="addMemory"
        >
          <text class="submit-btn-text">写入记忆元</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import {
  getSessionMemories,
  createSessionMemory,
  updateSessionMemory,
  deleteSessionMemory
} from "@/api/sessions";
import type { MemoryChunk } from "@/api/sessions";

const props = defineProps<{
  isOpen: boolean;
  sessionId: number | null;
}>();

const emit = defineEmits<{
  (e: "close"): void;
}>();

const memories = ref<MemoryChunk[]>([]);
const searchQuery = ref("");
const isLoading = ref(false);
const isMoreLoading = ref(false);

// Pagination states
const limit = 20;
const offset = ref(0);
const hasMore = ref(true);

// Inline editing states
const editingId = ref<number | null>(null);
const editingContent = ref("");

// New memory creation states
const newMemoryContent = ref("");

// Load memories when modal opens
watch(
  () => props.isOpen,
  async (newVal) => {
    if (newVal && props.sessionId !== null) {
      // 打开弹窗时清空搜索框
      searchQuery.value = "";
      await loadMemories();
    }
  }
);

// 监听搜索词变化并进行防抖检索
let searchTimeout: any = null;
watch(searchQuery, () => {
  if (searchTimeout) {
    clearTimeout(searchTimeout);
  }
  searchTimeout = setTimeout(async () => {
    if (props.isOpen && props.sessionId !== null) {
      await loadMemories();
    }
  }, 300);
});

const loadMemories = async () => {
  if (props.sessionId === null) return;
  isLoading.value = true;
  offset.value = 0;
  hasMore.value = true;
  memories.value = [];
  try {
    const res = await getSessionMemories(props.sessionId, limit, offset.value, searchQuery.value);
    memories.value = res;
    if (res.length < limit) {
      hasMore.value = false;
    } else {
      offset.value += limit;
    }
  } catch (e) {
    console.error("Failed to load memories", e);
    uni.showToast({ title: "加载记忆失败", icon: "none" });
  } finally {
    isLoading.value = false;
  }
};

const loadMore = async () => {
  if (props.sessionId === null || isMoreLoading.value || !hasMore.value) return;
  isMoreLoading.value = true;
  try {
    const res = await getSessionMemories(props.sessionId, limit, offset.value, searchQuery.value);
    if (res.length > 0) {
      memories.value.push(...res);
    }
    if (res.length < limit) {
      hasMore.value = false;
    } else {
      offset.value += limit;
    }
  } catch (e) {
    console.error("Failed to load more memories", e);
  } finally {
    isMoreLoading.value = false;
  }
};

const filteredMemories = computed(() => {
  // 服务端完成检索，前端直接返回数组列表即可
  return memories.value;
});

// Inline editing functions
const startInlineEdit = (item: MemoryChunk) => {
  editingId.value = item.id;
  editingContent.value = item.content;
};

const cancelInlineEdit = () => {
  editingId.value = null;
  editingContent.value = "";
};

const saveInlineEdit = async (id: number) => {
  if (props.sessionId === null) return;
  const content = editingContent.value.trim();
  if (!content) {
    uni.showToast({ title: "内容不能为空", icon: "none" });
    return;
  }

  try {
    uni.showLoading({ title: "正在保存..." });
    const item = memories.value.find((m) => m.id === id);
    const score = item ? item.importance_score : 0.8;
    await updateSessionMemory(props.sessionId, id, content, score);
    
    // Update local list
    if (item) {
      item.content = content;
    }
    editingId.value = null;
    editingContent.value = "";
    uni.hideLoading();
    uni.showToast({ title: "保存成功", icon: "success" });
  } catch (e) {
    uni.hideLoading();
    console.error("Failed to save memory edit", e);
    uni.showToast({ title: "保存失败", icon: "none" });
  }
};

// Delete memory
const deleteMemory = (id: number) => {
  if (props.sessionId === null) return;
  uni.showModal({
    title: "确认删除",
    content: "确定要永久删除这条记忆吗？AI 在检索时将不再持有该认知。",
    confirmColor: "#ff3b30",
    success: async (res) => {
      if (res.confirm) {
        try {
          uni.showLoading({ title: "正在删除..." });
          await deleteSessionMemory(props.sessionId!, id);
          memories.value = memories.value.filter((m) => m.id !== id);
          uni.hideLoading();
          uni.showToast({ title: "删除成功", icon: "success" });
        } catch (e) {
          uni.hideLoading();
          console.error("Failed to delete memory", e);
          uni.showToast({ title: "删除失败", icon: "none" });
        }
      }
    }
  });
};

// Add memory
const addMemory = async () => {
  if (props.sessionId === null) return;
  const content = newMemoryContent.value.trim();
  if (!content) return;

  try {
    uni.showLoading({ title: "正在写入..." });
    const res = await createSessionMemory(props.sessionId, content, 0.8);
    // Unshift to list
    memories.value.unshift(res.memory);
    newMemoryContent.value = "";
    uni.hideLoading();
    uni.showToast({ title: "写入成功", icon: "success" });
  } catch (e) {
    uni.hideLoading();
    console.error("Failed to add memory", e);
    uni.showToast({ title: "写入失败", icon: "none" });
  }
};
</script>

<style scoped>
/* Backdrop */
.modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(12px);
  z-index: 110; /* Higher than ChatDrawer's 100 */
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.25s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* Modal Body */
.memory-modal {
  width: 90vw;
  max-width: 680rpx;
  height: 75vh;
  background-color: #f8f8fa;
  border-radius: 32rpx;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.15);
  border: 1px solid rgba(0, 0, 0, 0.05);
  overflow: hidden;
  animation: scaleUp 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes scaleUp {
  from { transform: scale(0.95); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}

/* Header */
.modal-header {
  padding: 32rpx 36rpx 24rpx 36rpx;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
}

.header-title-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.title-icon {
  width: 38rpx;
  height: 38rpx;
  opacity: 0.85;
}

.modal-title {
  font-size: 32rpx;
  font-weight: 700;
  color: #1c1c1e;
  letter-spacing: -0.3px;
}

.close-btn {
  width: 52rpx;
  height: 52rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.05);
  transition: background-color 0.2s;
}

.close-btn:active {
  background-color: rgba(0, 0, 0, 0.1);
}

.close-icon {
  width: 24rpx;
  height: 24rpx;
  opacity: 0.6;
}

/* Search Box */
.search-container {
  padding: 20rpx 36rpx;
  background-color: #f8f8fa;
}

.search-input {
  width: 100%;
  height: 72rpx;
  background-color: rgba(0, 0, 0, 0.03);
  border: 1px solid rgba(0, 0, 0, 0.03);
  border-radius: 16rpx;
  padding: 0 24rpx;
  font-size: 26rpx;
  color: #1c1c1e;
  box-sizing: border-box;
}

/* Memory List */
.memory-list {
  flex: 1;
  height: 0;
  min-height: 0;
  padding: 10rpx 36rpx;
  box-sizing: border-box;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 80rpx 0;
}

.empty-text {
  font-size: 26rpx;
  color: #8e8e93;
}

/* Memory Card */
.memory-card {
  background-color: #ffffff;
  border-radius: 20rpx;
  padding: 24rpx;
  margin-bottom: 20rpx;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.03);
  transition: transform 0.2s;
}

.memory-card.is-inherited {
  background-color: rgba(242, 242, 247, 0.6);
  border: 1px dashed rgba(0, 0, 0, 0.08);
}

.memory-card.is-superseded {
  opacity: 0.65;
  border: 1px solid rgba(255, 149, 0, 0.15);
  background-color: rgba(242, 242, 247, 0.3);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16rpx;
}

.tag-row {
  display: flex;
  align-items: center;
  gap: 10rpx;
  flex-wrap: wrap;
}

.memory-type-badge {
  font-size: 18rpx;
  font-weight: 600;
  color: #5856d6;
  background-color: rgba(88, 86, 214, 0.1);
  padding: 4rpx 10rpx;
  border-radius: 6rpx;
  text-transform: uppercase;
}

.inherited-badge {
  font-size: 18rpx;
  font-weight: 500;
  color: #8e8e93;
  background-color: rgba(0, 0, 0, 0.05);
  padding: 4rpx 10rpx;
  border-radius: 6rpx;
}

.local-badge {
  font-size: 18rpx;
  font-weight: 500;
  color: #34c759;
  background-color: rgba(52, 199, 89, 0.10);
  padding: 4rpx 10rpx;
  border-radius: 6rpx;
}

.superseded-badge {
  font-size: 18rpx;
  font-weight: 500;
  color: #ff9500;
  background-color: rgba(255, 149, 0, 0.10);
  padding: 4rpx 10rpx;
  border-radius: 6rpx;
}

.source-badge {
  font-size: 18rpx;
  font-weight: 500;
  color: #007aff;
  background-color: rgba(0, 122, 255, 0.10);
  padding: 4rpx 10rpx;
  border-radius: 6rpx;
}

.score-text {
  font-size: 18rpx;
  color: #8e8e93;
}

.card-body {
  margin-bottom: 12rpx;
}

.content-text {
  font-size: 26rpx;
  color: #1c1c1e;
  line-height: 1.5;
  word-break: break-all;
}

/* Actions */
.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 28rpx;
  border-top: 1px solid rgba(0, 0, 0, 0.03);
  padding-top: 16rpx;
  margin-top: 12rpx;
}

.action-icon-btn {
  display: flex;
  align-items: center;
  gap: 6rpx;
  opacity: 0.65;
  transition: opacity 0.2s;
}

.action-icon-btn:active {
  opacity: 1;
}

.action-svg-icon {
  width: 24rpx;
  height: 24rpx;
}

.action-icon-text {
  font-size: 22rpx;
  color: #3a3a3c;
  font-weight: 500;
}

.action-icon-btn.danger .action-icon-text {
  color: #ff3b30;
}

/* Inline Edit Style */
.edit-mode-container {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.card-textarea {
  width: 100%;
  height: 140rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 12rpx;
  padding: 12rpx 16rpx;
  font-size: 26rpx;
  color: #1c1c1e;
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
  background-color: rgba(0, 0, 0, 0.05);
  color: #8e8e93;
}

.edit-btn.save {
  background-color: #1c1c1e;
  color: #ffffff;
}

/* Add memory box at bottom */
.add-memory-container {
  padding: 24rpx 36rpx 36rpx 36rpx;
  background-color: #ffffff;
  border-top: 1px solid rgba(0, 0, 0, 0.04);
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.add-textarea {
  width: 100%;
  height: 110rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.05);
  border-radius: 16rpx;
  padding: 16rpx 20rpx;
  font-size: 26rpx;
  color: #1c1c1e;
  line-height: 1.4;
  box-sizing: border-box;
}

.add-submit-btn {
  width: 100%;
  height: 72rpx;
  background-color: rgba(0, 0, 0, 0.04);
  border-radius: 16rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background-color 0.2s;
}

.add-submit-btn.is-active {
  background-color: #1c1c1e;
}

.submit-btn-text {
  font-size: 26rpx;
  color: rgba(255, 255, 255, 0.4);
  font-weight: 600;
}

.add-submit-btn.is-active .submit-btn-text {
  color: #ffffff;
}

/* Pagination Footer */
.list-footer {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24rpx 0 36rpx 0;
}

.footer-text {
  font-size: 22rpx;
  color: #8e8e93;
  letter-spacing: 0.2px;
}
</style>
