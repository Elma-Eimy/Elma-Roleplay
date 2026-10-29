<template>
  <view class="keepsake-mask" @tap="emit('close')">
    <view class="keepsake-sheet" role="dialog" aria-label="故事回忆册" @tap.stop>
      <view class="sheet-top">
        <view>
          <text class="eyebrow">OUR STORY · {{ String(cards.length).padStart(2, '0') }}</text>
          <text class="sheet-title">故事回忆册</text>
        </view>
        <button class="close-button" aria-label="关闭回忆册" @tap="emit('close')">×</button>
      </view>
      <text class="sheet-subtitle">与{{ characterName || '角色' }}，留下想再读一遍的片段。</text>
      <view class="palette-section">
        <view class="palette-heading"><text>角色配色</text><text class="palette-hint">同一角色的故事共用</text></view>
        <view class="palette-list">
          <button v-for="item in STORY_PALETTES" :key="item.id" class="palette-option"
            :class="{ selected: paletteId === item.id }" :aria-pressed="paletteId === item.id" :aria-label="item.name"
            :style="{ '--swatch': item.color, '--swatch-soft': item.soft }" @tap="emit('palette', item.id)">
            <view class="palette-swatch"><text v-if="paletteId === item.id">✓</text></view>
          </button>
        </view>
      </view>
      <view class="collection-heading"><text>珍藏片段</text><text>{{ cards.length ? '点标题可改名 · ' : '' }}{{ cards.length }} 张</text></view>
      <scroll-view scroll-y class="keepsake-scroll">
        <view v-if="!cards.length" class="empty-keepsakes">
          <view class="empty-mark">❝</view>
          <text class="empty-title">把心动的句子留在这里</text>
          <text class="empty-description">长按一条已完成的消息，选择「收藏这一刻」。</text>
          <view class="empty-rule"></view>
          <text class="empty-footnote">一次相遇，一页回忆。</text>
        </view>
        <view v-else class="keepsake-list">
          <view v-for="(card, index) in cards" :key="card.id" class="keepsake-card">
            <view class="card-meta"><text>片段 {{ String(cards.length - index).padStart(2, '0') }} · {{ card.speaker }}</text><text>{{ formatDate(card.savedAt) }}</text></view>
            <input class="card-title" :value="card.title" maxlength="40" aria-label="回忆标题"
              @blur="renameTitle(card.id, $event)" @confirm="renameTitle(card.id, $event)" />
            <text class="card-content" :class="{ expanded: expandedId === card.id }" selectable>{{ card.content }}</text>
            <view class="card-footer">
              <button class="card-action" @tap="expandedId = expandedId === card.id ? null : card.id">{{ expandedId === card.id ? '收起片段 ↑' : '展开阅读 ↓' }}</button>
              <button class="card-action remove-action" aria-label="移除这张回忆卡" @tap="emit('remove', card.id)">移除</button>
            </view>
          </view>
        </view>
      </scroll-view>
      <text class="storage-note">仅保存在本机 · 当前故事独立收藏 · 保留收藏时原文</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { STORY_PALETTES } from "@/composables/useStoryKeepsakes";
import type { StoryKeepsake, StoryPaletteId } from "@/composables/useStoryKeepsakes";
defineProps<{ cards: StoryKeepsake[]; characterName: string; paletteId: StoryPaletteId }>();
const emit = defineEmits<{
  (event: "close"): void;
  (event: "palette", id: StoryPaletteId): void;
  (event: "rename", id: string, title: string): void;
  (event: "remove", id: string): void;
}>();
const expandedId = ref<string | null>(null);
const renameTitle = (id: string, event: unknown) => {
  const input = event as { detail?: { value?: unknown }; target?: { value?: unknown } };
  const value = input.detail?.value ?? input.target?.value;
  if (typeof value === "string") emit("rename", id, value);
};
const formatDate = (date: string) => {
  const value = new Date(date);
  return Number.isNaN(value.getTime()) ? "" : `${value.getFullYear()}.${String(value.getMonth() + 1).padStart(2, "0")}.${String(value.getDate()).padStart(2, "0")}`;
};
</script>

<style scoped>
.keepsake-mask { position: fixed; inset: 0; z-index: 210; background: rgba(17, 24, 22, .48); display: flex; align-items: flex-end; justify-content: center; }
.keepsake-sheet { width: 100%; max-width: 720px; height: 86vh; height: 86dvh; box-sizing: border-box; padding: 36rpx 32rpx calc(env(safe-area-inset-bottom, 0px) + 24rpx); border-radius: 36rpx 36rpx 0 0; background: var(--app-color-background, #f7f9f7); color: var(--app-color-text-primary, #26332e); display: flex; flex-direction: column; overflow: hidden; }
.sheet-top, .palette-heading, .collection-heading, .card-meta, .card-footer { display: flex; justify-content: space-between; align-items: center; gap: 12rpx; }
.eyebrow { display: block; font-size: 19rpx; letter-spacing: 3rpx; color: var(--story-readable, var(--story-accent)); font-weight: 600; }
.sheet-title { display: block; margin-top: 12rpx; font-size: 44rpx; font-weight: 650; letter-spacing: 2rpx; }
button { margin: 0; padding: 0; border-radius: 0; background: transparent; line-height: normal; }
button::after { border: 0; }
.close-button { width: 80rpx; height: 80rpx; border-radius: 50%; font-size: 42rpx; color: var(--app-color-text-secondary); background: var(--app-color-surface); display: flex; align-items: center; justify-content: center; }
.sheet-subtitle { display: block; margin-top: 16rpx; font-size: 24rpx; color: var(--app-color-text-secondary); }
.palette-section { margin: 32rpx 0; padding: 24rpx; border: 1px solid var(--app-color-border); border-radius: 24rpx; background: var(--app-color-surface); }
.palette-heading { font-size: 25rpx; font-weight: 600; }
.palette-hint { font-size: 20rpx; color: var(--app-color-text-secondary); font-weight: 400; }
.palette-list { display: flex; gap: 8rpx; margin-top: 24rpx; }
.palette-option { flex: 1; min-width: 0; padding: 12rpx 0; border: 1px solid transparent; border-radius: 16rpx; color: var(--app-color-text-secondary); font-size: 20rpx; display: flex; flex-direction: column; align-items: center; gap: 12rpx; }
.palette-option.selected { border-color: var(--swatch); }
.palette-swatch { width: 48rpx; height: 48rpx; border-radius: 50%; background: var(--swatch); color: white; display: flex; align-items: center; justify-content: center; font-size: 25rpx; box-shadow: 0 0 0 6rpx var(--swatch-soft); }
.collection-heading { font-size: 25rpx; font-weight: 600; margin-bottom: 20rpx; }
.collection-heading > text:last-child { font-size: 22rpx; color: var(--app-color-text-secondary); font-weight: 400; }
.keepsake-scroll { flex: 1; min-height: 0; height: 0; }
.keepsake-list { display: flex; flex-direction: column; gap: 24rpx; padding-bottom: 20rpx; }
.keepsake-card { position: relative; padding: 28rpx; border: 1px solid var(--app-color-border); border-top: 4rpx solid var(--story-accent); border-radius: 6rpx 6rpx 24rpx 24rpx; background: var(--app-color-surface); }
.card-meta { font-size: 19rpx; color: var(--app-color-text-secondary); }
.card-meta > text:first-child { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-title { margin: 22rpx 0 18rpx; height: 48rpx; font-size: 31rpx; font-weight: 600; color: var(--app-color-text-primary); }
.card-content { display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; white-space: pre-wrap; font-size: 27rpx; line-height: 1.85; color: var(--app-color-text-primary); }
.card-content.expanded { display: block; }
.card-footer { border-top: 1px solid var(--app-color-border); margin-top: 24rpx; padding-top: 12rpx; }
.card-action { font-size: 22rpx; color: var(--story-readable, var(--story-accent)); min-height: 72rpx; display: flex; align-items: center; }
.remove-action { color: var(--app-color-text-secondary); min-width: 72rpx; justify-content: flex-end; }
.empty-keepsakes { text-align: center; padding: 30rpx 12rpx; }
.empty-mark { color: var(--story-readable, var(--story-accent)); font-size: 88rpx; font-family: Georgia, serif; }
.empty-title { display: block; font-size: 29rpx; font-weight: 600; }
.empty-description { display: block; font-size: 23rpx; color: var(--app-color-text-secondary); line-height: 1.8; margin-top: 16rpx; }
.empty-rule { width: 56rpx; height: 2rpx; background: var(--story-mist); margin: 32rpx auto 20rpx; }
.empty-footnote { color: var(--app-color-text-secondary); font-size: 21rpx; letter-spacing: 4rpx; }
.storage-note { text-align: center; padding-top: 20rpx; font-size: 19rpx; color: var(--app-color-text-secondary); }
@media (min-width: 900px) { .keepsake-mask { align-items: center; padding: 24px; } .keepsake-sheet { height: 85vh; max-height: 900px; border-radius: 24px; } }
</style>
