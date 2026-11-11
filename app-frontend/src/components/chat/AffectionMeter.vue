<template>
  <view>
    <view class="section-title-row"><text class="section-title">{{ label }}</text><view class="affection-value-wrapper"><image class="affection-heart-icon-drawer" :src="(score ?? 0) >= 50 ? '/static/icons/meta_heart.svg' : '/static/icons/meta_heart_broken.svg'" mode="aspectFit" /><text class="affection-value">{{ score === null ? '同步中…' : `${score} / 100` }}</text></view></view>
    <view class="progress-bg" role="progressbar" :aria-valuenow="score === null ? undefined : Math.min(100, Math.max(0, score))" :aria-valuemin="0" :aria-valuemax="100" :aria-label="label"><view class="progress-bar-gradient" :style="{ width: Math.min(100, Math.max(0, score ?? 0)) + '%' }" /></view>
  </view>
</template>
<script setup lang="ts">
withDefaults(defineProps<{ score: number | null; label?: string }>(), { label: "好感度" });
</script>
<style scoped>
@import "./chatDrawer.css";
.progress-bg { margin-top: 18rpx; }
</style>
