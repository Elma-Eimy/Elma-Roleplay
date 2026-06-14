<template>
  <view class="character-lorebook-tab">
    <!-- 专属与绑定世界书列表 -->
    <view class="lorebook-section">
      <!-- 独立世界书管理区域 -->
      <view class="bound-lorebooks-header">
        <text class="bound-title">关联世界设定集</text>
        <view class="bind-action-btn" @tap="openBindSelector">
          <image class="bind-btn-icon" src="/static/icons/header_plus.svg" mode="aspectFit" />
          <text class="bind-btn-text">关联世界书</text>
        </view>
      </view>
      
      <!-- 已关联列表 -->
      <view class="bound-list" v-if="character?.lorebooks && character.lorebooks.length > 0">
        <view class="bound-tag-card" v-for="lb in character.lorebooks" :key="lb.id">
          <image class="bound-tag-icon" src="/static/icons/modal_book_gray.svg" mode="aspectFit" />
          <text class="bound-tag-name">{{ lb.name }}</text>
          <view class="bound-tag-close" @tap="handleUnbind(lb.id)">×</view>
        </view>
      </view>
      <view class="bound-list-empty" v-else>
        <text class="bound-empty-text">当前未关联任何外部世界书，仅检索内置专属条目。</text>
      </view>

      <!-- 词条展示部分 -->
      <view class="entries-section-header">
        <text class="entries-title">全部激活设定条目 ({{ lorebookEntries.length }})</text>
      </view>

      <view class="lore-grid" v-if="lorebookEntries.length > 0">
        <view 
          class="lore-card" 
          v-for="(entry, index) in lorebookEntries" 
          :key="index"
        >
          <view class="lore-card-header">
            <view class="lore-key-row">
              <text class="lore-source-tag">{{ entry.sourceName }}</text>
              <text class="lore-tag" v-for="key in entry.keys" :key="key">{{ key }}</text>
            </view>
            <text class="lore-status-badge" :class="{ 'constant': entry.constant }">
              {{ entry.constant ? '常驻' : '条件触发' }}
            </text>
          </view>
          <view class="lore-meta-row">
            <text class="lore-meta-item">优先级: {{ entry.priority || 100 }}</text>
            <text class="lore-meta-item" v-if="entry.secondary_keys && entry.secondary_keys.length > 0">
              联合过滤: {{ entry.secondary_keys.join(', ') }}
            </text>
          </view>
          <text class="lore-content">{{ entry.content }}</text>
        </view>
      </view>
      <view v-else class="empty-branches">
        <text class="empty-branches-text">当前无任何可用的世界书条目设定。</text>
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
            <text class="bind-empty-hint">你可以在“设置 -> 独立世界书库”中导入更多设定集。</text>
          </view>
        </scroll-view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import type { CharacterDetail } from "@/api/characters";
import { getLorebooks, getLorebook, bindLorebook, unbindLorebook } from "@/api/lorebooks";
import type { LorebookSummary } from "@/api/lorebooks";

const props = defineProps<{
  character: CharacterDetail;
  characterId: number | null;
}>();

const emit = defineEmits<{
  (e: "refresh", id: number): void;
  (e: "entries-count", count: number): void;
}>();

const boundLorebooksDetails = ref<any[]>([]);
const isBindSelectorOpen = ref(false);
const allLibraryLorebooks = ref<LorebookSummary[]>([]);

const availableLorebooks = computed(() => {
  if (!props.character || !props.character.lorebooks) return allLibraryLorebooks.value;
  const boundIds = props.character.lorebooks.map((b: any) => b.id);
  return allLibraryLorebooks.value.filter(lb => !boundIds.includes(lb.id));
});

const loadBoundLorebooksDetails = async () => {
  boundLorebooksDetails.value = [];
  if (props.character && props.character.lorebooks) {
    const promises = props.character.lorebooks.map(async (lbSummary: any) => {
      try {
        const details = await getLorebook(lbSummary.id);
        return details;
      } catch (err) {
        console.error("Failed to load details for bound lorebook", lbSummary.id, err);
        return null;
      }
    });
    const results = await Promise.all(promises);
    boundLorebooksDetails.value = results.filter(Boolean);
  }
};

watch(
  () => [props.character?.lorebooks, props.character?.extensions?.character_book],
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

const lorebookEntries = computed(() => {
  const entries: any[] = [];
  
  // 1. 专属（内置）条目
  const charBook = props.character?.extensions?.character_book as any;
  if (charBook && Array.isArray(charBook.entries)) {
    charBook.entries.forEach((e: any) => {
      if (e && e.enabled !== false) {
        entries.push({
          ...normalizeEntry(e),
          sourceName: "专属"
        });
      }
    });
  }
  
  // 2. 绑定的独立世界书条目
  boundLorebooksDetails.value.forEach((lb: any) => {
    if (lb && Array.isArray(lb.entries)) {
      lb.entries.forEach((e: any) => {
        if (e && e.enabled !== false) {
          entries.push({
            ...normalizeEntry(e),
            sourceName: lb.name
          });
        }
      });
    }
  });
  
  return entries;
});

const normalizeEntry = (e: any) => {
  let keys = e.keys;
  if (!Array.isArray(keys)) {
    keys = keys ? [keys] : [];
  }
  let secondaryKeys = e.secondary_keys;
  if (!Array.isArray(secondaryKeys)) {
    secondaryKeys = secondaryKeys ? [secondaryKeys] : [];
  }
  return {
    keys: keys.filter(Boolean),
    secondary_keys: secondaryKeys.filter(Boolean),
    content: e.content || "",
    constant: !!e.constant,
    priority: e.priority || e.insertion_order || 100
  };
};
</script>

<style scoped>
/* ===== 专属世界书 (Lorebook Section) ===== */
.lorebook-section {
  padding: 8rpx 0 100rpx 0;
}

.lore-grid {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.lore-card {
  background-color: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 24rpx;
  padding: 28rpx;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.01);
  display: flex;
  flex-direction: column;
  gap: 16rpx;
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
  color: #1c1c1e;
  background-color: rgba(0, 0, 0, 0.03);
  border: 1px solid rgba(0, 0, 0, 0.02);
  padding: 4rpx 14rpx;
  border-radius: 40rpx;
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

.lore-meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16rpx;
}

.lore-meta-item {
  font-size: 18rpx;
  font-weight: 500;
  color: #8e8e93;
  background-color: rgba(0, 0, 0, 0.01);
  padding: 2rpx 10rpx;
  border-radius: 6rpx;
}

.lore-content {
  font-size: 24rpx;
  color: #48484a;
  line-height: 1.5;
  background-color: rgba(0, 0, 0, 0.01);
  padding: 16rpx 20rpx;
  border-radius: 12rpx;
  border: 1px solid rgba(0, 0, 0, 0.01);
  word-break: break-all;
}

/* ===== 关联世界书栏目 ===== */
.bound-lorebooks-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24rpx;
}

.bound-title {
  font-size: 28rpx;
  font-weight: 700;
  color: #1c1c1e;
}

.bind-action-btn {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 10rpx 20rpx;
  background-color: #1c1c1e;
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
  background-color: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.05);
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
  color: #1c1c1e;
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
  background-color: rgba(0,0,0,0.01);
  border-radius: 16rpx;
  text-align: center;
  margin-bottom: 36rpx;
  border: 1px dashed rgba(0,0,0,0.04);
}

.bound-empty-text {
  font-size: 22rpx;
  color: #8e8e93;
}

.entries-section-header {
  margin-bottom: 24rpx;
  border-top: 1px solid rgba(0, 0, 0, 0.03);
  padding-top: 36rpx;
}

.entries-title {
  font-size: 28rpx;
  font-weight: 700;
  color: #1c1c1e;
}

.lore-source-tag {
  font-size: 20rpx;
  font-weight: 700;
  color: #007aff;
  background-color: rgba(0, 122, 255, 0.08);
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

.empty-branches {
  padding: 64rpx 0;
  display: flex;
  justify-content: center;
  text-align: center;
}

.empty-branches-text {
  font-size: 26rpx;
  color: #8e8e93;
  line-height: 1.5;
}
</style>
