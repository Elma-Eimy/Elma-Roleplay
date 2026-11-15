<template>
  <view class="character-lorebook-tab">
    <!-- 专属与绑定世界书列表 -->
    <view class="lorebook-section">
      <!-- 独立世界书管理区域 -->
      <view class="bound-lorebooks-header">
        <text class="bound-title">关联世界设定集</text>
        <view class="bound-header-actions">
          <view class="library-link-btn" @tap="openLorebookLibrary">
            <text class="library-link-text">世界书库</text>
          </view>
          <view class="bind-action-btn" @tap="openBindSelector">
            <image class="bind-btn-icon" src="/static/icons/header_plus.svg" mode="aspectFit" />
            <text class="bind-btn-text">关联世界书</text>
          </view>
        </view>
      </view>
      
      <!-- 已关联列表 -->
      <view class="bound-list" v-if="character?.lorebooks && character.lorebooks.length > 0">
        <view
          class="bound-tag-card"
          v-for="lb in character.lorebooks"
          :key="lb.id"
          @tap="openLorebookEditor(lb.id)"
        >
          <image class="bound-tag-icon" src="/static/icons/modal_book_gray.svg" mode="aspectFit" />
          <text class="bound-tag-name">{{ lb.name }}</text>
          <view class="bound-tag-close" @tap.stop="handleUnbind(lb.id)">×</view>
        </view>
      </view>
      <view class="bound-list-empty" v-else>
        <text class="bound-empty-text">当前未关联任何外部世界书，仅展示内置专属条目。</text>
      </view>

      <!-- 词条展示部分 -->
      <view class="entries-section-header">
        <view class="entries-title-row">
          <text class="entries-title">全部世界书条目 ({{ lorebookEntries.length }})</text>
          <text
            v-if="lorebookEntries.length > 0 && activeEntriesCount < lorebookEntries.length"
            class="entries-active-pill"
          >
            已启用 {{ activeEntriesCount }}
          </text>
        </view>
        <text v-if="lorebookEntries.length > 0 || embeddedBookName" class="entries-book-name">
          {{ embeddedBookName ? `角色自带「${embeddedBookName}」` : "角色自带" }} {{ embeddedEntriesCount }} 条 · 关联世界书 {{ boundEntriesCount }} 条
        </text>
      </view>

      <view v-if="lorebookEntries.length > 0" class="lore-search-box">
        <input
          v-model="searchQuery"
          class="lore-search-input"
          type="text"
          confirm-type="search"
          placeholder="搜索关键字、内容、备注或设定集名称"
        />
        <view v-if="searchQuery" class="lore-search-clear" @tap="searchQuery = ''">×</view>
      </view>

      <view class="lore-grid" v-if="filteredEntries.length > 0">
        <view 
          class="lore-card"
          :class="{ 'is-disabled': !entry.enabled }"
          v-for="(entry, index) in filteredEntries" 
          :key="`${entry.sourceType}-${entry.sourceLorebookId ?? 'embedded'}-${index}`"
          @tap="toggleEntry(index)"
        >
          <view class="lore-card-header">
            <view class="lore-key-row">
              <text class="lore-source-tag">{{ entry.sourceName }}</text>
              <text class="lore-tag" v-for="(key, kIdx) in entry.keys" :key="`${kIdx}-${key}`">{{ key }}</text>
              <text class="lore-tag" v-if="entry.keys.length === 0">无关键字</text>
            </view>
            <view class="lore-badge-group">
              <text v-if="!entry.enabled" class="lore-status-badge disabled">
                已停用
              </text>
              <text class="lore-status-badge" :class="{ 'constant': entry.constant }">
                {{ entry.constant ? '常驻' : '条件触发' }}
              </text>
            </view>
          </view>
          <view v-if="entry.comment" class="lore-comment-row">
            <text class="lore-comment-text">{{ entry.comment }}</text>
          </view>
          <view class="lore-meta-row">
            <text class="lore-meta-item">优先级: {{ entry.priority || 100 }}</text>
            <text v-if="entry.position" class="lore-meta-item">位置: {{ entry.position }}</text>
            <text v-if="entry.depth !== undefined" class="lore-meta-item">深度: {{ entry.depth }}</text>
            <text class="lore-meta-item" v-if="entry.secondary_keys && entry.secondary_keys.length > 0">
              联合过滤: {{ entry.secondary_keys.join(', ') }}
            </text>
          </view>
          <view class="lore-content" :class="{ 'is-collapsed': !expandedEntries[index] && entry.content && entry.content.length > 80 }">
            {{ entry.content }}
          </view>
          <view class="lore-expand-toggle-row" v-if="entry.content && entry.content.length > 80">
            <text class="lore-expand-toggle">
              {{ expandedEntries[index] ? '点击收起条目' : '点击展开全部...' }}
            </text>
            <view class="lore-expand-arrow" :class="{ 'is-expanded': expandedEntries[index] }"></view>
          </view>
        </view>
      </view>
      <view v-else-if="lorebookEntries.length > 0" class="empty-branches">
        <text class="empty-branches-text">未找到匹配“{{ searchQuery }}”的世界书条目。</text>
        <view class="empty-action-btn" @tap="searchQuery = ''">
          <text class="empty-action-text">清除筛选</text>
        </view>
      </view>
      <view v-else class="empty-branches">
        <text class="empty-branches-text">当前无任何可用的世界书条目设定。</text>
        <view class="empty-action-btn" @tap="openLorebookLibrary">
          <text class="empty-action-text">前往世界书库导入 / 管理</text>
        </view>
      </view>
    </view>

    <!-- 关联独立世界书选择模态框 -->
    <view v-if="isBindSelectorOpen" class="bind-modal-backdrop" @tap.self="closeBindSelector">
      <view class="bind-modal-card">
        <view class="bind-modal-header">
          <text class="bind-modal-title">关联世界设定集</text>
          <view class="bind-modal-close" @tap="closeBindSelector">×</view>
        </view>
        <scroll-view scroll-y class="bind-modal-scroll">
          <view class="bind-modal-list" v-if="availableLorebooks.length > 0">
            <view 
              class="bind-modal-item"
              v-for="lb in availableLorebooks"
              :key="lb.id"
              @tap="handleBind(lb.id)"
            >
              <image class="bind-item-icon" src="/static/icons/modal_book_gray.svg" mode="aspectFit" />
              <view class="bind-item-info">
                <text class="bind-item-name">{{ lb.name }}</text>
                <text class="bind-item-desc">{{ lb.description || '暂无描述设定。' }}</text>
              </view>
              <view class="bind-item-action">关联</view>
            </view>
          </view>
          <view class="bind-modal-empty" v-else>
            <text class="bind-empty-desc">书库中暂无可用的设定集。</text>
            <text class="bind-empty-hint">你可以在“世界书库”中导入 JSON 设定集或查看已有条目。</text>
            <view class="bind-empty-action" @tap="openLorebookLibraryFromModal">
              <text class="bind-empty-action-text">前往世界书库导入</text>
            </view>
          </view>
        </scroll-view>
        <view v-if="availableLorebooks.length > 0" class="bind-modal-footer" @tap="openLorebookLibraryFromModal">
          <text class="bind-modal-footer-text">没有需要的设定集？前往世界书库导入 / 管理 →</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import type { CharacterDetail } from "@/api/characters";
import { getLorebooks, getLorebook, bindLorebook, unbindLorebook } from "@/api/lorebooks";
import type { LorebookSummary, LorebookDetail } from "@/api/lorebooks";
import {
  buildCharacterLorebookEntries,
  filterLorebookEntries,
  type CharacterLorebookEntryView,
} from "@/utils/lorebookDisplay";

const props = defineProps<{
  character: CharacterDetail;
  characterId: number | null;
}>();

const expandedEntries = ref<Record<number, boolean>>({});
const searchQuery = ref("");

const toggleEntry = (index: number) => {
  expandedEntries.value[index] = !expandedEntries.value[index];
};

const emit = defineEmits<{
  (e: "refresh", id: number): void;
  (e: "entries-count", count: number): void;
}>();

const boundLorebooksDetails = ref<LorebookDetail[]>([]);
const isBindSelectorOpen = ref(false);
const allLibraryLorebooks = ref<LorebookSummary[]>([]);
let loadDetailsSeq = 0;

const availableLorebooks = computed(() => {
  if (!props.character || !props.character.lorebooks) return allLibraryLorebooks.value;
  const boundIds = props.character.lorebooks.map((b) => b.id);
  return allLibraryLorebooks.value.filter(lb => !boundIds.includes(lb.id));
});

const lorebookSummary = computed(() =>
  buildCharacterLorebookEntries(props.character, boundLorebooksDetails.value),
);

const embeddedBookName = computed(() => lorebookSummary.value.embeddedName);
const activeEntriesCount = computed(() => lorebookSummary.value.activeCount);
const lorebookEntries = computed<CharacterLorebookEntryView[]>(() => lorebookSummary.value.entries);
const embeddedEntriesCount = computed(
  () => lorebookEntries.value.filter((entry) => entry.sourceType === "embedded").length,
);
const boundEntriesCount = computed(
  () => lorebookEntries.value.filter((entry) => entry.sourceType === "bound").length,
);
const filteredEntries = computed<CharacterLorebookEntryView[]>(() =>
  filterLorebookEntries(lorebookEntries.value, searchQuery.value),
);

watch(searchQuery, () => {
  expandedEntries.value = {};
});

const loadBoundLorebooksDetails = async () => {
  const seq = ++loadDetailsSeq;
  const boundList = props.character?.lorebooks;
  if (!boundList || boundList.length === 0) {
    boundLorebooksDetails.value = [];
    return;
  }

  const results = await Promise.all(
    boundList.map(async (lbSummary) => {
      try {
        return await getLorebook(lbSummary.id);
      } catch (err) {
        console.error("Failed to load details for bound lorebook", lbSummary.id, err);
        return null;
      }
    }),
  );
  if (seq !== loadDetailsSeq) return;
  boundLorebooksDetails.value = results.filter((item): item is LorebookDetail => item !== null);
};

watch(
  () => [props.character, props.character?.lorebooks, props.character?.extensions?.character_book],
  () => {
    loadBoundLorebooksDetails();
  },
  { immediate: true, deep: true }
);

watch(
  () => lorebookEntries.value.length,
  (newCount) => {
    emit("entries-count", newCount);
  },
  { immediate: true }
);

const openLorebookLibrary = () => {
  uni.navigateTo({ url: "/pages/settings/lorebooks/index" });
};

const openLorebookLibraryFromModal = () => {
  closeBindSelector();
  openLorebookLibrary();
};

const openLorebookEditor = (lorebookId: number) => {
  uni.navigateTo({ url: `/pages/settings/lorebooks/edit?id=${lorebookId}` });
};

const openBindSelector = async () => {
  try {
    const res = await getLorebooks();
    allLibraryLorebooks.value = res.lorebooks;
    isBindSelectorOpen.value = true;
  } catch (err) {
    console.error("Failed to fetch library lorebooks", err);
    uni.showToast({ title: "加载书库失败", icon: "none" });
  }
};

const closeBindSelector = () => {
  isBindSelectorOpen.value = false;
};

const handleBind = async (lorebookId: number) => {
  const charId = props.characterId;
  if (charId === null) return;
  try {
    uni.showLoading({ title: "正在绑定..." });
    await bindLorebook(charId, lorebookId);
    uni.showToast({ title: "绑定成功", icon: "success" });
    closeBindSelector();
    emit("refresh", charId);
  } catch (err) {
    console.error("Failed to bind lorebook", err);
    uni.showToast({ title: "绑定失败", icon: "none" });
  } finally {
    uni.hideLoading();
  }
};

const handleUnbind = async (lorebookId: number) => {
  const charId = props.characterId;
  if (charId === null) return;
  uni.showModal({
    title: "解除关联",
    content: "确定要解除此世界书的关联绑定吗？",
    success: async (res) => {
      if (res.confirm) {
        try {
          uni.showLoading({ title: "正在解除关联..." });
          await unbindLorebook(charId, lorebookId);
          uni.showToast({ title: "解绑成功", icon: "success" });
          emit("refresh", charId);
        } catch (err) {
          console.error("Failed to unbind lorebook", err);
          uni.showToast({ title: "解绑失败", icon: "none" });
        } finally {
          uni.hideLoading();
        }
      }
    }
  });
};

</script>

<style scoped>
/* ===== 专属世界书 (Lorebook Section) ===== */
.lorebook-section {
  padding: 0 var(--app-page-gutter, 36rpx) 100rpx;
}

.lore-grid {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.lore-card {
  background-color: rgba(255, 255, 255, 0.62);
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  border-radius: 24rpx;
  padding: 28rpx;
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.lore-card.is-disabled {
  opacity: 0.72;
  border-style: dashed;
}

.lore-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16rpx;
}

.lore-key-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8rpx;
  flex: 1;
}

.lore-tag {
  font-size: 20rpx;
  font-weight: 600;
  color: var(--app-color-primary-strong, #4f8e7c);
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
  border: 1px solid rgba(112, 174, 155, 0.12);
  padding: 4rpx 14rpx;
  border-radius: 40rpx;
}

.lore-badge-group {
  display: flex;
  align-items: center;
  gap: 8rpx;
  flex-shrink: 0;
}

.lore-status-badge {
  font-size: 18rpx;
  font-weight: 600;
  padding: 4rpx 12rpx;
  border-radius: 8rpx;
  background-color: rgba(230, 126, 34, 0.08);
  color: #e67e22;
  white-space: nowrap;
}

.lore-status-badge.constant {
  background-color: rgba(46, 204, 113, 0.08);
  color: #2ecc71;
}

.lore-status-badge.disabled {
  background-color: rgba(142, 142, 147, 0.14);
  color: #6c6c70;
}

.lore-comment-row {
  padding: 4rpx 0;
}

.lore-comment-text {
  font-size: 22rpx;
  color: var(--app-color-text-secondary, #7c8983);
  line-height: 1.4;
}

.lore-meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16rpx;
}

.lore-meta-item {
  font-size: 18rpx;
  font-weight: 500;
  color: var(--app-color-text-secondary, #7c8983);
  background-color: rgba(255, 255, 255, 0.42);
  padding: 2rpx 10rpx;
  border-radius: 6rpx;
}

.lore-content {
  display: block !important;
  box-sizing: border-box !important;
  font-size: 24rpx;
  color: var(--app-color-text-primary, #26332e);
  line-height: 1.6;
  background-color: var(--app-color-background, #f7f9f7) !important;
  padding: 20rpx 24rpx !important;
  border-radius: 16rpx !important;
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08)) !important;
  word-break: break-all;
  white-space: pre-wrap !important;
  transition: all 0.2s ease;
}

.lore-content.is-collapsed {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
  text-overflow: ellipsis;
}

.lore-expand-toggle-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  margin-top: 4rpx;
}

.lore-expand-toggle {
  font-size: 20rpx;
  color: var(--app-color-primary-strong, #4f8e7c);
  font-weight: 600;
  text-align: center;
}

.lore-expand-arrow {
  width: 14rpx;
  height: 14rpx;
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s ease;
}

.lore-expand-arrow::after {
  content: "";
  width: 8rpx;
  height: 8rpx;
  border-right: 2rpx solid var(--app-color-primary-strong, #4f8e7c);
  border-bottom: 2rpx solid var(--app-color-primary-strong, #4f8e7c);
  transform: rotate(45deg);
}

.lore-expand-arrow.is-expanded {
  transform: rotate(225deg);
  margin-top: 4rpx;
}

/* ===== 关联世界书栏目 ===== */
.bound-lorebooks-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24rpx;
  gap: 16rpx;
}

.bound-title {
  font-size: 28rpx;
  font-weight: 700;
  color: var(--app-color-text-primary, #26332e);
}

.bound-header-actions {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.library-link-btn {
  padding: 10rpx 20rpx;
  border-radius: 30rpx;
  background-color: rgba(112, 174, 155, 0.14);
  border: 1px solid rgba(112, 174, 155, 0.25);
}

.library-link-btn:active {
  opacity: 0.8;
}

.library-link-text {
  font-size: 22rpx;
  font-weight: 600;
  color: var(--app-color-primary-strong, #4f8e7c);
}

.bind-action-btn {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 10rpx 20rpx;
  background-color: var(--app-color-text-primary, #26332e);
  border-radius: 30rpx;
}

.bind-action-btn:active {
  background-color: #000000;
  transform: scale(0.97);
}

.bind-btn-icon {
  width: 22rpx;
  height: 22rpx;
  filter: invert(1);
}

.bind-btn-text {
  font-size: 22rpx;
  font-weight: 600;
  color: #ffffff;
}

.bound-list {
  display: flex;
  flex-wrap: wrap;
  gap: 16rpx;
  margin-bottom: 36rpx;
}

.bound-tag-card {
  display: flex;
  align-items: center;
  background-color: rgba(255, 255, 255, 0.62);
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  border-radius: 16rpx;
  padding: 12rpx 20rpx;
  gap: 12rpx;
  box-shadow: 0 2px 8px rgba(0,0,0,0.01);
}

.bound-tag-icon {
  width: 28rpx;
  height: 28rpx;
}

.bound-tag-name {
  font-size: 24rpx;
  font-weight: 600;
  color: var(--app-color-text-primary, #26332e);
}

.bound-tag-close {
  font-size: 32rpx;
  color: #ff3b30;
  font-weight: 400;
  padding: 0 4rpx;
  line-height: 1;
}

.bound-list-empty {
  padding: 24rpx;
  background-color: rgba(255, 255, 255, 0.38);
  border-radius: 16rpx;
  text-align: center;
  margin-bottom: 36rpx;
  border: 1px dashed var(--app-color-border, rgba(38, 51, 46, 0.1));
}

.bound-empty-text {
  font-size: 22rpx;
  color: var(--app-color-text-secondary, #7c8983);
}

.entries-section-header {
  margin-bottom: 20rpx;
  border-top: 1px solid rgba(0, 0, 0, 0.03);
  padding-top: 36rpx;
}

.entries-title-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
  flex-wrap: wrap;
}

.entries-title {
  font-size: 28rpx;
  font-weight: 700;
  color: var(--app-color-text-primary, #26332e);
}

.entries-active-pill {
  font-size: 20rpx;
  font-weight: 600;
  color: var(--app-color-primary-strong, #4f8e7c);
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
  padding: 4rpx 14rpx;
  border-radius: 999rpx;
}

.entries-book-name {
  display: block;
  margin-top: 8rpx;
  font-size: 22rpx;
  color: var(--app-color-text-secondary, #7c8983);
}

.lore-search-box {
  position: relative;
  display: flex;
  align-items: center;
  margin-bottom: 24rpx;
  background-color: rgba(255, 255, 255, 0.72);
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.1));
  border-radius: 18rpx;
  padding: 0 20rpx;
}

.lore-search-input {
  flex: 1;
  height: 72rpx;
  font-size: 24rpx;
  color: var(--app-color-text-primary, #26332e);
}

.lore-search-clear {
  width: 44rpx;
  height: 44rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32rpx;
  color: #8e8e93;
}

.lore-source-tag {
  font-size: 20rpx;
  font-weight: 700;
  color: #5d83a1;
  background-color: rgba(139, 184, 220, 0.12);
  padding: 4rpx 12rpx;
  border-radius: 6rpx;
  margin-right: 12rpx;
  text-transform: uppercase;
}

/* ===== 关联选择弹窗 ===== */
.bind-modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(10px);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
}

.bind-modal-card {
  width: 600rpx;
  height: 60%;
  max-height: 800rpx;
  background-color: #ffffff;
  border-radius: 28rpx;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 20px 45px rgba(0, 0, 0, 0.15);
  border: 1px solid rgba(0, 0, 0, 0.05);
}

.bind-modal-header {
  padding: 36rpx;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
}

.bind-modal-title {
  font-size: 32rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.bind-modal-close {
  font-size: 40rpx;
  color: #8e8e93;
  font-weight: 300;
  line-height: 1;
}

.bind-modal-scroll {
  flex: 1;
  overflow: hidden;
}

.bind-modal-list {
  padding: 24rpx 36rpx;
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.bind-modal-item {
  display: flex;
  align-items: center;
  padding: 24rpx;
  background-color: rgba(0,0,0,0.01);
  border-radius: 20rpx;
  gap: 20rpx;
  border: 1px solid rgba(0,0,0,0.02);
}

.bind-modal-item:active {
  background-color: rgba(0,0,0,0.04);
}

.bind-item-icon {
  width: 44rpx;
  height: 44rpx;
  flex-shrink: 0;
}

.bind-item-info {
  display: flex;
  flex-direction: column;
  gap: 4rpx;
  flex: 1;
  min-width: 0;
}

.bind-item-name {
  font-size: 26rpx;
  font-weight: 600;
  color: #1c1c1e;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bind-item-desc {
  font-size: 20rpx;
  color: #8e8e93;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bind-item-action {
  font-size: 22rpx;
  font-weight: 600;
  color: #ffffff;
  background-color: #1c1c1e;
  padding: 8rpx 20rpx;
  border-radius: 24rpx;
  flex-shrink: 0;
}

.bind-modal-empty {
  padding: 80rpx 40rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 12rpx;
}

.bind-empty-desc {
  font-size: 28rpx;
  font-weight: 600;
  color: #3a3a3c;
}

.bind-empty-hint {
  font-size: 22rpx;
  color: #8e8e93;
  line-height: 1.4;
  max-width: 400rpx;
}

.bind-empty-action,
.empty-action-btn {
  margin-top: 12rpx;
  padding: 14rpx 28rpx;
  border-radius: 999rpx;
  background-color: var(--app-color-primary-strong, #4f8e7c);
}

.bind-empty-action:active,
.empty-action-btn:active {
  opacity: 0.85;
}

.bind-empty-action-text,
.empty-action-text {
  font-size: 24rpx;
  font-weight: 600;
  color: #ffffff;
}

.bind-modal-footer {
  padding: 20rpx 36rpx;
  border-top: 1px solid rgba(0, 0, 0, 0.05);
  text-align: center;
  background-color: rgba(0, 0, 0, 0.015);
}

.bind-modal-footer:active {
  background-color: rgba(0, 0, 0, 0.04);
}

.bind-modal-footer-text {
  font-size: 22rpx;
  font-weight: 600;
  color: var(--app-color-primary-strong, #4f8e7c);
}

.empty-branches {
  padding: 64rpx 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 16rpx;
}

.empty-branches-text {
  font-size: 26rpx;
  color: #8e8e93;
  line-height: 1.5;
}
</style>
