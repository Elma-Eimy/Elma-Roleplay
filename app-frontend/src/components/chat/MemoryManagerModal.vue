<template>
  <view v-if="isOpen" class="modal-backdrop" @tap="emit('close')">
    <view class="memory-modal" @tap.stop>
      <view class="modal-header">
        <view class="header-title-row">
          <image class="title-icon" src="/static/icons/settings_database.svg" mode="aspectFit" />
          <view class="header-copy">
            <text class="modal-title">记忆库</text>
            <text class="modal-subtitle">
              {{ contextTitle ? `正在查看「${contextTitle}」的记忆` : "管理 AI 在这段故事中记住的内容" }}
            </text>
          </view>
        </view>
        <view class="close-btn" @tap="emit('close')">
          <image class="close-icon" src="/static/icons/drawer_close.svg" mode="aspectFit" />
        </view>
      </view>

      <view v-if="!groupPersonaId" class="processing-container"><MemoryProcessingPanel :session-id="sessionId" @completed="loadMemories" /></view>
      <view v-if="!groupPersonaId" class="mode-tabs">
        <button size="mini" :class="{ 'mode-active': !showConsolidation }" @tap="showConsolidation = false">浏览记忆</button>
        <button size="mini" :class="{ 'mode-active': showConsolidation }" @tap="showConsolidation = true">整理记忆</button>
      </view>
      <MemoryConsolidationPanel v-if="!groupPersonaId && showConsolidation && sessionId !== null" :key="sessionId" :session-id="sessionId" @changed="loadMemories" />
      <template v-else>
      <view class="search-container">
        <input
          v-model="searchQuery"
          class="search-input"
          placeholder="搜索记忆..."
          confirm-type="search"
        />
      </view>

      <scroll-view scroll-x class="filter-scroll" :show-scrollbar="false">
        <view class="filter-tabs">
          <view
            v-for="option in filterOptions"
            :key="option.value"
            class="filter-tab"
            :class="{ 'is-active': activeFilter === option.value }"
            @tap="selectFilter(option.value)"
          >
            <text class="filter-tab-text">{{ option.label }}</text>
            <text class="filter-tab-count">{{ option.count }}</text>
          </view>
        </view>
      </scroll-view>

      <scroll-view scroll-y class="memory-list" @scrolltolower="loadMore">
        <view v-if="isLoading" class="skeleton-list">
          <view v-for="index in 3" :key="index" class="memory-card skeleton-card">
            <view class="skeleton-line skeleton-content-line"></view>
            <view class="skeleton-line skeleton-content-line short"></view>
            <view class="skeleton-meta-row">
              <view class="skeleton-line skeleton-pill"></view>
              <view class="skeleton-line skeleton-score"></view>
            </view>
          </view>
        </view>

        <view v-else-if="filteredMemories.length === 0" class="empty-state">
          <image class="empty-icon" src="/static/icons/drawer_brain.svg" mode="aspectFit" />
          <text class="empty-title">{{ emptyStateTitle }}</text>
          <text class="empty-text">{{ emptyStateDescription }}</text>
        </view>

        <template v-else>
          <MemoryItemCard
            v-for="item in filteredMemories"
            :key="item.id"
            :item="item"
            :is-editing="editingId === item.id"
            :editing-content="editingContent"
            :editable="!groupPersonaId && item.is_local && !item.consolidation_id && !item.is_superseded"
            :local-label="localLabel"
            :group-mode="Boolean(groupPersonaId)"
            @start-edit="startInlineEdit"
            @update:editing-content="editingContent = $event"
            @cancel-edit="cancelInlineEdit"
            @save-edit="saveInlineEdit"
            @delete="deleteMemory"
          />
        </template>

        <view v-if="!isLoading && memories.length > 0" class="list-footer">
          <text v-if="isMoreLoading" class="footer-text">正在加载更多...</text>
          <text v-else-if="!hasMore" class="footer-text">没有更多记忆了</text>
        </view>
      </scroll-view>

      <MemoryAddComposer
        v-if="!groupPersonaId"
        v-model="newMemoryContent"
        :expanded="isAddMemoryOpen"
        @open="openAddMemory"
        @cancel="closeAddMemory"
        @submit="addMemory"
      />
      </template>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import { getGroupMemberMemories } from "@/api/groupSessions";
import MemoryProcessingPanel from "./MemoryProcessingPanel.vue";
import MemoryConsolidationPanel from "./MemoryConsolidationPanel.vue";
import MemoryItemCard from "./MemoryItemCard.vue";
import MemoryAddComposer from "./MemoryAddComposer.vue";
import {
  getSessionMemories,
  createSessionMemory,
  updateSessionMemory,
  deleteSessionMemory
} from "@/api/memories";
import type {
  MemoryChunk,
  MemoryScope,
  MemoryStats,
  MemoryStatus
} from "@/types/memories";

const props = defineProps<{
  isOpen: boolean;
  sessionId: number | null;
  contextTitle?: string;
  localLabel?: string;
  groupPersonaId?: number;
}>();

const emit = defineEmits<{
  (e: "close"): void;
}>();

const fetchMemories = (sessionId: number, options: import("@/types/memories").GetSessionMemoriesParams) =>
  props.groupPersonaId ? getGroupMemberMemories(sessionId, props.groupPersonaId, options) : getSessionMemories(sessionId, options);
const memories = ref<MemoryChunk[]>([]);
const showConsolidation = ref(false);
const searchQuery = ref("");
const isLoading = ref(false);
const isMoreLoading = ref(false);

// Pagination states
const limit = 20;
const offset = ref(0);
const hasMore = ref(true);
const facets = ref<MemoryStats>({
  effective_total: 0,
  local_active: 0,
  inherited_active: 0,
  superseded: 0
});

// Inline editing states
const editingId = ref<number | null>(null);
const editingContent = ref("");

// New memory creation states
const newMemoryContent = ref("");
const isAddMemoryOpen = ref(false);

type MemoryFilter = "all" | "local" | "inherited" | "superseded";

const activeFilter = ref<MemoryFilter>("all");
const filterOptions = computed<ReadonlyArray<{
  label: string;
  value: MemoryFilter;
  count: number;
}>>(() => [
  { label: "全部", value: "all", count: facets.value.effective_total },
  {
    label: props.localLabel || "当前故事",
    value: "local",
    count: facets.value.local_active
  },
  { label: "继承", value: "inherited", count: facets.value.inherited_active },
  { label: "历史原卡", value: "superseded", count: facets.value.superseded }
]);

const getFilterQuery = (
  filter: MemoryFilter
): { scope: MemoryScope; status: MemoryStatus } => {
  if (filter === "local") return { scope: "local", status: "active" };
  if (filter === "inherited") return { scope: "inherited", status: "active" };
  if (filter === "superseded") return { scope: "all", status: "superseded" };
  return { scope: "all", status: "active" };
};

const openAddMemory = () => {
  isAddMemoryOpen.value = true;
};

const closeAddMemory = () => {
  isAddMemoryOpen.value = false;
  newMemoryContent.value = "";
};

let loadRequestId = 0;

async function loadMemories() {
  if (props.sessionId === null) return;
  const requestId = ++loadRequestId;
  const { scope, status } = getFilterQuery(activeFilter.value);
  isLoading.value = true;
  offset.value = 0;
  hasMore.value = true;
  memories.value = [];
  try {
    const res = await fetchMemories(props.sessionId, {
      q: searchQuery.value,
      scope,
      status,
      limit,
      offset: 0,
    });
    if (requestId !== loadRequestId) return;
    memories.value = res.items;
    facets.value = res.facets;
    hasMore.value = res.has_more;
    offset.value = res.offset + res.items.length;
  } catch (e) {
    if (requestId !== loadRequestId) return;
    console.error("Failed to load memories", e);
    uni.showToast({ title: "加载记忆失败", icon: "none" });
  } finally {
    if (requestId === loadRequestId) {
      isLoading.value = false;
    }
  }
}

const selectFilter = async (filter: MemoryFilter) => {
  if (activeFilter.value === filter) return;
  activeFilter.value = filter;
  editingId.value = null;
  editingContent.value = "";
  await loadMemories();
};

// Load memories when modal opens or sessionId changes
watch(
  [() => props.isOpen, () => props.sessionId, () => props.groupPersonaId],
  async ([newOpen, newSessionId]) => {
    loadRequestId++;
    showConsolidation.value = false;
    editingId.value = null;
    editingContent.value = "";
    if (newOpen && newSessionId !== null) {
      // 打开弹窗时清空搜索框
      searchQuery.value = "";
      activeFilter.value = "all";
      isAddMemoryOpen.value = false;
      newMemoryContent.value = "";
      facets.value = {
        effective_total: 0,
        local_active: 0,
        inherited_active: 0,
        superseded: 0
      };
      await loadMemories();
    }
  },
  { immediate: true }
);

// 监听搜索词变化并进行防抖检索
let searchTimeout: ReturnType<typeof setTimeout> | null = null;
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

const loadMore = async () => {
  if (props.sessionId === null || isMoreLoading.value || !hasMore.value) return;
  const requestId = loadRequestId;
  const sessionId = props.sessionId;
  const filter = activeFilter.value;
  const query = searchQuery.value;
  const { scope, status } = getFilterQuery(filter);
  isMoreLoading.value = true;
  try {
    const res = await fetchMemories(sessionId, {
      q: query,
      scope,
      status,
      limit,
      offset: offset.value,
    });
    if (
      requestId !== loadRequestId ||
      props.sessionId !== sessionId ||
      activeFilter.value !== filter ||
      searchQuery.value !== query
    ) return;
    const existingIds = new Set(memories.value.map((memory) => memory.id));
    const newItems = res.items.filter((memory) => !existingIds.has(memory.id));
    memories.value.push(...newItems);
    facets.value = res.facets;
    hasMore.value = res.has_more;
    offset.value = res.offset + res.items.length;
  } catch (e) {
    console.error("Failed to load more memories", e);
  } finally {
    isMoreLoading.value = false;
  }
};

const filteredMemories = computed(() => {
  return memories.value;
});

const emptyStateTitle = computed(() => {
  if (searchQuery.value.trim()) return "没有找到相关记忆";
  if (activeFilter.value !== "all") return "这个分类还没有记忆";
  return "还没有记忆";
});

const emptyStateDescription = computed(() => {
  if (searchQuery.value.trim()) return "换个关键词试试，或清空搜索内容";
  if (activeFilter.value !== "all") return "可以切换其他分类查看";
  return "聊天过程中，AI 会自动整理值得记住的信息";
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
  if (props.sessionId === null || props.groupPersonaId) return;
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
    editingId.value = null;
    editingContent.value = "";
    await loadMemories();
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
  if (props.sessionId === null || props.groupPersonaId) return;
  uni.showModal({
    title: "确认删除",
    content: "确定要永久删除这条记忆吗？AI 在检索时将不再持有该认知。",
    confirmColor: "#ff3b30",
    success: async (res) => {
      if (res.confirm) {
        try {
          uni.showLoading({ title: "正在删除..." });
          await deleteSessionMemory(props.sessionId!, id);
          await loadMemories();
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
  if (props.sessionId === null || props.groupPersonaId) return;
  const content = newMemoryContent.value.trim();
  if (!content) return;

  try {
    uni.showLoading({ title: "正在写入..." });
    await createSessionMemory(props.sessionId, content, 0.8);
    closeAddMemory();
    activeFilter.value = "local";
    await loadMemories();
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
.processing-container { padding: 0 24rpx 12rpx; }
.mode-tabs { display: flex; padding: 16rpx 32rpx 0; gap: 18rpx; }
.mode-tabs button { margin: 0; font-size: 24rpx; }
.mode-tabs .mode-active { background: #1c1c1e; color: white; }
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
  padding: 30rpx 32rpx 22rpx;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
}

.header-title-row {
  display: flex;
  align-items: center;
  gap: 14rpx;
  min-width: 0;
}

.header-copy {
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}

.title-icon {
  width: 40rpx;
  height: 40rpx;
  opacity: 0.85;
  flex-shrink: 0;
}

.modal-title {
  font-size: 32rpx;
  font-weight: 700;
  color: #1c1c1e;
  letter-spacing: -0.3px;
}

.modal-subtitle {
  font-size: 20rpx;
  line-height: 1.35;
  color: #8e8e93;
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
  padding: 18rpx 32rpx 12rpx;
  background-color: #f8f8fa;
}

.search-input {
  width: 100%;
  height: 70rpx;
  background-color: #ffffff;
  border: 1px solid rgba(60, 60, 67, 0.08);
  border-radius: 16rpx;
  padding: 0 24rpx;
  font-size: 26rpx;
  color: #1c1c1e;
  box-sizing: border-box;
}

.filter-scroll {
  width: 100%;
  flex-shrink: 0;
  background-color: #f8f8fa;
}

.filter-tabs {
  display: inline-flex;
  align-items: center;
  gap: 10rpx;
  padding: 4rpx 32rpx 18rpx;
}

.filter-tab {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  height: 52rpx;
  padding: 0 22rpx;
  border-radius: 26rpx;
  background-color: rgba(118, 118, 128, 0.08);
  transition: background-color 0.2s, transform 0.2s;
}

.filter-tab:active {
  transform: scale(0.97);
}

.filter-tab.is-active {
  background-color: #1c1c1e;
}

.filter-tab-text {
  color: #636366;
  font-size: 22rpx;
  font-weight: 600;
  white-space: nowrap;
}

.filter-tab.is-active .filter-tab-text {
  color: #ffffff;
}

.filter-tab-count {
  min-width: 26rpx;
  height: 26rpx;
  padding: 0 6rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 13rpx;
  color: #8e8e93;
  background-color: rgba(255, 255, 255, 0.72);
  font-size: 17rpx;
  font-weight: 650;
  line-height: 1;
}

.filter-tab.is-active .filter-tab-count {
  color: #1c1c1e;
  background-color: rgba(255, 255, 255, 0.88);
}

/* Memory List */
.memory-list {
  flex: 1;
  height: 0;
  min-height: 0;
  padding: 12rpx 32rpx;
  box-sizing: border-box;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 100rpx 32rpx;
}

.empty-icon {
  width: 72rpx;
  height: 72rpx;
  margin-bottom: 24rpx;
  opacity: 0.18;
}

.empty-title {
  margin-bottom: 10rpx;
  color: #3a3a3c;
  font-size: 28rpx;
  font-weight: 650;
}

.empty-text {
  max-width: 460rpx;
  font-size: 23rpx;
  line-height: 1.5;
  color: #8e8e93;
  text-align: center;
}

/* Loading skeleton */
.skeleton-list {
  width: 100%;
}

.skeleton-card {
  overflow: hidden;
}

.skeleton-line {
  position: relative;
  overflow: hidden;
  background-color: rgba(118, 118, 128, 0.10);
}

.skeleton-line::after {
  position: absolute;
  top: 0;
  bottom: 0;
  left: -80%;
  width: 70%;
  content: "";
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.75), transparent);
  animation: skeletonShimmer 1.35s ease-in-out infinite;
}

.skeleton-content-line {
  width: 100%;
  height: 24rpx;
  border-radius: 8rpx;
  margin-bottom: 16rpx;
}

.skeleton-content-line.short {
  width: 66%;
  margin-bottom: 28rpx;
}

.skeleton-meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.skeleton-pill {
  width: 150rpx;
  height: 34rpx;
  border-radius: 17rpx;
}

.skeleton-score {
  width: 82rpx;
  height: 22rpx;
  border-radius: 8rpx;
}

@keyframes skeletonShimmer {
  to { left: 130%; }
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
