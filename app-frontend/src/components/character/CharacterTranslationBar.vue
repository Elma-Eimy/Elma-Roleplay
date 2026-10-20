<template>
  <view class="translation-bar">
    <view class="translation-actions">
      <button :class="{ selected: language === 'original' }" @tap="$emit('language', 'original')">原文</button>
      <button v-if="available" :class="{ selected: language === 'zh' }" @tap="$emit('language', 'zh')">中文</button>
      <button :disabled="busy" @tap="$emit('translate', available)">{{ busy ? '正在翻译…' : available ? '重新翻译' : '翻译为中文' }}</button>
    </view>
    <text class="translation-note">{{ busy ? '长角色卡会分段翻译，你可以继续浏览或导入。' : '中文仅供阅读，聊天仍使用原卡。原文更新后需重新翻译。' }}</text>
    <text v-if="error" class="translation-error" role="alert">{{ error }}</text>
  </view>
</template>

<script setup lang="ts">
defineProps<{ available: boolean; busy: boolean; language: 'original' | 'zh'; error: string }>();
defineEmits<{ (event: 'language', value: 'original' | 'zh'): void; (event: 'translate', force: boolean): void }>();
</script>

<style scoped>
.translation-bar { padding: 22rpx; border: 1px solid var(--app-color-border, #e3e9e5); border-radius: 20rpx; background: var(--app-color-surface, #fff); }
.translation-actions { display: flex; flex-wrap: wrap; gap: 12rpx; }
.translation-actions button { margin: 0; padding: 8rpx 22rpx; font-size: 25rpx; line-height: 1.8; color: var(--app-color-text-secondary, #7c8983); background: transparent; }
.translation-actions button::after { border: 0; }
.translation-actions .selected { background: var(--app-color-primary-soft, #e4f1eb); color: var(--app-color-primary-strong, #4f8e7c); }
.translation-note, .translation-error { display: block; margin-top: 14rpx; font-size: 23rpx; line-height: 1.6; color: var(--app-color-text-secondary, #7c8983); }
.translation-error { color: var(--app-color-danger, #b94f56); }
</style>
