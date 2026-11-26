<template>
  <view class="page-container app-motion-enter">
    <AppSoftGlow />
    <AppPageHeader
      title="角色画册"
      eyebrow="CHARACTERS"
      subtitle="收藏每一位故事主角"
    />

    <scroll-view scroll-y class="character-scroll" @scrolltolower="loadNextPage">
      <view class="gallery-content">
        <view class="gallery-toolbar">
          <view class="gallery-toolbar-left">
            <text class="gallery-toolbar-label">你收藏的故事主角</text>
            <text v-if="personaStore.characterList.length > 0" class="gallery-toolbar-count">{{ filteredCharacters.length }}</text>
          </view>
          <view class="gallery-import-pill" role="button" @tap="goToImport">
            <text class="gallery-import-pill-text">+ 导入角色卡</text>
          </view>
        </view>

        <view v-if="personaStore.characterList.length > 0" class="gallery-search-box">
          <input
            v-model="searchQuery"
            class="gallery-search-input"
            type="text"
            confirm-type="search"
            placeholder="搜索角色名、作者或简介…"
            placeholder-class="gallery-search-placeholder"
          />
          <view v-if="searchQuery" class="gallery-search-clear" role="button" aria-label="清空搜索" @tap="searchQuery = ''">
            <text>×</text>
          </view>
        </view>

        <view v-if="isInitialLoading" class="gallery-skeleton">
          <view
            v-for="index in 6"
            :key="index"
            class="skeleton-card"
          ></view>
        </view>

        <view v-else-if="filteredCharacters.length > 0" class="character-grid">
          <view
            v-for="(char, index) in filteredCharacters"
            :key="char.id"
            class="character-card"
            :class="getCardTheme(index)"
            @tap="goToDetail(char)"
            @longpress="onCharacterLongPress(char)"
            @contextmenu.prevent="onCharacterLongPress(char)"
          >
            <view class="card-background-glow"></view>
            <AvatarImage
              class="character-art"
              :src="getAvatarUrl(char.avatar_path || '')"
            />
            <view class="card-theme-wash"></view>
            <view class="card-content-gradient"></view>

            <view class="card-copy">
              <view class="card-label">
                <view class="card-label-dot"></view>
                <text class="card-label-text">{{ char.creator ? `作者 · ${char.creator}` : "角色档案" }}</text>
              </view>
              <text class="character-name">{{ char.name || "未命名角色" }}</text>
              <text class="character-description">
                {{ plainCardText(char.description).slice(0, 120) || "这位角色还没有留下介绍。" }}
              </text>
            </view>
          </view>
        </view>

        <AppEmptyState
          v-else-if="personaStore.characterList.length > 0"
          eyebrow="画册检索"
          title="没有找到匹配的角色"
          :description="`未找到与“${searchQuery.trim()}”相关的角色。`"
        >
          <template #actions>
            <view class="empty-actions-stack">
              <view class="secondary-button" role="button" @tap="searchQuery = ''">
                <text class="secondary-button-label">清空搜索条件</text>
              </view>
            </view>
          </template>
        </AppEmptyState>

        <AppEmptyState
          v-else
          eyebrow="角色画册"
          title="还没有收藏角色"
          description="创建或导入第一位角色，让故事从一张人物卡开始。"
        >
          <template #actions>
            <view class="empty-actions-stack">
              <AppPrimaryButton label="创建角色" block @tap="goToCreate" />
              <view class="secondary-button" @tap="goToImport">
                <text class="secondary-button-label">导入角色卡</text>
              </view>
            </view>
          </template>
        </AppEmptyState>

        <view
          v-if="personaStore.isLoadingCharacters && personaStore.characterList.length > 0"
          class="pagination-state"
        >
          <view class="pagination-spinner"></view>
          <text>正在翻开下一页…</text>
        </view>

        <view
          v-else-if="!hasMore && personaStore.characterList.length > limit"
          class="pagination-state pagination-end"
        >
          <view class="pagination-line"></view>
          <text>已经看到画册末页</text>
          <view class="pagination-line"></view>
        </view>
      </view>
    </scroll-view>

    <view
      v-if="personaStore.characterList.length > 0"
      class="create-fab"
      role="button"
      aria-label="创建角色"
      @tap="goToCreate"
    >
      <image class="create-fab-icon" src="/static/icons/header_plus.svg" mode="aspectFit" />
    </view>

    <TabBar activeTab="character" />
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { plainCardText } from "@/utils/characterCard";
import { onShow } from "@dcloudio/uni-app";
import { usePersonaStore } from "@/store/personaStore";
import TabBar from "@/components/common/TabBar.vue";
import AvatarImage from "@/components/common/AvatarImage.vue";
import AppEmptyState from "@/components/common/AppEmptyState.vue";
import AppPageHeader from "@/components/common/AppPageHeader.vue";
import AppPrimaryButton from "@/components/common/AppPrimaryButton.vue";
import AppSoftGlow from "@/components/common/AppSoftGlow.vue";
import { getAvatarUrl } from "@/api/characters";
import type { CharacterSummary } from "@/api/characters";

const personaStore = usePersonaStore();
const limit = 15;
const offset = ref(0);
const hasMore = ref(true);
const searchQuery = ref("");
const cardThemes = ["theme-mint", "theme-sky", "theme-warm"];

const filteredCharacters = computed(() => {
  const keyword = searchQuery.value.trim().toLowerCase();
  if (!keyword) {
    return personaStore.characterList;
  }
  return personaStore.characterList.filter((char) => {
    const haystack = [
      char.name || "",
      char.creator || "",
      plainCardText(char.description || "")
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(keyword);
  });
});

const isInitialLoading = computed(
  () =>
    personaStore.isLoadingCharacters &&
    personaStore.characterList.length === 0
);

const loadNextPage = async () => {
  if (personaStore.isLoadingCharacters || !hasMore.value) return;
  const count = await personaStore.loadCharacters(limit, offset.value, offset.value > 0);
  if (count < limit) {
    hasMore.value = false;
  }
  offset.value += count;
};

onShow(() => {
  // #ifndef H5
  uni.hideTabBar({ animation: false });
  // #endif
  offset.value = 0;
  hasMore.value = true;
  loadNextPage();
});

const getCardTheme = (index: number) =>
  cardThemes[index % cardThemes.length];

const goToDetail = (char: CharacterSummary) => {
  uni.navigateTo({
    url: `/pages/character/detail?id=${char.id}`
  });
};

const goToCreate = () => {
  uni.navigateTo({
    url: "/pages/character/create"
  });
};

const goToImport = () => {
  uni.navigateTo({
    url: "/pages/character/create?import=1"
  });
};

const onCharacterLongPress = (char: CharacterSummary) => {
  uni.vibrateShort({ success: () => {} });
  uni.showActionSheet({
    itemList: ['编辑人设', '删除角色'],
    success: (res) => {
      if (res.tapIndex === 0) {
        uni.navigateTo({
          url: `/pages/character/create?id=${char.id}`
        });
      } else if (res.tapIndex === 1) {
        uni.showModal({
          title: '删除角色',
          content: `确定要删除"${char.name}"吗？此角色关联的所有会话故事及记忆都将无法找回。`,
          confirmColor: '#D9655D',
          cancelColor: '#7C8983',
          success: async (modalRes) => {
            if (modalRes.confirm) {
              try {
                uni.showLoading({ title: '正在删除...' });
                await personaStore.removeCharacterFromList(char.id);
                uni.hideLoading();
                uni.showToast({ title: '角色已删除', icon: 'success' });
              } catch (e) {
                uni.hideLoading();
                uni.showToast({ title: '删除失败，请重试', icon: 'none' });
                console.error('Failed to delete character', e);
              }
            }
          }
        });
      }
    }
  });
};
</script>

<style scoped>
.page-container {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100%;
  background-color: var(--app-color-background, #f7f9f7);
  overflow: hidden;
}

/* ===== 角色画册 ===== */
.character-scroll {
  position: relative;
  z-index: 1;
  flex: 1;
  height: 0;
  min-height: 0;
}

.gallery-content {
  width: 100%;
  max-width: 1180px;
  margin: 0 auto;
  padding: 28rpx var(--app-page-gutter, 36rpx) 212rpx;
  box-sizing: border-box;
}

.gallery-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20rpx;
  margin-bottom: 20rpx;
}

.gallery-toolbar-left {
  display: flex;
  align-items: center;
  gap: 12rpx;
  min-width: 0;
}

.gallery-toolbar-label {
  font-size: 24rpx;
  font-weight: 600;
  color: var(--app-color-text-secondary, #64716b);
}

.gallery-toolbar-count {
  min-width: 36rpx;
  height: 36rpx;
  padding: 0 12rpx;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999rpx;
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
  color: var(--app-color-primary-strong, #4f8e7c);
  font-size: 20rpx;
  font-weight: 700;
}

.gallery-import-pill {
  padding: 10rpx 22rpx;
  border-radius: 999rpx;
  background-color: rgba(112, 174, 155, 0.14);
  border: 1px solid rgba(112, 174, 155, 0.24);
  transition: background-color var(--app-motion-fast, 160ms) ease, transform var(--app-motion-fast, 160ms) ease;
}

.gallery-import-pill:active {
  background-color: rgba(112, 174, 155, 0.24);
  transform: scale(0.97);
}

.gallery-import-pill-text {
  font-size: 23rpx;
  font-weight: 600;
  color: var(--app-color-primary-strong, #4f8e7c);
}

.gallery-search-box {
  position: relative;
  display: flex;
  align-items: center;
  margin-bottom: 24rpx;
}

.gallery-search-input {
  width: 100%;
  height: 76rpx;
  padding: 0 68rpx 0 26rpx;
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  border-radius: 22rpx;
  background-color: rgba(255, 255, 255, 0.86);
  color: var(--app-color-text-primary, #26332e);
  font-size: 25rpx;
  box-shadow: 0 6rpx 18rpx rgba(45, 72, 62, 0.04);
  box-sizing: border-box;
}

.gallery-search-placeholder {
  color: var(--app-color-text-muted, #89958f);
}

.gallery-search-clear {
  position: absolute;
  right: 18rpx;
  width: 44rpx;
  height: 44rpx;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: rgba(38, 51, 46, 0.07);
  color: var(--app-color-text-secondary, #64716b);
  font-size: 26rpx;
  line-height: 1;
}

.character-grid,
.gallery-skeleton {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24rpx 22rpx;
}

.character-card {
  --character-glow: rgba(112, 174, 155, 0.22);
  position: relative;
  display: flex;
  height: 438rpx;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.68);
  border-radius: 34rpx;
  background-color: var(--app-color-surface, #ffffff);
  box-shadow: var(--app-shadow-soft, 0 12rpx 36rpx rgba(45, 72, 62, 0.08));
  transform: translateZ(0);
  transition:
    transform var(--app-motion-fast, 160ms) ease,
    box-shadow var(--app-motion-fast, 160ms) ease;
}

.character-card.theme-sky {
  --character-glow: rgba(139, 184, 220, 0.24);
}

.character-card.theme-warm {
  --character-glow: rgba(241, 201, 141, 0.24);
}

.character-card:active {
  box-shadow: 0 8rpx 24rpx rgba(45, 72, 62, 0.1);
  transform: scale(0.978);
}

.card-background-glow {
  position: absolute;
  top: -90rpx;
  right: -100rpx;
  width: 300rpx;
  height: 300rpx;
  border-radius: 50%;
  background: radial-gradient(circle, var(--character-glow), transparent 70%);
}

.character-art {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  background-color: var(--character-glow);
}

.card-theme-wash {
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at 88% 8%, var(--character-glow), transparent 48%);
  pointer-events: none;
}

.card-content-gradient {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    180deg,
    rgba(255, 255, 255, 0) 34%,
    rgba(255, 255, 255, 0.18) 48%,
    rgba(248, 250, 248, 0.9) 72%,
    rgba(255, 255, 255, 0.99) 100%
  );
  pointer-events: none;
}

.card-copy {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 2;
  display: flex;
  min-width: 0;
  padding: 66rpx 24rpx 24rpx;
  flex-direction: column;
}

.card-label {
  display: inline-flex;
  align-self: flex-start;
  max-width: 100%;
  height: 38rpx;
  padding: 0 12rpx;
  align-items: center;
  gap: 8rpx;
  border: 1px solid rgba(255, 255, 255, 0.72);
  border-radius: var(--app-radius-pill, 999rpx);
  background-color: rgba(255, 255, 255, 0.76);
  color: var(--app-color-primary-strong, #4f8e7c);
  font-size: 19rpx;
  font-weight: 650;
  backdrop-filter: blur(12px);
}

.card-label-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-label-dot {
  width: 8rpx;
  height: 8rpx;
  border-radius: 50%;
  background-color: var(--character-glow);
  box-shadow: 0 0 0 5rpx var(--character-glow);
}

.character-name {
  margin-top: 12rpx;
  overflow: hidden;
  color: var(--app-color-text-primary, #26332e);
  font-size: 31rpx;
  font-weight: 720;
  letter-spacing: -0.3rpx;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.character-description {
  display: -webkit-box;
  min-height: 62rpx;
  margin-top: 6rpx;
  overflow: hidden;
  color: var(--app-color-text-secondary, #7c8983);
  font-size: 22rpx;
  line-height: 1.42;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

/* ===== 悬浮创建按钮 ===== */
.create-fab {
  position: fixed;
  right: var(--app-page-gutter, 36rpx);
  bottom: calc(env(safe-area-inset-bottom, 24rpx) + 146rpx);
  z-index: 98;
  display: flex;
  width: 96rpx;
  height: 96rpx;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(255, 255, 255, 0.72);
  border-radius: 50%;
  background-color: var(--app-color-primary, #70ae9b);
  box-shadow: 0 18rpx 38rpx rgba(79, 142, 124, 0.3);
  transition: transform var(--app-motion-fast, 160ms) ease;
}

.create-fab:active {
  transform: scale(0.92);
}

.create-fab-icon {
  width: 38rpx;
  height: 38rpx;
  filter: brightness(0) invert(1);
}

/* ===== 空状态 ===== */
.empty-actions-stack {
  display: flex;
  width: 100%;
  max-width: 440rpx;
  flex-direction: column;
  gap: 16rpx;
}

.secondary-button {
  display: flex;
  width: 100%;
  height: var(--app-control-height, 88rpx);
  align-items: center;
  justify-content: center;
  border: 1px solid var(--app-color-border-strong, rgba(38, 51, 46, 0.14));
  border-radius: var(--app-radius-pill, 999rpx);
  background-color: var(--app-color-surface-soft, rgba(255, 255, 255, 0.78));
}

.secondary-button-label {
  color: var(--app-color-primary-strong, #4f8e7c);
  font-size: var(--app-font-size-body, 28rpx);
  font-weight: 650;
}

/* ===== 加载与分页 ===== */
.skeleton-card {
  height: 438rpx;
  border-radius: 34rpx;
  background: linear-gradient(
    105deg,
    rgba(255, 255, 255, 0.56) 12%,
    rgba(255, 255, 255, 0.98) 34%,
    rgba(255, 255, 255, 0.56) 58%
  );
  background-size: 220% 100%;
  animation: skeleton-shimmer 1.4s ease-in-out infinite;
}

.pagination-state {
  display: flex;
  height: 112rpx;
  align-items: center;
  justify-content: center;
  gap: 14rpx;
  color: var(--app-color-text-secondary, #7c8983);
  font-size: var(--app-font-size-caption, 22rpx);
}

.pagination-spinner {
  width: 24rpx;
  height: 24rpx;
  border: 3rpx solid var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
  border-top-color: var(--app-color-primary, #70ae9b);
  border-radius: 50%;
  animation: pagination-spin 800ms linear infinite;
}

.pagination-end {
  color: var(--app-color-text-muted, #a4aea9);
}

.pagination-line {
  width: 56rpx;
  height: 1px;
  background-color: var(--app-color-border, rgba(38, 51, 46, 0.08));
}

@keyframes skeleton-shimmer {
  from {
    background-position: 100% 0;
  }
  to {
    background-position: -120% 0;
  }
}

@keyframes pagination-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (hover: hover) {
  .character-card:hover {
    transform: translateY(-4px);
    box-shadow: 0 18px 38px rgba(45, 72, 62, 0.12);
  }
}

@media screen and (min-width: 720px) {
  .character-grid,
  .gallery-skeleton {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 24px 20px;
  }

  .character-card,
  .skeleton-card {
    height: 300px;
    border-radius: 22px;
  }
}

@media screen and (min-width: 1040px) {
  .character-grid,
  .gallery-skeleton {
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 24px 22px;
  }
}

@media screen and (min-width: 1240px) {
  .create-fab {
    right: calc((100vw - 1180px) / 2 + 28px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .character-card,
  .gallery-import-pill,
  .create-fab {
    transition: none;
  }

  .skeleton-card,
  .pagination-spinner {
    animation: none;
  }
}
</style>
